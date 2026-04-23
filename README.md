# 驯龙高手 How to Train Your Nailong

一个基于 WinUI 3 + C++/WinRT 的**憋笑挑战**桌面小游戏。

你盯着奶龙，摄像头实时检测你的表情——谁先笑，谁就输。奶龙有一个隐藏的"绷不住"倒计时：如果你在倒计时结束前忍住不笑，奶龙会先笑，你赢了；如果你先笑，奶龙赢，然后奶龙也跟着大笑收场。**不管谁赢，奶龙最终都会大笑。**

## 游戏规则

| 结果 | 触发条件 | 画面表现 |
|---|---|---|
| **你赢** | 隐藏倒计时到点，你还没笑 | 奶龙先大笑，弹出"奶龙先笑了！你赢了" |
| **奶龙赢** | 你先笑了 | 弹出"你笑了！奶龙赢"，1.5 秒后奶龙也跟着大笑 |
| **本局作废** | 摄像头持续丢失你的脸超过数秒 | 弹出"奶龙看不见你了" |

隐藏倒计时根据难度随机生成（每局不同）：

| 难度 | 倒计时范围 | 笑容阈值 |
|---|---|---|
| 简单 | 8–18 秒 | 0.30 |
| 普通 | 5–12 秒 | 0.28 |
| 困难 | 3–8 秒 | 0.25 |

完整流程：选难度 → 开始挑战 → 校准中性脸（~2.5 秒） → 3-2-1 倒计时 → 对视循环 → 谁先笑谁输 → 奶龙大笑 → 可重新开始。

## 前置准备

### 必需软件

| 软件 | 版本 | 用途 |
|---|---|---|
| **Windows 10/11** | 1809 (17763) 以上 | 运行 WinUI 3 应用 |
| **Visual Studio 2022** | 17.x（任意版本均可） | 编译 C++/WinRT 项目 |
| **Python** | 3.10+ | 运行笑容检测 sidecar |
| **摄像头** | 任意 USB / 内置 | 实时表情检测 |

### Visual Studio 组件（重要）

仅安装 VS 2022 本体是不够的。你需要在 **Visual Studio Installer → 修改** 里额外勾选以下内容，否则打开项目后会报 `v143 生成工具找不到` / `无法找到平台 x64` 等错误。

**工作负载（Workloads）**——至少勾选这两个：

- [x] **使用 C++ 的桌面开发**（Desktop development with C++）
- [x] **通用 Windows 平台开发**（Universal Windows Platform development）

**单个组件（Individual components）**——确认勾选：

- [x] MSVC v143 - VS 2022 C++ x64/x86 生成工具（最新）
- [x] Windows 11 SDK（10.0.26100.0 或更新）
- [x] C++/WinRT
- [x] C++ (v143) 通用 Windows 平台工具

勾完后点"修改"，等安装完成再打开项目。

验证是否装好：打开"x64 Native Tools Command Prompt for VS 2022"，输入：

```cmd
where cl
where msbuild
```

都能找到就说明 v143 工具链就位。

## 构建与启动（分步教程）

### 第一步：打开解决方案

**用 `.sln` 而不是 `.slnx`。** 仓库里有两个解决方案文件：

| 文件 | 说明 |
|---|---|
| `how_to_train_your_nailong.sln` | 传统格式，VS 2022 所有版本都能打开 |
| `how_to_train_your_nailong.slnx` | 新 XML 格式，需要 VS 2022 **17.10+**。旧版本打开会报 `HRESULT E_FAIL` |

**推荐双击 `.sln`。** 如果你的 VS 够新且 `.slnx` 能打开，用它也行。

### 第二步：还原 NuGet 包

首次打开项目后，VS 通常会自动还原。如果没有：

1. 解决方案资源管理器 → 右键解决方案 → **还原 NuGet 程序包**
2. 或者菜单 工具 → NuGet 包管理器 → 程序包管理器控制台 → `Update-Package -reinstall`

这会拉取 Windows App SDK 1.8、CppWinRT、WebView2 等依赖到 `packages/` 目录，首次约 **1–2 GB**。

### 第三步：生成签名证书

项目使用 MSIX 打包，需要一个临时签名证书。如果 build 报 `Naiwa_TemporaryKey.pfx` 或 `how_to_train_your_nailong_TemporaryKey.pfx` 找不到：

1. 在解决方案资源管理器中双击 `Package.appxmanifest`
2. 切到"打包"标签页
3. 点击"选择证书…" → "创建测试证书"
4. 直接确定（不需要密码）

VS 会在项目根目录生成 `.pfx` 文件。

### 第四步：启用开发者模式

MSIX 应用部署需要 Windows 开发者模式：

- Windows 11：设置 → 系统 → 开发者选项 → **开发人员模式** 打开
- Windows 10：设置 → 更新与安全 → 开发者选项 → **开发人员模式** 打开

