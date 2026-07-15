# Clinical Trials Prospector — Async ALL Fix

This version keeps normal searches synchronous, but runs `Max Results = ALL` as a background job.

## Why

A browser request to `/api/search` can be cut by the browser, Flask, Render, or another hosting layer if it runs for too long. When that happens the frontend receives an empty or HTML error response and shows `Unexpected end of JSON input`.

## What changed

### Backend

- `clinical_trials_prospector.py`
  - `fetch_trials(..., max_results=None)` now means fetch all pages until ClinicalTrials.gov returns no `nextPageToken`.
  - Added optional `progress_callback` for real-time progress updates.

- `app.py`
  - `/api/search` remains for limited searches.
  - `/api/search/start` starts a background job for ALL.
  - `/api/search/status/<job_id>` returns progress and final results.
  - `/api/export/xlsx/<job_id>` exports a completed background job.

### Frontend

- `templates/index.html`
  - `ALL studies` now starts a background job.
  - The loading text updates while pages are fetched.
  - Export uses the job-specific export endpoint when the search was run as ALL.
  - JSON parsing is safer, so non-JSON server errors are explained clearly.

## How to use

Replace your existing files with:

- `clinical_trials_prospector.py`
- `app.py`
- `templates/index.html`

Then run:

```bash
python app.py
```

For large searches, select:

```text
Max Results = ALL studies (background job)
```

The UI will show progress like:

```text
Background search running — stage: fetching, fetched: 1200 / 8427
```

## Limitation

This uses an in-memory job store. It is good for a PoC or local use. If the server restarts, jobs are lost. For production, replace the in-memory `JOBS` dictionary with Redis/RQ, Celery, a database, or another persistent job queue.
