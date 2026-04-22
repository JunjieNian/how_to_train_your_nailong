#pragma once
//
// GameState.h — finite-state-machine vocabulary for the Nailong don't-laugh game.
//
// All states are owned by GameEngine. UI code never sets state directly; it
// only reacts to IGameView callbacks driven by state transitions.
//

#include <cstdint>

namespace Naiwa::Game
{
    enum class GameState : std::uint8_t
    {
        Idle,                   // app launched, waiting for user to press Start
        CameraWarmup,           // sidecar started, waiting for first valid sample
        Calibration,            // recording neutral baseline (~2.5s, configurable)
        Countdown,              // 3-2-1 overlay before stare loop begins
        StareLoop,              // playing stare cycle; nailong_laugh_deadline is armed
        UserLaughDetected,      // user smiled first → user lost, transitioning to Result
        NailongLaughTriggered,  // hidden deadline elapsed → cut to laugh segment, user won
        Result,                 // result overlay shown, awaiting reset
        Invalid,                // round aborted (e.g. lost face for too long)
    };

    enum class Winner : std::uint8_t
    {
        None,
        User,                   // nailong laughed first
        Nailong,                // user laughed first
    };

    enum class Difficulty : std::uint8_t
    {
        Easy,
        Normal,
        Hard,
    };

    constexpr const char* ToString(GameState s) noexcept
    {
        switch (s)
        {
        case GameState::Idle:                  return "Idle";
        case GameState::CameraWarmup:          return "CameraWarmup";
        case GameState::Calibration:           return "Calibration";
        case GameState::Countdown:             return "Countdown";
        case GameState::StareLoop:             return "StareLoop";
        case GameState::UserLaughDetected:     return "UserLaughDetected";
        case GameState::NailongLaughTriggered: return "NailongLaughTriggered";
        case GameState::Result:                return "Result";
        case GameState::Invalid:               return "Invalid";
        }
        return "?";
    }
}
