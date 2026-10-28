# ROS 2 workload / ROS 2 工作負載

This optional, Linux-only ament package uses ordinary `rclcpp` Publishers and
Subscribers in **separate processes**. It does not wrap Vinc or copy Apex.AI
`performance_test` source. The native Vinc build remains independent of ROS.

此選配套件以正式 rclcpp API 在兩個程序收送，與 Vinc 共用時間邊界、資料驗證、
排程方式及分析器。不是 Apex.AI performance_test 的執行結果，也不是其外掛。

## Build and run / 建置與執行

Install ROS 2 Jazzy using its [official Ubuntu instructions](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).
Use Ubuntu 24.04 and a non-root account for all measurements. Required Debian packages:
`ros-jazzy-ros-base`, `ros-jazzy-rmw-fastrtps-cpp`,
`ros-jazzy-rosidl-default-generators`, `python3-colcon-common-extensions`.
No desktop/GUI, Python ROS client, or ROS daemon is needed by the workload.

```sh
# From this repository's root, with GCC 13, CMake, Ninja and ROS installed:
source /opt/ros/jazzy/setup.bash
CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --base-paths ros2 \
  --build-base build/ros-build --install-base build/ros-install \
  --executor sequential --cmake-args -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=g++-13

python3 -m tools.ros \
  --exe build/ros-install/open_vinc_benchmark_ros/lib/open_vinc_benchmark_ros/ros_benchmark \
  --setup build/ros-install/setup.bash --profile datasharing \
  --bytes 1048576 --slots 32 --samples 1000 --warmup 64 --rate 100
```

Build configuration/compiler versions come from CMake's installed `ros-build.json`,
not executable-name inference. Every case saves binary SHA256, installed middleware
package versions, commands, requested XML, raw observations and normalized records.
Do not build or run another benchmark concurrently with a measurement.

## Explicit profiles / 明確區分設定

| Profile | API QoS / payload transport | Schema / Data Sharing |
|---|---|---|
| `default` | KeepLast(depth), RELIABLE; middleware transport defaults, no forced transport | Unbounded byte sequence; Jazzy RMW default Data Sharing OFF |
| `shm` | KeepLast(depth), BEST_EFFORT; SHM-only, enlarged transport segment/message limit | Unbounded byte sequence; Data Sharing OFF |
| `datasharing` | KeepLast(depth), BEST_EFFORT; SHM-only discovery/control transport | Per-size **bounded** byte sequence; Data Sharing **ON**, private mapping directory |

Both tuned profiles specify synchronous publication, PREALLOCATED_WITH_REALLOC,
bounded history resources and one extra sample. XML config is passed through
`FASTRTPS_DEFAULT_PROFILES_FILE` and `RMW_FASTRTPS_USE_QOS_FROM_XML=1`.
The former spelling is required by installed Fast DDS 2.14. A newer `FASTDDS_`
spelling is silently ignored by that version. Ambient DDS tuning is cleared.

Only the benchmark topic gets Data Sharing ON: ROS's own unbounded management
messages retain OFF. ON rejects incompatible types instead of silently falling
back. The controller additionally requires and inventories the private mapping
files while both processes are alive. Resource limits must account for serialized
size, metadata and the extra sample; 128 MiB at depth 31 exceeds Fast DDS 2.14's
uint32 segment limit, so the comparison uses depth 30 at that size.

ROS 設定不等於 Vinc 的交付契約：預設 RELIABLE 與調校後 BEST_EFFORT 分開呈現；
Vinc 仍是覆寫歷史及受保護複製期間等待。相同 queue 深度也不代表相同記憶體使用量。
Data Sharing 共用 DDS 歷史資料，與一般 SHM transport 不同。

## Ownership, timing and lifecycle / 所有權、時間與生命週期

- Publish reuses a preinitialized process-local vector and calls `publish(*message)`.
  No application loan, `ROS_DISABLE_LOANED_MESSAGES=1`, intra-process routing disabled.
- Receive uses the typed `Message::SharedPtr` callback, owning an independent local
  copy. It records CLOCK_MONOTONIC at callback entry, then validates size/sequence/
  boundary markers. No borrowed shared view is substituted for a local copy.
- SharedPtr here shares ownership **within the Subscriber process**, not DDS
  shared-memory payload. RMW message loans remain disabled. Installed Jazzy rclcpp
  dispatch converts its local SharedPtr to a new allocated/copied message for a
  UniquePtr callback; that unnecessary extra copy is excluded from the primary
  comparison. Earlier UniquePtr diagnostic runs remain archived and are not
  mixed into the final SharedPtr dataset.
