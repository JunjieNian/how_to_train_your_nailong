@echo off
chcp 65001 >nul
title 驯龙高手 - 打包

echo ========================================
echo   驯龙高手 - 打包为 .exe
echo ========================================
echo.

pip install pyinstaller >nul 2>&1
python build_exe.py

echo.
pause
