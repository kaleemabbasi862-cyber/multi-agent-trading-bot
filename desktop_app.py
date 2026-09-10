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

def is_server_running(host: str = "127.0.0.1", port: int = PORT, timeout: float = 0.4) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def start_backend_server():
    """Runs uvicorn FastAPI backend in background thread."""
    if is_server_running():
        return

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
            return

class DesktopAPI:
    """JS Bridge exposed to web frontend for native OS features."""
    def get_version(self):
        return "2.0.0"

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

def launch_app_window():
    """Launches high-performance desktop window using Microsoft Edge / Chrome in App Mode or default browser."""
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
            user_data = os.path.expandvars(r"%LocalAppData%\TradeTalk_App_Profile")
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

    # Keep Python backend process alive while serving requests
    while True:
        time.sleep(1.0)

def main():
    # 1. Start or verify backend server
    start_backend_server()

    # 2. Launch Desktop App Window
    launch_app_window()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        with open(os.path.join(os.path.dirname(__file__), "desktop_app_error.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[Error at {time.ctime()}]: {e}\n")
            traceback.print_exc(file=f)
