"""Load (or remove) demo history for the service-performance dashboard in the database DATABASE_URL points to.

    python scripts/seed_history.py            # about 12 months of resolved demo tickets (replaces earlier ones)
    python scripts/seed_history.py --months 6
    python scripts/seed_history.py --remove   # delete every demo ticket; nothing else is touched

Demo tickets are source "Demo" (ids DEMO-nnnnn), already closed, so they never reach a queue or the agents.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, so `app` imports when run as a script

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table)
from app.core.config import settings  # noqa: E402
from app.services import demo_history  # noqa: E402


async def main(months: int, remove: bool) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            def work(c) -> int:
                return demo_history.remove(Session(c)) if remove else demo_history.generate(Session(c), months)

            n = await conn.run_sync(work)
        print(f"{'Removed' if remove else 'Created'} {n} demo tickets in {engine.url.render_as_string(hide_password=True)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.months, args.remove))
