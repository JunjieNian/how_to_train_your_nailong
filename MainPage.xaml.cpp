#include "pch.h"
#include <winrt/Windows.Media.Playback.h>
#include <winrt/Windows.Media.Core.h>
#include "MainPage.xaml.h"
#if __has_include("MainPage.g.cpp")
#include "MainPage.g.cpp"
#endif

using namespace winrt;
using namespace Microsoft::UI::Xaml;
using namespace Windows::Media::Playback;
using namespace Windows::Media::Core;
using namespace winrt::Windows::Foundation;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace winrt::Naiwa::implementation
{
    MainPage::MainPage()
    {
        InitializeComponent();
        Loaded({ this, &MainPage::OnLoaded });
    }

	MainPage::~MainPage()
	{
		if (mediaPlayer)
		{
			mediaPlayer.Close();
		}
	}

    int32_t MainPage::MyProperty()
    {
        throw hresult_not_implemented();
    }

    void MainPage::MyProperty(int32_t /* value */)
    {
        throw hresult_not_implemented();
    }

    void MainPage::OnLoaded(winrt::Windows::Foundation::IInspectable const& sender, winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e)
    {
        // 在页面加载后初始化媒体播放器并将其附加到 MediaPlayerElement
        InitializeMediaPlayer();
        if (VideoPlayer())
        {
            VideoPlayer().SetMediaPlayer(mediaPlayer);
            // 根据视频原始尺寸调整控件宽度以匹配视频宽度，同时填满窗口高度
            // 如果无法立即获得 NaturalVideoHeight/Width，则在 MediaOpened 回调中设置
            auto playbackSession = mediaPlayer.PlaybackSession();
            auto setSize = [this, playbackSession]() {
                try
                {
                    double videoW = static_cast<double>(playbackSession.NaturalVideoWidth());
                    double videoH = static_cast<double>(playbackSession.NaturalVideoHeight());
                    if (videoW > 0 && videoH > 0)
                    {
                        double containerH = VideoBorder().ActualHeight();
                        double scale = containerH / videoH;
                        double desiredW = videoW * scale;
                        VideoPlayer().Width(desiredW);
                        VideoPlayer().Height(containerH);
                        // 居中
                        VideoPlayer().HorizontalAlignment(Microsoft::UI::Xaml::HorizontalAlignment::Center);
                        VideoPlayer().VerticalAlignment(Microsoft::UI::Xaml::VerticalAlignment::Center);
                    }
                }
                catch (...) {}
            };

            mediaPlayer.MediaOpened([this, setSize](auto&&, auto&&) {
                setSize();
            });

            // 也在 Border 大小改变时重新计算
            VideoBorder().SizeChanged([this, setSize](auto&&, auto&&) {
                setSize();
            });

            // 确保在首次布局完成后也做一次尺寸计算（解决启动时 ActualHeight 为 0 导致留白颜色未刷新的问题）
            {
                winrt::event_token layoutToken;
                layoutToken = VideoBorder().LayoutUpdated([this, setSize, &layoutToken](auto&&, auto&&) {
                    setSize();
                    // 取消订阅该事件（只执行一次）
                    VideoBorder().LayoutUpdated(layoutToken);
                });
            }
        }
    }
}

void winrt::Naiwa::implementation::MainPage::PlayButton_Click(winrt::Windows::Foundation::IInspectable const& sender, winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e)
{
    if (!mediaPlayer) return;

	auto playbackSession = mediaPlayer.PlaybackSession();
    if (playbackSession.PlaybackState() == MediaPlaybackState::Playing)
    {
        mediaPlayer.Pause();

		//PlayButton().Content(winrt::box_value(L"循环播放"));
    }
    else
    {
        mediaPlayer.Play();
		//PlayButton().Content(winrt::box_value(L"暂停"));
    }
}

void winrt::Naiwa::implementation::MainPage::InitializeMediaPlayer()
{
	mediaPlayer = MediaPlayer();
	mediaPlayer.IsLoopingEnabled(true);
    auto mediaSource = winrt::Windows::Media::Core::MediaSource::CreateFromUri(winrt::Windows::Foundation::Uri{ L"ms-appx:///Assets/Video/Naiwa.mp4" });
    mediaPlayer.Source(mediaSource);
	//PlayButton().Content(winrt::box_value(L"循环播放"));
}
