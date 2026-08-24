# Reel downloads through yt-dlp, under a local cap

**Date:** 2026-08-25
**Status:** approved, not yet implemented

## Why

Business Discovery indexes reels but will not serve their video. Probed on
2026-08-24 against `thevarunmayya`, `nike` and `natgeo`: `FEED` items always
carry `media_url`, `REELS` never do. Meta publishes the thumbnail and keeps
the file. So the app can show a reel, name it, and cache its thumbnail --
and then cannot download the one thing the user wanted.

yt-dlp closes that hole. This design uses it for nothing else.

## What the probe established

Run on 2026-08-25 against a real reel, anonymous, no cookies:

```
[Instagram] Dcbga5iBQgR: Checking post accessibility
[Instagram] Dcbga5iBQgR: Downloading webpage
[info] Dcbga5iBQgR: Downloading 1 format(s): 3
[download] 100% of 3.74MiB in 00:00:00
```

- **Anonymous access works.** The 429 measured earlier in this project was on
  Instagram's `web_profile_info` JSON endpoint. yt-dlp goes via the post page,
  which is a different path and currently open.
- **Roughly two instagram.com requests per reel** before the CDN transfer.
  A cap counted in reels is really a cap on twice that many requests.
- **One pre-muxed mp4, no merge.** ffmpeg is not required, and must not be a
  startup dependency.
- yt-dlp 2026.08.19 is installed in the project venv.

## Scope

Reels only, as a fallback, and only where Graph has already said it has
nothing. Every scraped request is therefore for a file that is genuinely
unobtainable through the sanctioned API. Feed videos and carousel video
children keep coming from Graph, which serves them today.

Rejected: using yt-dlp for all video, or for all media. Both would scrape for
files Meta already hands us legitimately.

## Honesty about what this is

Automated downloading from instagram.com is against Instagram's terms
regardless of how politely it is done. The caps below reduce footprint; they
do not make this sanctioned, and nothing in the UI should imply otherwise.

No user-agent rotation and no randomised "human-like" sleeps. Instagram
fingerprints request patterns and account behaviour, not user-agent strings,
so disguise buys exposure without protection. What this design does instead
is genuinely do less: a hard cap, a fixed floor between requests, and a
refusal rather than a queue.

## Caps

| Window | Limit | Env |
| --- | --- | --- |
| Rolling hour | 20 reels | `IG_REEL_MAX_PER_HOUR` |
| Rolling day | 100 reels | `IG_REEL_MAX_PER_DAY` |

Both overridable, like `IG_MIN_INTERVAL`, so tightening them never needs a
code change. The numbers are conservative rather than authoritative: Instagram
publishes no thresholds, and every "safe limit" in circulation is anecdote.
At 20/hour the app makes about 40 page requests an hour, one per ninety
seconds.

**Attempts count, not successes.** A failed download still sent the requests
the cap exists to limit. Counting only successes would let a run of failures
spend real-world exposure while the counter reads zero.

## Quota store

```sql
CREATE TABLE IF NOT EXISTS quota_events (
  id    INTEGER PRIMARY KEY,
  kind  TEXT NOT NULL,
  at    TEXT NOT NULL
);
```

`kind` is `reel_download` for now; the column exists so a second limited
activity does not need a second table. Counting is a `COUNT(*)` against each
window edge. Rows older than seven days are pruned on insert -- small table,
a few days of history kept.

**Reset times are exact**: `oldest event still inside the window + the window
length`. We own this ledger, so unlike Meta's quota there is nothing to
estimate and the UI can show a real countdown.

The table lives in the live adapter's database, so switching to the fake
adapter would show a separate count. Harmless -- the fake adapter never
scrapes -- but recorded here so it is not later mistaken for a bug.

## Downloader

`api/app/ig/reels.py`, one class, subprocess-based:

```
sys.executable -m yt_dlp
  --no-warnings --no-playlist --no-progress
  -f mp4/best[ext=mp4]/best
  -o <dest>
  https://www.instagram.com/reel/<shortcode>/
```

Invoked through `sys.executable`, not a PATH lookup: yt-dlp ships in the
project venv, so there is no `which` to get wrong on Windows and no "install
this first" instruction.

- **Hard timeout**, `IG_REEL_TIMEOUT`, default 120s. One worker thread serves
  the whole app; a hung subprocess without a timeout stalls every job.
- **Its own pacer interval**, `IG_REEL_MIN_INTERVAL`. instagram.com is a third
  host alongside graph.facebook.com and the CDN, with its own budget. Fixed,
  not jittered: at 20/hour the cap already forces about three minutes between
  reels, so randomising the floor changes nothing real.
