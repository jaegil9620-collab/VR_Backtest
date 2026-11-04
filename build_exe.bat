@echo off
rem VR Backtest - build VR_Backtest.exe (run once, takes a few minutes)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name VR_Backtest --collect-data plotly --collect-all yfinance --collect-all curl_cffi gui.py
if exist dist\VR_Backtest.exe (
  copy /y dist\VR_Backtest.exe VR_Backtest.exe >nul
  echo.
  echo DONE: VR_Backtest.exe created in %~dp0
) else (
  echo.
  echo BUILD FAILED - use run_gui.bat instead
)
pause
