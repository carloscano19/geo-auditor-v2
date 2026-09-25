"""
GEO-AUDITOR AI - Evidence Density Detector

Layer 4: Evidence & Claims Governance (15% of total score)

Evaluates the "Evidence Density" of content:
- Extracts "Claims": Sentences with statistics, numbers, or authoritative phrasing.
- Verifies "Sources": Checks if claims are supported by external links or citations.

Sub-metrics evaluated:
- Evidence Score: % of Claims with valid sources (100% of layer)

Implementation uses regex to find claims and DOM analysis for link proximity.
"""

import re
from typing import List, Tuple
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from src.utils.lang_patterns import get_lang_patterns, resolve_language
from config.settings import get_settings


from urllib.parse import urlparse


class EvidenceDensityDetector(BaseDetector):
    """
    Evidence Density Detector.
    
    Evaluates Layer 4 criteria:
    "4. Evidence Mapping | 15% | Claims vs Sources ratio"
    
    This detector:
    1. Extracts quantifiable claims (numbers, %, dates)
    2. Extracts authoritative statements ("studies show")
    3. Checks proximity of citation signals (<a href>, [1], (Source: ...), (Fuente: ...))
    
    Attributes:
        dimension_name: "evidence_density"
        weight: 0.20 (20% of total score)
    """
    
    dimension_name: str = "evidence_density"
    weight: float = 0.18
    
    # Claim Detection Patterns (Default English, loaded centrally)
    CLAIM_PATTERNS = get_lang_patterns("en")["claims"]
    
    # Social & Utility Domains (filtered from claim verification)
    SOCIAL_DOMAINS = [
        "facebook.com", "twitter.com", "x.com", "instagram.com", 
        "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com",
        "t.me", "discord.gg", "whatsapp.com", "telegram.org",
        "bsky.app", "threads.net", "wa.me", "reddit.com"
    ]
    
    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()
        
        # Load weights from config if available
        try:
            weights = self.settings.scoring_weights
            evidence_config = weights.get("dimensions", {}).get("evidence_density", {})
            self.weight = evidence_config.get("weight", self.weight)
        except Exception:
            pass
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """Analyze evidence density."""
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        
        # Analyze Claims using detected language patterns and centralized main content
        try:
            lang = resolve_language(page_data)
            patterns = get_lang_patterns(lang)
            from src.utils.text_processing import extract_main_content
            scoped_html, scoped_text = extract_main_content(page_data.html_rendered)
            claims_result = self._analyze_claims(
                html=scoped_html,
                text=scoped_text or page_data.text_content,
                claim_patterns=patterns["claims"],
                base_url=page_data.final_url or page_data.url or "",
                lang_patterns=patterns
            )
            breakdown.append(claims_result)
        except Exception as e:
            errors.append(f"Claim analysis failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Evidence Mapping", 1.0))
            
        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
        )
    
    def _analyze_claims(
        self,
        html: str = "",
        text: str = "",
        claim_patterns: list[str] = None,
        base_url: str = "",
        lang_patterns: dict = None
    ) -> ScoreBreakdown:
        """
        Extract claims and verify against sources.
        Logic:
        1. Clean HTML of boilerplate (nav, header, footer, aside, menus) using clean_html_for_analysis.
        2. Treat each block element (p, li, h1-h6, td, etc.) separately before splitting into sentences,
           ensuring an H2 is never concatenated with following paragraphs.
        3. Filter sentences that match claim patterns.
        4. For each claim, check if the corresponding HTML block or immediately previous/next block contains
           a citation marker or an external, non-social link.
        """
        patterns = claim_patterns if claim_patterns is not None else self.CLAIM_PATTERNS
        from bs4 import BeautifulSoup
        from src.utils.text_processing import clean_html_for_analysis
        
        # 1. Boilerplate removal: exclude nav, header, footer, aside, menu, etc.
        cleaned_html = clean_html_for_analysis(html) if html else ""
        scoped_soup = BeautifulSoup(cleaned_html, 'lxml') if cleaned_html else None
        
        # 2. Extract blocks separately
        block_tags = ['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'blockquote', 'figcaption']
        sentences_with_blocks: List[Tuple[str, Optional[object]]] = []
        
        if scoped_soup:
            raw_blocks = scoped_soup.find_all(block_tags)
            # Use leaf blocks (avoid blocks that contain nested block tags)
            leaf_blocks = [
                b for b in raw_blocks
                if not any(child.name in block_tags for child in b.find_all(block_tags))
            ]
            for block in leaf_blocks:
                block_text = block.get_text(separator=' ', strip=True)
                if not block_text or len(block_text) < 15:
                    continue
                # Split each block into sentences separately
                for s in re.split(r'(?<=[.!?])\s+', block_text):
                    s_clean = s.strip()
                    if s_clean and len(s_clean) >= 20:
                        sentences_with_blocks.append((s_clean, block))
        else:
            # Fallback for plain text mode without HTML
            raw_paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
            for p in raw_paragraphs:
                for s in re.split(r'(?<=[.!?])\s+', p):
                    s_clean = s.strip()
                    if s_clean and len(s_clean) >= 20:
                        sentences_with_blocks.append((s_clean, None))
        
        claims: List[Tuple[str, bool]] = []  # (sentence, is_verified)
        
        # Extract base domain for external link verification
        base_domain = ""
        if base_url:
            try:
                base_domain = urlparse(base_url).netloc.lower().replace("www.", "")
            except Exception:
                pass
        
        # Helper to find if a sentence exists near a link or citation in the DOM
        def is_verified_in_dom(sentence_text: str, source_block = None) -> bool:
            # 1. Check for explicit citation markers in text: [1], (Source:, (Fuente:
            if re.search(r'\[\d+\]|\(Source:|\(Fuente:', sentence_text, re.IGNORECASE):
                return True
                
            # 2. If source_block exists, check external non-social links in source block or immediate siblings
            if source_block:
                blocks_to_check = [source_block]
                prev_block = source_block.find_previous_sibling(['p', 'li', 'td', 'th', 'blockquote', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if prev_block:
                    blocks_to_check.append(prev_block)
                next_block = source_block.find_next_sibling(['p', 'li', 'td', 'th', 'blockquote', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if next_block:
                    blocks_to_check.append(next_block)

                for b in blocks_to_check:
                    for a in b.find_all('a'):
                        href = a.get('href', '').strip()
                        if not href.startswith(('http://', 'https://')):
                            continue
                        try:
                            domain = urlparse(href).netloc.lower().replace("www.", "")
                            if not domain:
                                continue
                            if base_domain and (domain == base_domain or domain.endswith("." + base_domain)):
                                continue
                            if any(social in domain for social in self.SOCIAL_DOMAINS):
                                continue
                            return True
                        except Exception:
                            continue
                        
            return False

        # Check methodology signals across full text
        has_methodology = False
        methodology_patterns = []
        first_party_patterns = []
        if lang_patterns:
            methodology_patterns = lang_patterns.get("methodology_signals", [])
            first_party_patterns = lang_patterns.get("first_party_claims", [])
        else:
            from src.utils.lang_patterns import PATTERNS_BY_LANG
            methodology_patterns = PATTERNS_BY_LANG["en"]["methodology_signals"] + PATTERNS_BY_LANG["es"]["methodology_signals"]
            first_party_patterns = PATTERNS_BY_LANG["en"]["first_party_claims"] + PATTERNS_BY_LANG["es"]["first_party_claims"]

        for pat in methodology_patterns:
            if re.search(pat, text, re.IGNORECASE):
                has_methodology = True
                break

        claims: List[Tuple[str, bool, Optional[str]]] = []  # (sentence, is_verified, verified_type)

        for sentence, block in sentences_with_blocks:
            # Check if sentence is a Claim
            is_claim = any(re.search(p, sentence, re.IGNORECASE) for p in patterns)
            if is_claim:
                is_verified = False
                verified_type = None

                # 1. External DOM / explicit citation marker verification
                if is_verified_in_dom(sentence, block):
                    is_verified = True
                    verified_type = "external"
                # 2. First-party methodology verification
                elif has_methodology and any(re.search(p, sentence, re.IGNORECASE) for p in first_party_patterns):
                    is_verified = True
                    verified_type = "first_party"

                claims.append((sentence, is_verified, verified_type))
        
        # Scoring
        if not claims:
            return ScoreBreakdown(
                name="Evidence Mapping",
                raw_score=50.0, # Neutral score for no claims
                weight=1.0,
                weighted_score=50.0,
                explanation="No strong claims or statistics detected requiring verification (Neutral 50).",
                recommendations=["Content is descriptive. Add data/stats to increase authority."],
            )
            
        verified_count = sum(1 for _, v, _ in claims if v)
        total_claims = len(claims)
        ratio = (verified_count / total_claims) * 100 if total_claims > 0 else 0
        
        # GOLD STANDARD: Volume Penalization
        volume_message = ""
        if total_claims < 3:
            # Cap at 60 for low volume
            evidence_score = min(ratio, 60.0)
            volume_message = " ⚠️ High accuracy but LOW VOLUME (<3 claims)."
        elif total_claims >= 5 and ratio >= 90:
            evidence_score = 100.0
        else:
            evidence_score = ratio
        
        # Formatting explanation with visual markers for frontend
        formatted_claims = []
        for c, v, v_type in claims[:5]:
            if v:
                marker = "✅ Verified (first-party data)" if v_type == "first_party" else "✅ Verified"
            else:
                marker = "❌ Unverified"
            clean_claim = (c[:60] + '...') if len(c) > 60 else c
            formatted_claims.append(f"{marker}: \"{clean_claim}\"")
        
        explanation = (
            f"Evidence Score: {evidence_score:.0f}/100. "
            f"Found {verified_count}/{total_claims} verified claims.{volume_message} "
            f"Claims identified: {', '.join(formatted_claims)}"
        )
        
        recommendations = []
        if total_claims < 3:
            recommendations.append("LOW VOLUME: Add more data points, statistics, or authoritative claims to strengthen content.")
        if evidence_score < 50:
            recommendations.append("Most statistical/authoritative claims lack citations.")
        if evidence_score < 90 and total_claims >= 3:
            recommendations.append("Add hyperlinks or [citations] to all data points and 'studies show' statements.")
        
        return ScoreBreakdown(
            name="Evidence Density",
            raw_score=evidence_score,
            weight=1.0,
            weighted_score=evidence_score,
            explanation=explanation,
            recommendations=recommendations,
        )

    def _create_error_breakdown(self, name: str, weight: float) -> ScoreBreakdown:
        """Create a zero-score breakdown for failed checks."""
        return ScoreBreakdown(
            name=name,
            raw_score=0.0,
            weight=weight,
            weighted_score=0.0,
            explanation=f"Error analyzing {name}. Score: 0.",
            recommendations=[f"Manual verification required: {name}."],
        )
