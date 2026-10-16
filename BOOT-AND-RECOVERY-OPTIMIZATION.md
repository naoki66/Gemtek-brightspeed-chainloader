# 引导链路对比与启动/恢复优化

对比对象：

- 本项目（U-Boot **2026.07** 分支，**chainloader 方案**）
- `D:\GitData\uboot-an758x`（U-Boot **2026.10**，**TF-A BL2/FIP 原生方案**）

> **文档维护状态**：本文最后**全量核对**于 2026-10-16，基线提交 `0d90131`
> （`git log --oneline -3` = `0d90131` / `80c6711` / `76494d4`）。
> 凡带"**（改动前）**"标记的表格行描述的是**引入本方案优化之前**的状态，
> 保留用于对照 an758x；当前状态一律以 §4.3、§4.5~§4.7 与 §5 为准。
>
> **2026-10-16 之前的过期描述已清除**，逐条见 §0。

---

## 0. 本轮（文档刷新）修正的过期内容

| 位置 | 过期描述 | 现状（已核实） |
|---|---|---|
| §1.1 | 板级文件写作 `board/airoha/an7581/an7581_rfb.c` | 实际是 **`xr1710g_rfb.c`**（961 行）与 **`xg2010g_rfb.c`**（906 行） |
| §1.1 | env 来自 **UBI**（`CONFIG_ENV_IS_IN_UBI`, `ubi:ubootenv`） | `configs/xr1710g_defconfig:47-50`：**`CONFIG_ENV_IS_IN_MTD=y`**、`CONFIG_ENV_MTD_DEV="uenv"`、`CONFIG_ENV_OFFSET=0x0`，且 `# CONFIG_ENV_IS_IN_UBI is not set` |
| §1.1 | `xr1710g_detect_ubi_part()` **依次试 ubi / ubi1.5 / ubi1.0** | `xr1710g_ubi_layouts[]` 现在**只有 1 项**：`{ "2.0", "system" }`（xr1710g_rfb.c:79-81） |
| §1.2 表 | "布局选择 ✅ WebUI 选 UBI 2.0 / 1.5 / 1.0" | 已从页面与代码移除（多布局视图在设备树里无对应分区） |
| §2.1 表 | "1.5/1.0 设备的布局探测，最多 3 次 attach" | 不成立，布局只剩 1 个 |
| §2.2 | 启动优化未说明机型范围 | `CONFIG_BOOTDELAY=1` / `FASTMAP` **只在 `xr1710g_defconfig`**；`xg2010g_defconfig` 仍是 `BOOTDELAY=3` 且**无 FASTMAP** |
| §3.2 | "备份 437 MiB 的 `ubi` 分区"、"`vendor` / `ubi` 分区名" | 分区名是 `bootloader / uenv / dsd / chainloader / system / reserved_bmt`；`system` = **439 MiB** |
| §3.2 | `index.html 43.4 KB → 50.8 KB`，`fsdata 245.8 KB → 282.9 KB` | 实测 `index.html` = **68,805 B**，`fsdata_xr1710g.c` = **374,132 B** |
| §3.2 | `mock_server.py`、`.workbuddy/verify_recovery_backup.py` | 两者**已不在树内**，相关描述删除 |
| §4.1/§4.2 | 表中"本项目"列写"单一固定地址、无租约表、一律 NAK" | 那是**改动前**状态；已在 §4.3 换成 16 条租约表 + 池 |
| §5 | 产物 914,938 B、"余量约 120 KB" | 实测 **1,001,522 B**，余量 **47,054 B（4.5%）** → 新增 §5、§6、§7 |
| 全篇 | 行数 `httpd_recovery.c`（3306 行） | 现为 **4,272 行**（`airoha_eth.c` 6,461 行） |

**2026-10-16 第二轮（本轮）新增**：§4.8「交换机 flood map 黑洞」——这是
"1G 口拿不到 IP"的**真正根因**；§4.9「flap 默认关闭 + RTL8261 不再掉电」——
修掉"10G 口不再连接"的回归。两者都基于 an758x 的对照（它 `SWITCH_MFC` 写全 0xff、
且完全没有链路 flap）。

> 关于 `D:\GitData\uboot-an758x`：本文件与 `net/lwip/httpd*.c` 的行数（1882 / 367）**仍然准确**，
> 但它的版本已确认是 **2026.10**，比本项目**领先 1 个发布**——这是 §6 讨论的对象。

---

## 1. 引导链路

### 1.1 本项目：三级串联，前两级不受我们控制

```
上电
 └─ 厂商 ECNT/AXON U-Boot 2014.04（NAND 0x0，不可改）
     bootcmd = flash read 0x602100 0x4000000 $loadaddr; bootm     ← 默认读 64 MiB
 └─ chainloader slot 镜像（NAND 0x600000，分区 1 MiB，双入口）
     0x600000  legacy bootm shim      IH_MAGIC  27 05 19 56
     0x602100  chainloader FIT        FDT_MAGIC d0 0d fe ed
 └─ FIT 内嵌二级 U-Boot 本体           CONFIG_TEXT_BASE=0x81E00000
```

二级 U-Boot 内部（`board/airoha/an7581/xr1710g_rfb.c` + `board/airoha/an7581/xr1710g.env`）：

