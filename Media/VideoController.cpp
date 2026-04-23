#include "pch.h"
#include "VideoController.h"

#include <fstream>
#include <filesystem>
#include <random>

#include <winrt/Windows.ApplicationModel.h>
#include <winrt/Microsoft.UI.Dispatching.h>
#include <winrt/Windows.Data.Json.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Media.Core.h>
#include <winrt/Windows.Storage.h>

namespace how_to_train_your_nailong::Media
{
    namespace
    {
        using winrt::Windows::Foundation::TimeSpan;
        using winrt::Windows::Foundation::Uri;

        constexpr TimeSpan ToTimeSpan(Ms ms) noexcept
        {
            return std::chrono::duration_cast<TimeSpan>(ms);
        }
        constexpr Ms FromTimeSpan(TimeSpan ts) noexcept
        {
            return std::chrono::duration_cast<Ms>(ts);
        }

        std::filesystem::path ResolvePackagePath(std::wstring_view package_uri)
        {
            Uri uri{winrt::hstring{package_uri}};
            std::wstring relative{uri.Path().c_str()};
            while (!relative.empty() && (relative.front() == L'/' || relative.front() == L'\\'))
            {
                relative.erase(relative.begin());
            }

            std::filesystem::path root{
                winrt::Windows::ApplicationModel::Package::Current().InstalledLocation().Path().c_str()
            };
            return root / std::filesystem::path{relative};
        }
    }

    // ---------------- VideoSegments JSON loader -----------------------------

    VideoSegments VideoSegments::LoadFromPackage(std::wstring_view config_uri)
    {
        using namespace winrt::Windows::Data::Json;

        VideoSegments seg{};
        try
        {
            const auto path = ResolvePackagePath(config_uri);
            std::ifstream input(path, std::ios::binary);
            if (!input)
            {
                return seg;
            }

            const std::string text{
                std::istreambuf_iterator<char>{input},
                std::istreambuf_iterator<char>{}
            };
            auto root = JsonObject::Parse(winrt::to_hstring(text));

            auto W = [&](std::wstring_view k) -> std::wstring {
                return std::wstring{root.GetNamedString(winrt::hstring{k}).c_str()};
            };
            auto N = [&](std::wstring_view k) -> double {
                return root.GetNamedNumber(winrt::hstring{k});
            };
            auto Ng = [&](std::wstring_view k, double dflt) -> double {
                if (!root.HasKey(winrt::hstring{k})) return dflt;
                auto v = root.GetNamedValue(winrt::hstring{k});
                if (v.ValueType() == JsonValueType::Null) return dflt;
                return v.GetNumber();
            };
            auto Range = [&](std::wstring_view k, Ms& mn, Ms& mx) {
                if (!root.HasKey(winrt::hstring{k})) return;
                auto arr = root.GetNamedArray(winrt::hstring{k});
                if (arr.Size() >= 2)
                {
                    mn = Ms{static_cast<long long>(arr.GetNumberAt(0))};
                    mx = Ms{static_cast<long long>(arr.GetNumberAt(1))};
                }
            };

            seg.source_uri              = W(L"source");
            seg.reverse_source_uri      = W(L"reverse_source");
            seg.stare_start_ms          = Ms{static_cast<long long>(N(L"stare_start_ms"))};
            seg.stare_end_ms            = Ms{static_cast<long long>(N(L"stare_end_ms"))};
            seg.laugh_trigger_frame_ms  = Ms{static_cast<long long>(N(L"laugh_trigger_frame_ms"))};
            seg.laugh_segment_end_ms    = Ms{static_cast<long long>(Ng(L"laugh_segment_end_ms", 0.0))};
            seg.duration_ms             = Ms{static_cast<long long>(Ng(L"duration_ms", 0.0))};
            seg.fps                     = Ng(L"fps", 30.0);
            Range(L"pause_after_stare_ms_range",  seg.pause_after_stare_min,  seg.pause_after_stare_max);
            Range(L"pause_before_stare_ms_range", seg.pause_before_stare_min, seg.pause_before_stare_max);
        }
        catch (...)
        {
            // Caller gets the default-constructed seg with empty URIs;
            // they should detect this and surface an error.
        }
        return seg;
    }

