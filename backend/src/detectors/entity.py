"""
GEO-AUDITOR AI - Entity Detector

Layer 6: Identificación de Entidades (8% of total score)

Evaluates entity identification and Power Lead presence.
Critical for LLMs to understand and cite content correctly.

Sub-metrics evaluated (from SRS Section 2.1):
- Power Lead: Brand/topic in first 150 characters (40% of layer)
- Title Entity Presence: H1 contains core entities (30% of layer)
- Entity Density: Key entities mentioned throughout (30% of layer)

Per SRS Section 2.1.3:
"Usar NLP para detectar si contiene: sujeto + verbo + objeto relacionado con el título"
"""

import re
from typing import Optional
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from src.utils.lang_patterns import get_lang_patterns, resolve_language
from config.settings import get_settings


class EntityDetector(BaseDetector):
    """
    Entity Identification Detector.
    
    Evaluates Layer 6 criteria from SRS Section 3:
    "6. Identificación de Entidades | 8% | Marca + Tema en primeros 150 chars, NER"
    
    This detector analyzes:
    1. Power Lead: Brand/topic appears in first 150 characters
    2. Title Entity: H1 contains identifiable entities
    3. Entity Density: Key terms distributed throughout content
    
    Example:
        >>> detector = EntityDetector()
        >>> result = await detector.analyze(page_data)
        >>> print(f"Entity Score: {result.score}")
        Entity Score: 85.0
        
    Attributes:
        dimension_name: "entity_identification"
        weight: 0.08 (8% of total score)
    """
    
    dimension_name: str = "entity_identification"
    weight: float = 0.08
    
    # Sub-dimension weights
    POWER_LEAD_WEIGHT = 0.40
    TITLE_ENTITY_WEIGHT = 0.30
    ENTITY_DENSITY_WEIGHT = 0.30
    
    # Thresholds
    POWER_LEAD_CHAR_LIMIT = 150  # Per SRS: First 150 characters
    MIN_ENTITY_DENSITY = 3  # Minimum key entity mentions
    
    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()
        
        # Load weights from config if available
        try:
            weights = self.settings.scoring_weights
            entity_config = weights.get("dimensions", {}).get("entity_identification", {})
            self.weight = entity_config.get("weight", self.weight)
        except Exception:
            pass
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """
        Analyze entity identification in the content.
        
        Evaluates how well the content identifies and emphasizes
        key entities for LLM comprehension.
        
        Args:
            page_data: Scraped page content and metadata
            
        Returns:
            DetectorResult with full breakdown and recommendations
        """
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        
        from src.utils.text_processing import extract_main_content
        scoped_html, scoped_text = extract_main_content(page_data.html_rendered)
        
        # Extract title (H1) from scoped HTML first (which preserves header in article/main)
        title = self._extract_title(scoped_html)
        if not title:
            title = self._extract_title(page_data.html_rendered)
            
        text = scoped_text if scoped_text else page_data.text_content
        html = scoped_html if scoped_html else page_data.html_rendered
        
        # Resolve language patterns
        lang = resolve_language(page_data)
        patterns = get_lang_patterns(lang)
        
        # 1. Power Lead Check
        try:
            power_lead_result = self._analyze_power_lead(text, title, patterns=patterns)
            breakdown.append(power_lead_result)
        except Exception as e:
            errors.append(f"Power Lead check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Power Lead", self.POWER_LEAD_WEIGHT))
        
        # 2. Title Entity Check
        try:
            title_result = self._analyze_title_entities(title, text=text, lang=lang)
            breakdown.append(title_result)
        except Exception as e:
            errors.append(f"Title entity check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Title Entities", self.TITLE_ENTITY_WEIGHT))
        
        # 3. Entity Density Check
        detected_entities = []
        try:
            density_result, detected_entities = self._analyze_entity_density(text, title, patterns=patterns)
            breakdown.append(density_result)
        except Exception as e:
            errors.append(f"Entity density check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Entity Density", self.ENTITY_DENSITY_WEIGHT))
        
        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
            debug_info={
                "title_entities": breakdown[1].explanation if len(breakdown) > 1 else "",
                "detected_entities_found": breakdown[2].explanation if len(breakdown) > 2 else "", 
                "detected_entities": detected_entities[:15] # Limit for UI
            }
        )
    
    def _extract_title(self, html: str) -> str:
        """
        Extract the H1 title from HTML using BeautifulSoup.
        """
        if not html:
            return ""
            
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        
        # Try H1 first
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        # Fall back to <title>
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)
        
        return ""
    
    def _analyze_power_lead(self, text: str, title: str, patterns: dict = None) -> ScoreBreakdown:
        """
        Analyze Power Lead presence.
        """
        first_150_chars = text[:self.POWER_LEAD_CHAR_LIMIT].lower()
        recommendations = []
        
        if not title:
            return ScoreBreakdown(
                name="Power Lead (Entity in Lead)",
                raw_score=50.0,
                weight=self.POWER_LEAD_WEIGHT,
                weighted_score=50.0 * self.POWER_LEAD_WEIGHT,
                explanation="No title detected to validate Power Lead.",
                recommendations=["Add a clear H1 header with the main entity."],
            )
        
        # Extract key words from title (exclude stop words per language)
        stop_words = patterns["stop_words"] if patterns else get_lang_patterns("en")["stop_words"]
        
        title_words = re.findall(r'\b[a-záéíóúüñ0-9]+\b', title.lower())
        key_entities = [w for w in title_words if w not in stop_words and len(w) > 2]
        
        if not key_entities:
            return ScoreBreakdown(
                name="Power Lead (Entity in Lead)",
                raw_score=60.0,
                weight=self.POWER_LEAD_WEIGHT,
                weighted_score=60.0 * self.POWER_LEAD_WEIGHT,
                explanation="No unique key entities identified in the title.",
                recommendations=["Use a title with specific terms (brand, product, concept)."],
            )
        
        # Count how many key entities appear in first 150 chars
        found_entities = [e for e in key_entities if e in first_150_chars]
        found_ratio = len(found_entities) / len(key_entities) if key_entities else 0
        
        # Check for declarative structure in first 150 chars (per language verbs)
        decl_regex = patterns["declarative_verbs_regex"] if patterns else get_lang_patterns("en")["declarative_verbs_regex"]
        has_declarative = bool(re.search(decl_regex, first_150_chars, re.IGNORECASE))
        
        # Score calculation
        if found_ratio >= 0.8 and has_declarative:
            raw_score = 100.0
            explanation = (
                f"Excellent Power Lead: {len(found_entities)}/{len(key_entities)} "
                f"title entities found in first 150 chars with declarative structure."
            )
        elif found_ratio >= 0.5:
            raw_score = 80.0
            explanation = (
                f"Good Power Lead: {len(found_entities)}/{len(key_entities)} "
                f"entities found in first 150 chars."
            )
            if not has_declarative:
                recommendations.append("Add a declarative verb (is, offers, provides) in the opening sentence.")
        elif found_ratio > 0:
            raw_score = 60.0
            explanation = (
                f"Partial Power Lead: Only {len(found_entities)}/{len(key_entities)} "
                f"entities found in first 150 chars."
            )
            recommendations.append(
                f"Mention key entities ({', '.join(key_entities[:3])}) "
                f"in the very first lines."
            )
        else:
            raw_score = 30.0
            explanation = (
                "No Power Lead detected: Title entities do not appear "
                "in the first 150 characters."
            )
            recommendations.append(
                "IMPORTANT: Start content by explicitly mentioning "
                f"the entities: {', '.join(key_entities[:3])}."
            )
        
        return ScoreBreakdown(
            name="Power Lead (Entity in Lead)",
            raw_score=raw_score,
            weight=self.POWER_LEAD_WEIGHT,
            weighted_score=raw_score * self.POWER_LEAD_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _is_title_case(self, title: str) -> bool:
        """
        Check if title is written in Title Case (majority of words capitalized).
        """
        words = re.findall(r'\b[a-záéíóúüñA-ZÁÉÍÓÚÜÑ0-9\$\-]+\b', title)
        alpha_words = [w for w in words if re.search(r'[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]', w)]
        if len(alpha_words) <= 2:
            return False
        capitalized = [w for w in alpha_words if w[0].isupper()]
        return (len(capitalized) / len(alpha_words)) >= 0.70

    def _extract_title_entities(self, title: str, text: str = "") -> list[str]:
        """
        Extract core entities from title.
        - Consecutive capitalized words form a single entity ('AI Overview', 'Fan Token', 'Google Search Console').
        - Discards entities of 4 characters or fewer unless they are uppercase acronyms ('AI', 'SEO', 'CHZ') or tickers ('$CHZ').
        - If title is in Title Case, verifies words/phrases against body text or ticker/acronym rules.
        """
        if not title:
            return []
            
        common_caps = {
            'The', 'A', 'An', 'How', 'What', 'Why', 'When', 'Where', 'Is', 'Are', 'Best', 'Top',
            'El', 'La', 'Los', 'Las', 'Un', 'Una', 'Unos', 'Unas', 'Cómo', 'Como', 'Qué', 'Que',
            'Por', 'Para', 'Mejor', 'Mejores'
        }
        
        is_tc = self._is_title_case(title)
        tokens = title.split()
        
        def is_ticker_or_symbol(w: str) -> bool:
            return bool('$' in w or '@' in w)

        def is_valid_acronym(w: str) -> bool:
            clean = re.sub(r'[^\w]', '', w)
            return bool(clean and clean.isupper() and 2 <= len(clean) <= 6)
            
        def appears_capitalized_mid_sentence(w: str, body_text: str) -> bool:
            if not body_text:
                return False
            pattern = rf'(?:\b[a-záéíóúüñ]+|\b[a-záéíóúüñ]+[,;:)]|\b[a-záéíóúüñ]+\))\s+{re.escape(w)}\b'
            return bool(re.search(pattern, body_text))

        # 1. Group consecutive capitalized tokens into initial clusters
        raw_clusters = []
        current_cluster = []
        for raw_w in tokens:
            clean_w = raw_w.strip(".,;:!?()[]\"'")
            if not clean_w:
                if current_cluster:
                    raw_clusters.append(current_cluster)
                    current_cluster = []
                continue
            is_cap = clean_w[0].isupper() or clean_w.startswith('$')
            if is_cap:
                current_cluster.append(clean_w)
            else:
                if current_cluster:
                    raw_clusters.append(current_cluster)
                    current_cluster = []
        if current_cluster:
            raw_clusters.append(current_cluster)

        # 2. Extract candidate phrases per cluster
        extracted: list[str] = []
        for cluster in raw_clusters:
            if not is_tc:
                # Not Title Case: entire consecutive capitalized cluster forms an entity
                words = list(cluster)
                while words and words[0] in common_caps:
                    words.pop(0)
                while words and words[-1] in common_caps:
                    words.pop()
                if words:
                    extracted.append(' '.join(words))
            else:
                # Title Case: find maximal sub-phrases verified in body or valid tickers/acronyms
                n = len(cluster)
                i = 0
                while i < n:
                    matched = False
                    for j in range(n, i, -1):
                        subphrase = ' '.join(cluster[i:j])
                        if j == i + 1:
                            w = cluster[i]
                            if is_ticker_or_symbol(w) or is_valid_acronym(w) or any(c.isdigit() for c in w) or appears_capitalized_mid_sentence(w, text):
                                extracted.append(w)
                                i = j
                                matched = True
                                break
                        else:
                            if appears_capitalized_mid_sentence(subphrase, text):
                                extracted.append(subphrase)
                                i = j
                                matched = True
                                break
                    if not matched:
                        i += 1

        # 3. Filter rule:
        # Descarta como entidad los fragmentos de 4 letras o menos salvo acrónimos en mayúsculas (AI, SEO, CHZ) o tickers
        final_entities: list[str] = []
        for ent in extracted:
            words = ent.split()
            while words and words[0] in common_caps:
                words.pop(0)
            while words and words[-1] in common_caps:
                words.pop()
            if not words:
                continue
            cleaned_ent = ' '.join(words)
            
            letter_count = len(re.sub(r'[^a-záéíóúüñA-ZÁÉÍÓÚÜÑ0-9]', '', cleaned_ent))
            if letter_count <= 4:
                if not (is_valid_acronym(cleaned_ent) or is_ticker_or_symbol(cleaned_ent)):
                    continue
            if cleaned_ent not in final_entities:
                final_entities.append(cleaned_ent)

        return final_entities

    def _analyze_title_entities(self, title: str, text: str = "", lang: str = "en") -> ScoreBreakdown:
        """Analyze entity presence in the title (English and Spanish optimized)."""
        recommendations = []
        
        if not title:
            return ScoreBreakdown(
                name="Title Entities",
                raw_score=0.0,
                weight=self.TITLE_ENTITY_WEIGHT,
                weighted_score=0.0,
                explanation="No H1 header detected.",
                recommendations=["Add a clear H1 header."],
            )
        
        # Check for specificity markers
        has_number = bool(re.search(r'\d+', title))
        has_year = bool(re.search(r'20[2-9]\d', title))
        
        # Extract title entities (Title Case aware)
        brand_like = self._extract_title_entities(title, text=text)
        
        # Calculate score (redistributed 40/25/20/15 = 100, removing value terms)
        score_factors = []
        if brand_like:
            score_factors.append((f"entities: {', '.join(brand_like[:3])}", 40))
        if has_number:
            score_factors.append(("specific number", 25))
        if has_year:
            score_factors.append(("current year", 20))
        if len(title.split()) >= 4:
            score_factors.append(("good length", 15))
        
        raw_score = min(100.0, sum(f[1] for f in score_factors))
        
        if raw_score < 100:
            missing = []
            if not brand_like:
                missing.append("recognizable brands/entities")
            if not has_number:
                missing.append("specific numbers")
            
            if missing:
                recommendations.append(
                    f"Enrich title by adding: {', '.join(missing)}."
                )
        
        factors_text = ", ".join(f[0] for f in score_factors)
        explanation = (
            f"Title analyzed: \"{title[:50]}{'...' if len(title) > 50 else ''}\". "
            f"Factors detected: {factors_text if factors_text else 'none'}."
        )
        
        return ScoreBreakdown(
            name="Title Entities",
            raw_score=raw_score,
            weight=self.TITLE_ENTITY_WEIGHT,
            weighted_score=raw_score * self.TITLE_ENTITY_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_entity_density(self, text: str, title: str, patterns: dict = None) -> tuple[ScoreBreakdown, list[str]]:
        """Analyze entity density throughout content."""
        recommendations = []
        found_entities_list = []
        
        if not title or not text:
            return ScoreBreakdown(
                name="Entity Density",
                raw_score=50.0,
                weight=self.ENTITY_DENSITY_WEIGHT,
                weighted_score=50.0 * self.ENTITY_DENSITY_WEIGHT,
                explanation="Insufficient content for density analysis.",
                recommendations=["Ensure content has consistent entity mentions."],
            ), []
        
        # Extract key entities from title using Title Case aware extraction
        key_entities = self._extract_title_entities(title, text=text)
        
        # If no strict entities found, fall back to non-stop words > 4 chars
        if not key_entities:
            stop_words = patterns["stop_words"] if patterns else get_lang_patterns("en")["stop_words"]
            for w in title.split():
                clean_w = w.strip(".,;:!?()[]\"'")
                if len(clean_w) > 4 and clean_w.lower() not in stop_words:
                    if clean_w not in key_entities:
                        key_entities.append(clean_w)
        
        if not key_entities:
            return ScoreBreakdown(
                name="Entity Density",
                raw_score=60.0,
                weight=self.ENTITY_DENSITY_WEIGHT,
                weighted_score=60.0 * self.ENTITY_DENSITY_WEIGHT,
                explanation="No specific key entities identified in title for density check.",
                recommendations=["Use more specific proper nouns (Brand, Product) in title."],
            ), []
        
        # Count mentions
        text_lower = text.lower()
        entity_counts = {}
        for entity in key_entities:
            # Simple word bound check
            count = len(re.findall(rf'\b{re.escape(entity.lower())}\b', text_lower))
            entity_counts[entity] = count
            if count > 0:
                found_entities_list.append(f"{entity} ({count})")
        
        total_mentions = sum(entity_counts.values())
        avg_mentions = total_mentions / len(key_entities) if key_entities else 0
        word_count = len(text.split())
        density_ratio = (total_mentions / word_count * 100) if word_count > 0 else 0
        
        if avg_mentions >= 4: # Strict
            raw_score = 100.0
            explanation = (
                f"Excellent density: Key entities ({', '.join(key_entities[:3])}) "
                f"mentioned frequently."
            )
        elif avg_mentions >= 2:
            raw_score = 80.0
            explanation = (
                f"Good density: Key entities mentioned."
            )
        elif avg_mentions >= 1:
            raw_score = 60.0
            explanation = (
                f"Moderate density: Mentions exist but could be stronger."
            )
            recommendations.append(
                f"Mention more frequently: {', '.join(key_entities[:3])}."
            )
        else:
            raw_score = 30.0
            explanation = (
                "Low entity density. Title Proper Nouns do not appear in content."
            )
            recommendations.append(
                "IMPORTANT: Consistently mention title entities throughout the text: "
                f"{', '.join(key_entities[:3])}."
            )
        
        return ScoreBreakdown(
            name="Entity Density",
            raw_score=raw_score,
            weight=self.ENTITY_DENSITY_WEIGHT,
            weighted_score=raw_score * self.ENTITY_DENSITY_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        ), found_entities_list
    
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
