# Open-VINC Benchmarks

Reproducible native Open-VINC pub/sub workloads and a framework-independent analyzer.
The Publisher and Subscriber are real Modules in separate ModuleHost processes;
data travels through Context and the shared-memory Message Bus. No ROS installation
is required for the Vinc workload. This is an independent harness, not an Apex.AI
`performance_test` plugin or a published ROS/DDS comparison.

可重現的 Open-VINC 原生測試與跨框架共用分析器。發布與接收 Module 分屬獨立程序，
透過正式 Context／Message Bus／pumpLoop；Vinc 測試不需要安裝 ROS。
目前尚未接入 Apex.AI 後端，也沒有產生 ROS／DDS 的比較成績。

## Get the pinned source / 取得固定版本

```sh
git clone --recurse-submodules https://github.com/JayTDawgzone1994/open-vinc-benchmarks.git
cd open-vinc-benchmarks
```

Open-VINC is pinned to `a3a0843c5dc89f8b052c5f25afa66e1f171db99e`, including notification-driven
pumpLoop. CMake rejects a different submodule revision. Update the gitlink and
`cmake/open-vinc-revision.txt` together when intentionally changing the tested version.
The submodule is never patched by this project. Initial recursive checkout also obtains
Open-VINC's existing dependencies and their licenses.

框架固定於上述 commit，包含通知喚醒。修改受測版本時須一起更新 submodule 與版本檔，
不自動追分支，也不改動第三方來源。

## Build / 建置

C++23 and CMake 3.20+ are required; exact validated tools are in [validation](docs/VALIDATION.md).
Use one configuration per build directory. Windows requires an **MSVC x64 Developer shell**
and Ninja, matching the Plugin/Host toolchain and CRT.

```sh
cmake -S . -B build/release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --target vinc_benchmark --parallel 4
ctest --test-dir build/release --output-on-failure
```

On Ubuntu 24.04, add `-DCMAKE_CXX_COMPILER=g++-13` if needed. Python 3.10+ is used for
execution and analysis; the tools use only its standard library. macOS validation
of this suite is pending. WSL results must be labeled WSL, not native Linux results.

Ubuntu 24.04 可明確指定 GCC 13。Python 工具只使用標準函式庫；本專案的 macOS 驗證尚待補上。
CTest 執行分析器契約測試及 push／loan 小型跨程序測試，冒煙數字不是正式效能報告。

## Measure / 執行量測

```sh
python -m tools.run --build-info build/release/benchmark-build-Release.json
```

Defaults: 1 KiB, 1 MiB and 8 MiB payloads; push and loan; one Publisher/Subscriber;
eight slots; requested 100 Hz; 64 warmup + 1,000 formal samples; three interleaved
rounds. A central process supervises both Hosts. The per-case shared budget is 4 GiB,
not a total process-memory limit. Capacity/rate never auto-adjust to hide overload.

預設每組三輪；容量／頻率固定，碰撞或漏收會使該組不合格，所有結果保留。
單次執行會在 `results/` 內建立新的時間戳資料夾，不覆蓋舊結果。
原始資料與建置產物預設不進 Git；要發布的結果須連同環境與原始證據另行整理。

Examples / 範例：

```sh
# Short functional check, not a reliable P99 estimate.
python -m tools.run --build-info build/release/benchmark-build-Release.json --sizes-bytes 1024 --samples 32 --repeats 1

# Explicit Windows-only experiment; this is not a framework default.
python -m tools.run --build-info build/release/benchmark-build-Release.json --pacing windows-highres
```

Standard pacing uses `sleep_until` on a fixed monotonic grid. Missed ticks are
counted and skipped, never replayed as catch-up bursts. A request of 100 Hz is not
an achieved-rate guarantee. Windows high-resolution pacing uses a reused blocking
waitable timer; it does not spin, change timer resolution globally, raise priority,
or silently fall back when unavailable.

預設沿用標準等待 API，不把實際約 64 Hz 寫成 100 Hz。高解析度 timer 為獨立標示的
Windows 實驗模式，失敗會回報，不會偷偷降級。

## Analyze and compare / 分析與比較

```sh
python -m tools.analyze results/SESSION/r1-push-1024
python -m tools.analyze FIRST_NORMALIZED_RUN SECOND_NORMALIZED_RUN --output comparison.json
```

The analyzer consumes [normalized schema v1](docs/SCHEMA.md), without importing Vinc.
It verifies sample IDs, trailing loss, duplicates, content flags, time boundaries,
clock domain and transport counters. P50/P90/P99 use nearest rank on formal valid
samples; a failed run remains failed even if its surviving samples look fast.
Comparison rejects incompatible environment, data size, ownership, rate, queue,
configuration and timing contracts. Use `--allow-pacing-difference` only for an
explicit pacing experiment. A matching fingerprint is not proof of identical hosts
or ambient load; the experiment owner must establish that independently.

共用分析器可由其他框架匯出相同格式後使用；目前沒有 Apex CSV 自動匯入器。
它不會從平均值猜出 P99，也不會把借用共享資料與已取得本機副本默認為相同工作。

Read [methodology](docs/METHODOLOGY.md), [native lifecycle](native/README.md),
[validation and limits](docs/VALIDATION.md), and [third-party attribution](THIRD_PARTY.md).

## License / 授權

Apache-2.0; retain [LICENSE](LICENSE) and [NOTICE](NOTICE).
Open-VINC's existing license deployment accompanies the native artifacts;
this suite also copies its LICENSE/NOTICE into `licenses/open-vinc-benchmarks`.
Distributors must preserve both sets. No Apex source is
incorporated; the methodology is informed by its [performance_test project](https://gitlab.com/ApexAI/performance_test).