- **The runner is injected** as a callable returning `(returncode, stdout,
  stderr)`, so tests never spawn a process.
- **stderr is mapped to real error types** rather than one generic failure:
  rate-limited and login-required become `IgRateLimited` and `IgChallenge`,
  removed or private posts become `IgNotFound`, anything else `IgTransient`.

**One place records, one place refuses.** The downloader writes the quota
event itself, immediately before spawning the process, and it is the only
code that ever writes one. Callers check the cap to decide whether to offer
the action; they never record. The script this replaces recorded in two
methods and spent two units of a twenty-unit budget on a single reel.

If the cap is already spent when the downloader is called -- the enqueue
check having raced or been bypassed -- it raises `IgQuotaSpent` without
spawning anything. The check at enqueue is the user-facing gate; this one is
the backstop that makes the limit true.

## Integration

`GraphAdapter` takes an optional `reel_downloader` collaborator.

`_refresh` stops raising when it finds a post carrying no sources and returns
empty instead. `fetch_media` then decides:

1. sources from the hint, minus any with no url
2. if empty, refresh
3. still empty and a downloader is configured -- check the cap, then download
4. still empty and no downloader -- raise the existing "Meta publishes no
   downloadable file" message

The file lands in the item directory as `full.mp4` with a `media_files` row,
exactly like a Graph download. Download-to-folder, the SAVED tab, the lightbox
and the cached count therefore need no changes at all.

This does mean `GraphAdapter` is no longer purely a Graph client. That is a
real smell, accepted because the fallback is defined by a Graph limitation and
fires nowhere else. The alternative -- a wrapping adapter implementing the
whole `IgAdapter` protocol to special-case one method -- costs more than it
buys.

### A new error type

`IgQuotaSpent`, failed terminally by the worker **without tripping the
breaker**. A spent local cap must not back off the Graph API, which has its
own quota and is nowhere near it.

## Refusing at the cap

Refusal happens at enqueue, not at download. `/api/media/ensure` checks the
cap for uncached reels and returns a `quota` status with the reset time
instead of queueing. Nothing runs unattended; the app is idle because you are
at the cap, not because something failed quietly hours later.

Rejected: queueing and draining as the window slides. Sustained unattended
automation is the behaviour the caps exist to prevent, and a cap that merely
meters is not the "strict limit" asked for.

## UI

`/api/status` gains:

```json
"reel_limits": {
  "hour": {"used": 7, "max": 20, "resets_at": "2026-08-25T01:14:00+00:00"},
  "day":  {"used": 31, "max": 100, "resets_at": "2026-08-25T18:02:00+00:00"}
}
```

**Header:** two small progress bars, `HOUR 7/20` and `DAY 31/100`, swapping
the label for the reset time at the cap. Proportion is legible before any
digit is read, which is the point of showing progress at all.

The fill runs green to orange to red as the window fills:

| Used | Fill | Meaning |
| --- | --- | --- |
| under 50% | `#2ecc71` | plenty of headroom |
| 50% to 84% | `#fcb045` | over half spent |
| 85% and up | `#ed4956` | nearly or fully spent |

`#fcb045` is the warm end of the story gradient and `#ed4956` is the palette's
existing destructive colour, so only the green is new. The Instagram palette
has no success colour, because Instagram's UI never needs to say "healthy" --
a meter does.

These bars are the one place a gradient would actively mislead: a fill whose
colour changes along its own length cannot also encode how full it is. Flat
colour per state, and the story gradient stays on the avatar ring.

**At the action:** the header cannot explain a dead button, so the download
control also greys out and says why -- "hourly reel cap spent, resets 01:14".
A control that silently stops working is worse than one that refuses out loud.

## Testing

- Window arithmetic against a fake clock: events ageing out, reset time,
  both caps, the boundary at exactly the window edge.
- Attempts recorded on failure, not only on success.
- Command construction, and each stderr shape mapping to its error type,
  through the injected runner.
- Timeout produces a real error rather than hanging.
- Adapter falls back only when Graph has nothing, and never when Graph has a
  url.
- `IgQuotaSpent` fails the job without tripping the breaker.
- `/api/media/ensure` refuses instead of queueing when the cap is spent.
- e2e: the header renders both bars from a stubbed status, and the refusal
  message appears on the control.
- No test may invoke yt-dlp or touch the network.

## Order of work

1. Quota store and window arithmetic
2. Reel downloader with an injected runner
3. `IgQuotaSpent` and the worker branch
4. Adapter fallback
5. `/api/status` and refusal in `ensure`
6. Header bars and the refusal on the control

Backend first throughout, so every UI step lands on numbers that already move.
