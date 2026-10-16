# XR1710G / XG2010G chainloader — 基于 U-Boot 的二级引导与 HTTP 恢复


本项目是 **U-Boot 2026.07 分支** 针对 Airoha AN7581（ARM64）路由器的改造版，
采用 **chainloader（二级引导）方案**，适配 XR1710G（W1700K / W1701K）与 XG2010G：

- 一个写入原厂 NAND **偏移 `0x600000`（6 MiB）处、大小 1 MiB** 的 chainloader 槽位镜像；
- 槽位内嵌的第二级 U-Boot 本体，负责从 UBI `system` 分区加载并启动 OpenWrt；
- 一个内置于二级 U-Boot 的 **HTTP 恢复 Web 服务**（固定 `192.168.0.1/24`），用于刷写固件、备份分区。

方案核心原则：**保留原厂前 6 MiB 分区**（`bootloader` 2 MiB + `uenv` 2 MiB + `dsd` 2 MiB）不动，
只在 6 MiB 之后写入 1 MiB chainloader，因此不需要擦除或重建原厂引导区。

---

## 1. 项目用途

| 维度 | 说明 |
|---|---|
| 目标设备 | XR1710G（W1700K / W1701K）、XG2010G（Airoha AN7581，ARM64） |
| 引导架构 | 三级串联：原厂 ECNT/AXON U-Boot（NAND 0x0，**不可改**）→ chainloader 槽位（NAND 0x600000，1 MiB，双入口）→ 内嵌二级 U-Boot（TEXT_BASE `0x81E00000`） |
| 刷机入口 | 仅 TTL + TFTP 写入 chainloader 一次；之后所有固件/chainloader 升级均走 HTTP 恢复网页 |
| 恢复能力 | HTTP Recovery Web UI：上传 OpenWrt `*-sysupgrade.itb`（`firmware` 目标）、上传 chainloader（`uboot` 目标）；只读备份下载 MTD / UBI 分区 |
| 与 uboot-an758x 区别 | 本项目**保留**原厂前 6 MiB、chainloader 写在 0x600000；uboot-an758x 从 0x0 重写引导区并重建 UBI |

适用的关键场景：在不动原厂引导区的前提下，给原厂机型刷入第三方 U-Boot + OpenWrt，
并通过网页化的恢复模式降低后续维护门槛（无需再拆机 TTL）。

- **硬性守卫**：若 `u-boot.bin` 内嵌的 commit 与当前 `git HEAD` 不一致，脚本直接报错退出
  （避免把错误版本打包发布）；槽位体积超过 1 MiB（`0x100000`）也会报错退出。


### 2. 首次刷入 chainloader（TTL + TFTP）

完整步骤见 [docs/flashing-xr1710g.md](docs/flashing-xr1710g.md) 与
[docs/flashing-xg2010g.md](docs/flashing-xg2010g.md)。要点：

1. 拆机连接 TTL（3.3V，115200 8N1），网线接 10GbE 口，PC 设静态 IP `192.168.0.10`；
2. PC 启动 TFTP 服务器，把 `xr1710g-chainloader-slot.bin` 放在其根目录；
3. 上电打断进入**原厂 U-Boot 命令行**（提示符 `ECNT>`）；
4. 在**原厂**提示符下加载并写入（以下命令来自刷机教程，且只能在该提示符执行）：

```sh
setenv serverip 192.168.0.10
setenv ipaddr 192.168.0.1
tftpboot 0x81800000 xr1710g-chainloader-slot.bin

setenv one "flash read 0x600000 0x100000 \$loadaddr"
setenv two "; bootm"
setenv bootcmd "$one$two"
saveenv
flash erase 0x600000 0x100000
flash write 0x600000 0x100000 0x81800000
reset
```

> ⚠️ 上面的 `saveenv` / `flash` 命令**只能在原厂 `ECNT>` 提示符**下执行。
> 详见 §6 常见问题：`uenv` 分区被原厂与二级 U-Boot 共用，在 chainloader 里 `saveenv` 会
> 覆盖原厂环境导致无法启动。

### 3 HTTP 恢复模式刷机 / 升级

上电3秒后按住 reset ，直到lede灯变色闪动，不可按住 reset在上电。进入恢复模式后：

- PC 网卡设静态 `192.168.0.10 / 255.255.255.0`（网关留空），或 DHCP 自动获取；
- 浏览器打开 <http://192.168.0.1>；
- 上传 OpenWrt `*-sysupgrade.itb` 到 **`firmware`** 目标；
- 日后升级 chainloader 本体，上传 `xr1710g-chainloader-*-slot.bin` 到 **`uboot`** 目标。

