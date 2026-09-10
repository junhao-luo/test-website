# Durability Fixes Report

Plan: `2026-09-10-live-realtime-lecture-companion.md`

## Completed

- Frontend component events now use an ordered pending queue and emit one `event_batch` payload at a time. Render cycles acknowledge only the in-flight batch, preserving events received afterward.
- Python validates event batches and the app processes every event sequentially, while retaining single-event compatibility and existing event-ID deduplication.
- Stop drains active transcript item IDs after committing buffered audio and stopping tracks. Known completed items resolve the drain quickly; a completed event with no preceding delta keeps the drain open for the bounded 5-second finalization window.
- Successful translation retries during an inactive session immediately use deterministic transcript upsert when a database is available.
- Locked saved course state remains in selector options through connecting, recording, and stopping even when the course is archived or no active courses remain. Inactive and failed sessions still fall back to the first active course or show the no-active-course error.

## Verification

- Python virtualenv suite: 51 passed.
- Frontend Vitest: 15 passed.
- Frontend TypeScript/Vite build: passed.
- `git diff --check`: passed.

No live API calls, package installs, commits, or unrelated refactors were performed.
