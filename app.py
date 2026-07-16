#!/usr/bin/env python3
"""
Flask web server for Clinical Trials Prospector.
Includes:
- normal synchronous search for limited result sets
- background jobs for ALL / long searches
- progress polling
- Excel export for latest search or a background job
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("❌ Error: Could not import ClinicalTrialsProspector")
    print("Make sure clinical_trials_prospector.py is in the same folder as app.py")
    sys.exit(1)

app = Flask(__name__)
CORS(app)

# Latest normal-search state
prospector = ClinicalTrialsProspector()
custom_column_order: List[str] = []

# In-memory background job store for local/PoC usage.
# For production, replace with Redis/Celery/RQ or persistent DB-backed jobs.
jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()


def parse_request_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse and validate frontend payload shared by sync and async routes."""
    keywords_raw = (data.get("keywords") or "").strip()
    if not keywords_raw:
        raise ValueError("Please provide at least one keyword")

    statuses = data.get("statuses") or []
    phases = data.get("phases") or []
    max_results_raw = data.get("maxResults", "500")

    # None means no organization filtering. Frontend usually sends selected types.
    org_types = data.get("organizationTypes")
    if org_types == []:
        org_types = None

    data_extractions = data.get("dataExtractions") or ["sponsors"]
    column_order = data.get("columnOrder") or []

    date_field = (data.get("dateField") or "").strip()
    date_from = (data.get("dateFrom") or "").strip()
    date_to = (data.get("dateTo") or "").strip()
    countries_raw = (data.get("countries") or "").strip()
    countries = [c.strip() for c in countries_raw.split(",") if c.strip()]

    if max_results_raw == "ALL":
        max_results: Optional[int] = None
    else:
        try:
            max_results = int(max_results_raw)
        except ValueError as exc:
            raise ValueError("Max Results must be a number or ALL") from exc
        if max_results <= 0:
            raise ValueError("Max Results must be greater than 0")

    return {
        "keywords_raw": keywords_raw,
        "statuses": statuses or None,
        "phases": phases or None,
        "max_results_raw": max_results_raw,
        "max_results": max_results,
        "org_types": org_types,
        "data_extractions": data_extractions,
        "column_order": column_order,
        "date_field": date_field or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "countries": countries or None,
    }


def build_response(active_prospector: ClinicalTrialsProspector, trials: List[Dict[str, Any]],
                   extracted_data: List[Dict[str, Any]], parsed: Dict[str, Any]) -> Dict[str, Any]:
    unique_orgs = 0
    if "sponsors" in (parsed["data_extractions"] or []):
        unique_orgs = len({row.get("lead_sponsor") for row in extracted_data if row.get("lead_sponsor")})

    return {
        "stats": {
            "totalTrials": len(trials),
            "extractedRecords": len(extracted_data),
            "uniqueOrganizations": unique_orgs,
            "dataFieldsExtracted": len(parsed["data_extractions"] or []),
        },
        "query": {
            "rawKeywords": parsed["keywords_raw"],
            "queryTerms": active_prospector.diagnostics.get("queryTerms", []),
            "queryTermCount": active_prospector.diagnostics.get("queryTermCount", 0),
            "statuses": parsed["statuses"] or [],
            "phases": parsed["phases"] or [],
            "maxResults": parsed["max_results_raw"],
            "organizationTypes": parsed["org_types"],
            "dataExtractions": parsed["data_extractions"] or [],
            "dateField": parsed["date_field"],
            "dateFrom": parsed["date_from"],
            "dateTo": parsed["date_to"],
            "countries": parsed["countries"] or [],
        },
        "diagnostics": active_prospector.diagnostics,
        "preview": extracted_data[:100],
        "dataFields": parsed["data_extractions"] or [],
    }


def run_search(parsed: Dict[str, Any], progress_callback=None) -> tuple[ClinicalTrialsProspector, List[Dict[str, Any]], List[Dict[str, Any]]]:
    active_prospector = ClinicalTrialsProspector(
        include_types=parsed["org_types"],
        extraction_options=parsed["data_extractions"],
    )
    trials = active_prospector.fetch_trials(
        keywords=parsed["keywords_raw"],
        statuses=parsed["statuses"],
        phases=parsed["phases"],
        max_results=parsed["max_results"],
        progress_callback=progress_callback,
        date_field=parsed["date_field"],
        date_from=parsed["date_from"],
        date_to=parsed["date_to"],
        countries=parsed["countries"],
    )
    if progress_callback:
        progress_callback({"stage": "extracting", "fetched": len(trials)})
    extracted_data = active_prospector.extract_data()
    return active_prospector, trials, extracted_data


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "clinical-trials-prospector"}), 200


@app.route("/api/search", methods=["POST"])
def search():
    """Normal synchronous search. Use for bounded searches, not ALL."""
    try:
        data = request.json or {}
        parsed = parse_request_payload(data)

        if parsed["max_results"] is None:
            return jsonify({
                "error": "ALL searches must use the background job route.",
                "details": "The frontend should call /api/search/start when Max Results is ALL."
            }), 400

        print("\n🔍 Search request")
        print(f"   Keywords: {parsed['keywords_raw']}")
        print(f"   Statuses: {parsed['statuses']}")
        print(f"   Phases: {parsed['phases']} (local filter)")
        print(f"   Max Results: {parsed['max_results']}")
        print(f"   Organization Types: {parsed['org_types']}")
        print(f"   Date: {parsed['date_field']} {parsed['date_from']} → {parsed['date_to']} (local filter)")
        print(f"   Countries: {parsed['countries']} (local filter)")

        global prospector, custom_column_order
        custom_column_order = parsed["column_order"]
        prospector, trials, extracted_data = run_search(parsed)
        return jsonify(build_response(prospector, trials, extracted_data, parsed))

    except ValueError as e:
        return jsonify({"error": str(e), "type": "INVALID_INPUT"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(e)}), 500


