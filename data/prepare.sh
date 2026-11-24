#!/usr/bin/env bash
# Unzip the HistData EUR/USD 1-minute files into data/csv (git-ignored) for the engine.
# Usage: bash data/prepare.sh        then: python3 run_tests.py data/csv measured 0.8
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p csv
for z in histdata/*.zip; do unzip -oq "$z" -d csv; done
ls csv/DAT_ASCII_EURUSD_M1_*.csv | wc -l | xargs echo "csv files ready:"
