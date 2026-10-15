# XR1710G U-Boot (Fork with DHCP Fix & CI Build)

> **Fork by** [naoki66](https://github.com/naoki66) · **Original project** by [YYH2913](https://github.com/YYH2913/http-uboot) · **Original release** [260712](https://github.com/YYH2913/http-uboot/releases/tag/260712)

## 捐赠 / Donate

如果您觉得对您有帮助，请我喝杯咖啡吧，让我更有动力持续更新。

<img src="./c6ea388c976395326514814f80d512d5.png" width="220" alt="Donate / 捐赠二维码">

## Fork Changes

This fork is based on YYH2913's XR1710G http-uboot and adds the following modifications:

### 1. DHCP Server Fix — Windows 11 Compatibility

**Problem**: The built-in DHCP server did not include the Router (Option 3, default gateway) and DNS Server (Option 6) options in DHCP Offer/ACK responses. Windows 11's DHCP client has stricter validation and would ignore the incomplete response, leaving the PC without an IP address. Users had to manually set `192.168.0.x` to access the recovery page.

**Fix**: Added Router and DNS options to `recovery_dhcp_send_reply()` in `net/lwip/httpd_recovery.c`. Both values default to the server IP (`192.168.0.1`).

### 2. GitHub Actions CI — Automated Build & Release

Added `.github/workflows/build.yml` for on-demand compilation and release publishing:
- Manual trigger only (`workflow_dispatch`)
- Cross-compiles with `aarch64-linux-gnu-` toolchain
- Automatically packages the chainloader slot image (`*-chainloader-slot.bin`)
- Publishes build artifacts to GitHub Releases with SHA256 checksums
- Releases are available at [Actions](https://github.com/naoki66/XR1710G-http-uboot/actions) page

### 3. Local Debug Mock Server

Added `mock_server.py` for previewing and debugging the HTTP recovery UI locally without hardware.

### 4. DHCP Server — Per-MAC Leases Instead of One Fixed Address

The original server offered a single hard-coded address (`192.168.0.2`) to
every client and answered `NAK` to any `DHCPREQUEST` that asked for something
else. A PC that still remembered a lease from another network was therefore
NAKed, gave up after a few attempts and fell back to `169.254.x.x`. Two clients
at once (a Windows host plus a VM bridge is enough) collided on the same
address and hit the same fallback through duplicate-address detection. Both
cases look identical from the outside: "the router never gives me an address,
I have to configure it by hand".

The server now keeps a small lease table keyed by client MAC:

- Pool defaults to `192.168.0.2` – `192.168.0.50`. The first client still
  gets `.2`, so existing documentation and pinned clients keep working.
- `DHCPREQUEST` for a stale address **outside** the pool gets a `NAK`, which
  sends the client back to `DHCPDISCOVER` (that is the correct behaviour — it
  is how a client leaves a foreign subnet).
- `DHCPREQUEST` for an address **inside** the pool gets an `ACK`, renewing or
  re-allocating as needed. No more NAK just because the remembered address is
  not exactly `.2`.
- `DHCPRELEASE` frees the lease.
- Pool bounds can be widened without rebuilding U-Boot:
  ```sh
  setenv recovery_dhcp_start 192.168.0.2
  setenv recovery_dhcp_end 192.168.0.254
  saveenv
  ```
- The recovery port policy still refuses to answer DHCP on the WAN port, but a
  refused request is now **logged** (rate limited) instead of vanishing:
  `DHCP: request ignored by port policy (recovery_port=..., rx fport=N)`.
  If you see that line, the request arrived on a port `recovery_port` excludes
  — set `recovery_port` to match the port your PC is plugged into, or leave it
  unset for `auto` (any LAN port except WAN).

If you do configure the PC by hand, pick an address **outside** the pool (for
example `192.168.0.100`) with mask `255.255.255.0`, so it cannot collide with
a lease handed to another host.

---

## Original README

The following is the original README by YYH2913, preserved in full.

---

# XR1710G U-Boot

This is a customized U-Boot port for the XR1710G. Its main features are:

- 10GbE support
- HTTP Recovery for convenient web-based firmware flashing
- Built-in DHCP server so a connected PC can obtain an address automatically in recovery mode
- Recovery page address: `http://192.168.0.1`

## 刷机教程 / Flashing Guide

两机型刷机方案相同：保留原厂前 6 MiB 分区（bootloader / uenv / dsd）不动，在偏移 `0x600000`（6 MiB）处写入 **1 MiB chainloader**。
Both boards share the same scheme: keep the stock first 6 MiB (`bootloader` / `uenv` / `dsd`) untouched, then write the **1 MiB chainloader** at offset `0x600000`.

| 机型 / Board | 教程 / Guide | 刷入文件 / File to flash |
|---|---|---|
| XR1710G (W1700K / W1701K) | [docs/flashing-xr1710g.md](docs/flashing-xr1710g.md) | `xr1710g-chainloader-slot.bin` |
| XG2010G | [docs/flashing-xg2010g.md](docs/flashing-xg2010g.md) | `xg2010g-chainloader-slot.bin` |

### 发布文件说明 / Release artifacts

每个机型仅发布 2 个文件。Each board ships exactly two files:

| 文件 / File | 用途 / Purpose |
|---|---|
| `<board>-chainloader-slot.bin` | 唯一用于刷机的镜像：通过 HTTP Recovery 的 `uboot` 目标写入 chainloader 分区（偏移 0x600000，1 MiB）。The only image to flash: write through the HTTP Recovery `uboot` target. |
| `<board>-chainloader.itb` | 仅用于 TFTP RAM 验证启动，请勿通过 HTTP Recovery 上传。RAM-only validation through TFTP. Do not upload this file to HTTP Recovery. |

> [!WARNING]
> - 不要刷 `u-boot.bin` / `u-boot.img`。Never flash `u-boot.bin` / `u-boot.img`.
> - 唯一刷机文件是 `<board>-chainloader-slot.bin`。The only flashable file is `<board>-chainloader-slot.bin`.

### 日常升级 / Upgrades after install

1. 按住 reset 键上电，进入 HTTP 恢复模式。
   *Power-cycle while holding the reset button to enter HTTP recovery.*
2. 电脑网卡用 DHCP（自动获取 192.168.0.2–192.168.0.50），浏览器打开 <http://192.168.0.1>。
   *Set the PC NIC to DHCP (192.168.0.2–192.168.0.50) and open http://192.168.0.1.*
3. 选择上传目标并上传文件：
   *Pick a target and upload:*
   - `firmware`：OpenWrt `*-sysupgrade.itb`，写入 `system:fit`。
   - `uboot`：`<board>-chainloader-slot.bin`，写入原始 chainloader 分区。
4. `firmware` 上传仅支持单一 `system` UBI 布局（大小 `0x1B700000`，528-PEB 预留尾区），镜像必须匹配该布局。
   *`firmware` uploads only support the single `system` UBI layout (`0x1B700000`, 528-PEB reserved tail); the image must match.*

### 与 uboot-an758x 的区别 / Difference from uboot-an758x

| | 本项目 / This repo | [uboot-an758x](https://github.com/naoki66/uboot-an758x) |
|---|---|---|
| 原厂分区 / Stock layout | **保留**：前 6 MiB 原样不动，chainloader 写在 0x600000 | **不保留**：从 0x0 重写引导区并重建 UBI，需先备份、再恢复板级数据卷 |
| 刷入方式 / Flashing | TTL + TFTP 写 chainloader；之后 HTTP Recovery 网页刷固件 | BL2/preloader 写 0x0，XMODEM 送 FIP，Web recovery 重建 UBI |
| 适用机型 / Devices | XR1710G / XG2010G | 16 个 AN758x 目标 |


<details>
<summary>ECNT stock U-Boot details</summary>

## Flash From ECNT Stock U-Boot

This section applies to units still using the original ECNT / AXON first-stage
U-Boot. The known stock environment reports:

```sh
ver=U-Boot 2014.04-rc1 (Mar 15 2024 - 15:13:21) AXON 1.6
version=1.6
vendor=ecnt
board=an7581_evb
loadaddr=0x81800000
fdt_high=0xac000000
bootcmd=flash read 0x602100 0x4000000 $loadaddr; bootm
ipaddr=192.168.0.1
serverip=192.168.0.205
bootfile=tclinux.bin
kernel_filename=tclinux.bin
uboot_filename=tcboot.bin
```

For this stock environment, keep the default `bootcmd` unchanged. The current
slot image is dual-entry:

- flash offset `0x600000` contains a small legacy bootm prefix shim
- flash offset `0x602100` contains the full chainloader FIT

The ECNT default command enters the FIT directly:

```sh
flash read 0x602100 0x4000000 $loadaddr
bootm
```

If the boot-critical variables do not match the values above, check only the
minimal set first:

```sh
printenv bootcmd loadaddr fdt_high
```

For the current chainloader slot image, the expected values are:

```sh
bootcmd=flash read 0x602100 0x4000000 $loadaddr; bootm
loadaddr=0x81800000
fdt_high=0xac000000
```

To change a mismatched ECNT first-stage environment back to these values:

```sh
setenv loadaddr 0x81800000
setenv fdt_high 0xac000000
setenv bootcmd 'flash read 0x602100 0x4000000 $loadaddr; bootm'
saveenv
reset
```

Do not copy a full `printenv` from another device. Board-specific values such
as `ethaddr`, `bootargs`, GPIO settings, serial data, and vendor/product fields
should be preserved unless there is a separate reason to change them.

The image to write is still:

```text
out/xr1710g-chainloader-slot.bin
```

The older `0x600000` no-argument form is also supported by the current
dual-entry slot image:

```sh
flash read 0x600000 0x100000 $loadaddr
bootm
```

In this mode, `bootm` starts the legacy prefix shim at `$loadaddr`; that shim
then locates the FIT at `$loadaddr + 0x2100` and jumps to the embedded
second-stage U-Boot payload.

After flashing the slot image, the ECNT prompt can be used to validate the
first-stage handoff manually:

```sh
printenv ver version vendor board bootcmd loadaddr fdt_high
flash read 0x600000 0x100 0x81800000
md.b 0x81800000 0x20
flash read 0x602100 0x4000000 $loadaddr
bootm
```

The expected magic bytes for a correctly flashed current slot image are:

- at flash offset `0x600000`: `27 05 19 56` (`IH_MAGIC`, legacy prefix shim)
- at flash offset `0x602100`: `d0 0d fe ed` (`FDT_MAGIC`, chainloader FIT)

If `bootcmd=flash read 0x602100 ...; bootm` prints `Wrong Image Format`, the
first thing to check is the second magic value above. If `0x602100` is not
`d0 0d fe ed`, the ECNT environment is not the cause; the chainloader slot was
not written with the current `out/xr1710g-chainloader-slot.bin`, or it was
written at the wrong offset.

If variable expansion is inconvenient, use the default address explicitly:

```sh
flash read 0x602100 0x4000000 0x81800000
bootm 0x81800000
```

The earlier bug where the log reached `Starting kernel ...` and then stopped
was observed on this same AXON 1.6 stock U-Boot line. In that failure mode the
shim could be entered from a FIT image reported at `0x89000000`, while the
control DTB still used the default `fit-base = 0x81800000`. The current shim
keeps `0x81800000` as the default and adds a fallback search for the AXON 1.6
handoff address, so the ECNT environment should not be changed just to work
around that bug.

The ECNT `flash` command is vendor-specific. This README intentionally does
not provide an unverified raw `flash write` command for the stock prompt; use a
known-good vendor update path or the OpenWrt `nandwrite` flow below for the
persistent write.

</details>

<details>
<summary>Migration from w1700k-ubi-installer details</summary>

## Migration From `w1700k-ubi-installer`

If the device is being switched from the older `w1700k-ubi-installer` path to
the current XR1710G chainloader layout, the first-stage vendor U-Boot
environment must be checked and usually updated.

The older installer commonly left the first-stage environment with:

```sh
bootcmd=flash read 0x600000 0x100000 $loadaddr; bootm
```

That command matched the older `openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb`
flow where the FIT image started directly at `0x600000`.

Older single-entry `xr1710g-chainloader-slot.bin` builds kept a vendor
`0x2100`-byte slot prefix and placed the FIT at `0x602100`, so the old
no-argument `bootm` form was not compatible. Current builds are dual-entry:
the slot starts with a legacy bootm prefix shim and still keeps the FIT at
`0x602100`.

Before expecting automatic boot to work, inspect the current setting in the
first-stage prompt:

```sh
printenv bootcmd
```

The following first-stage forms are confirmed to work with the current
`xr1710g-chainloader-slot.bin`:

```sh
flash read 0x600000 0x100000 0x81800000
bootm 0x81800000
```

or:

```sh
flash read 0x602100 0x100000 0x81800000
bootm 0x81800000
```

or:

```sh
flash read 0x600000 0x100000 0x81800000
bootm 0x81802100
```

To update the persistent first-stage environment, use one of these `bootcmd`
values:

```sh
setenv bootcmd 'flash read 0x600000 0x100000 $loadaddr; bootm'
saveenv
```

or:

```sh
setenv bootcmd 'flash read 0x602100 0x100000 $loadaddr; bootm 0x81800000'
saveenv
```

or:

```sh
setenv bootcmd 'flash read 0x600000 0x100000 $loadaddr; bootm 0x81802100'
saveenv
```

</details>

<details>
<summary>Current partition layout details</summary>

## Current Partition Layout

The chainloader build uses a single, uniform NAND layout for both XR1710G and
XG2010G. The first three 2 MiB regions preserve the stock firmware, followed by
the chainloader, then the `system` UBI partition, then the reserved BMT region:

| Partition | U-Boot MTD view | Offset | Size | Notes |
|---|---|---:|---:|---|
| `bootloader` | `bootloader` | `0x00000000` | `0x00200000` | read-only, stock U-Boot |
| `uenv` | `uenv` | `0x00200000` | `0x00200000` | U-Boot env (MTD) |
| `dsd` | `dsd` | `0x00400000` | `0x00200000` | stock factory / DSD data |
| `chainloader` | `chainloader` | `0x00600000` | `0x00100000` | read-only |
| `system` | `system` | `0x00700000` | `0x1B700000` | UBI: `fit` + `factory` |
| `reserved_bmt` | `reserved_bmt` | `0x1BE00000` | `0x04200000` | read-only, BMT/BBT |

`system` carries two UBI volumes: `fit` (the OpenWrt kernel/FDT FIT) and
`factory` (per-device calibration + MAC data). The U-Boot environment is stored
in the `uenv` MTD partition (`CONFIG_ENV_IS_IN_MTD=y`), **not** in UBI
`ubootenv`/`ubootenv2` volumes, so it survives `system` rebuilds. The `factory`
volume is populated from the `dsd` MTD partition at boot.

The `system` boundary follows the conservative 528-PEB reservation used by the
local OP integration. There is no longer a UBI 1.5 / 1.0 compatibility view;
migration from an older layout must fully rebuild UBI. OpenWrt PR `#22397` is
still unmerged and currently carries the older 16-PEB boundary; it is not
evidence for the local `system` size.

</details>

<details>
<summary>OpenWrt legacy tclinux flashing details</summary>

## Flashing the Primary `tclinux` Slot from OpenWrt

The following commands are intended for the case where:

- the device is still using the original legacy vendor partition layout
- there is not yet a dedicated `chainloader` partition
- you want to write `out/xr1710g-chainloader-slot.bin` into the primary `tclinux` slot

First, confirm that the partition names still match the old layout:

```sh
grep -E 'tclinux|tclinux_slave' /proc/mtd
```

If the primary slot is still `tclinux`, it is typically `/dev/mtd5`. It is recommended to overwrite only the first `1 MiB` of that slot. Do not use `sysupgrade`, and do not directly `mtd write ... tclinux` over the entire `64 MiB` slot.

Assuming the image has already been copied to `/tmp/xr1710g-chainloader-slot.bin` on the device, run:

```sh
# Optional: back up the first 1 MiB of the primary slot
nanddump -l 0x100000 -f /tmp/tclinux-head-1m.bin /dev/mtd5

# Erase the first 1 MiB (8 erase blocks of 128 KiB each)
flash_erase /dev/mtd5 0 8

# Write the chainloader slot image to the start of the primary slot
nandwrite -p /dev/mtd5 /tmp/xr1710g-chainloader-slot.bin

sync
reboot
```

Additional notes:

- The image written here is `out/xr1710g-chainloader-slot.bin`, not `u-boot.bin`
- These commands apply to the old layout where the primary slot is `tclinux`
- If the device has already been migrated to the new `bootloader + uenv + dsd + chainloader + system` layout, write the `chainloader` partition directly instead of writing `tclinux`

</details>

<details>
<summary>Why the raw build artifact cannot be flashed directly</summary>

## Why the Raw Build Artifact Cannot Be Flashed Directly

The vendor boot chain follows a `bootm` path and cannot boot a bare `u-boot.bin` directly.

Because of that, the U-Boot in this project is used as a secondary payload. An outer wrapper with a Linux `Image`-style header and a chainloader package must be added so that the vendor `bootm` path will accept it. That outer wrapper first boots a shim, and the shim then jumps to the real `u-boot.bin`.

In other words, the U-Boot artifact produced by the build cannot be flashed directly. It must first be packaged into a chainloader image with the required Linux-style header.

</details>

<details>
<summary>Packaging files and build commands</summary>

## Files Required for Packaging

To package the raw U-Boot payload into a flashable chainloader image, prepare:

- Raw secondary payload: `u-boot.bin`
- Vendor slot image, for example `mtd5_tclinux.bin`
  Used as a reference input when building the slot image
- Prefix shim: `chainloader-prefix-shim.uImage`
  Provides compatibility with legacy `flash read 0x600000 ...; bootm`
- Shim: `chainloader-shim.bin`
- Control DTB: `xr1710g-chainloader-control.dtb` (per-board; XG2010G uses `xg2010g-chainloader-control.dtb`)
- `u-boot/tools/mkimage`
- `u-boot/tools/dumpimage`

The resulting packaged artifacts are typically:

- `out/xr1710g-chainloader.itb`
- `out/xr1710g-chainloader-slot.bin`

Reference: simplified `build-chainloader-fit.sh` script contents, keeping only the core packaging logic:

```sh
#!/usr/bin/env sh
set -eu

stock_slot=xr1710g-backup/mtd5_tclinux.bin
prefix_shim=out/chainloader-prefix-shim.uImage
shim=out/chainloader-shim.bin
payload=out/u-boot.bin
dtb=out/xr1710g-chainloader-control.dtb
output_fit=out/xr1710g-chainloader.itb
output_slot=out/xr1710g-chainloader-slot.bin
mkimage=u-boot/tools/mkimage
dumpimage=u-boot/tools/dumpimage
template=xr1710g-chainloader.its.in
tmpdir=$(mktemp -d)
its="$tmpdir/xr1710g-chainloader.its"

sed \
  -e "s|__DTB__|$dtb|g" \
  -e "s|__SHIM__|$shim|g" \
  -e "s|__PAYLOAD__|$payload|g" \
  -e "s|__KCOMP__|none|g" \
  "$template" > "$its"

"$mkimage" -f "$its" "$output_fit"
"$dumpimage" -l "$output_fit"

# Place a legacy bootm prefix shim at slot offset 0, pad it to 0x2100 bytes,
# then append the full chainloader FIT image.
prefix_size=$(wc -c < "$prefix_shim")
cp "$prefix_shim" "$output_slot"
dd if=/dev/zero bs=1 count=$((0x2100 - prefix_size)) >> "$output_slot" 2>/dev/null
cat "$output_fit" >> "$output_slot"

```

</details>

<details>
<summary>Reference projects</summary>

## Reference Projects

- U-Boot official homepage: <https://u-boot.org/>
- U-Boot official documentation: <https://docs.u-boot.org/>
- U-Boot official source repository: <https://source.denx.de/u-boot/u-boot>

</details>
