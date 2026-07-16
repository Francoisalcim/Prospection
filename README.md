# Clinical Trials Prospector — rewritten version

This package replaces the three core files:

```text
clinical_trials_prospector.py
app.py
templates/index.html
```

## Main parsing rule

The parser now supports a mixed mode:

1. Split the user input first on top-level commas.
2. Each comma-separated item can be either:
   - a simple medical term; or
   - a Boolean sub-query using uppercase `AND` / `OR`.
3. Lowercase `and` / `or` are treated as normal wording.
4. Parentheses and commas inside parentheses are handled safely.
5. Simple terms are cleaned before API search:
   - `/` becomes a space
   - `&` becomes `and`
   - parentheses are removed but their content is kept
   - extra spaces are normalized

Examples:

```text
Acne, Cellulite, Wounds and Injuries
```

runs three independent searches:

```text
Acne
Cellulite
Wounds and Injuries
```

```text
Acne, Body cellulite OR localized fat reduction
```

runs:

```text
Acne
Body cellulite OR localized fat reduction
```

## Filtering logic

- Status is sent to the ClinicalTrials.gov API as `filter.overallStatus`.
- Phase is applied locally from `designModule.phases`.
- Date is applied locally from `statusModule` date fields.
- Countries are applied locally from `contactsLocationsModule.locations.country`.
- Organization type is applied locally on the extracted lead sponsor.

## Deduplication

All multi-term searches are deduplicated by `nct_id`.

## ALL searches

`ALL` uses a background job:

```text
/api/search/start
/api/search/status/<job_id>
/api/export/xlsx/<job_id>
```

This avoids the browser waiting on one long blocking request.

## Install

Replace your existing files with the files in this folder, then run:

```bash
pip install flask flask-cors requests openpyxl
python app.py
```

Open:

```text
http://localhost:5000
```

## Production note

The background job store is in-memory. For a production deployment, replace it with Redis/RQ, Celery, or a database-backed job store.
