"""
Offline and live evaluation harness for the analyst agents.

See ``docs/EVALS.md`` for the strategy this implements. Quick start::

    python -m evals run --suite all          # offline, replays cassettes
    python -m evals record --suite synthesis # live, refreshes cassettes
"""

__all__ = ["contracts", "dataset", "checks", "replay", "runner", "report"]
