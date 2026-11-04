@echo off
rem VR Backtest - open the settings window without building an exe
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo First run: installing packages...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe gui.py
