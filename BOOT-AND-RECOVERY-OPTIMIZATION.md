# 引导链路与启动/恢复：现状、约束与坑

本文描述**当前生效的状态与约束**，并横向对照 `D:\GitData\uboot-an758x`
（U-Boot **2026.10**，TF-A BL2/FIP 原生方案）。

---

## 0. 维护约定（改这份文档前先看）

1. **只写"现状"，不写轮次流水。** 每节回答"现在是什么样 / 为什么必须这样 / 怎么核对"。
   某次修复的 commit 号、CI run 号、当时的现象日志**不进正文**。
2. **历史坑统一归档到 §10**，固定三段式：`症状 → 根因 → 现约定`。
   新增一轮修复时：**改对应章节的现状值**，再往 §10 追加一条，**不要新增章节**。
3. **数值表格旁边标来源。** 体积/行数这类数字会随每次提交变化，
   统一在 §6.1 用版本串标注；其它地方不重复写死具体字节数，改为引用 §6.1。
4. **凡本文给出的寄存器/地址/掩码，都注明出处文件**，便于代码变动后回查。
5. 决策类章节（§7 扩容、§8 版本同步）写**结论 + 不做的理由 + 什么时候该翻案**，
   避免每次重新论证一遍。
6. **只能在 `ECNT>`（厂商 U-Boot）下手工执行的刷机期步骤**一律写进
   `docs/flashing-xr1710g.md` / `docs/flashing-xg2010g.md`，本文只留一句指针，不重复内容。
   （当前适用：缩短厂商一级 `bootcmd` 的读取长度 —— 刷机教程 §6。）

### 0.1 事实快照

| 项 | 值 | 出处 |
|---|---|---|
| 本项目 U-Boot | **2026.07** | `Makefile:3-4` |
| 对照树 an758x | **2026.10**（领先 1 个发布） | `uboot-an758x/Makefile:4` |
| 板级文件 | `board/airoha/an7581/xr1710g_rfb.c`（960 行）/ `xg2010g_rfb.c`（906 行） | — |
| env 后端 | **MTD `uenv`**（`CONFIG_ENV_IS_IN_MTD=y`，**不是** UBI） | `configs/xr1710g_defconfig:47-50` |
| UBI 布局 | 只剩 1 个：`{ "2.0", "system" }` | `xr1710g_rfb.c:79-81` |
| chainloader 槽位上限 | **1 MiB**（`0x100000`） | `RECOVERY_MAX_UBOOT_SIZE`、`MAX_SLOT_SIZE` |
| 两个 defconfig | 已同构（`BOOTDELAY=1` + `FASTMAP`） | §2.2 |
| `recovery_port` 默认 | 未设 = auto/dual = **1G + 10G + WAN 全部服务** | §4.2 |
| 网口拓扑 | lan2 = GDM4+PHY5+`eth_pcs`；wan = GDM2+PHY8+`pon_pcs` | §5.1 |
| 恢复服务 | `net/lwip/httpd_recovery.c`（4,272 行）+ 内置 DHCP | — |
| 网卡驱动 | `drivers/net/airoha_eth.c`（6,759 行） | — |
| 恢复页 | `lib/lwip/httpd/htdocs/index.html`（1,348 行 / 68,805 B）→ 生成物 `fsdata_xr1710g.c`（374,132 B） | §6.3 |

---

## 1. 引导链路

### 1.1 本项目：三级串联，前两级不受我们控制

```
上电
 └─ 厂商 ECNT/AXON U-Boot 2014.04（NAND 0x0，不可改）
     bootcmd = flash read 0x602100 0x4000000 $loadaddr; bootm     ← 默认读 64 MiB
 └─ chainloader slot 镜像（NAND 0x600000，分区 1 MiB，双入口）
     0x000000  legacy bootm shim      IH_MAGIC  27 05 19 56   （ih_size 4,248，占 4,312 B）
     0x002100  chainloader FIT        FDT_MAGIC d0 0d fe ed
 └─ FIT 内嵌二级 U-Boot 本体           CONFIG_TEXT_BASE=0x81E00000
```

二级 U-Boot 内部（`board/airoha/an7581/xr1710g_rfb.c` + `xr1710g.env`）：

```
env 从 **MTD `uenv` 分区**读（CONFIG_ENV_IS_IN_MTD=y / CONFIG_ENV_MTD_DEV="uenv" /
  CONFIG_ENV_OFFSET=0x0）。这是二级 U-Boot 与厂商 U-Boot **共享**的分区；
  xr1710g_uenv_consume_recovery_trigger() 从里面读走一次性恢复标志。
board_late_init()                          xr1710g_rfb.c:821
  ├─ 清 legacy fdt_high / 归一化 bootargs   :886 / :896
  ├─ xr1710g_sync_runtime_ethaddrs()        :732  读 vendor DSD → 运行时 MAC
  ├─ xr1710g_detect_ubi_part()              :570  只有 1 个布局："2.0" → "system"
  ├─ xr1710g_sync_factory_part()            :613  DSD→factory 卷比对，不同才写回
  └─ uenv 一次性标志 或 reset 键 → run_http_recovery()（阻塞）
autoboot
  bootcmd            = run boot_ubi || http_recovery
  boot_ubi           = ubi part system && run boot_production
  boot_production    = run ubi_read_production && bootm ${loadaddr}#${bootconf}
  ubi_read_production= ubi read ${loadaddr} fit
```

### 1.2 an758x：TF-A 标准两级

```
BootROM → BL2 (preloader.bin) → BL31 + U-Boot (bl31-u-boot.fip)
```

env 来自 `include/env/airoha/an758x-ubi.env`（`CONFIG_AIROHA_UBI_ENV`）：

```
bootcmd             = run boot_ubi
boot_ubi            = run boot_production ; echo ... ; run boot_recovery
boot_production     = led $bootled_status on ; run ubi_read_production && bootm $loadaddr
ubi_read_production = run ubi_mount && ubi read $loadaddr fit && iminfo $loadaddr && run ubi_prepare_rootfs
```

### 1.3 差异一览

| 维度 | 本项目 | an758x |
|---|---|---|
| 一级引导 | 厂商 ECNT `bootm` + chainloader FIT | TF-A BL2 → FIP |
| 核心版本 | 2026.07 | 2026.10 |
| env 后端 | **MTD `uenv`** | UBI（`CONFIG_AIROHA_UBI_ENV`） |
| UBI fastmap | ✅ `FASTMAP` + `AUTOCONVERT`（两机型） | ✅ 同左 |
| bootdelay | 1（两机型） | 3 + `AUTOBOOT_MENU_SHOW`（还会显示菜单，更慢） |
| 一级读取量 | **64 MiB**（厂商默认；slot 实际只 ~1 MiB） | 不适用 |
| 启动期 UBI attach | env 1 次（MTD）；`system` attach 1 次 | 1 次 |
| 启动期写 flash | `factory` 同步（不一致才写） | 无 |
| 恢复服务 | `httpd_recovery.c`（4,272 行）+ 内置 DHCP | `httpd.c`（1882 行）+ `httpd-dhcp.c`（367 行） |
| 布局选择 | ❌ 单一 `system`（多视图已移除） | ❌ 单一布局 |
| 软件触发恢复 | ✅ `recovery_trigger` env（LuCI 下发，走 `uenv`） | ❌ 只有按键 |
| 备份下载 | ✅ `/api/storage` + `/api/download`（§3） | ✅ `/api/download` + 存储目录 |
| UBI 写入回读校验 | ❌ 无（只有 raw MTD 逐块校验） | ✅ `ubi_verify_*` + `verifyaddr=loadaddr-filesize` |
| 链路 flap | 默认关闭（可 `recovery_link_flap=1` 打开） | 完全没有 |

