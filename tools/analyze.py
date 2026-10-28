"""Analyze normalized schema v1 without importing any framework SDK."""
import argparse
import csv
import json
import math
from pathlib import Path

SCHEMA_VERSION = 1
CLOCK = "same-host-monotonic-nanoseconds"
LATENCY = "publish-entry-to-callback-entry"


def load_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def csv_rows(path, required):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or set(reader.fieldnames) != set(required):
            raise ValueError(f"Invalid columns: {path}")
        records = []
        for row in reader:
            if len(records) >= 400000:
                raise ValueError("CSV exceeds schema v1 record bound")
            if None in row or any(value is None or not value.strip() for value in row.values()):
                raise ValueError(f"Truncated or empty CSV row: {path}")
            parsed = {key: int(value) for key, value in row.items()}
            if any(not 0 <= value <= (1 << 64) - 1 for value in parsed.values()):
                raise ValueError(f"Field outside uint64 range: {path}")
            records.append(parsed)
        return records


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    result = {f"p{percent}": ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)] / 1e6
              for percent in (50, 90, 99)}
    result.update({"max": ordered[-1] / 1e6, "mean": sum(ordered) / len(ordered) / 1e6})
    return result


def validate_metadata(metadata):
    if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported normalized schema version")
    if not isinstance(metadata["build"]["configuration"], str) or not metadata["build"]["configuration"]:
        raise ValueError("Build configuration must be explicit")
    contract = metadata["contract"]
    if contract["clock"] != CLOCK or contract["latency"] != LATENCY:
        raise ValueError("Clock domain or latency boundary is incompatible with schema v1")
    if not isinstance(contract["subscriber_ownership"], str) or not contract["subscriber_ownership"]:
        raise ValueError("Subscriber ownership must be explicit")
    case = metadata["case"]
    for key in ("payload_bytes", "samples", "period_ns", "slots"):
        if type(case[key]) is not int or case[key] <= 0:
            raise ValueError(f"Invalid case {key}")
    if type(case["warmup"]) is not int or case["warmup"] < 0:
        raise ValueError("Invalid warmup")
    if case["samples"] + case["warmup"] > 200000:
        raise ValueError("Case exceeds schema v1 sample bound")
    if case["mode"] not in ("push", "loan"):
        raise ValueError("Unsupported publication path")
    if metadata["topology"] != {"publishers": 1, "subscribers": 1}:
        raise ValueError("Schema v1 supports one Publisher and one Subscriber")
    if not metadata["framework"]["name"] or not metadata["framework"]["revision"]:
        raise ValueError("Missing framework provenance")
    return case


