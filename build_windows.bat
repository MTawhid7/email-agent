@echo off
REM build_windows.bat — Build Email Agent.exe on Windows
REM Usage: Double-click or run from Command Prompt

echo =^> Installing/upgrading build dependencies...
pip install --upgrade pyinstaller flask

echo =^> Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo =^> Running PyInstaller...
pyinstaller email_agent.spec

echo.
echo =^> Build complete!
echo     Exe: dist\Email Agent.exe
echo     Share 'Email Agent.exe' with coworkers.
echo     They double-click it — no Python or terminal needed.
pause
