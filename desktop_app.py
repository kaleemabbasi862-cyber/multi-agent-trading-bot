import os
import sys

# Ensure stdout and stderr are safe when running under pythonw (windowless)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import time
try:
    with open(os.path.join(os.path.dirname(__file__), "desktop_app_runtime.log"), "w", encoding="utf-8") as _log:
        _log.write(f"Starting desktop_app.py at {time.ctime()}\n")
except Exception:
    pass

import threading
import urllib.request
import uvicorn
import webview
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = str(BASE_DIR / "app_icon.ico")
PORT = 8000
LOCAL_URL = f"http://127.0.0.1:{PORT}"

def is_port_open(host: str = "127.0.0.1", port: int = PORT, timeout: float = 0.4) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def is_server_running(url: str = LOCAL_URL, timeout: float = 1.0) -> bool:
    """Verify port 8000 is serving TradeTalk, not merely any HTTP process."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/desktop-health", headers={"User-Agent": "TradeTalk-Desktop"})
        with urllib.request.urlopen(req, timeout=max(timeout, 2.0)) as resp:
            if resp.status != 200:
                return False
            import json
            payload = json.loads(resp.read().decode("utf-8"))
            return (
                isinstance(payload, dict)
                and payload.get("status") == "healthy"
                and payload.get("desktop_api") is True
            )
    except Exception:
        return False

def start_backend_server() -> bool:
    """Start the backend and return True only when this process owns it."""
    if is_server_running():
        return False
    if is_port_open():
        # Another click may have started the backend milliseconds earlier.
        for _ in range(20):
            time.sleep(0.25)
            if is_server_running():
                return False
        raise RuntimeError("Port 8000 is occupied but is not responding as TradeTalk. Refusing to start a duplicate backend.")

    from main_native import app
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server to come online
    for _ in range(60):
        time.sleep(0.25)
        if is_server_running():
            return True
    raise RuntimeError("TradeTalk backend failed health verification after startup.")

class DesktopAPI:
    """JS Bridge exposed to web frontend for native OS features."""
    def get_version(self):
        return "2.0.0-6agents"

    def minimize_window(self):
        try:
            webview.windows[0].minimize()
        except Exception:
            pass

    def maximize_window(self):
        try:
            webview.windows[0].toggle_fullscreen()
        except Exception:
            pass

    def close_app(self):
        try:
            webview.windows[0].destroy()
        except Exception:
            sys.exit(0)

def launch_app_window(keep_backend_alive: bool):
    """Launch the desktop window and keep alive only when this process owns the backend."""
    import subprocess
    import webbrowser

    browser_candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
    ]

    launched = False
    for b in browser_candidates:
        if os.path.isfile(b):
            user_data = os.path.expandvars(r"%LocalAppData%\TradeTalk_Desktop_Profile")
            cmd = [
                b,
                f"--app={LOCAL_URL}",
                f"--user-data-dir={user_data}",
                "--window-size=1500,950"
            ]
            try:
                subprocess.Popen(cmd)
                launched = True
                break
            except Exception:
                pass

    if not launched:
        webbrowser.open(LOCAL_URL)

    # Only the process that started uvicorn must remain alive.
    if keep_backend_alive:
        while True:
            time.sleep(1.0)

def main():
    # 1. Start or verify backend server
    owns_backend = start_backend_server()

    # 2. Launch Desktop App Window
    launch_app_window(keep_backend_alive=owns_backend)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        with open(os.path.join(os.path.dirname(__file__), "desktop_app_error.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[Error at {time.ctime()}]: {e}\n")
            traceback.print_exc(file=f)