```
env 从 **MTD `uenv` 分区**读取（CONFIG_ENV_IS_IN_MTD=y / CONFIG_ENV_MTD_DEV="uenv" /
  CONFIG_ENV_OFFSET=0x0）。这是二级 U-Boot 与厂商 U-Boot 共享的分区，
  xr1710g_uenv_consume_recovery_trigger() 会从里面读走一次性恢复标志。
board_late_init()                          xr1710g_rfb.c:821
  ├─ 清 legacy fdt_high / 归一化 bootargs   :886 / :896
  ├─ xr1710g_sync_runtime_ethaddrs()        :732  读 vendor DSD → 运行时 MAC
  ├─ xr1710g_detect_ubi_part()              :570  只有 1 个布局："2.0" → "system"
  ├─ xr1710g_sync_factory_part()            :613  DSD→factory 卷比对，不同则写回
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

env 来自 `include/env/airoha/an758x-ubi.env`（经 `CONFIG_AIROHA_UBI_ENV`）：

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
| 核心版本 | **2026.07** | **2026.10** |
| env 后端 | **MTD `uenv`**（`CONFIG_ENV_IS_IN_MTD`） | UBI（`CONFIG_AIROHA_UBI_ENV`） |
| UBI fastmap | ✅ `MTD_UBI_FASTMAP` + `AUTOCONVERT`（**仅 xr1710g**） | ✅ `MTD_UBI_FASTMAP` + `AUTOCONVERT` |
| bootdelay | 1（xr1710g）/ 3（xg2010g） | 3 + `AUTOBOOT_MENU_SHOW`（还会显示菜单，更慢） |
| 一级读取量 | **64 MiB**（厂商默认；slot 镜像仅 ~1 MiB） | 不适用 |
| 启动期 UBI attach | env 1 次（MTD）；`system` attach 1 次 | 1 次 |
| 启动期写 flash | `factory` 同步（不一致才写） | 无 |
| 恢复服务 | `net/lwip/httpd_recovery.c`（**4,272 行**）+ 内置 DHCP | `net/lwip/httpd.c`（1882 行）+ `httpd-dhcp.c`（367 行） |
| 布局选择 | ❌ 单一布局 `system`（多视图已移除） | ❌ 单一布局 |
| 软件触发恢复 | ✅ `recovery_trigger` env（LuCI 下发，走 `uenv`） | ❌ 只有按键 |
| 备份下载 | ✅ `/api/storage` + `/api/download`（见 §3.2） | ✅ `/api/download` + 存储目录 + 板级数据 |
| UBI 写入回读校验 | ❌ 无（只有 raw MTD 逐块校验） | ✅ `ubi_verify_*` + `verifyaddr=loadaddr-filesize` |

**本项目相对 an758x 的既有优势**：`recovery_trigger` 软件触发、四色彩虹呼吸灯效
（an758x 的 `httpd-led.c` 是反向移植自本项目）、16 条租约的 DHCP 服务——这些保留不动。

---

## 2. 启动速度

### 2.1 瓶颈排序（按量级）

| # | 位置 | 开销 | 归属 |
|---|---|---|---|
| 1 | 厂商 `flash read 0x602100 0x4000000` | 读 64 MiB，实际只需 ~1 MiB | 厂商 env，我们改不了代码 |
| 2 | `ubi read fit` | 整个 fit 卷（数十 MiB）搬进 RAM | 不可避免（`bootm` 需要完整 ITB） |
| 3 | UBI attach 全盘扫描 | 0x1B700000 / 128 KiB ≈ **3500 个 PEB**，逐个读 EC/VID 头 | ✅ 已优化（fastmap，仅 xr1710g） |
| 4 | bootdelay | 3 s 空等 | ✅ xr1710g 已降到 1 s；xg2010g 未改 |
| 5 | `xr1710g_sync_factory_part()` | 两次 24 KiB 读 + DSD 读，10 ms 量级 | 不是瓶颈，但保留"可能写 flash"的面 |

### 2.2 已落地的改动

1. **`configs/xr1710g_defconfig`**
   ```diff
   -CONFIG_BOOTDELAY=3
   +CONFIG_BOOTDELAY=1
   ...
   +CONFIG_MTD_UBI_FASTMAP=y
   +CONFIG_MTD_UBI_FASTMAP_AUTOCONVERT=1
   ```
   - fastmap 把每次启动的 UBI attach 从"扫 3500 个 PEB"降为"读几个 anchor PEB"。
     `AUTOCONVERT=1` 会在首次 attach 时给没有 fastmap 的设备补写一份，
     **已出厂的机器不用重新格式化**。
   - `CONFIG_BOOTDELAY` 只影响新 env 的默认值；已保存 `bootdelay=3` 的设备
     用 `setenv bootdelay 1; saveenv` 即可。按键/串口打断仍然有效，
     恢复按键是在 `board_late_init()`（autoboot 之前）采样的，**不受 bootdelay 影响**。
2. **README / docs**：把厂商一级 `bootcmd` 的长度从 `0x4000000` 说明为可改成 `0x100000`
   （`README.md:178`、`docs/flashing-xr1710g.md:208/347`），只能手工在 `ECNT>` 提示符下执行。

### 2.3 未做（附原因）

- **⚠️ `xg2010g_defconfig` 没跟上**：`CONFIG_BOOTDELAY=3`、无 `FASTMAP`。
  两个机型按约定应保持同构，这是一处**待补齐的差异**，建议随下次改动一并处理。
- **把布局探测结果缓存进 env**：布局只剩 1 个以后，收益基本消失，可以不做。
- **改厂商 env**：只能手工在 ECNT 提示符下执行，写进 README，不做自动改写。
- **`iminfo` 校验**：an758x 在 `ubi_read_production` 里带 `iminfo`，校验完整但会
  多花一次全镜像哈希计算；本项目启动路径不加，保持启动速度。

---

## 3. 恢复与备份能力

### 3.1 差距（对照 an758x，**改动前**）

an758x 的 httpd 是**读写双向**的：`HTTP_JOB_BL2 / FIP / BOARD_DATA / FIRMWARE /
REBUILD / ENV / NAND_SCRUB` + `HTTP_STORAGE` 备份请求 + `/api/download/<id>/<off>/<len>`
分段下载 + `build_storage_catalog()` 目标枚举。
本项目改动前**只能写，不能读**——一旦 `factory`（MAC / Wi-Fi EEPROM）或 `uenv`
被清掉，且事先没有备份，机器就救不回来了。

### 3.2 已落地：只读备份下载

新增三个端点（`net/lwip/httpd_recovery.c`）：

| 端点 | 作用 |
|---|---|
| `GET /api/storage` | JSON 列出所有 **MTD 分区**（`bootloader / uenv / dsd / chainloader / system / reserved_bmt`）与 **UBI 卷**（`fit` / `factory` / …），带字节大小 |
| `GET /api/backup/mtd/<name>` | 登记一次备份，返回 `{"id","kind","name","size"}` |
| `GET /api/download/<id>/<offset>/<length>` | 流式返回该段原始字节（`Content-Disposition: <name>.bin`） |

实现要点：

- **只列整个 MTD 分区**：UBI 卷是 `system` 分区内部的逻辑层，raw 备份 `system`
  已经包含全部卷；同时提供两者会诱导页面把几百 MiB 拉两遍，而且卷 dump
  不是 `mtd write` 能写回的形式。
- **MTD 备份保留物理偏移**：遇坏块时填 `0xff` 而不是跳过，
  这样 dump 出来的镜像可以直接用 `nandwrite` 原样写回，且长度恒等于分区大小。
  （an758x 的 `fs_read_custom()` 是同一套约定。）
- **流式，不占内存**：`file->data = NULL` + `LWIP_HTTPD_DYNAMIC_FILE_READ`，
  lwIP 通过 `fs_read_custom()` 分块拉取。
  所以备份 439 MiB 的 `system` 分区不需要在 RAM 里开同样大的缓冲。
- **安全边界**：
  - 名字只允许 `[A-Za-z0-9_.-]`，长度 < 32（`RECOVERY_PARTITION_NAME_LEN`）
    → JSON 无需转义，也堵掉路径穿越；
  - 单段上限 256 KiB（`RECOVERY_BACKUP_SEGMENT`），且 `offset + length`
    不得超过登记的 `size`；
  - `id` 必须等于当前登记的备份 id，且同时只允许一个下载在飞；
  - 擦写任务进行中（`prog_phase` 1/2）直接拒绝，避免和写路径抢 flash。

配套改动：

- `lib/lwip/u-boot/lwipopts.h`：打开 `LWIP_HTTPD_DYNAMIC_FILE_READ=1`
  与 `LWIP_HTTPD_FILE_EXTENSION=1`（后者给 `struct fs_file` 加私有指针字段，
  用来在 `fs_open_custom()` / `fs_read_custom()` / `fs_close_custom()` 之间带状态）。
- `fs_open_custom()` 开头强制 `file->pextension = NULL`——lwIP 的 `fs_open()`
  对 custom file 不会清这个字段，不清会读到上一次下载留下的野指针。
- `lib/lwip/httpd/htdocs/index.html`：恢复页底部新增"备份 / Backup"卡片
  （读取列表 → 点目标 → 分段下载 → Blob 另存为 `<name>.bin`），中英文齐全。
- `lib/lwip/httpd/fsdata_xr1710g.c`：改完 `htdocs/` 必须用 `makefsdata.py`
  **重新生成**（见 §5.4）。

### 3.3 未做（附原因）

- **UBI 写入回读校验**。本项目 raw MTD 写入有逐擦除块校验
  （`recovery_mtd_verify_write()`），但 UBI 写入路径写完只做 `ubi_check_volume()`，
  没有回读比对。an758x 的做法是 `setexpr verifyaddr $loadaddr - $filesize`
  把回读缓冲放在镜像**正下方**（放到上方会在 512 MiB 板上覆盖运行中的 U-Boot 自己）。
  本项目恢复缓冲在 `gd->ram_base + 0x10000000`，回读区同样应取 `recovery_addr - filesize`。
  这条改动落在**写路径**上，出错就是变砖，迄今没有盲改。
- **BL2 / FIP / 板级数据独立目标**：本项目是 chainloader 方案，只有
  "firmware（UBI `fit` 卷）" 和 "uboot（raw slot）" 两个目标，语义上不需要 BL2/FIP。
- **env 的 HTTP 读写**：an758x 有 `HTTP_JOB_ENV`。本项目恢复页的"完全重建"
  会重置 env，暂时没有逐项编辑的入口。

---

## 4. DHCP：为什么本项目"经常要手动设 IP"

对照 `D:\GitData\uboot-an758x\net\lwip\httpd-dhcp.c`（367 行，独立文件，UP PCB 绑 67）
与本项目 `net/lwip/httpd_recovery.c` 里的 DHCP 段。

### 4.1 架构差异（"本项目"列 = **改动前**）

| | 本项目（改动前） | an758x |
|---|---|---|
| 地址分配 | **单一固定地址** `192.168.0.2`，所有客户端共用；无租约表 | **16 条租约表**，按 `chaddr` 分配；池可配置 |
| REQUEST 判定 | option 50 / ciaddr ≠ 固定地址 → **NAK** | 先按 MAC 找租约；地址不在池内才 NAK；DISCOVER 要不到就退回池内任一空闲地址 |
| DHCPRELEASE | 不处理 | 处理，释放租约 |
| 收包路径 | **两条**：UDP PCB 绑 67 + `net_lwip_dispatch_recovery_dhcp()` raw 兜底（在 `net_lwip_rx()` 里逐帧手工解析 VLAN/IP/UDP，`src=68→dst=67` 就直调 `recovery_dhcp_recv`） | 一条：UDP PCB 绑 67 |
| 入端口过滤 | `airoha_recovery_dhcp_rx_allowed()` 按 `recovery_port` 只认 fport 1/4，**不匹配就静默丢弃** | 无端口过滤 |
| BOOTREPLY `secs` | `= req->secs`（回显） | 结构体 memset 0 |

### 4.2 "拿不到 IP"的三条真实成因

**① 单一固定地址 + 一律 NAK（协议层，最主要）**

Windows 记住了别的网络的租约后会先发 `DHCPREQUEST`(init-reboot)，option 50 不是
`192.168.0.2` → 本项目直接 NAK。连续几次后 Windows 放弃并退回 `169.254.x.x`。
两台主机同时来（Windows + 虚拟机网桥就够）会抢同一个 `.2`，ARP 重复地址检测同样
把后者踢到 APIPA。两者从外面看都是"必须手动设 IP"。

**② raw 兜底路径把包吃掉了**

`net_lwip_rx()` 里 `net_lwip_dispatch_recovery_dhcp()` 返回 true 就 `continue`，
包**不会**进 `netif->input()`。所以一旦 hook 注册，绑在 67 上的 UDP PCB
实质是死路，真正的收包全靠 raw 解析 —— 这也是为什么驱动层要额外维护
`last_rx_fport` 去"猜"入端口（raw 路径拿不到 lwIP 的 netif 信息）。
顺带一个好处：raw 路径是逐帧同步的，处理某个 DHCP 帧时 `eth->last_rx_fport`
**就是该帧自己的入端口**。

**③ 端口策略静默丢包**

`recovery_port` 决定只认哪个口：`wan`→fport 2、`10g/lan1/4`→fport 4、
`1g/lan2/lan3/1`→fport 1、`auto`（未设置）→ 1 或 4。PC 插的口不在允许集合里
就**一行日志都没有**。更麻烦的是 `airoha_rx_sport_to_recovery_fport()`：
交换机对 lan2/lan3 可能上报 CPU 侧或未映射的 SPORT，只在 `auto` 或显式 `1g` 时
兜底成 fport 1；一旦有人把 `recovery_port` 设成 `lan1`(10G) 而 PC 插在 1G 口 → 永远不回。

### 4.3 已落地的改动

1. **租约表**（对齐 an758x 模型，放在 `struct recovery_dhcp_server` 里）：
   - 池默认 `192.168.0.2 – 192.168.0.50`，第一个客户端仍拿 `.2`
     （兼容现有文档和固定客户端）；可用 env `recovery_dhcp_start` / `recovery_dhcp_end` 放宽。
   - `recovery_dhcp_alloc_lease()` 跳过服务器自身地址；
     DISCOVER 先按 MAC 找已有租约，再按 option 50 分配，最后退回池内任一空闲地址。
   - `recovery_dhcp_resolve_request()` 取代原来的 `recovery_dhcp_classify_request()`：
     池内地址 → ACK（续租或重分配）；池外地址 → NAK（让客户端回到 DISCOVER，这是标准行为）；
     没有 option 50 也没有租约（Windows 续租的常见形态）→ 直接分配。
   - `DHCPRELEASE` 释放租约；OFFER 60 s（`RECOVERY_DHCP_OFFER_HOLD_MS`）未跟 REQUEST
     自动回收；ACK 后租期 24 h。
2. `BOOTREPLY` 的 `secs` 置 0（RFC 2131 Table 3：`secs` 是客户端字段）。
3. **端口策略丢包不再静默**：新增 `airoha_recovery_last_rx_fport()`，被过滤时限流打印
   `DHCP: request ignored by port policy (recovery_port=..., rx fport=N)`。
   端口策略本身（不在 WAN 口回 DHCP）保留 —— 那是真实的安全需求。
4. README 增加 "DHCP Server" 一节，说明池范围、env 覆盖、诊断行的含义，
   以及手动设 IP 时应避开池（例如用 `192.168.0.100`）。

### 4.4 没动的部分

- **raw 兜底 vs UDP PCB 双路径**：能跑，且 raw 路径是唯一真正生效的；
  改成单路径需要确认 lwIP 在 netif 未完全 up / 广播包场景下的收包行为，风险不低。
- **`recovery_port` 的默认值与兜底逻辑**：保留现状，只加了可观测性。
  若现场常见"插 1G 口没反应"，优先查 `recovery_port` 是否被设成 `lan1`/`10g`。

### 4.5 启动时链路 flap 的"黑洞窗口"（本轮修复）

**成因（协议层之外的第四个成因，也是"要拔插几次才有 IP"的直接原因）：**
`airoha_recovery_restart_links()`（airoha_eth.c）在 DHCP/HTTP 就绪**之后**才把
LAN/10G PHY 断电重来，而且旧实现是**同步死等**：`mdelay(recovery_lan_flap_ms=1500)`
→ 上电 → `mdelay(recovery_lan_up_ms=2000)` 盲等 settle。这两次 `mdelay` 把恢复
主循环整个堵住：`net_lwip_rx()` 不跑（不收包、不跑 `sys_check_timeouts`），
约 3.5 s 内客户端的 DISCOVER/REQUEST 到不了或没人处理；盲等 2 s 也不保证
自协商真的完成，第一次 DHCP 回复仍可能发进一个还没就绪的数据通路——客户端
收不到，按退避重试，外观就是"拔插几次才拿到 IP"（PC 记着别网段的旧租约时
还要多走一轮 NAK→DISCOVER，更容易撞进窗口）。

**修复（`airoha_recovery_flap_service()`，非阻塞状态机）：**
- `restart_links()` 只做"立即断电 + 登记截止时间"然后返回，主循环不再被堵；
- 上电由主循环（`airoha_recovery_poll_link()` 每轮调用）在截止时刻执行，
  GDM4 立即 prime，10G 通路在等待期间持续训练；
- "settle"从盲等改为**真实链路状态等待**（BMSR/STAT1，50 ms 轮询），
  `recovery_lan_up_ms` 退化为超时兜底；按端口打印就绪状态。
- flap 进行中暂停 `airoha_recovery_retry_pending_wakes()`，避免上电时机被抢。

**新日志形态**（现场判断链路就绪时间用）：

```
airoha: restarting recovery links after network services are ready (down 1500ms, non-blocking)
airoha: recovery links powered up, waiting for link
airoha: recovery links up after 60ms (lan up, 10g up, wan n/a)
```

**可调 env（语义不变）**：`recovery_link_flap=0` 关闭 flap；
`recovery_lan_flap_ms`（断电时长，默认 1500）、
`recovery_lan_up_ms`（等 link 的超时，默认 2000）。

**NAK 诊断增强**（`httpd_recovery.c`）：NAK 时打印客户端请求的地址，
现场可直接区分"PC 记着别网段的旧 IP"和"池耗尽"：

```
DHCP: NAK to 38:a7:46:37:ee:65 (wanted 192.168.1.2)
```

### 4.6 非阻塞 flap 带来的回归：flap 期间把帧发进未就绪的 PHY（本轮修复）

**现场现象**：非阻塞 flap 生效（无冻结）后，1G 口反而**彻底拿不到 IP**——
日志稳定停在 DISCOVER→OFFER 循环，客户端始终不 REQUEST；而
`recovery links ready, link timeout after 2000ms (lan down, 10g down, wan n/a)`
说明 flap 结束时链路被读为 down。同一台机器**手动配置 192.168.0.2 可以打开恢复页**，
即数据面收发双向都是通的。

**根因（回归）**：4.5 的修复把主循环解冻了，但 **`airoha_eth_send()` 在 flap
进行期间照常发包**。旧实现用 `mdelay()` 冻结主循环，等价于"PHY 就绪前一个帧都不发"；
解冻后，客户端在掉电窗口内重发的 DISCOVER 会被**立即**回复，而这条 OFFER 被送进
正在掉电/尚未完成自协商的 PHY，MAC 直接丢弃——客户端收不到，于是无限重发 DISCOVER。
旧代码只是"把发包推迟到 settle 之后"，所以最终能成；新代码把这个隐含保证删掉了。

**修复**：`airoha_eth_send()` 开头新增

```c
if (eth->recovery_flap_active)
    return -EAGAIN;
