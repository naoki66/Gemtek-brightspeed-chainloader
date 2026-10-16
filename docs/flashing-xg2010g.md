# XG2010G TTL 刷机教程
# XG2010G TTL Flashing Guide

> **刷机方案 / Scheme**：保留原厂前 6 MiB（bootloader 2 MiB + uenv 2 MiB + dsd 2 MiB）不动，在偏移 **0x600000（6 MiB）** 处写入 **1 MiB chainloader**。
> Keep the stock first 6 MiB (`bootloader` + `uenv` + `dsd`) untouched, then write the **1 MiB chainloader** at offset `0x600000`.

| | |
|---|---|
| 适用机型 / Board | XG2010G |
| 刷入文件 / File to flash | `xg2010g-chainloader-<版本>-slot.bin`（唯一需要刷入的文件 / the only file to flash） |
| 下载 / Download | [Releases](https://github.com/naoki66/Gemtek-brightspeed-chainloader/releases) |
| 参考项目 / Reference | [Gemtek-brightspeed-chainloader](https://github.com/naoki66/Gemtek-brightspeed-chainloader) |

## 刷机前必读 / Before you start

**⚠️ 刷机有变砖风险，请逐步确认后再操作。**
**⚠️ Flashing can brick the device. Follow every step carefully.**

- 刷机过程不要断电、不要拔网线。Do not power off or disconnect during flashing.
- 确认固件文件与机型匹配（XG2010G 与 XR1710G 镜像不通用）。The XG2010G and XR1710G images are not interchangeable.

## 1. 准备工作 / Preparation

- USB 转 TTL 模块（3.3V，如 CH343）
  *USB-TTL module (3.3 V, e.g. CH343)*
- 杜邦线若干 / Dupont wires
- 螺丝刀（拆机用）/ Screwdriver (to open the case)
- 电脑（Windows / macOS / Linux）+ 串口终端（MobaXterm、SecureCRT、minicom 等，波特率 **115200** 8N1）
  *PC + serial terminal (115200 8N1)*
- TFTP 服务器软件（Windows 用 TFTPD64，Linux/macOS 用 `tftp`）
  *TFTP server software*
- 固件文件 `xg2010g-chainloader-<版本>-slot.bin`（放在 TFTP 服务器当前目录）
  *Place `xg2010g-chainloader-<version>-slot.bin` in the TFTP server directory*

> Release 页面每个机型只有一个文件，文件名内嵌版本号与构建时间。下文命令为简洁一律写作
> `xg2010g-chainloader-slot.bin`：请把下载到的文件**重命名**成该名，或把命令里的文件名换成实际下载的文件名。
> *Each board has exactly one file on the Releases page and its name carries the version and build
> time. The commands below use the short `xg2010g-chainloader-slot.bin` for brevity: rename the
> downloaded file, or substitute the real filename in the commands.*

## 2. TTL 连接 / TTL connection

1. 拆机，在主板上找到 TTL 接口（标识 GND / RX / TX）。
   *Open the case and locate the TTL header (GND / RX / TX) on the board.*
2. 按如下方式连接杜邦线（RX/TX 交叉）：
   *Wire the dupont cables (RX/TX crossed):*

   | TTL 模块 | 主板 |
   |---|---|
   | GND | GND |
   | RX | TX |
   | TX | RX |

3. **VCC 不接**，避免供电冲突；模块跳线选择 3.3V。
   *Leave VCC unconnected; set the module jumper to 3.3 V.*
4. USB 插入电脑，串口终端打开对应 COM 口（115200）。
   *Plug the USB in and open the serial port at 115200.*

## 3. 刷机步骤 / Flashing steps

### 3.1 配置电脑网络 / PC network

- 电脑网卡设静态 IP **192.168.0.10**，子网掩码 **255.255.255.0**。
  *Set the PC NIC to static IP 192.168.0.10 / 255.255.255.0.*
- 网线连接路由器的 **LAN 网口**（不要接 PON/WAN 口）。
  *Connect the Ethernet cable to a LAN port (not the PON/WAN port).*

### 3.2 启动 TFTP 服务器 / Start the TFTP server

- 确认 `xg2010g-chainloader-slot.bin` 在 TFTP 服务器当前目录下。
  *Make sure `xg2010g-chainloader-slot.bin` is in the TFTP server's current directory.*

### 3.3 上电打断 U-Boot / Interrupt U-Boot

1. 给路由器上电。
   *Power on the router.*
2. 串口出现启动日志时，迅速按任意键（空格或回车）打断，进入 U-Boot 命令行。
   *Press any key (space/enter) when the boot log appears to reach the U-Boot prompt.*
3. 如果看到 `T T T...` 表示已超时自动启动，重新上电再来。
   *`T T T...` means you missed the window — power-cycle and retry.*

### 3.4 TFTP 加载 chainloader / Load the chainloader via TFTP

在 U-Boot 命令行执行：
*At the U-Boot prompt:*

```sh
setenv serverip 192.168.0.10
setenv ipaddr 192.168.0.1
tftpboot 0x81800000 xg2010g-chainloader-slot.bin
```

> **XG2010G 内存为 1 GiB，加载地址必须使用 `0x81800000`，不要使用 `0x89000000`（超出内存范围）。**
> **The XG2010G has only 1 GiB of RAM — always use `0x81800000`, never `0x89000000` (out of range).**

### 3.5 写入 flash 并设置启动 / Write to flash and set bootcmd

```sh
setenv one "flash read 0x600000 0x100000 \$loadaddr"
setenv two "; bootm"
setenv bootcmd "$one$two"
saveenv
flash erase 0x600000 0x100000
flash write 0x600000 0x100000 0x81800000
reset
```

执行后原厂 U-Boot 会从偏移 `0x600000` 读取 1 MiB chainloader 并启动。
*The stock U-Boot now reads the 1 MiB chainloader from offset `0x600000` and boots it.*

> **⚠️ 上面这几条命令只能在`原厂 U-Boot`（提示符 `ECNT>`）下执行。**
> `uenv` 是原厂 U-Boot 的 env 分区，二级 chainloader 只是共用读取它；
> 在 chainloader 里 `saveenv` 会覆盖原厂 env，使原厂 U-Boot 之后无法启动 chainloader
> （卡在 `ECNT>` 并报 `Unknown command 'ubi'`）。详见 FAQ。
> **⚠️ Run these only at the vendor prompt (`ECNT>`).** Running `saveenv` from the chainloader
> overwrites the vendor environment and strands the vendor bootloader. See the FAQ.
>
> 顺便建议连原厂一级配方的**读取长度**一起改小，能显著缩短启动时间 —— 见 §6。
> *While you are here, also shrink the read length of the vendor recipe — see §6.*

### 3.6 刷机后：安装 OpenWrt / After flashing: install OpenWrt

1. `reset` 后 chainloader（第二级 U-Boot）启动，串口可见其横幅。
   *After `reset` the chainloader (second-stage U-Boot) starts.*
2. 按住 reset 键再上电，进入 HTTP 恢复模式。
   *Power-cycle again while holding the reset button to enter HTTP recovery.*
3. 电脑网卡改为 DHCP（自动获取 192.168.0.2–192.168.0.50），浏览器打开 <http://192.168.0.1>。
   *Set the PC NIC to DHCP (192.168.0.2–192.168.0.50) and open http://192.168.0.1.*
4. 上传 OpenWrt 固件 `*-sysupgrade.itb`（选择 `firmware` 目标），等待写入完成。
   *Upload the OpenWrt `*-sysupgrade.itb` (target `firmware`) and wait.*
5. 日常升级都走 HTTP 恢复，无需再拆机 TTL；更新 chainloader 本身用 `uboot` 目标上传 `xg2010g-chainloader-<版本>-slot.bin`。
   *Later upgrades all go through HTTP recovery — no more TTL. Update the chainloader itself via the `uboot` target.*

## 4. 固件文件 / The firmware file

| 文件 / File | 用途 / Purpose |
|---|---|
| `xg2010g-chainloader-<版本>-slot.bin` | 唯一用于刷机的镜像：通过 HTTP Recovery 的 `uboot` 目标写入 chainloader 分区（偏移 0x600000，1 MiB）。The only image to flash: write through the HTTP Recovery `uboot` target. |

> 文件名为 `xg2010g-chainloader-<构建时间>-g<commit>-slot.bin`，内嵌版本号与构建时间。
> 构建过程只产出这一个文件，**不再提供** `.itb`。
> *The name is `xg2010g-chainloader-<build time>-g<commit>-slot.bin`, carrying the version and build
> time. It is the only file produced; a bare `.itb` is no longer shipped.*

> 不要刷 `u-boot.bin` / `u-boot.img`。Never flash `u-boot.bin` / `u-boot.img`.

## 5. 与 uboot-an758x 的区别 / Difference from uboot-an758x

| | 本项目 / This project | [uboot-an758x](https://github.com/naoki66/uboot-an758x) |
|---|---|---|
| 原厂分区 / Stock layout | **保留**：前 6 MiB 原样不动，chainloader 写在 0x600000 | **不保留**：从 0x0 重写引导区并重建 UBI，需先备份、再恢复板级数据卷 |
| 刷入方式 / Flashing | TTL + TFTP 写 chainloader；之后 HTTP Recovery 网页刷固件 | BL2/preloader 写 0x0，XMODEM 送 FIP，Web recovery 重建 UBI |
| 适用机型 / Devices | XR1710G / XG2010G | 16 个 AN758x 目标 |

## 6. 可选优化：缩短原厂一级 U-Boot 的读取长度 / Optional: shorten the vendor U-Boot read

原厂一级 U-Boot 的配方一次读 **64 MiB**，而 chainloader 实际只占 1 MiB ——
这是整个启动过程中**最大的一项耗时**。在 `ECNT>` 下 `printenv bootcmd` 若看到这种形式：

```sh
flash read 0x602100 0x4000000 $loadaddr; bootm
```

把长度从 `0x4000000` 改成 `0x100000` 即可（偏移 `0x602100` 是 chainloader FIT 的固定位置，
**不要动**）：

```sh
ECNT> setenv bootcmd "flash read 0x602100 0x100000 \$loadaddr; bootm"
ECNT> saveenv
```

*The stock recipe reads 64 MiB while the chainloader only occupies 1 MiB — the single largest
item in boot time. Change the length from `0x4000000` to `0x100000`, leaving the offset alone.*

- **必须在原厂 U-Boot（`ECNT>`）下执行**，本项目不会自动改写原厂 env。
  *Run it at the vendor prompt (`ECNT>`); this project never rewrites the vendor environment.*
- 这里的 `saveenv` 是**正确用法** —— `uenv` 就是原厂 U-Boot 自己的 env 分区。
  反之，**在二级 chainloader 里绝不能 `saveenv`**（见 §7）。
  *`saveenv` is correct *here*: `uenv` is the vendor U-Boot's own environment partition.
  Never run it from the second-stage chainloader (see §7).*
- XR1710G 与 XG2010G 的一级 env 结构相同（FIT 同样落在 `0x602100`），这条对两个机型都适用。
  *XR1710G and XG2010G share the same first-stage layout, so this applies to both.*
- 若你的 `bootcmd` 是 `flash imgread 2048;bootm` 这种形式，说明已经是按分区读，无需改动。
  *If your `bootcmd` already looks like `flash imgread 2048;bootm`, there is nothing to change.*

## 7. 常见问题 / FAQ

- **`T T T...` 后自动启动**：打断超时，重新上电并提前按键。
  *Missed the interrupt window — power-cycle and press earlier.*
- **TFTP 超时**：检查电脑 IP（192.168.0.10）、TFTP 服务器已启动、文件名无误、网线插在 LAN 口。
  *Check the PC IP, TFTP server status, filename and cable.*
- **`Wrong Image Format`**：镜像文件不对，确认使用的是 `xg2010g-chainloader-*-slot.bin`
  （文件名带版本号与构建时间），而不是 `u-boot.bin` 或裸 `.itb`。
  *Wrong image file — use `xg2010g-chainloader-*-slot.bin` (the name carries the version and build
  time), not `u-boot.bin` or a bare `.itb`.*
- **恢复页面打不开**：确认按住 reset 上电、电脑为 DHCP、访问 <http://192.168.0.1>。
  *Make sure recovery was entered, the PC uses DHCP, and the URL is http://192.168.0.1.*
