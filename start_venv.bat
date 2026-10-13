@echo off

set PYTHONPATH=%~dp0

if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment .venv folder not found!
    echo Please make sure .venv is created in the project root.
    pause
    exit /b 1
)

echo [INFO] Activating virtual environment...
call "%~dp0.venv\Scripts\activate.bat"

cmd /k
