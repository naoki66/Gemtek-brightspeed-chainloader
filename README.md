# XR1710G XG2010G  chainloader  U-Boot 


## 刷机教程 / Flashing Guide

两机型刷机方案相同：保留原厂前 6 MiB 分区（bootloader / uenv / dsd）不动，在偏移 `0x600000`（6 MiB）处写入 **1 MiB chainloader**。
Both boards share the same scheme: keep the stock first 6 MiB (`bootloader` / `uenv` / `dsd`) untouched, then write the **1 MiB chainloader** at offset `0x600000`.

| 机型 / Board | 教程 / Guide | 刷入文件 / File to flash |
|---|---|---|
| XR1710G (W1700K / W1701K) | [docs/flashing-xr1710g.md](docs/flashing-xr1710g.md) | `xr1710g-chainloader-*-slot.bin` |
| XG2010G | [docs/flashing-xg2010g.md](docs/flashing-xg2010g.md) | `xg2010g-chainloader-*-slot.bin` |

### 发布文件说明 / Release artifacts

每个机型只发布 **1 个文件**：chainloader 槽位镜像。
*Each board ships exactly one file: the chainloader slot image.*

| 文件 / File | 用途 / Purpose |
|---|---|
| `<board>-chainloader-<版本>-slot.bin`<br>例 / e.g. `xr1710g-chainloader-20261016-040544-gc1a49ffc4d63-slot.bin` | 唯一用于刷机的镜像：通过 HTTP Recovery 的 `uboot` 目标写入 chainloader 分区（偏移 0x600000，1 MiB）。The only image to flash: write through the HTTP Recovery `uboot` target. |

文件名内嵌**版本号与构建时间**，可直接区分不同构建；刷机时文件名随意，校验只看镜像头部 magic。
*The filename carries the version and the build time so builds are easy to tell apart; the filename itself is not validated — only the image magic is.*


### 日常升级 / Upgrades after install

1. 上电约3s 后按住 reset 键，进入 HTTP 恢复模式。
2. 电脑网卡用 DHCP（自动获取 192.168.0.2–192.168.0.50），浏览器打开 <http://192.168.0.1>。
3. 选择上传目标并上传文件：
   *Pick a target and upload:*
   - `firmware`：OpenWrt `*-sysupgrade.itb`，写入 `system:fit`。
   - `uboot`：`<board>-chainloader-<版本>-slot.bin`，写入原始 chainloader 分区。
4. `firmware` 上传仅支持单一 `system` UBI 布局（大小 `0x1B700000`，528-PEB 预留尾区），镜像必须匹配该布局。
   *`firmware` uploads only support the single `system` UBI layout (`0x1B700000`, 528-PEB reserved tail); the image must match.*

 
## 捐赠 / Donate

如果您觉得对您有帮助，请我喝杯咖啡吧，让我更有动力持续更新。

<img src="./c6ea388c976395326514814f80d512d5.png" width="420" alt="Donate / 捐赠二维码">

