#pragma once
//
// GameEngine.h — central game state machine for the don't-laugh challenge.
//
// Threading model: all public methods MUST be called on the UI thread (the
// thread that constructed the engine). Smile samples arriving from a
// background WebSocket should be marshalled via DispatcherQueue.TryEnqueue
// before being passed to OnSmileSample.
//
// The engine owns no UI itself. It drives an IGameView interface implemented
// by MainPage; the view is responsible for triggering video transitions and
// rendering overlays.
//

#include "GameState.h"

#include <chrono>
#include <cstdint>
#include <memory>
#include <random>
#include <string>

namespace Naiwa::Game
{
    using Clock     = std::chrono::steady_clock;
    using TimePoint = Clock::time_point;
    using Duration  = std::chrono::milliseconds;

    struct DifficultyParams
    {
        Duration nailong_laugh_min{5000};
        Duration nailong_laugh_max{12000};
        Duration calibration{2500};
        float    smile_threshold{0.28f};
        int      consecutive_frames_to_confirm{4};
        Duration lost_face_grace{1500};
        Duration lost_face_invalid{5000};
    };

    struct SmileSample
    {
        TimePoint t;
        bool      face_found;
        float     smile_score;          // baseline-subtracted, 0..1
        bool      is_smiling;           // sliding-window confirmed
        bool      calibrated;
    };

    // View interface implemented by MainPage. All callbacks fire on the UI
    // thread synchronously from inside the corresponding On*() handler.
    struct IGameView
    {
        virtual ~IGameView() = default;

        virtual void ShowOverlay(std::wstring_view text)                = 0;
        virtual void ClearOverlay()                                     = 0;
        virtual void StartCountdown(int seconds)                        = 0;          // 3..2..1
        virtual void BeginStareCycle()                                  = 0;          // VideoController
        virtual void TriggerNailongLaugh()                              = 0;          // cut to laugh segment
        virtual void ShowResult(Winner winner)                          = 0;
        virtual void RequestSidecarCalibration(bool start)              = 0;          // forwards to SmileResultPipe
    };

    class GameEngine
    {
    public:
        explicit GameEngine(IGameView& view);
        ~GameEngine();

        GameEngine(const GameEngine&)            = delete;
        GameEngine& operator=(const GameEngine&) = delete;

        // ----- inputs from UI -------------------------------------------------
        void SetDifficulty(Difficulty d);
        void StartChallenge();          // Idle -> CameraWarmup
        void Reset();                   // any -> Idle

        // ----- inputs from detector ------------------------------------------
        void OnSmileSample(const SmileSample& s);

        // ----- inputs from VideoController -----------------------------------
        // Called at the END of each forward-stare phase. This is where we
        // decide whether the hidden nailong-laugh deadline has expired and
        // we should seamlessly transition into the laugh segment.
        void OnStareCycleBoundary();

        // ----- inputs from sidecar lifecycle ---------------------------------
        void OnSidecarReady();
        void OnSidecarLost();

        // ----- accessors ------------------------------------------------------
        GameState State() const noexcept;
        Winner    LastWinner() const noexcept;

    private:
        struct Impl;
        std::unique_ptr<Impl> m_impl;
    };
}