```

保留非阻塞主循环（RX/HTTP/lwIP 超时照跑），但**在 flap 完成前抑制以太网发送**，
把旧代码"PHY 就绪前不发包"的性质显式化。flap 结束后（就绪或超时）立即恢复发送，
客户端下一次 DISCOVER 就能拿到 OFFER。

**新增诊断**：DISCOVER/REQUEST 日志带入口端口，现场一眼看出客户端从哪个 fport 进来
（auto 模式只接受 fport 1/4，fport 2 会被端口策略静默丢弃）：

```
DHCP: DISCOVER from 38:a7:46:37:ee:65 (rx fport 1)
DHCP: REQUEST from 38:a7:46:37:ee:65 (rx fport 1)
```

**现场可零刷机验证**：`setenv recovery_link_flap 0` 后重启进恢复模式——
若 DHCP 立即正常，则确认是 flap（掉电重来）本身导致，而非端口/协议问题。
（§4.9 起 flap **默认就是关的**，无需再手动设这个 env；要复现旧行为才用 `recovery_link_flap 1`。）

> 注：现场那版日志版本串是 `gecc838e778f7-dirty`，即用**有未提交改动的源码**编的，
> 不能保证与本提交一致；复现请先 `git status` 确认干净后重新构建。

### 4.7 真机复查：广播回复送不到，改为按客户端 MAC 单播补发（本轮修复）

§4.6 的"flap 期间抑制发送"是必要的，但**不足以解决**现场问题。上机后 `g76494d4…` 日志显示：

```
airoha: restarting recovery links after network services are ready (down 1500ms, non-blocking)
airoha: recovery links powered up, waiting for link
airoha: recovery links ready, link timeout after 2000ms (lan down, 10g down, wan n/a)
DHCP: DISCOVER from 38:a7:46:37:ee:65 (rx fport 1)
DHCP: sent OFFER to 38:a7:46:37:ee:65 (offered 192.168.0.2)
...（循环）
```

**关键推断**：DISCOVER 已带入口端口 `rx fport 1`，说明客户端确实插在 1G 口、服务器也接受并回复了；
而 Windows 一直停在"正在识别"。若客户端**收到过** OFFER，它必然要么发 REQUEST（会打印
`DHCP: REQUEST from`）、要么发 DHCPDECLINE（会打印 `unknown msg type 4`）——日志里两者都没有
⇒ **客户端根本没收到 OFFER**。结合"手动配 192.168.0.2 能开恢复页"（那是普通 L2 **单播**），
结论是：**本机 CPU→1G 口的广播路径不能把回复送达主机，而单播路径是好的。**

**修复**（`net/lwip/httpd_recovery.c`）：保留原广播发送（满足要求广播的客户端），**再补发一份
L2 单播**——目标为客户端自己的 MAC：
- 临时用 `etharp_add_static_entry(yiaddr → req->chaddr)` 建立静态 ARP，
  让 lwIP 直接生成"IP 目的 = 分配地址、L2 目的 = 客户端 MAC"的单播帧，
  不必等未配置 IP 的客户端回 ARP；
- `udp_sendto_if_src()` 发出后立即 `etharp_remove_static_entry()` 复原；
- 仅在有分配地址（OFFER/带地址的 ACK）时补发，NAK/INFORM 仍只广播。

单播帧会走 `airoha_pick_packet_tx_fport()` → 学到的 peer fport（= 1）→ `send_on_fport(…,1)`，
正是与静态地址可访问相同的、已被证明可用的路径。

**依赖配置**：`etharp_add_static_entry()`/`etharp_remove_static_entry()` 仅在
`ETHARP_SUPPORT_STATIC_ENTRIES` 打开时存在，因此在
`lib/lwip/u-boot/lwipopts.h` 增加 `#define ETHARP_SUPPORT_STATIC_ENTRIES 1`
（该端口文件的 1 行改动，默认 `LWIP_DEBUG` 关闭故不会引入 ARP 调试刷屏）。
遗漏这个 define 会让 CI 以 `-Werror=implicit-function-declaration` 失败。

