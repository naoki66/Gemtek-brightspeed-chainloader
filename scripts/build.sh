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
#   UBOOT_KEEP_DIRTY  Set to 1 to append "-dirty" to the version string when
#                     the tree has uncommitted changes (off by default).

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

# The version string never carries "-dirty" (see UBOOT_SETLOCALVERSION_FLAGS in
# the Makefile), so this warning is the only thing standing between an
# uncommitted edit and an image that quietly names a commit it does not match.
# UBOOT_KEEP_DIRTY=1 brings the upstream suffix back instead.
if [ "${UBOOT_KEEP_DIRTY:-}" != "1" ]; then
	dirty="$(git --no-optional-locks status --porcelain --untracked-files=no 2>/dev/null || true)"
	if [ -n "$dirty" ]; then
		echo "warning: $board is being built from a tree with uncommitted changes:" >&2
		echo "$dirty" >&2
		echo "warning: the image will still report commit $(git rev-parse --short=12 HEAD) with no -dirty suffix." >&2
		echo "warning: commit the change, or rebuild with UBOOT_KEEP_DIRTY=1 to mark it." >&2
	fi
fi

make O="$build_root" "$defconfig"
make O="$build_root" -j"$jobs" CROSS_COMPILE="$CROSS_COMPILE" "$@"

# Copy whatever the configured BUILD_TARGET produced (u-boot.img for both
# boards); fall back to the raw u-boot.bin if the wrapper is unavailable.
for f in u-boot.img u-boot.bin; do
	[ -f "$build_root/$f" ] && cp "$build_root/$f" "$output_root/$f"
done

echo "==> $board artifacts in: $output_root"
ls -l "$output_root"
