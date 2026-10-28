"""ROS 2 rclcpp owned-copy workload and normalized exporter (Linux/WSL)."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from . import analyze
from . import run as native

PACKAGES = ("ros-jazzy-rclcpp", "ros-jazzy-rmw-fastrtps-cpp", "ros-jazzy-fastrtps", "ros-jazzy-fastcdr")
DISCOVERY_SECONDS = 40
DRAIN_SECONDS = 5
EXIT_SECONDS = 15
MIB = 1024 * 1024


def environment(setup):
    prepared = subprocess.check_output(["bash", "-c", f"source {shlex.quote(str(setup))} && env -0"])
    result = os.environ.copy()
    for item in prepared.decode().split("\0"):
        if "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    # Make the declared profile independent of ambient DDS tuning.
    for key in ("FASTDDS_DEFAULT_PROFILES_FILE", "FASTRTPS_DEFAULT_PROFILES_FILE", "RMW_FASTRTPS_USE_QOS_FROM_XML",
                "RMW_FASTRTPS_PUBLICATION_MODE", "FASTDDS_BUILTIN_TRANSPORTS", "ROS_DISCOVERY_SERVER", "ROS_LOCALHOST_ONLY",
                "ROS_AUTOMATIC_DISCOVERY_RANGE", "ROS_STATIC_PEERS"):
        result.pop(key, None)
    result.update({"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp", "ROS_DOMAIN_ID": "117",
                   "ROS_DISABLE_LOANED_MESSAGES": "1", "RCUTILS_COLORIZED_OUTPUT": "0"})
    return result


def tuning_xml(profile, payload, slots, shared_dir, topic="/benchmark"):
    if profile not in ("shm", "datasharing"):
        raise ValueError("XML profile must be shm or datasharing")
    max_message = max(65536, payload + 65536) if profile == "shm" else 65536
    segment = max(64 * MIB, max_message * min(slots, 4) + MIB)
    data_sharing = "ON" if profile == "datasharing" else "OFF"
    resource = f"""<topic><historyQos><kind>KEEP_LAST</kind><depth>{slots}</depth></historyQos>
      <resourceLimitsQos><max_samples>{slots}</max_samples><max_instances>1</max_instances>
      <max_samples_per_instance>{slots}</max_samples_per_instance><allocated_samples>1</allocated_samples>
      <extra_samples>1</extra_samples></resourceLimitsQos></topic>"""
    sharing = f"<data_sharing><kind>{data_sharing}</kind><shared_dir>{shared_dir}</shared_dir></data_sharing>"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors><transport_descriptor><transport_id>benchmark_shm</transport_id><type>SHM</type>
    <maxMessageSize>{max_message}</maxMessageSize><segment_size>{segment}</segment_size>
    <port_queue_capacity>{max(512, slots * 4)}</port_queue_capacity></transport_descriptor></transport_descriptors>
  <participant profile_name="benchmark_participant" is_default_profile="true"><rtps>
    <userTransports><transport_id>benchmark_shm</transport_id></userTransports><useBuiltinTransports>false</useBuiltinTransports>
  </rtps></participant>
  <data_writer profile_name="safe_default_writer" is_default_profile="true">
    <qos><data_sharing><kind>OFF</kind></data_sharing><publishMode><kind>SYNCHRONOUS</kind></publishMode></qos>
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy></data_writer>
  <data_reader profile_name="safe_default_reader" is_default_profile="true">
    <qos><data_sharing><kind>OFF</kind></data_sharing></qos>
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy></data_reader>
  <data_writer profile_name="{topic}">{resource}
    <qos>{sharing}<publishMode><kind>SYNCHRONOUS</kind></publishMode></qos>
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy></data_writer>
  <data_reader profile_name="{topic}">{resource}
    <qos>{sharing}</qos><historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy></data_reader>
</profiles>
"""
    ET.fromstring(xml)
    return xml, {"segment_bytes_per_participant": segment, "max_transport_message_bytes": max_message,
                 "data_sharing": data_sharing, "resource_max_samples": slots, "extra_samples": 1,
                 "publication": "SYNCHRONOUS", "memory_policy": "PREALLOCATED_WITH_REALLOC",
                 "transport": "SHM-only", "reliability": "BEST_EFFORT"}


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_file(path, processes, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists():
            return True
        if any(process.poll() not in (None, 0) for process in processes):
            return False
        time.sleep(0.02)
    return False


def invoke(args, raw, env):
    common = [args.profile, str(args.bytes), str(args.slots), str(args.period_ns), str(args.samples),
              str(args.warmup), "owned-copy", str(raw), args.topic]
    commands = [[str(args.exe), role, *common] for role in ("subscriber", "publisher")]
    analyze.write_json(raw / "commands.json", {"argv": commands,
        "environment": {key: env[key] for key in ("RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "ROS_DISABLE_LOANED_MESSAGES")}})
    processes = []
    streams = []
    try:
        for role, command in zip(("subscriber", "publisher"), commands):
            stream = (raw / f"{role}.log").open("w", encoding="utf-8")
            streams.append(stream)
            processes.append(subprocess.Popen(command, cwd=raw, env=env, stdout=stream, stderr=subprocess.STDOUT))
        subscriber, publisher = processes
        if not wait_file(raw / "publisher_ready", processes, DISCOVERY_SECONDS):
            raise RuntimeError("ROS startup/discovery failed; inspect raw publisher/subscriber logs")
        if not wait_file(raw / "subscriber_ready", processes, DISCOVERY_SECONDS):
            raise RuntimeError("ROS reciprocal discovery failed; inspect raw logs")
        # Observe the exact private data-sharing mappings while both roles live.
        if args.shared_dir:
            mappings = [{"name": path.name, "bytes": path.stat().st_size}
                        for path in args.shared_dir.iterdir() if path.is_file()]
            analyze.write_json(raw / "shared_files.json", mappings)
            if args.profile == "datasharing" and not mappings:
                raise RuntimeError("Data Sharing ON did not create its required private mapping")
        (raw / "go").touch()
        timeout = (args.samples + args.warmup) * args.period_ns / 1e9 * 5 + 100
        if not wait_file(raw / "publisher_done", processes, timeout):
            raise RuntimeError("ROS Publisher failed or exceeded measurement deadline")
        if not wait_file(raw / "subscriber_done", processes, DRAIN_SECONDS):
            stop(subscriber)  # Graceful signal unblocks spin and saves incomplete Rx data.
        (raw / "finish").touch()
        codes = [process.wait(timeout=EXIT_SECONDS) for process in processes]
        analyze.write_json(raw / "exit_codes.json", codes)
        return all(code == 0 for code in codes)
    finally:
        (raw / "finish").touch()
        for process in processes:
            stop(process)
        for stream in streams:
            stream.close()


def normalize(directory, metadata):
    raw = directory / "raw"
    tx = native.read_native(raw / "sent.csv")
    rx = native.read_native(raw / "received.csv")
    native.write_csv(directory / "tx.csv", [{"sample_id": row["sequence"], "prepare_ns": row["prepare_ns"],
        "publish_start_ns": row["begin_ns"], "publish_end_ns": row["end_ns"]} for row in tx], native.PER_SAMPLE_FIELDS)
    native.write_csv(directory / "rx.csv", [{"sample_id": row["sequence"], "receive_ns": row["arrival_ns"],
        "valid": row["valid"]} for row in rx], ("sample_id", "receive_ns", "valid"))
    publisher = native.read_native(raw / "publisher.csv")[0]
    subscriber = native.read_native(raw / "subscriber.csv")[0]
    analyze.write_json(directory / "transport.json", {"published": publisher["published"],
        "collisions": None, "lost_messages": None, "overwrite_events": None,
        "excess_callbacks": subscriber["excess_callbacks"]})
    resources = []
    for role, filename, window in (
        ("publisher", "publisher_formal_resources.csv", "formal-publication"),
        ("publisher", "publisher_resources.csv", "lifecycle-to-report"),
        ("subscriber", "subscriber_resources.csv", "lifecycle-to-report"),
    ):
        row = native.read_native(raw / filename)[0]
        resources.append({"role": role, "window": window, "valid": bool(row["valid"]),
            "cpu_ns": row["cpu_ns"], "wall_ns": row["wall_ns"], "peak_rss_bytes": row["peak_rss_bytes"]})
    analyze.write_json(directory / "resources.json", resources)
    ticks = native.read_native(raw / "timing.csv")
    native.write_csv(directory / "pacing.csv", [{"sample_id": row["sequence"], "planned_ns": row["planned_ns"],
        "woke_ns": row["woke_ns"], "skipped_after": row["skipped_after"]} for row in ticks])
    analyze.write_json(directory / "run.json", metadata)


def run_case(args, directory):
    raw = directory / "raw"
    raw.mkdir(parents=True)
    env = environment(args.setup)
    packages = subprocess.check_output(["dpkg-query", "-W", *PACKAGES], text=True).strip()
    host = {"system": __import__("platform").platform(), "machine": __import__("platform").machine(),
            "processor": native.processor_name(), "logical_cpus": os.cpu_count(),
            "libc": __import__("platform").libc_ver(), "python": __import__("platform").python_version()}
    host["comparison_environment"] = json.dumps({key: host[key] for key in
        ("system", "machine", "processor", "logical_cpus")}, sort_keys=True)
    args.shared_dir = None
    args.topic = "/benchmark_" + uuid.uuid4().hex
    policy = {"transport": "middleware-default-not-forced", "data_sharing": "RMW-default-OFF",
              "reliability": "RELIABLE", "memory_policy": "RMW-default-PREALLOCATED_WITH_REALLOC"}
    if args.profile != "default":
        args.shared_dir = Path("/dev/shm") / ("vinc-ros-benchmark-" + uuid.uuid4().hex)
        args.shared_dir.mkdir(mode=0o700)
        xml, policy = tuning_xml(args.profile, args.bytes, args.slots, args.shared_dir, args.topic)
        profile_path = raw / "fastdds.xml"
        profile_path.write_text(xml, encoding="utf-8")
        # Fast DDS 2.x uses the historical FASTRTPS variable name. A newer
        # FASTDDS spelling is silently ignored by the installed Jazzy backend.
        env["FASTRTPS_DEFAULT_PROFILES_FILE"] = str(profile_path)
        env["RMW_FASTRTPS_USE_QOS_FROM_XML"] = "1"
    metadata = {"schema_version": 1, "framework": {"name": "ROS 2 Jazzy / Fast DDS / " + args.profile, "revision": packages},
        "environment": host, "build": analyze.load_json(args.exe.parents[2] / 'share/open_vinc_benchmark_ros/ros-build.json'),
        "contract": {"clock": analyze.CLOCK, "latency": analyze.LATENCY,
                     "subscriber_ownership": "independent-process-local-copy", "payload_validation": "length-and-edge-markers"},
        "topology": {"publishers": 1, "subscribers": 1},
        "case": {"payload_bytes": args.bytes, "samples": args.samples, "warmup": args.warmup,
                 "period_ns": args.period_ns, "slots": args.slots, "mode": "push", "pacing": "standard"},
        "schedule": "fixed-monotonic-grid-skip-missed-no-burst", "transport_policy": policy,
        "message_schema": "per-size-bounded-sequence" if args.profile == "datasharing" else "unbounded-sequence",
        "application_callback": "mutable-SharedPtr-owning-process-local-message-no-RMW-loan",
        "run_status": "started"}
    analyze.write_json(directory / "run.json", metadata)
    analyze.write_json(directory / "binary.json", {"path": str(args.exe), "sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest()})
    try:
        good = invoke(args, raw, env)
        metadata["run_status"] = "completed" if good else "failed"
        normalize(directory, metadata)
        result = analyze.analyze(directory)
        analyze.write_json(directory / "metrics.json", result)
        return result
    except BaseException:
        metadata["run_status"] = "failed"
        analyze.write_json(directory / "run.json", metadata)
        raise
    finally:
        if args.shared_dir:
            # All owned test PIDs have been reaped before removing only our private
            # mapping directory. Never clean global Fast DDS or other users' files.
            assert args.shared_dir.parent == Path("/dev/shm") and args.shared_dir.name.startswith("vinc-ros-benchmark-")
            shutil.rmtree(args.shared_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--profile", choices=["default", "shm", "datasharing"], default="default")
    parser.add_argument("--bytes", type=int, default=1024)
    parser.add_argument("--slots", type=int, default=32)
    parser.add_argument("--rate", type=float, default=100)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=64)
    parser.add_argument("--output", type=Path, default=Path("results/ros"))
    args = parser.parse_args()
    if not 2 <= args.bytes <= 128 * MIB or not 2 <= args.slots <= 65536 or not 1 <= args.rate <= 100000:
        parser.error("Invalid payload, queue depth or rate")
    if not 2 <= args.samples <= 100000 or not 2 * args.slots <= args.warmup <= 100000:
        parser.error("Invalid sample/warmup count")
    if args.profile == "datasharing" and args.bytes not in (1024, MIB, 8*MIB, 16*MIB, 32*MIB, 64*MIB, 128*MIB):
        parser.error("No bounded schema for this size")
    args.exe = args.exe.resolve(strict=True)
    args.setup = args.setup.resolve(strict=True)
    args.period_ns = round(1e9 / args.rate)
    directory = args.output.resolve() / datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    print("Output:", directory, flush=True)
    try:
        result = run_case(args, directory)
        print(f"Qualified={result['qualified']} Hz={result['actual_hz']} P99={result['latency_ms']['p99'] if result['latency_ms'] else None}", flush=True)
        return 0 if result["qualified"] else 1
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("ROS case failed, evidence retained:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
