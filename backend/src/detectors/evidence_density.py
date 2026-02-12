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
from config.settings import get_settings


class EvidenceDensityDetector(BaseDetector):
    """
    Evidence Density Detector.
    
    Evaluates Layer 4 criteria:
    "4. Evidence Mapping | 15% | Claims vs Sources ratio"
    
    This detector:
    1. Extracts quantifiable claims (numbers, %, dates)
    2. Extracts authoritative statements ("studies show")
    3. Checks proximity of citation signals (<a href>, [1], (Source: ...))
    
    Attributes:
        dimension_name: "evidence_density"
        weight: 0.15 (15% of total score)
    """
    
    dimension_name: str = "evidence_density"
    weight: float = 0.15
    
    # Claim Detection Patterns
    CLAIM_PATTERNS = [
        # Statistical / Numerical
        r'\d+(\.\d+)?%', # Percentage (e.g., 75%)
        r'\b\d{1,3}(,\d{3})* (million|billion|trillion|users|customers|dollars|euros)\b', # Large numbers
        r'\bincreased by \d+', # Growth stats
        r'\bdecreased by \d+',
        r'\bgrew to \d+',
        # Authoritative Phrasing
        r'\b(studies|research|reports|data) (show|indicate|prove|suggest|demonstrate)s?\b',
        r'\baccording to \w+',
        r'\bas stated by \w+',
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
        
        # Analyze Claims
        try:
            claims_result = self._analyze_claims(page_data.html_rendered, page_data.text_content)
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
    
    def _analyze_claims(self, html: str, text: str) -> ScoreBreakdown:
        """
        Extract claims and verify against sources.
        Logic:
        1. Split text into sentences.
        2. Filter sentences that match CLAIM_PATTERNS.
        3. For each claim, check if the corresponding HTML block contains a link or citation.
        """
        
        # Simple sentence splitting (can be improved with NLP lib)
        sentences = re.split(r'(?<=[.!?]) +', text)
        
        claims: List[Tuple[str, bool]] = [] # (sentence, is_verified)
        
        # Pre-process HTML to identify linking contexts
        # Mapping simple text snippets to whether they are close to a link
        # This is a heuristic approximation since we don't have full DOM tree mapping here
        # A more robust way: use the HTML directly, split by block tags, check for 'href'.
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 20:
                continue
                
            # Check if sentence is a Claim
            is_claim = any(re.search(p, sentence, re.IGNORECASE) for p in self.CLAIM_PATTERNS)
            
            if is_claim:
                # Verification Logic
                # Check 1: Does the sentence contains a citation marker?
                has_citation_marker = bool(re.search(r'\[\d+\]|\(Source:', sentence, re.IGNORECASE))
                
                # Check 2: Look at the broader text for a citation marker IMMEDIATELY following this sentence
                # (Handle splits like "Stat." and "[1]")
                if not has_citation_marker:
                    # Find sentence location in full text
                    try:
                        idx = text.find(sentence)
                        if idx != -1:
                            # Look ahead 20 chars
                            lookahead = text[idx+len(sentence):idx+len(sentence)+20]
                            if re.search(r'\[\d+\]', lookahead):
                                has_citation_marker = True
                    except Exception:
                        pass

                # Check 3: Link Proximity in HTML (unchanged heuristic)
                try:
                    safe_sent = re.escape(sentence[:30]) 
                    match = re.search(safe_sent, html)
                    has_link_nearby = False
                    if match:
                        start, end = match.span()
                        context = html[max(0, start-200):min(len(html), end+200)]
                        if '<a href' in context or '</a>' in context:
                            has_link_nearby = True
                except Exception:
                    has_link_nearby = False
                            
                is_verified = has_citation_marker or has_link_nearby
                
                claims.append((sentence, is_verified))
        
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
            
        verified_count = sum(1 for _, v in claims if v)
        total_claims = len(claims)
        ratio = (verified_count / total_claims) * 100 if total_claims > 0 else 0
        
        # GOLD STANDARD: Volume Penalization
        # Low volume = capped score, regardless of accuracy
        volume_message = ""
        if total_claims < 3:
            # Cap at 60 for low volume (even if 100% verified)
            evidence_score = min(ratio, 60.0)
            volume_message = " ⚠️ High accuracy but LOW VOLUME (<3 claims)."
        elif total_claims >= 5 and ratio >= 90:
            # Full score only with 5+ claims AND high ratio
            evidence_score = 100.0
        else:
            # Standard calculation
            evidence_score = ratio
        
        # Formatting explanation with visual markers for frontend
        # We limit to 5 samples to avoid clutter
        formatted_claims = []
        for c, v in claims[:5]:
            marker = "✅ Verified" if v else "❌ Unverified"
            # Truncate claim
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
            recommendations.append("CRITICAL: Most statistical/authoritative claims lack citations.")
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
