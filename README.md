# instascraper

Local, single-user tool for browsing public Instagram profiles and pulling
media at full quality into a folder on this machine.

- Design: `docs/superpowers/specs/2026-08-23-instascraper-design.md`
- Plan: `docs/superpowers/plans/2026-08-23-instascraper.md`

## How it works

Two containers. `web` is Next.js and proxies `/api/*` to `api`. `api` is
FastAPI on uvicorn with `--workers 1`, running the HTTP event loop plus
exactly one fetch worker thread. That worker thread is the only code that
talks to Instagram, which makes request serialization structural rather than
a convention. All Instaloader usage is confined to `api/app/ig/`, so an
Instagram-side breakage has a one-directory blast radius.

Profile lookups fetch metadata and thumbnails. Full-resolution media is
fetched only when you select something and press Download, then cached
forever.

## Setup

    cp .env.example .env      # fill in IG_USERNAME, IG_PASSWORD, OUT_DIR
    docker compose build
    docker compose run --rm api python -m app.ig.login
    docker compose up -d

Open http://localhost:3000.

## Everyday use

Enter a username, browse the grid, click tiles to select (shift-click for a
range), type a base filename, and press Download. Files land in `OUT_DIR`
named `base_01.jpg`, `base_02.mp4`, and so on. Carousel slides get letter
suffixes: `base_07a.jpg`, `base_07b.jpg`.

Keep the tab open while a download runs — the browser drives the flow. If you
close it, the media that was already fetched stays cached, so re-selecting
finishes immediately.

## When the banner appears

- **Rate limited** — the worker paused itself. Nothing to do; it resumes.
- **Session invalid** — run the login command above, then press
  "I have fixed it" in the banner.
- **Empty grids and odd errors** — Instagram probably rotated something.
  Run the canary:

      cd api && python -m pytest -m live

  A failure there means `api/app/ig/adapter.py` needs updating. That is the
  only file that should ever need to change for this class of break.

## Tests

    cd api && python -m pytest        # backend, no network (125 tests)
    bash scripts/e2e-native.sh        # full stack on the host, no Docker
    bash scripts/e2e.sh               # same suite via Compose
    cd api && python -m pytest -m live   # opt-in, hits Instagram

The backend suite runs against an in-memory fake adapter and never touches
the network. The e2e suite seeds a throwaway database under `.e2e/` and runs
the whole stack with `IG_ADAPTER=fake`.

### Local development without Docker

    python -m venv .venv
    .venv/Scripts/python -m pip install -r api/requirements.txt
    cd web && npm install

Then use `scripts/e2e-native.sh`, or start the two processes by hand:

    cd api && DB_PATH=../data/app.db MEDIA_DIR=../data/media \
      SESSION_DIR=../data/session OUT_DIR_CONTAINER=../downloads \
      ../.venv/Scripts/python -m uvicorn app.main:app --port 8000 --workers 1

    cd web && API_ORIGIN=http://127.0.0.1:8000 npm run dev
