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
        
        html = page_data.html_rendered
        text = page_data.text_content
        
        # Extract title (H1)
        title = self._extract_title(html)
        
        # 1. Power Lead Check
        try:
            power_lead_result = self._analyze_power_lead(text, title)
            breakdown.append(power_lead_result)
        except Exception as e:
            errors.append(f"Power Lead check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Power Lead", self.POWER_LEAD_WEIGHT))
        
        # 2. Title Entity Check
        try:
            title_result = self._analyze_title_entities(title)
            breakdown.append(title_result)
        except Exception as e:
            errors.append(f"Title entity check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Title Entities", self.TITLE_ENTITY_WEIGHT))
        
        # 3. Entity Density Check
        detected_entities = []
        try:
            density_result, detected_entities = self._analyze_entity_density(text, title)
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
        Extract the H1 title from HTML.
        
        Args:
            html: HTML content
            
        Returns:
            Title text or empty string
        """
        # Try H1 first
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
            return title
        
        # Fall back to <title> tag
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            return title_match.group(1).strip()
        
        return ""
    
    def _analyze_power_lead(self, text: str, title: str) -> ScoreBreakdown:
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
        
        # Extract key words from title (exclude stop words - English)
        stop_words = {
            'the', 'a', 'an', 'of', 'to', 'in', 'with', 'for', 'and', 'or',
            'is', 'are', 'was', 'were', 'how', 'what', 'when', 'where', 'why', 'which',
            'best', 'top', 'guide', 'review', 'vs', 'versus', 'on', 'at', 'by'
        }
        
        title_words = re.findall(r'\b[a-z0-9]+\b', title.lower())
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
        
        # Check for declarative structure in first 150 chars (English verbs)
        has_declarative = bool(re.search(
            r'\b(is|are|means|refers to|defined as|consists of|offers|provides|allows|announces|launches|reveals|demonstrates|shows)\b',
            first_150_chars
        ))
        
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
    
    def _analyze_title_entities(self, title: str) -> ScoreBreakdown:
        """Analyze entity presence in the title (English optimized)."""
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
        
        # Analyze title characteristics
        title_lower = title.lower()
        
        # Check for specificity markers
        has_number = bool(re.search(r'\d+', title))
        has_year = bool(re.search(r'20[2-9]\d', title))
        has_specific_terms = bool(re.search(
            r'\b(guide|tutorial|step by step|complete|ultimate|best|top|review|example|free|easy|how to|checklist)\b',
            title_lower
        ))
        
        # Check for capitalized words (brands/names) excluding common starters
        capitalized_words = re.findall(r'\b[A-Z][a-z0-9]+\b', title)
        common_caps = {'The', 'A', 'An', 'How', 'What', 'Why', 'When', 'Where', 'Is', 'Are', 'Best', 'Top'}
        brand_like = [w for w in capitalized_words if w not in common_caps]
        
        # Calculate score
        score_factors = []
        if has_number:
            score_factors.append(("specific number", 20))
        if has_year:
            score_factors.append(("current year", 15))
        if has_specific_terms:
            score_factors.append(("value terms", 25))
        if brand_like:
            score_factors.append((f"entities: {', '.join(brand_like[:3])}", 30))
        if len(title.split()) >= 4:
            score_factors.append(("good length", 10))
        
        raw_score = min(100, sum(f[1] for f in score_factors))
        
        if raw_score < 100:
            missing = []
            if not has_number:
                missing.append("specific numbers")
            if not has_specific_terms:
                missing.append("value terms (guide, best, complete)")
            if not brand_like:
                missing.append("recognizable brands/entities")
            
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
    
    def _analyze_entity_density(self, text: str, title: str) -> tuple[ScoreBreakdown, list[str]]:
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
        
        # Extract key entities from title (English stop words)
        # Expanded Stoplist per user request "Over, The, What, How, About, News, More"
        stop_words = {
            'the', 'a', 'an', 'of', 'to', 'in', 'is', 'are', 'how', 'what', 'for', 'with', 'and', 'or',
            'guide', 'review', 'best', 'top', 'vs', 'over', 'about', 'news', 'more', 'this', 'that',
            'drives', 'really', 'just', 'from', 'your', 'will', 'can', 'why', 'when', 'where', 'which',
            'who', 'whose', 'does', 'do', 'should', 'would', 'could', 'has', 'have', 'had', 'been'
        }
        
        whitelist = {"chiliz", "fan token", "socios.com", "bitcoin", "ethereum", "blockchain", "crypto"}
        
        # Clean title to list of words using a method that preserves punctuation for "Socios.com"
        # We'll just split by space and strip mild punctuation, or use regex that keeps dots inside words
        title_words = title.split()
        
        key_entities = []
        for w in title_words:
            # Clean word: remove trailing/leading punctuation but allow internal dots/hyphens
            clean_w = w.strip(".,;:!?()[]\"'")
            lower_w = clean_w.lower()
            
            # CHECK 1: Whitelist (Accept immediately)
            # Check if loose match in whitelist (e.g. "Bitcoin" -> "bitcoin" in whitelist)
            is_whitelisted = False
            for wl_item in whitelist:
                if wl_item in lower_w: # "Can you buy Fan Tokens" -> "Fan Token" in whitelist
                    is_whitelisted = True
                    break
            
            if is_whitelisted:
                if clean_w not in key_entities:
                    key_entities.append(clean_w)
                continue
                
            # CHECK 2: Strict Candidate Rules
            # 1. Start with Uppercase (Title Case)
            # 2. Length > 3
            # 3. NOT in Stop Words
            if (len(clean_w) > 3 and 
                clean_w[0].isupper() and 
                lower_w not in stop_words):
                
                if clean_w not in key_entities:
                    key_entities.append(clean_w)
                    
        # If no entities found after strict check (unlikely for proper titles), fall back to simple
        if not key_entities:
             # Just take significant words > 4 chars not in stop words
            for w in title_words:
                clean_w = w.strip(".,;:!?()[]\"'")
                if len(clean_w) > 4 and clean_w.lower() not in stop_words:
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