    // ---------------- Impl --------------------------------------------------

    struct VideoController::Impl
    {
        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement element{nullptr};
        winrt::Windows::Media::Playback::MediaPlayer             player{nullptr};
        winrt::Windows::Media::Core::MediaSource                 forward_source{nullptr};
        winrt::Windows::Media::Core::MediaSource                 reverse_source{nullptr};

        VideoSegments segments;
        CyclePhase    phase{CyclePhase::Idle};
        bool          laugh_pending{false};
        bool          configured{false};

        std::mt19937  rng{std::random_device{}()};

        winrt::Microsoft::UI::Dispatching::DispatcherQueue       dispatcher{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  hold_timer{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  poll_timer{nullptr};

        explicit Impl(winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement el) : element(el)
        {
            using namespace winrt::Windows::Media::Playback;
            dispatcher = winrt::Microsoft::UI::Dispatching::DispatcherQueue::GetForCurrentThread();
            player = MediaPlayer();
            player.IsLoopingEnabled(false);   // we own seeking
            player.AutoPlay(false);           // we own play/pause too — prevents
                                              // a brief auto-play burst when Source(...) is set during preload
            element.SetMediaPlayer(player);

            hold_timer = dispatcher.CreateTimer();
            hold_timer.IsRepeating(false);

            poll_timer = dispatcher.CreateTimer();
            poll_timer.IsRepeating(true);
            // Poll position at ~60 Hz. PlaybackSession.PositionChanged fires
            // on a worker thread; polling on the UI thread sidesteps marshaling
            // and gives more deterministic timing for the boundary check.
            poll_timer.Interval(std::chrono::milliseconds{16});
            poll_timer.Tick([this](auto&&, auto&&) { OnPoll(); });
        }

        ~Impl()
        {
            if (poll_timer) poll_timer.Stop();
            if (hold_timer) hold_timer.Stop();
            if (player)     player.Pause();
        }

        void Configure(VideoSegments s)
        {
            segments = std::move(s);
            using winrt::Windows::Media::Core::MediaSource;
            forward_source = MediaSource::CreateFromUri(Uri{winrt::hstring{segments.source_uri}});
            reverse_source = MediaSource::CreateFromUri(Uri{winrt::hstring{segments.reverse_source_uri}});

            // Preload the forward source so audio routing is established and
            // NaturalDuration becomes available before BeginStareCycle. Without
            // this the very first Forward phase plays silently and the first
            // EnterReverse miscalculates its seek target (NaturalDuration is 0
            // until MediaOpened fires for the reverse source). AutoPlay(false)
            // keeps this from briefly showing on screen.
            player.Source(forward_source);
            player.Position(ToTimeSpan(segments.stare_start_ms));

            configured = true;
        }

        Ms RandRange(Ms mn, Ms mx)
        {
            if (mx <= mn) return mn;
            std::uniform_int_distribution<long long> dist(mn.count(), mx.count());
            return Ms{dist(rng)};
        }

        // ---- phase transitions -------------------------------------------

        void EnterForward()
        {
            phase = CyclePhase::Forward;
            player.Source(forward_source);
            player.Position(ToTimeSpan(segments.stare_start_ms));
            player.Play();
            poll_timer.Start();
        }

        void EnterHoldEnd()
        {
            phase = CyclePhase::HoldEnd;
            player.Pause();
            // Boundary fires here: the user has just been "stared at" once.
            if (on_boundary) on_boundary();
            if (laugh_pending)
            {
                laugh_pending = false;
                EnterLaugh();
                return;
            }
            poll_timer.Stop();
            ScheduleHold(RandRange(segments.pause_after_stare_min, segments.pause_after_stare_max),
                         [this] { EnterReverse(); });
        }

        // Length of the reverse video. Prefer the value baked into
        // video_segments.json so we don't depend on MediaPlayer.NaturalDuration
        // having resolved yet (it returns 0 until MediaOpened fires, which
        // races with EnterReverse on the very first cycle).
        Ms ReverseTotal() const
        {
            if (segments.duration_ms.count() > 0) return segments.duration_ms;
            const Ms nat = FromTimeSpan(player.NaturalDuration());
            return nat.count() > 0 ? nat : segments.stare_end_ms;
        }

        void EnterReverse()
        {
            phase = CyclePhase::Reverse;
            player.Source(reverse_source);
            // In the reverse file, the moment that visually corresponds to
            // forward time T is at (duration - T). We want to play the segment
            // that visually goes from stare_end → stare_start, i.e. file time
            // (duration - stare_end) → (duration - stare_start).
            const Ms total = ReverseTotal();
            Ms start_in_reverse = total - segments.stare_end_ms;
            if (start_in_reverse.count() < 0) start_in_reverse = Ms{0};
            player.Position(ToTimeSpan(start_in_reverse));
            player.Play();
            poll_timer.Start();
        }

        void EnterHoldStart()
        {
            phase = CyclePhase::HoldStart;
            player.Pause();
            poll_timer.Stop();
            ScheduleHold(RandRange(segments.pause_before_stare_min, segments.pause_before_stare_max),
                         [this] { EnterForward(); });
        }

        void EnterLaugh()
        {
            phase = CyclePhase::Laughing;
            // The cut happens on the same frame we paused on (stare_end == laugh_trigger),
            // so the user perceives no jump.
            player.Source(forward_source);
            player.Position(ToTimeSpan(segments.laugh_trigger_frame_ms));
            player.Play();
            poll_timer.Stop();   // no boundary checking during laugh
        }

        void ScheduleHold(Ms d, std::function<void()> fn)
        {
            hold_timer.Stop();
            hold_timer.Interval(d);
            static winrt::event_token tok{};
            if (tok.value) { hold_timer.Tick(tok); tok = {}; }
            tok = hold_timer.Tick([fn = std::move(fn)](auto&&, auto&&) { fn(); });
            hold_timer.Start();
        }

        void OnPoll()
        {
            if (!configured) return;
            const auto pos = FromTimeSpan(player.Position());
            switch (phase)
            {
            case CyclePhase::Forward:
                if (pos >= segments.stare_end_ms) EnterHoldEnd();
                break;
            case CyclePhase::Reverse:
            {
                const Ms total = ReverseTotal();
                const Ms target = total - segments.stare_start_ms;
                if (pos >= target) EnterHoldStart();
                break;
            }
            default:
                break;
            }
        }

        std::function<void()> on_boundary;  // mirrors public CycleBoundary
    };

    // ---------------- public surface ---------------------------------------

    VideoController::VideoController(winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement element)
        : m_impl(std::make_unique<Impl>(element)) {}

    VideoController::~VideoController() = default;

    void VideoController::Configure(VideoSegments segments)
    {
        m_impl->Configure(std::move(segments));
    }

    void VideoController::BeginStareCycle()
    {
        if (!m_impl->configured) return;
        m_impl->on_boundary = [this] { if (CycleBoundary) CycleBoundary(); };
        m_impl->laugh_pending = false;
        m_impl->EnterForward();
    }

    void VideoController::Stop()
    {
        if (m_impl->poll_timer) m_impl->poll_timer.Stop();
        if (m_impl->hold_timer) m_impl->hold_timer.Stop();
        if (m_impl->player)     m_impl->player.Pause();
        if (m_impl->configured)
        {
            m_impl->player.Source(m_impl->forward_source);
            m_impl->player.Position(ToTimeSpan(m_impl->segments.stare_start_ms));
        }
        m_impl->phase = CyclePhase::Idle;
    }

    void VideoController::TriggerLaugh()
    {
        // Defer the source swap to the next forward-phase boundary so the cut
        // happens on the "looking-at-viewer" frame and is visually seamless.
        m_impl->laugh_pending = true;
    }

    CyclePhase VideoController::Phase() const noexcept
    {
        return m_impl->phase;
    }
}
