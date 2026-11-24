# EUR/USD 1-minute data (HistData.com)

- Source: HistData.com free ASCII M1 files, bid prices only. The volume column is always 0.
- Coverage: 2023-01-01 to 2026-11-06 (file clock).
- Prepare: `bash data/prepare.sh` unzips into `data/csv/`, which git ignores.
- Use: `python3 run_tests.py data/csv measured 0.8`

Known issues (see `audit/` and `results/data_audit_monthly.txt`). `engine.py` handles them:
- Feb–Jul 2023: 27–29% of minutes missing. Excluded via `engine.EXCLUDE`.
- 128 duplicate timestamps. The first copy is kept.
- Timestamps follow European summer time: UTC = file + 4h from the last Sunday of March
  to the last Sunday of October, + 5h otherwise (`tz_mode="measured"`).
