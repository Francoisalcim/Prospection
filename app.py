#!/usr/bin/env python3
"""
Flask server for Clinical Trials Prospector - memory-safe version.

Main changes:
- Normal searches run synchronously with modest limits.
- ALL searches run in a background thread.
- Jobs export to XLSX when complete and then release the prospector object.
- Old jobs/files are cleaned up.
- Only small previews are returned to the frontend.
"""

from __future__ import annotations

import os
import sys
import uuid
import threading
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

try:
    from clinical_trials_prospector import ClinicalTrialsProspector
except ImportError:
    print("Could not import ClinicalTrialsProspector. Make sure clinical_trials_prospector.py is next to app.py.")
    sys.exit(1)


app = Flask(__name__)
CORS(app)

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
EXPORT_DIR = os.path.join(os.getcwd(), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

JOB_TTL_MINUTES = int(os.environ.get("JOB_TTL_MINUTES", "45"))
MAX_RUNNING_JOBS = int(os.environ.get("MAX_RUNNING_JOBS", "1"))
MAX_SYNC_RESULTS = int(os.environ.get("MAX_SYNC_RESULTS", "2000"))
MAX_ALL_RESULTS_ENV = os.environ.get("MAX_ALL_RESULTS", "")
MAX_ALL_RESULTS: Optional[int] = int(MAX_ALL_RESULTS_ENV) if MAX_ALL_RESULTS_ENV.strip() else None

jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()

# Last synchronous search, for non-background export.
latest_sync_prospector: Optional[ClinicalTrialsProspector] = None
latest_sync_column_order: List[str] = []


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def parse_countries(countries_raw: str) -> List[str]:
    return [c.strip() for c in (countries_raw or "").split(",") if c.strip()]


def parse_max_results(raw: Any, allow_all: bool = False) -> Optional[int]:
    raw = str(raw or "500").strip()
    if raw == "ALL":
        if not allow_all:
            raise ValueError("ALL is only available through the background search route.")
        return MAX_ALL_RESULTS
    value = int(raw)
    if value <= 0:
        raise ValueError("Max results must be positive.")
    return value


def extract_search_payload(data: Dict[str, Any], allow_all: bool = False) -> Dict[str, Any]:
    keywords_raw = (data.get("keywords") or "").strip()
    if not keywords_raw:
        raise ValueError("Please provide at least one keyword.")

    statuses = data.get("statuses", []) or []
    phases = data.get("phases", []) or []
    max_results = parse_max_results(data.get("maxResults", "500"), allow_all=allow_all)

    org_types = data.get("organizationTypes", None)
    if org_types == []:
        org_types = None

    data_extractions = data.get("dataExtractions", ["sponsors"]) or ["sponsors"]
    column_order = data.get("columnOrder", []) or []

    date_field = (data.get("dateField") or "").strip()
    date_from = (data.get("dateFrom") or "").strip()
    date_to = (data.get("dateTo") or "").strip()
    countries = parse_countries((data.get("countries") or "").strip())

    return {
        "keywords_raw": keywords_raw,
        "statuses": statuses,
        "phases": phases,
        "max_results": max_results,
        "org_types": org_types,
        "data_extractions": data_extractions,
        "column_order": column_order,
        "date_field": date_field or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "countries": countries or None,
    }


def build_response(prospector: ClinicalTrialsProspector, payload: Dict[str, Any], preview_limit: int = 50) -> Dict[str, Any]:
    preview_data = prospector.extracted_data[:preview_limit]
    unique_orgs = 0
    if "sponsors" in payload["data_extractions"]:
        unique_orgs = len({row.get("lead_sponsor") for row in prospector.extracted_data if row.get("lead_sponsor")})

    return {
        "stats": {
            "extractedRecords": len(prospector.extracted_data),
            "uniqueOrganizations": unique_orgs,
            "dataFieldsExtracted": len(payload["data_extractions"]),
            "queryTerms": len(prospector.query_terms),
            "rawStudiesSeen": prospector.raw_studies_seen,
            "apiRequestsMade": prospector.api_requests_made,
            "localFilterRejections": prospector.local_filter_rejections,
            "organizationFilterRejections": prospector.organization_filter_rejections,
        },
        "query": {
            "rawKeywords": payload["keywords_raw"],
            "queryTermsPreview": prospector.query_terms[:20],
            "queryTermsTotal": len(prospector.query_terms),
            "statuses": payload["statuses"],
            "phases": payload["phases"],
            "organizationTypes": payload["org_types"],
            "dataExtractions": payload["data_extractions"],
            "dateField": payload["date_field"],
            "dateFrom": payload["date_from"],
            "dateTo": payload["date_to"],
            "countries": payload["countries"],
            "maxResults": payload["max_results"],
        },
        "diagnostics": {
            "message": "Search completed successfully.",
            "processingErrors": prospector.processing_errors[:10],
            "memorySafeMode": True,
            "storesRawStudies": False,
        },
        "preview": preview_data,
        "dataFields": payload["data_extractions"],
    }


def cleanup_old_jobs() -> None:
    now = datetime.now()
    expired: List[str] = []
    with jobs_lock:
        for job_id, job in jobs.items():
            created_at = job.get("created_at")
            if created_at and now - created_at > timedelta(minutes=JOB_TTL_MINUTES):
                expired.append(job_id)

        for job_id in expired:
            job = jobs.pop(job_id, None)
            file_path = job.get("file_path") if job else None
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass


def count_running_jobs() -> int:
    with jobs_lock:
        return sum(1 for job in jobs.values() if job.get("status") == "running")


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health_check():
    cleanup_old_jobs()
    return jsonify({
        "status": "healthy",
        "service": "clinical-trials-prospector-memory-safe",
        "jobs": len(jobs),
        "runningJobs": count_running_jobs(),
    })


@app.route("/api/search", methods=["POST"])
def search():
    """Synchronous search for bounded result counts."""
    global latest_sync_prospector, latest_sync_column_order
    try:
        cleanup_old_jobs()
        data = request.json or {}
        payload = extract_search_payload(data, allow_all=False)

        if payload["max_results"] is None or payload["max_results"] > MAX_SYNC_RESULTS:
            return jsonify({
                "error": f"Synchronous searches are limited to {MAX_SYNC_RESULTS} records. Use ALL/background search for larger exports."
            }), 400

        print("Search request:")
        print(f"  Keywords: {payload['keywords_raw']}")
        print(f"  Statuses: {payload['statuses']}")
        print(f"  Phases: {payload['phases']}")
        print(f"  Max Results: {payload['max_results']}")
        print(f"  Countries: {payload['countries']}")

        prospector = ClinicalTrialsProspector(
            include_types=payload["org_types"],
            extraction_options=payload["data_extractions"],
        )
        prospector.fetch_trials(
            keywords=payload["keywords_raw"],
            statuses=payload["statuses"] or None,
            phases=payload["phases"] or None,
            max_results=payload["max_results"],
            date_field=payload["date_field"],
            date_from=payload["date_from"],
            date_to=payload["date_to"],
            countries=payload["countries"],
        )

        latest_sync_prospector = prospector
        latest_sync_column_order = payload["column_order"]
        return jsonify(build_response(prospector, payload, preview_limit=100))

    except ValueError as exc:
        return jsonify({"error": str(exc), "type": "VALIDATION_ERROR"}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "error": "Unexpected server error",
            "details": str(exc),
        }), 500