**本项目相对 an758x 的既有优势**（保留不动）：`recovery_trigger` 软件触发、
四色彩虹呼吸灯效（an758x 的 `httpd-led.c` 是反向移植自本项目）、16 条租约的 DHCP 服务。

---

## 2. 启动速度

### 2.1 瓶颈排序与现状

| # | 位置 | 开销 | 现状 |
|---|---|---|---|
| 1 | 厂商 `flash read 0x602100 0x4000000` | 读 64 MiB，实际只需 ~1 MiB | 厂商 env，本项目不改写；手工改法见 `docs/flashing-{xr1710g,xg2010g}.md` §6 |
| 2 | `ubi read fit` | 整个 fit 卷搬进 RAM | 不可避免（`bootm` 需要完整 ITB） |
| 3 | UBI attach 全盘扫描 | `0x1B700000 / 128 KiB` ≈ **3500 个 PEB** | ✅ fastmap（两机型） |
| 4 | bootdelay | 空等 | ✅ 1 s（两机型） |
| 5 | `xr1710g_sync_factory_part()` | 两次 24 KiB 读 + DSD 读，10 ms 量级 | 非瓶颈；保留"可能写 flash"的面 |

### 2.2 已生效的设置（两个机型同构）

`configs/xr1710g_defconfig` 与 `configs/xg2010g_defconfig`：

```
CONFIG_BOOTDELAY=1
CONFIG_MTD_UBI_FASTMAP=y
CONFIG_MTD_UBI_FASTMAP_AUTOCONVERT=1
```

- fastmap 把每次启动的 UBI attach 从"扫 3500 个 PEB"降为"读几个 anchor PEB"。
- `AUTOCONVERT=1` 会在**首次** attach 时给没有 fastmap 的设备补写一份 → **已出厂设备不用重新格式化**。
  首次那次 attach 会比之后慢，属预期，不是回归。
- **两个机型的 `.env` 都不定义 `bootdelay`**，所以生效值就是编译进固件的 `CONFIG_BOOTDELAY` → 改 defconfig 即可。
  真机上 `printenv bootdelay` 仍为 3 说明该值被 `saveenv` 持久化过，需覆盖一次。
  ⚠️ 但**二级 U-Boot 里 `saveenv` 会覆盖原厂 `uenv`**（见 §10）——不要只为 bootdelay 去 `saveenv`。
- 按键/串口打断**不受 bootdelay 影响**：恢复键是在 `board_late_init()`（autoboot 之前）采样的。

> 厂商一级 `bootcmd` 的读取长度（`0x4000000` → `0x100000`）是**可选的刷机期优化**，
> 只能在 `ECNT>` 提示符下手工执行，所以写在**刷机教程**里：
> `docs/flashing-xr1710g.md` / `docs/flashing-xg2010g.md` §6。本文不再重复。

### 2.3 不做的事（附原因）

- **把布局探测结果缓存进 env**：布局只剩 1 个，收益基本消失。
- **自动改写厂商 env**：只能在 ECNT 提示符下手工做，写进刷机教程即可。
- **启动路径加 `iminfo` 校验**：an758x 的 `ubi_read_production` 带它，校验完整但多花一次全镜像哈希；本项目不加。

---

## 3. 恢复与备份能力

### 3.1 端点

| 端点 | 作用 |
|---|---|
| `GET /api/storage` | JSON 列出所有 **MTD 分区**（`bootloader / uenv / dsd / chainloader / system / reserved_bmt`）与 **UBI 卷**（`fit` / `factory` / …），带字节大小 |
| `GET /api/backup/mtd/<name>` | 登记一次备份，返回 `{"id","kind","name","size"}` |
| `GET /api/download/<id>/<offset>/<length>` | 流式返回该段原始字节（`Content-Disposition: <name>.bin`） |
| `GET /api/about` | 版本/机型信息（横幅同源） |

### 3.2 实现要点（改这块前必读）

- **只列整个 MTD 分区**：UBI 卷是 `system` 分区内部的逻辑层，raw 备份 `system` 已包含全部卷；
  同时提供两者会诱导页面把几百 MiB 拉两遍，且卷 dump 不是 `mtd write` 能写回的形式。
- **MTD 备份保留物理偏移**：遇坏块填 `0xff` 而**不跳过**，这样 dump 可以直接 `nandwrite` 原样写回，
  长度恒等于分区大小。（an758x 的 `fs_read_custom()` 是同一套约定。）
- **流式，不占内存**：`file->data = NULL` + `LWIP_HTTPD_DYNAMIC_FILE_READ`，
  lwIP 通过 `fs_read_custom()` 分块拉取 → 备份 439 MiB 的 `system` 不需要等大 RAM 缓冲。
- **安全边界**：
  - 名字只允许 `[A-Za-z0-9_.-]`、长度 < 32（`RECOVERY_PARTITION_NAME_LEN`）→ JSON 无需转义，且堵掉路径穿越；
  - 单段上限 256 KiB（`RECOVERY_BACKUP_SEGMENT`），且 `offset + length` 不得超过登记的 `size`；
  - `id` 必须等于当前登记的备份 id，且同时只允许一个下载在飞；
  - 擦写任务进行中（`prog_phase` 1/2）直接拒绝，避免与写路径抢 flash。
- **配套**：`lib/lwip/u-boot/lwipopts.h` 打开 `LWIP_HTTPD_DYNAMIC_FILE_READ=1` 与
  `LWIP_HTTPD_FILE_EXTENSION=1`（后者给 `struct fs_file` 加私有指针字段）。
  `fs_open_custom()` 开头**必须**强制 `file->pextension = NULL`——lwIP 的 `fs_open()`
  对 custom file 不清这个字段，不清会读到上次下载留下的野指针。
- 页面改动后**必须重新生成 `fsdata`**，见 §6.3。

### 3.3 不做的事（附原因）

- **UBI 写入回读校验**。本项目 raw MTD 写入有逐擦除块校验（`recovery_mtd_verify_write()`），
  但 UBI 写入路径写完只做 `ubi_check_volume()`，没有回读比对。
  an758x 的做法是 `setexpr verifyaddr $loadaddr - $filesize`，把回读缓冲放在镜像**正下方**
  （放到上方会在 512 MiB 板上覆盖运行中的 U-Boot 自己）。
  本项目恢复缓冲在 `gd->ram_base + 0x10000000`，回读区同样应取 `recovery_addr - filesize`。
  这条落在**写路径**上，出错就是变砖，迄今没有盲改。
- **BL2 / FIP / 板级数据独立目标**：本 chainloader 方案只有"firmware（UBI `fit` 卷）"
  和 "uboot（raw slot）"两个目标，语义上不需要 BL2/FIP。
- **env 的 HTTP 逐项读写**：an758x 有 `HTTP_JOB_ENV`；本项目"完全重建"会重置 env，暂无逐项编辑入口。

---

## 4. DHCP 与端口策略

对照 `D:\GitData\uboot-an758x\net\lwip\httpd-dhcp.c`（367 行，独立文件，UP PCB 绑 67）
与本项目 `net/lwip/httpd_recovery.c` 的 DHCP 段。

