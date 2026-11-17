@echo off
chcp 65001 >nul
setlocal
set ADB=E:\tools\platform-tools\adb.exe

if not exist "%ADB%" (
  echo [X] adb not found at %ADB%
  exit /b 1
)

echo === devices ===
"%ADB%" devices
echo.

echo === setup reverse: phone localhost:3000 / 8000 -^> PC ===
"%ADB%" reverse tcp:3000 tcp:3000
"%ADB%" reverse tcp:8000 tcp:8000
echo.

echo === current forwards ===
"%ADB%" reverse --list
echo.

echo Done. On the phone open Chrome and go to:  http://localhost:3000
echo (Keep the USB cable plugged in. Re-run this script after unplugging.)
pause
