#include "pch.h"
#include "SmileResultPipe.h"

#include <atomic>
#include <mutex>
#include <sstream>
#include <string>

#include <winrt/Windows.Data.Json.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Networking.h>
#include <winrt/Windows.Networking.Sockets.h>
#include <winrt/Windows.Storage.Streams.h>

namespace Naiwa::IPC
{
    using winrt::Windows::Data::Json::JsonObject;
    using winrt::Windows::Data::Json::JsonValue;
    using winrt::Windows::Foundation::Uri;
    using winrt::Windows::Networking::Sockets::MessageWebSocket;
    using winrt::Windows::Networking::Sockets::MessageWebSocketMessageReceivedEventArgs;
    using winrt::Windows::Networking::Sockets::SocketMessageType;
    using winrt::Windows::Networking::Sockets::WebSocketClosedEventArgs;
    using winrt::Windows::Storage::Streams::DataReader;
    using winrt::Windows::Storage::Streams::DataWriter;
    using winrt::Windows::Storage::Streams::UnicodeEncoding;

    namespace
    {
        std::wstring NarrowToWide(std::string_view s)
        {
            return std::wstring{s.begin(), s.end()};
        }
    }

    struct SmileResultPipe::Impl
    {
        winrt::Microsoft::UI::Dispatching::DispatcherQueue ui_queue{nullptr};
        MessageWebSocket    ws{nullptr};
        DataWriter          writer{nullptr};
        std::mutex          send_mutex;
        std::atomic<bool>   connected{false};

        // Public callback slots referenced by the outer class.
        std::function<void(Game::SmileSample)> on_sample;
        std::function<void()>                  on_connected;
        std::function<void(std::string)>       on_disconnected;

        explicit Impl(winrt::Microsoft::UI::Dispatching::DispatcherQueue q) : ui_queue(q) {}

        ~Impl() { Disconnect(); }

        void Connect(const std::string& host, int port)
        {
            ws = MessageWebSocket();
            ws.Control().MessageType(SocketMessageType::Utf8);

            ws.MessageReceived([this](auto&&, MessageWebSocketMessageReceivedEventArgs const& args) {
                try
                {
                    auto reader = args.GetDataReader();
                    reader.UnicodeEncoding(UnicodeEncoding::Utf8);
                    auto text = reader.ReadString(reader.UnconsumedBufferLength());
                    HandleIncoming(std::wstring{text.c_str()});
                }
                catch (...) {}
            });

            ws.Closed([this](auto&&, WebSocketClosedEventArgs const& args) {
                connected = false;
                std::wstring reason{args.Reason().c_str()};
                std::string  reason_a{reason.begin(), reason.end()};
                if (ui_queue && on_disconnected)
                {
                    auto cb = on_disconnected;
                    ui_queue.TryEnqueue([cb, reason_a] { cb(reason_a); });
                }
            });

            std::wostringstream url;
            url << L"ws://" << NarrowToWide(host) << L":" << port;
            Uri uri{winrt::hstring{url.str()}};

            // Fire-and-forget: launch ConnectAsync. Capture *this is unsafe
            // long-term; in practice GameEngine owns SmileResultPipe and lives
            // longer than the connect operation.
            auto self = this;
            ws.ConnectAsync(uri).Completed([self](auto&& op, winrt::Windows::Foundation::AsyncStatus status) {
                if (status == winrt::Windows::Foundation::AsyncStatus::Completed)
                {
                    self->writer = DataWriter(self->ws.OutputStream());
                    self->writer.UnicodeEncoding(UnicodeEncoding::Utf8);
                    self->connected = true;
                    if (self->ui_queue && self->on_connected)
                    {
                        auto cb = self->on_connected;
                        self->ui_queue.TryEnqueue([cb] { cb(); });
                    }
                }
                else
                {
                    if (self->ui_queue && self->on_disconnected)
                    {
                        auto cb = self->on_disconnected;
                        self->ui_queue.TryEnqueue([cb] { cb("connect_failed"); });
                    }
                }
            });
        }

        void Disconnect()
        {
            connected = false;
            if (ws)
            {
                try { ws.Close(1000, L"client_disconnect"); } catch (...) {}
                ws = nullptr;
            }
            writer = nullptr;
        }

        void Send(std::wstring_view payload)
        {
            if (!connected || !writer) return;
            std::lock_guard lk(send_mutex);
            try
            {
                writer.WriteString(winrt::hstring{payload});
                // StoreAsync returns IAsyncOperation; fire-and-forget is fine
                // for short JSON commands.
                writer.StoreAsync();
            }
            catch (...) {}
        }

        void HandleIncoming(const std::wstring& text)
        {
            JsonObject obj;
            if (!JsonObject::TryParse(winrt::hstring{text}, obj)) return;
            const auto type = obj.HasKey(L"type") ? obj.GetNamedString(L"type") : L"";
            if (type != L"sample") return;  // status messages dropped silently for now

            Game::SmileSample s{};
            s.t           = Game::Clock::now();   // engine uses its own clock
            s.face_found  = obj.HasKey(L"face_found")  && obj.GetNamedBoolean(L"face_found");
            s.is_smiling  = obj.HasKey(L"is_smiling")  && obj.GetNamedBoolean(L"is_smiling");
            s.calibrated  = obj.HasKey(L"calibrated")  && obj.GetNamedBoolean(L"calibrated");
            s.smile_score = obj.HasKey(L"smile_score") ? static_cast<float>(obj.GetNamedNumber(L"smile_score")) : 0.0f;

            if (ui_queue && on_sample)
            {
                auto cb = on_sample;
                ui_queue.TryEnqueue([cb, s] { cb(s); });
            }
        }
    };

    // ---- public surface ----------------------------------------------------

    SmileResultPipe::SmileResultPipe(winrt::Microsoft::UI::Dispatching::DispatcherQueue ui_queue)
        : m_impl(std::make_unique<Impl>(ui_queue)) {}

    SmileResultPipe::~SmileResultPipe() = default;

    void SmileResultPipe::Connect(std::string host, int port)
    {
        m_impl->on_sample       = OnSample;
        m_impl->on_connected    = OnConnected;
        m_impl->on_disconnected = OnDisconnected;
        m_impl->Connect(host, port);
    }

    void SmileResultPipe::Disconnect()                    { m_impl->Disconnect(); }
    bool SmileResultPipe::IsConnected() const noexcept    { return m_impl->connected.load(); }

    void SmileResultPipe::StartCalibration() { m_impl->Send(LR"({"cmd":"start_calibration"})"); }
    void SmileResultPipe::EndCalibration()   { m_impl->Send(LR"({"cmd":"end_calibration"})");   }
    void SmileResultPipe::Reset()            { m_impl->Send(LR"({"cmd":"reset"})");             }

    void SmileResultPipe::SetThreshold(float v)
    {
        std::wostringstream o;
        o << LR"({"cmd":"set_threshold","value":)" << v << L"}";
        m_impl->Send(o.str());
    }

    void SmileResultPipe::SetConsecutiveFrames(int n)
    {
        std::wostringstream o;
        o << LR"({"cmd":"set_consecutive","value":)" << n << L"}";
        m_impl->Send(o.str());
    }
}
