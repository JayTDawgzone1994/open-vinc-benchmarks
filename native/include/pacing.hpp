#pragma once

#include <benchmark.hpp>
#include <cstdlib>
#include <iostream>
#include <thread>

namespace benchmark {
using PacingClock = std::chrono::steady_clock;

inline std::uint64_t pacing_stamp(PacingClock::time_point value) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch()).count();
}

inline std::string pacing_mode() {
#ifdef _WIN32
    char value[32]{};
    const auto length = GetEnvironmentVariableA("VINC_BENCHMARK_PACING", value, sizeof(value));
    if (length >= sizeof(value)) {
        return "invalid";
    }
    return length ? value : "standard";
#else
    // Environment is supplied at process creation and never mutated by this test.
    const auto* value = std::getenv("VINC_BENCHMARK_PACING");
    return value ? value : "standard";
#endif
}

class PacingWaiter {
#ifdef _WIN32
    HANDLE timer_ = nullptr;
#endif

public:
    ~PacingWaiter() {
#ifdef _WIN32
        if (timer_) {
            CloseHandle(timer_);
        }
#endif
    }

    vinc::Result<void> prepare() {
        const auto mode = pacing_mode();
        if (mode == "standard") {
            return {};
        }
#ifdef _WIN32
        if (mode == "windows-highres") {
            timer_ = CreateWaitableTimerExW(nullptr, nullptr,
                CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_MODIFY_STATE | SYNCHRONIZE);
            if (timer_) {
                return {};
            }
            std::cerr << "High-resolution timer creation failed: " << GetLastError() << '\n';
        }
#endif
        // A requested experiment must never silently become a different mode.
        return std::unexpected(failure());
    }

    vinc::Result<void> wait_until(PacingClock::time_point deadline) {
#ifdef _WIN32
        if (timer_) {
            for (;;) {
                const auto remaining = std::chrono::duration_cast<std::chrono::nanoseconds>(deadline - PacingClock::now()).count();
                if (remaining <= 0) {
                    return {};
                }

                // Win32 relative due times are negative multiples of 100 ns.
                // Keep scheduling on the monotonic clock; never pass UTC deadlines.
                LARGE_INTEGER due{};
                due.QuadPart = -((remaining + 99) / 100);
                if (!SetWaitableTimerEx(timer_, &due, 0, nullptr, nullptr, nullptr, 0)) {
                    std::cerr << "Timer arm failed: " << GetLastError() << '\n';
                    return std::unexpected(failure());
                }

                constexpr DWORD wait_failure_guard_ms = 2000;
                const auto waited = WaitForSingleObject(timer_, wait_failure_guard_ms);
                if (waited != WAIT_OBJECT_0) {
                    std::cerr << "Timer wait failed or exceeded guard: " << waited << '\n';
                    return std::unexpected(failure());
                }
            }
        }
#endif
        std::this_thread::sleep_until(deadline);
        return {};
    }
};
}