### 4.1 租约模型（当前实现）

| 项 | 值 | 出处 |
|---|---|---|
| 租约条数 | **16** | `RECOVERY_DHCP_MAX_LEASES` |
| 地址池 | `192.168.0.2 – 192.168.0.50`（首客户端仍拿 `.2`） | env `recovery_dhcp_start` / `recovery_dhcp_end` |
| OFFER 保留 | 60 s 未跟 REQUEST 自动回收 | `RECOVERY_DHCP_OFFER_HOLD_MS` |
| ACK 租期 | 24 h | `RECOVERY_DHCP_LEASE_SECS = 86400` |
| `BOOTREPLY.secs` | **0**（RFC 2131 Table 3：`secs` 是客户端字段） | — |
| `reply->flags` | 强制置 `0x8000`（广播位） | `httpd_recovery.c:1310` |
| DHCPRELEASE | 释放租约 | — |
| 分配顺序 | 按 MAC 找已有租约 → 按 option 50 → 池内任一空闲（跳过服务器自身） | `recovery_dhcp_alloc_lease()` |
| REQUEST 判定 | 池内 → ACK（续租/重分配）；池外 → NAK（让客户端回 DISCOVER，标准行为）；无 option 50 也无租约 → 直接分配 | `recovery_dhcp_resolve_request()` |

**收包路径是两条**：UDP PCB 绑 67 + `net_lwip_dispatch_recovery_dhcp()` raw 兜底。
`net_lwip_rx()` 里 raw 命中就 `continue`，包**不会**进 `netif->input()` ——
也就是说 hook 一注册，绑 67 的 PCB 实质是死路，真正生效的是 raw 解析。
好处是 raw 是逐帧同步的：处理某帧时 `eth->last_rx_fport` **就是该帧自己的入端口**（诊断依赖这一点）。

### 4.2 `recovery_port` 语义

| `recovery_port` | 1G（lan2/lan3） | 10G（lan1） | WAN |
|---|---|---|---|
| 未设 / `auto` / `both` / `dual` | ✅ | ✅ | ✅ |
| `1` / `1g` / `lan2` / `lan3` | ✅ | ✗ | ✗（PHY8 掉电，GDM2 走 DROP） |
| `4` / `10g` / `lan1` | ✗ | ✅ | ✗（同上） |
| `2` / `wan` | ✗ | ✗ | ✅ |

fport 编号：`1G → 1`、`WAN → 2`、`10G → 4`（`airoha_rx_sport_to_fport()`：
sport `1/2/4` 原样映射，GDM4 的 `0x18` → 4，其余 → 兜底）。

> ⚠️ **两套命名在 `lan2` 上重合，别混用：**
> - **`recovery_port` 的词表**（本项目自定）：`lan1`/`10g`/`4` = 10G 面板口，
>   `lan2`/`lan3`/`1g`/`1` = 1G 交换机口。
> - **内核 DTS 的 netdev 名**：GDM4 + PHY5（**就是那个 10G 面板口**）叫 **`lan2`**，
>   GDM2 + PHY8 叫 `wan`。
>
> 所以"内核 `lan2`" = "`recovery_port=lan1`"，是**同一个口**。本文按语境分别使用；
> §5.1 的表用的是**内核名**，§4.2 的 `recovery_port` 列用的是**词表值**。

判定函数只有一对，**不要再去写零散的 `port_is_wan()` 分支**：

```c
airoha_recovery_wan_service_enabled() = port_is_wan() || dual_service_enabled()
```

它同时门控：DHCP 是否接受 fport 2、PHY8 是否上电、GDM2 是否转发到 PPE1、
广播是否镜像到 fport 2、以及 WAN 的 PCS 是否拉起（§5）。

`airoha_gdm4_loopback_enabled()` 在 WAN 被服务时**返回 false**：
WAN 服务优先于那个"把 GDM2 挪作 GDM4 用"的实验；要跑实验就 `recovery_port=lan2` 把 GDM2 让出来。

### 4.3 三个"拿不到 IP"的历史坑（根因归档）

**坑 ①  单一固定地址 + 一律 NAK（协议层）**
早期只发 `192.168.0.2` 且所有不匹配的 REQUEST 一律 NAK。
Windows 记住别网段租约后会先发 `DHCPREQUEST`(init-reboot)，option 50 不是 `.2` → NAK；
连续几次后放弃并退回 `169.254.x.x`。两台主机同时来还会抢同一个 `.2`，
ARP 重复地址检测同样把后者踢到 APIPA。外观都是"必须手动设 IP"。
→ **现约定**：16 条租约表 + 可配置池（§4.1）。

**坑 ②  端口策略静默丢包**
PC 插的口不在允许集合里时**一行日志都没有**；且 `airoha_rx_sport_to_recovery_fport()`
对交换机上报的未映射 SPORT 只在 `auto`/`1g` 时兜底成 fport 1 ——
一旦有人把 `recovery_port` 设成 `lan1`(10G) 而 PC 插在 1G 口，就永远不回。
→ **现约定**：被过滤时限流打印
`DHCP: request ignored by port policy (recovery_port=..., rx fport=N)`，
并新增 `airoha_recovery_last_rx_fport()`。端口策略本身保留（真实安全需求）。

**坑 ③  交换机 flood map 把 CPU 发出的广播全部丢掉（数据面根因）**
`SWITCH_MFC` 的三个 flood 端口图被写成 **CPU 端口位**（只有 `BIT(6)`），
而前面板端口的 `PORT_MATRIX` 是 `cpu_port_mask`（只有端口 6）。
交换机对被泛洪帧实际投递的端口 = **flood 图 ∩ 入端口矩阵**，于是：

- 客户端广播从端口 1 进来：`{6} ∩ {6}` = `{6}` → 送到 CPU（日志里有 DISCOVER）；
- 服务器广播从 CPU 进来：`{6} ∩ {0..5}` = **空集** → 在交换机内部被丢弃，永远到不了前面板。

⇒ 凡是 CPU 发起的泛洪帧全部黑洞（DHCP OFFER/ACK、ARP 请求、未知单播）。
"手动设静态 IP 能用"完全吻合：静态地址走普通**单播**，按 FDB 转发，不经 flood 图。
客户端既不 REQUEST 也不 DHCPDECLINE，因为两者都要求它先收到 OFFER。

→ **现约定**：`airoha_switch_recovery_runtime_init()` 里

```c
u32 cpu_port_mask  = BIT(AIROHA_RECOVERY_SWITCH_CPU_PORT);
u32 flood_port_mask = GENMASK(7, 0);          /* 必须比矩阵更宽，由矩阵负责限制 */
```

**必须包含 CPU 端口**：前面板矩阵是 `cpu_port_mask`，flood 图若不含端口 6，
`客户端广播 → CPU` 的路也会被切断。**期望值 `SWITCH_MFC = 0xffffff00`**（旧值 `0x40404000`）。
CPU 端口自己的矩阵只有 0..5，所以本机广播不会自环回自己的 RX ring。

### 4.4 发送抑制与链路 flap（现状）

- **flap 默认关闭**：`airoha_recovery_link_flap_enabled()` 无 env 时返回 false；
  要复现旧行为才 `setenv recovery_link_flap 1`。
- **RTL8261（PHY5/PHY8）永不参与 flap**：`recovery_flap_mask` 只剩 `BIT(0)`（1G PHY）。
  原因见 §10「给 RTL8261 掉电」。