@app.route("/api/search/start", methods=["POST"])
def start_background_search():
    """Start a background search, typically used for ALL."""
    try:
        cleanup_old_jobs()
        if count_running_jobs() >= MAX_RUNNING_JOBS:
            return jsonify({
                "error": "Another background search is already running. Please wait for it to finish."
            }), 429

        data = request.json or {}
        payload = extract_search_payload(data, allow_all=True)
        job_id = uuid.uuid4().hex[:12]

        with jobs_lock:
            jobs[job_id] = {
                "status": "running",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "progress": {"stage": "queued", "extracted": 0},
                "error": None,
                "file_path": None,
                "summary": None,
            }

        thread = threading.Thread(target=run_background_job, args=(job_id, payload), daemon=True)
        thread.start()

        return jsonify({"jobId": job_id, "status": "running"})

    except ValueError as exc:
        return jsonify({"error": str(exc), "type": "VALIDATION_ERROR"}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(exc)}), 500


def run_background_job(job_id: str, payload: Dict[str, Any]) -> None:
    prospector: Optional[ClinicalTrialsProspector] = None

    def progress_callback(progress: Dict[str, Any]) -> None:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["progress"] = progress
                jobs[job_id]["updated_at"] = datetime.now()

    try:
        prospector = ClinicalTrialsProspector(
            include_types=payload["org_types"],
            extraction_options=payload["data_extractions"],
        )
        prospector.fetch_trials(
            keywords=payload["keywords_raw"],
            statuses=payload["statuses"] or None,
            phases=payload["phases"] or None,
            max_results=payload["max_results"],
            progress_callback=progress_callback,
            date_field=payload["date_field"],
            date_from=payload["date_from"],
            date_to=payload["date_to"],
            countries=payload["countries"],
        )

        filename = f"ClinicalTrials_Export_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path = os.path.join(EXPORT_DIR, filename)
        exported_path = prospector.export_to_xlsx(filename=file_path, column_order=payload["column_order"])

        summary = build_response(prospector, payload, preview_limit=25)
        summary["downloadReady"] = bool(exported_path)

        # Release most memory: keep only summary and file path.
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id].update({
                    "status": "completed",
                    "updated_at": datetime.now(),
                    "progress": {
                        "stage": "completed",
                        "extracted": len(prospector.extracted_data),
                        "api_requests_made": prospector.api_requests_made,
                        "raw_studies_seen": prospector.raw_studies_seen,
                    },
                    "summary": summary,
                    "file_path": exported_path,
                    "error": None,
                })

        # Explicitly release large lists.
        prospector.extracted_data.clear()
        prospector.seen_nct_ids.clear()
        prospector = None

    except Exception as exc:
        traceback.print_exc()
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id].update({
                    "status": "failed",
                    "updated_at": datetime.now(),
                    "error": str(exc),
                    "traceback": traceback.format_exc()[-4000:],
                })
        if prospector is not None:
            prospector.extracted_data.clear()
            prospector.seen_nct_ids.clear()


