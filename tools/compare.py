"""Sequential WSL comparison: retained pilots, frozen common rate, formal repeats."""
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

from . import analyze

MIB = 1024 * 1024
SHARED_BUDGET = 4 * 1024 * MIB
SIZES = (1024, MIB, 8*MIB, 16*MIB, 32*MIB, 64*MIB, 128*MIB)
RATES = (100, 50, 25, 10, 5, 2, 1)
MIN_AVAILABLE = 1024 * MIB
MAX_SWAP_GROWTH = 512 * MIB


def slots_for(payload):
    # Reserve image/control overhead and the DDS extra history sample. A 128 MiB
    # Data Sharing pool at depth 31 exceeds its backend's uint32 segment limit.
    return min(32, (SHARED_BUDGET - MIB) // (payload + 4096) - 1)


def memory():
    fields = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        fields[key] = int(value.split()[0]) * 1024
    return {'available': fields['MemAvailable'], 'swap_used': fields['SwapTotal'] - fields['SwapFree']}


def rate_qualified(metrics, rate):
    # Analyzer validity alone does not establish that the requested rate was
    # sustained. Keep overload runs, but exclude them from calibrated latency.
    return bool(metrics and metrics['qualified'] and metrics['actual_hz'] is not None
                and 0.95 * rate <= metrics['actual_hz'] <= 1.05 * rate)


def calibration_qualified(root, item):
    if not item['qualified'] or not item['metrics_path']:
        return False
    directory = root / item['metrics_path']
    directory = directory.parent
    with (directory / 'tx.csv').open() as stream:
        sent = {int(row['sample_id']): int(row['publish_start_ns']) for row in csv.DictReader(stream)}
    with (directory / 'rx.csv').open() as stream:
        received = {int(row['sample_id']): int(row['receive_ns']) for row in csv.DictReader(stream)}
    metadata = analyze.load_json(directory / 'run.json')
    warmup = metadata['case']['warmup']
    latencies = [received[key]-sent[key] for key in sorted(sent) if key > warmup and key in received]
    half = len(latencies) // 2
    drift = statistics.median(latencies[half:]) - statistics.median(latencies[:half])
    period = metadata['case']['period_ns']
    # Select latency workloads with queue headroom. This is a pilot policy, not
    # a framework latency SLA; formal outliers remain fully reported.
    p90 = item['metrics']['latency_ms']['p90'] * 1e6
    record = {'half_median_drift_ns': drift, 'p90_ns': p90,
              'policy': 'pilot drift <= one period; P90 <= four periods',
              'qualified': drift <= period and p90 <= 4*period}
    analyze.write_json(directory / 'calibration.json', record)
    return record['qualified']


def launch(args, root, phase, size, slots, rate, samples, repeat, backend, mode='push'):
    label = f'{phase}-{size}-{rate}hz-r{repeat}-{backend}-{mode}'
    directory = root / label
    directory.mkdir()
    command = [sys.executable, '-m', 'tools.run' if backend == 'vinc' else 'tools.ros']
    command += ['--slots', str(slots), '--rate', str(rate), '--samples', str(samples),
                '--warmup', str(max(64, 2*slots)), '--output', str(directory)]
    if backend == 'vinc':
        command += ['--build-info', str(args.build_info), '--sizes-bytes', str(size),
                    '--modes', mode, '--repeats', '1']
    else:
        command += ['--exe', str(args.ros_exe), '--setup', str(args.ros_setup),
                    '--bytes', str(size), '--profile', backend]
    analyze.write_json(directory / 'controller-command.json', command)
    print('Start:', label, flush=True)
    before = memory()
    minimum_available = before['available']
    maximum_swap = before['swap_used']
    aborted = None
    timeout = (samples + max(64, 2*slots)) / rate * 5 + 160
    started = time.monotonic()
    with (directory / 'controller.log').open('w') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                current = memory()
                minimum_available = min(minimum_available, current['available'])
                maximum_swap = max(maximum_swap, current['swap_used'])
                if current['available'] < MIN_AVAILABLE or current['swap_used'] - before['swap_used'] > MAX_SWAP_GROWTH:
                    aborted = 'memory-guard'
                if time.monotonic() - started > timeout:
                    aborted = 'controller-deadline'
                if aborted:
                    # Signal the worker first so it can drain/reap its owned
                    # processes. Group kill is a final, bounded test-only exit.
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=55)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=55)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    candidates = list(directory.rglob('metrics.json'))
    metrics = analyze.load_json(candidates[0]) if len(candidates) == 1 else None
    item = {'phase': phase, 'size': size, 'slots': slots, 'rate': rate, 'samples': samples,
            'repeat': repeat, 'backend': backend, 'mode': mode, 'directory': label,
            'metrics_path': str(candidates[0].relative_to(root)) if len(candidates) == 1 else None,
            'exit_code': process.returncode, 'abort': aborted, 'elapsed_seconds': time.monotonic()-started,
            'minimum_mem_available': minimum_available, 'maximum_swap_used': maximum_swap,
            'qualified': bool(not aborted and process.returncode == 0 and rate_qualified(metrics, rate)),
            'metrics': metrics}
    analyze.write_json(directory / 'controller.json', item)
    print('Done:', label, 'qualified=', item['qualified'],
          'Hz=', metrics['actual_hz'] if metrics else None, flush=True)
    return item


