#!/bin/sh
#
# Multi-board build helper for the XR1710G / XG2010G recovery tree.
#
# Builds U-Boot (u-boot.img) for a single board. No FIP/bootloader signing is
# performed -- the project flashes the unsigned U-Boot payload via the existing
# chainloader, so only the U-Boot image is produced here.
#
# Usage:
#   ./scripts/build.sh <xr1710g|xg2010g> [extra-make-args...]
#
# Required environment:
#   CROSS_COMPILE   AArch64 toolchain prefix (default: aarch64-linux-gnu-)
#
# Optional environment:
#   BUILD_ROOT      Per-board build directory (default: <repo>/build/<board>)
#   OUTPUT_ROOT     Artifact directory        (default: <repo>/output/<board>)
#   BUILD_JOBS      Parallel jobs            (default: nproc)

set -eu

board="${1:-}"
shift || true

case "$board" in
xr1710g)
	defconfig=xr1710g_defconfig
	;;
xg2010g)
	defconfig=xg2010g_defconfig
	;;
"")
	echo "usage: $0 <xr1710g|xg2010g> [extra-make-args...]" >&2
	exit 2
	;;
*)
	echo "error: unknown board '$board' (expected xr1710g or xg2010g)" >&2
	exit 2
	;;
esac

: "${CROSS_COMPILE:=aarch64-linux-gnu-}"
jobs="${BUILD_JOBS:-$(nproc 2>/dev/null || echo 1)}"

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_dir="$(CDPATH= cd -- "$script_dir/.." && pwd)"
build_root="${BUILD_ROOT:-$repo_dir/build/$board}"
output_root="${OUTPUT_ROOT:-$repo_dir/output/$board}"

mkdir -p "$build_root" "$output_root"

echo "==> Building $board ($defconfig) with CROSS_COMPILE=$CROSS_COMPILE"
cd "$repo_dir"
make O="$build_root" "$defconfig"
make O="$build_root" -j"$jobs" CROSS_COMPILE="$CROSS_COMPILE" "$@"

# Copy whatever the configured BUILD_TARGET produced (u-boot.img for both
# boards); fall back to the raw u-boot.bin if the wrapper is unavailable.
for f in u-boot.img u-boot.bin; do
	[ -f "$build_root/$f" ] && cp "$build_root/$f" "$output_root/$f"
done

echo "==> $board artifacts in: $output_root"
ls -l "$output_root"