- **`airoha_eth_send()` 在 flap 期间返回 `-EAGAIN`**：非阻塞 flap 解冻主循环后，
  若不抑制发送，OFFER 会被送进正在掉电/尚未完成自协商的 PHY。
  该抑制把旧 `mdelay()` 隐含的"PHY 就绪前不发包"显式化。
- **GDM4/USXGMII 训练移出 flap 开关**（`airoha_gdm4_recovery_prime()`），与 flap 无关，10G 通路一定被 prime。
- flap 相关 env：`recovery_link_flap`（默认 0）、`recovery_lan_flap_ms`（断电时长，默认 1500）、
  `recovery_lan_up_ms`（等 link 的超时，默认 2000）。
- flap 状态机：`restart_links()` 只做"立即断电 + 登记截止时间"然后返回；
  上电由主循环 `airoha_recovery_poll_link()` 在截止时刻执行；settle 从盲等改为**真实链路状态等待**
  （BMSR/STAT1，50 ms 轮询），`recovery_lan_up_ms` 退化为超时兜底。

### 4.5 诊断行速查

```
DHCP: DISCOVER from 38:a7:46:37:ee:65 (rx fport 1)
DHCP: REQUEST from 38:a7:46:37:ee:65 (rx fport 1)
DHCP: sent OFFER to 38:a7:46:37:ee:65 (offered 192.168.0.2)
DHCP: NAK to 38:a7:46:37:ee:65 (wanted 192.168.1.2)          ← 客户端记着别网段旧 IP
DHCP: request ignored by port policy (recovery_port=..., rx fport=N)
```

**判读要点**：只有 `DISCOVER` 没有 `REQUEST` ⇒ 客户端**没收到** OFFER（不是协议判定问题）。
「手动设静态 IP 能开恢复页」⇒ 单播通、泛洪不通（指向坑 ③ 那一类）。

---

## 5. 网口数据通路：两个 USXGMII PCS

### 5.1 端口 ↔ GDM ↔ PHY ↔ PCS 映射

AN7581 有**两个** USXGMII PCS 实例，板子每个接一颗 RTL8261（厂商内核 DTS 为证：
`an7581-xr1710g.dts` + `an7581.dtsi`）：

| 面板/内核名 | GDM | PHY | `pcs-handle` | `phy-mode` | PCS 寄存器窗口 |
|---|---|---|---|---|---|
| `lan2`（10G 口） | **GDM4** | PHY5 | `&eth_pcs` | `usxgmii` | `0x1fa09000` / `0x1fa74000` / `0x1fa75900` / `0x1fa76000` / `0x1fa7a000` / `0x1fa7b000` |
| `wan` | **GDM2** | PHY8 | `&pon_pcs` | `usxgmii` | `0x1fa08000` / `0x1fa84000` / `0x1fa85900` / `0x1fa86000` / `0x1fa8a000` / `0x1fa8b000` |

两个实例**布局完全相同，只差基址**；SCU 的 `SCU_WAN_SEL_USXGMII`
（`SCU_WAN_CONF 0x70`，`SCU_WAN_SEL GENMASK(7,0)`，值 `0x12`）
把那个空着的 XPON serdes 复用成 WAN 的 USXGMII PCS。
`SCU_SSR3 0x94 / SCU_ETH_XSI_SEL GENMASK(14,13)` 同理给 eth 侧选 USXGMII。

代码结构（`drivers/net/airoha_eth.c`）：

```c
struct airoha_ext_pcs {                 /* 一个 USXGMII PCS 实例 */
        void __iomem *xfi_mac, *multi_sgmii, *usxgmii, *rate_adp, *ana, *pma;
        bool ready;
};
struct airoha_eth {
        struct airoha_ext_pcs pcs;      /* GDM4 / PHY5 —— lan2 / 10G */
        struct airoha_ext_pcs wan_pcs;  /* GDM2 / PHY8 —— wan      */
        ...
};
```

**约定**：所有 USXGMII 辅助函数都吃 `struct airoha_ext_pcs *pcs`，**不要再写死 eth 实例**。
按 PHY 参数化的三个入口：`airoha_eth_gdm4_sync_rtl8261(eth, pcs, phy_addr, *speed)`、
`airoha_eth_gdm4_apply_runtime_phy_cfg(eth, phy_addr)`、
`airoha_eth_gdm4_link_up_config(eth, pcs, phy_addr)`。
两侧各一对 prime/ensure_ready：

| lan2 侧 | wan 侧 |
|---|---|
| `airoha_gdm4_recovery_prime()` | `airoha_recovery_wan_prime()` |
| `airoha_gdm4_ensure_ready()` | `airoha_recovery_wan_ensure_ready()` |

**唯一不能复用的是 GDM4 的 MBI 分片大小**（`airoha_eth_gdm4_set_frag_size()`，GDM4 独有），
所以 `airoha_eth_gdm4_link_up_config()` 里用 `if (pcs == &eth->pcs && speed)` 把它钉在 lan2 实例上。

拉起时机（三点都要，漏一处就有模式失效）：
1. `airoha_eth_init()` → `airoha_recovery_wan_prime()`。**必须在这里而不是 probe**：
   判据 `wan_service_enabled()` 读 env `recovery_port`，probe 期 env 未必就绪。
2. `airoha_recovery_restart_links()` 里 `if (serve_wan)` 再 prime 一次。
3. `airoha_recovery_poll_link()` 里的维护，必须放在 `airoha_recovery_accept_gdm4_rx()`
   提前 return **之前**——否则 wan-only 模式（`recovery_port=wan`）下 GDM4 路径整段跳过，
   WAN PCS 就没人管了。

### 5.2 WAN 的历史坑：XPON serdes 从未被拉起

**症状**：WAN 口**能协商速率、网卡灯间隔闪烁，但拿不到 IP**，且串口**没有任何后续日志**
（连 `DHCP: DISCOVER … (rx fport 2)` 都没有）。

**根因**：U-Boot 只 `map_sysmem()` 并初始化了 **eth PCS**（6 个硬编码宏 + 6 个 `eth_pcs_*` 指针），
`pon_pcs` 从未被映射、从未被编程，`XPON_PHY_RST` / `XPON_MAC_RST` 也从未释放。
PHY8 靠普通 MDIO 自己能谈出铜口链路（→ 灯闪、速率协商），但 **GDM2 一帧都发不出去**。

**注意**：这不是"软件端口策略屏蔽"的问题。解除软件屏蔽（DHCP 策略 / PHY8 电源 / GDM2 转发 /
广播镜像四处）**是必要但不充分的**——那四处早已在 auto/dual 下放开，WAN 仍然不通。
**WAN 相关门槛只存在于 `drivers/net/airoha_eth.c`**；
`lib/lwip/`、`net/`、`cmd/`、`board/` 里一条都没有（可用 grep 复核）。

**现约定**：见 §5.1 的代码结构 + §5.3 的复位释放。判别方法见 §12。

### 5.3 相关复位

`drivers/reset/reset-airoha.c`：bank0 = `REG_RESET_CONTROL2 0x830`、
bank1 = `REG_RESET_CONTROL1 0x834`，**置位 = assert（保持复位），清位 = deassert**。

| 复位 | 位置 | 对应的 PCS |
|---|---|---|
| `XSI_MAC_RST` / `XSI_PHY_RST` | bank0 bit7 / bit8 | eth PCS（lan2） |
| `XPON_PHY_RST` | bank0 **bit0** | pon PCS（wan） |
| `XPON_MAC_RST` | bank1 **bit31** | pon PCS（wan） |

