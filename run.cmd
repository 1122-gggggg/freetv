@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%~dp0freetv.py" %*
  exit /b %ERRORLEVEL%
)
python "%~dp0freetv.py" %*
exit /b %ERRORLEVEL%
