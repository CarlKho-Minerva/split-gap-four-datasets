#!/usr/bin/env bash
# Run from the extracted code/audit candidate after installing the pinned environment.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
export NP_WS="$ROOT"
export PYTHONPATH="$ROOT/reproducibility/vendor"
export MPLBACKEND=Agg
export PYTHONHASHSEED=0
export OMP_NUM_THREADS=4
"$PYTHON_BIN" reproducibility/verify.py --data
"$PYTHON_BIN" analysis/analysis.py
"$PYTHON_BIN" reproducibility/verify.py --data
