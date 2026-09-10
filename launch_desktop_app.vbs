Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "d:\Users\AL RAZZAQ\Desktop\Trade Talk"
WshShell.Run """C:\Users\AL RAZZAQ\AppData\Local\Python\pythoncore-3.14-64\python.exe"" desktop_app.py", 0, False
