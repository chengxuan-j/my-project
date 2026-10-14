@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  小智 ESP32 语音服务 - 启动脚本
REM  WS :8001（设备语音通道） + HTTP :8003（OTA / 视觉）
REM  双击即可
REM ============================================================
cd /d "%~dp0"

REM ---- 查找带依赖的 Python ----
REM 优先级: XIAOZHI_PYTHON > 本目录 .venv/venv > PATH > conda 环境 xiaozhi
REM 判定条件: 该解释器装了 opuslib_next（TTS 下发音频必需）
set "PYEXE="
call :try "%XIAOZHI_PYTHON%"
call :try "%~dp0.venv\Scripts\python.exe"
call :try "%~dp0venv\Scripts\python.exe"
if not defined PYEXE for /f "delims=" %%I in ('where python 2^>nul') do call :try "%%I"
if not defined PYEXE call :find_conda_env
if not defined PYEXE goto :nopython

REM ---- 把 ffmpeg / opus.dll 加进 PATH（音频编解码必需）----
for %%I in ("%PYEXE%") do set "PYROOT=%%~dpI"
if exist "%PYROOT%Library\bin\ffmpeg.exe" (
    set "PATH=%PYROOT%Library\bin;%PATH%"
) else (
    where ffmpeg >nul 2>&1 || echo   [警告] 未找到 ffmpeg，音频合成可能失败
)

REM ---- 端口占用检查，避免起第二份 ----
set "BUSY="
for %%P in (8001 8003) do (
    netstat -ano -p tcp | findstr "LISTENING" | findstr ":%%P " >nul && set "BUSY=!BUSY! %%P"
)
if defined BUSY goto :portsbusy

echo.
echo   Python : %PYEXE%
echo   WS     : ws://本机IP:8001/xiaozhi/v1/
echo   HTTP   : http://本机IP:8003    (OTA + 视觉分析)
echo   停止   : 在本窗口按 Ctrl+C
echo.
echo   给机器狗上电，它会自动请求 OTA 并连上本机。
echo   日志出现 "conn - Headers:" 就表示狗已经连上了。
echo.

"%PYEXE%" app.py

echo.
echo   服务已退出。
pause
exit /b 0

REM ============================================================
REM  辅助
REM ============================================================

REM :try <python.exe 路径> —— 存在 且 装了 opuslib_next 才算数
:try
if defined PYEXE goto :eof
if "%~1"=="" goto :eof
if not exist "%~1" goto :eof
for %%I in ("%~1") do (
    if exist "%%~dpI..\Lib\site-packages\opuslib_next" set "PYEXE=%~1"
)
goto :eof

REM :find_conda_env —— 从 where conda 推出 envs\xiaozhi
:find_conda_env
for /f "delims=" %%I in ('where conda 2^>nul') do (
    set "CTMP=%%~dpI"
    set "CTMP=!CTMP:~0,-1!"
    for %%J in ("!CTMP!") do call :try "%%~dpJenvs\xiaozhi\python.exe"
    if defined PYEXE goto :eof
)
goto :eof

REM ============================================================
REM  错误处理
REM ============================================================

:nopython
echo.
echo   [错误] 找不到可用的 Python 解释器（需要装有 opuslib_next）。
echo.
echo   任选一种解决：
echo     A. 指定解释器路径（一次性）：
echo          setx XIAOZHI_PYTHON "D:\miniconda3\envs\xiaozhi\python.exe"
echo     B. 在本目录建 venv 并装依赖：
echo          python -m venv .venv
echo          .venv\Scripts\pip install -r requirements.txt
echo.
pause
exit /b 1

:portsbusy
echo.
echo   [错误] 端口已被占用: !BUSY!
echo          小智服务可能已在运行，先确认 8001 / 8003。
echo.
pause
exit /b 1