probe 里用 `eth->scu_regmap` 清 XPON 两位即可（`SCU_RST_CTRL2` = `0x830`、`SCU_RST_CTRL1` = `0x834`；
与 reset 驱动的 `airoha_get_scu_regmap()` 是同一个 regmap）：

```c
/* xr1710g 与 xg2010g 共用同一份 PCS 代码 */
regmap_update_bits(eth->scu_regmap, SCU_RST_CTRL2, SCU_RST_XPON_PHY, 0);
regmap_update_bits(eth->scu_regmap, SCU_RST_CTRL1, SCU_RST_XPON_MAC, 0);
```

顺带：`airoha_hw_init()` 的 `reset_assert_bulk(&eth->rsts)` /
`reset_deassert_bulk(&eth->xsi_rsts)` **不包含** XPON 两位（`rsts` 只有 fe/pdma/qdma，
`xsi_rsts` 只有 hsi0/hsi1/hsi/xfp），所以 probe 里放开的 XPON 复位不会被后面重新置上。

PHY 侧是对称的：`airoha_rtl8261_minimal_init()` 对 PHY5/PHY8 都调 `init_one()` → `full_patch_one()`，
所以两颗 RTL8261 的固件补丁与 serdes 模式设置一致。

---

## 6. 槽位体积

### 6.1 上限与实测

`RECOVERY_MAX_UBOOT_SIZE = 1 MiB`（`httpd_recovery.c:100`），
分区 `chainloader@0x600000` 同为 `0x100000`（`dts/upstream/src/arm64/airoha/xr1710g.dts:168-172`，
`xg2010g.dts:184-188`）。写入目标由 env 决定（`httpd_recovery.c:2095-2111`）：
`recovery_dev_uboot="spi-nand0"` = 整颗 NAND，偏移 `uboot_ofs=0x600000`，
再被 `recovery_size_uboot=0x100000` 与 `RECOVERY_MAX_UBOOT_SIZE` 二者较小值夹住。

> ⚠️ **上限不是由设备树分区算出来的**，而是 env + 宏。
> 只改设备树分区**不会**放宽上传上限；只放宽 env/宏而不动设备树，
> 1 MiB 以上的镜像会**压到 `system`**（而且页面看起来"刷机成功"）。

最近一次双机型实测（版本串 `…-2026-10-16-g14def0596556`，构建 stamp `20261016-155419`）：

| 机型 | slot 字节 | KiB | 余量（对 1 MiB） | 占比余量 |
|---|---|---|---|---|
| **xr1710g** | 1,002,258 | 978.8 | **46,318 B / 45.2 KiB** | 4.4% |
| **xg2010g** | 1,014,506 | 990.7 | **34,070 B / 33.3 KiB** | **3.2%** |

> **XG2010G 的余量比 XR1710G 少约 12 KiB**，因为它的 defconfig 多编了
> `PHY_AIROHA` / `EN8811` / `EN8811_BUILTIN_FW`（§11.1 的机型固有差异表）。
> **体积闸门以 XG2010G 为准判断。**

slot 结构（以 xr1710g 为例）：

| 偏移 | 内容 | 字节 |
|---|---|---|
| `0x000000` | legacy bootm shim uImage（64 B 头 + `ih_size` 4,248 = 4,312），其后填充到 `0x2100` | 8,448 |
| `0x002100` | chainloader FIT（含头） | 993,810 |
| | 合计 | 1,002,258 |

FIT 内部（`compression` 全部为 `none`，payload **内联**在结构块里，无 `data-position`）：

| 组件 | xr1710g | xg2010g | 说明 |
|---|---|---|---|
| `fdt@1` | 266 | 266 | 控制 DTB |
| `kernel@1` | 8,632 | 8,632 | chainloader shim |
| **`uboot@1`** | **983,504** | **995,752** | **二级 U-Boot 本体（≈98%）** |
| FIT 结构/字符串/哈希 | 1,408 | 1,408 | — |

`xg2010g` 的 `uboot@1` 比 `xr1710g` 大 12,248 B —— 这就是两者余量差的来源。

**重新测量的方法**（本机无需交叉工具链）：

```sh
gh run download <run-id> -D ci            # 取最近一次双机型产物
ls -l ci/*/*-slot.bin                     # 直接得到 slot 字节数 → 余量 = 1048576 - 该值
```

要看 FIT 内部构成：slot 里 FIT 从 `0x002100` 开始（`FDT_MAGIC d0 0d fe ed`），
本工程的 ITS 把 payload **内联**在结构块里，所以 `fdt@1` / `kernel@1` / `uboot@1`
各自就是对应 `data` 属性的长度（**没有** `data-position` / `data-size`）；
`FIT totalsize − 三个 data 长度 = 1,408 B` 的 FIT 结构/字符串/哈希开销。
不需要 `dtc`：任何 FDT 遍历几十行就能读出来。

> ⚠️ Git Bash 的 `/tmp` 与 Windows 原生 python 的 `/tmp` **不是同一个目录**
> （前者是 `%TEMP%`，后者是当前盘符下的 `\tmp`）。
> 下载目录用**仓库内相对路径**（如 `ci`），避免踩这个坑。

### 6.2 余量与趋势

- 趋势：README 曾记录 914,938 B → 当前 1,002,258 B，恢复页 + DHCP 诊断一轮就吃掉 **~85 KiB**。
- 按此速度，**再一轮功能改动就会撞上闸门**（见 §6.1 的 XG2010G 余量）。
- 可控体积项：
  - 内嵌恢复页：`htdocs/` 共 72,946 B（`index.html` 68,805）→ 只占槽位 **~7%**，即使压缩也只省十几 KiB；
  - `printf` 诊断字符串：都在 `.rodata`，进 slot，属"随功能增长"的部分。

### 6.3 生成物纪律（最易复发）

`lib/lwip/httpd/fsdata_xr1710g.c` 是 `htdocs/` 的**生成物**，被 `lib/lwip/Makefile`
以 `-DHTTPD_FSDATA_FILE="httpd/fsdata_xr1710g.c"` 编入固件，**XR1710G 与 XG2010G 共用同一份**。
改完 `htdocs/index.html` **必须**重跑（`--minify` 不加，与历史一致）：

```sh
python lib/lwip/httpd/makefsdata.py lib/lwip/httpd/htdocs lib/lwip/httpd/fsdata_xr1710g.c
```

忘了会导致"启动后页面不是最新的"。`build.yml:111-114` 有守卫：
重新生成后 `git diff --exit-code` 不为空即 CI 失败。

---

## 7. 分区扩容评估：1 MiB → 2 MiB（决策：暂不做）

### 7.1 现状（512 MiB SPI-NAND，无空闲尾部）

| 起始 | 名称 | 大小 | 属性 |
|---|---|---|---|
| `0x000000` | `bootloader` | 2 MiB | read-only |
| `0x200000` | `uenv` | 2 MiB | 二级 U-Boot 的 env |
| `0x400000` | `dsd` | 2 MiB | vendor 板级数据 |
| `0x600000` | **`chainloader`** | **1 MiB** | read-only |
| `0x700000` | `system` | 439 MiB（`0x1b700000`） | `linux,ubi`（卷 `fit` / `factory`） |
| `0x1BE00000` | `reserved_bmt` | 66 MiB | read-only，厂商 BMT/BBT |