### 4 备份分区（只读下载）

恢复页面底部的“备份 / Backup”卡片对应以下真实端点（也可直接 `curl` 验证）：

```sh
# 列出所有 MTD 分区与 UBI 卷
curl http://192.168.0.1/api/storage
# 登记一次 MTD 备份（返回 {"id","kind","name","size"}）
curl http://192.168.0.1/api/backup/mtd/spi-nand0
# 按段流式下载（单段上限 256 KiB）
curl "http://192.168.0.1/api/download/<id>/0/262144" -o spi-nand0.part1.bin
```

MTD 备份保留物理偏移（遇坏块填 `0xff`），可直接 `nandwrite` 原样写回；
UBI 备份为逻辑字节，对应 `ubi write` 输入语义。


## 5. 关键配置说明

### 5.1 机型 defconfig（`configs/`）

| 文件 | 机型 |
|---|---|
| `configs/xr1710g_defconfig` | XR1710G / W1700K / W1701K |
| `configs/xg2010g_defconfig` | XG2010G |

关键开关（以 `xr1710g_defconfig` 为准，均真实存在于文件中）：

- `CONFIG_ARM=y`、`CONFIG_ARCH_AIROHA=y`、`CONFIG_TARGET_AN7581=y`
- `CONFIG_TEXT_BASE=0x81E00000`（二级 U-Boot 加载基址）
- `CONFIG_BOOTDELAY=1`（新 env 默认值；已保存 `bootdelay=3` 的设备用 `setenv bootdelay 1; saveenv`）
- `CONFIG_MTD_UBI_FASTMAP=y` + `CONFIG_MTD_UBI_FASTMAP_AUTOCONVERT=1`：
  把每次启动的 UBI attach 从“全盘扫描 ~3500 个 PEB”降为“读几个 anchor PEB”；
  `AUTOCONVERT` 会在首次 attach 时为没有 fastmap 的设备补写，已出厂设备无需重新格式化。
- `CONFIG_HTTPD_RECOVERY=y`、`CONFIG_NET_LWIP=y`：HTTP 恢复服务与 lwIP 网络栈。
- `CONFIG_ENV_IS_IN_MTD=y`、`CONFIG_ENV_MTD_DEV="uenv"`、`CONFIG_ENV_OFFSET=0x0`：
  env 存放在**原厂 `uenv` 分区**，这是二级 U-Boot 与原厂 U-Boot 共享的分区（务必牢记 §6 警告）。

### 5.2 chainloader 槽位布局

| 偏移 | 内容 | Magic |
|---|---|---|
| `0x600000` | legacy bootm shim（`chainloader-prefix-shim.uImage`） | `27 05 19 56`（IH_MAGIC） |
| `0x602100` | chainloader FIT（内嵌 DTB + shim + 二级 U-Boot） | `d0 0d fe ed`（FDT_MAGIC） |

槽位上限 `RECOVERY_MAX_UBOOT_SIZE = 1 MiB`；本机最近产物约 914 KB，余量约 120 KB。

### 5.3 二级 U-Boot 启动环境变量（`board/airoha/an7581/xr1710g.env`）

```sh
bootcmd=run boot_ubi || http_recovery
boot_ubi=ubi part system && run boot_production
boot_production=run ubi_read_production && bootm ${loadaddr}#${bootconf}
ubi_read_production=ubi read ${loadaddr} fit
recovery_addr=0x81800000
recovery_ubi_part=system
uboot_ofs=0x600000
recovery_size_uboot=0x100000
```

### 5.4 DHCP 与端口策略

- 恢复模式 DHCP 池默认 `192.168.0.2 – 192.168.0.50`（首个客户端仍拿 `.2` 以兼容旧文档）；
  可用 env `recovery_dhcp_start` / `recovery_dhcp_end` 放宽。
- `recovery_port` 决定只在哪些口回 DHCP（安全需求，保留）：`wan`→fport 2、
  `10g/lan1/4`→fport 4、`1g/lan2/lan3/1`→fport 1、`auto`→1 或 4。
  被端口策略丢弃的包现在会限流打印日志（不再静默）。

---

## 6. 常见问题（FAQ）

- **打断超时，看到 `T T T...`**：打断窗口错过，重新上电并提前按键。
- **TFTP 超时**：检查 PC IP（192.168.0.10）、TFTP 服务器已启动、文件名无误、网线插在 10GbE 口。
- **`Wrong Image Format`**：镜像不对。确认使用的是 `xr1710g-chainloader-*-slot.bin`
  （文件名带版本号与构建时间），不要刷 `u-boot.bin` / `u-boot.img` 或裸 `.itb`。
