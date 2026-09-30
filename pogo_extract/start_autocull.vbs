' Starts the autocull watcher hidden at login. It polls the Pokemon box and fires the GATED
' full_audit.py (4 independent audits must pass or it refuses to sync). It only ever TAGS.
Set s = CreateObject("WScript.Shell")
s.CurrentDirectory = "C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
s.Run """C:\Program Files\Python314\python.exe"" ""C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\autocull_watch.py""", 0, False
