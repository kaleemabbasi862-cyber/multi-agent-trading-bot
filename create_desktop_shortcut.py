import os
import subprocess
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent
ICON_PATH = WORKSPACE_DIR / "app_icon.ico"
VBS_PATH = WORKSPACE_DIR / "launch_desktop_app.vbs"
BAT_PATH = WORKSPACE_DIR / "launch_desktop_app.bat"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", "C:\\Users\\AL RAZZAQ")) / "Desktop"
SHORTCUT_PATH = DESKTOP_DIR / "TradeTalk AI.lnk"

def make_shortcut():
    ps_script = f"""
$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut('{str(SHORTCUT_PATH)}')
$sc.TargetPath = 'wscript.exe'
$sc.Arguments = '"{str(VBS_PATH)}"'
$sc.WorkingDirectory = '{str(WORKSPACE_DIR)}'
$sc.Description = 'TradeTalk AI - Institutional Multi-Agent Trading Terminal'
if (Test-Path '{str(ICON_PATH)}') {{
    $sc.IconLocation = '{str(ICON_PATH)}'
}}
$sc.Save()
"""
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"[+] Desktop shortcut successfully created: {SHORTCUT_PATH}")
    else:
        print(f"[!] Error creating shortcut: {res.stderr}")

if __name__ == "__main__":
    make_shortcut()
