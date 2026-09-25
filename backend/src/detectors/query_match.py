"""
GEO-AUDITOR AI - Query Match Detector

Phase 4b: Evaluates semantic relevance and BM25 alignment between an optional target query
and the page's main content:
1. Full content similarity (Coverage and frequency across the whole article)
2. Best passage similarity (BM25 alignment of the top matching paragraph)
3. Opening paragraph presence (Whether key query terms appear in the lead paragraph)
"""

import math
import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.utils.lang_patterns import resolve_language, get_lang_patterns
from src.utils.text_processing import extract_main_content, clean_html_for_analysis


class BM25:
    """Lightweight, in-memory BM25 implementation for paragraph ranking."""

    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / self.corpus_size if self.corpus_size > 0 else 1.0
        self.doc_freqs: List[Dict[str, int]] = []
        self.nd: Dict[str, int] = {}

        for doc in corpus:
            freqs: Dict[str, int] = {}
            for w in doc:
                freqs[w] = freqs.get(w, 0) + 1
            self.doc_freqs.append(freqs)
            for w in freqs:
                self.nd[w] = self.nd.get(w, 0) + 1

        self.idf: Dict[str, float] = {}
        for w, freq in self.nd.items():
            self.idf[w] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score(self, query_terms: List[str], doc_idx: int) -> float:
        score = 0.0
        if doc_idx >= len(self.corpus):
            return 0.0
        doc = self.corpus[doc_idx]
        doc_len = len(doc)
        freqs = self.doc_freqs[doc_idx]
        denom_part = self.k1 * (1.0 - self.b + self.b * (doc_len / self.avgdl))

        for term in query_terms:
            if term not in freqs:
                continue
            f = freqs[term]
            idf = self.idf.get(term, 0.0)
            score += idf * (f * (self.k1 + 1.0)) / (f + denom_part)

        return score