`0x600000 + 0x100000 = 0x700000` → **`chainloader` 与 `system` 紧邻，中间无缝隙**。
两个机型的这 6 个分区**完全一致**（`xr1710g.dts:152-`、`xg2010g.dts:168-`）。

### 7.2 改成 2 MiB 的实际影响

- **`system` 必须后移 1 MiB**（`0x700000` → `0x800000`）并缩小为 438 MiB；尾部 `reserved_bmt` 不能动。
- **`system` 是 UBI**：起始偏移一变，所有 LEB 物理位置错位，**旧 UBI 内容当场失效**
  ⇒ 采用新分区表的机器都要**重刷整机固件**（`fit` + `factory` 全套），不能只推 chainloader。
- **引导本身不受影响**：一级/二级都按**固定偏移**读，不查分区表
  （`uboot_ofs=0x600000`、`RECOVERY_UBOOT_SLOT_DEFAULT_OFS=0x600000`、厂商 `flash read 0x602100 …`）
  ⇒ 扩容只是**给 Linux/OpenWrt 侧看**的布局变更。
- **只改 env/宏不改分区表是危险的**：见 §6.1 的 ⚠️。

**必须协同修改的位置**（漏一处就出问题）：

1. `dts/upstream/src/arm64/airoha/xr1710g.dts:168-176` 与 `xg2010g.dts:184-192`
   （`chainloader` → `0x200000`，`system` 起始 → `0x800000`、大小减 1 MiB）
2. `net/lwip/httpd_recovery.c:100` `RECOVERY_MAX_UBOOT_SIZE`
3. `.github/workflows/build.yml` 的发布说明文案（现写死"偏移 0x600000，1 MiB"）
4. `chainloader/build-chainloader-fit.sh:68` `MAX_SLOT_SIZE=$((0x100000))`
5. `board/airoha/an7581/xr1710g.env` / `xg2010g.env` 的 `recovery_size_uboot`
6. `README.md` / `docs/flashing-*.md` 的说明与 `flash read/erase/write` 长度
7. 使用新分区表的整机固件的 UBI 重新生成流程

### 7.3 替代方案实测（按本版产物推算）

对本版 FIT 逐组件做压缩（gzip-9 / lzma）：

| 组件 | 原始 | gzip-9 | 压缩率 | lzma |
|---|---|---|---|---|
| `fdt@1` | 266 | 176 | 66.2% | 212 |
| `kernel@1` | 8,632 | 4,848 | 56.2% | 4,312 |
| **`uboot@1`** | **983,504** | **424,716** | **43.2%** | **335,316** |
| 合计 | 992,402 | **429,740** | 43.3% | 339,840 |

⇒ 把 `uboot@1` / `kernel@1` 声明为 `compression = "gzip"`（DTB 保持 `none`）后，
**slot 预计从 ~979 KiB 降到 ~430 KiB，余量 ~595 KiB（占分区 57%）**；
用 lzma 可再降到 ~340 KiB。

| 方案 | 省下 | 风险 | 备注 |
|---|---|---|---|
| **① 压缩 FIT 里的 `uboot@1`** | **~550 KiB** | 中（须实测厂商一级 loader 会解压 `type=firmware` 的 loadable） | 首选 |
| ② 对恢复页 `--minify` | ~15–25 KiB | 低（但与"不 minify"的历史约定冲突） | 只改生成物 |
| ③ 精简诊断 `printf` | 数 KiB | 低 | DHCP 问题闭环后顺手做 |
| ④ 扩到 2 MiB | 1 MiB | 中（布局）+ **高（现场重刷整机）** | 上述 7 处协同修改 |

**落地方式**（两处改动）：

1. `chainloader/*-chainloader.its.in`：`uboot@1` 的 `compression` 由 `"none"` 改 `"gzip"`；
   `kernel@1` 的 `__KCOMP__` 占位符在 `build-chainloader-fit.sh:80` 已存在，把那里的 `none` 改成 `gzip`。
2. `chainloader/build-chainloader-fit.sh`：`mkimage -f its` **不会自己压缩**
   （`tools/fit_image.c` 只把 `compression` 名字写进节点），
   必须先把载荷 `gzip -9` 到临时文件，再把 `__PAYLOAD__` 指向它。

**唯一必须在真机上验证的疑点**：FIT 由**厂商 ECNT/AXON U-Boot 2014.04**
（`bootcmd = flash read 0x602100 …; bootm`）解析，我们改不了它。
上游 `fit_image_load()` 对**非 kernel** 类型（含 `type=firmware` 的 loadable）会就地解压，
`kernel` 则延后到 `bootm_load_os()`；这套通用解压存在很多年了，
但 **2014.04 的 vintage 需要实测**。另外该函数用 `max_decomp_len = len * 20` 映射解压缓冲
（压缩后 ~424 KB → ~8.1 MiB 窗口，落在 `0x81e00000` 的载荷装入地址上），
上机时留意这块窗口是否与运行中的 U-Boot 自身内存冲突。

### 7.4 结论

扩容技术风险可控，但代价是**现场每台机器都要重刷整机**，而这个代价**大概率可以避免**。
**先用方案 ① 换空间，把方案 ④ 留到不得不做的那一天**（例如将来要塞 3 MiB 的镜像）。
**翻案条件**：① 在真机上被证伪（厂商 loader 不解压），或槽位需求超过 ~1.4 MiB（压缩后仍不够）。

---

## 8. U-Boot 核心版本同步（决策：暂不同步）

| | 版本 | 依据 |
|---|---|---|
| 本项目 | **2026.07** | `Makefile:3-4` |
| 上游最新 | **v2026.10**（2026-10-05） | u-boot 邮件列表公告 |
| 上游下一个 | v2027.01-rc1（2026-10-26） | 同上 |
| 对照树 an758x | **2026.10** | `uboot-an758x/Makefile:4` |

差 1 个发布（约 3 个月）。U-Boot 是**季度**发布节奏（1/4/7/10 月首个周一）。

**为什么不建议现在同步：**

1. **没有祖先可 rebase。** 本仓库历史已压成 2 个提交（`5983ffd` 基线 + `76494d4` 开发集合），
   `git log` 里**没有任何上游祖先**、也没有 upstream remote。
   "同步到最新"不是 `git rebase`，而是**重新移植**：把 v2026.10 整棵树拿来，再把本地增量逐项贴回。
2. **本地增量大且分散**，每个都要重新验证：
   `drivers/net/airoha_eth.c`、`drivers/net/airoha/pcs-*.c`、`net/lwip/httpd_recovery.c`、
   `lib/lwip/` 整棵导入 + `lwipopts.h` 本地选项、`board/airoha/an7581/*_rfb.c` / `*.env`、
   `chainloader/`（shim + ITS + 打包脚本）、`dts/upstream/`、`htdocs/`（+ 生成物）、
   `Makefile` 的 `UBOOTVERSION` 与 `scripts/setlocalversion` 定制。
3. **本机没有 aarch64 交叉工具链**，唯一真实编译验证是 CI ⇒ 移植 + 排错只能"推一次、等一次 Actions"。
4. **v2026.10 对本板没有必须的修复**：公告条目是平台更新（Marvell / NXP / i.MX / AMD-Xilinx /
   Renesas / Rockchip / STM32）、EFI loader / FPGA / DFU / 网络子系统通用修复、FIT 清理，
   外加两条可能相关但不关键项（"某些平台 reserved memory 的伪 ERROR 打印"是纯日志噪声；
   "FIT 可校验 dm-verity roothash" 本方案不用 dm-verity）。

