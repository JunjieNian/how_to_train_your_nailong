#include "pch.h"
#include "MainPage.xaml.h"
#if __has_include("MainPage.g.cpp")
#include "MainPage.g.cpp"
#endif

#include <winrt/Microsoft.UI.Dispatching.h>
#include <winrt/Microsoft.UI.Xaml.Controls.h>

using namespace winrt;
using namespace Microsoft::UI::Xaml;

// ---------------------------------------------------------------------------
//
// MainPage glues four subsystems together:
//
//   VideoController  → owns the奶龙 MediaPlayer + cycle / laugh logic
//   SmileResultPipe  → WebSocket client for the Python smile sidecar
//   CameraService    → spawns / tears down the sidecar (no-op stub for MVP)
//   GameEngine       → state machine driving everything else
//
// MainPage itself implements the IGameView callback surface via a small
// internal bridge object (ViewBridge) that just calls back into MainPage.
//
// MVP behaviour (until CameraService.Start is wired):
//   - The sidecar must be launched manually before pressing Start, e.g.:
//       python tools/smile_sidecar/main.py --model ... --port 38751
//   - StartButton_Click connects the WS pipe; once OnConnected fires,
//     GameEngine::OnSidecarReady() is called and the round begins.
//
// ---------------------------------------------------------------------------

namespace winrt::how_to_train_your_nailong::implementation
{
    // -------- ViewBridge implementation of IGameView -----------------------
    struct MainPage::ViewBridge : how_to_train_your_nailong::Game::IGameView
    {
        MainPage* owner;
        explicit ViewBridge(MainPage* o) : owner(o) {}

        void ShowOverlay(std::wstring_view text) override
        {
            owner->SetOverlay(text);
        }
        void ClearOverlay() override
        {
            owner->ClearOverlay();
        }
        void StartCountdown(int /*seconds*/) override
        {
            // The numeric label is pushed via ShowOverlay by GameEngine; this
            // hook is a place to attach a beep / animation later.
        }
        void BeginStareCycle() override
        {
            if (owner->m_video) owner->m_video->BeginStareCycle();
        }
        void TriggerNailongLaugh() override
        {
            if (owner->m_video) owner->m_video->TriggerLaugh();
        }
        void ShowResult(how_to_train_your_nailong::Game::Winner winner) override
        {
            std::wstring_view text =
                winner == how_to_train_your_nailong::Game::Winner::User
                    ? L"奶龙先笑了！你赢了"
                : winner == how_to_train_your_nailong::Game::Winner::Nailong
                    ? L"你笑了！奶龙赢"
                    : L"本局无效";
            owner->SetOverlay(text);
            owner->DisableControls(false);
        }
        void RequestSidecarCalibration(bool start) override
        {
            if (!owner->m_pipe) return;
            if (start) owner->m_pipe->StartCalibration();
            else       owner->m_pipe->EndCalibration();
        }
    };

    // -------- MainPage -----------------------------------------------------

    MainPage::MainPage()
    {
        InitializeComponent();
        Loaded({this, &MainPage::OnLoaded});
    }

    MainPage::~MainPage()
    {
        // Members destroyed in reverse declaration order (camera last → its
        // dtor closes the Job Object handle which kills the sidecar).
    }

    int32_t MainPage::MyProperty()              { throw hresult_not_implemented(); }
    void    MainPage::MyProperty(int32_t)       { throw hresult_not_implemented(); }

    void MainPage::OnLoaded(
        winrt::Windows::Foundation::IInspectable const&,
        winrt::Microsoft::UI::Xaml::RoutedEventArgs const&)
    {
        InitializeGame();
    }

