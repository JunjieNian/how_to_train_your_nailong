#include "pch.h"
#include "CameraService.h"

#include <atomic>
#include <chrono>
#include <sstream>
#include <string>
#include <thread>

#include <winrt/Microsoft.UI.Dispatching.h>

#include <Windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")

namespace Naiwa::Media
{
    namespace
    {
        std::wstring BuildCommandLine(const CameraServiceConfig& cfg)
        {
            std::wostringstream o;
            // Quote python exe in case it has spaces.
            o << L"\"" << cfg.python_exe.wstring() << L"\""
              << L" \"" << cfg.sidecar_script.wstring() << L"\""
              << L" --model \"" << cfg.model_path.wstring() << L"\""
              << L" --camera " << cfg.camera_index
              << L" --port "   << cfg.ws_port
              << L" --fps "    << cfg.capture_fps;
            return o.str();
        }

        bool ProbePort(int port, std::chrono::milliseconds timeout)
        {
            // Block-poll TCP connect to 127.0.0.1:port with the given total
            // timeout. Returns true as soon as one connect succeeds.
            WSADATA wsa;
            if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
            const auto deadline = std::chrono::steady_clock::now() + timeout;

            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port   = htons(static_cast<u_short>(port));
            inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

            bool ok = false;
            while (std::chrono::steady_clock::now() < deadline)
            {
                SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
                if (s == INVALID_SOCKET) break;
                if (connect(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0)
                {
                    ok = true;
                    closesocket(s);
                    break;
                }
                closesocket(s);
                std::this_thread::sleep_for(std::chrono::milliseconds{150});
            }
            WSACleanup();
            return ok;
        }
    }

    struct CameraService::Impl
    {
        winrt::Microsoft::UI::Dispatching::DispatcherQueue ui_queue{nullptr};
        HANDLE            hJob{nullptr};
        PROCESS_INFORMATION pi{};
        std::atomic<bool> running{false};
        std::thread       watcher;
        int               ws_port{0};

        // Callbacks (copies of public slots, read on background threads).
        std::function<void()>             on_ready;
        std::function<void(int)>          on_lost;

        Impl()
        {
            ui_queue = winrt::Microsoft::UI::Dispatching::DispatcherQueue::GetForCurrentThread();
        }

        ~Impl() { Stop(); }

        bool Start(const CameraServiceConfig& cfg)
        {
            if (running.exchange(true)) return false;  // already running
            ws_port = cfg.ws_port;

            // Build the job first so we can assign the child to it before it
            // does anything. JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE guarantees the
            // child is killed when our handle to the job is released — i.e.,
            // when we exit for any reason, normal or not.
            hJob = CreateJobObjectW(nullptr, nullptr);
            if (!hJob) { running = false; return false; }

            JOBOBJECT_EXTENDED_LIMIT_INFORMATION info{};
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(hJob, JobObjectExtendedLimitInformation, &info, sizeof(info));

            std::wstring cmdline = BuildCommandLine(cfg);
            // CreateProcessW's lpCommandLine must be writable.
            std::vector<wchar_t> cmdbuf(cmdline.begin(), cmdline.end());
            cmdbuf.push_back(L'\0');

            STARTUPINFOW si{};
            si.cb = sizeof(si);

            BOOL ok = CreateProcessW(
                nullptr,
                cmdbuf.data(),
                nullptr, nullptr,
                FALSE,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB,
                nullptr, nullptr,
                &si, &pi);
            if (!ok)
            {
                CloseHandle(hJob);
                hJob = nullptr;
                running = false;
                return false;
            }

            AssignProcessToJobObject(hJob, pi.hProcess);
            ResumeThread(pi.hThread);

            // Probe + watcher threads. Probe fires OnReady; watcher fires OnLost.
            std::thread([this] {
                bool ready = ProbePort(ws_port, std::chrono::milliseconds{8000});
                if (ready && ui_queue && on_ready)
                {
                    auto cb = on_ready;
                    ui_queue.TryEnqueue([cb] { cb(); });
                }
                else if (!ready && ui_queue && on_lost)
                {
                    auto cb = on_lost;
                    ui_queue.TryEnqueue([cb] { cb(-1); });
                }
            }).detach();

            watcher = std::thread([this] {
                WaitForSingleObject(pi.hProcess, INFINITE);
                DWORD code = 0;
                GetExitCodeProcess(pi.hProcess, &code);
                running = false;
                if (ui_queue && on_lost)
                {
                    auto cb = on_lost;
                    ui_queue.TryEnqueue([cb, code] { cb(static_cast<int>(code)); });
                }
            });
            return true;
        }

        void Stop()
        {
            if (!running.exchange(false) && !hJob) return;
            if (hJob)
            {
                // Closing the job kills the child per JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
                CloseHandle(hJob);
                hJob = nullptr;
            }
            if (pi.hThread)  { CloseHandle(pi.hThread);  pi.hThread = nullptr; }
            if (pi.hProcess) { CloseHandle(pi.hProcess); pi.hProcess = nullptr; }
            if (watcher.joinable())
            {
                // The watcher is blocked on WaitForSingleObject which we've
                // already closed. Detach rather than join to avoid a deadlock
                // if the handle was invalidated in the wrong order.
                watcher.detach();
            }
        }
    };

    // ---- public surface ----------------------------------------------------

    CameraService::CameraService()  : m_impl(std::make_unique<Impl>()) {}
    CameraService::~CameraService() = default;

    bool CameraService::Start(const CameraServiceConfig& cfg)
    {
        m_impl->on_ready = OnReady;
        m_impl->on_lost  = OnLost;
        return m_impl->Start(cfg);
    }

    void CameraService::Stop()                       { m_impl->Stop(); }
    bool CameraService::IsRunning() const noexcept   { return m_impl->running.load(); }
    int  CameraService::WebSocketPort() const noexcept { return m_impl->ws_port; }
}
