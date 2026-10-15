# XR1710G（W1700K / W1701K）TTL 刷机教程
# XR1710G (W1700K / W1701K) TTL Flashing Guide

> **刷机方案 / Scheme**：保留原厂前 6 MiB（bootloader 2 MiB + uenv 2 MiB + dsd 2 MiB）不动，在偏移 **0x600000（6 MiB）** 处写入 **1 MiB chainloader**。
> Keep the stock first 6 MiB (`bootloader` + `uenv` + `dsd`) untouched, then write the **1 MiB chainloader** at offset `0x600000`.

| | |
|---|---|
| 适用机型 / Boards | XR1710G / W1700K / W1701K |
| 刷入文件 / File to flash | `xr1710g-chainloader-slot.bin`（唯一需要刷入的文件 / the only file to flash） |
| 下载 / Download | [Releases](https://github.com/naoki66/Gemtek-brightspeed-chainloader/releases) |
| 参考项目 / Reference | [Gemtek-brightspeed-chainloader](https://github.com/naoki66/Gemtek-brightspeed-chainloader) |

## 刷机前必读 / Before you start

**⚠️ 刷机有变砖风险，请逐步确认后再操作。**
**⚠️ Flashing can brick the device. Follow every step carefully.**

- 刷机过程不要断电、不要拔网线。Do not power off or disconnect during flashing.
- 确认固件文件与机型匹配（XR1710G 与 XG2010G 镜像不通用）。The XR1710G and XG2010G images are not interchangeable.

## 1. 准备工作 / Preparation

- USB 转 TTL 模块（3.3V，如 CH343）
  *USB-TTL module (3.3 V, e.g. CH343)*
- 杜邦线若干 / Dupont wires
- T10 螺丝刀（拆机用）/ T10 screwdriver (to open the case)
- 电脑（Windows / macOS / Linux）+ 串口终端（MobaXterm、SecureCRT、minicom 等，波特率 **115200** 8N1）
  *PC + serial terminal (115200 8N1)*
- TFTP 服务器软件（Windows 用 TFTPD64，Linux/macOS 用 `tftp`）
  *TFTP server software*
- 固件文件 `xr1710g-chainloader-slot.bin`（放在 TFTP 服务器当前目录）
  *Place `xr1710g-chainloader-slot.bin` in the TFTP server directory*

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
- 网线连接路由器的 **10GbE 网口**。
  *Connect the Ethernet cable to the router's 10GbE port.*

### 3.2 启动 TFTP 服务器 / Start the TFTP server

- 确认 `xr1710g-chainloader-slot.bin` 在 TFTP 服务器当前目录下。
  *Make sure `xr1710g-chainloader-slot.bin` is in the TFTP server's current directory.*

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
tftpboot 0x81800000 xr1710g-chainloader-slot.bin
```

> XR1710G 内存为 2 GiB，加载地址也可用 `0x89000000`；两机型教程统一使用 `0x81800000`。
> The XR1710G has 2 GiB of RAM, so `0x89000000` also works; both guides use `0x81800000`.

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

### 3.6 刷机后：安装 OpenWrt / After flashing: install OpenWrt

1. `reset` 后 chainloader（第二级 U-Boot）启动，串口可见其横幅。
   *After `reset` the chainloader (second-stage U-Boot) starts.*
2. 按住 reset 键再上电，进入 HTTP 恢复模式。
   *Power-cycle again while holding the reset button to enter HTTP recovery.*
3. 电脑网卡改为 DHCP（自动获取 192.168.0.2–192.168.0.50），浏览器打开 <http://192.168.0.1>。
   *Set the PC NIC to DHCP (192.168.0.2–192.168.0.50) and open http://192.168.0.1.*
4. 上传 OpenWrt 固件 `*-sysupgrade.itb`（选择 `firmware` 目标），等待写入完成。
   *Upload the OpenWrt `*-sysupgrade.itb` (target `firmware`) and wait.*
5. 日常升级都走 HTTP 恢复，无需再拆机 TTL；更新 chainloader 本身用 `uboot` 目标上传 `xr1710g-chainloader-slot.bin`。
   *Later upgrades all go through HTTP recovery — no more TTL. Update the chainloader itself via the `uboot` target.*

## 4. 两种固件文件 / The two firmware files

| 文件 / File | 用途 / Purpose |
|---|---|
| `xr1710g-chainloader-slot.bin` | 唯一用于刷机的镜像：通过 HTTP Recovery 的 `uboot` 目标写入 chainloader 分区（偏移 0x600000，1 MiB）。The only image to flash: write through the HTTP Recovery `uboot` target. |
| `xr1710g-chainloader.itb` | 仅用于 TFTP RAM 验证启动（`tftpboot` + `bootm`），**请勿**通过 HTTP Recovery 上传。RAM-only validation through TFTP. Do **not** upload to HTTP Recovery. |

> 不要刷 `u-boot.bin` / `u-boot.img`。Never flash `u-boot.bin` / `u-boot.img`.

## 5. 与 uboot-an758x 的区别 / Difference from uboot-an758x

| | 本项目 / This project | [uboot-an758x](https://github.com/naoki66/uboot-an758x) |
|---|---|---|
| 原厂分区 / Stock layout | **保留**：前 6 MiB 原样不动，chainloader 写在 0x600000 | **不保留**：从 0x0 重写引导区并重建 UBI，需先备份、再恢复板级数据卷 |
| 刷入方式 / Flashing | TTL + TFTP 写 chainloader；之后 HTTP Recovery 网页刷固件 | BL2/preloader 写 0x0，XMODEM 送 FIP，Web recovery 重建 UBI |
| 适用机型 / Devices | XR1710G / XG2010G | 16 个 AN758x 目标 |

## 6. 常见问题 / FAQ

- **`T T T...` 后自动启动**：打断超时，重新上电并提前按键。
  *Missed the interrupt window — power-cycle and press earlier.*
- **TFTP 超时**：检查电脑 IP（192.168.0.10）、TFTP 服务器已启动、文件名无误、网线插在 10GbE 口。
  *Check the PC IP, TFTP server status, filename and cable.*
- **`Wrong Image Format`**：镜像文件不对，确认使用的是 `xr1710g-chainloader-slot.bin`。
  *Wrong image file — use `xr1710g-chainloader-slot.bin`.*
- **恢复页面打不开**：确认按住 reset 上电、电脑为 DHCP、访问 <http://192.168.0.1>。
  *Make sure recovery was entered, the PC uses DHCP, and the URL is http://192.168.0.1.*
