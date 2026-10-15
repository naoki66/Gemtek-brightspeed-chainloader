#!/usr/bin/env python3
"""Rebuild fsdata_xr1710g.c from the htdocs/ directory.

This is a small, dependency-free stand-in for the lwIP `makefsdata` perl
script. It is kept in the repo so the recovery pages can be rebuilt on hosts
without perl (for example Windows). Output is byte-for-byte identical to the
file produced by upstream makefsdata for the same inputs.

Usage:
    python lib/lwip/httpd/makefsdata.py [htdocs_dir] [output_file]

Defaults: htdocs_dir = <script dir>/htdocs, output_file = <script dir>/fsdata_xr1710g.c
"""

import os
import re
import sys

LWIP_SERVER = "lwIP/2.2.0 (http://savannah.nongnu.org/projects/lwip)"
STATUS_LINES = {
    "200": "200 OK",
    "400": "400 Bad Request",
    "404": "404 Not Found",
}
MIME = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
}


def symbol(name):
    """'/index.html' -> 'index_html'"""
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() and ord(ch) < 128) else "_")
    return "".join(out).lstrip("_")


def hex_lines(data, width=16):
    return [",".join("0x%02x" % b for b in data[i:i + width]) + ","
            for i in range(0, len(data), width)]


def status_for(path):
    base = os.path.basename(path)
    code = base.split(".")[0]
    if len(code) == 3 and code.isdigit() and code in STATUS_LINES:
        return STATUS_LINES[code]
    return STATUS_LINES["200"]


def header_lines(path, size):
    """HTTP header split into one entry per line (line ending kept implicit).

    The last entry carries the blank line that terminates the header block.
    """
    ext = os.path.splitext(path)[1].lower()
    ctype = MIME.get(ext, "text/html")
    return [
        "HTTP/1.0 " + status_for(path),
        "Server: " + LWIP_SERVER,
        "Content-Length: " + str(size),
        "Content-Type: " + ctype + "\r\n",
    ]


def minify(text):
    """Conservative shrink of the embedded pages.

    Only drops HTML/CSS comments and redundant whitespace; nothing that could
    change the meaning of a declaration is touched (no rewriting of values,
    no touching of url(...) payloads).
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    def shrink_css(match):
        css = match.group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        css = re.sub(r"\s+", " ", css)
        css = re.sub(r"\s*([{};])\s*", r"\1", css)
        return "<style>" + css.strip() + "</style>"

    return re.sub(r"<style>(.*?)</style>", shrink_css, text, flags=re.S)


def build(src_dir, out_path, do_minify=False):
    names = sorted(n for n in os.listdir(src_dir)
                   if os.path.isfile(os.path.join(src_dir, n)))
    if not names:
        raise SystemExit("no files found in " + src_dir)

    files = []
    for name in names:
        with open(os.path.join(src_dir, name), "rb") as handle:
            data = handle.read()
        if do_minify and name.lower().endswith((".html", ".htm")):
            data = minify(data.decode("utf-8")).encode("utf-8")
        files.append((name, data, header_lines(name, len(data))))

    out = []
    w = out.append
    w('#include "lwip/apps/fs.h"')
    w('#include "lwip/def.h"')
    w("")
    w("")
    w("#define file_NULL (struct fsdata_file *) NULL")
    w("")
    w("")
    w("#ifndef FS_FILE_FLAGS_HEADER_INCLUDED")
    w("#define FS_FILE_FLAGS_HEADER_INCLUDED 1")
    w("#endif")
    w("#ifndef FS_FILE_FLAGS_HEADER_PERSISTENT")
    w("#define FS_FILE_FLAGS_HEADER_PERSISTENT 0")
    w("#endif")
    w("/* FSDATA_FILE_ALIGNMENT: 0=off, 1=by variable, 2=by include */")
    w("#ifndef FSDATA_FILE_ALIGNMENT")
    w("#define FSDATA_FILE_ALIGNMENT 0")
    w("#endif")
    w("#ifndef FSDATA_ALIGN_PRE")
    w("#define FSDATA_ALIGN_PRE")
    w("#endif")
    w("#ifndef FSDATA_ALIGN_POST")
    w("#define FSDATA_ALIGN_POST")
    w("#endif")
    w("#if FSDATA_FILE_ALIGNMENT==2")
    w('#include "fsdata_alignment.h"')
    w("#endif")

    for index, (name, data, header) in enumerate(files):
        sym = symbol(name)
        w("#if FSDATA_FILE_ALIGNMENT==1")
        w("static const unsigned int dummy_align__%s = %d;" % (sym, index))
        w("#endif")
        w("static const unsigned char FSDATA_ALIGN_PRE data__%s[] "
          "FSDATA_ALIGN_POST = {" % sym)
        w("/* /%s (%d chars) */" % (name, len(name) + 2))
        raw_name = ("/" + name).encode("utf-8") + b"\x00"
        pad = (-len(raw_name)) % 4
        out.extend(hex_lines(raw_name + b"\x00" * pad))
        w("")
        w("/* HTTP header */")

        for part in header:
            line = part + "\r\n"
            shown = part.replace("\r", "")
            if part.startswith("Content-Length:"):
                comment = '/* "Content-Length: %s\n" (18+ bytes) */' % (
                    str(len(data)),)
            else:
                comment = '/* "%s\n" (%d bytes) */' % (shown, len(line))
            out.extend(comment.split("\n"))
            out.extend(hex_lines(line.encode("utf-8")))

        w("/* raw file data (%d bytes) */" % len(data))
        body = hex_lines(data)
        if not body:
            body = []
        out.extend(body)
        # terminate the array: '};' glued to the last hex line
        if body:
            out[-1] = out[-1] + "};"
        else:
            w("};")
        w("")

    w("")
    w("")

    prev = "file_NULL"
    for name, data, header in files:
        sym = symbol(name)
        offset = len(("/" + name).encode("utf-8")) + 1
        offset += (-offset) % 4
        w("const struct fsdata_file file__%s[] = { {" % sym)
        w(prev + ",")
        w("data__%s," % sym)
        w("data__%s + %d," % (sym, offset))
        w("sizeof(data__%s) - %d," % (sym, offset))
        w("FS_FILE_FLAGS_HEADER_INCLUDED | FS_FILE_FLAGS_HEADER_PERSISTENT,")
        w("}};")
        w("")
        prev = "file__" + sym

    w("#define FS_ROOT file__%s" % symbol(files[-1][0]))
    w("#define FS_NUMFILES %d" % len(files))
    w("")
    w("")

    text = "\n".join(out)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("wrote %s (%d files, %d bytes)" % (out_path, len(files), len(text)))


def main():
    args = [a for a in sys.argv[1:] if a != "--minify"]
    do_minify = "--minify" in sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    src = args[0] if args else os.path.join(here, "htdocs")
    dst = args[1] if len(args) > 1 else os.path.join(here, "fsdata_xr1710g.c")
    build(src, dst, do_minify)


if __name__ == "__main__":
    main()
