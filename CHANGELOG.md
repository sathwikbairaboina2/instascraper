# Changelog

A record of what shipped, in the order it shipped, with the reasoning that is
not obvious from the diffs. Roadmap phases (`P5`, `P7` and so on) match the
table in `docs/handbook.html`.

## 2026-08-24

### Interface rebuilt on Ant Design (`4a1be96`)

Replaced the hand written CSS with antd 6.6.1. Verified before adopting: its
peer range is `react >=18`, so React 19 works with no patch package. Added
`@ant-design/nextjs-registry` for App Router SSR and `@ant-design/icons`.

The profile screen became a three pane media tool: a rail with lookup and
tracked accounts, a contact sheet grid with the newest post featured, and an
inspector holding metadata and the download form. Five themes ship as a real
switcher, persisted per browser. Each theme declares its own `onAccent` text
colour because antd puts white on the accent, which fails contrast on the
lighter ones.

Polling limits, since the shared shell had added pollers to every route:

| | Before | After |
|---|---|---|
| Visible tab | 0.80 req/s | 0.58 req/s |
| Hidden tab | 0.80 req/s | 0.00 req/s |

A hidden tab now stops its timer entirely and refreshes once on return. None
of this changes Instagram traffic, which is gated by the single worker and the
pacer rather than by how often the UI polls.

Six defects surfaced during the port, all real rather than test artifacts:

- a single selection had no download form at all, so you could only download
  two or more posts
- the lookup button was `display: none`, reachable only by pressing Enter
- saved selections sat inside the selection block, so clearing the selection
  made them unreachable
- the preview control and the checkbox existed only on hover, so neither
  keyboard nor touch could reach them
- the lightbox test id landed on antd's zero size modal wrapper
- `scripts/e2e-native.sh` deleted `.e2e` before killing leftover servers, so a
  stale API holding the SQLite file aborted the whole run under `set -e`

## 2026-08-23

### Anonymous mode, and honouring the wait Instagram asks for (`dd33099`)

The adapter no longer hard requires a login. With no credentials it runs
unauthenticated and reports what Instagram says instead of failing to start.

Measured twice from a cold IP: Instagram returns 429 on the **first**
anonymous profile lookup. Anonymous browsing does not currently work. The mode
exists so the app degrades honestly, not because it retrieves anything.

Three changes that lower the risk of the IP being blocked:

- Instaloader handles a 429 by sleeping about thirty minutes inside `sleep()`
  and retrying, which blocked the single worker with no breaker trip and
  nothing in the UI. It now raises, which is the override Instaloader
  documents.
- The refused wait rides on `IgRateLimited.retry_after` and the breaker
  honours it. `IG_BACKOFF` is a floor, never a licence to return sooner than
  asked. Instagram wanted 1818s while `IG_BACKOFF` is 900s, so the old code
  would have retried at half the requested interval, indefinitely.
- In anonymous mode a 429 trips the breaker permanently. Waiting cannot fix a
  refusal, so a timer based retry is pure added load.

### P10, the Instaloader version bump drill (`680867e`)

`scripts/bump-instaloader.sh` runs the contract tests, bumps the pin,
reinstalls, re-runs the contract tests, then runs the live canary. A failed
install or contract run restores the previous pin.

It refuses to call a bump verified when the canary cannot run: a green
contract suite only proves the parsers still agree with checked in fixtures,
not with Instagram. Exercised for real against a 4.14.1 to 4.15.3 bump. 4.15.3
passes both suites, so the pin was reverted to 4.14.1 rather than moved on
unverified evidence.

### P8 and P9, preview, filters, and a paging fix (`89a41b0`)

The paging bug came first: the grid always requested `limit=120&offset=0`
while "Load more" kept indexing 36 more, so every post past the newest 120 was
invisible even though the API held it.

Then a lightbox reachable from a per tile control, filters by kind, cached
state and caption text, and named selections in `localStorage`.

Three more bugs found by running it rather than reading it: an `opacity: 0`
control still receives pointer events, so every tile had an invisible button
swallowing clicks meant for its neighbour; "Select all shown" was a permanent
no-op if pressed before the grid loaded; and `usePolling` replaced state every
four seconds even when the payload was identical, which took the e2e suite
from 3.0 minutes to 43 seconds once fixed.

### P7, per item errors and retry (`6a8e1e2`)

`media_items.full_error` already existed in the schema but never left the
database. A failed tile now shows the reason with its own retry control, and
the selection bar names the failing shortcodes instead of saying "some items
failed".

### P5, the Compose path verified (`e349486`)

Both images build, `scripts/e2e.sh` runs green in containers, the production
stack boots with the worker alive, port 8000 stays unpublished, and a single
`--workers 1` process was confirmed inside the container.

Booting it also caught a defect: the startup log advertised JSON while
emitting a Python dict repr with single quotes, which parses in no JSON
reader (`38cb98f`).

### v1 (`1d05b47` through `7afd955`)

Built in one pass as 23 TDD tasks: settings and schema, path and atomic write
helpers, the adapter contract with an in memory fake, job queue, circuit
breaker, startup sweep, pacer and the single worker thread, three job
handlers, the real Instaloader adapter, the login entrypoint, sixteen API
routes, the Next.js frontend, and the e2e suite.

Two bugs shipped past a green unit suite and only appeared under a real
server (`755b271`): FastAPI resolves a sync dependency and runs the sync
endpoint on different threadpool threads, so a thread local SQLite connection
was used off thread and every request returned 500; and `make_adapter` built
an empty `FakeAdapter`, so a seeded database referenced posts the running
server had never heard of. `TestClient` runs on one thread and could see
neither.

## Still open

- **No real Instagram post has ever been fetched.** The production database is
  empty and no session file has ever existed. Needs a dedicated account in
  `.env` and one `python -m app.ig.login` run. This is `P6`.
- **The lightbox fetch does not swap to full quality.** The API is proven
  fine: `ensure` queues and the media list reports `ready` on the next poll.
  The cause is in the React layer and is not yet found. An optimistic spinner
  hides the symptom.
