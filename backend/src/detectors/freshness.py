"""
GEO-AUDITOR AI - Freshness & Temporal Relevance Detector

Phase 7: Freshness (Layer 7 - 10%)
Evaluates content currency and temporal relevance.
"""

import re
from datetime import datetime
from typing import Optional
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown

class FreshnessDetector(BaseDetector):
    """
    Detector for Content Freshness.
    
    Evaluates:
    1. Date Currency: Age of content (Time since published/updated).
    2. Keyword Relevance: Reference to current/future year in Title/H1.
    """
    
    dimension_name = "freshness"
    weight = 0.10
    
    current_year = 2026 # Hardcoded for simulation as per user prompt context (2026)
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        
        # 1. Date Extraction & Currency (60%)
        # ----------------------------------------------------------------
        extracted_date: Optional[datetime] = self._extract_date(page_data)
        
        date_score = 0.0
        date_explanation = "No publication or update date found."
        date_recs = []
        
        if extracted_date:
            # Calculate age
            age_days = (datetime(self.current_year, 2, 6) - extracted_date).days # Mock "now" as Feb 6, 2026
            age_years = age_days / 365.0
            
            if age_years < 1:
                date_score = 100.0
                status = "Fresh"
            elif age_years < 2:
                date_score = 50.0
                status = "Aging"
            else:
                date_score = 0.0
                status = "Outdated"
                
            date_explanation = f"{status}: Last updated on {extracted_date.strftime('%Y-%m-%d')} ({age_days} days ago)."
            if date_score < 100:
                date_recs.append("Update content and refresh the 'dateModified' meta tag.")
        else:
            date_recs.append("Ensure one of these is present: <meta property='article:published_time'>, <time> tag, or 'Updated on' text.")
            
        breakdown.append(ScoreBreakdown(
            name="Date Currency",
            raw_score=date_score,
            weight=0.60,
            weighted_score=date_score * 0.60,
            explanation=f"{'✅' if date_score >= 50 else '❌'} {date_explanation}",
            recommendations=date_recs
        ))
        
        # 2. Keyword Relevance (Current Year) (40%)
        # ----------------------------------------------------------------
        # Check Title and H1 for current year (2026) or next year (2027)
        target_years = [str(self.current_year), str(self.current_year + 1)]
        
        html_lower = page_data.html_raw.lower()
        
        # Extract Title and H1
        title_match = re.search(r'<title>(.*?)</title>', html_lower)
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html_lower)
        
        title_text = title_match.group(1) if title_match else ""
        h1_text = h1_match.group(1) if h1_match else ""
        
        combined_text = title_text + " " + h1_text
        
        found_year = False
        for year in target_years:
            if year in combined_text:
                found_year = True
                break
                
        year_score = 100.0 if found_year else 0.0
        
        year_explanation = f"Current year ({self.current_year}) found in Title/H1." if found_year else f"Current year ({self.current_year}) NOT found in Title/H1."
        year_recs = []
        
        if not found_year:
            year_recs.append(f"Include the current year ({self.current_year}) in your Title tag or H1 to signal relevance.")
            
        breakdown.append(ScoreBreakdown(
            name="Current Year Compliant",
            raw_score=year_score,
            weight=0.40,
            weighted_score=year_score * 0.40,
            explanation=f"{'✅' if found_year else '❌'} {year_explanation}",
            recommendations=year_recs
        ))
        
        # Calculate Total
        score = sum(item.weighted_score for item in breakdown)
        
        for item in breakdown:
            recommendations.extend(item.recommendations)

        return DetectorResult(
            dimension=self.dimension_name,
            score=score,
            weight=self.weight,
            contribution=self.calculate_contribution(score),
            breakdown=breakdown,
            errors=errors
        )
        
    def _extract_date(self, page_data: PageData) -> Optional[datetime]:
        """Try to extract a valid date from metadata, HTML, or text."""
        html = page_data.html_raw
        
        # 1. Meta Tags (ISO Format)
        meta_patterns = [
            r'<meta[^>]+property=["\']article:(published|modified)_time["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:(published|modified)_time["\']',
            r'<meta[^>]+name=["\'](date|pubdate|lastmod)["\'][^>]+content=["\']([^"\']+)["\']',
        ]
        
        for pattern in meta_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                for group in match.groups():
                    if group and len(group) > 5:
                        parsed = self._parse_date(group)
                        if parsed: return parsed

        # 2. Time Tag
        time_match = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if time_match:
            parsed = self._parse_date(time_match.group(1))
            if parsed: return parsed
            
        # 3. Visual Backup (Regex) - Scan top 200 words of text
        first_200_words = " ".join(page_data.text_content.split()[:200])
        
        # Patterns: January 29, 2026 or 29/01/2026
        visual_patterns = [
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            r'(?:updated|published|posted)\s*(?:on)?\s*:?\s*(\d{4}-\d{2}-\d{2})'
        ]
        
        for pattern in visual_patterns:
            match = re.search(pattern, first_200_words, re.IGNORECASE)
            if match:
                # If there's a group, use it, else use whole match
                date_str = match.group(1) if match.groups() else match.group(0)
                parsed = self._parse_date(date_str)
                if parsed: return parsed

        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Helper to parse common date formats."""
        formats = [
            "%Y-%m-%dT%H:%M:%S%z", # ISO with timezone
            "%Y-%m-%dT%H:%M:%S",   # ISO simple
            "%Y-%m-%d",            # Date only
            "%Y/%m/%d",
            "%B %d, %Y",           # January 29, 2026
            "%d/%m/%Y",            # 29/01/2026
            "%m/%d/%Y",            # 01/29/2026
        ]
        
        # Clean string
        date_str = date_str.strip()
        
        for fmt in formats:
            try:
                # Handle Z for UTC
                tmp_date_str = date_str
                if tmp_date_str.endswith('Z'):
                    tmp_date_str = tmp_date_str[:-1]
                # Truncate fractional seconds
                if '.' in tmp_date_str and 'T' in tmp_date_str:
                     tmp_date_str = tmp_date_str.split('.')[0]
                     
                return datetime.strptime(tmp_date_str, fmt)
            except ValueError:
                continue
        return None
