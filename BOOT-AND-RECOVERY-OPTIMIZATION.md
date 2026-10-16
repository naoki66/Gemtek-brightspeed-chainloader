# 引导链路对比与启动/恢复优化

对比对象：

- 本项目（U-Boot 2026.07 分支，**chainloader 方案**）
- `D:\GitData\uboot-an758x`（U-Boot v2026.10，**TF-A BL2/FIP 原生方案**）

> **2026-10-16 更新**：UBI 布局已收敛为**单一 UBI 2.0**（439 MiB `system` 分区）。
> 下文出现的 `ubi` / `ubi1.5` / `ubi1.0` 与"WebUI 多布局在线切换"均为**历史状态**：
> 这两个视图在设备树里没有对应分区，选了只会回落到 `system`，已从页面与代码中移除。
> 固件上传见 `docs/flashing-xr1710g.md` §6。

---

## 1. 引导链路

### 1.1 本项目：三级串联，前两级不受我们控制

```
上电
 └─ 厂商 ECNT/AXON U-Boot 2014.04（NAND 0x0，不可改）
     bootcmd = flash read 0x602100 0x4000000 $loadaddr; bootm     ← 读 64 MiB
 └─ chainloader slot 镜像（NAND 0x600000，1 MiB，双入口）
     0x600000  legacy bootm shim      IH_MAGIC  27 05 19 56
     0x602100  chainloader FIT        FDT_MAGIC d0 0d fe ed
 └─ FIT 内嵌二级 U-Boot 本体           CONFIG_TEXT_BASE=0x81E00000
```

二级 U-Boot 内部（`board/airoha/an7581/an7581_rfb.c` + `board/airoha/an7581/xr1710g.env`）：

