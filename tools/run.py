"""Run fixed-workload native Vinc cases and export normalized schema v1."""
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from . import analyze

ROOT = Path(__file__).resolve().parent.parent
PER_SAMPLE_FIELDS = ("sample_id", "prepare_ns", "publish_start_ns", "publish_end_ns")
MIB = 1024 * 1024
SHARED_BUDGET = 4 * 1024 * MIB


def write_csv(path, records, fields=None):
    if not records and fields is None:
        return
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def read_native(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return [{key: int(value) for key, value in row.items()} for row in csv.DictReader(stream)]


def processor_name():
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def invoke(command, directory, pacing, timeout):
    environment = os.environ.copy()
    environment["VINC_BENCHMARK_PACING"] = pacing
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with (directory / "driver.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=directory, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, **options)
        try:
            return process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Cancel only this experiment. The driver supervises and reaps its Hosts.
            (directory / "cancel").touch()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                time.sleep(7)  # Existing Host central-loss supervision needs time to exit.
            raise


def normalize(directory, metadata):
    raw = directory / "raw"
    tx = read_native(raw / "sent.csv")
    rx = read_native(raw / "received.csv")
    write_csv(directory / "tx.csv", [
        {"sample_id": row["sequence"], "prepare_ns": row["prepare_ns"],
         "publish_start_ns": row["begin_ns"], "publish_end_ns": row["end_ns"]} for row in tx], PER_SAMPLE_FIELDS)
    write_csv(directory / "rx.csv", [
        {"sample_id": row["sequence"], "receive_ns": row["arrival_ns"], "valid": row["valid"]} for row in rx],
        ("sample_id", "receive_ns", "valid"))
    publisher = read_native(raw / "publisher.csv")[0]
    subscriber = read_native(raw / "subscriber.csv")[0]
    if publisher["shared_bytes"] + 8 > SHARED_BUDGET:
        raise ValueError("Actual Bus shared allocation exceeds 4 GiB budget")
    analyze.write_json(directory / "transport.json", {**publisher, **subscriber})
    resources = []
    for role, filename, window in (
        ("publisher", "publisher_formal_resources.csv", "formal-publication"),
        ("publisher", "publisher_resources.csv", "lifecycle-to-report"),
        ("subscriber", "subscriber_resources.csv", "lifecycle-to-report"),
        ("central", "central_resources.csv", "lifecycle-to-report"),
    ):
        row = read_native(raw / filename)[0]
        resources.append({"role": role, "window": window, "valid": bool(row["valid"]),
                          "cpu_ns": row["cpu_ns"], "wall_ns": row["wall_ns"], "peak_rss_bytes": row["peak_rss_bytes"]})
    analyze.write_json(directory / "resources.json", resources)
    ticks = read_native(raw / "timing.csv")
    write_csv(directory / "pacing.csv", [
        {"sample_id": row["sequence"], "planned_ns": row["planned_ns"],
         "woke_ns": row["woke_ns"], "skipped_after": row["skipped_after"]} for row in ticks])
    metadata["observed_storage"] = {"shared_bytes": publisher["shared_bytes"],
                                    "image_bytes": publisher["image_bytes"], "effective_slots": publisher["slots"]}
    analyze.write_json(directory / "run.json", metadata)


def report(output, attempts):
    lines = ["# Native Vinc benchmark session", "",
             "Measured with the formal Module/Context API, shared-memory Bus and notification-driven pumpLoop.",
             "All attempts are listed. No adaptive rate reduction, capacity change, best-run selection, or silent retries.",
             "CPU 100% = one logical core. Publisher CPU below uses the formal-publication window.",
             "Subscriber/central lifecycle CPU and peak RSS are in each metrics.json; their windows differ. Do not sum RSS as physical RAM.", "",
             "| Repeat | Bytes | Mode | Pacing | Qualified | Actual Hz | P50/P90/P99 ms | Max ms | Publisher CPU % |", "|---:|---:|---|---|---|---:|---:|---:|---:|"]
    for attempt in attempts:
        result = attempt.get("metrics")
        if result and result["latency_ms"]:
            latency = result["latency_ms"]
            resource = next(row for row in result["resources"] if row["role"] == "publisher" and row["window"] == "formal-publication")
            cpu = resource["cpu_percent_one_core"]
            cpu_text = f"{cpu:.3f}" if cpu is not None else "unavailable"
            hz_text = f"{result['actual_hz']:.3f}" if result["actual_hz"] is not None else "unavailable"
            lines.append(f"| {attempt['repeat']} | {result['case']['payload_bytes']} | {result['case']['mode']} | {result['case']['pacing']} | {result['qualified']} | {hz_text} | {latency['p50']:.4f}/{latency['p90']:.4f}/{latency['p99']:.4f} | {latency['max']:.4f} | {cpu_text} |")
        else:
            lines.append(f"| {attempt['repeat']} | {attempt['payload_bytes']} | {attempt['mode']} | {attempt['pacing']} | ERROR | — | — | — | — |")
    lines += ["", "Each case retains raw native CSV, a normalized run.json/tx.csv/rx.csv/transport.json/resources.json/pacing.csv, and metrics.json.",
              "Percentiles use nearest rank, formal valid samples only. Missing/duplicate/invalid/negative-time samples or Bus collisions disqualify the run and remain visible.",
              "Loan latency starts before commit; full_path_ms additionally includes get_next/resize/fill. It is not a claim that preparing a loan is free.",
              "The native receiver validates length/sequence/edge markers, not a full payload hash. The receive endpoint includes framework copy/validation, excludes application work after callback entry.",
              "This is a paced workload, not maximum throughput, hard real time, or a guarantee of zero future tail spikes.",
              "Windows high-resolution pacing is opt-in experimental test code, not an Open-VINC framework default. WSL evidence is not native Linux deployment/performance certification."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-info", type=Path, required=True)
    parser.add_argument("--sizes-bytes", nargs="+", type=int, default=[1024, MIB, 8 * MIB])
    parser.add_argument("--modes", nargs="+", choices=["push", "loan"], default=["push", "loan"])
    parser.add_argument("--rate", type=float, default=100)
    parser.add_argument("--slots", type=int, default=8)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pacing", choices=["standard", "windows-highres"], default="standard")
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    if not 1 <= args.rate <= 100000 or not 2 <= args.slots <= 65536:
        parser.error("rate must be 1..100000 Hz and slots 2..65536")
    if not 2 <= args.samples <= 100000 or not 2 * args.slots <= args.warmup <= 100000:
        parser.error("samples must be 2..100000 and warmup must be at least two ring cycles, at most 100000")
    if not 1 <= args.repeats <= 100 or any(not 2 <= size <= 128 * MIB for size in args.sizes_bytes):
        parser.error("repeats must be 1..100, payloads 2 B..128 MiB")
    if args.pacing == "windows-highres" and os.name != "nt":
        parser.error("windows-highres is a Windows-only experiment")
    if len(set(args.sizes_bytes)) != len(args.sizes_bytes) or len(set(args.modes)) != len(args.modes):
        parser.error("Duplicate sizes or modes would repeat the same case directory")
    return args


def main():
    args = parse_args()
    info = analyze.load_json(args.build_info)
    expected_pin = (ROOT / "cmake/open-vinc-revision.txt").read_text(encoding="utf-8").strip()
    if info.get("schema_version") != 1 or info["framework_revision"] != expected_pin:
        raise ValueError("Build provenance does not match this suite's Open-VINC pin")
    executable = Path(info["executable"])
    plugin = Path(info["plugin"])
    for key in ("executable", "plugin", "host"):
        if not Path(info[key]).is_file():
            raise ValueError(f"Missing build artifact: {info[key]}")
    environment = {"system": platform.platform(), "machine": platform.machine(),
                   "processor": processor_name(), "logical_cpus": os.cpu_count(),
                   "libc": platform.libc_ver(), "python": platform.python_version()}
    # Descriptive fingerprint, not a hardware identity or proof of equal workloads.
    environment["comparison_environment"] = json.dumps({key: environment[key] for key in
        ("system", "machine", "processor", "logical_cpus")}, sort_keys=True)
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve() / datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir()  # Never reuse or overwrite an earlier experiment.
    analyze.write_json(output / "build.json", info)
    suite_commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True)
    source_paths = [ROOT / "CMakeLists.txt", ROOT / "cmake/open-vinc-revision.txt"]
    source_paths += list((ROOT / "tools").glob("*.py")) + list((ROOT / "native").rglob("*.cpp"))
    source_paths += list((ROOT / "native").rglob("*.hpp")) + list((ROOT / "native/messages").glob("*.msg"))
    analyze.write_json(output / "suite.json", {
        "revision": suite_commit.stdout.strip() if suite_commit.returncode == 0 else None,
        "sources_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted(source_paths)},
        "policy": "Source hashes identify this working tree even before the first suite commit."})
    analyze.write_json(output / "binaries.json", {key: hashlib.sha256(Path(info[key]).read_bytes()).hexdigest()
                                                for key in ("executable", "plugin", "host")})
    attempts = []
    period = round(1e9 / args.rate)
    print("Output:", output, flush=True)
    for repeat in range(1, args.repeats + 1):
        for size in args.sizes_bytes:
            for mode in (args.modes if repeat % 2 else list(reversed(args.modes))):
                directory = output / f"r{repeat}-{mode}-{size}"
                raw = directory / "raw"
                raw.mkdir(parents=True)
                metadata = {"schema_version": 1, "framework": {"name": "Open-VINC", "revision": info["framework_revision"]},
                    "environment": environment, "build": {key: info[key] for key in
                        ("configuration", "compiler", "compiler_version", "cmake_version", "system", "processor")},
                    "contract": {"clock": analyze.CLOCK, "latency": analyze.LATENCY,
                                 "subscriber_ownership": "independent-process-local-copy", "payload_validation": "length-and-edge-markers"},
                    "topology": {"publishers": 1, "subscribers": 1},
                    "transport_policy": {"data": "shared-memory", "history": "per-publisher-ring-overwrite",
                                         "reader_protection": "writer-waits-during-framework-copy",
                                         "reliable_delivery": False},
                    "case": {"payload_bytes": size, "samples": args.samples, "warmup": args.warmup,
                             "period_ns": period, "slots": args.slots, "mode": mode, "pacing": args.pacing},
                    "schedule": "fixed-monotonic-grid-skip-missed-no-burst", "run_status": "started"}
                analyze.write_json(directory / "run.json", metadata)
                command = [str(executable), str(plugin), mode, str(size), str(args.slots),
                           str(period), str(args.samples), str(args.warmup), str(raw), "1"]
                analyze.write_json(directory / "command.json", {"argv": command, "VINC_BENCHMARK_PACING": args.pacing})
                attempt = {"repeat": repeat, "payload_bytes": size, "mode": mode, "pacing": args.pacing,
                           "directory": directory.name}
                print("Start:", directory.name, flush=True)
                try:
                    timeout = (args.samples + args.warmup) * period / 1e9 * 5 + 100
                    code = invoke(command, raw, args.pacing, timeout)
                    metadata["run_status"] = "completed" if code == 0 else "failed"
                    analyze.write_json(directory / "run.json", metadata)
                    normalize(directory, metadata)
                    metrics = analyze.analyze(directory)
                    analyze.write_json(directory / "metrics.json", metrics)
                    attempt["metrics"] = metrics
                    print(f"Done: qualified={metrics['qualified']} actual_hz={metrics['actual_hz']} P99={metrics['latency_ms']['p99'] if metrics['latency_ms'] else None} ms", flush=True)
                except KeyboardInterrupt:
                    metadata["run_status"] = "cancelled"
                    analyze.write_json(directory / "run.json", metadata)
                    attempt["error"] = "cancelled"
                    attempts.append(attempt)
                    analyze.write_json(output / "attempts.json", attempts)
                    report(output, attempts)
                    return 130
                except (ValueError, OSError, KeyError, TypeError, IndexError, subprocess.TimeoutExpired) as error:
                    metadata["run_status"] = "failed"
                    analyze.write_json(directory / "run.json", metadata)
                    attempt["error"] = str(error)
                    print("Failed, evidence retained:", error, flush=True)
                attempts.append(attempt)
                analyze.write_json(output / "attempts.json", attempts)
                report(output, attempts)
    print("Report:", output / "REPORT.md", flush=True)
    return 0 if all(item.get("metrics", {}).get("qualified", False) for item in attempts) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Benchmark rejected: {error}", file=sys.stderr)
        raise SystemExit(2)
