#!/usr/bin/env python3
"""
Flask web server for Clinical Trials Prospector v3 - async ALL version.

Fixes included:
- robust synchronous search for limited result sets
- asynchronous background jobs for Max Results = ALL
- progress polling endpoint to avoid browser/server JSON timeout issues
- safer keyword validation errors returned as 400
- explicit API-vs-filter diagnostics
- job-specific Excel export
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import os
import sys
import uuid
import threading
from datetime import datetime

try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("❌ Error: Could not import ClinicalTrialsProspector")
    print("Make sure your backend file is named: clinical_trials_prospector.py")
    sys.exit(1)

app = Flask(__name__)
CORS(app)

# Last interactive/limited search, kept for backward-compatible export endpoint
prospector = ClinicalTrialsProspector()
custom_column_order = []

# Background job store for ALL searches
JOBS = {}
JOBS_LOCK = threading.Lock()


def _normalize_list(value):
    """Return None for missing values, otherwise a clean list without empty items."""
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    cleaned = [str(v).strip() for v in value if str(v).strip()]
    return cleaned if cleaned else None


def _parse_search_payload(data):
    """Validate and normalize the search request payload."""
    keywords_raw = data.get('keywords', '').strip()
    if not keywords_raw:
        raise ValueError('Please provide at least one keyword')

    statuses = _normalize_list(data.get('statuses'))
    phases = _normalize_list(data.get('phases'))
    org_types = _normalize_list(data.get('organizationTypes'))
    data_extractions = _normalize_list(data.get('dataExtractions')) or ['sponsors']
    column_order = _normalize_list(data.get('columnOrder')) or []

    max_results_raw = str(data.get('maxResults', '500')).strip()
    if max_results_raw == 'ALL':
        max_results = None  # None means fetch every page until the API has no nextPageToken
    else:
        max_results = int(max_results_raw)
        if max_results <= 0:
            raise ValueError('Max results must be greater than 0')

    return {
        'keywords_raw': keywords_raw,
        'statuses': statuses,
        'phases': phases,
        'org_types': org_types,
        'data_extractions': data_extractions,
        'column_order': column_order,
        'max_results_raw': max_results_raw,
        'max_results': max_results
    }


def _build_response(prospector_instance, trials, extracted_data, payload):
    """Build the JSON response shared by sync and async searches."""
    total_trials = len(trials)
    total_extracted = len(extracted_data)

    unique_orgs = 0
    if 'sponsors' in payload['data_extractions']:
        unique_sponsors = set()
        for item in extracted_data:
            if item.get('lead_sponsor'):
                unique_sponsors.add(item['lead_sponsor'])
        unique_orgs = len(unique_sponsors)

    filtering_removed_all = total_trials > 0 and total_extracted == 0
    diagnostics_message = 'Search completed successfully.'
    if total_trials == 0:
        diagnostics_message = 'ClinicalTrials.gov returned no studies for the current query and API filters.'
    elif filtering_removed_all:
        diagnostics_message = 'ClinicalTrials.gov returned studies, but all records were removed by extraction or organization filtering.'

    return {
        'stats': {
            'totalTrials': total_trials,
            'apiTotalCount': prospector_instance.last_total_count,
            'extractedRecords': total_extracted,
            'uniqueOrganizations': unique_orgs,
            'dataFieldsExtracted': len(payload['data_extractions'])
        },
        'query': {
            'rawKeywords': payload['keywords_raw'],
            'parsedKeywords': prospector_instance.last_query_term,
            'statuses': payload['statuses'] or [],
            'phases': payload['phases'] or [],
            'organizationTypes': payload['org_types'] or [],
            'organizationFilterApplied': payload['org_types'] is not None,
            'dataExtractions': payload['data_extractions'],
            'maxResults': payload['max_results_raw']
        },
        'diagnostics': {
            'apiReturnedResults': total_trials > 0,
            'recordsAfterFiltering': total_extracted,
            'possibleFilteringIssue': filtering_removed_all,
            'message': diagnostics_message,
            'extraction': prospector_instance.extraction_diagnostics,
            'apiDebug': prospector_instance.last_request_debug
        },
        'preview': extracted_data[:100],
        'dataFields': payload['data_extractions']
    }


def _run_search(payload, job_id=None):
    """Run a search. If job_id is provided, update background job progress."""
    local_prospector = ClinicalTrialsProspector(
        include_types=payload['org_types'],
        extraction_options=payload['data_extractions']
    )

    def progress_callback(progress):
        if not job_id:
            return
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job['status'] = 'running'
                job['stage'] = progress.get('stage', 'fetching')
                job['fetched'] = progress.get('fetched', job.get('fetched', 0))
                job['apiTotalCount'] = progress.get('apiTotalCount')
                job['updatedAt'] = datetime.utcnow().isoformat() + 'Z'

    trials = local_prospector.fetch_trials(
        keywords=payload['keywords_raw'],
        statuses=payload['statuses'],
        phases=payload['phases'],
        max_results=payload['max_results'],
        progress_callback=progress_callback
    )

    if job_id:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job['stage'] = 'extracting'
                job['fetched'] = len(trials)
                job['updatedAt'] = datetime.utcnow().isoformat() + 'Z'

    extracted_data = local_prospector.extract_data()
    result = _build_response(local_prospector, trials, extracted_data, payload)
    return local_prospector, result


def _background_job(job_id, payload):
    try:
        with JOBS_LOCK:
            JOBS[job_id].update({
                'status': 'running',
                'stage': 'starting',
                'updatedAt': datetime.utcnow().isoformat() + 'Z'
            })

        local_prospector, result = _run_search(payload, job_id=job_id)

        with JOBS_LOCK:
            JOBS[job_id].update({
                'status': 'completed',
                'stage': 'completed',
                'fetched': result['stats']['totalTrials'],
                'extracted': result['stats']['extractedRecords'],
                'apiTotalCount': result['stats'].get('apiTotalCount'),
                'result': result,
                'prospector': local_prospector,
                'column_order': payload['column_order'],
                'completedAt': datetime.utcnow().isoformat() + 'Z',
                'updatedAt': datetime.utcnow().isoformat() + 'Z'
            })
    except Exception as e:
        print(f"❌ Background job {job_id} failed: {e}")
        import traceback
        traceback.print_exc()
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update({
                    'status': 'failed',
                    'stage': 'failed',
                    'error': str(e),
                    'updatedAt': datetime.utcnow().isoformat() + 'Z'
                })


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/search', methods=['POST'])
def search():
    """Synchronous search. Use for limited result sets only."""
    try:
        data = request.get_json(silent=True) or {}
        payload = _parse_search_payload(data)

        if payload['max_results'] is None:
            return jsonify({
                'error': 'Max Results = ALL must use the background job endpoint.',
                'type': 'USE_ASYNC_SEARCH'
            }), 400

        print("🔍 Sync search request:")
        print(f"   Keywords: {payload['keywords_raw']}")
        print(f"   Max Results: {payload['max_results']}")
        print(f"   Organization Types: {payload['org_types'] or 'No organization filter'}")

        local_prospector, response_data = _run_search(payload)

        global prospector, custom_column_order
        prospector = local_prospector
        custom_column_order = payload['column_order']

        print(f"✅ Returning {response_data['stats']['extractedRecords']} extracted records")
        return jsonify(response_data)

    except ValueError as e:
        return jsonify({'error': str(e), 'type': 'INVALID_INPUT'}), 400
    except Exception as e:
        print(f"❌ Error in search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Unexpected server error', 'details': str(e)}), 500


@app.route('/api/search/start', methods=['POST'])
def start_search_job():
    """Start a background search job. Designed for Max Results = ALL."""
    try:
        data = request.get_json(silent=True) or {}
        payload = _parse_search_payload(data)

        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {
                'jobId': job_id,
                'status': 'queued',
                'stage': 'queued',
                'fetched': 0,
                'extracted': 0,
                'apiTotalCount': None,
                'createdAt': datetime.utcnow().isoformat() + 'Z',
                'updatedAt': datetime.utcnow().isoformat() + 'Z',
                'query': {
                    'rawKeywords': payload['keywords_raw'],
                    'maxResults': payload['max_results_raw']
                }
            }

        thread = threading.Thread(target=_background_job, args=(job_id, payload), daemon=True)
        thread.start()

        return jsonify({
            'jobId': job_id,
            'status': 'queued',
            'message': 'Search job started.'
        }), 202

    except ValueError as e:
        return jsonify({'error': str(e), 'type': 'INVALID_INPUT'}), 400
    except Exception as e:
        print(f"❌ Error starting job: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Unexpected server error', 'details': str(e)}), 500


@app.route('/api/search/status/<job_id>', methods=['GET'])
def get_search_job_status(job_id):
    """Return current background job status and final result when complete."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({'error': 'Unknown job ID'}), 404

        response = {
            'jobId': job_id,
            'status': job.get('status'),
            'stage': job.get('stage'),
            'fetched': job.get('fetched', 0),
            'extracted': job.get('extracted', 0),
            'apiTotalCount': job.get('apiTotalCount'),
            'error': job.get('error'),
            'createdAt': job.get('createdAt'),
            'updatedAt': job.get('updatedAt')
        }

        if job.get('status') == 'completed':
            response['result'] = job.get('result')

        return jsonify(response)


