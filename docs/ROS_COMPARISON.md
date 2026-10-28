# WSL ROS 2 comparison / WSL ROS 2 對照紀錄

Measured 2026-10-28–29 (Asia/Taipei), primary dataset
`20261028-224514-735300`. The [published result bundle](../reports/2026-10-28-wsl-ros2/README.md)
contains all 116 primary attempts, raw numeric samples, normalized data, charts
and verification instructions. Original local command/build logs and the earlier
aborted diagnostic campaigns remain outside the published data archive.

測試機為 Windows 11／Ryzen 7 5700X3D，WSL2 Ubuntu 24.04.5，16 個邏輯 CPU。
兩者皆為 GCC/libstdc++ 13.3、Release。Open-VINC 固定
`a3a0843c5dc89f8b052c5f25afa66e1f171db99e`，框架未修改。
ROS 2 Jazzy：rclcpp 28.1.22、rmw_fastrtps_cpp 8.4.4、Fast DDS 2.14.7、Fast CDR 2.2.8。
這是 WSL 實測，不是原生 Linux 部署認證或所有 ROS 後端的排名。

## Method / 方法

One Publisher and Subscriber in separate processes, ordinary local push/publish,
independent process-local receive messages, CLOCK_MONOTONIC API-entry-to-callback
latency. Standard blocking pacing on a fixed monotonic grid; missed ticks skipped,
never catch-up bursts. No priority, affinity, global timer, or busy-spin tuning.
Interactive desktop background load was not isolated.

每組 64 筆暖身及 1,000 筆正式資料，三輪交錯順序。Ring/history 深度 32，
128 MiB 使用 30；Native 實際 Bus 配置檢查上限 4 GiB。先保留從 100 Hz 起的壓力試跑，
以 128 筆校準、完整 ID、實際頻率 ±5%、延遲累積及餘裕選共同速率；正式設定凍結。
完整規則與配置見 [ROS README](../ros2/README.md)。

ROS default uses RELIABLE, default transports and Data Sharing OFF. The tuned
profile uses BEST_EFFORT, synchronous publication, explicit Data Sharing ON,
per-size bounded sequences and bounded history resources. RMW application loans
and intra-process delivery are disabled. A local SharedPtr callback retains the
required owned local message. This is not an end-to-end zero-copy claim or a claim
that DDS reliability equals Vinc's overwrite/protected-reader contract.

## Formal observations / 正式結果

P99 below is the **median of the three per-run P99 values**, milliseconds; it is
not the percentile of pooled samples. Percentiles use nearest rank. Full reports
include P50/P90/P99/max, per-run ranges, losses, CPU, RSS, pacing and every pilot.

| Payload | Common Hz | Vinc P99 median ms | ROS Data Sharing P99 median ms | Default ROS passing rounds |
|---|---:|---:|---:|---:|
| 1 KiB | 100 | 0.11 | 0.23 | 3/3 |
| 1 MiB | 100 | 0.57 | 0.51 | 3/3 |
| 8 MiB | 100 | 4.07 | 3.52 | 3/3 |
| 16 MiB | 100 | 7.75 | 7.62 | 0/3 |
| 32 MiB | 25 | 36.45 | 32.62 | 0/3 |
| 64 MiB | 10 | 79.53 | 73.91 | 2/3 |
| 128 MiB | 5 | 178.72 | 147.01 | 0/3 |

Native Vinc and tuned ROS each passed **21/21** formal cases: all expected IDs,
including warmup, arrived with valid size/sequence/edge markers. This is not a full
payload hash. Unavailable DDS internal counters remain null, not invented zeros.
Failed default ROS cases and high-rate pilots remain in the dataset.

不可把本表解讀成所有大小都達到 100 Hz，也不能把中位數視為最差情境。
例如 64 MiB 的調校 ROS 三輪 P99 範圍約 68–466 ms，Vinc 約 77–81 ms；
32 MiB Vinc 約 35–130 ms、調校 ROS 約 30–49 ms。請連同尾端波動與完整收送判定閱讀。
調校 ROS 並非一律比 Vinc 慢；較大的資料也不能只拿未調校 ROS 作總體結論。

## Corrected diagnostic setup / 已修正的診斷設定

Earlier `build/comparison/` campaigns used UniquePtr callbacks. Installed rclcpp
dispatch allocates and copy-constructs a second local message for that callback
shape. SharedPtr delivery avoids that extra copy while retaining a process-local
message, with RMW loans disabled. The final matrix was rerun in full; earlier
UniquePtr data is diagnostic only and never mixed into the primary scores.
See the [recorded-version dispatch](https://github.com/ros2/rclcpp/blob/28.1.22/rclcpp/include/rclcpp/any_subscription_callback.hpp).

Other preflight corrections: installed Fast DDS 2.14 uses
`FASTRTPS_DEFAULT_PROFILES_FILE`; the newer spelling was ignored. Explicit ON is
limited to the benchmark topic, since ROS management messages can be unbounded.
Both endpoints must observe discovery before sample 1. Private mapping files are
inventoried to verify Data Sharing was prepared. Depth 31 at 128 MiB exceeds the
backend's uint32 segment bound after its extra sample/metadata; depth 30 fits.
All failed/invalid preflights remain archived as diagnostics.

## Loan and charts / Loan 與圖表

The [root README](../README.md#recorded-baseline--本次結果) includes both P50 and
P99 four-path charts. Push and ROS use the median of three run-level percentiles;
loan has one run. Its commit-to-callback latency excludes acquisition, resize and
initialization, while push reuses a prepared local message. At 128 MiB the loan
P99 is 158.708 ms for commit-to-callback and 303.336 ms for preparation-to-callback.
These are different workloads, not a claim that loan improves full-path latency.

## Reproduction and limits / 重現與限制

Use the commands in [ROS README](../ros2/README.md), then
`python3 -m tools.comparison_report RESULTS_DIRECTORY` for a Traditional Chinese
report. Each case retains commands, package/build versions, binary/source hashes,
requested XML, mapping inventory, raw observations and normalized schema v1.
Verify exact IDs and raw percentiles rather than trusting a successful process
exit alone. `tools.compare` completing means collection ended; qualification is
recorded per attempt and expected default-profile failures do not stop collection.

CPU 100% means one logical core. Publisher formal and other lifecycle intervals
differ; do not sum their percentages. RSS includes shared pages in multiple
processes and is not summed physical/private memory. No power measurements,
dedicated-machine isolation, long soak, fan-out, POD application loans, other DDS
vendors, networked hosts, native Linux or macOS evidence is provided by this run.
