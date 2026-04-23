#pragma once
//
// VideoController.h — drives the Nailong MediaPlayer through the four-phase
// stare cycle and seamlessly into the laugh segment.
//
// Phase sequence (one cycle):
//
//   Phase 1  Forward     play(stare_start_ms -> stare_end_ms) using forward source
//   Phase 2  HoldEnd     pause on last stare frame (random duration)
//   Phase 3  Reverse     play forward(0 -> stare_end_ms - stare_start_ms) on the
//                        reverse source — visually "stare_end_ms -> stare_start_ms"
//   Phase 4  HoldStart   pause on first stare frame (random duration)
//
// On each Phase 1 -> Phase 2 boundary, VideoController fires CycleBoundary(),
// which GameEngine uses to decide whether to call TriggerLaugh(). When
// TriggerLaugh() is called, the controller switches the source back to the
// forward video and plays from laugh_trigger_frame_ms to laugh_segment_end_ms
// (or natural end). The cut happens on the same frame the cycle paused on,
// so the user perceives no jump.
//
// Threading: all public methods on UI thread.
//

#include <chrono>
#include <functional>
#include <memory>
#include <string>

#include <winrt/Microsoft.UI.Xaml.Controls.h>
#include <winrt/Windows.Media.Playback.h>

namespace how_to_train_your_nailong::Media
{
    using Ms = std::chrono::milliseconds;

    struct VideoSegments
    {
        std::wstring source_uri;            // forward mp4
        std::wstring reverse_source_uri;    // pre-generated reverse mp4
        Ms  stare_start_ms{0};
        Ms  stare_end_ms{1000};
        Ms  laugh_trigger_frame_ms{1000};
        Ms  laugh_segment_end_ms{0};        // 0 => play to natural end
        Ms  pause_after_stare_min{800};
        Ms  pause_after_stare_max{1200};
        Ms  pause_before_stare_min{400};
        Ms  pause_before_stare_max{800};
        Ms  duration_ms{0};                 // total duration of the source clip; 0 => unknown, fall back to MediaPlayer.NaturalDuration
        double fps{30.0};

        // Load from Assets/Config/video_segments.json (relative to package).
        static VideoSegments LoadFromPackage(std::wstring_view config_uri);
    };

    enum class CyclePhase
    {
        Idle,
        Forward,
        HoldEnd,
        Reverse,
        HoldStart,
        Laughing,
    };

    class VideoController
    {
    public:
        explicit VideoController(winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement element);
        ~VideoController();

        VideoController(const VideoController&)            = delete;
        VideoController& operator=(const VideoController&) = delete;

        void Configure(VideoSegments segments);

        // Begin the four-phase cycle from the Forward phase.
        void BeginStareCycle();

        // Cleanly stop. Resets player to first stare frame, paused.
        void Stop();

        // Cut from current cycle into the laugh segment. Safe to call from
        // any phase; the controller waits until the next "looking-at-viewer"
        // frame (Phase 1 end) before swapping sources, so the transition is
        // visually seamless.
        void TriggerLaugh();

        // Fired on every Phase 1 -> Phase 2 transition (i.e. the moment the
        // user has just been "stared at" for stare_end_ms - stare_start_ms).
        // GameEngine uses this to evaluate the hidden deadline.
        std::function<void()> CycleBoundary;

        CyclePhase Phase() const noexcept;

    private:
        struct Impl;
        std::unique_ptr<Impl> m_impl;
    };
}
