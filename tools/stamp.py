#!/usr/bin/env python3
"""Stamp frontend asset URLs with content hashes. Run before every frontend deploy.

There are two installable apps: the POS (index.html, pos.html, sw.js) and the KEYPOS
Sheet app (sheet/index.html, sheet/sw.js). For each:

- Every script and stylesheet URL in its pages gets ?v=<first 8 hex of its md5>, so
  browsers (and nginx's 1-year cache headers) fetch a file again only when it changed.
- Its service worker's SHELL_FILES is rebuilt from those URLs plus its fixed shell files,
  and CACHE_NAME becomes a hash of the whole shell, so a deploy always installs a fresh
  offline copy.

tests/check-shell.py fails when a stamp is stale.
    python3 tools/stamp.py
"""
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
ASSET = re.compile(r'((?:src|href)=")/?((?:js|css|sheet)/[^"?]+\.(?:js|css))(?:\?v=[^"]*)?(")')


@dataclass(frozen=True)
class App:
    pages: tuple[str, ...]
    worker: str
    fixed: tuple[str, ...]
    cache: str


APPS = (
    App(
        pages=("index.html", "pos.html"),
        worker="sw.js",
        fixed=("/index.html", "/pos.html", "/manifest.json", "/icons/icon-192.png", "/icons/icon-512.png"),
        cache="keypos-shell",
    ),
    App(
        pages=("sheet/index.html",),
        worker="sheet/sw.js",
        fixed=("/sheet/index.html", "/sheet/manifest.json", "/sheet/icon-192.png", "/sheet/icon-512.png"),
        cache="keypos-sheet",
    ),
)
PAGES = tuple(page for app in APPS for page in app.pages)


def digest(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()[:8]


def asset_url(path: str) -> str:
    return f"/{path}?v={digest((FRONTEND / path).read_bytes())}"


def stamped_page(html: str) -> str:
    return ASSET.sub(lambda m: m.group(1) + asset_url(m.group(2)) + m.group(3), html)


def page_assets(html: str) -> list[str]:
    return [asset_url(m.group(2)) for m in ASSET.finditer(html)]


def app_assets(app: App) -> list[str]:
    return [url for page in app.pages for url in page_assets((FRONTEND / page).read_text())]


def stamped_worker(app: App, worker: str) -> str:
    shell = list(app.fixed) + sorted(set(app_assets(app)))
    files = ",\n".join(f'  "{url}"' for url in shell)
    worker = re.sub(r"var SHELL_FILES = \[[^\]]*\];", f"var SHELL_FILES = [\n{files}\n];", worker, count=1)
    pages = b"".join((FRONTEND / p).read_bytes() for p in app.pages)
    cache = digest(pages + "".join(shell).encode())
    return re.sub(r'var CACHE_NAME = "[^"]*";', f'var CACHE_NAME = "{app.cache}-{cache}";', worker, count=1)


def stamp() -> list[str]:
    """Rewrite the pages and service workers; returns the files that changed."""
    changed = []
    for page in PAGES:
        path = FRONTEND / page
        before = path.read_text()
        after = stamped_page(before)
        if after != before:
            path.write_text(after)
            changed.append(page)
    for app in APPS:
        worker_path = FRONTEND / app.worker
        before = worker_path.read_text()
        after = stamped_worker(app, before)
        if after != before:
            worker_path.write_text(after)
            changed.append(app.worker)
    return changed


if __name__ == "__main__":
    changed = stamp()
    print("stamped:", ", ".join(changed) if changed else "nothing changed")
    sys.exit(0)
