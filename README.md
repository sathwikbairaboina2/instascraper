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
a convention. All Meta Graph API usage is confined to `api/app/ig/`, so an
Instagram-side breakage has a one-directory blast radius.

Data comes from Meta's Business Discovery API, which sees **public Business
and Creator accounts only**. Personal accounts are invisible to it, and no
workaround exists -- that is a property of the API, not a missing feature.

Profile lookups fetch metadata and thumbnails. Full-resolution media is
fetched only when you select something and press Download, then cached
forever.

## Setup

    cp .env.example .env      # fill in the IG_GRAPH_* values and OUT_DIR
    docker compose build
    docker compose up -d

Open http://localhost:3000.

### Getting the Graph credentials

Business Discovery reads other accounts through an account of your own, so
there is a one-time setup. None of it can be automated.

1. Convert an Instagram account to **Business** or **Creator**.
2. Create or choose a **Facebook Page**, and link the Instagram account to
   it. Business Discovery is only available through the Facebook-Login
   flavour of the API, so this link is mandatory.
3. Create a **Meta developer app** at developers.facebook.com and add the
   Instagram product.
4. Grant the token `instagram_basic`, `pages_show_list`,
   `pages_read_engagement` and `business_management`.
5. Find your Instagram user id: `GET /me/accounts` for the Page id, then
   `GET /{page-id}?fields=instagram_business_account`.
6. Prefer a **Business Manager system-user token**, which does not expire,
   over a long-lived user token, which expires after 60 days.

Put the results in `.env` as `IG_GRAPH_TOKEN`, `IG_GRAPH_USER_ID` and
`IG_GRAPH_VERSION`, then verify without starting the stack:

    cd api && IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py -v

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
- **Token invalid** — the token expired or was revoked. Issue a new one,
  update `.env`, restart, then press "I have fixed it" in the banner.
- **Token not configured** — `IG_GRAPH_TOKEN` is empty. See Setup above.
- **Empty grids and odd errors** — Instagram probably rotated something.
  Run the canary:

      cd api && IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py -v

  A failure there means `api/app/ig/graph_map.py` needs updating -- it is
  the only file that should ever need to change when Meta reshapes a
  response. Re-record the fixtures first:

      cd api && python scripts/capture_graph_fixtures.py nike

## Tests

    cd api && python -m pytest        # backend, no network (203 tests)
    bash scripts/e2e-native.sh        # full stack on the host, no Docker
    bash scripts/e2e.sh               # same suite via Compose
    cd api && IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py

The backend suite runs against an in-memory fake adapter and never touches
the network. The e2e suite seeds a throwaway database under `.e2e/` and runs
the whole stack with `IG_ADAPTER=fake`.

### Local development without Docker

    python -m venv .venv
    .venv/Scripts/python -m pip install -r api/requirements.txt
    cd web && npm install

Then use `scripts/e2e-native.sh`, or start the two processes by hand:

    cd api && DB_PATH=../data/app.db MEDIA_DIR=../data/media \
      OUT_DIR_CONTAINER=../downloads \
      ../.venv/Scripts/python -m uvicorn app.main:app --port 8000 --workers 1

    cd web && API_ORIGIN=http://127.0.0.1:8000 npm run dev