class QueryMatchDetector(BaseDetector):
    """Detector for Query Relevance and Best-Passage BM25 Alignment."""

    dimension_name = "query_match"
    weight = 0.10  # 10% of total score

    def __init__(self, target_query: str, config_override: dict = None):
        self.target_query = target_query.strip()
        try:
            from config.settings import get_settings
            weights = config_override or get_settings().scoring_weights
            qm_config = weights.get("dimensions", {}).get(self.dimension_name, {})
            self.weight = qm_config.get("weight", self.weight)
        except Exception:
            pass

    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown: List[ScoreBreakdown] = []
        errors: List[str] = []
        recommendations: List[str] = []

        lang = resolve_language(page_data)
        patterns = get_lang_patterns(lang)
        stop_words = patterns.get("stop_words", set())

        # Tokenize query
        raw_query_words = re.findall(r'\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\$\-]+\b', self.target_query.lower())
        query_terms = [w for w in raw_query_words if w not in stop_words and len(w) > 1]
        if not query_terms:
            query_terms = raw_query_words if raw_query_words else [self.target_query.lower()]

        # Extract main content
        scoped_html, scoped_text = extract_main_content(page_data.html_rendered or page_data.html_raw)
        full_text = scoped_text or page_data.text_content or ""
        content_tokens = [w.lower() for w in re.findall(r'\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\$\-]+\b', full_text)]

        # Extract paragraphs for passage ranking
        cleaned_html = clean_html_for_analysis(scoped_html) if scoped_html else ""
        soup = BeautifulSoup(cleaned_html, 'lxml') if cleaned_html else None

        paragraphs: List[str] = []
        if soup:
            for p in soup.find_all(['p', 'li', 'td', 'blockquote']):
                text_p = p.get_text(separator=' ', strip=True)
                if text_p and len(text_p.split()) >= 10:
                    paragraphs.append(text_p)
        if not paragraphs:
            paragraphs = [p.strip() for p in re.split(r'\n+', full_text) if len(p.strip().split()) >= 10]

        # ---------------------------------------------------------
        # Submetric 1: Full Content Match (40%)
        # ---------------------------------------------------------
        matched_terms = [t for t in query_terms if t in content_tokens]
        coverage_ratio = len(matched_terms) / len(query_terms) if query_terms else 0.0
        total_occurrences = sum(content_tokens.count(t) for t in query_terms)

        if coverage_ratio == 1.0:
            full_score = 100.0 if total_occurrences >= len(query_terms) * 2 else 90.0
            full_status = "Complete"
        elif coverage_ratio >= 0.66:
            full_score = 75.0
            full_status = "High"
        elif coverage_ratio >= 0.33:
            full_score = 50.0
            full_status = "Partial"
        elif coverage_ratio > 0.0:
            full_score = 30.0
            full_status = "Low"
        else:
            full_score = 0.0
            full_status = "None"

        full_recs = []
        if full_score < 75.0:
            missing_terms = [t for t in query_terms if t not in matched_terms]
            if missing_terms:
                full_recs.append(f"Incorporate missing query concepts: {', '.join(missing_terms[:3])}.")

        breakdown.append(ScoreBreakdown(
            name="Full Content Match",
            raw_score=full_score,
            weight=0.40,
            weighted_score=full_score * 0.40,
            explanation=f"{'✅' if full_score >= 70 else '⚠️' if full_score > 0 else '❌'} {full_status} relevance: {len(matched_terms)}/{len(query_terms)} query terms found ({total_occurrences} total mentions across article).",
            recommendations=full_recs
        ))

        # ---------------------------------------------------------
        # Submetric 2: Best Passage Match (40%)
        # ---------------------------------------------------------
        best_passage_text = ""
        best_passage_score = 0.0
        best_bm25_score = 0.0

        if paragraphs:
            tokenized_paragraphs = [
                [w.lower() for w in re.findall(r'\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\$\-]+\b', p)]
                for p in paragraphs
            ]
            bm25 = BM25(tokenized_paragraphs)
            scores = [bm25.score(query_terms, idx) for idx in range(len(paragraphs))]
            best_idx = max(range(len(scores)), key=lambda idx: scores[idx]) if scores else 0
            best_bm25_score = scores[best_idx] if scores else 0.0
            best_passage_text = paragraphs[best_idx] if paragraphs else ""

            # Measure term coverage in best passage
            best_tokens = tokenized_paragraphs[best_idx] if tokenized_paragraphs else []
            passage_matches = [t for t in query_terms if t in best_tokens]
            passage_coverage = len(passage_matches) / len(query_terms) if query_terms else 0.0

            if passage_coverage == 1.0:
                best_passage_score = 100.0
            elif passage_coverage >= 0.66:
                best_passage_score = 80.0
            elif passage_coverage >= 0.33:
                best_passage_score = 50.0
            elif passage_coverage > 0.0:
                best_passage_score = 30.0
            else:
                best_passage_score = 0.0
        else:
            best_passage_score = full_score

        snippet = (best_passage_text[:130] + "...") if len(best_passage_text) > 130 else best_passage_text
        passage_recs = []
        if best_passage_score < 75.0:
            passage_recs.append("Create a dedicated, concise passage directly addressing all aspects of the target query.")

        breakdown.append(ScoreBreakdown(
            name="Best Passage Match",
            raw_score=best_passage_score,
            weight=0.40,
            weighted_score=best_passage_score * 0.40,
            explanation=f"{'✅' if best_passage_score >= 70 else '⚠️' if best_passage_score > 0 else '❌'} Best Passage Match ({best_passage_score:.0f}/100): \"{snippet}\"",
            recommendations=passage_recs
        ))

        # ---------------------------------------------------------
        # Submetric 3: Opening Paragraph Presence (20%)
        # ---------------------------------------------------------
        lead_paragraph = paragraphs[0] if paragraphs else full_text[:300]
        lead_tokens = [w.lower() for w in re.findall(r'\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\$\-]+\b', lead_paragraph)]
        lead_matches = [t for t in query_terms if t in lead_tokens]
        lead_coverage = len(lead_matches) / len(query_terms) if query_terms else 0.0

        if lead_coverage == 1.0:
            lead_score = 100.0
        elif lead_coverage >= 0.50:
            lead_score = 75.0
        elif lead_coverage > 0.0:
            lead_score = 45.0
        else:
            lead_score = 0.0

        lead_recs = []
        if lead_score < 70.0:
            lead_recs.append(f"Include target query terms ({', '.join(query_terms[:3])}) in the opening paragraph for instant LLM query matching.")

        breakdown.append(ScoreBreakdown(
            name="Opening Paragraph Match",
            raw_score=lead_score,
            weight=0.20,
            weighted_score=lead_score * 0.20,
            explanation=f"{'✅' if lead_score >= 70 else '⚠️' if lead_score > 0 else '❌'} Opening Paragraph: {len(lead_matches)}/{len(query_terms)} core query terms found in opening section.",
            recommendations=lead_recs
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
                "target_query": self.target_query,
                "query_terms": query_terms,
                "best_bm25_score": round(best_bm25_score, 3),
                "best_passage_snippet": snippet,
            }
        )