- **恢复页面打不开**：确认按住 reset 上电进入恢复、PC 用 DHCP 或静态 `192.168.0.10`、
  访问 <http://192.168.0.1>。
- **串口停在 `Unknown command 'flash'` 并自动重启（boot loop）**：旧 `uenv` 里残留的原厂
  配方 `flash read ...; bootm` 被二级 U-Boot 沿用，而 `flash` 命令在本 U-Boot 已不存在。
  当前 `xr1710g_rfb.c` 会在启动时自动改写这类旧配方，重刷后无需手工处理。
  临时绕过（仅内存，不要 `saveenv`）：`setenv bootcmd 'run boot_ubi || http_recovery'; boot`。
- **⚠️ 绝对不要在二级 chainloader U-Boot 里执行 `saveenv` 或 `env default -a`**：
  `uenv` 是**原厂 U-Boot 的 env 分区**，二级 U-Boot 只是共用读取。一旦 `saveenv`，
  原厂环境被整套替换成 chainloader 的环境，原厂 U-Boot 再启动就找不到自己的启动配方。
- **原厂 U-Boot 停在 `ECNT>`，日志报 `Unknown command 'ubi'` / `http_recovery'`**：
  说明二级 U-Boot 误执行过 `saveenv`，原厂 `uenv` 已被替换。在原厂命令行恢复：
  `setenv bootcmd 'flash read 0x600000 0x100000 0x81800000; bootm 0x81800000'; saveenv`。
- **客户端长时间拿不到 IP（需手动设 IP）**：历史上是“单一固定地址 + 一律 NAK”所致，
  现已改为按 MAC 的租约表；若仍拿不到，先排查 `recovery_port` 是否被设成 `lan1`/`10g`
  而 PC 实际插在 1G 口。手动设 IP 时应避开地址池（例如 `192.168.0.100`）。
- **本机没有 aarch64 交叉工具链，所有 C 改动未经编译验证**：请在 CI / 有工具链的环境构建
  （详见 §7 已知限制）。

---

## 7. 已知限制

- **无交叉工具链验证**：作者机器没有 aarch64 工具链，本仓库的 C 改动未在本地编译验证过；
  需在 GitHub Actions（`build.yml`，`workflow_dispatch`）或有工具链的环境中构建确认。
- **UBI 写入缺少回读校验**：raw MTD 写入有逐擦除块校验（`recovery_mtd_verify_write`），
  但 `recovery_write_ubi_target` 写完后仅做 `ubi_check_volume()`，未做回读比对。
  该改动落在写路径、出错即变砖，本次未盲改。
- **目标有限**：chainloader 方案只有 `firmware`（UBI fit 卷）与 `uboot`（raw slot）两个上传目标，
  没有 BL2 / FIP / 板级数据独立目标，也没有 env 的 HTTP 逐项读写（完全重建会重置 env）。
- **DHCP 双路径**：raw 兜底 vs UDP PCB 双收包路径并存，raw 路径是唯一实际生效的；
  改为单路径需确认 lwIP 在广播场景下的收包行为，风险不低，暂未改。
- **布局探测结果未缓存**：`env` 本身在 UBI 内，探测函数存在循环依赖，未做持久化缓存。
- **原厂一级 `bootcmd` 长度**：原厂默认 `flash read 0x602100 0x4000000`（读 64 MiB），
  实际只需 ~1 MiB；只能手工在 `ECNT>` 提示符下改成 `0x100000`，本项目不自动改写。

---

## 交流与支持 / Community

- **QQ 群：571318173**（刷机、构建、分享）
- GitHub 仓库与 Release：<https://github.com/naoki66/Gemtek-brightspeed-chainloader>
  （Release 每机型仅一个 `*-slot.bin` 文件）

## 文档索引 / Docs

- [docs/flashing-xr1710g.md](docs/flashing-xr1710g.md) — XR1710G（W1700K / W1701K）TTL 刷机教程
- [docs/flashing-xg2010g.md](docs/flashing-xg2010g.md) — XG2010G 刷机教程
- [BOOT-AND-RECOVERY-OPTIMIZATION.md](BOOT-AND-RECOVERY-OPTIMIZATION.md) — 引导链路、启动速度、恢复/备份、DHCP 优化与设计权衡

---

## 捐赠 / Donate

如果您觉得对您有帮助，请我喝杯咖啡吧，让我更有动力持续更新。

<img src="./c6ea388c976395326514814f80d512d5.png" width="420" alt="Donate / 捐赠二维码">
