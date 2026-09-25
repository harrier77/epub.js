@echo off
cd /d "%~dp0"

start "" /b py app.py

:waitloop
netstat -ano | findstr /r /c:":5000 .*LISTENING" >nul
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)

start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge_proxy.exe" --profile-directory=Default --app-id=mleldakmoebeolhcnjndafbokokbkgcn --app-url=http://localhost:5000/ --app-launch-source=4
