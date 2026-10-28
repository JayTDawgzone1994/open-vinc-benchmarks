# Validation record / 驗證紀錄

Date: 2026-10-28, Asia/Taipei. Tested framework revision:
`a3a0843c5dc89f8b052c5f25afa66e1f171db99e`.
The measurements were taken before this benchmark repository's first commit;
session suite.json therefore records source SHA256 rather than a suite commit.
Framework source and pacing were unchanged throughout the measurements.

## Environments and checks

| Environment | Tools | Checks |
|---|---|---|
| Windows 11 x64 10.0.26200, Ryzen 7 5700X3D, 16 logical CPUs | MSVC 19.51.36257 / toolset 14.51.36231, CMake 4.3.2, Ninja 1.13.2; native CPython 3.13.12 for CTest, MINGW Python 3.14.4 for the formal runner | Release build passed; final CTest **3/3**, including 18 analyzer unit cases, standard push/loan smoke and Windows-highres push/loan smoke |
| WSL2 Ubuntu 24.04.5 x86_64, Linux 6.18.54.1-microsoft-standard-WSL2, same CPU allocation | GCC/libstdc++ 13.3, glibc 2.39, CMake 3.28.3, Ninja 1.11.1, Python 3.12.3 | Release build passed; final CTest **2/2**, including the same 18 unit cases and native push/loan smoke |

The analyzer checks known percentile results, warmup exclusion, trailing loss,
duplicate/unknown IDs, invalid warmup payload, reversed timestamps, nonincreasing
publish clocks, truncated CSV, incompatible clocks/schema, uint64 bounds, resource
validity, fixed-grid pacing, incomplete execution and comparison mismatches.
A synthetic second framework passes the same contract without importing Vinc;
borrowed ownership, another OS, Debug-vs-Release and implicit pacing differences
are rejected. Actual same-profile CLI comparison passed; actual Windows-vs-WSL
comparison was rejected with exit 2.

LICENSE/NOTICE copies in both build directories match the root by SHA256.
Final inspection found no remaining benchmark/ModuleHost processes. The pinned
Open-VINC checkout remains clean. GCC warnings in upstream are recorded in the
[native limitations](../native/README.md#outstanding-limits--待補驗證與限制).

After measurement, changes were limited to configure-time copying of suite notices
and stricter invalid-input checks in the analyzer. All 36 runs were reanalyzed
with the final analyzer and reproduced their stored metrics exactly. Independent
raw-CSV checks recomputed P50/P90/P99, every sequence/content flag, shared budget,
and collision/loss/overwrite counts. Native source and pacing did not change.

## First native matrix / 第一輪原生矩陣

Each environment: 1 KiB/1 MiB/8 MiB × push/loan × three rounds, eight slots,
requested 100 Hz, 64 warmups + 1,000 formal samples. Standard pacing only for the
formal matrix; Windows-highres was functionally smoke-tested, not substituted into
these baseline numbers. All 18 runs per environment qualified: **36,000 formal +
2,304 warmup messages**, no missing IDs, duplicate/unknown IDs, invalid markers,
collisions, lost messages or overwrite events. These are paced tests, not saturation.

The tables summarize validation observations. The full raw datasets remain local
and ignored; they have not been published as a standalone performance dataset.
Before citing these externally as a published benchmark, archive/distribute the
raw evidence, provenance and source/binary hashes as well. Normal interactive
desktop conditions apply, with no agent-started build/test concurrent with timing.

### Windows observations (standard pacing)

| Payload | Path | Three-round P99 range ms |
|---|---|---:|
| 1 KiB | push | 0.0757–0.0985 |
| 1 KiB | loan | 0.0669–0.0799 |
| 1 MiB | push | 0.5559–0.7588 |
| 1 MiB | loan | 0.4285–0.5928 |
| 8 MiB | push | 2.8949–3.1979 |
| 8 MiB | loan | 2.0472–2.2010 |

Actual rate: approximately 64 Hz. No timer-resolution/priority/affinity tuning.
Loan P99 starts at commit; preparation is additionally recorded in full_path_ms.

### WSL observations (standard pacing)

| Payload | Path | Three-round P99 range ms |
|---|---|---:|
| 1 KiB | push | 0.0921–0.1051 |
| 1 KiB | loan | 0.0668–0.1106 |
| 1 MiB | push | 0.4150–0.4744 |
| 1 MiB | loan | 0.2137–0.3001 |
| 8 MiB | push | 2.4619–2.8601 |
| 8 MiB | loan | 1.3447–1.4412 |

Actual rate: approximately 100 Hz. Different OS/scheduler/achieved load, so these
tables must not be interpreted as an isolated compiler or framework speedup.

Local evidence (relative to this checkout, not versioned):

- `build/windows-formal/20261028-205150-104815/`
- `build/wsl-formal/20261028-205810-405686/`
- Each session: REPORT.md, attempts.json, build.json, binaries.json, suite.json,
  per-case raw and normalized data, metrics.json, verification.json.
- Windows functional logs: `build/windows-build.log`, `build/windows-test.log`.
- WSL functional logs: `/home/vinc-test/build/benchmarks-build.log` and
  `/home/vinc-test/build/benchmarks-test.log`.

## Outstanding coverage / 尚待驗證

- Native macOS and native Linux execution of this independent suite.
- Other frameworks and their normalized exporters; no ROS/DDS score is claimed.
- Full byte-wise payload hashes, multi-Publisher/fan-out profiles, saturation,
  long-duration soak, fault campaigns, pure idle CPU and power measurements.
- Windows highres at the entire formal matrix; only its smoke path is included
  in this suite's initial validation. Earlier local timer experiments are separate.

兩個環境皆完成正式 API 的原生收送與共用分析器驗證，原始紀錄可重算且保留。
本表不構成跨框架排名、硬即時保證，也不把 WSL 當成原生 Linux 的部署驗證。
