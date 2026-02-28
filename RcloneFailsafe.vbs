Option Explicit
Dim WshShell
Set WshShell = WScript.CreateObject("WScript.Shell")

WshShell.Run "taskkill /f /im rclone.exe", 0, True
WScript.Sleep 3000

WshShell.Run "rclone mount ""Cloud Volume:"" Z: " & _
"--rc --rc-web-gui --rc-web-gui-no-open-browser " & _
"--rc-addr 127.0.0.1:7576 --rc-user rounak --rc-pass rounakbag2002 " & _
"--vfs-cache-mode writes " & _
"--vfs-read-ahead 512M " & _
"--buffer-size 512M " & _
"--dir-cache-time 1h " & _
"--poll-interval 10m " & _
"--transfers 4 --checkers 4 " & _
"--links", 0, False