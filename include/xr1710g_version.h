/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __XR1710G_VERSION_H
#define __XR1710G_VERSION_H

#include <version.h>

/*
 * Keep the board banner tied to U-Boot's generated SCM version.
 *
 * PLAIN_VERSION is produced by scripts/setlocalversion as
 * "<UBOOTVERSION>[-<CONFIG_LOCALVERSION>]-<build date>-g<commit>", so the
 * string reported on the console and through /api/about can never again lag
 * behind the image that is actually running.  The "-dirty" suffix is
 * deliberately never emitted (see UBOOT_SETLOCALVERSION_FLAGS in the
 * Makefile): the banner describes a released image, not the state of
 * somebody's working copy.  Do NOT hand-edit a date here: the previous
 * hard-coded "2026-8-8" kept printing a release line months after the build
 * time, which is exactly what a stale banner looks like.
 */
#define XR1710G_RELEASE_VERSION PLAIN_VERSION
#define XR1710G_RELEASE_CREDIT  "naoki66"

#endif /* __XR1710G_VERSION_H */
