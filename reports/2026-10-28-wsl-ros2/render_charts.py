"""One-off figure from the immutable formal dataset; no benchmark code changes."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True, help='Extracted dataset directory')
parser.add_argument('--output', type=Path, default=Path('build/charts'))
parser.add_argument('--percentile', choices=('p50', 'p99'), default='p99')
parser.add_argument('--font', type=Path, required=True, help='Traditional Chinese TTF/TTC/OTF font')
args = parser.parse_args()
DATA = args.data.resolve(strict=True)
OUTPUT = args.output.resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
metric = args.percentile
title_metric = metric.upper()
font_path = args.font.resolve(strict=True)
font_manager.fontManager.addfont(str(font_path))
font = font_manager.FontProperties(fname=str(font_path)).get_name()
plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False,
                     'svg.fonttype': 'path', 'pdf.fonttype': 42})

summary = json.loads((DATA / 'summary.json').read_text(encoding='utf-8'))
attempts = json.loads((DATA / 'attempts.json').read_text(encoding='utf-8'))
plans = json.loads((DATA / 'plan.json').read_text(encoding='utf-8'))
sizes = [plan['size'] for plan in plans]
assert len(sizes) == 7 and sizes[0] == 1024 and sizes[-1] == 128 * 1024**2
series = {}
for backend in ('vinc', 'datasharing', 'default'):
    rows = [next(row for row in summary if row['size'] == size and row['backend'] == backend) for size in sizes]
    series[backend] = {'values_ms': [row['median_of_run_percentiles_ms'][metric] for row in rows],
                       'range_ms': [
                           [min(item['metrics']['latency_ms'][metric] for item in attempts
                                if item['phase'] == 'formal' and item['size'] == size and item['backend'] == backend),
                            max(item['metrics']['latency_ms'][metric] for item in attempts
                                if item['phase'] == 'formal' and item['size'] == size and item['backend'] == backend)]
                           for size in sizes],
                       'passed': [row['qualified_repeats'] for row in rows], 'repeats': 3}
loans = [next(row for row in attempts if row['phase'] == 'loan' and row['size'] == size) for size in sizes]
assert all(row['qualified'] and row['metrics']['expected_formal'] == 1000 for row in loans)
series['loan'] = {'values_ms': [row['metrics']['latency_ms'][metric] for row in loans],
                  'full_path_ms': [row['metrics']['full_path_ms'][metric] for row in loans],
                  'passed': [1]*7, 'repeats': 1}

x = np.arange(len(sizes), dtype=float)
colors = {'vinc': '#2563EB', 'datasharing': '#008C75', 'loan': '#8B4DB5', 'default': '#C8523D'}
names = {'vinc': 'Vinc push', 'datasharing': 'ROS Data Sharing',
         'loan': 'Vinc loan（commit）', 'default': 'ROS 預設'}
markers = {'vinc': 'o', 'datasharing': 's', 'loan': 'D', 'default': '^'}
styles = {'vinc': '-', 'datasharing': '-', 'loan': '-.', 'default': '--'}

fig, ax = plt.subplots(figsize=(15, 9.2), facecolor='white')
fig.subplots_adjust(left=0.09, right=0.965, bottom=0.25, top=0.77)
fig.text(0.09, 0.965, f'正式結果｜{title_metric} 訊息延遲比較', fontsize=24, weight='bold', color='#10243A')
fig.text(0.09, 0.915, 'WSL2 Ubuntu 24.04 · ROS 2 Jazzy / Fast DDS · 獨立程序、接收端取得本機副本',
         fontsize=12, color='#526477')
fig.text(0.09, 0.877, f'每輪 1,000 筆；push / ROS 為三輪 {title_metric} 中位數，loan 為單輪 {title_metric}。越低越好。',
         fontsize=11.5, color='#526477')

for backend in ('default', 'datasharing', 'loan', 'vinc'):
    data = series[backend]
    values = np.array(data['values_ms'])
    if 'range_ms' in data:
        bounds = np.array(data['range_ms'])
        ax.errorbar(x, values, yerr=[values-bounds[:, 0], bounds[:, 1]-values], fmt='none',
                    ecolor=colors[backend], elinewidth=1.2, capsize=4, alpha=0.38, zorder=2)
    ax.plot(x, values, color=colors[backend], linewidth=2.5, linestyle=styles[backend],
            marker=markers[backend], markersize=7 if backend != 'vinc' else 6,
            markeredgewidth=1.3, label=names[backend], zorder=3)
    for index, passed in enumerate(data['passed']):
        if passed < data['repeats']:
            ax.scatter([x[index]], [values[index]], s=105, marker=markers[backend],
                       facecolors='white', edgecolors=colors[backend], linewidths=2, zorder=5)
            ax.annotate(f'{passed}/{data["repeats"]} 通過', (x[index], values[index]), xytext=(0, 17),
                        textcoords='offset points', ha='center', fontsize=9.5, color=colors[backend],
                        bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.9, 'pad': 1})

ax.set_yscale('log')
ax.set_ylim((0.025, 2000) if metric == 'p50' else (0.06, 7000))
ax.set_xlim(-0.25, 7.15)
ax.set_yticks([0.1, 1, 10, 100, 1000])
ax.yaxis.set_major_formatter(FuncFormatter(lambda value, position: f'{value:g}'))
ax.minorticks_off()
ax.grid(axis='y', color='#DCE3EC', linewidth=0.9)
ax.set_axisbelow(True)
ax.set_ylabel(f'{title_metric} 延遲（ms，對數刻度）', fontsize=12, labelpad=12)
labels = ['1 KiB'] + [f'{size // 1024**2} MiB' for size in sizes[1:]]
ax.set_xticks(x, [f'{label}\n{plan["common_rate"]} Hz' for label, plan in zip(labels, plans)], fontsize=11)
ax.set_xlabel('訊息有效資料量／該組共同要求頻率（各大小分組顯示）', fontsize=11.5, labelpad=15)
ax.tick_params(axis='y', labelsize=11, length=0, pad=8)
ax.tick_params(axis='x', length=0, pad=10)
for side in ('top', 'right', 'left'):
    ax.spines[side].set_visible(False)
ax.spines['bottom'].set_color('#CFD8E3')

handles = [Line2D([0], [0], color=colors[key], marker=markers[key], linewidth=2.5,
                  linestyle=styles[key], label=names[key]) for key in ('vinc', 'datasharing', 'loan', 'default')]
fig.legend(handles=handles, loc='upper left', bbox_to_anchor=(0.085, 0.847),
           ncol=4, frameon=False, fontsize=11.5, handlelength=2.9, columnspacing=2)

# Separate endpoint labels so close 128 MiB values remain readable on a log axis.
label_y = ({'vinc': 170, 'loan': 115, 'datasharing': 75, 'default': 390}
           if metric == 'p50' else {'vinc': 240, 'loan': 168, 'datasharing': 105, 'default': 2600})
for backend in ('vinc', 'datasharing', 'loan', 'default'):
    value = series[backend]['values_ms'][-1]
    ax.annotate(f'{value:,.2f} ms', xy=(6, value), xytext=(6.25, label_y[backend]),
                color=colors[backend], fontsize=10, va='center',
                arrowprops={'arrowstyle': '-', 'color': colors[backend], 'lw': 0.9})

fig.text(0.09, 0.145, '空心點＝該設定未三輪全通過；其延遲只供診斷，不能當成等條件有效排名。',
         fontsize=10.5, color='#9F352A')
fig.text(0.09, 0.109, f'細直線＝三輪 {title_metric} 的最小／最大值（非信賴區間）。Y 軸每一大格相差 10 倍。',
         fontsize=10.5, color='#526477')
fig.text(0.09, 0.073, f"Loan 的 commit 延遲不含借用／初始化：128 MiB 為 {series['loan']['values_ms'][-1]:.2f} ms；含準備的 full-path {title_metric} 為 {series['loan']['full_path_ms'][-1]:.2f} ms。",
         fontsize=10.3, color='#6D4290')
fig.text(0.09, 0.035, 'Data Sharing：BEST_EFFORT / ON；ROS 預設：RELIABLE / OFF。交付契約不同；資料集 20261028-224514-735300。',
         fontsize=9.5, color='#718096')

stem = OUTPUT / metric
for extension in ('png', 'svg', 'pdf'):
    fig.savefig(stem.with_suffix('.'+extension), dpi=180, facecolor='white')
    if extension == 'svg':
        # Matplotlib emits trailing spaces inside SVG path attributes. Newlines
        # retain the token separators while keeping generated Git diffs clean.
        path = stem.with_suffix('.svg')
        lines = path.read_text(encoding='utf-8').splitlines()
        path.write_text('\n'.join(line.rstrip() for line in lines) + '\n', encoding='utf-8')
plt.close(fig)
record = {'source': str(DATA), 'metric': title_metric + ' milliseconds', 'series': series,
          'payload_bytes': sizes, 'requested_hz': [plan['common_rate'] for plan in plans],
          'summary_sha256': hashlib.sha256((DATA/'summary.json').read_bytes()).hexdigest(),
          'attempts_sha256': hashlib.sha256((DATA/'attempts.json').read_bytes()).hexdigest()}
stem.with_suffix('.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(stem.with_suffix('.png'))