### 第五步：构建并运行

1. 顶部工具栏选择 `Debug` | `x64`
2. 按 **F5** 或点击绿色箭头
3. 首次 build 可能需要几分钟（生成 C++/WinRT projection headers）

如果 build 成功，应用窗口会弹出，黑底上显示奶龙静帧和底部控制栏。

**此时先不要点"开始挑战"——你还需要启动 sidecar。**

### 第六步：准备 Python 笑容检测 sidecar

在仓库根目录打开 PowerShell 或 CMD：

```powershell
# 创建虚拟环境
python -m venv .venv

# 安装依赖
.\.venv\Scripts\pip install -r tools\smile_sidecar\requirements.txt
```

下载 MediaPipe 人脸模型（约 3.6 MB，只需下载一次）：

```powershell
Invoke-WebRequest `
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task `
  -OutFile tools\smile_sidecar\face_landmarker.task
```

或者用 curl：

```cmd
curl -L -o tools\smile_sidecar\face_landmarker.task ^
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
```

### 第七步：启动 sidecar 并开始游戏

```powershell
.\.venv\Scripts\python tools\smile_sidecar\main.py `
  --model tools\smile_sidecar\face_landmarker.task `
  --port 38751 `
  --camera 0
```

看到以下输出说明 sidecar 就绪：

```
HH:MM:SS INFO  smile_sidecar | source = camera 0
HH:MM:SS INFO  smile_sidecar | listening on ws://127.0.0.1:38751
```

然后回到应用窗口，选择难度，点击 **"开始挑战"**。

## 常见问题排查

### 打开 .slnx 报 `HRESULT E_FAIL`

你的 VS 2022 版本低于 17.10。`.slnx` 是新格式。解决方案：**双击 `.sln` 文件打开**。

### `无法找到 v143 生成工具` / `无法找到平台 x64`

VS 没装 C++ 桌面开发工作负载。打开 Visual Studio Installer → 修改 → 勾选"使用 C++ 的桌面开发"和"通用 Windows 平台开发" → 修改。参见上方"Visual Studio 组件"一节。

### `winrt/xxx.h not found` 或 NuGet 相关报错

NuGet 包没有正确还原。右键解决方案 → 还原 NuGet 程序包。如果还不行，删除 `packages/` 目录后重新还原。

### 部署失败 `requires developer mode`

去 Windows 设置里打开开发者模式。参见上方"第四步"。

### `signtool.exe not found` 或证书报错

参见上方"第三步"创建测试证书。如果 `.pfx` 文件名和 `.vcxproj` 里 `PackageCertificateKeyFile` 不一致，手动在项目属性 → 打包 → 证书里重新选择。

### 首轮视频闪到大笑片段 / 黑屏

确保 `Assets/Config/video_segments.json` 中 `source` 指向 H.264 版本：

```json
"source": "ms-appx:///Assets/Video/how_to_train_your_nailong_h264.mp4"
```

reverse 资产必须是**仅 stare 段倒放**（约 1 秒 / 84 KB），不是全片倒放。重新生成：

```bash
./tools/make_reverse_video.sh
```

### sidecar 报 `libGLESv2.so.2: cannot open shared object file`

这是在 **Linux** 无头服务器上跑 sidecar 的问题。Windows 上不会遇到。如果你在 Linux 上做开发测试，可以用 mock 模式绕过：

```bash
python3 tools/smile_sidecar/main.py --mock-detector --port 38751
```

### 点了"开始挑战"但一直显示"准备摄像头…"

sidecar 没有启动，或者 WebSocket 连接失败。检查：

1. sidecar 是否在 38751 端口运行（看终端输出）
2. 防火墙是否放行了 `127.0.0.1:38751`
3. sidecar 是否报了摄像头打开失败（`cannot open camera 0`）

## 架构概览

```
┌────────────────────────────────────────────────┐
│                   MainPage                     │
│  ┌──────────┐  ┌─────────┐  ┌───────────────┐ │
│  │ 难度选择  │  │ 开始挑战 │  │     重置      │ │
│  └──────────┘  └─────────┘  └───────────────┘ │
│  ┌──────────────────────────────────────────┐  │
│  │         MediaPlayerElement x2            │  │
│  │   (forward + reverse, opacity swap)      │  │
│  └──────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────┐  │
│  │         Overlay (倒计时 / 结果字幕)        │  │
│  └──────────────────────────────────────────┘  │
└──────────┬───────────┬───────────┬─────────────┘
           │           │           │
    ┌──────▼──────┐ ┌──▼─────┐ ┌──▼──────────┐
    │ GameEngine  │ │ Video  │ │ SmileResult  │
    │  (FSM)      │ │Controll│ │    Pipe      │
    │             │ │  er    │ │ (WebSocket)  │
    └──────┬──────┘ └────────┘ └──────┬───────┘
           │                          │
           │    ┌─────────────────┐   │ ws://127.0.0.1:38751
           │    │  CameraService  │   │
           │    │ (进程托管, 预留) │   │
           │    └─────────────────┘   │
           │                    ┌─────▼──────────────┐
           └────────────────────│  Python sidecar     │
                                │  (MediaPipe +       │
                                │   OpenCV + WS)      │
                                └─────────────────────┘
