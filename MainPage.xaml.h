#pragma once

#include "MainPage.g.h"

#include "Core/GameEngine.h"
#include "IPC/SmileResultPipe.h"
#include "Media/CameraService.h"
#include "Media/VideoController.h"

#include <memory>

namespace winrt::how_to_train_your_nailong::implementation
{
    struct MainPage : MainPageT<MainPage>
    {
        MainPage();
        ~MainPage();

        // ----- XAML hooks ---------------------------------------------------
        void OnLoaded(
            winrt::Windows::Foundation::IInspectable const& sender,
            winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e);

        void StartButton_Click(
            winrt::Windows::Foundation::IInspectable const& sender,
            winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e);

        void ResetButton_Click(
            winrt::Windows::Foundation::IInspectable const& sender,
            winrt::Microsoft::UI::Xaml::RoutedEventArgs const& e);

        void DifficultyCombo_SelectionChanged(
            winrt::Windows::Foundation::IInspectable const& sender,
            winrt::Microsoft::UI::Xaml::Controls::SelectionChangedEventArgs const& e);

        // ----- legacy template stubs (kept for IDL compatibility) ----------
        int32_t MyProperty();
        void    MyProperty(int32_t value);

    private:
        // IGameView is implemented by a small bridge object so MainPage does
        // not need to multiply-inherit a non-WinRT abstract class on top of
        // its MainPageT<…> base.
        struct ViewBridge;
        std::unique_ptr<ViewBridge>                 m_view_bridge;

        std::unique_ptr<how_to_train_your_nailong::Game::GameEngine>       m_engine;
        std::unique_ptr<how_to_train_your_nailong::Media::VideoController> m_video;
        std::unique_ptr<how_to_train_your_nailong::Media::CameraService>   m_camera;
        std::unique_ptr<how_to_train_your_nailong::IPC::SmileResultPipe>   m_pipe;

        how_to_train_your_nailong::Game::Difficulty m_difficulty{
            how_to_train_your_nailong::Game::Difficulty::Normal};

        void InitializeGame();
        void SetOverlay(std::wstring_view text);
        void ClearOverlay();
        void DisableControls(bool disabled);
    };
}

namespace winrt::how_to_train_your_nailong::factory_implementation
{
    struct MainPage : MainPageT<MainPage, implementation::MainPage>
    {
    };
}
