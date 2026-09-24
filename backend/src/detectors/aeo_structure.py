"""
GEO-AUDITOR AI - AEO Structure Detector

Layer 3: Estructura de Respuesta AEO (18% of total score)

Evaluates content structure for Answer Engine Optimization.
This is the highest-weighted dimension, critical for LLM citability.

Sub-metrics evaluated (from SRS Section 2.1):
- Regla de 60: Direct answer in first 60 words (30% of layer)
- H2 Interrogativos: Headers formatted as questions (25% of layer)
- Estructura H2/H3: Proper heading ratio (25% of layer)
- Muros de Texto: Penalty for long text blocks without subheaders (20% of layer)

Implementation uses regex patterns as recommended in best practices:
"Usar Regex patterns customizados: Detectar frases de experiencia"
"""

import re
from typing import Optional
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from src.utils.lang_patterns import get_lang_patterns, resolve_language, is_interrogative_h2
from config.settings import get_settings


class AEOStructureDetector(BaseDetector):
    """
    AEO Structure Detector.
    
    Evaluates Layer 3 criteria from SRS Section 3:
    "3. Estructura de Respuesta (AEO) | 18% | H2 interrogativos, Power Lead, Regla de 60"
    
    This detector analyzes:
    1. Regla de 60: Answer appears in first 60 words
    2. H2 Interrogativos: Headers are question-formatted
    3. Estructura H2/H3: 1 H2 per 300-500 words (SRS)
    4. Muros de Texto: >500 words without subheaders penalized
    
    Example:
        >>> detector = AEOStructureDetector()
        >>> result = await detector.analyze(page_data)
        >>> print(f"AEO Score: {result.score}")
        AEO Score: 72.5
        
    Attributes:
        dimension_name: "aeo_structure"
        weight: 0.18 (18% of total score - highest weighted)
    """
    
    dimension_name: str = "aeo_structure"
    weight: float = 0.20
    
    # Sub-dimension weights (Redistributed across remaining metrics: Rule of 60, Heading Structure, Text Walls, Logical Connectors)
    RULE_60_WEIGHT = 0.3333           # Was 0.20
    HEADING_STRUCTURE_WEIGHT = 0.2500 # Was 0.15
    TEXT_WALLS_WEIGHT = 0.1667        # Was 0.10
    LOGICAL_CONNECTORS_WEIGHT = 0.2500 # Was 0.15
    
    # Thresholds
    OPTIMAL_WORDS_PER_H2 = 200
    MAX_WORDS_WITHOUT_HEADER = 500
    FIRST_N_WORDS_FOR_ANSWER = 60
    MIN_WORDS_PER_H2 = 80
    MAX_WORDS_PER_H2 = 350
    MIN_LOGICAL_CONNECTORS = 3      # Min connectors required
    
    # Question patterns (English + Spanish legacy support)
    QUESTION_PATTERNS = [
        r'^.+\?$',
        r'^(what|how|when|where|why|which|who|whose)\s',
        r'^(is|are|can|does|do|will|should)\s',
        r'^¿.+\?$',
        r'^(qué|cómo|cuándo|dónde|por qué|cuál|quién|cuánto)\s',
    ]
    
    # Fluff and narrative starter patterns
    NARRATIVE_PATTERNS = [
        r'^in this (article|post|guide)',
        r"^we('re| are) going to",
        r'^we will (explore|discuss|cover|show)',
        r'^let me show you',
        r'^today we will',
        r'^welcome to',
        r'^read on to',
        r'^keep reading',
        r'^en este (artículo|articulo|post)',
        r'^vamos a ver',
        r'^once upon a time',
        r'^imagine a world',
        r'^imagine if',
        r'^story about',
        r'^it all started',
        r'^long ago',
        r"^in today's",
        r'^we are used to',
        r'^looking back',
        r'^have you ever',
        r'^since the beginning',
        r'^nowadays',
        r'^hoy en día',
        r'^hoy en dia',
        r'^en la actualidad',
        r'^a lo largo de la historia',
        r'^alguna vez te has preguntado',
    ]

    # Logical Connectors (Default English, loaded centrally)
    LOGICAL_CONNECTORS = get_lang_patterns("en")["logical_connectors"]

    # Generic Headers Blacklist (Default English, loaded centrally)
    GENERIC_HEADERS_BLACKLIST = get_lang_patterns("en")["generic_headers"]
    
    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()
        
        # Load weights from config if available
        try:
            weights = self.settings.scoring_weights
            aeo_config = weights.get("dimensions", {}).get("aeo_structure", {})
            self.weight = aeo_config.get("weight", self.weight)
        except Exception:
            pass
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """Analyze AEO structure of the content."""
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        
        # Initialize safe defaults for metrics
        h1_headers = []
        h2_headers = []
        h3_headers = []
        h2_texts = []
        h1_text = ""
        scoped_text = ""
        connector_count = 0
        
        try:
            # Use HTML from PageData (rendered if available for JS content, else raw)
            html = page_data.html_rendered
            
            # Prepare scoped HTML for analysis
            from src.utils.text_processing import clean_html_for_analysis
            scoped_html = clean_html_for_analysis(html)
            
            # EXTRACT HEADERS (Simplified Logic)
            from src.utils.text_processing import extract_headers
            all_headers = extract_headers(html) # Use full HTML for headers to avoid losing them in scoping
            
            # Filter for specific levels
            h1_headers = [h for h in all_headers if h['tag'] == 'h1']
            h2_headers = [h for h in all_headers if h['tag'] == 'h2']
            h3_headers = [h for h in all_headers if h['tag'] == 'h3']
            
            h2_texts = [h['text'] for h in h2_headers]
            h1_text = h1_headers[0]['text'] if h1_headers else ""
            
            # EXTRACT SCOPED TEXT (Centralized)
            from src.utils.text_processing import extract_clean_text
            scoped_text = extract_clean_text(scoped_html)
            
            # Resolve language patterns
            lang = resolve_language(page_data)
            patterns = get_lang_patterns(lang)
            
            # 1. Regla de 60 Check (Uses scoped text)
            try:
                rule_60_result = self._analyze_rule_of_60(scoped_text, scoped_html, h1_text)
                breakdown.append(rule_60_result)
            except Exception as e:
                errors.append(f"Rule of 60 check failed: {str(e)}")
                breakdown.append(self._create_error_breakdown("Rule of 60", self.RULE_60_WEIGHT))
                
            # 2. Heading Structure Check
            try:
                # Use scoped text word count for more accurate ratio
                structure_result = self._analyze_heading_structure(len(h2_headers), len(h3_headers), scoped_text)
                breakdown.append(structure_result)
            except Exception as e:
                errors.append(f"Heading structure check failed: {str(e)}")
                breakdown.append(self._create_error_breakdown("Heading Structure", self.HEADING_STRUCTURE_WEIGHT))
            
            # 3. Text Walls Check (Uses SCOPED html)
            try:
                walls_result = self._analyze_text_walls(scoped_html)
                breakdown.append(walls_result)
            except Exception as e:
                errors.append(f"Text walls check failed: {str(e)}")
                breakdown.append(self._create_error_breakdown("Text Walls", self.TEXT_WALLS_WEIGHT))
    
            # 4. Logical Connectors Check
            try:
                connectors_result, count_val = self._analyze_logical_connectors(
                    scoped_text,
                    connectors=patterns["logical_connectors"]
                )
                connector_count = count_val
                breakdown.append(connectors_result)
            except Exception as e:
                errors.append(f"Logical connectors check failed: {str(e)}")
                breakdown.append(self._create_error_breakdown("Logical Connectors", self.LOGICAL_CONNECTORS_WEIGHT))
                
        except Exception as e:
            # Global catch-all to prevent module crash
            import traceback
            traceback.print_exc() # Log to stderr
            errors.append(f"Critical error in AEO module: {str(e)}")
            
            # Try to salvage headers if possible
            try:
                if not h2_texts and 'all_headers' in locals():
                     h2_texts = [h['text'] for h in all_headers if h['tag'] == 'h2']
            except:
                pass

        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        # STRUCTURE METRICS for Debugging
        structure_metrics = {
            "h1_count": len(h1_headers),
            "h2_count": len(h2_headers),
            "h3_count": len(h3_headers),
            "h1_text": h1_text,
            "total_words": len(scoped_text.split()) if scoped_text else 0,
            "connector_count": connector_count
        }
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
            debug_info={
                "detected_headers": h2_texts[:15], # Limit for UI
                "structure_metrics": structure_metrics,
                "header_count": len(h2_texts)
            }
        )
    
    def _analyze_rule_of_60(self, text: str, html: str = "", h1_text: str = "") -> ScoreBreakdown:
        """
        Rule of 60: Evaluate first paragraph quality for LLM citability.
        
        Scoring logic:
        - 100/100 if the first paragraph does NOT start with narrative/filler hook.
        - 40/100 if it starts with narrative filler.
        """
        first_p_text = ""
        if html:
            from src.utils.text_processing import extract_substantive_paragraphs
            substantive_paragraphs = extract_substantive_paragraphs(html, min_words=10)
            first_p_text = substantive_paragraphs[0] if substantive_paragraphs else ""
        if not first_p_text and text:
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.split()) >= 5]
            if not paragraphs:
                paragraphs = [p.strip() for p in text.split("\n") if len(p.split()) >= 5]
            if not paragraphs and text.strip():
                paragraphs = [text.strip()]
            first_p_text = paragraphs[0] if paragraphs else ""
        
        if not first_p_text:
            return ScoreBreakdown(
                name="Rule of 60 (Answer First)",
                raw_score=0.0,
                weight=self.RULE_60_WEIGHT,
                weighted_score=0.0,
                explanation="❌ No substantive first paragraph (≥10 words) detected.",
                recommendations=["Add an introductory paragraph answering user intent directly."],
            )
        
        first_p_lower = first_p_text.lower().strip()
        recommendations = []
        
        # Check if first paragraph starts with narrative/filler hook
        is_narrative = any(re.search(pat, first_p_lower, re.IGNORECASE) for pat in self.NARRATIVE_PATTERNS)
        
        if is_narrative:
            raw_score = 40.0
            explanation = "⚠️ Narrative Warning: Intro starts with filler/narrative hook instead of direct substance."
            recommendations.append("Remove narrative filler at the opening. Start directly with the core answer or factual substance.")
        else:
            raw_score = 100.0
            explanation = "✅ Direct Answer: First paragraph gets straight to the point without narrative filler."

        return ScoreBreakdown(
            name="Rule of 60 (Answer First)",
            raw_score=raw_score,
            weight=self.RULE_60_WEIGHT,
            weighted_score=raw_score * self.RULE_60_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )

    
    def _analyze_interrogative_h2s(self, h2_texts: list[str]) -> ScoreBreakdown:
        """
        Analyze if H2 headers are formatted as questions.
        Uses cached headers extracted via BeautifulSoup.
        """
        if not h2_texts:
            return ScoreBreakdown(
                name="Interrogative H2s",
                raw_score=30.0,
                weight=self.INTERROGATIVE_H2_WEIGHT,
                weighted_score=30.0 * self.INTERROGATIVE_H2_WEIGHT,
                explanation="No H2 headers detected.",
                recommendations=[
                    "Add H2 headers to structure the content.",
                ],
            )
        
        # Count interrogative H2s (ends with '?', starts with '¿', or interrogative word in EN or ES)
        interrogative_count = sum(1 for h2_text in h2_texts if is_interrogative_h2(h2_text))
        
        # Calculate score
        total_h2s = len(h2_texts)
        interrogative_ratio = interrogative_count / total_h2s if total_h2s > 0 else 0
        
        # SCORE (Gold Standard)
        if interrogative_ratio >= 0.3:
            raw_score = 100.0
        elif interrogative_ratio >= 0.1:
            raw_score = 85.0
        elif total_h2s > 0:
            raw_score = 70.0
        else:
            raw_score = 30.0
        
        if interrogative_ratio < 0.1 and total_h2s > 0:
            recommendations = [f"Rephrase H2s as questions (e.g. 'What is...', '¿Cómo...?'). Found {interrogative_count}/{total_h2s}."]
        else:
            recommendations = []
        
        explanation = (
            f"Detected {total_h2s} H2 headers, "
            f"{interrogative_count} ending in '?'."
        )
        
        return ScoreBreakdown(
            name="Interrogative H2s",
            raw_score=raw_score,
            weight=self.INTERROGATIVE_H2_WEIGHT,
            weighted_score=raw_score * self.INTERROGATIVE_H2_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_heading_structure(self, h2_count: int, h3_count: int, text: str) -> ScoreBreakdown:
        """
        Analyze heading structure ratio.
        Per SRS Section 2.1.6: Ratio optimal: 1 H2 each 300-500 words.
        """
        # Defensive check
        if not text:
             return ScoreBreakdown(
                name="Heading Structure",
                raw_score=0.0,
                weight=self.HEADING_STRUCTURE_WEIGHT,
                weighted_score=0.0,
                explanation="No text content to analyze.",
                recommendations=["Add text content."],
            )

        word_count = len(text.split())
        total_headings = h2_count + h3_count
        
        if word_count == 0:
            return ScoreBreakdown(
                name="Heading Structure",
                raw_score=0.0,
                weight=self.HEADING_STRUCTURE_WEIGHT,
                weighted_score=0.0,
                explanation="No text content to analyze.",
                recommendations=["Add text content."],
            )
        
        # Calculate ideal number of H2s
        ideal_h2_count = word_count / self.OPTIMAL_WORDS_PER_H2
        
        recommendations = []
        
        if h2_count == 0:
            raw_score = 20.0
            explanation = "No H2 headers detected. Content lacks structure."
            recommendations.append(
                f"Add approximately {max(1, int(ideal_h2_count))} H2 headers "
                f"for {word_count} words."
            )
        else:
            words_per_h2 = word_count / h2_count
            
            # GOLD STANDARD: Expanded ideal range 80-350 for news tolerance
            if self.MIN_WORDS_PER_H2 <= words_per_h2 <= self.MAX_WORDS_PER_H2:
                raw_score = 100.0
                explanation = f"Excellent structure: {h2_count} H2s for {word_count} words ({words_per_h2:.0f} words/H2)."
            elif 60 <= words_per_h2 <= 500:
                raw_score = 85.0
                explanation = f"Good structure: {h2_count} H2s ({words_per_h2:.0f} words/H2)."
            elif 40 <= words_per_h2 <= 700:
                raw_score = 70.0
                explanation = f"Acceptable structure: {h2_count} H2s ({words_per_h2:.0f} words/H2)."
                if words_per_h2 < 80:
                    recommendations.append("Consider merging some H2 sections (too granular).")
                else:
                    recommendations.append("Consider adding more H2s for better scannability.")
            else:
                raw_score = 50.0
                explanation = f"Suboptimal structure: {h2_count} H2s ({words_per_h2:.0f} words/H2)."
                if words_per_h2 < 40:
                    recommendations.append("Reduce number of H2s or expand content.")
                else:
                    recommendations.append(
                        f"Add more H2s. Goal: 1 H2 every 80-350 words "
                        f"(currently {words_per_h2:.0f})."
                    )
        
        # Bonus for having H3s (sub-structure)
        if h3_count > 0 and raw_score < 100:
            raw_score = min(100, raw_score + 10)
            explanation += f" Bonus: {h3_count} H3s detected."
        
        return ScoreBreakdown(
            name="Heading Structure",
            raw_score=raw_score,
            weight=self.HEADING_STRUCTURE_WEIGHT,
            weighted_score=raw_score * self.HEADING_STRUCTURE_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_text_walls(self, html: str) -> ScoreBreakdown:
        """Analyze for 'text walls' (>500 words without subheaders)."""
        # Split by headers
        header_pattern = r'<h[1-6][^>]*>'
        sections = re.split(header_pattern, html, flags=re.IGNORECASE)
        
        text_walls = []
        for i, section in enumerate(sections):
            # Extract text from section
            text = re.sub(r'<[^>]+>', ' ', section)
            text = re.sub(r'\s+', ' ', text).strip()
            word_count = len(text.split())
            
            if word_count > self.MAX_WORDS_WITHOUT_HEADER:
                text_walls.append(word_count)
        
        recommendations = []
        
        if not text_walls:
            raw_score = 100.0
            explanation = "No text walls detected. Good structure."
        elif len(text_walls) == 1:
            raw_score = 50.0
            explanation = f"Detected 1 text wall (>500 words). Breakdown required."
        else:
            raw_score = 0.0
            explanation = f"Detected {len(text_walls)} text walls. Significant readability issues."
            
        if text_walls:
            recommendations.append(
                f"Break up long blocks with H2/H3 headers. "
                f"Goal: max 500 words per section."
            )
        
        return ScoreBreakdown(
            name="Text Walls",
            raw_score=raw_score,
            weight=self.TEXT_WALLS_WEIGHT,
            weighted_score=raw_score * self.TEXT_WALLS_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )

    def _analyze_sentence_length(self, text: str) -> tuple[ScoreBreakdown, float]:
        """
        Analyze average sentence length.
        Goal: < 25 words per sentence for AI readability.
        Returns tuple: (ScoreBreakdown, avg_length)
        """
        if not text:
             return (ScoreBreakdown(
                name="Sentence Length",
                raw_score=0.0,
                weight=self.SENTENCE_LENGTH_WEIGHT,
                weighted_score=0.0,
                explanation="No text content to analyze.",
                recommendations=[],
            ), 0.0)

        # Simple sentence split by punctuation
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10] # Ignore short fragments
        
        if not sentences:
             return (ScoreBreakdown(
                name="Sentence Length",
                raw_score=0.0,
                weight=self.SENTENCE_LENGTH_WEIGHT,
                weighted_score=0.0,
                explanation="No sentences detected.",
                recommendations=[],
            ), 0.0)

        total_words = sum(len(s.split()) for s in sentences)
        
        # Defensive division
        if len(sentences) > 0:
            avg_length = total_words / len(sentences)
        else:
            avg_length = 0.0
        
        recommendations = []
        if avg_length <= 20:
            raw_score = 100.0
            explanation = f"Excellent complexity: Average {avg_length:.1f} words/sentence."
        elif avg_length <= 25:
            raw_score = 80.0
            explanation = f"Good complexity: Average {avg_length:.1f} words/sentence."
        else:
            raw_score = 40.0
            explanation = f"Sentences too long: Average {avg_length:.1f} words/sentence."
            recommendations.append(
                f"Simplify sentences. Average length is {avg_length:.1f} words (aim for <20) to help LLMs process facts."
            )
            
        return (ScoreBreakdown(
            name="Sentence Length",
            raw_score=raw_score,
            weight=self.SENTENCE_LENGTH_WEIGHT,
            weighted_score=raw_score * self.SENTENCE_LENGTH_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        ), avg_length)

    def _analyze_logical_connectors(self, text: str, connectors: list[str] = None) -> tuple[ScoreBreakdown, int]:
        """
        Analyze presence of logical connectors (Cohesion).
        Returns tuple: (ScoreBreakdown, count)
        """
        if not text:
             return (ScoreBreakdown(
                name="Logical Connectors",
                raw_score=0.0,
                weight=self.LOGICAL_CONNECTORS_WEIGHT,
                weighted_score=0.0,
                explanation="No text content to analyze.",
                recommendations=[],
            ), 0)

        active_connectors = connectors if connectors is not None else self.LOGICAL_CONNECTORS
        text_lower = text.lower()
        found_connectors = []
        
        for connector in active_connectors:
            # Check distinct word boundaries
            if re.search(r'\b' + re.escape(connector) + r'\b', text_lower):
                found_connectors.append(connector)
                
        count = len(found_connectors)
        recommendations = []
        
        if count >= self.MIN_LOGICAL_CONNECTORS:
            raw_score = 100.0
            explanation = f"Good cohesion: Found {count} unique logical connectors."
        elif count > 0:
            raw_score = 60.0
            explanation = f"Weak cohesion: Found only {count} unique logical connectors."
            recommendations.append(
                "Use more logical connectors (Therefore, However, Because) to link ideas."
            )
        else:
            raw_score = 20.0
            explanation = "Poor cohesion: No logical connectors found."
            recommendations.append(
                "Use logical connectors (Therefore, However, Because) to link ideas and help AI follow your reasoning."
            )
            
        return (ScoreBreakdown(
            name="Logical Connectors",
            raw_score=raw_score,
            weight=self.LOGICAL_CONNECTORS_WEIGHT,
            weighted_score=raw_score * self.LOGICAL_CONNECTORS_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        ), count)

    def _analyze_generic_headers(self, h2_texts: list[str], generic_blacklist: list[str] = None) -> ScoreBreakdown:
        """
        Check for generic H2 headers (Banned H2s).
        """
        active_blacklist = generic_blacklist if generic_blacklist is not None else self.GENERIC_HEADERS_BLACKLIST
        bad_headers = []
        for h2 in h2_texts:
            h2_lower = h2.lower().strip()
            # Exact match or very generic phrase
            if h2_lower in active_blacklist:
                bad_headers.append(h2)
                
        recommendations = []
        if not bad_headers:
            raw_score = 100.0
            explanation = "No generic headers detected."
        else:
            raw_score = 0.0 # Strict penalty
            explanation = f"Detected {len(bad_headers)} generic H2 headers."
            for bad in bad_headers[:3]:
                 recommendations.append(
                    f"Avoid generic headers like '{bad}'. Use descriptive entities (e.g., 'Bitcoin Summary' instead of 'Summary')."
                )
        
        return ScoreBreakdown(
            name="Generic Headers",
            raw_score=raw_score,
            weight=self.GENERIC_HEADERS_WEIGHT,
            weighted_score=raw_score * self.GENERIC_HEADERS_WEIGHT,
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
