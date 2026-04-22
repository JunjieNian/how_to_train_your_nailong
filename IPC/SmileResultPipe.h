#pragma once
//
// SmileResultPipe.h — WebSocket client to the Python smile-detection sidecar.
//
// Receives JSON sample messages on a worker thread, deserialises into
// Game::SmileSample, and posts them to the UI dispatcher queue for
// consumption by GameEngine::OnSmileSample.
//
// Also forwards a handful of control commands back to the sidecar:
// start_calibration / end_calibration / reset / set_threshold /
// set_consecutive.
//

#include "../Core/GameEngine.h"

#include <functional>
#include <memory>
#include <string>

#include <winrt/Microsoft.UI.Dispatching.h>

namespace how_to_train_your_nailong::IPC
{
    class SmileResultPipe
    {
    public:
        explicit SmileResultPipe(winrt::Microsoft::UI::Dispatching::DispatcherQueue ui_queue);
        ~SmileResultPipe();

        SmileResultPipe(const SmileResultPipe&)            = delete;
        SmileResultPipe& operator=(const SmileResultPipe&) = delete;

        // Connect to ws://host:port. Returns immediately; events fire async.
        void Connect(std::string host, int port);
        void Disconnect();

        // Called on UI thread for every incoming sample.
        std::function<void(Game::SmileSample)> OnSample;

        // Connection lifecycle (UI thread).
        std::function<void()>             OnConnected;
        std::function<void(std::string)>  OnDisconnected;   // reason

        // Outbound commands (any thread).
        void StartCalibration();
        void EndCalibration();
        void Reset();
        void SetThreshold(float v);
        void SetConsecutiveFrames(int n);

        bool IsConnected() const noexcept;

    private:
        struct Impl;
        std::unique_ptr<Impl> m_impl;
    };
}
