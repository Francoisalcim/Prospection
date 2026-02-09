# Clinical Trials Prospector

A tool to search ClinicalTrials.gov for commercial sponsors and collaborators, automatically filtering out universities, institutes, and hospitals.

## Features

✓ **Automatic Filtering**: Excludes universities, institutes, hospitals, research centers  
✓ **Python Backend**: Easy to customize and understand  
✓ **Simple Web Interface**: Clean HTML interface for searches  
✓ **Export Options**: CSV for PhantomBuster or detailed data  
✓ **Flexible Search**: Filter by keywords, status, and phase  

## Installation

1. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

2. **Run the application:**
```bash
python app.py
```

3. **Open your browser:**
Navigate to `http://localhost:5000`

## Usage

### Web Interface

1. Enter keywords (comma-separated) like: `diabetes, CAR-T therapy`
2. Optionally select study statuses and phases
3. Choose max results (100-1000 or ALL)
4. Click "Search Clinical Trials"
5. Export results as CSV

### Command Line (Python Only)

You can also use the backend directly without the web interface:

```python
from clinical_trials_backend import ClinicalTrialsProspector

# Create instance
prospector = ClinicalTrialsProspector()

# Search for trials
trials = prospector.fetch_trials(
    keywords=['diabetes', 'insulin'],
    statuses=['RECRUITING', 'COMPLETED'],
    phases=['PHASE2', 'PHASE3'],
    max_results=500
)

# Extract companies (automatically filters out universities/institutes)
companies = prospector.extract_companies()

# Print summary
prospector.print_summary()

# Export to CSV
prospector.export_to_csv('my_results.csv')
prospector.export_detailed_to_csv('detailed_results.csv')
```

## What Gets Filtered Out

The tool automatically excludes organizations containing these keywords:
- university, université, universität, universidad
- institute, institut, instituto
- college, school
- hospital, medical center, health system
- foundation, fundación
- research center/centre
- academy, académie

## Customization

### Add More Exclusion Keywords

Edit `clinical_trials_backend.py` and add to the `EXCLUDE_KEYWORDS` list:

```python
EXCLUDE_KEYWORDS = [
    'university', 'universite', 'universität', 'universidad',
    'institute', 'institut', 'instituto',
    # Add your own keywords here:
    'clinic', 'clinique',
    'laboratory', 'laboratoire'
]
```

### Change Search Logic

The `is_company()` method determines what gets filtered:

```python
def is_company(self, name: str) -> bool:
    """Check if the organization name is a company"""
    if not name:
        return False
        
    name_lower = name.lower()
    
    # Add custom logic here
    for keyword in self.EXCLUDE_KEYWORDS:
        if keyword in name_lower:
            return False
    
    return True
```

## File Structure

```
clinical-trials-prospector/
├── app.py                          # Flask web server
├── clinical_trials_backend.py      # Core logic (API calls, filtering, export)
├── requirements.txt                # Python dependencies
├── templates/
│   └── index.html                 # Web interface
└── README.md                      # This file
```

## API Endpoints

The Flask app provides these endpoints:

- `GET /` - Main web interface
- `POST /api/search` - Search clinical trials
- `GET /api/export/csv` - Export companies to CSV
- `GET /api/export/detailed` - Export detailed trial data

## Export Formats

### CSV for PhantomBuster
Contains:
- Company Name
- Role (Lead Sponsor / Collaborator / Both)
- Lead Sponsor Mentions
- Collaborator Mentions
- Total Mentions
- LinkedIn Search URL

### Detailed CSV
Contains:
- NCT ID
- Title
- Status
- Phase
- Lead Sponsor
- All Collaborators
- Conditions
- Start Date
- ClinicalTrials.gov URL

## Troubleshooting

**Problem**: "Module not found" error  
**Solution**: Make sure you installed requirements: `pip install -r requirements.txt`

**Problem**: "Address already in use"  
**Solution**: Change the port in `app.py`: `app.run(port=5001)`

**Problem**: No results returned  
**Solution**: Try broader keywords or remove status/phase filters

**Problem**: Getting universities in results  
**Solution**: Check if they use alternate names. Add those keywords to `EXCLUDE_KEYWORDS`

## Example Searches

**CAR-T Therapy Companies:**
```
Keywords: CAR-T, cell therapy
Status: Recruiting, Active
Phase: Phase 1, Phase 2
```

**Diabetes Drug Developers:**
```
Keywords: diabetes, insulin, glucose
Status: Recruiting, Completed
Phase: Phase 2, Phase 3
```

**COVID-19 Vaccine Makers:**
```
Keywords: COVID-19, coronavirus, vaccine
Status: Completed
Phase: Phase 3
```

## License

This is a tool for research purposes. Please respect ClinicalTrials.gov terms of service and rate limits.

## Tips

- Start with 100-500 results to test your filters
- Use specific therapeutic area keywords for better targeting
- Export to CSV for easy import into CRM or prospecting tools
- The Python backend can be easily modified for your specific needs
- Check the console output for real-time progress and statistics
