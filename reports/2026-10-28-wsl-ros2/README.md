# WSL2 comparison, 2026-10-28–29 / 本次數據與圖表

Frozen primary session: `20261028-224514-735300`, Asia/Taipei. Framework revision:
`a3a0843c5dc89f8b052c5f25afa66e1f171db99e`. Results and limitations are summarized
in the [repository README](../../README.md#recorded-baseline--本次結果) and
[experiment record](../../docs/ROS_COMPARISON.md).

## Published files / 公開內容

| File | Contents |
|---|---|
| [data.zip](data.zip) | All 116 primary attempts: raw numeric CSV, normalized inputs, saved metrics, calibration, transport XML/mapping inventory and resource/pacing observations |
| [data.zip.sha256](data.zip.sha256) | Archive SHA-256 |
| [summary.json](summary.json) | Three-run P50/P90/P99 medians, P99 ranges and formal qualification counts; loan remains in the full dataset |
| [P50 PNG](p50.png) / [SVG](p50.svg) | Four paths, including single-run Vinc loan commit latency |
| [P99 PNG](p99.png) / [SVG](p99.svg) | The same paths and explicit failure markers |
| [render_charts.py](render_charts.py) | Recreate either chart from the extracted dataset |

The data archive includes every primary pilot, formal run and loan run, including
failures. Existing measurement files are preserved byte-for-byte. Machine-local
command lines, console/build logs, paths to executables and duplicate source/build
trees are excluded. Executable/native-artifact hashes are collected separately in
`binary-fingerprints.json`; no binary is redistributed. Earlier aborted UniquePtr
diagnostic campaigns remain local and are not primary performance scores.

數據包保留全部主資料集的 116 次嘗試，沒有刪掉高頻失敗或 ROS 預設設定的失敗。
排除的是本機路徑、建置／執行輸出及重複原始碼，並未更改測得的數字。
`MANIFEST.sha256.json` 核對每個收錄檔案；`binary-fingerprints.json` 只保留實際 binary 雜湊。
`sources.json` 是量測時工作樹的來源雜湊，可能受 checkout 換行格式影響，不是 Git blob ID。

## Verify and reanalyze / 核對與重算

Use the repository's standard-library-only analyzer. From the repository root:

```sh
python -m zipfile -e reports/2026-10-28-wsl-ros2/data.zip build/published-wsl
python -m tools.analyze build/published-wsl/dataset/FORMAL_CASE/SESSION/r1-push-SIZE
```

`FORMAL_CASE/SESSION/r1-push-SIZE` above is a placeholder, not a literal path.
Choose the actual relative case path from the extracted `dataset/attempts.json`:
its `metrics_path` identifies a case's `metrics.json`; pass that file's **parent
directory** to the analyzer. ROS and Vinc directory depths differ.
The extracted `dataset/REPORT.zh-TW.md` provides the complete tables and relative
links to each case's controller record. `verification.json` records the original
independent raw-percentile check; `binary-fingerprints.json` identifies artifacts.

`tools.analyze` exit 0 means valid measured data, 1 means an unqualified run, and
2 means rejected input. The comparison controller additionally checks achieved
frequency within ±5%; its completed collection does not mean every case passed.
Formal/loan data, failed pilots and calibration-headroom decisions stay distinct.

解壓後，以 `attempts.json` 的相對路徑找各組；不能把收到部分訊息就算成功。
DDS 內部碰撞／覆寫計數是 null（未提供），不是測得零；漏收依精確訊息 ID 核對。
圖上的空心點未三輪全通過，延遲僅供診斷，不可作等條件有效排名。

## Recreate the charts / 重畫圖表

Chart generation is optional and separate from the benchmark/analyzer runtime.
It was checked with Python 3.13, Matplotlib 3.10.8 and NumPy 2.4.3. A Traditional
Chinese TTF/TTC/OTF font is required; font software is not bundled. For example,
Windows can use Microsoft JhengHei; Linux/macOS can supply an installed CJK font.

```sh
python -m pip install -r reports/2026-10-28-wsl-ros2/chart-requirements.txt
python reports/2026-10-28-wsl-ros2/render_charts.py --data build/published-wsl/dataset --font FONT_FILE --percentile p50
python reports/2026-10-28-wsl-ros2/render_charts.py --data build/published-wsl/dataset --font FONT_FILE --percentile p99
```

Outputs go to ignored `build/charts/`: PNG, SVG, PDF and the plotted data JSON.
All percentiles are read from measured observations. Thin bars are min/max across
the three run-level percentiles, not confidence intervals. Loan has one run and
excludes acquisition/initialization from its commit-to-callback curve; full-path
statistics remain available in its original metrics.

Benchmark rerun instructions are in [native](../../README.md#build--建置) and
[ROS](../../ros2/README.md). Build the separate ROS package with colcon. Do not
benchmark concurrently with builds/tests. This dataset remains the retained
baseline; no framework performance optimization was made for publication.
