@echo off
echo ============================================
echo   CSAT Chatbot Analysis Agent
echo ============================================
echo.

REM Copy .env nếu chưa có
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [OK] Tao file .env tu .env.example
    )
)

REM Tạo thư mục output nếu chưa có
if not exist uploads mkdir uploads
if not exist output  mkdir output

echo [*] Khoi dong server tai http://localhost:8000
echo     Nhan Ctrl+C de dung server
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
