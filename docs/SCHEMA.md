# Normalized input schema v1 / 共用輸入格式

The analyzer depends only on Python's standard library. Another framework can
export this contract without linking Vinc or copying its native test code.
No importer for Apex's summary CSV is provided: an average/stddev/min/max table
cannot reconstruct the original P90/P99. An adapter needs per-message samples,
or a separately designed histogram schema; it must not invent missing values.

## Directory and metadata

Each normalized run contains `run.json`, `tx.csv`, `rx.csv`, `transport.json`,
`resources.json`, and optional `pacing.csv`. Native evidence is retained in raw/.
The runner adds command.json and metrics.json. Session files retain compiler/build
provenance, binary SHA256, suite revision (null before first commit), source hashes,
all attempts and a readable report. Initial validation before the first suite
commit is identified by source hashes, never attributed to a nonexistent commit.

Required run.json shape:

```json
{
  "schema_version": 1,
  "framework": {"name": "FrameworkName", "revision": "exact-version-or-commit"},
  "environment": {"comparison_environment": "documented-same-machine-and-os"},
  "build": {"configuration": "Release"},
  "contract": {
    "clock": "same-host-monotonic-nanoseconds",
    "latency": "publish-entry-to-callback-entry",
    "subscriber_ownership": "independent-process-local-copy",
    "payload_validation": "length-and-edge-markers"
  },
  "topology": {"publishers": 1, "subscribers": 1},
  "case": {
    "payload_bytes": 1024, "samples": 1000, "warmup": 64,
    "period_ns": 10000000, "slots": 8,
    "mode": "push", "pacing": "standard"
  },
  "schedule": "fixed-monotonic-grid-skip-missed-no-burst",
  "run_status": "completed"
}
```

Add actual OS/CPU/compiler/library/configuration details, framework-specific
transport/QoS policies and limitations. The native exporter includes these fields;
comparison checks build configuration and schedule as well as the required
contract/case/environment. It does not prove a backend's implementation matches
its metadata. Missing policy information must be disclosed, not assumed equivalent.

Schema v1 is one Publisher/one Subscriber. IDs are 1..warmup+samples; warmup IDs
are first. Each expected send must exist; missing receives are missing rows.
Keep duplicate/unknown receive rows so the analyzer can reject them. Do not write
fake timestamps for missing messages. The native CLI supports at most 100,000
formal and 100,000 warmup samples; normalized v1 caps total expected IDs at 200,000
and bounds CSV records to prevent unbounded accumulation.

## CSV fields

All times/durations are unsigned integer nanoseconds; no float or scientific notation.
Fields must fit uint64. Headers must match exactly. Record ordering is retained;
no silent deduplication. Build configuration must be explicit.

| File | Header |
|---|---|
| tx.csv | sample_id,prepare_ns,publish_start_ns,publish_end_ns |
| rx.csv | sample_id,receive_ns,valid |
| pacing.csv | sample_id,planned_ns,woke_ns,skipped_after |

rx.valid is 0/1. A consumer callback can run before publish returns, so receive_ns
may be less than publish_end_ns; only receive_ns < publish_start_ns is negative
latency. Preparation is a duration, not a timestamp to compare across clocks.
Pacing timestamps are process-local; the formal phase starts a fresh grid after
warmup. Consecutive grid steps equal period_ns*(1+previous.skipped_after).

## Counters and resources

transport.json is an object of nonnegative integer counters, or null if unavailable.
Recognized qualification fields are published, collisions, lost_messages,
overwrite_events and excess_callbacks. Native storage sizes/wait durations are
retained as additional fields. An absent/null collision counter from another
framework means unavailable, not proven collision-free.

resources.json is an array:

```json
[
  {
    "role": "publisher", "window": "formal-publication", "valid": true,
    "cpu_ns": 1000000, "wall_ns": 1000000000, "peak_rss_bytes": 1048576
  }
]
```

valid is a JSON boolean. A valid interval requires wall_ns > 0 and nonnegative
integer counters. Invalid acquisition remains valid:false with CPU percentage
null, rather than a fabricated 0%. Memory remains lifetime peak, even when CPU's
window is formal. Separate roles/windows; see methodology before comparing costs.

The analyzer rejects malformed schema, truncated rows, incompatible clocks and
incorrect pacing grids. It returns qualification errors for complete but faulty
measurements; it still reports their surviving samples. CLI exit 0 means all runs
qualified, 1 means a measurement was unqualified, and 2 means rejected input.

中文摘要：共用格式明定時間邊界、所有權、樣本與資源單位，不依賴特定框架。
其他工具只有平均值時，不能推算百分位。借用共享資料、不同 OS 或不同負載必須分開，
不得以相同欄位名稱冒充相同實驗。
