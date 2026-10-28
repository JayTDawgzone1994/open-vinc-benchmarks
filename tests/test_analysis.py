import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools import analyze


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.metadata = {"schema_version": 1, "framework": {"name": "FixtureTransport", "revision": "test-revision"},
            "build": {"configuration": "Release"},
            "environment": {"comparison_environment": "same-host-same-os"},
            "contract": {"clock": analyze.CLOCK, "latency": analyze.LATENCY,
                         "subscriber_ownership": "independent-process-local-copy", "payload_validation": "length-and-edge-markers"},
            "topology": {"publishers": 1, "subscribers": 1},
            "case": {"samples": 3, "warmup": 1, "payload_bytes": 1024, "mode": "push", "period_ns": 10000000,
                     "slots": 8, "pacing": "standard"}, "run_status": "completed"}
        self.tx = [{"sample_id": index, "prepare_ns": 500000,
                    "publish_start_ns": 1000000000 + index * 10000000,
                    "publish_end_ns": 1000000000 + index * 10000000 + 100000}
                   for index in range(1, 5)]
        latencies = [99000000, 1000000, 3000000, 2000000]
        self.rx = [{"sample_id": index, "receive_ns": self.tx[index - 1]["publish_start_ns"] + latencies[index - 1], "valid": 1}
                   for index in range(1, 5)]
        self.write_fixture(self.root)

    def write_fixture(self, directory, metadata=None):
        directory.mkdir(exist_ok=True)
        analyze.write_json(directory / "run.json", metadata or self.metadata)
        for name, values in (("tx", self.tx), ("rx", self.rx)):
            with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
        analyze.write_json(directory / "transport.json", {"published": 4, "collisions": 0, "lost_messages": 0, "overwrite_events": 0})
        analyze.write_json(directory / "resources.json", [
            {"role": "publisher", "window": "formal-publication", "valid": True,
             "cpu_ns": 1000000, "wall_ns": 1000000000, "peak_rss_bytes": 1024}])

    def test_exact_percentiles_exclude_warmup_and_include_preparation(self):
        result = analyze.analyze(self.root)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["latency_ms"]["p50"], 2)
        self.assertEqual(result["latency_ms"]["p90"], 3)
        self.assertEqual(result["latency_ms"]["p99"], 3)
        self.assertEqual(result["full_path_ms"]["p99"], 3.5)
        self.assertAlmostEqual(result["actual_hz"], 100)
        self.assertAlmostEqual(result["resources"][0]["cpu_percent_one_core"], 0.1)

    def test_trailing_missing_sample_is_not_hidden(self):
        self.rx.pop()
        self.write_fixture(self.root)
        result = analyze.analyze(self.root)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["errors"]["missing_receive"], 1)
        self.assertEqual(result["received_formal"], 2)

    def test_duplicate_and_unknown_ids_disqualify(self):
        self.rx.append(dict(self.rx[1]))
        self.rx.append({"sample_id": 100, "receive_ns": 2000000000, "valid": 1})
        self.write_fixture(self.root)
        result = analyze.analyze(self.root)
        self.assertEqual(result["errors"]["duplicate_receive_id"], 1)
        self.assertEqual(result["errors"]["unknown_receive_id"], 1)
        self.assertFalse(result["qualified"])

    def test_invalid_warmup_remains_a_failure(self):
        self.rx[0]["valid"] = 0
        self.write_fixture(self.root)
        result = analyze.analyze(self.root)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["errors"]["invalid_payload"], 1)

    def test_negative_latency_is_excluded_and_reported(self):
        self.rx[-1]["receive_ns"] = self.tx[-1]["publish_start_ns"] - 1
        self.write_fixture(self.root)
        result = analyze.analyze(self.root)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["errors"]["negative_latency"], 1)
        self.assertEqual(result["valid_latency_samples"], 2)

    def test_collisions_and_overwrites_disqualify_even_if_all_received(self):
        analyze.write_json(self.root / "transport.json", {"collisions": 2, "overwrite_events": 1, "published": 4})
        result = analyze.analyze(self.root)
        self.assertEqual(result["errors"]["collisions"], 2)
        self.assertEqual(result["errors"]["overwrite_events"], 1)
        self.assertFalse(result["qualified"])

    def test_truncated_csv_is_rejected(self):
        (self.root / "rx.csv").write_text("sample_id,receive_ns,valid\n1,123\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Truncated"):
            analyze.analyze(self.root)

    def test_unknown_schema_and_wall_clock_are_rejected(self):
        for key, value in (("version", 99), ("clock", "unix-wall-clock")):
            with self.subTest(key=key):
                metadata = copy.deepcopy(self.metadata)
                if key == "version":
                    metadata["schema_version"] = value
                else:
                    metadata["contract"]["clock"] = value
                analyze.write_json(self.root / "run.json", metadata)
                with self.assertRaises(ValueError):
                    analyze.analyze(self.root)

    def test_boolean_schema_and_unbounded_timestamps_are_rejected(self):
        metadata = copy.deepcopy(self.metadata)
        metadata["schema_version"] = True
        analyze.write_json(self.root / "run.json", metadata)
        with self.assertRaises(ValueError):
            analyze.analyze(self.root)
        self.rx[-1]["receive_ns"] = 1 << 65
        self.write_fixture(self.root)
        with self.assertRaisesRegex(ValueError, "uint64"):
            analyze.analyze(self.root)

    def test_build_configuration_mismatch_rejected(self):
        other = self.root / "other"
        metadata = copy.deepcopy(self.metadata)
        metadata["build"]["configuration"] = "Debug"
        self.write_fixture(other, metadata)
        with self.assertRaises(ValueError):
            analyze.comparable([self.root, other])

    def test_unavailable_cpu_is_not_fabricated_zero(self):
        analyze.write_json(self.root / "resources.json", [
            {"role": "subscriber", "window": "lifecycle-to-report", "valid": False,
             "cpu_ns": 0, "wall_ns": 0, "peak_rss_bytes": 0}])
        self.assertIsNone(analyze.analyze(self.root)["resources"][0]["cpu_percent_one_core"])

    def test_unfinished_run_does_not_qualify(self):
        self.metadata["run_status"] = "failed"
        self.write_fixture(self.root)
        self.assertIn("incomplete_execution", analyze.analyze(self.root)["errors"])

    def test_analyzer_accepts_another_framework_with_same_contract(self):
        other = self.root / "other"
        metadata = copy.deepcopy(self.metadata)
        metadata["framework"] = {"name": "AnotherFramework", "revision": "opaque-version"}
        self.write_fixture(other, metadata)
        self.assertEqual(len(analyze.comparable([self.root, other])), 2)

    def test_borrowed_receive_environment_and_size_mismatch_rejected(self):
        other = self.root / "other"
        for kind in ("ownership", "os", "payload"):
            with self.subTest(kind=kind):
                metadata = copy.deepcopy(self.metadata)
                if kind == "ownership":
                    metadata["contract"]["subscriber_ownership"] = "borrowed-shared-view"
                elif kind == "os":
                    metadata["environment"]["comparison_environment"] = "another-os"
                else:
                    metadata["case"]["payload_bytes"] = 2048
                self.write_fixture(other, metadata)
                with self.assertRaisesRegex(ValueError, "Incompatible"):
                    analyze.comparable([self.root, other])

    def test_pacing_difference_needs_explicit_comparison_flag(self):
        other = self.root / "other"
        metadata = copy.deepcopy(self.metadata)
        metadata["case"]["pacing"] = "windows-highres"
        self.write_fixture(other, metadata)
        with self.assertRaises(ValueError):
            analyze.comparable([self.root, other])
        self.assertEqual(len(analyze.comparable([self.root, other], True)), 2)

    def test_nonincreasing_publish_clock_disqualifies(self):
        self.tx[-1]["publish_start_ns"] = self.tx[-2]["publish_start_ns"]
        self.write_fixture(self.root)
        self.assertIn("nonincreasing_send_clock", analyze.analyze(self.root)["errors"])

    def test_negative_resource_and_string_valid_flag_are_rejected(self):
        for field, value in (("cpu_ns", -1), ("valid", "false")):
            with self.subTest(field=field):
                resource = {"role": "publisher", "window": "formal-publication", "valid": True,
                            "cpu_ns": 1, "wall_ns": 10, "peak_rss_bytes": 20}
                resource[field] = value
                analyze.write_json(self.root / "resources.json", [resource])
                with self.assertRaises(ValueError):
                    analyze.analyze(self.root)

    def test_pacing_grid_and_skips_are_checked(self):
        ticks = [{"sample_id": index, "planned_ns": 1000000000 + index * 10000000,
                  "woke_ns": 1000000000 + index * 10000000 + 100,
                  "skipped_after": 0} for index in range(1, 5)]
        path = self.root / "pacing.csv"
        def write_ticks():
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(ticks[0]))
                writer.writeheader()
                writer.writerows(ticks)
        write_ticks()
        self.assertTrue(analyze.analyze(self.root)["qualified"])
        ticks[-1]["planned_ns"] += 1
        write_ticks()
        with self.assertRaisesRegex(ValueError, "fixed-grid"):
            analyze.analyze(self.root)


if __name__ == "__main__":
    unittest.main()
