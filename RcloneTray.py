"""
RcloneTray.py
Tray monitor for rclone mount — always-on mode
Requires: pip install pystray pillow psutil
"""

import threading
import subprocess
import time

import psutil
import pystray
from PIL import Image, ImageDraw

# ─────────────────────────────────────────────────────────────────────────────
#  Config — adjust these to match your setup
# ─────────────────────────────────────────────────────────────────────────────

RC_ADDR           = "127.0.0.1:7576"
RC_USER           = "username"
RC_PASS           = "password"
REMOUNT_TASK_NAME = "RcloneRemount"  # Task Scheduler task name
CHECK_INTERVAL    = 5    # seconds between auto-detect checks
STARTUP_GRACE     = 40   # seconds to wait before first auto-detect


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_icon(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    return img


def is_rclone_running() -> bool:
    for p in psutil.process_iter(["name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == "rclone.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def start_rclone():
    """Trigger the RcloneRemount scheduled task — runs in user session so Z: mounts correctly."""
    if not is_rclone_running():
        subprocess.Popen(
            ["schtasks", "/run", "/tn", REMOUNT_TASK_NAME],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def stop_rclone():
    if is_rclone_running():
        # Graceful quit via RC
        try:
            subprocess.run(
                [
                    "rclone", "rc", "core/quit",
                    f"--rc-addr={RC_ADDR}",
                    f"--rc-user={RC_USER}",
                    f"--rc-pass={RC_PASS}",
                ],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5
            )
        except Exception:
            pass
        time.sleep(3)
        # Force kill any remaining rclone processes
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and p.info["name"].lower() == "rclone.exe":
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(2)


def wait_for_port_free(port: int, timeout: int = 15):
    """Wait until port is no longer in use."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        conns = [c for c in psutil.net_connections()
                 if c.laddr and c.laddr.port == port]
        if not conns:
            return
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
#  Tray app
# ─────────────────────────────────────────────────────────────────────────────

class RcloneTray:
    def __init__(self):
        self._lock    = threading.Lock()
        self._stop_ev = threading.Event()

        self.icon = pystray.Icon(
            "rclone_tray",
            make_icon("#ff4444"),
            "Rclone: Stopped",
            menu=pystray.Menu(
                pystray.MenuItem("Toggle Rclone", self._toggle, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start Rclone",  self._menu_start),
                pystray.MenuItem("Stop Rclone",   self._menu_stop),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit",          self._menu_exit),
            )
        )

    # ── Icon state ────────────────────────────────────────────────────────────

    def _set_running(self):
        self.icon.icon  = make_icon("#32cd32")
        self.icon.title = "Rclone: Running"

    def _set_stopped(self):
        self.icon.icon  = make_icon("#ff4444")
        self.icon.title = "Rclone: Stopped"

    def _set_busy(self):
        self.icon.icon  = make_icon("#ffa500")
        self.icon.title = "Rclone: Working…"

    def _refresh_icon(self):
        if is_rclone_running():
            self._set_running()
        else:
            self._set_stopped()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_start(self):
        with self._lock:
            if is_rclone_running():
                return
            self._set_busy()
            wait_for_port_free(int(RC_ADDR.split(":")[1]))
            start_rclone()
            time.sleep(5)  # give VBS time to start rclone
            self._refresh_icon()

    def _do_stop(self):
        with self._lock:
            if not is_rclone_running():
                return
            self._set_busy()
            stop_rclone()
            self._refresh_icon()

    def _toggle(self, icon=None, item=None):
        threading.Thread(target=self._toggle_worker, daemon=True).start()

    def _toggle_worker(self):
        if is_rclone_running():
            self._do_stop()
        else:
            self._do_start()

    def _menu_start(self, icon=None, item=None):
        threading.Thread(target=self._do_start, daemon=True).start()

    def _menu_stop(self, icon=None, item=None):
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _menu_exit(self, icon=None, item=None):
        self._stop_ev.set()
        self.icon.stop()

    # ── Auto-detect loop (always-on — restarts rclone if it crashes) ──────────

    def _auto_detect(self):
        # Wait for boot mount to finish before first check
        self._stop_ev.wait(STARTUP_GRACE)
        self._refresh_icon()

        while not self._stop_ev.wait(CHECK_INTERVAL):
            if not is_rclone_running():
                # Rclone crashed or was stopped externally — restart it
                threading.Thread(target=self._do_start, daemon=True).start()
            else:
                self._refresh_icon()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        self._refresh_icon()
        threading.Thread(target=self._auto_detect, daemon=True).start()
        self.icon.run()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RcloneTray().run()