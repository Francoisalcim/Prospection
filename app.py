#!/usr/bin/env python3
"""
Flask web server for Clinical Trials Prospector
Simple interface that serves HTML and processes requests
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import os
import sys

# Import your ClinicalTrialsProspector class
# Make sure the file is named clinical_trials_prospector.py
try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("❌ Error: Could not import ClinicalTrialsProspector")
    print("Make sure your backend file is named: clinical_trials_prospector.py")
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
    """Handle search requests"""
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
        
        # Handle "ALL" option
        if max_results_raw == 'ALL':
            max_results = 10000  # Reasonable upper limit
        else:
            max_results = int(max_results_raw)
        
        print(f"🔍 Search request: keywords={keywords}, statuses={statuses}, phases={phases}, max={max_results}")
        
        # Create new prospector instance for this search
        global prospector
        prospector = ClinicalTrialsProspector()
        
        # Fetch trials
        trials = prospector.fetch_trials(
            keywords=keywords,
            statuses=statuses if statuses else None,
            phases=phases if phases else None,
            max_results=max_results
        )
        
        # Extract companies (automatically filters out universities/institutes)
        companies = prospector.extract_companies()
        
        # Prepare companies list for response
        companies_list = []
        for company in sorted(companies.values(), key=lambda x: x['trial_count'], reverse=True):
            role = prospector._get_role_label(company)
            companies_list.append({
                'name': company['name'],
                'role': role,
                'trialCount': company['trial_count']  # Match what HTML expects
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
        
        print(f"✅ Returning {len(trials)} trials, {len(companies)} companies")
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


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    print("\n" + "="*60)
    print("🚀 Clinical Trials Prospector - Flask Server")
    print("="*60)
    print("📱 Open your browser at: http://localhost:5000")
    print("📁 Make sure index.html is in the 'templates' folder")
    print("🛑 Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    # Get port from environment variable (Render sets this)
    port = int(os.environ.get('PORT', 5000))
    
    # Must use 0.0.0.0 and environment PORT
    app.run(debug=False, host='0.0.0.0', port=port)
