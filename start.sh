#!/usr/bin/env bash
set -e
export PIN_DATA_DIR="${PIN_DATA_DIR:-/data}"
mkdir -p "$PIN_DATA_DIR"

if [ "${RUN_POOL:-1}" = "1" ]; then
  proxy-scraper --recheck live --serve 8899 --serve-refill 6 \
                --sticky 300 --https-only --no-datacenter -y \
                >/tmp/pool.log 2>&1 &
fi

( cd funcaptcha-solver && python main.py >/tmp/solver.log 2>&1 & )

exec python reference_api.py
