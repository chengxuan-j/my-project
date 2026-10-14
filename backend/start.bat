@echo off
REM ============================================================
REM  老人陪伴后端 - 启动脚本
REM  用 backend\.venv 里的 Python 运行 run.py（监听 :8000）
REM  双击即可
REM ============================================================
setlocal
cd /d "%~dp0"

set "PYEXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYEXE%" (
    echo.
    echo   [错误] 未找到虚拟环境: .venv\Scripts\python.exe
    echo.
    echo   请先在本目录（backend）执行：
    echo       python -m venv .venv
    echo       .venv\Scripts\pip install -r requirements.txt
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

echo.
echo   Python : %PYEXE%
echo   地址   : http://127.0.0.1:8000
echo   文档   : http://127.0.0.1:8000/docs
echo   停止   : 在本窗口按 Ctrl+C
echo.

"%PYEXE%" run.py

echo.
echo   服务已退出。
pause