**状态**：已编译通过在 CI（run 38912198535 ✅），**真机效果待验证**。

> ⚠️ 结论修正：§4.7 的单播补发**不是根因修复**，只是绕过。
> `g0d90131…` 上机后现象完全不变，说明单播补发没有解决问题（下面的 §4.8 才是根因）。
> 单播补发保留（无害，且对 10G 通路有用），但真正的修复在 §4.8。

### 4.8 交换机 flood map 把 CPU 发出的广播全部丢掉（本轮修复，**根因**）

**现场现象（`g0d90131…-dirty`，即 §4.7 的单播补发已生效的那一版）**：

```
airoha: recovery links ready, link timeout after 2000ms (lan down, 10g down, wan n/a)
DHCP: DISCOVER from 38:a7:46:37:ee:65 (rx fport 1)     ← 客户端广播上得来
DHCP: sent OFFER to 38:a7:46:37:ee:65 (offered 192.168.0.2)   ← 服务器也发出去了
...（无限循环，客户端始终不 REQUEST）
```

同时现场确认：**手动把 PC 设成 192.168.0.2 能打开恢复页**。

**根因**：`airoha_switch_recovery_runtime_init()`（`airoha_eth.c`）把
`SWITCH_MFC` 的三个 flood 端口图写成了 **CPU 端口位**：

