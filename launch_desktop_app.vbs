Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir
cmd = "cmd.exe /c """ & baseDir & "\launch_tradetalk.bat"""
shell.Run cmd, 0, False
