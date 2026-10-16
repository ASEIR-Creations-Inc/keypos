"""Fail when frontend asset stamps are stale (run tools/stamp.py to fix).

A till (or a Sheet app phone) that goes offline right after install only has what its
service worker precached, so every script and stylesheet its pages load must be
precached under the URL the page uses,
and every ?v= must be the hash of the file's current content.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("stamp", ROOT / "tools" / "stamp.py")
stamp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stamp)


def main() -> int:
    problems = [
        f"{page}: asset URLs are not stamped with current content hashes"
        for page in stamp.PAGES
        if (stamp.FRONTEND / page).read_text() != stamp.stamped_page((stamp.FRONTEND / page).read_text())
    ]
    for app in stamp.APPS:
        worker = (stamp.FRONTEND / app.worker).read_text()
        if worker != stamp.stamped_worker(app, worker):
            problems.append(f"{app.worker}: SHELL_FILES or CACHE_NAME out of date")
    for line in problems:
        print("STALE", line)
    print("shell check:", "FAIL (run tools/stamp.py)" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