```c
/* 修复前 */
airoha_switch_wr(eth, SWITCH_MFC,
                 FIELD_PREP(SWITCH_BC_FFP, cpu_port_mask) |   /* 只有 BIT(6) */
                 FIELD_PREP(SWITCH_UNM_FFP, cpu_port_mask) |
                 FIELD_PREP(SWITCH_UNU_FFP, cpu_port_mask));
```

而同一函数后面把各端口的出口矩阵写成：

| 端口 | `SWITCH_PCR(n).PORT_MATRIX`（可出口集合） |
|---|---|
| CPU（6） | `user_port_mask` = `GENMASK(5,0)` = 端口 0..5 |
| 前面板 1/2 | `cpu_port_mask` = 只有端口 6 |

交换机对**被泛洪的帧**（广播 / 未知组播 / 未知单播）实际投递的端口 =
**flood 端口图 ∩ 入端口矩阵**。于是：

- 客户端广播从端口 1 进来：`{6} ∩ {6}` = `{6}` → **送到 CPU**（所以日志里有 DISCOVER）；
- 服务器广播从 CPU 进来：`{6} ∩ {0..5}` = **空集** → **在交换机内部被丢弃**，
  永远到不了前面板。

⇒ **凡是 CPU 发起的泛洪帧全部黑洞**：DHCP 的 OFFER/ACK（目的地址
255.255.255.255，`reply->flags` 强制置了 0x8000 广播位）、ARP 请求、未知单播。

**为什么"手动设静态 IP 能用"完全吻合**：静态地址走的是普通**单播**，
交换机按 FDB 学到的端口直接转发，**不经过 flood 端口图**——所以单播通、广播不通。
这也解释了 §4.7 里为什么单播补发也救不回来：单播能到，但客户端要的是**广播 OFFER**
来推进 DHCP 状态机；而且真正的 DHCP 广播 ACK 仍然死在交换机里。

**为什么客户端既不 REQUEST 也不 DHCPDECLINE**：两者都要求它先收到 OFFER。收不到 ⇒ 重发 DISCOVER。

**修复**（对齐 an758x，它写的就是全端口掩码）：

```c
/* 修复后 */
u32 flood_port_mask = GENMASK(7, 0);
airoha_switch_wr(eth, SWITCH_MFC,
                 FIELD_PREP(SWITCH_BC_FFP, flood_port_mask) |
                 FIELD_PREP(SWITCH_UNM_FFP, flood_port_mask) |
                 FIELD_PREP(SWITCH_UNU_FFP, flood_port_mask));
```

