#!/usr/bin/env python3
"""
Flask web server for Clinical Trials Prospector v3
With flexible organization type filtering AND data extraction options
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import os
import sys

# Import the updated prospector class (V3)
try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("❌ Error: Could not import ClinicalTrialsProspector")
    print("Make sure your backend file is named: clinical_trials_prospector.py")
    print("You can rename clinical_trials_prospector_v3.py to clinical_trials_prospector.py")
    sys.exit(1)

app = Flask(__name__)
CORS(app)

# Store the prospector instance
prospector = ClinicalTrialsProspector()


@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')


@app.route('/api/search', methods=['POST'])
def search():
    """Handle search requests with organization type filtering and data extraction options"""
    try:
        data = request.json
        
        # Parse keywords
        keywords_raw = data.get('keywords', '').strip()
        if not keywords_raw:
            return jsonify({'error': 'Please provide at least one keyword'}), 400
        
        keywords = [k.strip() for k in keywords_raw.split(',') if k.strip()]
        statuses = data.get('statuses', [])
        phases = data.get('phases', [])
        max_results_raw = data.get('maxResults', '500')
        
        # Organization type filtering
        org_types = data.get('organizationTypes', ['company'])
        
        # NEW: Data extraction options
        data_extractions = data.get('dataExtractions', ['sponsors'])
        
        # Handle "ALL" option
        if max_results_raw == 'ALL':
            max_results = 10000
        else:
            max_results = int(max_results_raw)
        
        print(f"🔍 Search request:")
        print(f"   Keywords: {keywords}")
        print(f"   Statuses: {statuses}")
        print(f"   Phases: {phases}")
        print(f"   Max Results: {max_results}")
        print(f"   Organization Types: {org_types}")
        print(f"   Data Extractions: {data_extractions}")
        
        # Create new prospector instance with filtering and extraction options
        global prospector
        prospector = ClinicalTrialsProspector(
            include_types=org_types,
            extraction_options=data_extractions
        )
        
        # Fetch trials
        trials = prospector.fetch_trials(
            keywords=keywords,
            statuses=statuses if statuses else None,
            phases=phases if phases else None,
            max_results=max_results
        )
        
        # Extract data based on selected options
        extracted_data = prospector.extract_data()
        
        # Prepare summary statistics
        total_trials = len(trials)
        total_extracted = len(extracted_data)
        
        # Calculate unique organizations (if sponsors is selected)
        unique_orgs = 0
        sponsors_count = 0
        collaborators_count = 0
        
        if 'sponsors' in data_extractions:
            unique_sponsors = set()
            for item in extracted_data:
                if item.get('lead_sponsor'):
                    unique_sponsors.add(item['lead_sponsor'])
                    sponsors_count += 1
                if item.get('collaborators'):
                    collab_list = item['collaborators'].split('; ')
                    collaborators_count += len([c for c in collab_list if c])
            unique_orgs = len(unique_sponsors)
        
        # Prepare preview data for display (first 100 records)
        preview_data = extracted_data[:100]
        
        response_data = {
            'stats': {
                'totalTrials': total_trials,
                'extractedRecords': total_extracted,
                'uniqueOrganizations': unique_orgs,
                'dataFieldsExtracted': len(data_extractions)
            },
            'preview': preview_data,
            'dataFields': data_extractions
        }
        
        print(f"✅ Returning {total_extracted} extracted records")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error in search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Export extracted data to Excel (XLSX)"""
    try:
        if not prospector.extracted_data:
            return jsonify({'error': 'No data to export. Please run a search first.'}), 400
        
        # Use XLSX export instead of CSV
        filename = prospector.export_to_xlsx()
        
        if not filename or not os.path.exists(filename):
            return jsonify({'error': 'Failed to generate Excel file'}), 500
        
        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"❌ Error in export: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/xlsx', methods=['GET'])
def export_xlsx():
    """Alternative endpoint for XLSX export"""
    return export_csv()


@app.route('/api/data-fields', methods=['GET'])
def get_data_fields():
    """Return available data extraction fields for the UI"""
    fields_info = []
    for key, info in ClinicalTrialsProspector.DATA_EXTRACTION_OPTIONS.items():
        fields_info.append({
            'key': key,
            'label': info['label'],
            'description': info['description'],
            'default': info.get('default', False)
        })
    return jsonify({'dataFields': fields_info})


@app.route('/api/organization-types', methods=['GET'])
def get_organization_types():
    """Return available organization types for the UI"""
    types_info = []
    for key, info in ClinicalTrialsProspector.ORGANIZATION_TYPES.items():
        types_info.append({
            'key': key,
            'label': info['label'],
            'keywords': info['keywords']
        })
    return jsonify({'organizationTypes': types_info})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({'status': 'healthy', 'service': 'clinical-trials-prospector-v3'}), 200


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Get port from environment variable (Render sets this)
    port = int(os.environ.get('PORT', 5000))
    
    # Determine if running in production
    is_production = os.environ.get('RENDER') is not None
    
    print("\n" + "="*70)
    print("🚀 Clinical Trials Prospector v3 - Flask Server")
    print("="*70)
    if is_production:
        print("🌐 Running in PRODUCTION mode (Render)")
        print(f"📱 Port: {port}")
    else:
        print("💻 Running in DEVELOPMENT mode (Local)")
        print(f"📱 Open your browser at: http://localhost:{port}")
        print("📁 Make sure index.html is in the 'templates' folder")
    print("✨ NEW: Flexible data extraction (10 data categories)")
    print("✨ Organization type filtering (8 categories)")
    print("🛑 Press Ctrl+C to stop")
    print("="*70 + "\n")
    
    app.run(
        debug=not is_production,
        host='0.0.0.0',
        port=port
    )