#!/usr/bin/env python3
import http.server
import json
import os
import threading
import time
import urllib.parse

HTDOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'lwip', 'httpd', 'htdocs')

MOCK_UBOOT_VERSION = "U-Boot XR1710G-2026-8-10-gfc5d785865fb (Aug 10 2026 - local preview)"
MOCK_RECOVERY_VERSION = "2026-8-8"
MOCK_CREDIT = "Gemtek-brightspeed-chainloader"
MOCK_DETECTED_LAYOUT = "2.0"

# Mirrors what /api/storage reports on real hardware: the raw MTD devices of
# the XR1710G 512 MiB SPI-NAND.  mtd_for_each_device() yields the chip itself
# first (ofs 0, parent == NULL) and then its six DT partitions.  UBI volumes
# are deliberately absent - they live inside "system", and a volume dump is
# not something the write path can put back, so the page no longer offers it.
MOCK_STORAGE_TARGETS = [
    {"kind": "mtd", "name": "spi-nand0", "size": 0x20000000, "ofs": 0x00000000},
    {"kind": "mtd", "name": "bootloader", "size": 0x00200000, "ofs": 0x00000000},
    {"kind": "mtd", "name": "uenv", "size": 0x00200000, "ofs": 0x00200000},
    {"kind": "mtd", "name": "dsd", "size": 0x00200000, "ofs": 0x00400000},
    {"kind": "mtd", "name": "chainloader", "size": 0x00100000, "ofs": 0x00600000},
    {"kind": "mtd", "name": "system", "size": 0x1b700000, "ofs": 0x00700000},
    {"kind": "mtd", "name": "reserved_bmt", "size": 0x04200000, "ofs": 0x1be00000},
]
MOCK_SEGMENT = 256 * 1024
_backup_seq = [1000]
_armed = {"id": 0, "name": None, "size": 0}


def next_backup_id():
    _backup_seq[0] += 1
    return _backup_seq[0]


def find_target(name):
    return next((x for x in MOCK_STORAGE_TARGETS if x['name'] == name), None)

prog_phase = 0
prog_done = 0
prog_total = 0
prog_erase_done = 0
prog_erase_total = 0
prog_write_done = 0
prog_write_total = 0
prog_lock = threading.Lock()


def reset_progress():
    global prog_phase, prog_done, prog_total
    global prog_erase_done, prog_erase_total
    global prog_write_done, prog_write_total
    with prog_lock:
        prog_phase = 0
        prog_done = 0
        prog_total = 0
        prog_erase_done = 0
        prog_erase_total = 0
        prog_write_done = 0
        prog_write_total = 0


def simulate_flash(target, layout, size):
    global prog_phase, prog_done, prog_total
    global prog_erase_done, prog_erase_total
    global prog_write_done, prog_write_total

    total_size = max(size, 1 * 1024 * 1024)
    erase_size = total_size

    with prog_lock:
        prog_phase = 1
        prog_total = total_size + erase_size
        prog_erase_total = erase_size
        prog_write_total = total_size

    for i in range(50):
        time.sleep(0.06)
        with prog_lock:
            if prog_phase != 1:
                return
            prog_erase_done = int(erase_size * (i + 1) / 50)
            prog_done = prog_erase_done

    with prog_lock:
        prog_phase = 2
        prog_erase_done = erase_size
        prog_done = erase_size

    for i in range(100):
        time.sleep(0.05)
        with prog_lock:
            if prog_phase != 2:
                return
            prog_write_done = int(total_size * (i + 1) / 100)
            prog_done = erase_size + prog_write_done

    with prog_lock:
        prog_phase = 3
        prog_write_done = total_size
        prog_done = total_size + erase_size


class RecoveryHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/index.html':
            self.serve_static('index.html')
            return
        if path == '/fail.html':
            self.serve_static('fail.html')
            return
        if path == '/about':
            self.send_json({
                "u_boot": MOCK_UBOOT_VERSION,
                "recovery_version": MOCK_RECOVERY_VERSION,
                "credit": MOCK_CREDIT,
                "detected_layout": MOCK_DETECTED_LAYOUT
            })
            return
        if path == '/status':
            with prog_lock:
                ok = (prog_phase == 3)
                err = (prog_phase == -1)
                in_progress = (prog_phase > 0 and prog_phase < 3)
                self.send_json({
                    "in_progress": 1 if in_progress else 0,
                    "done": prog_done,
                    "total": prog_total,
                    "erase_done": prog_erase_done,
                    "erase_total": prog_erase_total,
                    "write_done": prog_write_done,
                    "write_total": prog_write_total,
                    "ok": 1 if ok else 0,
                    "error": 1 if err else 0,
                    "phase": prog_phase
                })
            return

        if path == '/api/storage':
            self.send_json({
                "targets": MOCK_STORAGE_TARGETS
            })
            return

        if path.startswith('/api/backup/'):
            spec = path[len('/api/backup/'):]
            kind, _, name = spec.partition('/')
            if kind != 'mtd' or not name:
                self.send_error(404)
                return
            entry = find_target(name)
            if not entry:
                self.send_json({"error": "cannot backup '%s'" % name, "code": -19})
                return
            _armed.update(id=next_backup_id(), name=name, size=entry['size'])
            self.send_json({
                "id": _armed['id'],
                "kind": "mtd",
                "name": name,
                "size": entry['size']
            })
            return

        if path.startswith('/api/download/'):
            spec = path[len('/api/download/'):]
            parts = spec.split('/')
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                self.send_error(404)
                return
            _id, offset, length = (int(p) for p in parts)
            if (_id != _armed['id'] or length <= 0 or length > MOCK_SEGMENT or
                    offset + length > _armed['size']):
                self.send_error(400)
                return
            body = bytes((offset + i) & 0xFF for i in range(length))
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Disposition',
                             'attachment; filename="mock-backup.bin"')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        content_length_header = self.headers.get('Content-Length')
        try:
            content_length = int(content_length_header or 0)
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return

        if path == '/reboot':
            with prog_lock:
                reboot_busy = prog_phase > 0
            if parsed.query or content_length_header is None or content_length != 0 or reboot_busy:
                body = b'Bad Request'
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            print('[mock] reboot requested; normal startup simulated')
            body = b'OK'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith('/upload/firmware'):
            layout = query.get('layout', ['2.0'])[0]
            if layout not in ('2.0', '1.5', '1.0'):
                self.send_response(400)
                self.end_headers()
                return

            if content_length < 1 * 1024 * 1024:
                print(f"[mock] content_len {content_length} below min for firmware")
                self.send_response(400)
                self.end_headers()
                return

            body = self.rfile.read(content_length)
            print(f"[mock] firmware upload: {content_length} bytes, layout={layout}")

            reset_progress()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>OK</body></html>')

            t = threading.Thread(target=simulate_flash, args=('firmware', layout, content_length))
            t.daemon = True
            t.start()
            return

        if path == '/upload/partition':
            names = query.get('name', [])
            name = names[0] if names else ''
            entry = find_target(name)

            def reject(reason):
                # Drain the body first: answering before the client has
                # finished sending resets the connection and the browser
                # reports a network error instead of the 400 (the device
                # firmware reads the body before it validates too).
                if content_length > 0:
                    self.rfile.read(content_length)
                print(f"[mock] partition write rejected: {reason}")
                self.send_response(400)
                self.send_header('Content-Length', '0')
                self.send_header('Connection', 'close')
                self.end_headers()

            if not entry:
                reject(f"unknown target {name!r}")
                return
            if content_length <= 0 or content_length > entry['size']:
                reject(f"{content_length} bytes does not fit in {name} "
                       f"({entry['size']} bytes)")
                return

            self.rfile.read(content_length)
            print(f"[mock] partition write: {content_length} bytes -> {name}")

            reset_progress()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'OK')

            t = threading.Thread(target=simulate_flash,
                                 args=('partition', name, content_length))
            t.daemon = True
            t.start()
            return

        if path.startswith('/upload/uboot'):
            if content_length > 1 * 1024 * 1024:
                print(f"[mock] content_len {content_length} exceeds max for uboot")
                self.send_response(400)
                self.end_headers()
                return

            body = self.rfile.read(content_length)
            print(f"[mock] uboot upload: {content_length} bytes")

            reset_progress()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>OK</body></html>')

            t = threading.Thread(target=simulate_flash, args=('uboot', None, content_length))
            t.daemon = True
            t.start()
            return

        self.send_error(404)

    def serve_static(self, filename):
        filepath = os.path.join(HTDOCS_DIR, filename)
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        with open(filepath, 'rb') as f:
            content = f.read()
        self.send_response(200)
        if filename.endswith('.html'):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        else:
            self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data):
        body = (json.dumps(data) + '\n').encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[mock] {args[0]} - {args[1] if len(args) > 1 else ''}")


def main():
    port = 8080
    server = http.server.HTTPServer(('127.0.0.1', port), RecoveryHandler)
    print(f"XR1710G Recovery Mock Server running at http://127.0.0.1:{port}")
    print(f"  - GET  /about    -> version info")
    print(f"  - GET  /status   -> progress status")
    print(f"  - GET  /api/storage          -> MTD partition list")
    print(f"  - GET  /api/backup/mtd/<n>   -> arm a backup")
    print(f"  - GET  /api/download/<id>/<off>/<len>")
    print(f"  - POST /upload/firmware?layout=2.0")
    print(f"  - POST /upload/uboot")
    print(f"  - POST /upload/partition?name=<partition>")
    print(f"  - POST /reboot")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == '__main__':
    main()
