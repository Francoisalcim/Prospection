# Clinical Trials Prospector — memory-safe rewrite

This version is designed to avoid Render memory restarts.

## Main changes

- Does **not** store raw ClinicalTrials.gov study JSON after processing each page.
- Extracts rows page by page and keeps only final extracted rows.
- Deduplicates results by NCT ID while streaming.
- `ALL` searches run in a background job.
- Background jobs export to XLSX when complete, then release the large in-memory data.
- Old jobs and export files are cleaned up automatically.
- Only one background job is allowed by default.

## Parsing rule

The parser uses mixed list mode:

1. Split first on top-level commas.
2. Each comma-separated item is either:
   - a simple medical term, or
   - a Boolean sub-query if it contains uppercase `AND` / `OR`.
3. Lowercase `and` / `or` are normal text.
4. Simple terms are cleaned lightly:
   - `/` becomes a space
   - `&` becomes `and`
   - parentheses are removed but the content is kept
   - repeated spaces are normalized

Examples:

```text
Acne, Wounds and Injuries, Body cellulite OR localized fat reduction
```

becomes separate API searches:

```text
Acne
Wounds and Injuries
Body cellulite OR localized fat reduction
```

## Filters

- Status: ClinicalTrials.gov API filter.
- Phase: local Python filter.
- Date: local Python filter.
- Countries: local Python filter.
- Organization type: local Python filter on lead sponsor.

## Install locally

```bash
pip install flask flask-cors requests openpyxl
python app.py
```

Open:

```text
http://localhost:5000
```

## Render environment variables

Optional:

```text
MAX_SYNC_RESULTS=2000
MAX_RUNNING_JOBS=1
JOB_TTL_MINUTES=45
MAX_ALL_RESULTS=20000
```

If `MAX_ALL_RESULTS` is left empty, ALL has no code cap, but Render may still kill the process if the job is too large.

For a small Render instance, using `MAX_ALL_RESULTS=10000` or `20000` is safer.

## Deployment reminder

Replace these files in your project:

```text
clinical_trials_prospector.py
app.py
templates/index.html
```

Then commit and redeploy.
