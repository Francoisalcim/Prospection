#!/usr/bin/env python3
"""
Clinical Trials Prospector - Python Backend
Fetches data from ClinicalTrials.gov API v2 and filters out universities/institutes
"""

import requests
import json
import csv
import time
from typing import List, Dict, Set
from collections import defaultdict
from datetime import datetime
import re


class ClinicalTrialsProspector:
    """Handles fetching and processing clinical trials data"""
    
    BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
    
    # Keywords that indicate academic/research institutions (not commercial companies)
    EXCLUDE_KEYWORDS = [
        'university', 'universite', 'universität', 'universidad',
        'institute', 'institut', 'instituto',
        'college', 'school',
        'hospital', 'medical center', 'health system',
        'foundation', 'fundacion',
        'research center', 'research centre',
        'academy', 'academie'
    ]
    
    def __init__(self):
        self.trials_data = []
        self.companies_data = {}
        
    def is_company(self, name: str) -> bool:
        """
        Check if the organization name is a company (not university/institute)
        Returns False if any exclude keyword is found
        """
        if not name:
            return False
            
        name_lower = name.lower()
        
        # Check for exclusion keywords
        for keyword in self.EXCLUDE_KEYWORDS:
            if keyword in name_lower:
                return False
        
        return True
    
    def build_query_term(self, keywords: List[str], phases: List[str] = None) -> str:
        """Build the query.term parameter for the API"""
        if len(keywords) == 1:
            keyword_part = keywords[0]
        else:
            quoted_keywords = ['"{}"'.format(k) for k in keywords]
            keyword_part = "({})".format(' OR '.join(quoted_keywords))
        
        if not phases:
            return keyword_part
        
        phase_part = "AREA[Phase]({})".format(' OR '.join(phases))
        return "{} AND {}".format(keyword_part, phase_part)
    
    def fetch_trials(self, 
                     keywords: List[str],
                     statuses: List[str] = None,
                     phases: List[str] = None,
                     max_results: int = 500) -> List[Dict]:
        """
        Fetch clinical trials from ClinicalTrials.gov API with pagination
        
        Args:
            keywords: List of search keywords
            statuses: List of study statuses to filter
            phases: List of study phases to filter
            max_results: Maximum number of results to fetch
        
        Returns:
            List of study dictionaries
        """
        self.trials_data = []
        page_size = 100
        page_token = None
        
        query_term = self.build_query_term(keywords, phases)
        
        print("🔍 Searching for: {}".format(query_term))
        print("📊 Filters: Statuses={}, Max Results={}".format(statuses or 'All', max_results))
        
        while len(self.trials_data) < max_results:
            params = {
                'query.term': query_term,
                'pageSize': min(page_size, max_results - len(self.trials_data)),
                'format': 'json',
                'countTotal': 'true'
            }
            
            if statuses:
                params['filter.overallStatus'] = ','.join(statuses)
            
            if page_token:
                params['pageToken'] = page_token
            
            print("📥 Fetching... ({}/{})".format(len(self.trials_data), max_results))
            
            try:
                response = requests.get(self.BASE_URL, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                studies = data.get('studies', [])
                if not studies:
                    break
                
                self.trials_data.extend(studies)
                
                page_token = data.get('nextPageToken')
                if not page_token:
                    break
                
                time.sleep(0.2)
                
            except requests.exceptions.RequestException as e:
                print("❌ Error fetching data: {}".format(e))
                break
        
        print("✅ Fetched {} trials".format(len(self.trials_data)))
        return self.trials_data
    
    def extract_companies(self, trials: List[Dict] = None) -> Dict:
        """
        Extract company information from trials, filtering out universities/institutes
        
        Returns:
            Dictionary with company names as keys and their details as values
        """
        if trials is None:
            trials = self.trials_data
        
        self.companies_data = {}
        excluded_count = 0
        
        for study in trials:
            try:
                ps = study.get('protocolSection', {})
                nct_id = ps.get('identificationModule', {}).get('nctId', '')
                
                # Get sponsors and collaborators
                sponsors_module = (ps.get('sponsorsCollaboratorsModule') or 
                                 ps.get('sponsorCollaboratorsModule', {}))
                
                # Process lead sponsor
                lead_sponsor = sponsors_module.get('leadSponsor', {})
                if lead_sponsor.get('name'):
                    name = lead_sponsor['name'].strip()
                    if self.is_company(name):
                        self._upsert_company(name, 'LEAD', nct_id)
                    else:
                        excluded_count += 1
                
                # Process collaborators
                collaborators = sponsors_module.get('collaborators', [])
                for collab in collaborators:
                    if collab.get('name'):
                        name = collab['name'].strip()
                        if self.is_company(name):
                            self._upsert_company(name, 'COLLAB', nct_id)
                        else:
                            excluded_count += 1
                            
            except Exception as e:
                print("⚠️  Warning: Error processing study {}: {}".format(nct_id, e))
                continue
        
        print("🏢 Found {} companies".format(len(self.companies_data)))
        print("🎓 Excluded {} universities/institutes/hospitals".format(excluded_count))
        
        return self.companies_data
    
    def _upsert_company(self, name: str, role: str, nct_id: str):
        """Add or update company in the companies_data dictionary"""
        if name not in self.companies_data:
            self.companies_data[name] = {
                'name': name,
                'lead_count': 0,
                'collab_count': 0,
                'trial_count': 0,
                'nct_ids': set()
            }
        
        company = self.companies_data[name]
        
        if role == 'LEAD':
            company['lead_count'] += 1
        elif role == 'COLLAB':
            company['collab_count'] += 1
        
        company['trial_count'] += 1
        if nct_id:
            company['nct_ids'].add(nct_id)
    
    def export_to_csv(self, filename: str = None, target_role: str = None):
        """Export companies to CSV for PhantomBuster"""
        if not self.companies_data:
            print("❌ No data to export")
            return
        
        if filename is None:
            date = datetime.now().strftime('%Y-%m-%d')
            filename = f"ClinicalTrials_Companies_{date}.csv"
        
        # Sort by trial count
        sorted_companies = sorted(
            self.companies_data.values(),
            key=lambda x: x['trial_count'],
            reverse=True
        )
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=";")
            
            if target_role:
                writer.writerow([
                    'Company Name',
                    'Role (ClinicalTrials)',
                    'Target Role (LinkedIn)',
                    'Lead Sponsor Mentions',
                    'Collaborator Mentions',
                    'Total Mentions',
                    'LinkedIn People Search URL'
                ])
            else: 
                writer.writerow([
                    'Company Name',
                    'Role (ClinicalTrials)',
                    'Lead Sponsor Mentions',
                    'Collaborator Mentions',
                    'Total Mentions',
                    'LinkedIn Company Search URL'
                ])
            
            # Data rows
            for company in sorted_companies:
                role_label = self._get_role_label(company)
                company_name = company['name']

                if target_role:
                    # People search: keyword = "{role} {company}"
                    # (this is the most reliable without Sales Navigator/company-id filters)
                    keywords = f'{target_role} "{company_name}"'
                    linkedin_url = (
                        "https://www.linkedin.com/search/results/people/"
                        f"?keywords={requests.utils.quote(keywords)}"
                    )

                    writer.writerow([
                        company_name,
                        role_label,
                        target_role,
                        company['lead_count'],
                        company['collab_count'],
                        company['trial_count'],
                        linkedin_url
                    ])
                else:
                    # Company search (your current behavior)
                    linkedin_url = (
                        "https://www.linkedin.com/search/results/companies/"
                        f"?keywords={requests.utils.quote(company_name)}"
                    )

                    writer.writerow([
                        company_name,
                        role_label,
                        company['lead_count'],
                        company['collab_count'],
                        company['trial_count'],
                        linkedin_url
                    ])

        print("✅ Exported to {}".format(filename))
        return filename
    
    def export_detailed_to_csv(self, filename: str = None):
        """Export detailed trial information to CSV"""
        if not self.trials_data:
            print("❌ No data to export")
            return
        
        if filename is None:
            date = datetime.now().strftime('%Y-%m-%d')
            filename = f"ClinicalTrials_Detailed_{date}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=";")
            
            # Header
            writer.writerow([
                'NCT ID',
                'Title',
                'Status',
                'Phase',
                'Lead Sponsor',
                'Collaborators',
                'Conditions',
                'Start Date',
                'URL'
            ])
            
            # Data rows
            for study in self.trials_data:
                ps = study.get('protocolSection', {})
                id_module = ps.get('identificationModule', {})
                status_module = ps.get('statusModule', {})
                design_module = ps.get('designModule', {})
                cond_module = ps.get('conditionsModule', {})
                sponsors_module = (ps.get('sponsorsCollaboratorsModule') or 
                                 ps.get('sponsorCollaboratorsModule', {}))
                
                nct_id = id_module.get('nctId', '')
                
                # Get collaborators
                collaborators = sponsors_module.get('collaborators', [])
                collab_names = [c.get('name', '') for c in collaborators if c.get('name')]
                
                writer.writerow([
                    nct_id,
                    id_module.get('briefTitle', ''),
                    status_module.get('overallStatus', ''),
                    ', '.join(design_module.get('phases', [])),
                    sponsors_module.get('leadSponsor', {}).get('name', ''),
                    '; '.join(collab_names),
                    '; '.join(cond_module.get('conditions', [])),
                    status_module.get('startDateStruct', {}).get('date', ''),
                    f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ''
                ])
        
        print("✅ Exported detailed data to {}".format(filename))
        return filename
    
    def _get_role_label(self, company: Dict) -> str:
        """Get human-readable role label"""
        if company['lead_count'] > 0 and company['collab_count'] > 0:
            return 'Lead+Collaborator'
        elif company['lead_count'] > 0:
            return 'Lead Sponsor'
        else:
            return 'Collaborator'
    
    def print_summary(self):
        """Print a summary of the results"""
        print("\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print("Total Trials: {}".format(len(self.trials_data)))
        print("Total Companies (filtered): {}".format(len(self.companies_data)))
        
        sponsors = sum(1 for c in self.companies_data.values() if c['lead_count'] > 0)
        collaborators = sum(1 for c in self.companies_data.values() if c['collab_count'] > 0)
        
        print("Companies as Lead Sponsor: {}".format(sponsors))
        print("Companies as Collaborator: {}".format(collaborators))
        
        print("\n🏆 Top 10 Companies by Trial Count:")
        sorted_companies = sorted(
            self.companies_data.values(),
            key=lambda x: x['trial_count'],
            reverse=True
        )[:10]
        
        for i, company in enumerate(sorted_companies, 1):
            role = self._get_role_label(company)
            print("  {:2d}. {:50s} | {:3d} trials | {}".format(
                i, company['name'][:50], company['trial_count'], role))
        
        print("="*60 + "\n")


def main():
    """Example usage"""
    prospector = ClinicalTrialsProspector()
    
    # Example search parameters
    keywords = ['diabetes', 'CAR-T therapy']
    statuses = ['RECRUITING', 'ACTIVE_NOT_RECRUITING', 'COMPLETED']
    phases = ['PHASE2', 'PHASE3']
    
    # Fetch trials
    trials = prospector.fetch_trials(
        keywords=keywords,
        statuses=statuses,
        phases=phases,
        max_results=500
    )
    
    # Extract companies (automatically filters out universities/institutes)
    companies = prospector.extract_companies()
    
    # Print summary
    prospector.print_summary()
    
    # Export results
    prospector.export_to_csv()
    prospector.export_detailed_to_csv()


if __name__ == "__main__":
    main()