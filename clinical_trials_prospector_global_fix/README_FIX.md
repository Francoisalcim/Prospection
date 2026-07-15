# Clinical Trials Prospector global fix

Replace your current files with:

- `clinical_trials_prospector.py`
- `app.py`
- `templates/index.html`

## What was fixed

1. Robust keyword parser:
   - `diabetes, insulin` -> `(diabetes OR insulin)`
   - `diabetes AND (insulin OR metformin)` stays valid and is no longer corrupted
   - invalid expressions return a clean 400 error instead of crashing

2. API / filtering diagnostics:
   - backend returns API trials fetched vs records kept after filtering
   - frontend displays parsed query, organization filtering, records removed by org filter, and processing errors

3. Validation:
   - status and phase filters are validated before the API call
   - malformed keyword expressions are caught before sending to ClinicalTrials.gov

4. Organization filtering:
   - if no organization type is selected, backend treats it as no organization filter
   - if types are selected, filtering is applied and displayed transparently

## Quick local test

```bash
python app.py
```

Then open:

```text
http://localhost:5000
```

Suggested test queries:

```text
diabetes, insulin, treatment
cancer AND immunotherapy
diabetes AND (insulin OR metformin)
mRNA AND vaccine AND (COVID OR influenza)
```
