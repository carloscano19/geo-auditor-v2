"""
GEO-AUDITOR AI - Authority & Trust Detector (E-E-A-T)

Analyzes pages for signals of Authority, Expertise, and Trustworthiness.
Focuses on identifying authors, first-person experience evidence, and trust pages.
"""

import re
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown

class AuthorityDetector(BaseDetector):
    """
    Detector for E-E-A-T signals (Authority, Expertise, Trust).
    
    Evaluates:
    1. Authorship Identification: 'Written by', 'rel=author', etc.
    2. Experience Signals: First-person verification ('I tested', 'We found').
    3. Trust Infrastructure: Presence of About, Contact, Privacy pages.
    """
    
    dimension_name = "eeat_authority"
    weight = 0.15  # 15% of total score
    
    # Regex patterns for authorship - Strict: Requires triggered by words + 2 Capitalized Words (Name Surname)
    AUTHOR_PATTERNS = [
        r"(?i:written by)\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
        r"(?i:author:)\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
        r"(?i:by)\s+(?!the\b)[A-Z][a-z]+\s+[A-Z][a-z]+",
        r"(?i:reviewed by)\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
        r"(?i:fact checked by)\s+[A-Z][a-z]+\s+[A-Z][a-z]+"
    ]
    
    # Regex for Experience Signals (First-person verbs)
    EXPERIENCE_PATTERNS = [
        r"(?i)\b(i|we)\s+(tested|analyzed|found|discovered|observed|evaluated|reviewed|verified)",
        r"(?i)\bin\s+(my|our)\s+(experience|opinion|view|analysis|testing)",
        r"(?i)\b(i|we)\s+have\s+(used|tried|spent)",
        r"(?i)\b(i|we)\s+personally",
        r"(?i)\bhand-on\s+(test|review|experience)"
    ]

    async def analyze(self, page_data: PageData) -> DetectorResult:
        score = 0.0
        breakdown = []
        errors = []
        recommendations = []
        
        # 1. Authorship Verification (40%)
        # ----------------------------------------------------------------
        has_author = False
        author_match = None
        
        # Pattern 'Credential': Detects lines like "Name: Job Title"
        CREDENTIAL_PATTERN = r"(?i)[A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+:\s+[A-Z][a-zA-Z\s]+"
        
        # Check text content (Normal patterns)
        for pattern in self.AUTHOR_PATTERNS:
            match = re.search(pattern, page_data.text_content)
            if match:
                has_author = True
                author_match = match.group(0)
                break
        
        # DEEP SCAN: Check bottom 10% of text
        if not has_author:
            words = page_data.text_content.split()
            bottom_10_start = int(len(words) * 0.9)
            bottom_text = " ".join(words[bottom_10_start:])
            
            for pattern in self.AUTHOR_PATTERNS + [CREDENTIAL_PATTERN]:
                match = re.search(pattern, bottom_text)
                if match:
                    has_author = True
                    author_match = f"{match.group(0)} (Found in Footer area)"
                    break

        # Check HTML for rel="author" or similar meta tags if text check fails
        if not has_author:
            if 'rel="author"' in page_data.html_raw or 'class="author"' in page_data.html_raw:
                has_author = True
                author_match = "Meta/HTML Attribute"

        auth_score = 100.0 if has_author else 0.0
        
        auth_explanation = f"Author signals found: {author_match}" if has_author else "No clear authorship attribution found."
        auth_recs = []
        if not has_author:
            auth_recs.append("Add a clear 'Written by [Name]' byline with author credentials.")
            
        breakdown.append(ScoreBreakdown(
            name="Authorship Verification",
            raw_score=auth_score,
            weight=0.40,
            weighted_score=auth_score * 0.40,
            explanation=f"{'✅' if has_author else '❌'} {auth_explanation}",
            recommendations=auth_recs
        ))
        
        # 2. Experience Signals (35%)
        # ----------------------------------------------------------------
        exp_matches = []
        for pattern in self.EXPERIENCE_PATTERNS:
            matches = re.findall(pattern, page_data.text_content)
            exp_matches.extend(matches)
            
        signal_count = len(exp_matches)
        
        # Scoring logic: >3 strong, 1-2 moderate, 0 weak
        if signal_count >= 3:
            exp_score = 100.0
            exp_status = "Strong"
        elif signal_count >= 1:
            exp_score = 60.0
            exp_status = "Moderate"
        else:
            exp_score = 0.0
            exp_status = "Weak"
            
        exp_explanation = f"Found {signal_count} first-person experience signals."
        exp_recs = []
        if signal_count < 3:
            exp_recs.append("Use more first-person language ('I tested', 'We found') to demonstrate real experience.")
            
        breakdown.append(ScoreBreakdown(
            name="Experience Signals",
            raw_score=exp_score,
            weight=0.35,
            weighted_score=exp_score * 0.35,
            explanation=f"{'✅' if signal_count > 0 else '❌'} {exp_status} Experience: {exp_explanation}",
            recommendations=exp_recs
        ))
        
        # 3. Trust Pages (25%) - STRICT CRITERIA
        # ----------------------------------------------------------------
        trust_pages_found = []
        # Categories
        HIGH_VALUE = ["about", "team", "editorial", "authors", "staff"]
        BASIC = ["privacy", "terms", "policy", "legal", "contact"]
        
        html_lower = page_data.html_rendered.lower()
        
        for kw in HIGH_VALUE + BASIC:
            if re.search(r'href=[\'"][^\'"]*?' + re.escape(kw) + r'[^\'"]*?[\'"]', html_lower):
                trust_pages_found.append(kw)
        
        trust_pages_found = list(set(trust_pages_found))
        has_high_value = any(kw in trust_pages_found for kw in HIGH_VALUE)
        has_basic = any(kw in trust_pages_found for kw in BASIC)
        
        if has_high_value and len(trust_pages_found) >= 3:
            trust_score = 100.0
        elif has_high_value:
            trust_score = 70.0 # High value present but few pages
        elif has_basic:
            trust_score = 40.0 # CAP: Only basic compliance
        else:
            trust_score = 0.0
            
        trust_explanation = f"Found trust pages: {', '.join(trust_pages_found)}."
        if trust_score == 40.0:
            trust_explanation += " (Capped: Missing High-Value signals like 'About Us' or 'Team')"
            
        trust_recs = []
        if not has_high_value:
             trust_recs.append("CRITICAL: Add 'About Us' and 'Our Team' pages to build Authority.")
        if len(trust_pages_found) < 3:
             trust_recs.append("Increase transparency by linking Editorial Guidelines and Staff profiles.")
                
        breakdown.append(ScoreBreakdown(
            name="Trust Pages",
            raw_score=trust_score,
            weight=0.25,
            weighted_score=trust_score * 0.25,
            explanation=f"{'✅' if trust_score >= 70 else '⚠️' if trust_score > 0 else '❌'} {trust_explanation}",
            recommendations=trust_recs
        ))

        # Calculate Total Score
        total_contribution = sum(item.weighted_score for item in breakdown)
        # Normalize: Since weights sum to 1.0 (0.4+0.35+0.25), the sum is the score.
        score = total_contribution
        
        # Add all recommendations to main list
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