@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Export last synchronous search to Excel. Kept for compatibility."""
    try:
        if not prospector.extracted_data:
            return jsonify({'error': 'No data to export. Please run a search first.'}), 400

        filename = prospector.export_to_xlsx(column_order=custom_column_order)
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
    return export_csv()


@app.route('/api/export/xlsx/<job_id>', methods=['GET'])
def export_xlsx_job(job_id):
    """Export completed background job to Excel."""
    try:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return jsonify({'error': 'Unknown job ID'}), 404
            if job.get('status') != 'completed':
                return jsonify({'error': 'Job is not completed yet.'}), 400
            job_prospector = job.get('prospector')
            column_order = job.get('column_order') or []

        if not job_prospector or not job_prospector.extracted_data:
            return jsonify({'error': 'No data to export for this job.'}), 400

        filename = job_prospector.export_to_xlsx(column_order=column_order)
        if not filename or not os.path.exists(filename):
            return jsonify({'error': 'Failed to generate Excel file'}), 500

        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        print(f"❌ Error in job export: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/data-fields', methods=['GET'])
def get_data_fields():
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
    return jsonify({'status': 'healthy', 'service': 'clinical-trials-prospector-v3-async'}), 200


if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    is_production = os.environ.get('RENDER') is not None

    print("\n" + "="*70)
    print("🚀 Clinical Trials Prospector v3 - Flask Server")
    print("="*70)
    if is_production:
        print("🌐 Running in PRODUCTION mode")
        print(f"📱 Port: {port}")
    else:
        print("💻 Running in DEVELOPMENT mode")
        print(f"📱 Open your browser at: http://localhost:{port}")
    print("✨ Fixed: robust parser, diagnostics, and async ALL searches")
    print("🛑 Press Ctrl+C to stop")
    print("="*70 + "\n")

    app.run(
        debug=not is_production,
        host='0.0.0.0',
        port=port
    )