**为什么必须包含 CPU 端口（不能只写 `user_port_mask`）**：
前面板端口的矩阵是 `cpu_port_mask`，若 flood 图不含端口 6，
`客户端广播 → CPU` 的路也会被一起切断（`{0..5} ∩ {6}` = 空）。所以要比矩阵更宽，
让**矩阵去负责限制**；CPU 端口自己的矩阵只有 0..5，因此本机广播不会自环回自己的 RX ring。

修复后 `SWITCH_MFC` 的期望值从 `0x40404000` 变为 **`0xffffff00`**。

**现场可零刷机验证**：进入恢复模式后在提示符执行 `rtl8261_diag`，
看 `rtl8261: cmd switch mfc=` 一行——`mfc=ffffff00` 即已生效（旧版为 `40404000`）。

### 4.9 链路 flap 默认关闭，且不再给 RTL8261 掉电（本轮修复）

**新现象**：上机后除了 1G 仍拿不到 IP，**10G 口直接不连接了**（此前是能连接/能用的）。

**根因**：`airoha_recovery_restart_links()` 的 flap 会把 **RTL8261 10G PHY 掉电再上电**：

```c
if (cycle_10g) {                       /* auto 模式恒为真 */
        phy5_cycle = true;
        eth->rtl8261_phy5_wake_pending = true;
        airoha_recovery_rtl8261_set_power(eth, RTL8261_PHY5_ADDR, false);  /* LPOWER */
}
```

日志 `...(lan down, 10g down, wan n/a)` 里的 `10g` 就是 `BIT(1)` 被置位，
即**那一次现场运行确实给 PHY5 掉过电**。

而 RTL8261 只有在 `airoha_rtl8261_minimal_init()`（probe 期，走 `arht-mdio`）
做过固件补丁 + serdes 模式设置之后才转发帧；
`airoha_switch_recovery_runtime_init()` 的注释明确写了它 **"avoids PHY resets and
RTL8261 patching"**。清 `LPOWER` + 重启自协商**不会**重做那套设置，
于是 PHY 回来了但 serdes 不在 USXGMII 模式 → **口再也不连接，只能冷启动恢复**。

**修复**：
1. **flap 默认关闭**（`airoha_recovery_link_flap_enabled()` 无 env 时返回 false；
   需要时 `setenv recovery_link_flap 1` 显式打开）。
2. RTL8261（PHY5/PHY8）**永不参与 flap**：原来的 PHY5/PHY8 掉电分支删除，
   `recovery_flap_mask` 只剩 `BIT(0)`（1G PHY）。
   即使有人打开 flap，也只动 1G 铜口。
3. GDM4/USXGMII 的链路训练（`airoha_gdm4_recovery_prime()`）**移出 flap 开关**，
   与 flap 是否启用无关，保证 10G 通路一定会被 prime。

**为什么可以不要 flap**：flap 的本意是"让已经连着的 PC 看到一次断链、重新发起 DHCP"。
但（a）§4.8 才是 1G 拿不到 IP 的真正原因；（b）板子上电时硬件本来就会复位 PHY，
PC 一定会看到链路变化并自行发起新的 DHCP；（c）an758x **完全没有 flap**，恢复一样正常。
而 flap 的代价是：1.5 s 掉电窗口 + ≥2 s settle 正好压在 PC 发起 DHCP 的时刻，
且 `airoha_eth_send()` 在 `recovery_flap_active` 期间直接 `return -EAGAIN`，把最初的几个回复丢掉。

**遗留风险（未改，需现场判断）**：`airoha_recovery_power_down_wan_phy()` 在
非 WAN 模式（auto/1G）下**仍然会对 PHY8（WAN RTL8261）掉电**，
与上面 1G/10G 是同一类隐患——WAN 口可能在进过一次恢复模式后就不再连接。
本次未动它（属于既有行为，用于"把物理 WAN 流量挡在恢复数据通路之外"）。
如果现场确认 WAN 口也不连接，应改用"不动 PHY、只在端口矩阵/RX 侧过滤"的方式实现该目的。

---

## 5. 槽位体积实测

### 5.1 分区与上限

`RECOVERY_MAX_UBOOT_SIZE = 1 MiB`（`httpd_recovery.c:100`），
分区 `chainloader@0x600000` 大小同为 `0x100000`（`dts/upstream/.../xr1710g.dts:168-172`）。
写入目标由 env 决定（`httpd_recovery.c:2095-2111`）：`recovery_dev_uboot="spi-nand0"`
= **整颗 NAND**，偏移 `uboot_ofs=0x600000`，再被 `recovery_size_uboot=0x100000`
与 `RECOVERY_MAX_UBOOT_SIZE` 二者较小值夹住。

> ⚠️ 关键结论：**上限不是由设备树分区算出来的**，而是 env + 宏。
> 所以单独把设备树分区改成 2 MiB **不会**放宽上传上限；
> 反过来，只放宽 env/宏而不动设备树，则 1 MiB 以上的镜像会**压到 `system`**。

### 5.2 实测产物（CI run 38912198535，commit `0d90131`）

`xr1710g-chainloader-20261016-135953-g0d90131373e4-slot.bin` = **1,001,522 字节（978.0 KiB）**

| 偏移 | 内容 | 字节 |
|---|---|---|
| `0x0000` | legacy bootm shim uImage | 4,312 |
| `0x2100` | chainloader FIT（含其头部） | 993,074 |
| | **合计** | **1,001,522** |

FIT 内部（`compression` 全部为 `none`）：

| 组件 | 说明 | 字节 | 占比 |
|---|---|---|---|
| `fdt@1` | 控制 DTB | 266 | 0.03% |
| `kernel@1` | chainloader shim | 8,632 | 0.9% |
| **`uboot@1`** | **二级 U-Boot 本体** | **982,768** | **98.1%** |
| | FIT 结构/字符串/哈希 | ~1,408 | 0.1% |

### 5.3 余量与趋势

- 余量 = 1,048,576 − 1,001,522 = **47,054 字节（45.9 KiB，占分区 4.5%）**。
- 趋势：README 记录的上一版是 914,938 字节（余量 ~120 KiB），
  恢复页 + DHCP 诊断一轮就吃掉 **~85 KiB**。按这个速度，
  再一轮功能改动就会撞上构建脚本的硬闸（`MAX_SLOT_SIZE`，超限直接 CI 失败）。
- 已知可控的体积项（用于判断"是否必须扩容"）：
  - 内嵌恢复页：`htdocs/` 共 72,946 字节（`index.html` 68,805）；
    只占槽位 **~7%**，即使压缩也只省十几 KiB。
  - `printf` 诊断字符串：都在 `.rodata`，进 slot，属于"随功能增长"的部分。

### 5.4 生成物纪律（最易复发）

