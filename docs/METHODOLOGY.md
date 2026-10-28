# Measurement contract / 量測契約

This project measures **paced end-to-end delivery through formal framework APIs**.
It does not measure pure memcpy, maximum throughput, a network-only transport, or
hard real-time guarantees. Frameworks must be tested on the same machine/OS and
with the same workload before results are placed side by side.

本專案量測正式 API 的有節奏端到端交付成本。相同工具不自動代表公平；
相同負載、時間邊界與資料所有權才是比較的基礎。

## Work and ownership

- One Publisher Module and one Subscriber Module, each in its own Host process;
  one central process performs supervision, registration and control. Data stays
  in shared memory. Subscriber callbacks use normal `context.pumpLoop()`.
- A received message is an independently owned process-local copy. A borrowed
  shared-memory view is a different comparison profile, not equivalent work.
- Payload bytes mean the uint8 array's useful contents. Schema, sequence, framework
  metadata, image/alignment and control overhead are reported separately where
  available. Equal payload bytes do not imply equal serialized images.
- The local push message is allocated/initialized before timed publication and
  reused, with sequence updated per publication. Loan preparation includes
  get_next/resize/initialization/markers before commit. Both paths retain actual
  SDK work; neither accesses private RingBuffer layout.
- Receive timestamp is taken at callback entry, after framework copy/validation.
  Application validation checks sequence, length and edge markers, not a full hash.
  Its post-entry work is outside this sample's latency but affects subsequent load.

## Time boundaries

All cross-process timestamps use OSAL's same-host monotonic nanoseconds. No UTC,
wall-clock adjustment, or raw cross-process `steady_clock::time_point` assumption.
Pacing diagnostics use a separate process-local monotonic clock, only compared
within that Publisher.

| Metric | Start → end |
|---|---|
| latency_ms | Immediately before push/commit → first callback timestamp |
| send_call_ms | Immediately before push/commit → its return |
| prepare_ms | Begin local update or loan acquisition/fill → push/commit entry |
| full_path_ms | Prepare start → callback entry |
| interval_ms | Consecutive formal push/commit entry timestamps |
| pacing.late_ms | Planned Publisher tick → actual return from its wait |

Loan latency alone excludes its preparation: always inspect full_path_ms too.
Percentiles of separate stages must not be added. The log includes actual Hz;
requested 100 Hz is not proof that 100 Hz was achieved.

## Fixed workload and waiting

- Default matrix: 1 KiB/1 MiB/8 MiB × push/loan × three rounds, 1,000 formal
  samples after 64 warmups, eight slots, requested 100 Hz. Reverse mode order in
  alternate rounds; finish each case's shutdown before starting the next.
- Warmup requires at least two ring cycles; wait one second after warmup before
  starting the formal grid. Initial topology settling does not replace exact
  sequence checks: missing warmup samples still disqualify the case.
- Both pacing modes use a fixed monotonic grid; skip missed ticks after a send,
  record the skip, never burst to catch up. A skip is a scheduling diagnostic,
  separate from a Bus sample loss. This differs from the older Vinc benchmark's
  start-relative spacing; historical comparisons must disclose that difference.
- Standard mode uses `sleep_until`. Opt-in `windows-highres` reuses an unnamed
  high-resolution waitable timer; relative one-shot deadlines, zero requested
  tolerable delay, blocking wait, no silent fallback. No busy spin/yield,
  timeBeginPeriod, priority/affinity or global timer changes.
- The Bus shared-allocation admission budget is 4 GiB, including controls/counter,
  excluding other resources and process-local copies. Buffer/rate are fixed for
  the entire run. An overloaded run remains visible and unqualified; the suite
  does not tune it into a faster-looking workload.
- Native case deadlines, command timeouts, drain and shutdown limits are named
  constants in native/include/benchmark.hpp. Python adds an outer deadline. Cancel
  first requests orderly shutdown; only a still-stuck test central is killed,
  followed by time for Host central-loss supervision. That fallback does not
  promise zero POSIX name remnants and is never a successful measurement.

## Analysis and publication

Warmup is excluded from percentiles but included in correctness checks. Match
every expected ID, including trailing missing samples. Unknown IDs, duplicates,
invalid content, reversed clocks, transport loss/overwrites/collisions and incomplete
execution disqualify the run. Surviving latency samples remain inspectable.
Transport-specific unavailable counters are null, not fabricated zeros.

P50/P90/P99 use nearest rank `ceil(p*n)`; 1,000 samples give only about ten
upper-1% observations. Keep every attempt and publish repeat ranges, not just the
best run. Report mismatched achieved rates before making equal-load claims.

CPU uses OS user+kernel time divided by the role's recorded wall interval;
100% means one logical core. The formal Publisher window excludes warmup and
CSV writes. Other role windows include their startup/warmup/wait/drain-to-report;
do not sum percentages from different windows. Low-cost OS CPU accounting is
quantized, and a recorded zero is not proof of zero work. Peak RSS is per-process
lifetime high-water usage with shared pages counted by multiple processes;
do not sum it as physical memory or call it private memory. Power is unmeasured.

Environment fingerprints describe OS/CPU, not unique hardware identity or identical
ambient load. The operator must record version, actual setup and background load.
Compiler/standard library, Release/Debug, framework revision, source and binary
hashes belong with every published dataset. Do not run builds/tests concurrently
with timed cases. WSL evidence remains WSL evidence; macOS and native Linux need
their own validation. Do not compare Windows Vinc against Linux ROS as if only
the framework differed.

跨框架比較還須分開標示 DDS／ROS 的後端、傳輸、QoS、loan 與接收所有權。
Vinc 的覆寫歷史與複製期間 Writer 等待，不能冒稱等同 DDS 的可靠交付。
ROS 2 選配工作負載及同機校準／正式測試規則另見 [ROS 方法](../ros2/README.md)。
原生 runner 的固定矩陣不會自動調整；跨框架 controller 僅在明確標示的校準階段選擇
共同頻率，正式測試全部凍結，失敗及 100 Hz 壓力結果保留。
