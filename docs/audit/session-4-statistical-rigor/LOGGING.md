# Where to check the assumption logs

The stochastic assumption logger (`quant/assumption_audit.py`) records every
statistical assumption an instrumented routine relies on, and whether it held,
failed, or could not be checked. There are **four** places to read those logs,
from most convenient to most raw.

## 1. The CLI viewer (terminal) — start here

```bash
python3 scripts/show_assumption_log.py                   # grouped summary + violations
python3 scripts/show_assumption_log.py --status violated # only violations
python3 scripts/show_assumption_log.py --severity high   # high + critical only
python3 scripts/show_assumption_log.py --target sharpe    # filter by target
python3 scripts/show_assumption_log.py --tail 20          # last 20 records
python3 scripts/show_assumption_log.py --json             # machine-readable
```

It resolves the log location automatically (see precedence below).

## 2. The batch auditor's report (markdown)

Running the harness over the system's own evidence writes a human-readable
report and a full JSONL stream:

```bash
python3 scripts/run_statistical_rigor_audit.py
# -> docs/audit/session-4-statistical-rigor/assumption_report.md
# -> docs/audit/session-4-statistical-rigor/assumption_log.jsonl
```

`assumption_report.md` groups violations by severity and lists the information
gaps (checks that could not be evaluated). This is the best artifact to review
in a PR or commit to the repo.

## 3. The live JSONL sink (running app / pipeline)

When the backend starts it points the default logger at the configured sink
(`backend/main.py` → `configure_default_log`). Any instrumented routine
(e.g. `quant/cross_sectional.normalize_signals_cross_sectionally`) then appends
one JSON object per check to:

```
logs/assumptions.jsonl        # default; configurable
```

Tail it directly:

```bash
tail -f logs/assumptions.jsonl | python3 -m json.tool
# or
python3 scripts/show_assumption_log.py --path logs/assumptions.jsonl
```

The directory is git-ignored (runtime artifact).

## 4. The diagnostics API (dashboard / HTTP)

The backend exposes the records over HTTP so the frontend or an operator can
read them in-app:

```
GET /api/diagnostics/assumptions
GET /api/diagnostics/assumptions?status=violated
GET /api/diagnostics/assumptions?severity=high&limit=200
```

It returns live in-memory records from the running API when present, and falls
back to the JSONL file on disk otherwise, with a rolled-up summary.

---

## Configuration & precedence

Enablement and the file location are resolved in this order (first wins):

1. **Environment variables**
   - `ASSUMPTION_AUDIT_ENABLED` — `0`/`false`/`no` disables recording.
   - `ASSUMPTION_AUDIT_JSONL` — path to stream records to.
2. **App settings** (`config.py`)
   - `assumption_audit_enabled` (default `True`)
   - `assumption_audit_log_path` (default `logs/assumptions.jsonl`)
3. **Built-in defaults** — enabled, in-memory only (no file) until a path is set.

Programmatic access:

```python
from quant.assumption_audit import get_audit_log
log = get_audit_log()
print(log.summary())          # counts + violations
log.to_jsonl("/tmp/a.jsonl")  # dump the in-memory records
```

## What gets logged today

Instrumented call sites so far:

- `quant/cross_sectional.normalize_signals_cross_sectionally` — cross-section
  size adequacy (`min_sample`) and the silent-zero confound per signal field
  (`no_silent_zeros`).
- `scripts/run_statistical_rigor_audit.py` — the full battery against the IC /
  walk-forward / composite artifacts.

More call sites (Sharpe/IC significance, position sizing, outcome calibration)
are being wired in on the other harness branches.
