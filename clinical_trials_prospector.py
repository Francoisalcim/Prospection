#!/usr/bin/env python3
"""
Clinical Trials Prospector - Python Backend with Flexible Filtering
Allows users to select which organization types to include/exclude
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
    
    # Organization type categories with keywords
    # Users can select which types to INCLUDE or EXCLUDE
    ORGANIZATION_TYPES = {
        'university': {
            'keywords': ['university', 'universite', 'universität', 'universidad', 'universiti', 
                        'college', 'école'],
            'label': 'Universities & Colleges'
        },
        'institute': {
            'keywords': ['institute', 'institut', 'instituto', 'research center', 'research centre'],
            'label': 'Research Institutes'
        },
        'hospital': {
            'keywords': ['hospital', 'medical center', 'medical centre', 'health system', 
                        'health center', 'clinic', 'clinique', 'klinik'],
            'label': 'Hospitals & Medical Centers'
        },
        'government': {
            'keywords': ['national institutes', 'nih', 'ministry of health', 'department of health',
                        'veterans affairs', 'va medical', 'public health', 'government'],
            'label': 'Government Agencies'
        },
        'foundation': {
            'keywords': ['foundation', 'fondation', 'fundacion', 'stichting', 'trust fund'],
            'label': 'Foundations & Trusts'
        },
        'academic': {
            'keywords': ['school of medicine', 'school of pharmacy', 'faculty of', 
                        'academy', 'academie', 'academic'],
            'label': 'Academic Medical Centers'
        },
        'nonprofit': {
            'keywords': ['nonprofit', 'non-profit', 'charity', 'charitable', 'society', 
                        'association', 'organization'],
            'label': 'Non-Profit Organizations'
        },
        'company': {
            # No keywords - these are identified by NOT matching other categories
            'keywords': [],
            'label': 'Commercial Companies (default)'
        }
    }
    
    def __init__(self, include_types=None, exclude_types=None):
        """
        Initialize prospector with filtering options
        
        Args:
            include_types: List of organization types to INCLUDE (None = all)
            exclude_types: List of organization types to EXCLUDE (None = none)
        
        Example:
            # Only include companies
            prospector = ClinicalTrialsProspector(include_types=['company'])
            
            # Include everything except universities and hospitals
            prospector = ClinicalTrialsProspector(exclude_types=['university', 'hospital'])
        """
        self.trials_data = []
        self.companies_data = {}
        self.include_types = include_types
        self.exclude_types = exclude_types or []
        
    def get_organization_type(self, name: str) -> str:
        """
        Determine the organization type based on its name
        
        Returns:
            Type key (e.g., 'university', 'hospital', 'company')
        """
        if not name:
            return 'unknown'
            
        name_lower = name.lower()
        
        # Check each category (except 'company' which is default)
        for org_type, info in self.ORGANIZATION_TYPES.items():
            if org_type == 'company':
                continue
            
            for keyword in info['keywords']:
                if keyword in name_lower:
                    return org_type
        
        # If no match, it's a company
        return 'company'
    
    def should_include_organization(self, name: str) -> bool:
        """
        Check if organization should be included based on filtering rules
        
        Returns:
            True if organization should be included, False otherwise
        """
        if not name:
            return False
        
        org_type = self.get_organization_type(name)
        
        # If include_types is specified, only include those types
        if self.include_types is not None:
            return org_type in self.include_types
        
        # Otherwise, exclude specified types
        return org_type not in self.exclude_types
    
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
                
                # Be polite to the API
                time.sleep(0.2)
                
            except requests.exceptions.RequestException as e:
                print("❌ Error fetching data: {}".format(e))
                break
        
        print("✅ Fetched {} trials".format(len(self.trials_data)))
        return self.trials_data
    
    def extract_companies(self, trials: List[Dict] = None) -> Dict:
        """
        Extract organization information from trials with filtering
        
        Returns:
            Dictionary with organization names as keys and their details as values
        """
        if trials is None:
            trials = self.trials_data
        
        self.companies_data = {}
        stats_by_type = defaultdict(int)
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
                    org_type = self.get_organization_type(name)
                    stats_by_type[org_type] += 1
                    
                    if self.should_include_organization(name):
                        self._upsert_company(name, 'LEAD', nct_id, org_type)
                    else:
                        excluded_count += 1
                
                # Process collaborators
                collaborators = sponsors_module.get('collaborators', [])
                for collab in collaborators:
                    if collab.get('name'):
                        name = collab['name'].strip()
                        org_type = self.get_organization_type(name)
                        stats_by_type[org_type] += 1
                        
                        if self.should_include_organization(name):
                            self._upsert_company(name, 'COLLAB', nct_id, org_type)
                        else:
                            excluded_count += 1
                            
            except Exception as e:
                print("⚠️  Warning: Error processing study {}: {}".format(nct_id, e))
                continue
        
        print("\n📊 Organization Type Breakdown:")
        for org_type, count in sorted(stats_by_type.items(), key=lambda x: x[1], reverse=True):
            label = self.ORGANIZATION_TYPES.get(org_type, {}).get('label', org_type)
            status = "✓ INCLUDED" if (self.include_types is None or org_type in self.include_types) and org_type not in self.exclude_types else "✗ EXCLUDED"
            print(f"  {label:40s}: {count:4d} {status}")
        
        print(f"\n✅ Included: {len(self.companies_data)} organizations")
        print(f"❌ Excluded: {excluded_count} organizations")
        
        return self.companies_data
    
    def _upsert_company(self, name: str, role: str, nct_id: str, org_type: str = 'company'):
        """Add or update organization in the companies_data dictionary"""
        if name not in self.companies_data:
            self.companies_data[name] = {
                'name': name,
                'org_type': org_type,
                'org_type_label': self.ORGANIZATION_TYPES.get(org_type, {}).get('label', org_type),
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
    
    def export_to_csv(self, filename: str = None):
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
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                'Company Name',
                'Organization Type',
                'Role',
                'Lead Sponsor Mentions',
                'Collaborator Mentions',
                'Total Mentions',
                'LinkedIn Company Search URL'
            ])
            
            # Data rows
            for company in sorted_companies:
                role = self._get_role_label(company)
                linkedin_url = f"https://www.linkedin.com/search/results/companies/?keywords={requests.utils.quote(company['name'])}"
                
                writer.writerow([
                    company['name'],
                    company.get('org_type_label', 'Unknown'),
                    role,
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
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                'NCT ID',
                'Title',
                'Status',
                'Phase',
                'Lead Sponsor',
                'Lead Sponsor Type',
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
                lead_name = sponsors_module.get('leadSponsor', {}).get('name', '')
                lead_type = self.get_organization_type(lead_name)
                lead_type_label = self.ORGANIZATION_TYPES.get(lead_type, {}).get('label', lead_type)
                
                # Get collaborators
                collaborators = sponsors_module.get('collaborators', [])
                collab_names = [c.get('name', '') for c in collaborators if c.get('name')]
                
                writer.writerow([
                    nct_id,
                    id_module.get('briefTitle', ''),
                    status_module.get('overallStatus', ''),
                    ', '.join(design_module.get('phases', [])),
                    lead_name,
                    lead_type_label,
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
        print("Total Organizations (filtered): {}".format(len(self.companies_data)))
        
        sponsors = sum(1 for c in self.companies_data.values() if c['lead_count'] > 0)
        collaborators = sum(1 for c in self.companies_data.values() if c['collab_count'] > 0)
        
        print("Organizations as Lead Sponsor: {}".format(sponsors))
        print("Organizations as Collaborator: {}".format(collaborators))
        
        print("\n🏆 Top 10 Organizations by Trial Count:")
        sorted_companies = sorted(
            self.companies_data.values(),
            key=lambda x: x['trial_count'],
            reverse=True
        )[:10]
        
        for i, company in enumerate(sorted_companies, 1):
            role = self._get_role_label(company)
            org_label = company.get('org_type_label', 'Unknown')
            print("  {:2d}. {:40s} | {:3d} trials | {:20s} | {}".format(
                i, company['name'][:40], company['trial_count'], org_label, role))
        
        print("="*60 + "\n")


def main():
    """Example usage"""
    
    # Example 1: Only include commercial companies (default behavior)
    print("\n" + "="*60)
    print("EXAMPLE 1: Only Commercial Companies")
    print("="*60)
    prospector = ClinicalTrialsProspector(include_types=['company'])
    
    trials = prospector.fetch_trials(
        keywords=['diabetes'],
        statuses=['RECRUITING', 'ACTIVE_NOT_RECRUITING'],
        max_results=100
    )
    
    companies = prospector.extract_companies()
    prospector.print_summary()
    
    # Example 2: Include companies AND universities
    print("\n" + "="*60)
    print("EXAMPLE 2: Companies + Universities")
    print("="*60)
    prospector2 = ClinicalTrialsProspector(include_types=['company', 'university'])
    
    trials2 = prospector2.fetch_trials(
        keywords=['mRNA'],
        max_results=100
    )
    
    companies2 = prospector2.extract_companies()
    prospector2.print_summary()
    
    # Example 3: Exclude only hospitals
    print("\n" + "="*60)
    print("EXAMPLE 3: Everything Except Hospitals")
    print("="*60)
    prospector3 = ClinicalTrialsProspector(exclude_types=['hospital'])
    
    trials3 = prospector3.fetch_trials(
        keywords=['CAR-T'],
        max_results=100
    )
    
    companies3 = prospector3.extract_companies()
    prospector3.print_summary()


if __name__ == "__main__":
    main()