@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  XiaoZhi Robot Dog - All-in-One Launcher
REM  Starts: Voice Backend (WS 8001) + Web Frontend (8080) + Vision Control
REM  ASCII-only + GBK + CRLF: avoids cmd encoding issues
REM ============================================================

REM ROOT = project root (this script lives in docs/, so go one level up)
set "ROOT=%~dp0.."
set "SERVER=%ROOT%robot\xiaozhi-server"
set "WEB=%ROOT%robot\web-control"
set "DOG_IP=10.1.56.231"

REM ============================================================
REM  Auto-detect Python with funasr + mediapipe
REM  Priority: XIAOZHI_PYTHON > project venv > PATH > conda xiaozhi
REM  Each candidate is tested for funasr presence (voice backend requirement)
REM ============================================================
set "PYEXE="
call :try "%XIAOZHI_PYTHON%"
call :try "%ROOT%.venv\Scripts\python.exe"
call :try "%ROOT%venv\Scripts\python.exe"
call :try "%SERVER%\.venv\Scripts\python.exe"
call :try "%SERVER%\venv\Scripts\python.exe"
if not defined PYEXE for /f "delims=" %%I in ('where python 2^>nul') do call :try "%%I"
if not defined PYEXE call :find_conda_env
if not defined PYEXE goto :nopython

REM ---- Check required files ----
if not exist "%SERVER%\app.py" goto :miss_server
if not exist "%WEB%\index.html" goto :miss_web

REM ---- Add ffmpeg to PATH (from conda env Library\bin if available) ----
for %%I in ("%PYEXE%") do set "PYROOT=%%~dpI"
if exist "%PYROOT%Library\bin\ffmpeg.exe" (
    set "PATH=%PYROOT%Library\bin;%PATH%"
) else (
    where ffmpeg >nul 2>&1 || echo   [WARN] ffmpeg not found, audio synthesis may fail
)

REM ---- Port occupancy check: avoid starting a second backend ----
set "BUSY="
for %%P in (8001 8003) do (
    netstat -ano -p tcp | findstr "LISTENING" | findstr ":%%P " >nul && set "BUSY=!BUSY! %%P"
)
if defined BUSY goto :portsbusy
set "WEB_BUSY="
netstat -ano -p tcp | findstr "LISTENING" | findstr ":8080 " >nul && set "WEB_BUSY=1"

echo.
echo   Python: %PYEXE%
echo   Dog IP: %DOG_IP%
echo.
echo   [1/2] Starting voice backend  (WS 8001 / OTA 8003) ...
start "XiaoZhi-Voice" /D "%SERVER%" cmd /k ""%PYEXE%" app.py"

if defined WEB_BUSY (
    echo   [2/2] Web frontend already listening on 8080; skipping duplicate launch.
) else (
    echo   [2/2] Starting web frontend   (http://127.0.0.1:8080) ...
    start "XiaoZhi-Web" /D "%WEB%" cmd /k ""%PYEXE%" server.py"
)

echo.
echo   Both services launched in separate windows.
echo   Wait for the voice backend to show "Websocket address: ws://..."
echo   Then open web frontend in browser:
echo     http://127.0.0.1:8080
echo.
echo   Voice control: speak to dog's microphone
echo   Vision control: click "Open Camera" button in web page, then make gestures
echo.
echo   To stop: close all service windows.
echo.
pause
exit /b 0

REM ============================================================
REM  Helper functions
REM ============================================================

REM :try <python.exe path>  Test if path exists AND has funasr in site-packages
:try
if defined PYEXE goto :eof
if "%~1"=="" goto :eof
if not exist "%~1" goto :eof
for %%I in ("%~1") do (
    if exist "%%~dpILib\site-packages\funasr" set "PYEXE=%~1"
    if exist "%%~dpI..\Lib\site-packages\funasr" set "PYEXE=%~1"
)
goto :eof

REM :find_conda_env  Derive conda envs\xiaozhi from where conda lives
:find_conda_env
for /f "delims=" %%I in ('where conda 2^>nul') do (
    set "CTMP=%%~dpI"
    set "CTMP=!CTMP:~0,-1!"
    for %%J in ("!CTMP!") do call :try "%%~dpJenvs\xiaozhi\python.exe"
    if defined PYEXE goto :eof
)
goto :eof

REM ============================================================
REM  Error handlers
REM ============================================================

:nopython
echo.
echo   [ERROR] Cannot find suitable Python interpreter.
echo           Requirement: must have funasr in site-packages (voice backend)
echo.
echo   Searched:
echo     1. XIAOZHI_PYTHON env var
echo     2. .venv / venv in project or server directory
echo     3. python on PATH
echo     4. conda env named xiaozhi
echo.
echo   Solutions:
echo     A. Set XIAOZHI_PYTHON to your interpreter path:
echo          setx XIAOZHI_PYTHON "D:\miniconda3\envs\xiaozhi\python.exe"
echo     B. Create a project venv and install dependencies:
echo          python -m venv .venv
echo          .venv\Scripts\pip install -r robot\xiaozhi-server\requirements.txt
echo     C. Create a conda env named xiaozhi:
echo          conda create -n xiaozhi python=3.10
echo          conda run -n xiaozhi pip install -r robot\xiaozhi-server\requirements.txt
echo.
pause
exit /b 1

:portsbusy
echo.
echo   [ERROR] Backend ports already in use: !BUSY!
echo           XiaoZhi may already be running. Check 8001 and 8003 before starting another copy.
echo           Existing processes were not changed.
echo.
pause
exit /b 1

:miss_server
echo.
echo   [ERROR] Voice backend not found: %SERVER%\app.py
echo.
pause
exit /b 1

:miss_web
echo.
echo   [ERROR] Web frontend not found: %WEB%\index.html
echo.
pause
exit /b 1

REM ------------------------------------------------------------
REM Optional: uncomment to set proxy for LLM/TTS if they timeout
REM set "HTTPS_PROXY=http://127.0.0.1:7890"
REM set "NO_PROXY=127.0.0.1,localhost,10.1.56.231"
REM Do NOT set HTTP_PROXY or the dog will also be proxied
REM ------------------------------------------------------------
