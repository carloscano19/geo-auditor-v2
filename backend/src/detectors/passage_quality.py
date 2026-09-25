"""
GEO-AUDITOR AI - Passage Quality Detector

Phase 4b: Evaluates paragraph and passage-level quality for AI citation:
1. Lexical Richness with MTLD (Measure of Textual Lexical Diversity)
2. Complete Sentences (% of substantive paragraphs ending with a period/terminal punctuation)
3. Content Depth (Number of substantive paragraphs >= 25 words)
4. Autonomous Passages (% of paragraphs not starting with context-referencing demonstratives/connectors)
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.utils.lang_patterns import resolve_language, get_lang_patterns
from src.utils.text_processing import extract_main_content, clean_html_for_analysis


def compute_mtld(tokens: List[str], threshold: float = 0.72) -> float:
    """
    Compute Measure of Textual Lexical Diversity (MTLD).
    Calculates the mean factor length with TTR threshold = 0.72,
    both forward and backward, and averages them.
    """
    if len(tokens) < 10:
        return 0.0

    def _factor_count(token_list: List[str]) -> float:
        factors = 0.0
        types = set()
        count = 0
        for tok in token_list:
            count += 1
            types.add(tok)
            ttr = len(types) / count
            if ttr <= threshold:
                factors += 1.0
                types = set()
                count = 0
        if count > 0:
            final_ttr = len(types) / count
            if final_ttr < 1.0:
                factors += (1.0 - final_ttr) / (1.0 - threshold)
        return factors

    f_forward = _factor_count(tokens)
    f_backward = _factor_count(list(reversed(tokens)))

    mtld_f = len(tokens) / f_forward if f_forward > 0 else float(len(tokens))
    mtld_b = len(tokens) / f_backward if f_backward > 0 else float(len(tokens))
    return (mtld_f + mtld_b) / 2.0


class PassageQualityDetector(BaseDetector):
    """Detector for Passage Quality and Standalone Citability."""

    dimension_name = "passage_quality"
    weight = 0.12  # 12% of total score

    def __init__(self, config_override: dict = None):
        try:
            from config.settings import get_settings
            weights = config_override or get_settings().scoring_weights
            pq_config = weights.get("dimensions", {}).get(self.dimension_name, {})
            self.weight = pq_config.get("weight", self.weight)
        except Exception:
            pass

    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown: List[ScoreBreakdown] = []
        errors: List[str] = []
        recommendations: List[str] = []

        lang = resolve_language(page_data)
        patterns = get_lang_patterns(lang)

        # 1. Extract scoped main content
        scoped_html, scoped_text = extract_main_content(page_data.html_rendered or page_data.html_raw)
        cleaned_html = clean_html_for_analysis(scoped_html) if scoped_html else ""
        soup = BeautifulSoup(cleaned_html, 'lxml') if cleaned_html else None

        # Extract substantive paragraphs (p tags or blocks)
        raw_paragraphs = []
        if soup:
            for p in soup.find_all(['p', 'li', 'td', 'blockquote']):
                text_p = p.get_text(separator=' ', strip=True)
                if text_p:
                    raw_paragraphs.append(text_p)
        if not raw_paragraphs:
            raw_text = scoped_text or page_data.text_content or ""
            raw_paragraphs = [p.strip() for p in re.split(r'\n+', raw_text) if p.strip()]

        # Filter substantive paragraphs (>= 25 words preferred, fallback >= 15 words)
        substantive_paragraphs = [p for p in raw_paragraphs if len(p.split()) >= 25]
        eval_paragraphs = substantive_paragraphs if substantive_paragraphs else [p for p in raw_paragraphs if len(p.split()) >= 15]

        # ---------------------------------------------------------
        # Submetric 1: Lexical Richness with MTLD (25%)
        # ---------------------------------------------------------
        full_text = scoped_text or page_data.text_content or ""
        tokens = [w.lower() for w in re.findall(r'\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+\b', full_text)]
        mtld = compute_mtld(tokens, threshold=0.72)

        if mtld >= 100.0:
            mtld_score = 100.0
            mtld_status = "High"
        elif mtld >= 85.0:
            mtld_score = 85.0
            mtld_status = "Good"
        elif mtld >= 70.0:
            mtld_score = 70.0
            mtld_status = "Moderate"
        elif mtld >= 55.0:
            mtld_score = 50.0
            mtld_status = "Fair"
        else:
            mtld_score = 30.0
            mtld_status = "Low"

        mtld_recs = []
        if mtld_score < 70.0:
            mtld_recs.append("Increase vocabulary diversity and avoid repeating the exact same phrasing across sections.")

        breakdown.append(ScoreBreakdown(
            name="Lexical Richness (MTLD)",
            raw_score=mtld_score,
            weight=0.25,
            weighted_score=mtld_score * 0.25,
            explanation=f"{'✅' if mtld_score >= 70 else '⚠️' if mtld_score >= 50 else '❌'} {mtld_status} Lexical Diversity (MTLD: {mtld:.1f}). Measures vocabulary richness without token length bias.",
            recommendations=mtld_recs
        ))

        # ---------------------------------------------------------
        # Submetric 2: Complete Sentences in Paragraphs (25%)
        # ---------------------------------------------------------
        total_eval = len(eval_paragraphs)
        if total_eval > 0:
            terminal_punct_count = sum(
                1 for p in eval_paragraphs if bool(re.search(r'[.!?]["\')\]]?\s*$', p))
            )
            complete_ratio = (terminal_punct_count / total_eval) * 100.0
        else:
            terminal_punct_count = 0
            complete_ratio = 50.0

        complete_score = min(100.0, complete_ratio)
        complete_recs = []
        if complete_score < 80.0:
            complete_recs.append("Ensure all substantive paragraphs end with a complete sentence and period (.) for proper AI extraction.")

        breakdown.append(ScoreBreakdown(
            name="Complete Sentences",
            raw_score=complete_score,
            weight=0.25,
            weighted_score=complete_score * 0.25,
            explanation=f"{'✅' if complete_score >= 80 else '⚠️' if complete_score >= 50 else '❌'} {complete_score:.0f}% ({terminal_punct_count}/{total_eval}) of substantive paragraphs end with complete terminal punctuation.",
            recommendations=complete_recs
        ))

        # ---------------------------------------------------------
        # Submetric 3: Content Depth (>= 25 words) (25%)
        # ---------------------------------------------------------
        depth_count = len(substantive_paragraphs)
        if depth_count >= 8:
            depth_score = 100.0
            depth_status = "Comprehensive"
        elif depth_count >= 5:
            depth_score = 80.0
            depth_status = "Substantial"
        elif depth_count >= 3:
            depth_score = 60.0
            depth_status = "Moderate"
        elif depth_count >= 1:
            depth_score = 40.0
            depth_status = "Light"
        else:
            depth_score = 0.0
            depth_status = "Insufficient"

        depth_recs = []
        if depth_score < 70.0:
            depth_recs.append("Develop at least 5-8 in-depth paragraphs (>= 25 words each) providing detailed explanations.")

        breakdown.append(ScoreBreakdown(
            name="Content Depth",
            raw_score=depth_score,
            weight=0.25,
            weighted_score=depth_score * 0.25,
            explanation=f"{'✅' if depth_score >= 70 else '⚠️' if depth_score > 0 else '❌'} {depth_status} depth: Found {depth_count} substantive paragraph(s) (≥ 25 words).",
            recommendations=depth_recs
        ))

        # ---------------------------------------------------------
        # Submetric 4: Autonomous Passages (25%)
        # ---------------------------------------------------------
        referential_starters = patterns.get("referential_starters", [])
        autonomous_count = 0
        non_autonomous_samples = []

        for p in eval_paragraphs:
            is_referential = any(bool(re.search(pat, p, re.IGNORECASE)) for pat in referential_starters)
            if is_referential:
                non_autonomous_samples.append(p[:60] + ("..." if len(p) > 60 else ""))
            else:
                autonomous_count += 1

        if total_eval > 0:
            auto_ratio = (autonomous_count / total_eval) * 100.0
        else:
            auto_ratio = 100.0

        auto_score = min(100.0, auto_ratio)
        auto_recs = []
        if auto_score < 80.0:
            auto_recs.append("Make paragraph openings self-contained: avoid starting with context references like 'as mentioned above', 'como hemos visto', or demonstratives ('this', 'esto').")

        breakdown.append(ScoreBreakdown(
            name="Autonomous Passages",
            raw_score=auto_score,
            weight=0.25,
            weighted_score=auto_score * 0.25,
            explanation=f"{'✅' if auto_score >= 80 else '⚠️' if auto_score >= 50 else '❌'} {auto_score:.0f}% ({autonomous_count}/{total_eval}) of paragraphs are standalone without anaphoric dependencies.",
            recommendations=auto_recs
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
            errors=errors,
            debug_info={
                "mtld": round(mtld, 2),
                "substantive_paragraphs_count": depth_count,
                "autonomous_paragraphs_count": autonomous_count,
                "non_autonomous_samples": non_autonomous_samples[:5],
            }
        )