- Data Sharing is **not an end-to-end zero-copy claim**. Bounded vectors permit
  shared DDS history but are not plain fixed-layout loanable message types.
- Both endpoints must observe matching before sample 1. Warmup is at least two
  queue cycles, followed by one second drain. Missing warmup samples still fail.
- Fixed monotonic grid, skip missed ticks, no busy-spin or catch-up bursts. Same
  rule as Vinc. All CSV writes occur outside timed sample collection.
- Writer remains alive until the reader drains. Discovery, collection, drain and
  shutdown have controller deadlines. SIGINT unblocks ROS spin so partial Rx data
  can be saved. Cleanup targets only owned PIDs and the unique private mapping path.
- DDS collision/overwrite/internal-loss counters are **unavailable/null** here;
  exact sent/received IDs detect end-to-end loss. Null is not evidence of zero DDS
  internal drops or reliable delivery.

## Comparison controller / 對照控制器

```sh
python3 -m tools.compare \
  --build-info build/release/benchmark-build-Release.json \
  --ros-exe build/ros-install/open_vinc_benchmark_ros/lib/open_vinc_benchmark_ros/ros_benchmark \
  --ros-setup build/ros-install/setup.bash
```

Default matrix: 1 KiB, 1/8/16/32/64/128 MiB; 1,000 formal samples × three
alternating-order repeats. Ring depth is enlarged to 32, or 30 at 128 MiB,
with native actual shared allocation checked against 4 GiB. This is a Bus admission
budget, not a total RSS cap or a DDS total-memory promise.

Predeclared profile selection prefers verified Data Sharing; explicit SHM is a
fallback only if its pilot qualifies. All pilots remain visible. Then Vinc push
and tuned ROS start calibration at 100 Hz, stepping through 50/25/10/5/2/1 Hz
only if complete delivery, zero Vinc collision/loss and ±5% achieved-rate checks
fail. Calibration uses 128 formal pilot samples and also requires P90 within four
periods and half-to-half median latency growth within one period, to avoid a short
pilot hiding sustained queue buildup. These are pilot headroom rules, not framework
latency guarantees or formal outlier rejection. Formal runs freeze the chosen
rate/depth and are never silently retried.
Default ROS is also measured at that same rate, but does not choose the rate for
the optimized comparison. Failed 100 Hz pilots are pressure evidence, not hidden.
One additional Vinc loan run per size is separate from normal ROS publish.

`attempts.json` includes **every** case, validity, effective rate, memory guard,
errors and raw paths. Calibration success does not guarantee later formal success.
Any failed formal remains failed. CPU/memory windows follow the common schema.

比較先校準，再固定參數正式測試。保留全部試跑與失敗；不拿最佳一輪當整體成績。
比較控制器每 250 ms 檢查 WSL 可用記憶體；低於 1 GiB 或交換空間增加超過
512 MiB 時中止該次測試並保留診斷。這只保護本機，不調整 OS 的記憶體或排程設定。

## Limits / 限制

Only rmw_fastrtps_cpp/Jazzy on the recorded WSL environment is validated. This is
not a claim about all ROS distributions, DDS vendors, networks, real-time kernels,
fan-out, CPU affinity, loaned POD messages or native Linux deployment performance.
The ROS package is not part of Windows native CTest. Payload checking is not a
full hash. External library/allocator exceptions are contained at the executable
boundary, diagnosed and counted as failed runs.

The mutable SharedPtr callback is supported by the recorded Jazzy build but is
marked deprecated upstream. It deliberately preserves mutable local-message
ownership for this profile. A future ROS-version migration should evaluate a
ConstSharedPtr profile explicitly; neither shape borrows the DDS mapping when
RMW loans are disabled. See the recorded-version
[dispatch implementation](https://github.com/ros2/rclcpp/blob/28.1.22/rclcpp/include/rclcpp/any_subscription_callback.hpp).

References: [Jazzy rmw_fastrtps configuration](https://github.com/ros2/rmw_fastrtps/blob/jazzy/README.md),
[Fast DDS Data Sharing](https://fast-dds.docs.eprosima.com/en/2.x/fastdds/transport/datasharing.html),
[SHM transport](https://fast-dds.docs.eprosima.com/en/2.x/fastdds/transport/shared_memory/shared_memory.html).