def analyze(directory):
    directory = Path(directory)
    metadata = load_json(directory / "run.json")
    case = validate_metadata(metadata)
    tx = csv_rows(directory / "tx.csv", ("sample_id", "prepare_ns", "publish_start_ns", "publish_end_ns"))
    rx = csv_rows(directory / "rx.csv", ("sample_id", "receive_ns", "valid"))
    total = case["samples"] + case["warmup"]
    if len(tx) > total * 2 or len(rx) > total * 2:
        raise ValueError("Input record count exceeds bounded schema v1 allowance")
    errors = {}

    def record_error(name, count=1):
        if count:
            errors[name] = errors.get(name, 0) + count

    sent = {}
    received = {}
    for row in tx:
        key = row["sample_id"]
        if not 1 <= key <= total:
            record_error("unknown_send_id")
            continue
        if key in sent:
            record_error("duplicate_send_id")
            continue
        if row["publish_end_ns"] < row["publish_start_ns"]:
            record_error("negative_send_duration")
        sent[key] = row
    for row in rx:
        key = row["sample_id"]
        if row["valid"] not in (0, 1):
            raise ValueError("valid must be encoded as 0 or 1")
        if not 1 <= key <= total:
            record_error("unknown_receive_id")
            continue
        if key in received:
            record_error("duplicate_receive_id")
            continue
        received[key] = row
        if not row["valid"]:
            record_error("invalid_payload")

    record_error("missing_send", total - len(sent))
    missing = set(range(1, total + 1)) - set(received)
    record_error("missing_receive", len(missing))
    latencies = []
    full_path = []
    send_calls = []
    prepares = []
    formal_sent = []
    for key in range(1, total + 1):
        sender = sent.get(key)
        receiver = received.get(key)
        if sender and receiver and receiver["receive_ns"] < sender["publish_start_ns"]:
            record_error("negative_latency")
        if key <= case["warmup"] or not sender:
            continue
        formal_sent.append(sender)
        if sender["publish_end_ns"] >= sender["publish_start_ns"]:
            send_calls.append(sender["publish_end_ns"] - sender["publish_start_ns"])
        prepares.append(sender["prepare_ns"])
        if receiver and receiver["valid"] and receiver["receive_ns"] >= sender["publish_start_ns"]:
            elapsed = receiver["receive_ns"] - sender["publish_start_ns"]
            latencies.append(elapsed)
            full_path.append(elapsed + sender["prepare_ns"])

    intervals = [right["publish_start_ns"] - left["publish_start_ns"]
                 for left, right in zip(formal_sent, formal_sent[1:])]
    record_error("nonincreasing_send_clock", sum(value <= 0 for value in intervals))
    actual_hz = None
    if len(formal_sent) >= 2:
        span = formal_sent[-1]["publish_start_ns"] - formal_sent[0]["publish_start_ns"]
        if span > 0:
            actual_hz = (len(formal_sent) - 1) * 1e9 / span

    counters = load_json(directory / "transport.json")
    if not isinstance(counters, dict):
        raise ValueError("Transport counters must be an object")
    for name, value in counters.items():
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"Invalid transport counter: {name}")
    for name in ("collisions", "lost_messages", "overwrite_events", "excess_callbacks"):
        record_error(name, counters.get(name) or 0)
    if counters.get("published") is not None and counters["published"] != total:
        record_error("published_count_mismatch")
    if metadata.get("run_status") != "completed":
        record_error("incomplete_execution")

    resources = load_json(directory / "resources.json")
    if not isinstance(resources, list):
        raise ValueError("Resources must be an array")
    for resource in resources:
        if type(resource["valid"]) is not bool:
            raise ValueError("Resource valid flag must be a JSON boolean")
        for field in ("cpu_ns", "wall_ns", "peak_rss_bytes"):
            if type(resource[field]) is not int or resource[field] < 0:
                raise ValueError("Resource counters must be unsigned integers")
        resource["cpu_percent_one_core"] = None
        if resource["valid"]:
            if resource["wall_ns"] <= 0 or resource["cpu_ns"] < 0 or resource["peak_rss_bytes"] < 0:
                raise ValueError("Invalid resource interval")
            resource["cpu_percent_one_core"] = resource["cpu_ns"] / resource["wall_ns"] * 100

    timing = None
    timing_path = directory / "pacing.csv"
    if timing_path.exists():
        records = csv_rows(timing_path, ("sample_id", "planned_ns", "woke_ns", "skipped_after"))
        expected_ids = list(range(1, total + 1))
        if [row["sample_id"] for row in records] != expected_ids:
            raise ValueError("Pacing records must preserve every expected sample in order")
        for left, right in zip(records, records[1:]):
            if right["sample_id"] == case["warmup"] + 1:
                continue  # The formal phase starts a new grid after warmup drain.
            step = right["planned_ns"] - left["planned_ns"]
            if step != case["period_ns"] * (1 + left["skipped_after"]):
                raise ValueError("Pacing schedule violates fixed-grid contract")
        formal_ticks = records[case["warmup"]:]
        early = sum(row["woke_ns"] < row["planned_ns"] for row in formal_ticks)
        record_error("early_wake", early)
        timing = {"late_ms": distribution([max(0, row["woke_ns"] - row["planned_ns"]) for row in formal_ticks]),
                  "skipped_ticks": sum(row["skipped_after"] for row in formal_ticks[:-1])}

    return {"schema_version": SCHEMA_VERSION, "framework": metadata["framework"], "case": case,
            "qualified": not errors, "errors": errors, "expected_formal": case["samples"],
            "received_formal": sum(key > case["warmup"] for key in received),
            "valid_latency_samples": len(latencies), "missing_including_warmup": len(missing),
            "actual_hz": actual_hz, "latency_ms": distribution(latencies),
            "send_call_ms": distribution(send_calls), "prepare_ms": distribution(prepares),
            "full_path_ms": distribution(full_path), "interval_ms": distribution([value for value in intervals if value > 0]),
            "over_10_ms": sum(value > 10_000_000 for value in latencies),
            "over_15_ms": sum(value > 15_000_000 for value in latencies),
            "transport": counters, "resources": resources, "pacing": timing}


def comparable(directories, allow_pacing_difference=False):
    metadata = [load_json(Path(path) / "run.json") for path in directories]
    signatures = []
    for item in metadata:
        validate_metadata(item)
        case = item["case"]
        signatures.append({"contract": item["contract"], "topology": item["topology"],
                           "environment": item["environment"]["comparison_environment"],
                           "payload_bytes": case["payload_bytes"], "mode": case["mode"],
                           "period_ns": case["period_ns"], "slots": case["slots"],
                           "samples": case["samples"], "warmup": case["warmup"],
                           "configuration": item.get("build", {}).get("configuration"),
                           "schedule": item.get("schedule"),
                           "pacing": None if allow_pacing_difference else case["pacing"]})
    if any(signature != signatures[0] for signature in signatures[1:]):
        raise ValueError("Incompatible comparison: environment, payload, ownership, timing, topology, queue, rate or pacing differ")
    return [analyze(path) for path in directories]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--allow-pacing-difference", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        results = comparable(args.runs, args.allow_pacing_difference)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Analysis rejected: {error}\n")
    if args.output:
        if args.output.exists():
            parser.exit(2, "Refusing to overwrite analysis output\n")
        write_json(args.output, results)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(result["qualified"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
