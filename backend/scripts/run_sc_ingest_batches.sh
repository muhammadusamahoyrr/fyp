#!/usr/bin/env bash
# run_sc_ingest_batches.sh — drive ingest_sc_parquet.py in short batches.
#
# WHY BATCHES
# Two full-length attempts died on the Atlas link: the first at 255/1405 with
# _OperationCancelled mid-write, the second at 285 with an SSL handshake
# timeout. Both faults landed in pymongo's connection layer, below the retry
# wrapper around the awaited write, so widening that retry would not have
# caught either.
#
# A batch is a fresh process that ingests at most BATCH judgments and exits.
# Because the resume check treats a judgment as done only when it is in BOTH
# Mongo and Chroma, batches are idempotent and a crash costs only the batch in
# flight — minutes, not the whole run. Total wall time is slightly worse; the
# probability of ever finishing is much better.
#
# Usage:  bash scripts/run_sc_ingest_batches.sh PARQUET [BATCH]

set -u

PARQUET="${1:?usage: run_sc_ingest_batches.sh PARQUET [BATCH]}"
BATCH="${2:-200}"
# Overridable so the caller can supply pythonw.exe. A console-attached
# interpreter receives Ctrl+C sent to any process sharing its console, which
# is what killed the judgments rebuild mid-run; pythonw has no console to
# deliver one to.
PY="${PY:-venv/Scripts/python.exe}"
MAX_CONSECUTIVE_FAILURES=3

export PYTHONIOENCODING=utf-8

round=0
failures=0

while : ; do
    round=$((round + 1))
    echo "=== batch $round (limit $BATCH) at $(date '+%H:%M:%S') ==="

    out=$("$PY" scripts/ingest_sc_parquet.py --parquet "$PARQUET" \
              --apply --limit "$BATCH" 2>&1)
    status=$?

    echo "$out" | grep -E "^\s+held now|already ingested|Supreme Ct|judgments  |^\s+[0-9]+/|retry" \
        | tail -4

    if echo "$out" | grep -q "Nothing to do"; then
        echo "=== COMPLETE at $(date '+%H:%M:%S') after $round batch(es) ==="
        break
    fi

    if [ $status -ne 0 ]; then
        failures=$((failures + 1))
        echo "  batch failed (exit $status), consecutive failures: $failures"
        echo "$out" | tail -3
        if [ $failures -ge $MAX_CONSECUTIVE_FAILURES ]; then
            echo "=== GIVING UP after $failures consecutive failures ==="
            echo "  The link is down rather than flaky; progress so far is saved."
            exit 1
        fi
        # Back off before retrying: an immediate retry into a dead link just
        # burns another batch.
        sleep 30
    else
        failures=0
    fi
done
