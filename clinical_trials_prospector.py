#!/usr/bin/env python3
"""
Clinical Trials Prospector
Robust ClinicalTrials.gov v2 API client with:
- mixed comma-list + Boolean parsing
- safe query term cleaning
- multi-query execution
- NCT ID deduplication
- local filters for phase, date, country, and organization type
- flexible data extraction
"""

from __future__ import annotations

import csv
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Any

import requests


ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


class ClinicalTrialsProspector:
    """Fetches, filters, extracts, and exports ClinicalTrials.gov study data."""

    BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

    VALID_STATUSES = {
        "RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "NOT_YET_RECRUITING",
        "COMPLETED",
        "TERMINATED",
        "WITHDRAWN",
        "SUSPENDED",
        "ENROLLING_BY_INVITATION",
        "UNKNOWN",
    }

    VALID_PHASES = {
        "EARLY_PHASE1",
        "PHASE1",
        "PHASE2",
        "PHASE3",
        "PHASE4",
        "NA",
    }

    VALID_DATE_FIELDS = {
        "start_date": "startDateStruct",
        "completion_date": "completionDateStruct",
        "last_update": "lastUpdatePostDateStruct",
    }

    ORGANIZATION_TYPES = {
        "university": {
            "keywords": [
                "university", "universite", "universität", "universidad", "universiti",
                "college", "école"
            ],
            "label": "Universities & Colleges",
        },
        "institute": {
            "keywords": ["institute", "institut", "instituto", "research center", "research centre"],
            "label": "Research Institutes",
        },
        "hospital": {
            "keywords": [
                "hospital", "medical center", "medical centre", "health system",
                "health center", "clinic", "clinique", "klinik"
            ],
            "label": "Hospitals & Medical Centers",
        },
        "government": {
            "keywords": [
                "national institutes", "nih", "ministry of health", "department of health",
                "veterans affairs", "va medical", "public health", "government"
            ],
            "label": "Government Agencies",
        },
        "foundation": {
            "keywords": ["foundation", "fondation", "fundacion", "stichting", "trust fund"],
            "label": "Foundations & Trusts",
        },
        "academic": {
            "keywords": ["school of medicine", "school of pharmacy", "faculty of", "academy", "academie", "academic"],
            "label": "Academic Medical Centers",
        },
        "nonprofit": {
            "keywords": ["nonprofit", "non-profit", "charity", "charitable", "society", "association", "organization"],
            "label": "Non-Profit Organizations",
        },
        "company": {
            "keywords": [],
            "label": "Commercial Companies",
        },
    }

    DATA_EXTRACTION_OPTIONS = {
        "sponsors": {"label": "Sponsors & Collaborators", "description": "Lead sponsors and collaborating organizations", "default": True},
        "investigators": {"label": "Principal Investigators", "description": "Lead researchers and affiliations", "default": False},
        "locations": {"label": "Study Locations", "description": "Facilities, cities, countries", "default": False},
        "interventions": {"label": "Interventions", "description": "Drugs, devices, procedures", "default": False},
        "conditions": {"label": "Conditions", "description": "Diseases and conditions", "default": False},
        "outcomes": {"label": "Study Outcomes", "description": "Primary and secondary outcome measures", "default": False},
        "design": {"label": "Study Design", "description": "Phase, type, enrollment, randomization", "default": False},
        "eligibility": {"label": "Eligibility Criteria", "description": "Age, sex, criteria", "default": False},
        "contacts": {"label": "Contact Information", "description": "Recruitment contacts", "default": False},
        "timeline": {"label": "Dates & Timeline", "description": "Start, completion, update dates", "default": False},
    }

    def __init__(self, include_types: Optional[List[str]] = None, exclude_types: Optional[List[str]] = None,
                 extraction_options: Optional[List[str]] = None):
        self.trials_data: List[Dict[str, Any]] = []
        self.extracted_data: List[Dict[str, Any]] = []
        self.include_types = include_types
        self.exclude_types = exclude_types or []
        self.extraction_options = extraction_options or ["sponsors"]
        self.last_request_debug: Dict[str, Any] = {"requests": [], "errors": []}
        self.diagnostics: Dict[str, Any] = {}

    # ---------------------------------------------------------------------
    # Query parsing
    # ---------------------------------------------------------------------
    def _split_top_level_commas(self, text: str) -> List[str]:
        """Split on commas, except commas inside parentheses or quotes."""
        parts: List[str] = []
        current: List[str] = []
        depth = 0
        in_quote = False

        for char in text:
            if char == '"':
                in_quote = not in_quote
                current.append(char)
            elif char == "(" and not in_quote:
                depth += 1
                current.append(char)
            elif char == ")" and not in_quote:
                depth = max(0, depth - 1)
                current.append(char)
            elif char == "," and depth == 0 and not in_quote:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
            else:
                current.append(char)

        part = "".join(current).strip()
        if part:
            parts.append(part)

        return parts

    def clean_query_term(self, term: str) -> str:
        """
        Clean one simple medical term before sending it to ClinicalTrials.gov.
        Boolean expressions are not passed through this cleaner.
        """
        term = (term or "").strip()
        replacements = {
            " / ": " ",
            "/": " ",
            "&": " and ",
            "(": " ",
            ")": " ",
            ";": " ",
            ":": " ",
        }
        for old, new in replacements.items():
            term = term.replace(old, new)

        # Keep hyphens inside words, but normalize extra whitespace.
        term = re.sub(r"\s+", " ", term).strip()
        return term

    def _validate_keyword_expression(self, expression: str) -> None:
        """Validate one Boolean expression with uppercase AND/OR operators."""
        balance = 0
        for char in expression:
            if char == "(":
                balance += 1
            elif char == ")":
                balance -= 1
            if balance < 0:
                raise ValueError("Invalid keyword expression: closing parenthesis before opening parenthesis.")
        if balance != 0:
            raise ValueError("Invalid keyword expression: unbalanced parentheses.")

        if re.search(r"\b(?:AND|OR)\s+(?:AND|OR)\b", expression):
            raise ValueError("Invalid keyword expression: two Boolean operators are next to each other.")
        if re.search(r"^\s*(?:AND|OR)\b", expression) or re.search(r"\b(?:AND|OR)\s*$", expression):
            raise ValueError("Invalid keyword expression: expression cannot start or end with AND/OR.")

    def parse_keyword_expression(self, keyword_string: str) -> str:
        """
        Validate one Boolean sub-query.
        Use only after comma-splitting. Commas are not allowed inside Boolean items.
        """
        expression = (keyword_string or "").strip()
        if not expression:
            return ""
        expression = re.sub(r"\s+", " ", expression)
        if "," in expression:
            raise ValueError("Invalid Boolean expression: commas are only allowed as separators between search items.")
        self._validate_keyword_expression(expression)
        return expression

    def parse_keyword_terms(self, keyword_string: str) -> List[str]:
        """
        Main parsing rule.

        1. Split first on top-level commas.
        2. Each item can be:
           - a simple medical term; or
           - a Boolean sub-query using uppercase AND/OR.
        3. Lowercase 'and'/'or' are treated as normal words.

        Examples:
            Acne, Wounds and Injuries
              -> ["Acne", "Wounds and Injuries"]
            Acne, Body cellulite OR localized fat reduction
              -> ["Acne", "Body cellulite OR localized fat reduction"]
            cancer AND (immunotherapy OR chemotherapy)
              -> ["cancer AND (immunotherapy OR chemotherapy)"]
        """
        expression = (keyword_string or "").strip()
        if not expression:
            return []

        expression = re.sub(r"\s+", " ", expression)
        items = self._split_top_level_commas(expression)
        query_terms: List[str] = []

        for item in items:
            item = item.strip()
            if not item:
                continue

            has_boolean = re.search(r"\b(?:AND|OR)\b", item) is not None
            if has_boolean:
                query = self.parse_keyword_expression(item)
            else:
                query = self.clean_query_term(item)

            if query and query not in query_terms:
                query_terms.append(query)

        return query_terms

    # Backwards-compatible name used by older code.
    def build_query_term(self, keywords: str) -> str:
        terms = self.parse_keyword_terms(keywords)
        if not terms:
            return ""
        if len(terms) == 1:
            return terms[0]
        # This method should not be used for multi-term execution anymore.
        return " OR ".join(terms)

    # ---------------------------------------------------------------------
    # Validation and local filters
    # ---------------------------------------------------------------------
    def validate_filters(self, statuses: Optional[List[str]] = None, phases: Optional[List[str]] = None,
                         date_field: Optional[str] = None) -> None:
        if statuses:
            invalid = set(statuses) - self.VALID_STATUSES
            if invalid:
                raise ValueError(f"Invalid status value(s): {', '.join(sorted(invalid))}")
        if phases:
            invalid = set(phases) - self.VALID_PHASES
            if invalid:
                raise ValueError(f"Invalid phase value(s): {', '.join(sorted(invalid))}")
        if date_field and date_field not in self.VALID_DATE_FIELDS:
            raise ValueError(f"Invalid date field: {date_field}")

    def _extract_study_phases(self, study: Dict[str, Any]) -> List[str]:
        return study.get("protocolSection", {}).get("designModule", {}).get("phases", []) or []

    def _extract_study_countries(self, study: Dict[str, Any]) -> Set[str]:
        locations = study.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", []) or []
        return {loc.get("country", "").strip().lower() for loc in locations if loc.get("country")}

    def _extract_study_date(self, study: Dict[str, Any], date_field: str) -> Optional[str]:
        struct_name = self.VALID_DATE_FIELDS.get(date_field)
        if not struct_name:
            return None
        return study.get("protocolSection", {}).get("statusModule", {}).get(struct_name, {}).get("date")

    def _normalize_date_for_compare(self, value: Optional[str], is_upper_bound: bool = False) -> Optional[str]:
        """Normalize YYYY, YYYY-MM, or YYYY-MM-DD to a comparable YYYY-MM-DD string."""
        if not value:
            return None
        value = value.strip()
        if re.fullmatch(r"\d{4}", value):
            return f"{value}-12-31" if is_upper_bound else f"{value}-01-01"
        if re.fullmatch(r"\d{4}-\d{2}", value):
            return f"{value}-31" if is_upper_bound else f"{value}-01"
        return value[:10]

    def _date_in_range(self, date_value: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
        study_date = self._normalize_date_for_compare(date_value)
        if not study_date:
            return False
        lower = self._normalize_date_for_compare(date_from)
        upper = self._normalize_date_for_compare(date_to, is_upper_bound=True)
        if lower and study_date < lower:
            return False
        if upper and study_date > upper:
            return False
        return True

    def _passes_local_filters(self, study: Dict[str, Any], phases: Optional[List[str]] = None,
                              date_field: Optional[str] = None, date_from: Optional[str] = None,
                              date_to: Optional[str] = None, countries: Optional[List[str]] = None) -> bool:
        if phases:
            study_phases = set(self._extract_study_phases(study))
            if not set(phases).intersection(study_phases):
                return False

        if date_field and (date_from or date_to):
            study_date = self._extract_study_date(study, date_field)
            if not self._date_in_range(study_date, date_from, date_to):
                return False

        if countries:
            requested = {c.strip().lower() for c in countries if c.strip()}
            if requested and not requested.intersection(self._extract_study_countries(study)):
                return False

        return True

    # ---------------------------------------------------------------------
    # Organization filtering
    # ---------------------------------------------------------------------
    def get_organization_type(self, name: str) -> str:
        if not name:
            return "unknown"
        name_lower = name.lower()
        for org_type, info in self.ORGANIZATION_TYPES.items():
            if org_type == "company":
                continue
            for keyword in info["keywords"]:
                if keyword in name_lower:
                    return org_type
        return "company"

    def should_include_organization(self, name: str) -> bool:
        if not name:
            return False
        org_type = self.get_organization_type(name)
        if self.include_types is not None:
            return org_type in self.include_types
        return org_type not in self.exclude_types

    # ---------------------------------------------------------------------
    # API fetching
    # ---------------------------------------------------------------------
    def fetch_trials(self, keywords: str, statuses: Optional[List[str]] = None, phases: Optional[List[str]] = None,
                     max_results: Optional[int] = 500, progress_callback: ProgressCallback = None,
                     date_field: Optional[str] = None, date_from: Optional[str] = None,
                     date_to: Optional[str] = None, countries: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetch trials from ClinicalTrials.gov.

        Status is sent to the API.
        Phase/date/country are applied locally for reliability and consistency.
        Comma-separated terms are executed as separate API calls and deduplicated by NCT ID.
        max_results=None means fetch all matching records available through pagination.
        """
        self.trials_data = []
        self.extracted_data = []
        self.last_request_debug = {"requests": [], "errors": []}

        statuses = statuses or None
        phases = phases or None
        countries = countries or None
        self.validate_filters(statuses=statuses, phases=phases, date_field=date_field)

        query_terms = self.parse_keyword_terms(keywords)
        if not query_terms:
            return []

        page_size = 100
        seen_nct_ids: Set[str] = set()
        raw_api_records_seen = 0
        local_filter_removed = 0

        self.diagnostics = {
            "queryTerms": query_terms,
            "queryTermCount": len(query_terms),
            "rawApiRecordsSeen": 0,
            "deduplicatedRecords": 0,
            "localFilterRemoved": 0,
            "phaseFilterLocal": bool(phases),
            "dateFilterLocal": bool(date_field and (date_from or date_to)),
            "countryFilterLocal": bool(countries),
        }

        for query_index, query_term in enumerate(query_terms, start=1):
            page_token = None
            term_pages = 0

            while max_results is None or len(self.trials_data) < max_results:
                params: Dict[str, Any] = {
                    "query.term": query_term,
                    "pageSize": page_size if max_results is None else min(page_size, max_results - len(self.trials_data)),
                    "format": "json",
                    "countTotal": "true",
                }

                if statuses:
                    params["filter.overallStatus"] = ",".join(statuses)

                # Intentionally not using filter.phase. Phase is filtered locally.

                if page_token:
                    params["pageToken"] = page_token

                if params["pageSize"] <= 0:
                    break

                try:
                    response = requests.get(self.BASE_URL, params=params, timeout=60)
                    request_debug = {
                        "query_term": query_term,
                        "url": response.url,
                        "status_code": response.status_code,
                        "params": params.copy(),
                    }
                    if response.status_code != 200:
                        request_debug["response_preview"] = response.text[:1000]
                        self.last_request_debug["errors"].append(request_debug)
                    self.last_request_debug["requests"].append(request_debug)
                    response.raise_for_status()
                except requests.exceptions.RequestException:
                    raise

                data = response.json()
                studies = data.get("studies", []) or []
                raw_api_records_seen += len(studies)
                term_pages += 1

                if not studies:
                    break

                before_local = len(studies)
                studies = [
                    study for study in studies
                    if self._passes_local_filters(
                        study,
                        phases=phases,
                        date_field=date_field,
                        date_from=date_from,
                        date_to=date_to,
                        countries=countries,
                    )
                ]
                local_filter_removed += before_local - len(studies)

                for study in studies:
                    nct_id = study.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
                    if not nct_id or nct_id in seen_nct_ids:
                        continue
                    self.trials_data.append(study)
                    seen_nct_ids.add(nct_id)
                    if max_results is not None and len(self.trials_data) >= max_results:
                        break

                page_token = data.get("nextPageToken")

                self.diagnostics.update({
                    "rawApiRecordsSeen": raw_api_records_seen,
                    "deduplicatedRecords": len(self.trials_data),
                    "localFilterRemoved": local_filter_removed,
                })

                if progress_callback:
                    progress_callback({
                        "stage": "fetching",
                        "current_query": query_term,
                        "query_index": query_index,
                        "query_count": len(query_terms),
                        "term_pages": term_pages,
                        "raw_api_records_seen": raw_api_records_seen,
                        "fetched": len(self.trials_data),
                        "max_results": max_results,
                        "has_next_page": bool(page_token),
                    })

                if not page_token:
                    break

                time.sleep(0.2)

            if max_results is not None and len(self.trials_data) >= max_results:
                break

        self.diagnostics.update({
            "rawApiRecordsSeen": raw_api_records_seen,
            "deduplicatedRecords": len(self.trials_data),
            "localFilterRemoved": local_filter_removed,
        })
        return self.trials_data

    # ---------------------------------------------------------------------
    # Data extraction
    # ---------------------------------------------------------------------
    def extract_data(self, trials: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        if trials is None:
            trials = self.trials_data

        self.extracted_data = []
        org_filter_removed = 0
        processing_errors = 0
        org_type_counts: Dict[str, int] = {}

        for study in trials:
            nct_id = ""
            try:
                ps = study.get("protocolSection", {})
                nct_id = ps.get("identificationModule", {}).get("nctId", "")
                extracted: Dict[str, Any] = {
                    "nct_id": nct_id,
                    "title": ps.get("identificationModule", {}).get("briefTitle", ""),
                    "status": ps.get("statusModule", {}).get("overallStatus", ""),
                }

                if "sponsors" in self.extraction_options:
                    extracted.update(self._extract_sponsors(ps))
                if "investigators" in self.extraction_options:
                    extracted.update(self._extract_investigators(ps))
                if "locations" in self.extraction_options:
                    extracted.update(self._extract_locations(ps))
                if "interventions" in self.extraction_options:
                    extracted.update(self._extract_interventions(ps))
                if "conditions" in self.extraction_options:
                    extracted.update(self._extract_conditions(ps))
                if "outcomes" in self.extraction_options:
                    extracted.update(self._extract_outcomes(ps))
                if "design" in self.extraction_options:
                    extracted.update(self._extract_design(ps))
                if "eligibility" in self.extraction_options:
                    extracted.update(self._extract_eligibility(ps))
                if "contacts" in self.extraction_options:
                    extracted.update(self._extract_contacts(ps))
                if "timeline" in self.extraction_options:
                    extracted.update(self._extract_timeline(ps))

                if "sponsors" in self.extraction_options:
                    lead_sponsor = extracted.get("lead_sponsor", "")
                    org_type = extracted.get("lead_sponsor_type") or self.get_organization_type(lead_sponsor)
                    org_type_counts[org_type] = org_type_counts.get(org_type, 0) + 1
                    if self.include_types is not None and not self.should_include_organization(lead_sponsor):
                        org_filter_removed += 1
                        continue

                self.extracted_data.append(extracted)
            except Exception as exc:
                processing_errors += 1
                print(f"⚠️ Warning: Error processing study {nct_id}: {exc}")
                continue

        self.diagnostics.update({
            "recordsBeforeOrgFilter": len(trials),
            "recordsAfterOrgFilter": len(self.extracted_data),
            "orgFilterRemoved": org_filter_removed,
            "processingErrors": processing_errors,
            "organizationTypeCountsBeforeFilter": org_type_counts,
        })
        return self.extracted_data

    def _extract_sponsors(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        sponsors_module = ps.get("sponsorsCollaboratorsModule") or ps.get("sponsorCollaboratorsModule", {})
        lead_sponsor = sponsors_module.get("leadSponsor", {}).get("name", "")
        lead_sponsor_class = sponsors_module.get("leadSponsor", {}).get("class", "")
        collaborators = sponsors_module.get("collaborators", []) or []
        collab_names = [c.get("name", "") for c in collaborators if c.get("name")]
        return {
            "lead_sponsor": lead_sponsor,
            "lead_sponsor_class": lead_sponsor_class,
            "lead_sponsor_type": self.get_organization_type(lead_sponsor),
            "collaborators": "; ".join(collab_names),
            "collaborator_count": len(collab_names),
        }

    def _extract_investigators(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        officials = ps.get("contactsLocationsModule", {}).get("overallOfficials", []) or []
        pi_names, pi_affiliations = [], []
        for official in officials:
            if official.get("role") in ["PRINCIPAL_INVESTIGATOR", "STUDY_DIRECTOR"]:
                if official.get("name"):
                    pi_names.append(official.get("name", ""))
                if official.get("affiliation"):
                    pi_affiliations.append(official.get("affiliation", ""))
        return {"principal_investigators": "; ".join(pi_names), "pi_affiliations": "; ".join(pi_affiliations), "pi_count": len(pi_names)}

    def _extract_locations(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        locations = ps.get("contactsLocationsModule", {}).get("locations", []) or []
        facilities, cities, countries = set(), set(), set()
        for loc in locations:
            if loc.get("facility"):
                facilities.add(loc["facility"])
            if loc.get("city"):
                cities.add(loc["city"])
            if loc.get("country"):
                countries.add(loc["country"])
        return {
            "facilities": "; ".join(sorted(facilities)),
            "cities": "; ".join(sorted(cities)),
            "countries": "; ".join(sorted(countries)),
            "location_count": len(locations),
        }

    def _extract_interventions(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        interventions = ps.get("armsInterventionsModule", {}).get("interventions", []) or []
        drugs, devices, procedures, other = [], [], [], []
        for intervention in interventions:
            int_type = intervention.get("type", "")
            name = intervention.get("name", "")
            if int_type == "DRUG":
                drugs.append(name)
            elif int_type == "DEVICE":
                devices.append(name)
            elif int_type in ["PROCEDURE", "SURGERY"]:
                procedures.append(name)
            else:
                other.append(name)
        return {
            "drugs": "; ".join(drugs),
            "devices": "; ".join(devices),
            "procedures": "; ".join(procedures),
            "other_interventions": "; ".join(other),
            "intervention_count": len(interventions),
        }

    def _extract_conditions(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        cond_module = ps.get("conditionsModule", {})
        conditions = cond_module.get("conditions", []) or []
        keywords = cond_module.get("keywords", []) or []
        return {"conditions": "; ".join(conditions), "keywords": "; ".join(keywords), "condition_count": len(conditions)}

    def _extract_outcomes(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        outcomes_module = ps.get("outcomesModule", {})
        primary = outcomes_module.get("primaryOutcomes", []) or []
        secondary = outcomes_module.get("secondaryOutcomes", []) or []
        return {
            "primary_outcomes": "; ".join([o.get("measure", "") for o in primary if o.get("measure")]),
            "secondary_outcomes": "; ".join([o.get("measure", "") for o in secondary if o.get("measure")]),
            "primary_outcome_count": len(primary),
            "secondary_outcome_count": len(secondary),
        }

    def _extract_design(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        design_module = ps.get("designModule", {})
        enrollment = design_module.get("enrollmentInfo", {}) or {}
        design_info = design_module.get("designInfo", {}) or {}
        return {
            "phase": ", ".join(design_module.get("phases", []) or []),
            "study_type": design_module.get("studyType", ""),
            "enrollment": enrollment.get("count", 0),
            "allocation": design_info.get("allocation", ""),
            "intervention_model": design_info.get("interventionModel", ""),
            "primary_purpose": design_info.get("primaryPurpose", ""),
            "masking": (design_info.get("maskingInfo", {}) or {}).get("masking", ""),
        }

    def _extract_eligibility(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        eligibility = ps.get("eligibilityModule", {})
        return {
            "min_age": eligibility.get("minimumAge", ""),
            "max_age": eligibility.get("maximumAge", ""),
            "sex": eligibility.get("sex", ""),
            "healthy_volunteers": eligibility.get("healthyVolunteers", ""),
            "eligibility_criteria": (eligibility.get("eligibilityCriteria", "") or "")[:1000],
        }

    def _extract_contacts(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        contacts = ps.get("contactsLocationsModule", {}).get("centralContacts", []) or []
        names, emails, phones = [], [], []
        for contact in contacts:
            if contact.get("name"):
                names.append(contact["name"])
            if contact.get("email"):
                emails.append(contact["email"])
            if contact.get("phone"):
                phones.append(contact["phone"])
        return {"contact_name": "; ".join(names), "contact_email": "; ".join(emails), "contact_phone": "; ".join(phones)}

    def _extract_timeline(self, ps: Dict[str, Any]) -> Dict[str, Any]:
        status = ps.get("statusModule", {})
        return {
            "start_date": status.get("startDateStruct", {}).get("date", ""),
            "completion_date": status.get("completionDateStruct", {}).get("date", ""),
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date", ""),
        }

    # ---------------------------------------------------------------------
    # Export
    # ---------------------------------------------------------------------
    def export_to_xlsx(self, filename: Optional[str] = None, column_order: Optional[List[str]] = None) -> Optional[str]:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.utils import get_column_letter
        except ImportError:
            print("❌ openpyxl not installed. Run: pip install openpyxl")
            return None

        if not self.extracted_data:
            print("❌ No data to export")
            return None

        if filename is None:
            filename = f"ClinicalTrials_Export_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.xlsx"

        all_keys: Set[str] = set()
        for row in self.extracted_data:
            all_keys.update(row.keys())

        if column_order:
            fieldnames = [col for col in column_order if col in all_keys]
            fieldnames.extend([col for col in sorted(all_keys) if col not in fieldnames])
        else:
            fieldnames = sorted(all_keys)
            for field in reversed(["nct_id", "title", "status", "lead_sponsor"]):
                if field in fieldnames:
                    fieldnames.remove(field)
                    fieldnames.insert(0, field)

        wb = Workbook()
        ws = wb.active
        ws.title = "Clinical Trials Data"

        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for col_idx, fieldname in enumerate(fieldnames, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = fieldname.replace("_", " ").title()
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment

        for row_idx, record in enumerate(self.extracted_data, 2):
            for col_idx, fieldname in enumerate(fieldnames, 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.value = record.get(fieldname, "")
                if fieldname in ["title", "eligibility_criteria", "conditions", "collaborators", "facilities"]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")

        for col_idx, fieldname in enumerate(fieldnames, 1):
            letter = get_column_letter(col_idx)
            if fieldname == "nct_id":
                width = 12
            elif fieldname == "title":
                width = 55
            elif fieldname in ["eligibility_criteria", "conditions", "collaborators", "facilities"]:
                width = 45
            elif fieldname in ["lead_sponsor", "principal_investigators"]:
                width = 30
            else:
                width = 18
            ws.column_dimensions[letter].width = width

        ws.freeze_panes = "A2"
        wb.save(filename)
        return filename

    def export_to_csv(self, filename: Optional[str] = None) -> Optional[str]:
        if not self.extracted_data:
            return None
        if filename is None:
            filename = f"ClinicalTrials_Export_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.csv"
        all_keys: Set[str] = set()
        for row in self.extracted_data:
            all_keys.update(row.keys())
        fieldnames = sorted(all_keys)
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.extracted_data)
        return filename
