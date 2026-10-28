# Native workload / 原生工作負載

driver.cpp creates the central ModuleManager with the 4 GiB admission budget,
registers the benchmark ModuleType and starts Subscriber and Publisher through
the standard ModuleHost. It waits for startup, requests go, bounds the experiment,
drains/saves the receiver, and waits for central shutdown/reaping. Manager ownership
outlives both Modules; the Publisher remains alive while the Subscriber drains.

module.cpp uses BaseModule Manual mode. Subscriber main enters context.pumpLoop;
Publisher pumps startup commands, sends its finite sequence, saves preallocated
samples after measurement, then resumes pumping until central Stop. The framework
owns control/heartbeat threads. The workload adds no background dispatch thread.
Messages come from Ribosome-generated BenchmarkFrame via the normal SDK. No direct
RingBuffer/private-layout API is used. Payload markers are application checks,
while normal framework image validation remains enabled.

Raw sent/received/publisher/subscriber/resource CSV preserve native observations.
timing.csv uses process-local monotonic ticks for pacing diagnostics. The generic
exporter in tools/run.py performs naming/unit normalization after timing, retains
raw records and does not repair missing data. File I/O is excluded from latency
samples and formal Publisher CPU, not from lifecycle windows.

PacingWaiter owns one optional unnamed Windows timer. Timer preparation failure
fails that test Module; no implicit downgrade. Its destructor closes the native
handle. Ordinary pacing blocks through standard sleep_until. Both methods use the
same monotonic grid/skip policy and never change global OS scheduling settings.
Test-specific configuration constants live in include/benchmark.hpp, independent
of framework config.hpp. Non-Windows high-resolution mode is rejected by the runner.

The original Open-VINC benchmark code is adapted under Apache-2.0; preserve the
root NOTICE. The pinned framework and its sources remain unmodified.

## Outstanding limits / 待補驗證與限制

- This first profile is one Publisher/one Subscriber. Multi-publisher ordering,
  fan-out, saturation, long soak/fault campaigns and additional frameworks are
  not validated by its paced matrix.
- POSIX cancellation fallback may leave named resource cleanup for later startup;
  a forced timeout is not a qualified run. No cleanup code deletes unrelated resources.
- Native macOS validation is pending. WSL evidence is explicitly identified.
- GCC 13 Release emits warnings in the pinned framework (aggregate initialization
  and a deadline-copy dangling-pointer diagnostic). They are not benchmark-source
  changes or verified runtime failures; separate upstream review is needed before
  labeling the latter a defect or a compiler false positive. This suite does not
  patch the dependency to hide warnings.

中央管理程序啟停，Module 只用正式 Context。錯誤或逾時保留結果並判定不合格；
量測不會改寫框架、調整全域計時器或偷偷改容量／頻率。上述未驗證範圍不得宣稱已支援。
