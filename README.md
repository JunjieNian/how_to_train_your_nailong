# how_to_train_your_nailong

一个基于 WinUI 3 + C++/WinRT 的“别把自己逗笑”小游戏原型：你盯着奶龙，摄像头实时检测你的表情；如果你先笑，奶龙获胜；如果你撑到隐藏时机点，奶龙会先笑，你获胜。

## 当前状态

- 可玩的 MVP 原型，主流程已经打通。
- 前端是 WinUI 3 桌面应用，后端表情检测暂时由 Python sidecar 提供。
- 当前版本需要**手动启动**表情检测 sidecar；`CameraService` 已实现进程托管骨架，但 `MainPage` 里还没有正式接上自动拉起逻辑。
- 项目以 **Windows** 为目标平台；仓库里虽然有 Python 工具脚本，但主程序本身不是跨平台应用。

## 游戏流程

1. 点击“开始挑战”。
2. 进行一小段“中性表情”校准。
3. 屏幕中央显示 `3 → 2 → 1` 倒计时。
4. 奶龙进入循环盯人状态。
5. 如果检测到你先笑了，判定“奶龙赢”。
6. 如果你撑到了本轮隐藏时机点，奶龙先笑，判定“你赢了”。
7. 如果摄像头长时间看不到脸，本局作废。

## 架构概览

- `Core/GameEngine.*`：游戏状态机，管理校准、倒计时、输赢和作废逻辑。
- `Media/VideoController.*`：控制奶龙视频的正放、停顿、倒放和切入笑场片段。
- `IPC/SmileResultPipe.*`：通过 WebSocket 接收 Python sidecar 送来的笑容检测结果。
- `Media/CameraService.*`：用于托管 sidecar 生命周期的 Windows 进程封装，当前尚未在 UI 中自动启用。
- `tools/smile_sidecar/main.py`：基于 MediaPipe 的笑容检测 sidecar。
- `Assets/Config/*.json`：难度参数与视频切片配置。

## 目录结构

```text
.
├─ Assets/
│  ├─ Config/                 # 难度和视频分段配置
│  └─ Video/                  # 奶龙正放/倒放素材
├─ Core/                      # 游戏状态机
├─ IPC/                       # WebSocket 收发
├─ Media/                     # 视频播放与 sidecar 托管
└─ tools/
   ├─ probe_segments.py       # 探测视频 fps/时长并写回配置
   ├─ make_reverse_video.sh   # 生成倒放视频
   └─ smile_sidecar/          # MediaPipe 笑容检测服务
```

## 开发环境

### Windows 应用

- Windows 10 1809+ 或 Windows 11
- Visual Studio 2022
- C++ 桌面开发相关组件
- 能够还原 `packages.config` 中声明的 NuGet 依赖
- 摄像头权限

### Python sidecar

- Python 3.10+
- 一个可用摄像头
- `tools/smile_sidecar/requirements.txt` 中的依赖
- MediaPipe 的 `face_landmarker.task` 模型文件

## 快速开始

### 1. 构建 Windows 应用

1. 在 Visual Studio 2022 中打开 `how_to_train_your_nailong.slnx`。
2. 执行 NuGet 还原。
3. 选择 `x64` + `Debug` 或 `Release`。
4. 构建并启动应用。

### 2. 准备 Python 检测服务

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r tools\smile_sidecar\requirements.txt
```

下载模型到 `tools/smile_sidecar/face_landmarker.task`：

```powershell
Invoke-WebRequest `
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task `
  -OutFile tools/smile_sidecar/face_landmarker.task
```

启动 sidecar：

```powershell
.\.venv\Scripts\python tools\smile_sidecar\main.py `
  --model tools\smile_sidecar\face_landmarker.task `
  --port 38751 `
  --camera 0
```

然后回到应用里点击“开始挑战”。

## 调试与工具

### Sidecar 调试模式

- 使用视频或图片代替摄像头：

```powershell
.\.venv\Scripts\python tools\smile_sidecar\main.py `
  --model tools\smile_sidecar\face_landmarker.task `
  --source path\to\clip.mp4
```

- 使用 mock detector，不依赖摄像头和 MediaPipe 模型：

```powershell
python tools\smile_sidecar\main.py --mock-detector --port 38751
```

- 用测试客户端查看 sidecar 输出：

```powershell
python tools\smile_sidecar\test_client.py --port 38751
```

### 视频配置工具

- 探测视频信息：

```bash
python3 tools/probe_segments.py --probe
```

- 重新生成倒放视频（依赖 `ffmpeg`）：

```bash
./tools/make_reverse_video.sh
```

## 可调配置

- `Assets/Config/game_difficulty.json`
  - 控制笑场触发区间、校准时长、笑容阈值、连续帧数、丢脸容忍时长等。
- `Assets/Config/video_segments.json`
  - 控制盯人片段起止时间、笑场切入点、前后停顿区间等。

### HEVC 兼容性说明

仓库同时提供：

- `Assets/Video/how_to_train_your_nailong.mp4`：原始素材
- `Assets/Video/how_to_train_your_nailong_h264.mp4`：H.264 兼容版本
- `Assets/Video/how_to_train_your_nailong_reverse.mp4`：倒放版本

当前代码默认读取 `video_segments.json` 里的 `source` 字段；如果目标机器缺少 HEVC 解码支持，可以把 `source` 手动改成：

```json
"source": "ms-appx:///Assets/Video/how_to_train_your_nailong_h264.mp4"
```

## 已知限制

- sidecar 目前需要手动启动。
- 主程序未在当前仓库内提供自动化测试。
- 仓库中的 Python 工具经过语法级检查，但完整联调仍需要 Windows + 摄像头环境。
- 打包和签名相关配置仍带有模板/本地环境痕迹，若要发布安装包，需要替换为你自己的证书与发布设置。

## License

见 `LICENSE.txt`。
