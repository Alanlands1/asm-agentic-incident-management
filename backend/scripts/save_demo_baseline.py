"""Save a demo baseline: the console's tables and the issues of the synced Jira projects, as they are now.

The demo reset puts both back once DEMO_BASELINE_DIR names the folder (app/services/baseline.py). Reads the configured
database and Jira and changes neither; a baseline already in the folder is never overwritten.
Usage: python scripts/save_demo_baseline.py <directory>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, so `app` imports when run as a script

from sqlalchemy import select  # noqa: E402

import app.admin.models  # noqa: E402,F401  (registers the admin tables)
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.jira import JiraProject  # noqa: E402
from app.services import atlassian, baseline  # noqa: E402


async def main(directory: Path) -> None:
    async with AsyncSessionLocal() as db:
        projects = list(await db.scalars(select(JiraProject.key)))
        await db.commit()  # no transaction open while Jira answers
        async with atlassian.client() as c:
            issues = await baseline.fetch_issues(c, projects)
        print(await db.run_sync(lambda s: baseline.save_baseline(s, issues, directory)))
    print(f"Saved {directory}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
