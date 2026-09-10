Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "d:\Users\AL RAZZAQ\Desktop\Trade Talk"

' 1. Clean port 8000 quietly
WshShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -aon ^| findstr "":8000"" ^| findstr ""LISTENING""') do taskkill /F /PID %a", 0, True

' 2. Launch TradeTalk desktop application silently (0 = completely hidden)
WshShell.Run """C:\Users\AL RAZZAQ\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"" ""d:\Users\AL RAZZAQ\Desktop\Trade Talk\desktop_app.py""", 0, False
