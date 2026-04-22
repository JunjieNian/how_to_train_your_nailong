#pragma once

#include "MainPage.g.h"

namespace winrt::Naiwa::implementation
{
    struct MainPage : MainPageT<MainPage>
    {
        MainPage();

        ~MainPage();
        void OnLoaded(winrt::Windows::Foundation::IInspectable const& sender, winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e);
        int32_t MyProperty();
        void MyProperty(int32_t value);

        private:
			winrt::Windows::Media::Playback::MediaPlayer mediaPlayer{ nullptr };
			void InitializeMediaPlayer();
    public:
        void PlayButton_Click(winrt::Windows::Foundation::IInspectable const& sender, winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e);
    };
}

namespace winrt::Naiwa::factory_implementation
{
    struct MainPage : MainPageT<MainPage, implementation::MainPage>
    {
    };
}
