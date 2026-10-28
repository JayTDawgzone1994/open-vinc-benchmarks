#pragma once

#include <charconv>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <sys/resource.h>
#include <time.h>
#include <vector>

namespace experiment {
using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;
inline constexpr std::uint64_t maximum_bytes = 128ULL * 1024 * 1024;
inline constexpr auto discovery_timeout = 30s;
inline constexpr auto control_poll = 20ms;
inline constexpr auto warmup_drain = 1s;
inline constexpr auto post_publish_timeout = 30s;
inline constexpr std::uint8_t first_marker = 0x5a;
inline constexpr std::uint8_t last_marker = 0xa5;

inline std::uint64_t now_ns() {
    timespec value{};
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        std::terminate();
    }
    return std::uint64_t(value.tv_sec) * 1000000000ULL + value.tv_nsec;
}

inline std::uint64_t pacing_ns(Clock::time_point value) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(value.time_since_epoch()).count();
}

struct Resources {
    bool valid = false;
    std::uint64_t cpu_ns = 0;
    std::uint64_t peak_rss_bytes = 0;
};

inline Resources resources() {
    rusage value{};
    if (getrusage(RUSAGE_SELF, &value) != 0) {
        return {};
    }
    return {true,
        (std::uint64_t(value.ru_utime.tv_sec) + value.ru_stime.tv_sec) * 1000000000ULL +
        (std::uint64_t(value.ru_utime.tv_usec) + value.ru_stime.tv_usec) * 1000,
        std::uint64_t(value.ru_maxrss) * 1024};
}

inline bool save_resources(const std::filesystem::path& path, Resources before,
                           Resources after, std::uint64_t start, std::uint64_t end) {
    const bool valid = before.valid && after.valid && after.cpu_ns >= before.cpu_ns && end > start;
    std::ofstream file(path);
    file << "valid,cpu_ns,wall_ns,peak_rss_bytes\n";
    file << valid << ',' << (valid ? after.cpu_ns - before.cpu_ns : 0) << ','
         << (end >= start ? end - start : 0) << ',' << after.peak_rss_bytes << '\n';
    file.close();
    return !file.fail();
}

struct Options {
    std::string role;
    std::string profile;
    std::uint64_t bytes = 0;
    std::uint64_t slots = 0;
    std::uint64_t period_ns = 0;
    std::uint64_t samples = 0;
    std::uint64_t warmup = 0;
    std::filesystem::path directory;
    std::string topic;
};

inline bool number(std::string_view text, std::uint64_t& value) {
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size();
}

inline bool parse(int argc, char** argv, Options& options) {
    if (argc != 11) {
        return false;
    }
    options.role = argv[1];
    options.profile = argv[2];
    options.directory = argv[9];
    options.topic = argv[10];
    return number(argv[3], options.bytes) && number(argv[4], options.slots) &&
        number(argv[5], options.period_ns) && number(argv[6], options.samples) &&
        number(argv[7], options.warmup) && std::string_view(argv[8]) == "owned-copy" &&
        options.bytes >= 2 && options.bytes <= maximum_bytes && options.slots >= 2 && options.slots <= 65536 &&
        options.period_ns > 0 && options.period_ns <= 1000000000 &&
        options.samples >= 2 && options.samples <= 100000 && options.warmup <= 100000 &&
        options.warmup >= 2 * options.slots &&
        (options.role == "publisher" || options.role == "subscriber") &&
        (options.profile == "default" || options.profile == "shm" || options.profile == "datasharing") &&
        std::filesystem::is_directory(options.directory);
}

int run_frame(const Options&);
int run_frame1k(const Options&);
int run_frame1m(const Options&);
int run_frame8m(const Options&);
int run_frame16m(const Options&);
int run_frame32m(const Options&);
int run_frame64m(const Options&);
int run_frame128m(const Options&);
}