```
env 从 UBI 读取（CONFIG_ENV_IS_IN_UBI, ubi:ubootenv / ubootenv2, REDUNDANT）
  └─ 第 1 次 UBI attach（全盘扫描）
board_late_init()                       an7581_rfb.c:653
  ├─ xr1710g_sync_runtime_ethaddrs()    读 vendor DSD
  ├─ xr1710g_detect_ubi_part()          :402  依次试 ubi / ubi1.5 / ubi1.0
  ├─ xr1710g_sync_factory_part()        :445  DSD→factory 卷比对，不同则写回
  └─ recovery_trigger(env) 或 reset 键 → run_http_recovery()（阻塞）
autoboot
  bootcmd            = run boot_ubi || http_recovery
  boot_ubi           = ubi part <探测到的分区> && run boot_production
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

差异一览：

| 维度 | 本项目 | an758x |
|---|---|---|
| 一级引导 | 厂商 ECNT `bootm` + chainloader FIT | TF-A BL2 → FIP |
| UBI fastmap | ❌ 无（改动前） | ✅ `MTD_UBI_FASTMAP` + `AUTOCONVERT` |
| bootdelay | 3 | 3 + `AUTOBOOT_MENU_SHOW`（还会显示菜单，更慢） |
| 一级读取量 | **64 MiB**（slot 镜像仅 ~0.9 MiB） | 不适用 |
| 启动期 UBI attach | env 1 次；1.5/1.0 设备探测时可能再 1~2 次 | 1 次 |
| 启动期写 flash | `factory` 同步（每次都跑，不一致就写） | 无 |
| 恢复服务 | `net/lwip/httpd_recovery.c`（3306 行）+ 内置 DHCP | `net/lwip/httpd.c`（1882 行）+ `httpd-dhcp.c` / `httpd-led.c` |
| 布局选择 | ✅ WebUI 选 UBI 2.0 / 1.5 / 1.0 | ❌ 单一布局 |
| 软件触发恢复 | ✅ `recovery_trigger` env（LuCI 下发） | ❌ 只有按键 |
| 备份下载 | ❌ 无（改动前） | ✅ `/api/download` + 存储目录 + 板级数据 |
| UBI 写入回读校验 | ❌ 无（只有 raw MTD 逐块校验） | ✅ `ubi_verify_*` + `verifyaddr=loadaddr-filesize` |

**本项目相对 an758x 的既有优势**：多 UBI 布局在线切换、`recovery_trigger` 软件触发、
四色彩虹呼吸灯效（an758x 的 `httpd-led.c` 是反向移植自本项目）——这些保留不动。

---

## 2. 启动速度

### 2.1 瓶颈排序（按量级）

| # | 位置 | 开销 | 归属 |
|---|---|---|---|
| 1 | 厂商 `flash read 0x602100 0x4000000` | 读 64 MiB，实际只需 ~0.9 MiB | 厂商 env，我们改不了代码 |
| 2 | `ubi read fit` | 整个 fit 卷（数十 MiB）搬进 RAM | 不可避免（`bootm` 需要完整 ITB） |
| 3 | UBI attach 全盘扫描 | 0x1B700000 / 128 KiB ≈ **3500 个 PEB**，逐个读 EC/VID 头 | ✅ 已优化 |
| 4 | bootdelay | 3 s 空等 | ✅ 已优化到 1 s |
| 5 | 1.5/1.0 设备的布局探测 | 最多 3 次 attach（只有 `-ENOMEM` 才继续） | 待优化 |

`board_late_init()` 里的 `xr1710g_sync_factory_part()` 已核过：两次 24 KiB 读 + DSD 读，
绝对开销在 10 ms 量级，**不是瓶颈**；但它保留了"每次启动都可能写一次 flash"的面，
建议后续只在恢复模式或 `factory` 卷缺失时执行。

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

2. **`README.md`**：在 "ECNT Stock U-Boot Prompt" 一节加了 boot-time 说明，
   把一级 `bootcmd` 的长度从 `0x4000000` 改成 `0x100000`：
   ```sh
   setenv bootcmd 'flash read 0x602100 0x100000 $loadaddr; bootm $loadaddr'
   saveenv
   ```
   双入口 slot 镜像在 `0x602100` 起的 1 MiB 内完整，64 MiB 只是厂商默认值。

### 2.3 未做（附原因）

- **把布局探测结果缓存进 env**：env 本身就在 UBI 里（`env_ubi_get_part()` 又依赖
  `xr1710g_detect_ubi_part()`），存在循环依赖，需要另找持久化位置。
- **改厂商 env**：只能手工在 ECNT 提示符下执行，写进 README，不做自动改写。
- **`iminfo` 校验**：an758x 在 `ubi_read_production` 里带 `iminfo`，校验完整但会
  多花一次全镜像哈希计算；本项目启动路径不加，保持启动速度。

---

## 3. 恢复与备份能力

### 3.1 差距（对照 an758x）

an758x 的 httpd 是**读写双向**的：`HTTP_JOB_BL2 / FIP / BOARD_DATA / FIRMWARE /
REBUILD / ENV / NAND_SCRUB` + `HTTP_STORAGE` 备份请求 + `/api/download/<id>/<off>/<len>`
分段下载 + `build_storage_catalog()` 目标枚举。
本项目改动前**只能写，不能读**——一旦 `factory`（MAC / Wi-Fi EEPROM）或 `ubootenv`
被清掉，且事先没有备份，机器就救不回来了。

### 3.2 已落地：只读备份下载

新增三个端点（`net/lwip/httpd_recovery.c`）：

| 端点 | 作用 |
|---|---|
| `GET /api/storage` | JSON 列出所有 MTD 分区（vendor / chainloader / ubi…）和 UBI 卷（fit / factory / rootfs_data / ubootenv…），带字节大小 |
| `GET /api/backup/mtd/<name>`<br>`GET /api/backup/ubi/<name>` | 登记一次备份，返回 `{"id","kind","name","size"}` |
| `GET /api/download/<id>/<offset>/<length>` | 流式返回该段原始字节（`Content-Disposition: <name>.bin`） |

实现要点：

- **MTD 备份保留物理偏移**：遇坏块时填 `0xff` 而不是跳过，
  这样 dump 出来的镜像可以直接用 `nandwrite` 原样写回。
  （an758x 的 `fs_read_custom()` 是同一套约定。）
- **UBI 备份是逻辑字节**：按 `ubi_volume_read()` 读 `used_bytes`，
  对应 `ubi write` 的输入语义。
- **流式，不占内存**：`file->data = NULL` + `LWIP_HTTPD_DYNAMIC_FILE_READ`，
  lwIP 通过 `fs_read_custom()` 分块拉取；UBI 侧只有 32 KiB 预读窗口。
  所以备份 437 MiB 的 `ubi` 分区不需要在 RAM 里开同样大的缓冲。
- **安全边界**：
  - 名字只允许 `[A-Za-z0-9_.-]`，长度 < 32 → JSON 无需转义，也堵掉路径穿越；
  - 单段上限 256 KiB，且 `offset + length` 不得超过登记的 `size`；
  - `id` 必须等于当前登记的备份 id，且同时只允许一个下载在飞；
  - 擦写任务进行中（`prog_phase` 1/2）直接拒绝，避免和写路径抢 flash。

配套改动：

- `lib/lwip/u-boot/lwipopts.h`：打开 `LWIP_HTTPD_DYNAMIC_FILE_READ=1`
  与 `LWIP_HTTPD_FILE_EXTENSION=1`（后者给 `struct fs_file` 加私有指针字段，
  用来在 `fs_open_custom()` / `fs_read_custom()` / `fs_close_custom()` 之间带状态）。
  已有的内存型响应（`recovery_open_custom_response()`，index/len 一次性交付）
  在这两个选项下行为不变。
- `fs_open_custom()` 开头强制 `file->pextension = NULL`——lwIP 的 `fs_open()`
  对 custom file 不会清这个字段，不清会读到上一次下载留下的野指针。
- `lib/lwip/httpd/htdocs/index.html`：恢复页底部新增"备份 / Backup"卡片
  （读取列表 → 点目标 → 分段下载 → Blob 另存为 `<name>.bin`），中英文齐全。
- `mock_server.py`：同步 mock 了这三个端点，`python mock_server.py`
  打开 http://127.0.0.1:8080 即可本地验证 UI 与下载流程。
- `lib/lwip/httpd/fsdata_xr1710g.c`：已用 `makefsdata.py` 重新生成
  （index.html 43.4 KB → 50.8 KB，fsdata C 文件 245.8 KB → 282.9 KB）。

### 3.3 未做（附原因）

- **UBI 写入回读校验**。本项目 raw MTD 写入有逐擦除块校验
  （`recovery_mtd_verify_write()`，httpd_recovery.c:1813），
  但 `recovery_write_ubi_target()`（:2395）写完只做 `ubi_check_volume()`，没有回读比对。
  an758x 的做法是 `setexpr verifyaddr $loadaddr - $filesize` 把回读缓冲放在镜像
  **正下方**（放到上方会在 512 MiB 板上覆盖运行中的 U-Boot 自己）。
  本项目恢复缓冲在 `ram_base + 0x10000000`，回读区同样应取 `recovery_addr - filesize`。
  这条改动落在**写路径**上，出错就是变砖，本次没有盲改。
- **BL2 / FIP / 板级数据独立目标**：本项目是 chainloader 方案，只有
  "firmware（UBI fit 卷）" 和 "uboot（raw slot）" 两个目标，语义上不需要 BL2/FIP。
- **env 的 HTTP 读写**：an758x 有 `HTTP_JOB_ENV`。本项目恢复页的"完全重建"
  会重置 env，暂时没有逐项编辑的入口。

---

## 4. DHCP：为什么本项目"经常要手动设 IP"

对照 `D:\GitData\uboot-an758x\net\lwip\httpd-dhcp.c`（367 行，独立文件，UP PCB 绑 67）
与本项目 `net/lwip/httpd_recovery.c` 里的 DHCP 段。

### 4.1 架构差异

| | 本项目 | an758x |
|---|---|---|
| 地址分配 | **单一固定地址** `192.168.0.2`（`RECOVERY_DHCP_CLIENT_IPADDR`），所有客户端共用；无租约表 | **16 条租约表**，按 `chaddr` 分配；池由 `network \| CONFIG_HTTPD_DHCP_POOL_START..END`（或 env `httpd_dhcp_start/end`）算出 |
| REQUEST 判定 | option 50 / ciaddr ≠ 固定地址 → **NAK** | 先按 MAC 找租约；地址不在池内才 NAK；DISCOVER 要不到就退回池内任一空闲地址 |
| DHCPRELEASE | 不处理 | 处理，释放租约 |
| 收包路径 | **两条**：UDP PCB 绑 67 + `net_lwip_dispatch_recovery_dhcp()` raw 兜底（在 `net_lwip_rx()` 里逐帧手工解析 VLAN/IP/UDP，`src=68→dst=67` 就直调 `recovery_dhcp_recv`） | 一条：UDP PCB 绑 67 |
| 入端口过滤 | `airoha_recovery_dhcp_rx_allowed()`（airoha_eth.c:1680）按 `recovery_port` 只认 fport 2/4/1，**不匹配就静默丢弃** | 无端口过滤 |
| BOOTREPLY `secs` | `= req->secs`（回显） | 结构体 memset 0 |

### 4.2 "拿不到 IP"的三条真实成因

**① 单一固定地址 + 一律 NAK（协议层，最主要）**

Windows 记住了别的网络的租约后会先发 `DHCPREQUEST`(init-reboot)，option 50 不是
`192.168.0.2` → 本项目直接 NAK。连续几次后 Windows 放弃并退回 `169.254.x.x`。
两台主机同时来（Windows + 虚拟机网桥就够）会抢同一个 `.2`，ARP 重复地址检测同样
把后者踢到 APIPA。两者从外面看都是"必须手动设 IP"。

**② raw 兜底路径把包吃掉了**

`net_lwip_rx()`（net-lwip.c:504）里 `net_lwip_dispatch_recovery_dhcp()` 返回 true 就
`continue`，包**不会**进 `netif->input()`。所以一旦 hook 注册，绑在 67 上的 UDP PCB
实质是死路，真正的收包全靠 raw 解析 —— 这也是为什么驱动层要额外维护
`last_rx_fport` 去"猜"入端口（raw 路径拿不到 lwIP 的 netif 信息）。
顺带一个好处：raw 路径是逐帧同步的，处理某个 DHCP 帧时 `eth->last_rx_fport`
**就是该帧自己的入端口**（`airoha_eth_recv_qdma()` 返回一帧就被立刻处理）。

**③ 端口策略静默丢包**

`recovery_port` 决定只认哪个口：`wan`→fport 2、`10g/lan1/4`→fport 4、`1g/lan2/lan3/1`→fport 1、
`auto`（未设置）→ 1 或 4。PC 插的口不在允许集合里就**一行日志都没有**。
更麻烦的是 `airoha_rx_sport_to_recovery_fport()`（:1736）：交换机对 lan2/lan3 可能上报
CPU 侧或未映射的 SPORT，只在 `auto` 或显式 `1g` 时兜底成 fport 1；
一旦有人把 `recovery_port` 设成 `lan1`(10G) 而 PC 插在 1G 口 → 永远不回。

### 4.3 已落地的改动

1. **租约表**（对齐 an758x 模型，放在 `struct recovery_dhcp_server` 里）：
   - 池默认 `192.168.0.2 – 192.168.0.50`，第一个客户端仍拿 `.2`
     （兼容现有文档和固定客户端）；可用 env `recovery_dhcp_start` / `recovery_dhcp_end` 放宽。
   - `recovery_dhcp_alloc_lease()` 跳过服务器自身地址；
     DISCOVER 先按 MAC 找已有租约，再按 option 50 分配，最后退回池内任一空闲地址。
   - `recovery_dhcp_resolve_request()` 取代原来的 `recovery_dhcp_classify_request()`：
     池内地址 → ACK（续租或重分配）；池外地址 → NAK（让客户端回到 DISCOVER，这是标准行为）；
     没有 option 50 也没有租约（Windows 续租的常见形态）→ 直接分配。
   - `DHCPRELEASE` 释放租约；OFFER 60 s 未跟 REQUEST 自动回收；ACK 后租期 24 h。
2. `BOOTREPLY` 的 `secs` 置 0（RFC 2131 Table 3：`secs` 是客户端字段）。
3. **端口策略丢包不再静默**：新增 `airoha_recovery_last_rx_fport()`
   （`drivers/net/airoha_eth.c` + `include/airoha_eth.h`），被过滤时限流打印
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

> 注：现场那版日志版本串是 `gecc838e778f7-dirty`，即用**有未提交改动的源码**编的，
> 不能保证与本提交一致；复现请先 `git status` 确认干净后重新构建。

---

## 5. 体积与验证状态

- 槽位上限 `RECOVERY_MAX_UBOOT_SIZE = 1 MiB`；本机上次产物
  `xr1710g-uboot-20260811-dhcp-wan-ui-flash-slot.bin` = **914938 字节**，
  本次新增约 17 KB（HTML ~7.4 KB + C 代码 ~10 KB），仍有 ~120 KB 余量。
- ⚠️ **本机没有 aarch64 交叉工具链，本次所有 C 改动未经编译验证。**
  请在有工具链的环境或 GitHub Actions（`build.yml`，`workflow_dispatch`）上构建。
- 离线校验脚本 `.workbuddy/verify_recovery_backup.py` 全 PASS，覆盖：
  defconfig/lwipopts 配置接线、三个端点路由与读写语义、坏块填 0xff、
  并发与 busy 保护、C 括号与 `#if/#endif` 配平、页面 i18n 键完整性、
  生成的 fsdata 与 `htdocs/index.html` 字节一致、mock server 可编译。
