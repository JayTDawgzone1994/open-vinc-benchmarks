"""Render all comparison attempts; never replace missing counters with zeros."""
import argparse
from collections import defaultdict
from pathlib import Path
import statistics

from . import analyze


def number(value, digits=3):
    return f'{value:.{digits}f}' if value is not None else '—'


def available_median(values):
    # Failed resource acquisition is unavailable, not a zero CPU measurement.
    present = [value for value in values if value is not None]
    return statistics.median(present) if present else None


def size_label(value):
    return '1 KiB' if value == 1024 else f'{value // (1024*1024)} MiB'


def cpu(metrics, role, window):
    return next((row['cpu_percent_one_core'] for row in metrics['resources']
                 if row['role'] == role and row['window'] == window), None)


def render(root):
    attempts = analyze.load_json(root / 'attempts.json')
    plans = analyze.load_json(root / 'plan.json')
    settings = analyze.load_json(root / 'settings.json')
    complete = (root / 'complete.json').exists()
    lines = ['# Open-VINC／ROS 2：WSL 同機實測報告', '',
        f'資料集：`{root.name}`。狀態：' + ('完整執行結束。' if complete else '**尚未完整結束，僅為目前進度。**'), '',
        '這是本機 WSL2 Ubuntu 24.04 的原生 C++ API 比較，不是原生 Linux 部署認證、',
        'Apex.AI performance_test 成績、所有 ROS 後端排名或硬即時保證。', '',
        '## 測試邊界', '',
        '- 同一台 Ryzen 7 5700X3D、16 個邏輯 CPU；Windows 11 上的 WSL2 Ubuntu 24.04.5。',
        '- Open-VINC 固定版本 `a3a0843c5dc89f8b052c5f25afa66e1f171db99e`，未修改框架。',
        '- ROS 2 Jazzy、rclcpp 28.1.22、rmw_fastrtps_cpp 8.4.4、Fast DDS 2.14.7、Fast CDR 2.2.8。',
        '- 雙方 GCC/libstdc++ 13.3、Release；每組各一個獨立 Publisher／Subscriber 程序。Vinc 另有中央監督程序。',
        '- 延遲從 publish／push／commit API 入口到取得獨立本機副本的 callback 入口，使用同機 CLOCK_MONOTONIC。',
        '- 普通 push／ROS publish 重用預先初始化的本機 byte vector；序號逐筆更新。接收檢查長度、序號與頭尾標記，不是完整內容雜湊。',
        '- ROS 使用持有本機訊息的 SharedPtr callback，RMW loans 與 intra-process routing 關閉；不把共享記憶體借用視圖當成本機副本。',
        '- 早期 UniquePtr 診斷會在 rclcpp 派送時額外深拷貝，已另存且排除在本次主資料集之外；詳見 ROS 工作負載 README 與固定版本的 rclcpp dispatch 實作。',
        '- 不使用 busy spin、全域計時器調整、CPU 綁核或優先級調整；未量測功耗。桌面背景負載未隔離。',
        f"- 每輪 {settings['samples']:,} 筆正式資料，{settings['repeats']} 輪；另有至少 64 筆暖身。P99 用 nearest rank，不從平均值推估。", '',
        '## 容量與共同速率', '',
        '先以校準試跑選定速率，再凍結正式測試設定。主矩陣從 100 Hz 逐級下降；校準須完整收送、',
        'Vinc 無碰撞／覆寫／漏收且實際頻率落在要求的 ±5%。另以校準 P90 ≤ 四個週期、前後半段中位數成長 ≤ 一個週期選擇餘裕；這不是正式測試的延遲 SLA。ROS 預設設定另作對照，不決定調校組的共同速率。',
        '所有 100 Hz 失敗試跑仍列在下方。32 格 RingBuffer，128 MiB 使用 30 格；實際 Bus 配置不得超過 4 GiB。',
        'DDS 另有控制區、序列化緩衝與備用格，不能把相同深度說成相同總記憶體。', '',
        '| Payload | 格數 | 共同 Hz | ROS 調校路徑 |', '|---|---:|---:|---|']
    for plan in plans:
        lines.append(f"| {size_label(plan['size'])} | {plan['slots']} | {plan['common_rate']} | {plan['tuned'] or '無可用調校路徑'} |")
    if settings.get('origin'):
        lines += ['', f"**本次是額外確認**：原始資料集 `{settings['origin']}` 的正式失敗仍保留，沒有覆寫或改判成功。",
                  '這裡只重測受影響的 Vinc／調校 ROS 配對，採較低共同速率。不同速率的數字不可混成同一組成績。',
                  '每方僅一輪 300 筆，用於確認低速收送；P99 尾端僅約三筆，不能取代原始三輪各 1,000 筆的正式成績。', '']
    lines += ['', '## 正式結果', '',
        f"下表 P50／P90／P99 各自取 {settings['repeats']} 輪統計值的中位數，**不是合併樣本後的百分位數**。",
        'P99 範圍列出各輪差異；有任一失敗，整組不標為全部通過，也不隱藏該輪。',
        'ROS default 為 RELIABLE、預設傳輸及 Data Sharing OFF；調校組為 BEST_EFFORT、',
        '明確 ON 的 Data Sharing（有界訊息），或明確 SHM fallback。Vinc 的覆寫與讀取保護契約不同，不能據此宣稱可靠度等同。', '',
        '| Payload | 路徑 | 合格輪數 | 實際 Hz 範圍 | P50 / P90 / P99 中位數 ms | P99 範圍 ms | 全部樣本最大 ms |',
        '|---|---|---:|---:|---:|---:|---:|']
    grouped = defaultdict(list)
    for item in attempts:
        if item['phase'] == 'formal':
            grouped[(item['size'], item['backend'])].append(item)
    summaries = []
    for (size, backend), rows in sorted(grouped.items()):
        measured = [row['metrics'] for row in rows if row['metrics'] and row['metrics']['latency_ms']]
        passed = sum(row['qualified'] for row in rows)
        summary = {'size': size, 'backend': backend, 'qualified_repeats': passed, 'repeats': len(rows)}
        if measured:
            p = {key: statistics.median(row['latency_ms'][key] for row in measured) for key in ('p50', 'p90', 'p99')}
            rates = [row['actual_hz'] for row in measured if row['actual_hz'] is not None]
            tails = [row['latency_ms']['p99'] for row in measured]
            summary.update({'median_of_run_percentiles_ms': p, 'p99_range_ms': [min(tails), max(tails)]})
            lines.append(f"| {size_label(size)} | {backend} | {passed}/{len(rows)} | {number(min(rates))}–{number(max(rates))} | "
                         f"{number(p['p50'])} / {number(p['p90'])} / {number(p['p99'])} | {number(min(tails))}–{number(max(tails))} | "
                         f"{number(max(row['latency_ms']['max'] for row in measured))} |")
        else:
            lines.append(f'| {size_label(size)} | {backend} | {passed}/{len(rows)} | — | 無完整量測，見原始診斷 | — | — |')
        summaries.append(summary)
    lines += ['', '## CPU 與記憶體', '',
        'CPU 100% 表示一個邏輯核心。Publisher 用排除暖身與寫檔的正式發布區間；',
        'Subscriber／中央用含啟動、暖身與收尾等待的 lifecycle-to-report 區間，不能把不同區間的百分比相加。',
        '表中為各輪中位數；RSS 為各程序生命週期 high-water，會重複計入共享頁，不能加總為實體記憶體。', '',
        '| Payload | 路徑 | Pub 正式 CPU % | Sub lifecycle CPU % | 中央 lifecycle CPU % | Pub / Sub / 中央最大 RSS MiB |',
        '|---|---|---:|---:|---:|---:|']
    for (size, backend), rows in sorted(grouped.items()):
        measured = [row['metrics'] for row in rows if row['metrics']]
        if not measured:
            continue
        pub = [cpu(row, 'publisher', 'formal-publication') for row in measured]
        sub = [cpu(row, 'subscriber', 'lifecycle-to-report') for row in measured]
        central = [cpu(row, 'central', 'lifecycle-to-report') for row in measured]
        central = [value for value in central if value is not None]
        peaks = {role: max((resource['peak_rss_bytes'] for row in measured for resource in row['resources']
                           if resource['role'] == role), default=0) / (1024*1024) for role in ('publisher', 'subscriber', 'central')}
        lines.append(f"| {size_label(size)} | {backend} | {number(available_median(pub))} | "
                     f"{number(available_median(sub))} | "
                     f"{number(statistics.median(central)) if central else '—'} | "
                     f"{number(peaks['publisher'],1)} / {number(peaks['subscriber'],1)} / "
                     f"{number(peaks['central'],1) if central else '—'} |")
    lines += ['', '## Vinc loan 補充', '',
        '每個大小另做一輪，與 ROS 普通 publish 不作同工作量倍率比較。commit 延遲不含 get_next／resize／初始化；',
        'full_path 額外包含這些準備成本。兩欄各自計算百分位數，不可相加。', '',
        '| Payload | 合格 | 實際 Hz | commit P99 ms | full_path P99 ms |', '|---|---|---:|---:|---:|']
    for row in attempts:
        if row['phase'] == 'loan':
            metrics = row['metrics']
            lines.append(f"| {size_label(row['size'])} | {row['qualified']} | {number(metrics['actual_hz']) if metrics else '—'} | "
                f"{number(metrics['latency_ms']['p99']) if metrics and metrics['latency_ms'] else '—'} | "
                f"{number(metrics['full_path_ms']['p99']) if metrics and metrics['full_path_ms'] else '—'} |")
    lines += ['', '## 全部嘗試與失敗', '',
        '下表涵蓋正式、校準及設定預檢。即使有部分好看的延遲數字，漏收、碰撞或低於要求速率的結果仍不合格。',
        'ROS 的內部碰撞／覆寫計數為 null（未提供），並非測得零；端到端漏收由精確 ID 清單判定。', '',
        '| 階段 | Payload | 路徑 | 要求 Hz | 實際 Hz | 合格 | 問題／計數 | 原始資料 |',
        '|---|---|---|---:|---:|---|---|---|']
    for row in attempts:
        metrics = row['metrics']
        errors = metrics['errors'] if metrics else {'exit': row['exit_code']}
        pilot_ok = None
        if row['phase'] == 'pilot' and row['metrics_path']:
            pilot_path = (root / row['metrics_path']).parent / 'calibration.json'
            if pilot_path.exists():
                pilot_ok = analyze.load_json(pilot_path)['qualified']
                if not pilot_ok:
                    errors = {**errors, 'pilot': 'queue-growth-or-insufficient-latency-headroom'}
        if row['abort']:
            errors = {**errors, 'controller': row['abort']}
        if metrics and not analyze.load_json(root / row['metrics_path'])['qualified']:
            errors = {**errors, 'analyzer': 'unqualified'}
        if metrics and not row['qualified'] and not errors:
            errors = {'rate': 'outside ±5%'}
        lines.append(f"| {row['phase']} r{row['repeat']} | {size_label(row['size'])} | {row['backend']} {row['mode']} | "
            f"{row['rate']} | {number(metrics['actual_hz']) if metrics else '—'} | {row['qualified'] and pilot_ok is not False} | "
            f"{str(errors).replace('|', '/')} | [資料]({row['directory']}/controller.json) |")
    lines += ['', '## 證據與重算', '',
        '- `attempts.json`、`plan.json`、`settings.json`：全部嘗試、凍結設定與記憶體保護門檻。',
        '- 各組 `raw/`、normalized CSV、run.json、metrics.json、resources.json、pacing.csv。',
        '- ROS XML 與運行中的共享映像清單；實際 binary SHA256、CMake 建置資訊及套件版本。',
        '- 以 `python3 -m tools.analyze CASE_DIRECTORY` 重算單組。跨框架比較還會檢查時鐘、所有權、容量、頻率與樣本數一致。',
        '- 本報告只對這份資料集負責；正式失敗不以事後降低頻率或刪除離群值補成成功。',
        '- 測試採記憶體低於 1 GiB 或 swap 增加超過 512 MiB 時中止；這是測試機保護，不是傳輸效能數字。', '']
    (root / 'REPORT.zh-TW.md').write_text('\n'.join(lines), encoding='utf-8')
    analyze.write_json(root / 'summary.json', summaries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    render(args.directory.resolve(strict=True))
    print(args.directory / 'REPORT.zh-TW.md')


if __name__ == '__main__':
    main()