**同步时按这个顺序做，且单独成一个提交：**
1. 先确认 `git status` 干净、上表的功能改动都已真机闭环；
2. 以 v2026.10 为基线，把上面第 2 条清单当"移植工单"逐项贴回；
3. 只用 CI 验证，两个机型都要绿；
4. 真机重点回归 **引导链路（§1.1）+ 恢复页 + DHCP + 备份下载 + 两个网口（§5）**。

**顺手要修的周边**：上游已从 `lists.denx.de` / `github.com/u-boot/u-boot` 迁到
`git.u-boot-project.org/u-boot/u-boot`，`source.denx.de/u-boot` 只是重定向；
构建/发布脚本里若还钉着旧域名，应一起改掉。

**翻案条件**：本板需要上游某个具体修复，或版本落后到 ≥2 个发布。

---

## 9. 版本号与发布约定

### 9.1 版本串

`Makefile:375` `UBOOTVERSION = XR1710G` 是**全局常量**，所以
**XG2010G 的版本串也是 `XR1710G-recovery-…`**，机型只靠 `CONFIG_LOCALVERSION="-recovery"` 区分。
是否要为 XG2010G 单独生成 `UBOOTVERSION` —— **待定**（见 §11）。

格式：`<UBOOTVERSION>[-<CONFIG_LOCALVERSION>]-<构建日期>-g<12位commit>`，
由 `scripts/setlocalversion` 生成（`PLAIN_VERSION`）。构建日期取 `include/timestamp.h` 的
`U_BOOT_DATE`/`U_BOOT_TIME`/`U_BOOT_TZ`（`common/version.c` 无条件使用，板级代码可直接用）。

**板级版本号只能用 `PLAIN_VERSION`**，禁止在 `include/<board>_version.h` 里手写日期
（曾写死 `"2026-8-8"`，导致横幅与 `/api/about` 长期显示旧版本）。

### 9.2 `-dirty` 已取消

历史上横幅一直带 `-dirty` 而无实际未提交改动，根因是**文件权限位**：

- `scripts/build.sh` 与 `chainloader/build-chainloader-fit.sh` 以 `100644` 提交；
- `build.yml` 在 make **之前**执行 `chmod +x scripts/build.sh`；
- Linux 上这是**受版本跟踪的权限变更**（`100644 → 100755`），`git status --porcelain` 因此报 `M scripts/build.sh`；
- `make` 在**构建一开始**就由 `scripts/setlocalversion` 生成 `PLAIN_VERSION`，
  它的 dirty 检查看到任何受跟踪改动就追加 `-dirty`。

Windows 上永远复现不出来（`core.filemode` 默认 false，git 忽略权限位）。

**现约定：**

1. 两个脚本的**可执行位写进索引并提交**（`mode change 100644 => 100755`）。
   **不要在 workflow 里加 `chmod +x`** —— 那会在 Linux 上制造一次受版本跟踪的权限变更，
   把 `-dirty` 重新带回来。
2. `build.yml` 有守卫 **Verify the work tree is clean before the version stamp**：
   make 之前 `git status --porcelain --untracked-files=no` 非空即 CI 失败并打印改动文件。
3. `Makefile` 的
   `UBOOT_SETLOCALVERSION_FLAGS := $(if $(filter 1,$(UBOOT_KEEP_DIRTY)),,--no-dirty)`
   （传给 `filechk_uboot.release`）+ `scripts/setlocalversion` 顶层新增的 `--no-dirty`：
   `-g<commit>` 与构建日期照常保留，**溯源能力不减**，只是不再把 `-dirty` 混进版本号。
   `scripts/build.sh` 在树不干净时打**警告**并列出改动文件，提示 `UBOOT_KEEP_DIRTY=1` 可换回旧行为。

### 9.3 发布约定

- 每机型 **只发布 1 个文件**：`<board>-chainloader-<YYYYMMDD-HHMMSS>-g<commit12>-slot.bin`。
  **裸 `.itb` 不产出也不发布**（它不能通过 HTTP Recovery 上传，不该存在）。
- `*-build-info.txt` / `*-sha256sums.txt` **只留在 Actions artifact**，不进 Release 页面。
- tag = `<YYYY-MM-DD>-<commit12>`（日期取构建 stamp 的 UTC 日期）；
  title = `AN7581 U-Boot <PLAIN_VERSION>-<stamp>`。
- `build.yml`（构建+发布）与 `publish-existing-artifact.yml`（复用旧运行产物重发）**必须同构**，
  改一个就要改另一个。
- `build.yml` 的 `stamp` job 产出全板共享的构建时刻；**不要把 `date` 放进 matrix job**（两板时间会不一致）。
- 发布本身由 `stamp` → `build`（matrix）→ `release` 串起来；
  `release_type` 输入决定 build only / pre-release / release。

---

## 10. 容易复发的坑（症状 → 根因 → 现约定）

### 坑 1：启动后恢复页不是最新的
- **根因**：`fsdata_xr1710g.c` 是 `htdocs/` 的生成物，改页面忘了重新生成。
- **现约定**：见 §6.3；`build.yml:111-114` 已加守卫。

### 坑 2：给 RTL8261（PHY5/PHY8）掉电后端口再也不连接，只能冷启动
- **根因**：RTL8261 只有在 `airoha_rtl8261_minimal_init()`（probe 期，走 `arht-mdio`）
  做过固件补丁 + serdes 模式设置之后才转发帧；而
  `airoha_switch_recovery_runtime_init()` 明确 **"avoids PHY resets and RTL8261 patching"**。
  清 `LPOWER` + 重启自协商**不会**重做那套设置 → PHY 回来了但 serdes 不在 USXGMII 模式。
- **现约定**：RTL8261 **永不参与 flap**（`recovery_flap_mask` 只剩 `BIT(0)`）；
  `airoha_recovery_power_down_wan_phy()`（钉前面板口时掉电 PHY8）保留，
  但重新服务 WAN 时由 `airoha_recovery_wan_prime()` 重新拉起 PCS。
  **想限制端口就用端口矩阵/RX 侧过滤，不要动 PHY 电源。**

### 坑 3：非阻塞 flap 期间把帧发进未就绪的 PHY
- **根因**：旧实现用 `mdelay()` 冻结主循环，等价于"PHY 就绪前一个帧都不发"；解冻后这个隐含保证消失。
- **现约定**：`airoha_eth_send()` 开头 `if (eth->recovery_flap_active) return -EAGAIN;`。
  **只要引入任何"非阻塞等待"，就要检查是否依赖了原来阻塞语义提供的隐含保证。**

### 坑 4：CPU 发出的泛洪帧（广播 / 未知组播 / 未知单播）全部黑洞
- **根因**：`SWITCH_MFC` 的 flood 图写成 CPU 端口位，与入端口矩阵取交集后为空。
- **现约定**：`flood_port_mask = GENMASK(7, 0)`，期望 `SWITCH_MFC = 0xffffff00`。
  **flood 图必须比端口矩阵更宽，由矩阵负责限制。**
  判读：只有 `DISCOVER` 没有 `REQUEST`、且手动静态 IP 可访问 → 指向这一类。

