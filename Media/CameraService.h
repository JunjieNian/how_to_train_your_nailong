#pragma once
//
// CameraService.h — owns the smile-detector sidecar lifecycle.
//
// MVP path: spawn tools/smile_sidecar/main.py as a child process bound to a
// Job Object so it dies with us. Sidecar listens on ws://127.0.0.1:38751
// and produces SmileSamples consumed by SmileResultPipe.
//
// Future native path: replace with Windows.Media.Capture + MediaFrameReader
// + ONNX Runtime inference inside the same process. Public surface stays.
//

#include <filesystem>
#include <functional>
#include <memory>
#include <string>

namespace Naiwa::Media
{
    struct CameraServiceConfig
    {
        std::filesystem::path python_exe;        // e.g. python3 from PATH or bundled
        std::filesystem::path sidecar_script;    // tools/smile_sidecar/main.py (absolute)
        std::filesystem::path model_path;        // face_landmarker.task
        int     camera_index{0};
        int     ws_port{38751};
        double  capture_fps{15.0};
    };

    class CameraService
    {
    public:
        CameraService();
        ~CameraService();

        CameraService(const CameraService&)            = delete;
        CameraService& operator=(const CameraService&) = delete;

        // Start the sidecar process. Returns false if spawn failed.
        // OnReady fires after the WebSocket is reachable; OnLost fires if
        // the child exits unexpectedly.
        bool Start(const CameraServiceConfig& cfg);
        void Stop();

        bool IsRunning() const noexcept;
        int  WebSocketPort() const noexcept;

        std::function<void()>            OnReady;
        std::function<void(int /*exit*/)> OnLost;

    private:
        struct Impl;
        std::unique_ptr<Impl> m_impl;
    };
}