`lib/lwip/httpd/fsdata_xr1710g.c` 是 `htdocs/` 的**生成物**，被 `lib/lwip/Makefile`
以 `-DHTTPD_FSDATA_FILE="httpd/fsdata_xr1710g.c"` 编入固件，**XR1710G 与 XG2010G 共用**。
改完 `htdocs/index.html` 必须重跑（不加 `--minify`，与历史一致）：

```sh
python lib/lwip/httpd/makefsdata.py lib/lwip/httpd/htdocs lib/lwip/httpd/fsdata_xr1710g.c
```

忘了会导致"启动后页面不是最新的"；`build.yml` 已有守卫会 CI 失败。

---

## 6. U-Boot 核心版本同步评估

### 6.1 现状

| | 版本 | 依据 |
|---|---|---|
| 本项目 | **2026.07** | `Makefile:3-4` `VERSION = 2026` / `PATCHLEVEL = 07` |
| 上游最新 | **v2026.10**（2026-10-05 发布） | u-boot 邮件列表公告 |
| 上游下一个 | v2027.01-rc1（2026-10-26） | 同上 |
| 对照树 `uboot-an758x` | **2026.10** | `D:\GitData\uboot-an758x\Makefile:4` `PATCHLEVEL = 10` |

差 **1 个发布（约 3 个月）**。U-Boot 是**季度**发布节奏（1/4/7/10 月首个周一）。

### 6.2 为什么现在不建议同步

1. **代价不在"看 diff"，在于没有祖先可 rebase。**
   本仓库历史已被压成 2 个提交（`5983ffd` 基线 + `76494d4` 开发集合），
   `git log` 里**没有任何上游祖先**、也没有 upstream remote。
   所以"同步到最新"不是 `git rebase`，而是**重新移植**：
   把 `v2026.10` 整棵树拿来，再把本地增量逐个贴回去。
2. **本地增量很大且分散**，每一个都要重新验证：
   - `drivers/net/airoha_eth.c`（6,461 行，含 §4.5/§4.6 的 flap 与发送抑制）
   - `drivers/net/airoha/pcs-*.c`（AN7581 PCS）
   - `net/lwip/httpd_recovery.c`（4,272 行，恢复服务 + DHCP + 备份）
   - `lib/lwip/` 整棵 lwIP 导入 + `lib/lwip/u-boot/lwipopts.h` 本地选项
   - `board/airoha/an7581/xr1710g_rfb.c` / `xg2010g_rfb.c` / `*.env`
   - `chainloader/`（shim 二进制 + ITS 模板 + 打包脚本）
   - `dts/upstream/`（内核 DTS 同步目录）、`htdocs/`（+ 生成物）
   - `Makefile` `UBOOTVERSION = XR1710G` 与 `scripts/setlocalversion` 的定制
3. **本机没有 aarch64 交叉工具链**，唯一真实编译验证是 CI。
   移植 + 排错只能靠"推一次、等一次 Actions"的循环，成本高。
4. **v2026.10 对本板没有必须的修复**。公告里的条目是平台更新
   （Marvell / NXP / i.MX / AMD-Xilinx / Renesas / Rockchip / STM32）、
   EFI loader / FPGA / DFU / 网络子系统的通用修复、FIT 清理，
   外加两条可能相关但都不关键项：
   - "修复某些平台启动时 reserved memory 相关的**伪 ERROR 打印**"——纯日志噪声；
   - "FIT 可校验 dm-verity roothash"——本 chainloader FIT 不用 dm-verity。
5. **当前有未闭环的功能改动**：§4.7 的单播补发还未在真机验证。
   此时做大规模机械合并，会把"未验证的功能改动"和"未验证的移植"叠在一起，
   一旦出问题无法二分。

### 6.3 建议

- **现在不同步**。1 个季度落后是产品树的正常状态。
- 需要同步时，按这个顺序做，且**单独成一个提交**：
  1. 先确认 `git status` 干净、DHCP 修复已真机闭环；
  2. 以 `v2026.10` 为基线，把 §6.2 第 2 条清单当"移植工单"逐项贴回；
  3. 只用 CI 验证，两个机型都要绿；
  4. 在真机上重点回归 **引导链路（§1.1）+ 恢复页 + DHCP + 备份下载**。
- **顺手要修的周边**：上游已从 `lists.denx.de` / `github.com/u-boot/u-boot` 迁到
  `git.u-boot-project.org/u-boot/u-boot`，`source.denx.de/u-boot` 只是重定向。
  构建/发布脚本里若还钉着旧域名，应在上次规划变更时一起改掉。

---

## 7. 分区扩容评估：1 MiB → 2 MiB

### 7.1 分区表现状（512 MiB SPI-NAND，无空闲尾部）

| 起始 | 名称 | 大小 | 属性 |
|---|---|---|---|
| `0x000000` | `bootloader` | 2 MiB | read-only |
| `0x200000` | `uenv` | 2 MiB | 二级 U-Boot 的 env 存这里 |
| `0x400000` | `dsd` | 2 MiB | vendor 板级数据 |
| `0x600000` | **`chainloader`** | **1 MiB** | read-only |
| `0x700000` | `system` | 439 MiB | `linux,ubi`（卷 `fit` / `factory`） |
| `0x1BE00000` | `reserved_bmt` | 66 MiB | read-only，厂商 BMT/BBT |

`0x600000 + 0x100000 = 0x700000`，**`chainloader` 与 `system` 是紧邻的，中间没有缝隙**。

### 7.2 改成 2 MiB 的实际影响

- **`system` 必须后移 1 MiB**（`0x700000` → `0x800000`）并缩小为 438 MiB。
  尾部 `reserved_bmt` 是厂商 BMT/BBT 预留，不能动。
- **`system` 是 UBI**：起始偏移一变，所有 LEB 的物理位置全部错位，
  旧 UBI 内容当场失效。也就是说，凡是采用**新分区表**的机器都要**重刷整机固件**
  （`fit` + `factory` 全套），不能只推一个 chainloader。
- **引导本身不受影响**：一级/二级都是**按固定偏移**读，不查分区表——
  `uboot_ofs=0x600000`、`RECOVERY_UBOOT_SLOT_DEFAULT_OFS=0x600000`、
  厂商 `flash read 0x602100 …`。所以扩容是**给 Linux/OpenWrt 侧看**的布局变更。
- **但只改 env/宏、不改分区表是危险的**：§5.1 已说明上限来自 env + 宏，
  若把 `recovery_size_uboot` 放到 2 MiB 而设备树仍是 1 MiB，
  1 MiB 以上的镜像会写进 `system` 的头部，**直接破坏 UBI**——而且这种破坏
  在恢复页上看起来是"刷机成功"。

**必须协同修改的位置**（漏一处就出问题）：

