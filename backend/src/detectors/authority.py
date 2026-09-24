"""
GEO-AUDITOR AI - Authority & Trust Detector (E-E-A-T)

Analyzes pages for signals of Authority, Expertise, and Trustworthiness.
Focuses on identifying authors, first-person experience evidence, and trust pages.
"""

import re
import json
from typing import Tuple, Optional
from bs4 import BeautifulSoup
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.utils.lang_patterns import get_lang_patterns, resolve_language

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
    
    # Regex patterns for authorship (Default English, loaded centrally)
    AUTHOR_PATTERNS = get_lang_patterns("en")["authorship"]
    
    # Regex for Experience Signals (Default English, loaded centrally)
    EXPERIENCE_PATTERNS = get_lang_patterns("en")["experience"]

    def _extract_author_from_json_ld(self, html: str) -> Optional[str]:
        """Extract author from JSON-LD schema (Article, BlogPosting, NewsArticle)."""
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, 'lxml')
            for script in soup.find_all('script', type=lambda t: t and 'ld+json' in t):
                try:
                    data = json.loads(script.string or '')
                except Exception:
                    continue
                
                items = []
                if isinstance(data, dict):
                    if '@graph' in data and isinstance(data['@graph'], list):
                        items.extend(data['@graph'])
                    items.append(data)
                elif isinstance(data, list):
                    items.extend(data)
                    
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    types = [item_type] if isinstance(item_type, str) else (item_type if isinstance(item_type, list) else [])
                    types_lower = [str(t).lower() for t in types]
                    
                    if any(t in types_lower for t in ['article', 'blogposting', 'newsarticle']):
                        author_val = item.get('author')
                        if author_val:
                            author_list = [author_val] if isinstance(author_val, (dict, str)) else (author_val if isinstance(author_val, list) else [])
                            for auth in author_list:
                                if isinstance(auth, dict):
                                    name = auth.get('name')
                                    if name and isinstance(name, str) and name.strip():
                                        return name.strip()
                                elif isinstance(auth, str) and auth.strip():
                                    return auth.strip()
        except Exception:
            pass
        return None

    def _extract_author_from_html(self, html: str) -> Optional[str]:
        """Extract author from HTML elements (rel="author", itemprop/class with author/autor)."""
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, 'lxml')
            
            def is_comment_element(el):
                for parent in el.parents:
                    if parent.name in ['div', 'section', 'aside', 'ul', 'ol', 'li']:
                        cls = " ".join(parent.get('class', [])).lower()
                        elem_id = (parent.get('id') or '').lower()
                        if any(c in f"{cls} {elem_id}" for c in ['comment', 'comentario', 'disqus', 'respond']):
                            return True
                return False

            # Check rel="author"
            for el in soup.find_all(attrs={"rel": lambda r: r and "author" in (r if isinstance(r, str) else " ".join(r)).lower()}):
                if is_comment_element(el):
                    continue
                text = el.get_text(separator=" ", strip=True) or el.get('content', '') or el.get('title', '')
                if text and len(text.strip()) < 100:
                    return text.strip()

            # Check itemprop="author" or itemprop="autor"
            for el in soup.find_all(attrs={"itemprop": re.compile(r'aut(?:h)?or', re.I)}):
                if is_comment_element(el):
                    continue
                text = el.get_text(separator=" ", strip=True) or el.get('content', '') or el.get('title', '')
                if text and len(text.strip()) < 100:
                    return text.strip()

            # Check class with "author" or "autor"
            for el in soup.find_all(attrs={"class": re.compile(r'aut(?:h)?or', re.I)}):
                if is_comment_element(el):
                    continue
                text = el.get_text(separator=" ", strip=True) or el.get('content', '')
                if text and len(text.strip()) < 80:
                    return text.strip()
        except Exception:
            pass
        return None

    def _extract_author_from_text(self, text: str, author_patterns: list) -> Optional[str]:
        """Extract author from text content (first 15% and last 10%), excluding comments."""
        if not text:
            return None
            
        # Strip comments
        comment_marker = re.search(r'\n+\s*(?:comments?|comentarios|leave a comment|leave a reply|deja un comentario|respuestas)\b', text, re.I)
        if comment_marker:
            text = text[:comment_marker.start()]
            
        words = text.split()
        if not words:
            return None
            
        total_words = len(words)
        first_15_count = max(min(total_words, 15), int(total_words * 0.15))
        last_10_count = max(min(total_words, 10), int(total_words * 0.10))
        
        first_chunk = " ".join(words[:first_15_count])
        last_chunk = " ".join(words[-last_10_count:]) if total_words > (first_15_count + last_10_count) else ""
        
        CREDENTIAL_PATTERN = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+:\s+[A-ZÁÉÍÓÚÑ][a-zA-ZáéíóúñÁÉÍÓÚÑ\s]+"
        all_patterns = author_patterns + [CREDENTIAL_PATTERN]
        
        for pat in all_patterns:
            m = re.search(pat, first_chunk)
            if m:
                return m.group(0).strip()
                
        if last_chunk:
            for pat in all_patterns:
                m = re.search(pat, last_chunk)
                if m:
                    return m.group(0).strip()
                    
        return None

    async def analyze(self, page_data: PageData) -> DetectorResult:
        score = 0.0
        breakdown = []
        errors = []
        recommendations = []
        
        # Resolve language patterns
        lang = resolve_language(page_data)
        patterns = get_lang_patterns(lang)
        author_patterns = patterns["authorship"]
        experience_patterns = patterns["experience"]
        
        # 1. Authorship Verification (40%)
        # Prioritize reliable sources and stop at the first that gives a result:
        # a) JSON-LD schema (Article/BlogPosting/NewsArticle -> Person name)
        # b) HTML elements (rel="author", class or itemprop with author/autor)
        # c) Text patterns in first 15% and last 10%
        has_author = False
        author_match = None
        
        # Tier a: JSON-LD
        schema_author = self._extract_author_from_json_ld(page_data.html_rendered)
        if schema_author:
            has_author = True
            author_match = f"Author found in schema: {schema_author}"
        
        # Tier b: HTML attributes
        if not has_author:
            html_author = self._extract_author_from_html(page_data.html_rendered)
            if html_author:
                has_author = True
                author_match = f"Author found in HTML attribute: {html_author}"
                
        # Tier c: Text content
        if not has_author:
            text_author = self._extract_author_from_text(page_data.text_content, author_patterns)
            if text_author:
                has_author = True
                author_match = f"Author found in content: {text_author}"

        auth_score = 100.0 if has_author else 0.0
        auth_explanation = author_match if has_author else "No clear authorship attribution found."
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
        for pattern in experience_patterns:
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
        # Categories (supports English and Spanish trust paths)
        HIGH_VALUE = [
            "about", "team", "editorial", "authors", "staff", 
            "sobre-nosotros", "equipo", "quienes-somos", "autores",
            "sobre-mi", "quien-soy", "about-me", "acerca-de", "conoceme"
        ]
        BASIC = ["privacy", "terms", "policy", "legal", "contact", "privacidad", "terminos", "contacto", "aviso-legal"]
        
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