def run(args, root):
    attempts = []
    plans = []

    def attempt(*values, **kwargs):
        item = launch(args, root, *values, **kwargs)
        attempts.append(item)
        analyze.write_json(root / 'attempts.json', attempts)
        return item

    for size in args.sizes:
        slots = slots_for(size)
        # Pilot selection is fixed in advance: prefer Data Sharing if startup,
        # ownership and delivery work; SHM is an explicit fallback, never AUTO.
        sharing = attempt('profile', size, slots, 10, 32, 0, 'datasharing')
        shm = attempt('profile', size, slots, 10, 32, 0, 'shm')
        tuned = 'datasharing' if sharing['qualified'] else 'shm' if shm['qualified'] else None
        backends = ['vinc', 'default'] + ([tuned] if tuned else [])
        chosen_rate = None
        for rate in RATES:
            calibration = ['vinc'] + ([tuned] if tuned else ['default'])
            group = [attempt('pilot', size, slots, rate, args.pilot_samples, 0, backend) for backend in calibration]
            if all(calibration_qualified(root, item) for item in group):
                chosen_rate = rate
                break
        plan = {'size': size, 'slots': slots, 'common_rate': chosen_rate,
                'tuned': tuned, 'backends': backends}
        plans.append(plan)
        analyze.write_json(root / 'plan.json', plans)
        if chosen_rate is None:
            print('No jointly sustainable rate; retain failures:', size, flush=True)
            continue
        # No formal result influences tuning. All repeats stay at the pilot's
        # chosen capacity/rate; alternating order reduces a fixed order bias.
        for repeat in range(1, args.repeats + 1):
            ordered = backends if repeat % 2 else list(reversed(backends))
            group = [attempt('formal', size, slots, chosen_rate, args.samples, repeat, backend) for backend in ordered]
            paths = [root / item['metrics_path'] for item in group if item['metrics_path']]
            if len(paths) == len(group):
                analyze.comparable([path.parent for path in paths])
        # Native loan avoids a Publisher copy and is reported separately from
        # ordinary ROS publish. It is not included in a like-for-like ratio.
        attempt('loan', size, slots, chosen_rate, args.samples, 1, 'vinc', mode='loan')
    analyze.write_json(root / 'complete.json', {'plans': plans, 'attempts': len(attempts)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-info', type=Path, required=True)
    parser.add_argument('--ros-exe', type=Path, required=True)
    parser.add_argument('--ros-setup', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=SIZES)
    parser.add_argument('--samples', type=int, default=1000)
    parser.add_argument('--pilot-samples', type=int, default=128)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path('results/comparison'))
    args = parser.parse_args()
    if any(size not in SIZES for size in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error('Select distinct supported payload sizes')
    if not 100 <= args.samples <= 100000 or not 16 <= args.pilot_samples <= 10000 or not 1 <= args.repeats <= 10:
        parser.error('Invalid formal/pilot sample or repeat count')
    for name in ('build_info', 'ros_exe', 'ros_setup'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    root = args.output.resolve() / datetime.datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')
    root.mkdir(parents=True)
    sources = list(Path('tools').glob('*.py')) + list(Path('ros2').rglob('*.cpp'))
    sources += list(Path('ros2').rglob('*.hpp')) + list(Path('ros2/msg').glob('*.msg'))
    analyze.write_json(root / 'sources.json', {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
    analyze.write_json(root / 'settings.json', {'samples': args.samples, 'pilot_samples': args.pilot_samples,
        'repeats': args.repeats, 'sizes': args.sizes, 'rates': RATES, 'minimum_mem_available': MIN_AVAILABLE,
        'max_swap_growth': MAX_SWAP_GROWTH, 'rate_tolerance_percent': 5,
        'profile_selection': 'DataSharing if qualified, otherwise explicit SHM; no best-formal selection'})
    print('Comparison:', root, flush=True)
    run(args, root)
    print('Completed:', root, flush=True)


if __name__ == '__main__':
    main()
