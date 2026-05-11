@echo off
chcp 65001 >nul
title 驯龙高手 - 打包

echo ========================================
echo   驯龙高手 - 打包为 .exe
echo ========================================
echo.
echo 建议在干净的 conda 环境中打包：
echo   conda create -n build python=3.12 -y
echo   conda activate build
echo   pip install PySide6 opencv-python mediapipe numpy pyinstaller Pillow
echo   python build_exe.py
echo.
echo 如果当前环境已就绪，按任意键继续打包...
pause >nul

pip install pyinstaller >nul 2>&1
python build_exe.py

echo.
pause
