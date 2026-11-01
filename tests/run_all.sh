#!/bin/sh
# Run every simulator test against the current builds (build first: see README).
# usage: tests/run_all.sh
cd "$(dirname "$0")/.." || exit 1
status=0
python3 tests/test_badapple.py | tail -1 || status=1
python3 tests/test_life.py | tail -1 || status=1
exit $status
