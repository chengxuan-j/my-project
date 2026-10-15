@echo off
REM ============================================================
REM  老人情感陪伴 AI - 后端启动脚本
REM  注意：本文件必须保存为 GBK/ANSI 编码，存成 UTF-8 会让中文乱码
REM  用 backend\.venv 里的 Python 运行 run.py（监听 :8000）
REM  双击即可
REM ============================================================
chcp 936 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
set "PORT=8000"

if not exist "%PYEXE%" (
    echo.
    echo   [错误] 未找到虚拟环境: .venv\Scripts\python.exe
    echo.
    echo   请先在本目录（backend）执行：
    echo       python -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0.env" (
    echo.
    echo   [提示] 未找到 backend\.env —— 服务能正常启动，但 /chat 等接口会因缺少
    echo          QWEN_API_KEY 返回 502。需要完整功能时：
    echo              copy ..\.env.example .env
    echo          再编辑 .env 填入 QWEN_API_KEY。
    echo.
)

REM 端口占用检查：已有进程在跑时直接提示，避免 uvicorn 抛 WinError 10048
netstat -ano | findstr /c:"LISTENING" | findstr /c:":%PORT% " >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   [错误] 端口 %PORT% 已被占用，本服务无法启动（uvicorn 会报 WinError 10048）。
    echo.
    echo   查看占用者：  netstat -ano ^| findstr ":%PORT%"
    echo   结束占用者：  taskkill /PID ^<上面查到的PID^> /F
    echo   或换端口：    修改 run.py 里的 port=%PORT%
    echo.
    pause
    exit /b 1
)

echo.
echo   Python : %PYEXE%
echo   地址   : http://127.0.0.1:%PORT%
echo   文档   : http://127.0.0.1:%PORT%/docs
echo   停止   : 在本窗口按 Ctrl+C
echo.

"%PYEXE%" run.py

echo.
echo   服务已退出。
pause
