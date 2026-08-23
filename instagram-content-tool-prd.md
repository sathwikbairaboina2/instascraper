# PRD: Internal Instagram Content Retrieval Tool

**Status:** Draft
**Last updated:** August 23, 2026

## Overview
An internal tool for content managers to look up any public Instagram profile, browse its posts and Reels in a grid, and download selected media individually at full quality — with a shared record of which profiles the team tracks and who downloaded what. Built on [Instaloader](https://instaloader.github.io/), the open-source library that does the actual Instagram fetching.

## Problem
Content managers need a reliable, shared way to pull reference and source media from public Instagram accounts at full quality, without each person running their own scraper or risking a personal Instagram account.

## Goals
- Look up any public IG profile by username and browse its posts/Reels in a grid
- Select one, several, or all items and download them individually (no ZIP), at max available quality, under a custom filename
- Maintain a shared list of tracked profiles and a log of who did what, when
- Keep Instagram account and IP risk contained to one system-owned identity, not spread across the team

## Non-goals (v1)
- Private/non-public accounts
- Publishing, scheduling, or any write access to Instagram
- Unattended bulk-archiving of an account's full history in one pass
- Per-content-manager Instagram logins

## Users
Internal content managers. Flat access for v1 — no role tiers.

## Functional requirements

| # | Requirement | Priority |
|---|---|---|
| 1 | Enter an Instagram username or ID (public profiles only) | Must |
| 2 | Retrieve and display available posts and Reels for that account | Must |
| 3 | Responsive media grid | Must |
| 4 | Select one, multiple, or all items | Must |
| 5 | Custom base filename for downloads | Must |
| 6 | Download selected files individually, not zipped | Must |
| 7 | Maximum available quality and resolution | Must |
| 8 | Reels retain their audio | Must |
| 9 | Activity log — who did what, when | Must |
| 10 | Persistent list of tracked profiles | Must |

## Constraints & key decisions
- **Instaloader is the core dependency** — the open-source library doing all the actual Instagram interaction (pagination, media URLs, rate-limit handling). Actively maintained, but Instagram periodically rotates the internal API identifiers it relies on, which breaks it every few weeks regardless of how well-paced requests are. This is ongoing maintenance, not a one-time integration.
- Instagram rate-limits by IP and caps anonymous browsing around a dozen recent posts per profile. Requirement 7 (max quality) needs a login regardless, so v1 fetches through one shared, dedicated Instagram account — never individual content managers' credentials.
- All Instagram-bound requests are queued through a single serialized worker, independent of how many content managers are active — this holds regardless of team size.
- Public accounts and internal use only. This sits in ToS gray-area territory, not legal exposure, at this scale.
- Stack: Next.js frontend, NestJS API, DynamoDB + S3, Python fetch worker (Instaloader). Full architecture, schema, and API design covered separately.
