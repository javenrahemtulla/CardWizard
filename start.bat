@echo off
rem Start Card Wizard on this computer (Windows). Data is stored in the "data" folder.
rem A password is required because the site may be reachable from the internet through a tunnel.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add Python to PATH", then run this again.
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: installing. This takes a few minutes and downloads a search model on first use...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if "%SITE_PASSWORD%"=="" (
  if exist .password (
    set /p SITE_PASSWORD=<.password
  ) else (
    set /p SITE_PASSWORD=Choose a password for the site ^(people will need it to open it^): 
    if "%SITE_PASSWORD%"=="" (
      echo A password is required.
      pause
      exit /b 1
    )
    >.password echo %SITE_PASSWORD%
  )
)

if "%PORT%"=="" set PORT=8000
echo Card Wizard is running at http://localhost:%PORT%  (username: anything, password: the one you chose)
echo Press Ctrl+C to stop.
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
