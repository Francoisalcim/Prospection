#!/usr/bin/env python3
"""
Flask web server for Clinical Trials Prospector v2
With flexible organization type filtering
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import os
import sys

# Import the updated prospector class
try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("❌ Error: Could not import ClinicalTrialsProspector")
    print("Make sure your backend file is named: clinical_trials_prospector.py")
    print("You can rename clinical_trials_prospector_v2.py to clinical_trials_prospector.py")
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
    """Handle search requests with organization type filtering"""
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
        
        # NEW: Organization type filtering
        org_types = data.get('organizationTypes', ['company'])  # Default to companies only
        
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
        
        # Create new prospector instance with filtering (always include mode)
        global prospector
        prospector = ClinicalTrialsProspector(include_types=org_types)
        
        # Fetch trials
        trials = prospector.fetch_trials(
            keywords=keywords,
            statuses=statuses if statuses else None,
            phases=phases if phases else None,
            max_results=max_results
        )
        
        # Extract companies with filtering
        companies = prospector.extract_companies()
        
        # Prepare companies list for response
        companies_list = []
        for company in sorted(companies.values(), key=lambda x: x['trial_count'], reverse=True):
            role = prospector._get_role_label(company)
            companies_list.append({
                'name': company['name'],
                'role': role,
                'trialCount': company['trial_count'],
                'orgType': company.get('org_type_label', 'Unknown')
            })
        
        # Calculate stats
        sponsors = sum(1 for c in companies.values() if c['lead_count'] > 0)
        collaborators = sum(1 for c in companies.values() if c['collab_count'] > 0)
        
        response_data = {
            'stats': {
                'totalTrials': len(trials),
                'uniqueCompanies': len(companies),
                'sponsors': sponsors,
                'collaborators': collaborators
            },
            'companies': companies_list
        }
        
        print(f"✅ Returning {len(trials)} trials, {len(companies)} organizations")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error in search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Export companies to CSV for PhantomBuster"""
    try:
        if not prospector.companies_data:
            return jsonify({'error': 'No data to export. Please run a search first.'}), 400
        
        filename = prospector.export_to_csv()
        
        if not filename or not os.path.exists(filename):
            return jsonify({'error': 'Failed to generate CSV file'}), 500
        
        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype='text/csv'
        )
        
    except Exception as e:
        print(f"❌ Error in export_csv: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/detailed', methods=['GET'])
def export_detailed():
    """Export detailed trial information to CSV"""
    try:
        if not prospector.trials_data:
            return jsonify({'error': 'No data to export. Please run a search first.'}), 400
        
        filename = prospector.export_detailed_to_csv()
        
        if not filename or not os.path.exists(filename):
            return jsonify({'error': 'Failed to generate CSV file'}), 500
        
        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype='text/csv'
        )
        
    except Exception as e:
        print(f"❌ Error in export_detailed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


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
    return jsonify({'status': 'healthy', 'service': 'clinical-trials-prospector-v2'}), 200


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Get port from environment variable (Render sets this)
    port = int(os.environ.get('PORT', 5000))
    
    # Determine if running in production
    is_production = os.environ.get('RENDER') is not None
    
    print("\n" + "="*60)
    print("🚀 Clinical Trials Prospector v2 - Flask Server")
    print("="*60)
    if is_production:
        print("🌐 Running in PRODUCTION mode (Render)")
        print(f"📱 Port: {port}")
    else:
        print("💻 Running in DEVELOPMENT mode (Local)")
        print(f"📱 Open your browser at: http://localhost:{port}")
        print("📁 Make sure index.html is in the 'templates' folder")
    print("✨ NEW: Organization type filtering enabled")
    print("🛑 Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    app.run(
        debug=not is_production,
        host='0.0.0.0',
        port=port
    )