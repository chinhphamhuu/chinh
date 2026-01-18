@echo off
:: RK ROM Kitchen - Run Script
:: Sử dụng venv để cách ly dependencies

echo ========================================
echo  RK ROM Kitchen - Development Mode
echo ========================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python khong duoc cai dat!
    echo Vui long cai dat Python 3.10+ tu https://python.org
    pause
    exit /b 1
)

:: Setup venv nếu chưa có
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Tao virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Khong the tao venv!
        echo Thu chay: python -m venv .venv
        pause
        exit /b 1
    )
)

:: Activate và sử dụng python trong venv
set PYTHON=.venv\Scripts\python.exe

:: Upgrade pip
echo [INFO] Kiem tra pip...
%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip khong hoat dong trong venv!
    pause
    exit /b 1
)

:: Check và install runtime requirements
echo [INFO] Kiem tra dependencies...
%PYTHON% -c "import PyQt5; import send2trash" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Cai dat runtime dependencies...
    %PYTHON% -m pip install -r requirements.runtime.txt
    if errorlevel 1 (
        echo [ERROR] Cai dat dependencies that bai!
        echo Vui long chay thu cong:
        echo   .venv\Scripts\python -m pip install -r requirements.runtime.txt
        pause
        exit /b 1
    )
)

:: Run app
echo [INFO] Khoi dong RK ROM Kitchen...
echo [INFO] Python: %PYTHON%
echo.
%PYTHON% -m app.main

if errorlevel 1 (
    echo.
    echo [ERROR] Ung dung bi loi!
    echo Xem log de biet chi tiet.
    pause
)
