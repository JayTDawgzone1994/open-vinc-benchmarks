from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools import compare, ros
from tools import analyze, run


class RosComparisonTests(unittest.TestCase):
    def test_capacity_reserves_both_image_overhead_and_dds_extra_slot(self):
        for size in compare.SIZES:
            slots = compare.slots_for(size)
            self.assertGreaterEqual(slots, 2)
            self.assertLess((slots + 1) * (size + 4096), compare.SHARED_BUDGET)
        self.assertEqual(compare.slots_for(128 * compare.MIB), 30)

    def test_complete_but_slow_run_is_not_calibration_success(self):
        self.assertFalse(compare.rate_qualified({'qualified': True, 'actual_hz': 64}, 100))
        self.assertFalse(compare.rate_qualified({'qualified': False, 'actual_hz': 100}, 100))
        self.assertFalse(compare.rate_qualified(None, 100))
        self.assertTrue(compare.rate_qualified({'qualified': True, 'actual_hz': 99.8}, 100))

    def test_a_growing_receiver_queue_is_not_a_stable_pilot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analyze.write_json(root / 'run.json', {'case': {'warmup': 2, 'period_ns': 1000000}})
            sent = [{'sample_id': index, 'publish_start_ns': index * 1000000} for index in range(1, 11)]
            run.write_csv(root / 'tx.csv', sent)
            item = {'qualified': True, 'metrics_path': 'metrics.json', 'metrics': {'latency_ms': {'p90': 1}}}
            run.write_csv(root / 'rx.csv', [{'sample_id': row['sample_id'], 'receive_ns': row['publish_start_ns']+1000000} for row in sent])
            self.assertTrue(compare.calibration_qualified(root, item))
            run.write_csv(root / 'rx.csv', [{'sample_id': row['sample_id'], 'receive_ns': row['publish_start_ns']+row['sample_id']*2000000} for row in sent])
            item['metrics']['latency_ms']['p90'] = 20
            self.assertFalse(compare.calibration_qualified(root, item))

    def test_datasharing_on_is_limited_to_the_bounded_benchmark_topic(self):
        text, policy = ros.tuning_xml('datasharing', 128 * ros.MIB, 30,
                                      Path('/dev/shm/benchmark-test'), '/benchmark_test')
        root = ET.fromstring(text)
        namespace = {'d': 'http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles'}
        for kind in ('data_writer', 'data_reader'):
            profiles = root.findall('d:' + kind, namespace)
            default = next(profile for profile in profiles if profile.get('is_default_profile') == 'true')
            specific = next(profile for profile in profiles if profile.get('profile_name') == '/benchmark_test')
            self.assertEqual(default.find('d:qos/d:data_sharing/d:kind', namespace).text, 'OFF')
            self.assertEqual(specific.find('d:qos/d:data_sharing/d:kind', namespace).text, 'ON')
            self.assertEqual(specific.find('d:topic/d:resourceLimitsQos/d:max_samples', namespace).text, '30')
        self.assertEqual(policy['data_sharing'], 'ON')
        self.assertEqual(policy['reliability'], 'BEST_EFFORT')

    def test_shm_transport_can_hold_a_whole_large_image(self):
        _, policy = ros.tuning_xml('shm', 128 * ros.MIB, 30, Path('/dev/shm/benchmark-test'))
        self.assertGreater(policy['max_transport_message_bytes'], 128 * ros.MIB)
        self.assertGreater(policy['segment_bytes_per_participant'], 4 * 128 * ros.MIB)
        self.assertEqual(policy['data_sharing'], 'OFF')

    def test_invalid_tuning_name_does_not_silently_use_defaults(self):
        with self.assertRaises(ValueError):
            ros.tuning_xml('automatic', 1024, 32, Path('/dev/shm/benchmark-test'))
