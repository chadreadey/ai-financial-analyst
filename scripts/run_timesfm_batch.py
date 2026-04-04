"""
TimesFM nightly batch scheduler.

Verification:
    # Gate disabled (skips):
    python scripts/run_timesfm_batch.py --run-now

    # Full run:
    ENABLE_TIMESFM=true TIMESFM_BATCH_TICKERS=AAPL python scripts/run_timesfm_batch.py --run-now

    # Scheduled:
    python scripts/run_timesfm_batch.py --hour 23
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_timesfm_batch")


def run_job():
    from config import settings

    if not settings.enable_timesfm:
        logger.info("ENABLE_TIMESFM=false — skipping")
        return

    raw = settings.timesfm_batch_tickers.strip()
    if not raw:
        logger.warning("TIMESFM_BATCH_TICKERS is empty — nothing to process")
        return

    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not tickers:
        logger.warning("No valid tickers after parsing — skipping")
        return

    from quant.timesfm.batch import run_batch
    results = run_batch(tickers)
    ok_count = sum(1 for v in results.values() if v == "ok")
    logger.info("TimesFM batch complete: %d/%d tickers OK", ok_count, len(results))
    for ticker, status in results.items():
        if status != "ok":
            logger.warning("  %s: %s", ticker, status)


def main():
    parser = argparse.ArgumentParser(description="TimesFM nightly batch scheduler")
    parser.add_argument("--run-now", action="store_true", help="Run batch immediately and exit")
    parser.add_argument("--hour", type=int, default=23, help="Cron hour (default: 23 = 11 PM)")
    parser.add_argument("--minute", type=int, default=0, help="Cron minute (default: 0)")
    args = parser.parse_args()

    if args.run_now:
        run_job()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(run_job, "cron", hour=args.hour, minute=args.minute)
    logger.info("Scheduler started — job fires at %02d:%02d ET", args.hour, args.minute)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
