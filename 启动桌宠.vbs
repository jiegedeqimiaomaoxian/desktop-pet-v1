' 深海小女仆 · DeepSeek 桌宠 2.0 —— 静默启动（不弹黑框）
Option Explicit
Dim fso, shell, base
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
shell.Run "pythonw.exe """ & base & "\pet\main.py""", 0, False
