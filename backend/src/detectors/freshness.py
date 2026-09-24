"""
GEO-AUDITOR AI - Freshness & Temporal Relevance Detector

Phase 7: Freshness (Layer 7 - 10%)
Evaluates content currency and temporal relevance.
"""

import re
from datetime import datetime, timezone
from typing import Optional
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.utils.lang_patterns import get_lang_patterns, resolve_language, parse_date_string

class FreshnessDetector(BaseDetector):
    """
    Detector for Content Freshness.
    
    Evaluates:
    1. Date Currency: Age of content (Time since published/updated).
    2. Keyword Relevance: Reference to current/future year in Title/H1.
    """
    
    dimension_name = "freshness"
    weight = 0.05
    
    @property
    def current_year(self) -> int:
        return datetime.now(timezone.utc).year
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        now_utc = datetime.now(timezone.utc)
        
        # 1. Date Extraction & Currency (100%)
        # ----------------------------------------------------------------
        lang = resolve_language(page_data)
        extracted_date: Optional[datetime] = self._extract_date(page_data, lang=lang)
        
        date_score = 0.0
        date_explanation = "No publication or update date found."
        date_recs = []
        
        if extracted_date:
            # Calculate age (handle timezone-aware and naive safely)
            if extracted_date.tzinfo is not None:
                diff_seconds = (now_utc - extracted_date).total_seconds()
            else:
                diff_seconds = (now_utc.replace(tzinfo=None) - extracted_date).total_seconds()
            
            # Future dates are treated as 0 age
            age_days = max(0, int(diff_seconds // 86400))
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
            weight=1.00,
            weighted_score=date_score * 1.00,
            explanation=f"{'✅' if date_score >= 50 else '❌'} {date_explanation}",
            recommendations=date_recs
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

        
    def _extract_date(self, page_data: PageData, lang: str = "en") -> Optional[datetime]:
        """Try to extract a valid date from metadata, HTML, or text."""
        html = page_data.html_rendered
        
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
                        parsed = self._parse_date(group, lang=lang)
                        if parsed: return parsed

        # 2. Time Tag
        time_match = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if time_match:
            parsed = self._parse_date(time_match.group(1), lang=lang)
            if parsed: return parsed
            
        # 3. Visual Backup (Regex) - Scan top 200 words of text
        first_200_words = " ".join(page_data.text_content.split()[:200])
        
        # Load language visual patterns
        patterns_dict = get_lang_patterns(lang)
        visual_patterns = patterns_dict.get("visual_date_patterns", [])
        
        for pattern in visual_patterns:
            match = re.search(pattern, first_200_words, re.IGNORECASE)
            if match:
                # If there's a group, use it, else use whole match
                date_str = match.group(1) if match.groups() else match.group(0)
                parsed = self._parse_date(date_str, lang=lang)
                if parsed: return parsed

        return None

    def _parse_date(self, date_str: str, lang: str = "en") -> Optional[datetime]:
        """Helper to parse common date formats across languages."""
        if not date_str:
            return None
            
        # Try centralized bilingual parser first
        parsed = parse_date_string(date_str, lang=lang)
        if parsed:
            return parsed
            
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
        cleaned_date_str = date_str.strip()
        
        for fmt in formats:
            try:
                # Handle Z for UTC
                tmp_date_str = cleaned_date_str
                if tmp_date_str.endswith('Z'):
                    tmp_date_str = tmp_date_str[:-1]
                # Truncate fractional seconds
                if '.' in tmp_date_str and 'T' in tmp_date_str:
                     tmp_date_str = tmp_date_str.split('.')[0]
                     
                return datetime.strptime(tmp_date_str, fmt)
            except ValueError:
                continue
        return None
