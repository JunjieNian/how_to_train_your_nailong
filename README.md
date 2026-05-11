# 驯龙高手 How to Train Your Nailong

<p align="center">
  <img src="desktop_pet/assets/idle/0010.png" alt="奶龙" height="200" />
</p>

**憋笑挑战**桌面小游戏。你盯着奶龙，摄像头实时检测你的表情——谁先笑，谁就输。

奶龙有一个隐藏的"绷不住"倒计时：如果你在倒计时结束前忍住不笑，奶龙会先笑，你赢了；如果你先笑，奶龙赢。**不管谁赢，奶龙最终都会大笑。**

## 游戏规则

| 结果 | 触发条件 | 画面表现 |
|---|---|---|
| **你赢** | 隐藏倒计时到点，你还没笑 | 奶龙先大笑，"奶龙先笑了！你赢了" |
| **奶龙赢** | 你先笑了 | "你笑了！奶龙赢"，奶龙跟着大笑 |
| **本局作废** | 摄像头持续看不到你的脸 | "奶龙看不见你了" |

| 难度 | 隐藏倒计时 | 笑容阈值 |
|---|---|---|
| 简单 | 8–18 秒 | 0.30 |
| 普通 | 5–12 秒 | 0.28 |
| 困难 | 3–8 秒 | 0.25 |

---

## 桌面宠物版（推荐）

透明无边框的奶龙站在桌面角落，自动开始对视挑战，输了会大笑。可打包成独立 `.exe`，无需安装任何开发环境。

### 快速开始

**前置**：Python 3.10+（安装时勾选 `Add Python to PATH`），Windows 摄像头

```cmd
cd desktop_pet

:: 方式一：一键配置（安装依赖 + 下载模型 + 生成素材）
setup_windows.bat

:: 方式二：手动
pip install -r requirements.txt
curl -L -o face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
python prepare_assets.py

:: 启动
python main.py
```

启动后奶龙出现在屏幕右下角，2 秒后自动开始对视挑战。**右键奶龙**可以切换难度、暂停、重置、退出。

### 打包为独立 .exe

```cmd
cd desktop_pet
build_exe.bat
```

产出在 `dist/驯龙高手/`，双击 `驯龙高手.exe` 即可运行。整个文件夹打 zip 发给别人，无需装 Python。

### 命令行选项

```
python main.py              # 默认：自动开始、自动循环
python main.py --no-auto    # 手动模式（右键 → 开始挑战）
python main.py --no-camera  # 纯观赏（没摄像头也能看奶龙）
```

### 右键菜单

- **难度** → 简单 / 普通（默认） / 困难
- **开始挑战** — 手动触发一局
- **暂停游戏 / 继续游戏** — 切换自动循环
- **重置** — 回到待机
- **退出**

---

## WinUI 3 原生版

基于 WinUI 3 + C++/WinRT 的完整窗口应用，需要 Visual Studio 2022 编译。

### 前置

| 软件 | 版本 | 用途 |
|---|---|---|
| **Windows 10/11** | 1809+ | WinUI 3 运行环境 |
| **Visual Studio 2022** | 17.x | 编译 C++/WinRT |
| **Python** | 3.10+ | 笑容检测 sidecar |
| **摄像头** | 任意 | 实时表情检测 |

VS 安装时需要勾选：
- **使用 C++ 的桌面开发** 工作负载
- **通用 Windows 平台开发** 工作负载
- MSVC v143、Windows 11 SDK、C++/WinRT 组件

### 构建

1. 双击 `how_to_train_your_nailong.sln`（不要用 `.slnx`，除非 VS ≥ 17.10）
2. 右键解决方案 → 还原 NuGet 程序包
3. `Package.appxmanifest` → 打包 → 创建测试证书
4. 打开 Windows 开发者模式
5. 选 `Debug | x64`，按 F5

### 启动 sidecar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r tools\smile_sidecar\requirements.txt

curl -L -o tools\smile_sidecar\face_landmarker.task ^
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task

.\.venv\Scripts\python tools\smile_sidecar\main.py ^
  --model tools\smile_sidecar\face_landmarker.task ^
  --port 38751 --camera 0
```

然后在应用中点击 **"开始挑战"**。

---

## 架构

```
桌面宠物版 (desktop_pet/)           WinUI 3 原生版
┌─────────────────────┐           ┌──────────────────────────┐
│  main.py            │           │  MainPage.xaml.cpp       │
│  ├─ GameEngine      │  ← 同一FSM →  │  ├─ GameEngine (C++)     │
│  ├─ VideoController │           │  ├─ VideoController (C++) │
│  ├─ SmileDetector   │ (内嵌)    │  └─ SmileResultPipe      │
│  └─ config.py       │           │     (WebSocket → sidecar)│
└─────────────────────┘           └──────────────────────────┘
```

两个版本共享完全相同的 9 状态 FSM 和 4 相位视频循环逻辑：

**游戏状态机**：`Idle → CameraWarmup → Calibration → Countdown → StareLoop → {UserLaughDetected / NailongLaughTriggered} → Result / Invalid`

**视频四相位**：正放(0→1s) → 停顿(800-1200ms) → 倒放(1s→0) → 停顿(400-800ms) → 循环，触发大笑时在相位边界无缝切入

**笑容检测**：`score = 0.5×(mouthSmileLeft + mouthSmileRight) + 0.2×jawOpen`，校准后基线减除，滑动窗口确认

## 可调配置

- `Assets/Config/game_difficulty.json` — 各难度参数（倒计时范围、阈值、丢脸容忍时长）
- `Assets/Config/video_segments.json` — 视频分段时间点、停顿时长范围

修改后无需重新编译。

## 致谢

- 原始项目 fork 自 [CHENGONGSHUO/Naiwa](https://github.com/CHENGONGSHUO/Naiwa)
- 笑容检测基于 [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)

## License

GPL-3.0（继承自上游仓库）
