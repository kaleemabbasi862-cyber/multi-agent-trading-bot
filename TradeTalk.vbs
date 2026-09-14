Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "d:\Users\AL RAZZAQ\Desktop\Trade Talk"

' Launch TradeTalk desktop application silently (0 = completely hidden)
' Port management is handled safely by desktop_app.py with health verification
WshShell.Run """C:\Users\AL RAZZAQ\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"" ""d:\Users\AL RAZZAQ\Desktop\Trade Talk\desktop_app.py""", 0, False
