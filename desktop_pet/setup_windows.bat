@echo off
chcp 65001 >nul
title 驯龙高手 - 环境配置

echo ========================================
echo   驯龙高手 - 一键环境配置
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    echo   下载: https://www.python.org/downloads/
    echo   安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)
echo [OK] Python 已安装
python --version

:: Install dependencies
echo.
echo [1/4] 安装 Python 依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] 部分依赖安装失败，尝试逐个安装...
    pip install PyQt6
    pip install Pillow
    pip install rembg
    pip install imageio-ffmpeg
    pip install opencv-python
    pip install mediapipe
    pip install numpy
)
echo [OK] 依赖安装完成

:: Download face_landmarker.task if missing
echo.
echo [2/4] 检查人脸检测模型...
if exist face_landmarker.task (
    echo [OK] face_landmarker.task 已存在
) else (
    echo 正在下载 face_landmarker.task (~4.7 MB^)...
    curl -L -o face_landmarker.task ^
        https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
    if errorlevel 1 (
        echo [WARN] 下载失败，请手动下载:
        echo   https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
        echo   放到 desktop_pet/ 目录下
    ) else (
        echo [OK] 模型下载完成
    )
)

:: Generate assets
echo.
echo [3/4] 生成素材（帧提取 + 背景去除 + 音频）...
echo   首次运行 rembg 会下载模型 (~180 MB^)，请耐心等待
python prepare_assets.py
if errorlevel 1 (
    echo [ERROR] 素材生成失败
    pause
    exit /b 1
)
echo [OK] 素材生成完成

:: Done
echo.
echo [4/4] 环境配置完成！
echo ========================================
echo.
echo 运行方式:
echo   python main.py              (自动开始游戏)
echo   python main.py --no-auto    (手动右键开始)
echo   python main.py --no-camera  (纯观赏模式)
echo.
echo 右键奶龙: 切换难度 / 暂停 / 退出
echo ========================================
echo.
pause
