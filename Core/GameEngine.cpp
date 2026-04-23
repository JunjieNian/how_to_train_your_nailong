#include "pch.h"
#include "GameEngine.h"

#include <algorithm>
#include <functional>
#include <optional>
#include <random>

#include <winrt/Microsoft.UI.Dispatching.h>

namespace how_to_train_your_nailong::Game
{
    namespace
    {
        // Hard-coded fallback difficulty presets. Mirror the values in
        // Assets/Config/game_difficulty.json so behaviour is consistent even if
        // that file is missing or corrupt. A future change can have the engine
        // load and merge the JSON over these defaults.
        DifficultyParams ParamsFor(Difficulty d) noexcept
        {
            DifficultyParams p;
            switch (d)
            {
            case Difficulty::Easy:
                p.nailong_laugh_min = Duration{8000};
                p.nailong_laugh_max = Duration{18000};
                p.calibration       = Duration{3000};
                p.smile_threshold   = 0.30f;
                p.consecutive_frames_to_confirm = 4;
                p.lost_face_grace   = Duration{2000};
                p.lost_face_invalid = Duration{7000};
                break;
            case Difficulty::Normal:
                p.nailong_laugh_min = Duration{5000};
                p.nailong_laugh_max = Duration{12000};
                p.calibration       = Duration{2500};
                p.smile_threshold   = 0.28f;
                p.consecutive_frames_to_confirm = 4;
                p.lost_face_grace   = Duration{1500};
                p.lost_face_invalid = Duration{5000};
                break;
            case Difficulty::Hard:
                p.nailong_laugh_min = Duration{3000};
                p.nailong_laugh_max = Duration{8000};
                p.calibration       = Duration{2000};
                p.smile_threshold   = 0.25f;
                p.consecutive_frames_to_confirm = 3;
                p.lost_face_grace   = Duration{1000};
                p.lost_face_invalid = Duration{4000};
                break;
            }
            return p;
        }
    }

    struct GameEngine::Impl
    {
        IGameView&        view;
        GameState         state{GameState::Idle};
        Difficulty        difficulty{Difficulty::Normal};
        DifficultyParams  params{ParamsFor(Difficulty::Normal)};
        Winner            last_winner{Winner::None};

        std::mt19937                       rng{std::random_device{}()};
        TimePoint                          nailong_laugh_deadline{};
        std::optional<TimePoint>           lost_face_since;
        int                                countdown_remaining{0};