    void MainPage::InitializeGame()
    {
        m_view_bridge = std::make_unique<ViewBridge>(this);
        m_engine = std::make_unique<how_to_train_your_nailong::Game::GameEngine>(*m_view_bridge);
        m_engine->SetDifficulty(m_difficulty);

        m_video = std::make_unique<how_to_train_your_nailong::Media::VideoController>(VideoPlayer());
        // Load segment timings from the packaged config; fall back to the
        // URI defaults baked into VideoSegments if loading fails.
        auto segments = how_to_train_your_nailong::Media::VideoSegments::LoadFromPackage(
            L"ms-appx:///Assets/Config/video_segments.json");
        if (segments.source_uri.empty())
        {
            segments.source_uri =
                L"ms-appx:///Assets/Video/how_to_train_your_nailong.mp4";
            segments.reverse_source_uri =
                L"ms-appx:///Assets/Video/how_to_train_your_nailong_reverse.mp4";
        }
        m_video->Configure(segments);
        m_video->CycleBoundary = [this] {
            if (m_engine) m_engine->OnStareCycleBoundary();
        };

        auto ui_queue = winrt::Microsoft::UI::Dispatching::DispatcherQueue::GetForCurrentThread();
        m_pipe = std::make_unique<how_to_train_your_nailong::IPC::SmileResultPipe>(ui_queue);
        m_pipe->OnSample = [this](how_to_train_your_nailong::Game::SmileSample s) {
            if (m_engine) m_engine->OnSmileSample(s);
        };
        m_pipe->OnConnected = [this] {
            if (m_engine) m_engine->OnSidecarReady();
        };
        m_pipe->OnDisconnected = [this](std::string /*reason*/) {
            if (m_engine) m_engine->OnSidecarLost();
            DisableControls(false);
        };

        m_camera = std::make_unique<how_to_train_your_nailong::Media::CameraService>();
        // Auto-spawn of the sidecar is not wired yet — run it manually:
        //   python tools/smile_sidecar/main.py --model ... --port 38751
    }

    void MainPage::StartButton_Click(
        winrt::Windows::Foundation::IInspectable const&,
        winrt::Microsoft::UI::Xaml::RoutedEventArgs const&)
    {
        if (!m_engine) return;
        DisableControls(true);
        m_engine->StartChallenge();
        // Connect the pipe; OnConnected will call engine.OnSidecarReady() and
        // the calibration → countdown → stare loop sequence kicks off from
        // there. If the sidecar isn't running, OnDisconnected fires and the
        // engine moves to the Invalid state.
        if (m_pipe && !m_pipe->IsConnected())
        {
            m_pipe->Connect("127.0.0.1", 38751);
        }
        else if (m_pipe && m_pipe->IsConnected())
        {
            // Already connected from a previous round.
            m_engine->OnSidecarReady();
        }
    }

    void MainPage::ResetButton_Click(
        winrt::Windows::Foundation::IInspectable const&,
        winrt::Microsoft::UI::Xaml::RoutedEventArgs const&)
    {
        if (m_video)  m_video->Stop();
        if (m_engine) m_engine->Reset();
        DisableControls(false);
    }

    void MainPage::DifficultyCombo_SelectionChanged(
        winrt::Windows::Foundation::IInspectable const&,
        winrt::Microsoft::UI::Xaml::Controls::SelectionChangedEventArgs const&)
    {
        const auto idx = DifficultyCombo().SelectedIndex();
        m_difficulty =
            idx == 0 ? how_to_train_your_nailong::Game::Difficulty::Easy :
            idx == 2 ? how_to_train_your_nailong::Game::Difficulty::Hard :
                       how_to_train_your_nailong::Game::Difficulty::Normal;
        if (m_engine) m_engine->SetDifficulty(m_difficulty);
    }

    void MainPage::SetOverlay(std::wstring_view text)
    {
        OverlayText().Text(winrt::hstring{text});
        OverlayBackdrop().Visibility(Microsoft::UI::Xaml::Visibility::Visible);
    }

    void MainPage::ClearOverlay()
    {
        OverlayText().Text(L"");
        OverlayBackdrop().Visibility(Microsoft::UI::Xaml::Visibility::Collapsed);
    }

    void MainPage::DisableControls(bool disabled)
    {
        StartButton().IsEnabled(!disabled);
        DifficultyCombo().IsEnabled(!disabled);
    }
}
