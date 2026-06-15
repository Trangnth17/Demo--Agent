@echo off
echo ============================================
echo   CSAT Agent - Cai dat moi truong
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Python chua duoc cai. Dang tai Python 3.11...
    echo     Vao https://www.python.org/downloads/ de tai va cai Python 3.11+
    echo     Nho chon "Add Python to PATH" khi cai!
    pause
    exit /b 1
)

echo [OK] Python da co:
python --version

echo.
echo [*] Dang cai thu vien...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo [!] Loi khi cai thu vien. Kiem tra ket noi mang.
    pause
    exit /b 1
)

echo.
echo [OK] Cai dat hoan thanh!
echo.
echo Chay start.bat de khoi dong ung dung.
pause