### 坑 5：WAN 口"灯闪、速率能谈、拿不到 IP、串口无日志"
- **根因**：WAN 的 serdes 是**另一个** USXGMII PCS 实例（`pon_pcs`），
  早期 U-Boot 只初始化了 `eth_pcs`，且从未释放 XPON 复位。
- **现约定**：见 §5；判别见 §12。**不要先去查软件端口策略** —— 那四处早已放开。

### 坑 6：二级 U-Boot 里 `saveenv` 破坏原厂 `uenv`
- **根因**：`uenv` 是**原厂 U-Boot 的 env 分区**，二级 U-Boot 只是共用读取。
  `saveenv` 会把原厂环境整套替换成 chainloader 的环境。
- **现约定**：**绝对不要在二级 chainloader U-Boot 里执行 `saveenv` 或 `env default -a`**；
  连 `bootdelay` 这种小事也别为它去 save（§2.2）。
  原厂 U-Boot 若停在 `ECNT>` 报 `Unknown command 'ubi'`，说明已被替换，在原厂命令行执行：
  `setenv bootcmd 'flash read 0x600000 0x100000 0x81800000; bootm 0x81800000'; saveenv`。

### 坑 7：把 `-dirty` 当情报追查
- **根因**：文件权限位变更 + `setlocalversion` 的 dirty 检查（§9.2）。
- **现约定**：见 §9.2；`build.yml` 已有"版本戳之前树必须干净"的守卫。

### 坑 8：改了 defconfig 但真机不生效
- **根因**：`CONFIG_BOOTDELAY` 这类值若已被 `saveenv` 持久化，env 里的值优先。
- **现约定**：两机型 `.env` 源文件都**不定义** `bootdelay`，所以默认取编译值；
  真机若仍是旧值，说明被持久化过（覆盖要谨慎，见坑 6）。

### 坑 9：`/tmp` 在两个世界里不是同一个目录
- **根因**：Git Bash 的 `/tmp` = `%TEMP%`；Windows 原生 python 的 `/tmp` = 当前盘符下的 `\tmp`。
- **现约定**：跨两者传路径时一律用**仓库内相对路径**（如 `ci`）。

### 坑 10：`lan2` 有两套含义
- **根因**：`recovery_port` 的词表里 `lan2` = 1G 口，而内核 DTS 里 GDM4+PHY5（**10G 面板口**）
  的 netdev 名也叫 `lan2`。
- **现约定**：正文按语境分别使用；引用时**必须写清是哪一套**（§4.2 有对照说明）。
  改端口相关代码时，先确认自己用的是 `fport` 号还是 netdev 名。

---

## 11. 待办

| # | 项 | 类型 |
|---|---|---|
| 1 | 真机确认 §5（WAN PCS）+ §4.3 坑③ 的判据，两个机型都过一遍 | 验证 |
| 2 | §7.3 方案 ①（FIT 压缩）真机验证 | 验证 |
| 3 | XG2010G 是否要单独的 `UBOOTVERSION`（§9.1） | 待定 |
| 4 | §3.3 UBI 写入回读校验（写路径，出错即变砖，未盲改） | 未做 |
| 5 | DHCP 问题闭环后精简诊断 `printf`（§6.2 方案 ③） | 未做 |
| 6 | 两个机型的 defconfig 差异**只应保留机型固有项**，不要再"统一" | 约定 |

### 11.1 两个 defconfig 的机型固有差异（不要再统一）

| 条目 | xr1710g | xg2010g |
|---|---|---|
| `CONFIG_BOARD_*` | `CONFIG_BOARD_XR1710G=y` | `CONFIG_BOARD_XG2010G=y` |
| `CONFIG_DEFAULT_DEVICE_TREE` | `airoha/xr1710g` | `airoha/xg2010g` |
| `CONFIG_DEFAULT_FDT_FILE` | `xr1710g` | `xg2010g` |
| `CONFIG_ENV_SOURCE_FILE` | `xr1710g` | `xg2010g` |
| `CONFIG_LOCALVERSION` | （空） | `-recovery` |
| `CONFIG_POSITION_INDEPENDENT` | 未设 | y |
| `CONFIG_SYS_MALLOC_LEN` | 未设 | `0x800000` |
| `CONFIG_CMD_SAVEENV` | 未设 | y |
| PHY | `CONFIG_PHY_REALTEK=y` | 另加 `PHY_AIROHA` / `EN8811` / `EN8811_BUILTIN_FW`（**这是 XG2010G 槽位余量更小的原因**，§6.1） |
| `CONFIG_LZMA_SIZE_OPTIMIZATION` | 未设 | y |
| `BOOTDELAY` | 1 | 1（**共有，不是差异**） |
| `MTD_UBI_FASTMAP` / `_AUTOCONVERT` | y / 1 | y / 1（**共有**） |

---

## 12. 真机验证判据（零刷机）

⚠️ **本机没有 aarch64 交叉工具链，所有 C 改动均未经本地编译验证**，
编译验证只能靠 GitHub Actions `build.yml`。

**体积闸门**：`chainloader/build-chainloader-fit.sh:99` —— 产物 `>= 1 MiB` 直接报错退出，
所以"快满了"会以 **CI 失败**的形式暴露，不会静默发出超限镜像。

### 12.1 进恢复模式后逐项核对

在恢复模式提示符执行 `rtl8261_diag`，按下面这张表读：

| 检查 | 期望 | 含义 / 历史坑 |
|---|---|---|
| `switch mfc=` | **`ffffff00`** | 泛洪图正确（旧值 `40404000`）→ 坑 4 |
| 串口是否出现 `airoha: restarting recovery links...` | **不应出现** | flap 默认关闭 → 坑 2/3 |
| `gdm2[fwd=...]` | `00000004`（PPE1） | GDM2 入向转发（旧值 `0000000f` = DROP） |
| `wan[serve=1 link=1]` | 1 / 1 | WAN 在服务范围内 + PHY8 铜口链路起来 |
| **`wan[ready=1 pcslink=1 usx=1 rx=1]`** | **全 1** | **WAN 侧 USXGMII PCS 已初始化 + 上行 + 收到 RX 信号 → 坑 5 的判据** |
| `wan[xfi[gib=.. rst=..] pcs[4=.. 310=..]]` | 非全 0 | XPON PCS 寄存器活着；若 `ready=0` 说明 `wan_pcs` 从未初始化 |

### 12.2 端口连通（每个口都插一次 PC）

| 口 | 串口应出现 | 说明 |
|---|---|---|
| 1G 交换机口（`recovery_port=1g`/词表 `lan2`/`lan3`） | `DHCP: DISCOVER … (rx fport 1)` → `DHCP: REQUEST …` | **有 REQUEST 才说明客户端收到了 OFFER** |
| 10G 面板口（内核 netdev `lan2`；`recovery_port=lan1`/`10g`/`4`） | `… (rx fport 4)` → `REQUEST` | 顺带确认 10G 口能连接（坑 2 的回归判据） |
| WAN（内核 netdev `wan`；`recovery_port=wan`/`2`） | `… (rx fport 2)` → `REQUEST` | 坑 5 的最终判据 |

若只看到 DISCOVER 不见 REQUEST：先查 `mfc`（坑 4），再看该口的 `wan[...]` / `gdm4_fwd`。

### 12.3 启动速度

- 串口启动日志里 UBI attach 的耗时明显下降（fastmap 生效）；
- `printenv bootdelay` = 1（该设备此前未持久化过 `bootdelay` 时）。
