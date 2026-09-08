import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

# Base Paths
WORKSPACE_DIR = Path(__file__).resolve().parent
ICON_PATH = WORKSPACE_DIR / "app_icon.ico"
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")))
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", "C:\\Users\\AL RAZZAQ")) / "Desktop"
SHORTCUT_PATH = DESKTOP_DIR / "TradeTalk AI - Multi-Agent Forex Dashboard.lnk"
PROFILE_DIR = LOCAL_APP_DATA / "TradeTalk_Desktop_Profile"

# Configuration
USE_LOCAL_ENGINE = os.getenv("USE_LOCAL_ENGINE", "true").strip().lower() in ("true", "1", "yes")
DEFAULT_LOCAL_URL = "http://127.0.0.1:8000"
DEFAULT_CLOUD_URL = "https://multi-agent-trading-bot.onrender.com"

TARGET_URL = os.getenv("DESKTOP_APP_URL", DEFAULT_LOCAL_URL if USE_LOCAL_ENGINE else DEFAULT_CLOUD_URL)

def find_browser_executable() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("Neither Google Chrome nor Microsoft Edge could be found on the system.")

def purge_desktop_cache():
    print(f"[*] Purging Desktop Application Cache and Stale Storage at {PROFILE_DIR}...")
    if PROFILE_DIR.exists():
        try:
            # Purge cache subdirectories
            for sub in ["Cache", "Code Cache", "GPUCache", "Session Storage", "Local Storage", "IndexedDB", "Service Worker"]:
                target = PROFILE_DIR / "Default" / sub
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            print("[+] Desktop cache successfully purged.")
        except Exception as e:
            print(f"[!] Note on cache purge: {e}")
    else:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        print("[+] Created fresh desktop application profile directory.")

def update_desktop_shortcut(browser_path: str, url: str):
    print(f"[*] Updating Desktop Shortcut: {SHORTCUT_PATH} -> {url}")
    args = f'--app={url} --user-data-dir="{PROFILE_DIR}" --window-size=1440,920 --disable-features=Translate'
    
    ps_script = f"""
$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut('{str(SHORTCUT_PATH)}')
$sc.TargetPath = '{browser_path}'
$sc.Arguments = '{args}'
$sc.WorkingDirectory = '{str(WORKSPACE_DIR)}'
if (Test-Path '{str(ICON_PATH)}') {{
    $sc.IconLocation = '{str(ICON_PATH)}'
}}
$sc.Save()
"""
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
        if proc.returncode == 0:
            print("[+] Windows Desktop Shortcut updated successfully to point to local engine!")
        else:
            print(f"[!] PowerShell warning: {proc.stderr.strip()}")
    except Exception as e:
        print(f"[!] Could not update shortcut: {e}")

def launch_app(browser_path: str, url: str, wait: bool = False):
    print(f"\\n========================================================")
    print(f"  TRADETALK AI - AUTONOMOUS DESKTOP APP LAUNCHER")
    print(f"========================================================")
    print(f"  Target URL      : {url}")
    print(f"  Engine Mode     : {'LOCAL ENGINE (localhost:8000)' if '8000' in url else 'RENDER CLOUD'}")
    print(f"  Profile Storage : {PROFILE_DIR}")
    print(f"  Browser Binary  : {browser_path}")
    print(f"========================================================\\n")
    
    cmd = [
        browser_path,
        f"--app={url}",
        f"--user-data-dir={PROFILE_DIR}",
        "--window-size=1440,920",
        "--disable-features=Translate",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    
    if wait:
        subprocess.run(cmd)
    else:
        subprocess.Popen(cmd)
        print("[+] TradeTalk Desktop App successfully launched as a native standalone window!")

def main():
    parser = argparse.ArgumentParser(description="TradeTalk AI Desktop Launcher")
    parser.add_argument("--purge", action="store_true", help="Purge cached state and local storage before launching")
    parser.add_argument("--url", default=TARGET_URL, help="Target URL to bind the desktop app to")
    parser.add_argument("--wait", action="store_true", help="Wait for process to exit")
    parser.add_argument("--shortcut-only", action="store_true", help="Only update the shortcut without launching")
    args = parser.parse_args()

    browser = find_browser_executable()
    
    if args.purge or True:  # Always purge by default to clear stale blocked state
        purge_desktop_cache()

    update_desktop_shortcut(browser, args.url)

    if not args.shortcut_only:
        launch_app(browser, args.url, wait=args.wait)

if __name__ == "__main__":
    main()
