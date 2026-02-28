Option Explicit
Dim WshShell
Set WshShell = WScript.CreateObject("WScript.Shell")

' Kill any leftover rclone processes before mounting
WshShell.Run "taskkill /f /im rclone.exe", 0, True

' Wait for network to initialize
WScript.Sleep 10000

WshShell.Run "rclone mount ""Cloud Volume:"" Z: " & _
"--rc --rc-web-gui --rc-web-gui-no-open-browser " & _
"--rc-addr 127.0.0.1:7576 --rc-no-auth " & _
"--vfs-cache-mode minimal " & _
"--buffer-size 1G " & _
"--dir-cache-time 12h " & _
"--poll-interval 10m " & _
"--transfers 2 --checkers 2 " & _
"--links", 0, False