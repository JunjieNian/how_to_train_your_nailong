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
        enum class Track
        {
            Forward,
            Reverse,
        };

        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement forward_element{nullptr};
        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement reverse_element{nullptr};
        winrt::Windows::Media::Playback::MediaPlayer             forward_player{nullptr};
        winrt::Windows::Media::Playback::MediaPlayer             reverse_player{nullptr};
        winrt::Windows::Media::Core::MediaSource                 forward_source{nullptr};
        winrt::Windows::Media::Core::MediaSource                 reverse_source{nullptr};

        VideoSegments segments;
        CyclePhase    phase{CyclePhase::Idle};
        Track         visible_track{Track::Forward};
        bool          laugh_pending{false};
        bool          configured{false};

        std::mt19937  rng{std::random_device{}()};

        winrt::Microsoft::UI::Dispatching::DispatcherQueue       dispatcher{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  hold_timer{nullptr};
        winrt::Microsoft::UI::Dispatching::DispatcherQueueTimer  poll_timer{nullptr};

        Impl(
            winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement forward_el,
            winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement reverse_el)
            : forward_element(forward_el), reverse_element(reverse_el)
        {
            using namespace winrt::Windows::Media::Playback;

            dispatcher = winrt::Microsoft::UI::Dispatching::DispatcherQueue::GetForCurrentThread();

            forward_player = MediaPlayer();
            forward_player.IsLoopingEnabled(false);
            forward_player.AutoPlay(false);
            forward_element.SetMediaPlayer(forward_player);

            reverse_player = MediaPlayer();
            reverse_player.IsLoopingEnabled(false);
            reverse_player.AutoPlay(false);
            reverse_player.IsMuted(true);
            reverse_element.SetMediaPlayer(reverse_player);

            ShowTrack(Track::Forward);

            hold_timer = dispatcher.CreateTimer();
            hold_timer.IsRepeating(false);

            poll_timer = dispatcher.CreateTimer();
            poll_timer.IsRepeating(true);
            poll_timer.Interval(std::chrono::milliseconds{16});
            poll_timer.Tick([this](auto&&, auto&&) { OnPoll(); });
        }

        ~Impl()
        {
            if (poll_timer)   poll_timer.Stop();
            if (hold_timer)   hold_timer.Stop();
            if (forward_player) forward_player.Pause();
            if (reverse_player) reverse_player.Pause();
        }

        void Configure(VideoSegments s)
        {
            segments = std::move(s);
            using winrt::Windows::Media::Core::MediaSource;
            forward_source = MediaSource::CreateFromUri(Uri{winrt::hstring{segments.source_uri}});
            reverse_source = MediaSource::CreateFromUri(Uri{winrt::hstring{segments.reverse_source_uri}});

            forward_player.Source(forward_source);
            reverse_player.Source(reverse_source);

            PrimeForwardStart();
            PrimeReverseStart();
            ShowTrack(Track::Forward);
            configured = true;
        }

        winrt::Windows::Media::Playback::MediaPlayer& PlayerFor(Track track) noexcept
        {
            return track == Track::Forward ? forward_player : reverse_player;
        }

        const winrt::Windows::Media::Playback::MediaPlayer& PlayerFor(Track track) const noexcept
        {
            return track == Track::Forward ? forward_player : reverse_player;
        }

        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement& ElementFor(Track track) noexcept
        {
            return track == Track::Forward ? forward_element : reverse_element;
        }

        void ShowTrack(Track track)
        {
            visible_track = track;
            ElementFor(Track::Forward).Opacity(track == Track::Forward ? 1.0 : 0.0);
            ElementFor(Track::Reverse).Opacity(track == Track::Reverse ? 1.0 : 0.0);

            // Reverse asset has no useful audio; only the visible forward player
            // should ever speak.
            forward_player.IsMuted(track != Track::Forward);
            reverse_player.IsMuted(true);
        }

        void PrimeForwardStart()
        {
            forward_player.Pause();
            forward_player.Position(ToTimeSpan(segments.stare_start_ms));
        }

        void PrimeReverseStart()
        {
            reverse_player.Pause();
            reverse_player.Position(ToTimeSpan(Ms{0}));
        }

        Ms RandRange(Ms mn, Ms mx)
        {
            if (mx <= mn) return mn;
            std::uniform_int_distribution<long long> dist(mn.count(), mx.count());
            return Ms{dist(rng)};
        }

        Ms StareDuration() const noexcept
        {
            const Ms d = segments.stare_end_ms - segments.stare_start_ms;
            return d.count() > 0 ? d : Ms{1000};
        }

        // ---- phase transitions -------------------------------------------

        void EnterForward()
        {
            phase = CyclePhase::Forward;
            PrimeForwardStart();
            ShowTrack(Track::Forward);
            forward_player.Play();
            poll_timer.Start();
        }

        void EnterHoldEnd()
        {
            phase = CyclePhase::HoldEnd;
            forward_player.Pause();
            if (on_boundary) on_boundary();
            if (laugh_pending)
            {
                laugh_pending = false;
                EnterLaugh();
                return;
            }
            poll_timer.Stop();

            // Prepare the reverse surface while the last forward frame remains
            // visible, then flip opacity after the configured hold.
            PrimeReverseStart();
            ScheduleHold(RandRange(segments.pause_after_stare_min, segments.pause_after_stare_max),
                         [this] { EnterReverse(); });
        }

        void EnterReverse()
        {
            phase = CyclePhase::Reverse;
            ShowTrack(Track::Reverse);
            reverse_player.Play();
            poll_timer.Start();

            // Immediately park the hidden forward player back at stare_start so
            // the next Reverse -> Forward handoff also avoids any source churn.
            PrimeForwardStart();
        }

        void EnterHoldStart()
        {
            phase = CyclePhase::HoldStart;
            reverse_player.Pause();
            poll_timer.Stop();
            PrimeForwardStart();
            ScheduleHold(RandRange(segments.pause_before_stare_min, segments.pause_before_stare_max),
                         [this] { EnterForward(); });
        }

        void EnterLaugh()
        {
            phase = CyclePhase::Laughing;
            ShowTrack(Track::Forward);
            forward_player.Position(ToTimeSpan(segments.laugh_trigger_frame_ms));
            forward_player.Play();
            poll_timer.Stop();
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

            const auto pos = FromTimeSpan(PlayerFor(visible_track).Position());
            switch (phase)
            {
            case CyclePhase::Forward:
                if (pos >= segments.stare_end_ms) EnterHoldEnd();
                break;
            case CyclePhase::Reverse:
                if (pos >= StareDuration()) EnterHoldStart();
                break;
            default:
                break;
            }
        }

        std::function<void()> on_boundary;
    };

    // ---------------- public surface ---------------------------------------

    VideoController::VideoController(
        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement forward_element,
        winrt::Microsoft::UI::Xaml::Controls::MediaPlayerElement reverse_element)
        : m_impl(std::make_unique<Impl>(forward_element, reverse_element)) {}

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
        if (m_impl->forward_player) m_impl->forward_player.Pause();
        if (m_impl->reverse_player) m_impl->reverse_player.Pause();
        if (m_impl->configured)
        {
            m_impl->PrimeForwardStart();
            m_impl->PrimeReverseStart();
            m_impl->ShowTrack(Impl::Track::Forward);
        }
        m_impl->phase = CyclePhase::Idle;
    }

    void VideoController::TriggerLaugh()
    {
        // Defer the handoff to the next forward-phase boundary so the cut
        // happens on the "looking-at-viewer" frame and is visually seamless.
        m_impl->laugh_pending = true;
    }

    CyclePhase VideoController::Phase() const noexcept
    {
        return m_impl->phase;
    }
}