@app.route("/api/search/start", methods=["POST"])
def start_search_job():
    """Start a background search job, mainly for ALL / long searches."""
    try:
        data = request.json or {}
        parsed = parse_request_payload(data)
        job_id = uuid.uuid4().hex[:12]

        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "progress": {
                    "stage": "queued",
                    "current_query": None,
                    "query_index": 0,
                    "query_count": 0,
                    "fetched": 0,
                    "raw_api_records_seen": 0,
                    "max_results": parsed["max_results"],
                },
                "parsed": parsed,
                "result": None,
                "error": None,
                "prospector": None,
                "column_order": parsed["column_order"],
            }

        thread = threading.Thread(target=_run_background_job, args=(job_id,), daemon=True)
        thread.start()
        return jsonify({"jobId": job_id, "status": "queued"}), 202

    except ValueError as e:
        return jsonify({"error": str(e), "type": "INVALID_INPUT"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(e)}), 500


def _run_background_job(job_id: str) -> None:
    def update_progress(payload: Dict[str, Any]) -> None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["updated_at"] = datetime.now().isoformat(timespec="seconds")
            job["progress"].update(payload)

    try:
        with jobs_lock:
            parsed = jobs[job_id]["parsed"]
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"]["stage"] = "starting"
            jobs[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")

        active_prospector, trials, extracted_data = run_search(parsed, progress_callback=update_progress)
        response_data = build_response(active_prospector, trials, extracted_data, parsed)

        with jobs_lock:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")
            jobs[job_id]["progress"].update({
                "stage": "completed",
                "fetched": len(trials),
                "extracted": len(extracted_data),
            })
            jobs[job_id]["result"] = response_data
            jobs[job_id]["prospector"] = active_prospector
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")
                jobs[job_id]["error"] = {"message": str(e), "traceback": tb}
                jobs[job_id]["progress"]["stage"] = "failed"


@app.route("/api/search/status/<job_id>", methods=["GET"])
def get_job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job ID"}), 404
        payload = {
            "jobId": job_id,
            "status": job["status"],
            "createdAt": job["created_at"],
            "updatedAt": job["updated_at"],
            "progress": job["progress"],
            "error": job["error"],
        }
        if job["status"] == "completed":
            payload["result"] = job["result"]
        return jsonify(payload)


@app.route("/api/export/xlsx", methods=["GET"])
def export_latest_xlsx():
    try:
        if not prospector.extracted_data:
            return jsonify({"error": "No data to export. Please run a search first."}), 400
        filename = prospector.export_to_xlsx(column_order=custom_column_order)
        if not filename or not os.path.exists(filename):
            return jsonify({"error": "Failed to generate Excel file"}), 500
        return send_file(filename, as_attachment=True, download_name=os.path.basename(filename),
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(e)}), 500


@app.route("/api/export/xlsx/<job_id>", methods=["GET"])
def export_job_xlsx(job_id: str):
    try:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify({"error": "Unknown job ID"}), 404
            if job["status"] != "completed":
                return jsonify({"error": "Job is not completed yet"}), 400
            active_prospector = job["prospector"]
            column_order = job["column_order"]

        if not active_prospector or not active_prospector.extracted_data:
            return jsonify({"error": "No data to export for this job"}), 400

        filename = f"ClinicalTrials_Job_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = active_prospector.export_to_xlsx(filename=filename, column_order=column_order)
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "Failed to generate Excel file"}), 500
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath),
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(e)}), 500


@app.route("/api/export/csv", methods=["GET"])
def export_csv_alias():
    # Backward-compatible alias. This now returns XLSX because the UI expects Excel.
    return export_latest_xlsx()


@app.route("/api/data-fields", methods=["GET"])
def get_data_fields():
    fields_info = [
        {"key": key, "label": info["label"], "description": info["description"], "default": info.get("default", False)}
        for key, info in ClinicalTrialsProspector.DATA_EXTRACTION_OPTIONS.items()
    ]
    return jsonify({"dataFields": fields_info})


@app.route("/api/organization-types", methods=["GET"])
def get_organization_types():
    types_info = [
        {"key": key, "label": info["label"], "keywords": info["keywords"]}
        for key, info in ClinicalTrialsProspector.ORGANIZATION_TYPES.items()
    ]
    return jsonify({"organizationTypes": types_info})


if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    is_production = os.environ.get("RENDER") is not None

    print("\n" + "=" * 70)
    print("🚀 Clinical Trials Prospector")
    print("=" * 70)
    print("🌐 Production mode" if is_production else "💻 Development mode")
    print(f"📱 Port: {port}")
    print("✨ Mixed parsing: comma-list + Boolean subqueries")
    print("✨ Local filters: phase, date, country, organization")
    print("✨ Background jobs for ALL searches")
    print("=" * 70 + "\n")

    app.run(debug=not is_production, host="0.0.0.0", port=port, threaded=True)
