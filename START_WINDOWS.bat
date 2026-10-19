@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python launcher not found. Install Python 3.11 or 3.12 and try again.
        pause
        exit /b 1
    )
    py -m venv .venv
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -c "import streamlit; assert streamlit.__version__ == '1.50.0'" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies. Internet access is needed for this first setup.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Setup or launch failed. See the message above and README.md.
pause
exit /b 1