@app.route("/api/search/status/<job_id>", methods=["GET"])
def job_status(job_id: str):
    cleanup_old_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404
        return jsonify({
            "jobId": job_id,
            "status": job.get("status"),
            "progress": job.get("progress"),
            "error": job.get("error"),
            "summary": job.get("summary") if job.get("status") == "completed" else None,
        })


@app.route("/api/export/xlsx", methods=["GET"])
def export_sync_xlsx():
    global latest_sync_prospector, latest_sync_column_order
    try:
        if not latest_sync_prospector or not latest_sync_prospector.extracted_data:
            return jsonify({"error": "No data to export. Please run a search first."}), 400
        filename = latest_sync_prospector.export_to_xlsx(column_order=latest_sync_column_order)
        if not filename or not os.path.exists(filename):
            return jsonify({"error": "Failed to generate Excel file."}), 500
        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": "Unexpected server error", "details": str(exc)}), 500


@app.route("/api/export/xlsx/<job_id>", methods=["GET"])
def export_job_xlsx(job_id: str):
    cleanup_old_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404
        if job.get("status") != "completed":
            return jsonify({"error": "Job is not completed yet."}), 400
        file_path = job.get("file_path")

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "Export file not found."}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(file_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/data-fields", methods=["GET"])
def get_data_fields():
    fields_info = []
    for key, info in ClinicalTrialsProspector.DATA_EXTRACTION_OPTIONS.items():
        fields_info.append({
            "key": key,
            "label": info["label"],
            "description": info["description"],
            "default": info.get("default", False),
        })
    return jsonify({"dataFields": fields_info})


@app.route("/api/organization-types", methods=["GET"])
def get_organization_types():
    types_info = []
    for key, info in ClinicalTrialsProspector.ORGANIZATION_TYPES.items():
        types_info.append({
            "key": key,
            "label": info["label"],
            "keywords": info["keywords"],
        })
    return jsonify({"organizationTypes": types_info})


if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    is_production = os.environ.get("RENDER") is not None

    print("\n" + "=" * 70)
    print("Clinical Trials Prospector - memory-safe Flask server")
    print("=" * 70)
    print(f"Mode: {'PRODUCTION / Render' if is_production else 'LOCAL DEVELOPMENT'}")
    print(f"Port: {port}")
    print(f"Max synchronous records: {MAX_SYNC_RESULTS}")
    print(f"Max running background jobs: {MAX_RUNNING_JOBS}")
    print(f"ALL cap: {MAX_ALL_RESULTS if MAX_ALL_RESULTS is not None else 'no code cap'}")
    print(f"Job TTL: {JOB_TTL_MINUTES} minutes")
    print("=" * 70 + "\n")

    app.run(debug=not is_production, host="0.0.0.0", port=port, threaded=True)