        winrt::Microsoft::UI::Dispatching::DispatcherQueue       dispatcher{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  delay_timer{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  countdown_timer{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  lost_face_timer{nullptr};

        explicit Impl(IGameView& v) : view(v)
        {
            dispatcher = winrt::Microsoft::UI::Dispatching::DispatcherQueue::GetForCurrentThread();
            // GameEngine must be constructed on the UI thread.
            // If GetForCurrentThread() returns nullptr, callers used the wrong thread.
            delay_timer     = dispatcher.CreateTimer();
            countdown_timer = dispatcher.CreateTimer();
            lost_face_timer = dispatcher.CreateTimer();
        }

        void Transition(GameState next)
        {
            state = next;
        }

        void DelayOnce(Duration d, std::function<void()> fn)
        {
            delay_timer.Stop();
            delay_timer.Interval(d);
            delay_timer.IsRepeating(false);
            // Replace the previous Tick handler. revoker pattern would be cleaner;
            // for MVP we just keep one shared timer and overwrite.
            static winrt::event_token token{};
            if (token.value)
            {
                delay_timer.Tick(token);
                token = {};
            }
            token = delay_timer.Tick([fn = std::move(fn)](auto&&, auto&&) {
                fn();
            });
            delay_timer.Start();
        }

        void StopAllTimers()
        {
            if (delay_timer)     delay_timer.Stop();
            if (countdown_timer) countdown_timer.Stop();
            if (lost_face_timer) lost_face_timer.Stop();
        }

        // ---- transitions --------------------------------------------------

        void EnterCalibration()
        {
            Transition(GameState::Calibration);
            view.ShowOverlay(L"看着奶龙，先别笑（校准中…）");
            view.RequestSidecarCalibration(true);

            DelayOnce(params.calibration, [this] {
                if (state != GameState::Calibration) return;
                view.RequestSidecarCalibration(false);
                EnterCountdown();
            });
        }

        void EnterCountdown()
        {
            Transition(GameState::Countdown);
            countdown_remaining = 3;
            view.StartCountdown(countdown_remaining);
            view.ShowOverlay(L"3");

            countdown_timer.Stop();
            countdown_timer.Interval(std::chrono::milliseconds{1000});
            countdown_timer.IsRepeating(true);
            static winrt::event_token tok{};
            if (tok.value) { countdown_timer.Tick(tok); tok = {}; }
            tok = countdown_timer.Tick([this](auto&&, auto&&) {
                if (state != GameState::Countdown) { countdown_timer.Stop(); return; }
                --countdown_remaining;
                if (countdown_remaining > 0)
                {
                    view.StartCountdown(countdown_remaining);
                    view.ShowOverlay(countdown_remaining == 2 ? L"2" : L"1");
                }
                else
                {
                    countdown_timer.Stop();
                    view.ClearOverlay();
                    EnterStareLoop();
                }
            });
            countdown_timer.Start();
        }

        void EnterStareLoop()
        {
            Transition(GameState::StareLoop);
            // Arm the hidden deadline.
            std::uniform_int_distribution<long long> dist(
                params.nailong_laugh_min.count(),
                params.nailong_laugh_max.count());
            nailong_laugh_deadline = Clock::now() + Duration{dist(rng)};
            lost_face_since.reset();
            view.BeginStareCycle();
        }

        void DeclareWinner(Winner w)
        {
            last_winner = w;

            // Both outcomes end with nailong laughing. The difference is timing:
            //
            // User wins (nailong laughed first):
            //   t=0     TriggerNailongLaugh → seamless cut at next cycle boundary
            //   t+300ms show "奶龙先笑了！你赢了" overlay, re-enable controls
            //
            // Nailong wins (user laughed first):
            //   t=0     show "你笑了！奶龙赢" overlay (let user read it)
            //   t+1500  TriggerNailongLaugh → nailong also breaks into laughter
            //           re-enable controls (user can reset / start a new round)
            //
            // In both cases the stare cycle keeps running in the background
            // until VideoController.TriggerLaugh() defers the cut to the next
            // Forward→HoldEnd boundary for a visually seamless transition.

            if (w == Winner::User)
            {
                Transition(GameState::NailongLaughTriggered);
                view.TriggerNailongLaugh();
                DelayOnce(Duration{300}, [this, w] {
                    Transition(GameState::Result);
                    view.ShowResult(w);
                });
            }
            else  // Winner::Nailong — user laughed first
            {
                Transition(GameState::UserLaughDetected);
                view.ShowOverlay(L"你笑了！奶龙赢");
                DelayOnce(Duration{1500}, [this, w] {
                    view.TriggerNailongLaugh();
                    Transition(GameState::Result);
                    view.ShowResult(w);
                });
            }
        }

        void DeclareInvalid()
        {
            Transition(GameState::Invalid);
            view.ShowOverlay(L"奶龙看不见你了 — 本局作废");
            DelayOnce(Duration{1500}, [this] {
                Reset();
            });
        }

        void Reset()
        {
            StopAllTimers();
            view.ClearOverlay();
            view.RequestSidecarCalibration(false);  // ensure sidecar is back to idle
            last_winner = Winner::None;
            lost_face_since.reset();
            Transition(GameState::Idle);
        }

        // ---- inputs --------------------------------------------------------

        void OnSample(const SmileSample& s)
        {
            // Track lost-face windows in any "live" state.
            const bool live =
                state == GameState::Countdown ||
                state == GameState::StareLoop;

            if (live)
            {
                if (!s.face_found)
                {
                    if (!lost_face_since) lost_face_since = s.t;
                    auto missing = std::chrono::duration_cast<Duration>(s.t - *lost_face_since);
                    if (missing > params.lost_face_grace)
                    {
                        view.ShowOverlay(L"奶龙看不见你了…");
                    }
                    if (missing > params.lost_face_invalid)
                    {
                        DeclareInvalid();
                        return;
                    }
                }
                else
                {
                    if (lost_face_since)
                    {
                        view.ClearOverlay();
                        lost_face_since.reset();
                    }
                }
            }

            // Smile triggers user-loss only during StareLoop.
            if (state == GameState::StareLoop && s.is_smiling && s.calibrated)
            {
                DeclareWinner(Winner::Nailong);  // user laughed first → nailong wins
            }
        }
    };

    // ---- public surface ----------------------------------------------------

    GameEngine::GameEngine(IGameView& view) : m_impl(std::make_unique<Impl>(view)) {}
    GameEngine::~GameEngine() = default;

    void GameEngine::SetDifficulty(Difficulty d)
    {
        m_impl->difficulty = d;
        m_impl->params = ParamsFor(d);
    }

    void GameEngine::StartChallenge()
    {
        if (m_impl->state != GameState::Idle && m_impl->state != GameState::Result &&
            m_impl->state != GameState::Invalid)
        {
            return;  // already in a round
        }
        m_impl->Transition(GameState::CameraWarmup);
        m_impl->view.ShowOverlay(L"准备摄像头…");
        // GameEngine waits for OnSidecarReady() to be called by the host.
    }

    void GameEngine::Reset()
    {
        m_impl->Reset();
    }

    void GameEngine::OnSmileSample(const SmileSample& s)
    {
        m_impl->OnSample(s);
    }

    void GameEngine::OnStareCycleBoundary()
    {
        if (m_impl->state != GameState::StareLoop) return;
        if (Clock::now() >= m_impl->nailong_laugh_deadline)
        {
            m_impl->DeclareWinner(Winner::User);  // nailong laughed first → user wins
        }
        // else: VideoController will keep cycling on its own.
    }

    void GameEngine::OnSidecarReady()
    {
        if (m_impl->state != GameState::CameraWarmup) return;
        m_impl->EnterCalibration();
    }

    void GameEngine::OnSidecarLost()
    {
        m_impl->StopAllTimers();
        m_impl->view.ShowOverlay(L"摄像头检测进程已断开");
        m_impl->Transition(GameState::Invalid);
    }

    GameState GameEngine::State() const noexcept     { return m_impl->state; }
    Winner    GameEngine::LastWinner() const noexcept { return m_impl->last_winner; }
}
