# 通过 SSH 刷写 chainloader（XR1710G / XG2010G）

适用于设备已能正常启动 OpenWrt、且 SSH 可登录的场景。通过 SSH 更新 **mtd3 / chainloader**（1 MiB）分区，不需要拆机接 TTL。

> 只刷 `xr1710g-chainloader-<版本>-slot.bin` 或 `xg2010g-chainloader-<版本>-slot.bin`。
> **不要刷 `u-boot.bin` / `u-boot.img`。**

## 1. 确认目标分区

```sh
ssh root@<设备IP> 'cat /proc/mtd'
```

确认存在类似：

```text
mtd3: 00100000 00010000 "chainloader"
```

不同固件的 mtd 编号可能不同，**以 label 为准**；后面的命令也用 label 操作，避免写错分区。

## 2. 备份当前 chainloader

```sh
ssh root@<设备IP> 'dd if=/dev/mtd3 of=/tmp/mtd3-before.bin bs=64k && sha256sum /tmp/mtd3-before.bin'
scp root@<设备IP>:/tmp/mtd3-before.bin ./mtd3-before.bin
```

`/tmp` 是内存盘，重启即丢失，务必把备份拉回本机保存。

## 3. 上传新镜像并校验

```sh
scp xr1710g-chainloader-<版本>-slot.bin root@<设备IP>:/tmp/new-slot.bin
```

两端分别计算 SHA256，必须一致：

```sh
# PC（Windows PowerShell）
Get-FileHash .\xr1710g-chainloader-<版本>-slot.bin -Algorithm SHA256

# 设备
ssh root@<设备IP> 'sha256sum /tmp/new-slot.bin'
```

## 4. 写入分区

```sh
ssh root@<设备IP> 'mtd write /tmp/new-slot.bin chainloader'
```

- OpenWrt 的 `mtd` 会先擦除整个分区再写入，输出中的 `[e]` / `[w]` 是擦除/写入进度。
- 1 MiB 分区通常 1 秒内完成，期间**不要断电、不要重启**。
- 写入只覆盖镜像长度，尾部保持擦除后的 `0xff`，不影响启动。

## 5. 回读校验

```sh
ssh root@<设备IP> '
SIZE=$(stat -c %s /tmp/new-slot.bin)
dd if=/dev/mtd3 bs=4096 count=$(( (SIZE + 4095) / 4096 )) 2>/dev/null \
  | head -c $SIZE | sha256sum
'
```

结果应与第 3 步的 SHA256 完全相同。

可选：确认两处 magic（前缀 uImage 与 FIT）：

```sh
dd if=/dev/mtd3 bs=1 count=4 2>/dev/null | hexdump -C            # 27 05 19 56
dd if=/dev/mtd3 bs=1 skip=8448 count=4 2>/dev/null | hexdump -C  # d0 0d fe df
```

## 6. 重启生效

```sh
ssh root@<设备IP> 'sync; reboot'
```

- 设备通常 60–90 秒后恢复 SSH（中间会先运行 chainloader）。
- 校验：`uptime`、`ip -br link`、管理页面/业务是否正常。
- 本次实测 XR1710G：重启前 CPU 口与 lan2 的 MAC 重复，重启后 CPU 口变为 LAN base + 4，说明 chainloader 的 FDT fixup 已生效。

## 7. 出问题时

- **回读 SHA256 不一致或写入报错**：不要重启，重新上传后再写一次。
- **重启后设备不回来**：按 [TTL 刷机教程](flashing-xr1710g.md) 第 3.4–3.5 节，在原厂 U-Boot（`ECNT>`）下用 TFTP 重刷偏移 `0x600000`、长度 `0x100000`。
- **需要回滚**：在同一位置写回第 2 步备份的 `mtd3-before.bin`。

## 注意

- 不要在二级 chainloader 的 U-Boot 里执行 `saveenv` 或 `env default -a`，原因见 TTL 教程 FAQ。
- 写入 mtd3 不会影响当前正在运行的系统；**重启后才生效**。
- 建议每次只改这一块，刷完立即回读校验。