1. `dts/upstream/src/arm64/airoha/xr1710g.dts:168-176` 与 `xg2010g.dts:185-…`
   （`chainloader` 改 `0x200000`，`system` 起始改 `0x800000`、大小减 1 MiB）
2. `net/lwip/httpd_recovery.c:100` `RECOVERY_MAX_UBOOT_SIZE`（`1 MiB` → `2 MiB`）
3. `.github/workflows/build.yml:260` 的发布说明文案（现在写死"偏移 0x600000，1 MiB"）
4. `chainloader/build-chainloader-fit.sh:68` `MAX_SLOT_SIZE=$((0x100000))`
5. `board/airoha/an7581/xr1710g.env` / `xg2010g.env` 的 `recovery_size_uboot`
6. `README.md:30/115/178`、`docs/flashing-*.md` 的说明与 `flash read/erase/write` 长度
7. 使用新分区表的整机固件的 UBI 重新生成流程

### 7.3 结论：先别扩容

扩容的**技术风险可控**（后续分区不重排、偏移不变、`system` 只少 1 MiB），
但**代价是现场每台机器都要重刷整机**，而这个代价**大概率可以避免**。
真正的"槽位快满了"问题有更便宜的解，按性价比排序：

| 方案 | 省下 | 风险 | 备注 |
|---|---|---|---|
| **① 压缩 FIT 里的 `uboot@1`** | **~545 KiB** | 中（须验证厂商一级 loader 会解压 `type=firmware` 的 loadable） | 见 §7.4 |
| ② 对恢复页 `--minify` | ~15–25 KiB | 低（但与"不 minify"的历史约定冲突） | 只改生成物 |
| ③ 精简诊断 `printf` | 数 KiB | 低 | DHCP 问题闭环后顺手做 |
| ④ 扩到 2 MiB | 1 MiB | 中（布局）+ **高（现场重刷）** | 上述 7 处协同修改 |

建议：**先用 ① 换出空间，把 ④ 留到不得不做的那一天**（例如将来要塞 3 MiB 的镜像）。

### 7.4 方案 ① 的实测依据

对本轮 CI 产物中的 FIT 逐组件做了压缩实测：

| 组件 | 原始 | gzip -9 | 压缩率 | 省下 |
|---|---|---|---|---|
| `fdt@1` | 266 | 176 | 66.2% | 90 |
| `kernel@1` | 8,632 | 4,848 | 56.2% | 3,784 |
| **`uboot@1`** | **982,768** | **424,340** | **43.2%** | **558,428** |
| （参考）`uboot@1` lzma | 982,768 | 334,876 | 34.1% | 647,892 |

**预期效果**：把 `uboot@1` 与 `kernel@1` 声明为 `compression = "gzip"`
（DTB 保持 `none`，太小不值得），槽位从 978 KiB 降到 **≈429 KiB**，
余量从 46 KiB 变成 **≈595 KiB（占分区 58%）**。用 lzma 可再降到 ≈342 KiB。

**落地方式**（两处改动）：

1. `chainloader/*-chainloader.its.in`：`uboot@1` 的 `compression` 从 `"none"` 改为 `"gzip"`；
   `kernel@1` 的 `__KCOMP__` 占位符在 `build-chainloader-fit.sh:80` 已存在，
   把那里的 `none` 改成 `gzip` 即可。
2. `chainloader/build-chainloader-fit.sh`：`mkimage -f its` **不会自己压缩**
   （`tools/fit_image.c` 只把 `compression` 名字写进节点），
   所以必须先把载荷 `gzip -9` 到临时文件，再把 `__PAYLOAD__` 指向它。

**必须先在真机验证的唯一疑点**：FIT 由**厂商 ECNT/AXON U-Boot 2014.04**
（`bootcmd = flash read 0x602100 …; bootm`）解析，我们改不了它。
上游 U-Boot 里 `fit_image_load()` 对**非 kernel** 类型（含 `type=firmware` 的
loadable）会就地解压，`kernel` 则延后到 `bootm_load_os()`；
这套通用解压已经存在很多年，但 **2014.04 的 vintage 需要实测确认**。
另外该函数用 `max_decomp_len = len * 20` 映射解压缓冲
（压缩后 424 KB → 约 8.1 MiB 窗口，落在 `0x81e00000` 的载荷装入地址上），
上机时留意这块窗口是否与运行中的 U-Boot 自身内存冲突。

**验证步骤**（一次构建即可，不必等发布）：

```sh
# 1. 构建压缩版 slot（本地无法交叉编译，走 workflow_dispatch）
# 2. 取 CI 产物，确认体积从 ~978 KiB 降到 ~429 KiB
# 3. 单台设备刷入，抓启动串口日志
#    成功特征：出现 Loading kernel/uboot、无 "Error decompressing"、
#              版本横幅正确、能进 autoboot
# 4. 两个机型都过一遍，再改成默认
```

---

## 8. 验证状态

- ⚠️ **本机没有 aarch64 交叉工具链，所有 C 改动均未经本地编译验证。**
  编译验证只能靠 GitHub Actions `build.yml`（`workflow_dispatch`）。
- **CI 基线**：run **38912198535** ✅（`Build xg2010g` 56 s、`Build xr1710g` 57 s），
  对应提交 `0d90131`。
- **体积闸门**：`chainloader/build-chainloader-fit.sh:99`——
  产物 `>= 1 MiB` 直接报错退出，所以"快满了"会以 **CI 失败**的形式暴露，不会静默发出超限镜像。
- **本轮（§4.8 / §4.9）验证步骤**——一次构建即可，按顺序看：
  1. 刷入后进恢复模式，确认串口**不再出现**
     `airoha: restarting recovery links...`（flap 已默认关闭），
     且**不要**再出现 `(lan down, 10g down, ...)` 里带 `10g` 的那行；
  2. 提示符执行 `rtl8261_diag`，确认 `switch mfc=ffffff00`（旧版 `40404000`）；
  3. 1G 口插 PC，串口应出现 `DHCP: DISCOVER from ... (rx fport 1)` 紧跟
     **`DHCP: REQUEST from ...`**（有 REQUEST 才说明客户端收到了 OFFER）；
  4. 确认 10G 口恢复连接（本次回归的判据）；
  5. `xg2010g` 同样过一遍。
- **待办**：
  1. §4.8 / §4.9 的真机验证（上面 5 步）；
  2. `xg2010g_defconfig` 补齐 `BOOTDELAY=1` + `FASTMAP`（§2.3）；
  3. §7.4 压缩方案的真机验证；
  4. §4.9 末尾的 PHY8（WAN）掉电隐患：确认 WAN 口在进过恢复模式后是否还连接。
