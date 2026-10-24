"""Runs ON the Raspberry Pi. Serves full-resolution stills to the laptop over the local network.

Setup on the Pi (Raspberry Pi OS Bookworm, camera module connected):
    sudo apt install -y python3-picamera2
    python3 pi_snapshot_server.py            # then open http://<pi-host>:8080/snapshot.jpg from the laptop

Endpoints:
    GET /snapshot.jpg   full-resolution still (autofocus first on Camera Module 3)
    GET /preview.jpg    small, fast frame for change detection
    GET /health         "ok"
"""
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from picamera2 import Picamera2

PORT = 8080
lock = threading.Lock()

cam = Picamera2()
still_cfg = cam.create_still_configuration()                       # sensor's full resolution
preview_cfg = cam.create_preview_configuration(main={"size": (640, 480)})
cam.configure(preview_cfg)
cam.start()

try:  # Camera Module 3 has autofocus; older modules don't — ignore if unsupported
    from libcamera import controls
    cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
    HAS_AF = True
except Exception:
    HAS_AF = False


def jpeg(full: bool) -> bytes:
    buf = io.BytesIO()
    with lock:
        if full:
            if HAS_AF:
                try:
                    cam.autofocus_cycle()
                except Exception:
                    pass
            cam.switch_mode_and_capture_file(still_cfg, buf, format="jpeg")
        else:
            cam.capture_file(buf, format="jpeg")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/snapshot.jpg"):
            body, ctype = jpeg(True), "image/jpeg"
        elif self.path.startswith("/preview.jpg"):
            body, ctype = jpeg(False), "image/jpeg"
        elif self.path.startswith("/health"):
            body, ctype = b"ok", "text/plain"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Serving on :{PORT}  (autofocus: {HAS_AF})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