```

### 核心模块

| 模块 | 路径 | 职责 |
|---|---|---|
| **GameEngine** | `Core/GameEngine.{h,cpp}` | 9 状态 FSM：Idle → CameraWarmup → Calibration → Countdown → StareLoop → {UserLaughDetected / NailongLaughTriggered} → Result / Invalid |
| **VideoController** | `Media/VideoController.{h,cpp}` | 双轨 MediaPlayerElement（forward + reverse），通过 Opacity 切换实现无闪四相位循环：正放 → 停顿 → 倒放 → 停顿 |
| **SmileResultPipe** | `IPC/SmileResultPipe.{h,cpp}` | MessageWebSocket 客户端，解析 sidecar JSON，通过 DispatcherQueue 切回 UI 线程 |
| **CameraService** | `Media/CameraService.{h,cpp}` | 通过 Job Object 托管 sidecar 子进程（已实现，MainPage 尚未自动调用） |
| **sidecar** | `tools/smile_sidecar/main.py` | MediaPipe FaceLandmarker (LIVE_STREAM)，12–15 FPS 检测，输出 smile_score + is_smiling，支持校准 / 阈值 / mock 模式 |

### 视频四相位循环

```
Phase 1: 正放 0→1s (forward_player, 有声)
Phase 2: 停顿 (随机 800–1200ms, 画面定格在"看着你")
Phase 3: 倒放 1s→0 (reverse_player, 无声, 1秒 stare-only 资产)
Phase 4: 停顿 (随机 400–800ms, 画面定格在"看别处")
→ 回到 Phase 1, 每个循环末尾检查隐藏倒计时
→ 触发大笑时在 Phase 1→2 边界无缝切入 laugh 片段
```

## 可调配置

### `Assets/Config/game_difficulty.json`

控制每个难度下的：隐藏倒计时范围、校准时长、笑容阈值、连续帧确认数、丢脸容忍时长。修改后无需重新编译，重启应用即可生效。

### `Assets/Config/video_segments.json`

控制：视频源 URI、stare 段起止时间、笑场切入点、停顿时长范围。修改后需重新部署。

如果更改了 `stare_end_ms`，需要用 ffmpeg 重新生成倒放资产：

```bash
./tools/make_reverse_video.sh --stare-end-ms 1200
```

## 开发工具

### sidecar 调试

```powershell
# 用视频文件代替摄像头（循环播放）
.\.venv\Scripts\python tools\smile_sidecar\main.py `
  --model tools\smile_sidecar\face_landmarker.task `
  --source path\to\face_clip.mp4

# 纯 mock 模式（无摄像头、无模型，正弦波模拟 smile_score）
python tools\smile_sidecar\main.py --mock-detector --port 38751

# 测试客户端（检查 WebSocket 协议、校准回路、帧率）
python tools\smile_sidecar\test_client.py --port 38751 --duration 11
```

### 视频工具

```bash
# 探测视频信息（fps / 时长 / 帧数）
python3 tools/probe_segments.py --probe

# 重新生成倒放视频（默认 stare 0–1000ms）
./tools/make_reverse_video.sh

# 自定义 stare 范围
./tools/make_reverse_video.sh --stare-start-ms 0 --stare-end-ms 1200 --fps 30
```

### 命令行 build（不启动 VS IDE）

在"x64 Native Tools Command Prompt for VS 2022"中：

```cmd
msbuild how_to_train_your_nailong.vcxproj /t:Restore
msbuild how_to_train_your_nailong.vcxproj /p:Configuration=Debug /p:Platform=x64 /m
msbuild how_to_train_your_nailong.vcxproj /p:Configuration=Debug /p:Platform=x64 /t:Deploy
```

## 已知限制

- sidecar 需要手动启动（`CameraService` 骨架已写好，尚未接入 MainPage 的自动拉起逻辑）。
- 无自动化测试。完整联调需要 Windows + 摄像头环境。
- 打包签名配置带有模板痕迹；对外发布需替换为你自己的证书。
- 奶龙角色素材来自上游仓库 (GPL-3.0)，角色 IP 是否可商用需单独确认。

## 致谢

- 原始 WinUI 3 项目 fork 自 [CHENGONGSHUO/Naiwa](https://github.com/CHENGONGSHUO/Naiwa)
- 笑容检测基于 [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)

## License

见 `LICENSE.txt`（GPL-3.0，继承自上游仓库）。
