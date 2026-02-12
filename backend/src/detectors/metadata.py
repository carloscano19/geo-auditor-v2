"""
GEO-AUDITOR AI - Metadata Intelligence Detector

Layer 2: Metadata Intelligence & Schema (8% of total score)

Evaluates the presence and validity of Structured Data (Schema.org),
which is critical for Search Engines and LLMs to understand content context.

Sub-metrics evaluated:
- Schema Presence: Is there any valid JSON-LD/Microdata? (40%)
- Critical Types: Article, FAQPage, Product found? (40%)
- Entity Depth: Person/Organization (Author signals)? (20%)

Implementation uses `extruct` for robust parsing of:
- JSON-LD (Preferred)
- Microdata
- RDFa
"""

import extruct
from typing import Dict, List, Any
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown
from src.detectors.base_detector import BaseDetector
from config.settings import get_settings


class MetadataDetector(BaseDetector):
    """
    Metadata Intelligence Detector.
    
    Evaluates Layer 2 criteria:
    "2. Metadata Intelligence | 8% | Schema.org (Article, FAQ, Person)"
    
    Attributes:
        dimension_name: "metadata_schema"
        weight: 0.08 (8% of total score)
    """
    
    dimension_name: str = "metadata_schema"
    weight: float = 0.08
    
    # Sub-dimension weights
    SCHEMA_PRESENCE_WEIGHT = 0.40
    CRITICAL_TYPES_WEIGHT = 0.40
    ENTITY_DEPTH_WEIGHT = 0.20
    
    # Priority Schema Types
    CRITICAL_TYPES = {"Article", "BlogPosting", "NewsArticle", "FAQPage", "Product"}
    ENTITY_TYPES = {"Person", "Organization"}
    
    def __init__(self):
        """Initialize with settings."""
        self.settings = get_settings()
        
        # Load weights from config if available
        try:
            weights = self.settings.scoring_weights
            meta_config = weights.get("dimensions", {}).get("metadata_schema", {})
            self.weight = meta_config.get("weight", self.weight)
        except Exception:
            pass
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """Analyze metadata and schema.org implementation."""
        errors: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        
        # Parse Schema
        try:
            # Use raw HTML for extraction
            metadata = extruct.extract(
                page_data.html_raw,
                base_url=page_data.url,
                uniform=True,  # Normalize output
                syntaxes=['json-ld', 'microdata', 'rdfa']
            )
        except Exception as e:
            errors.append(f"Schema extraction failed: {str(e)}")
            metadata = {}
            
        # Flatten extracted data
        all_schemas = []
        for syntax, items in metadata.items():
            if items:
                # Add syntax info to each item
                for item in items:
                    item['_syntax'] = syntax
                all_schemas.extend(items)
        
        # 1. Critical Types Check First (needed for presence logic)
        try:
            types_result = self._analyze_critical_types(all_schemas)
            # We'll append it later to keep the order in breakdown
        except Exception as e:
            errors.append(f"Critical types check failed: {str(e)}")
            types_result = self._create_error_breakdown("Critical Schema Types", self.CRITICAL_TYPES_WEIGHT)

        # 2. Schema Presence Check (Now with JSON-LD priority)
        try:
            presence_result = self._analyze_presence(all_schemas, types_result.raw_score > 0)
            breakdown.append(presence_result)
        except Exception as e:
            errors.append(f"Presence check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Schema Presence", self.SCHEMA_PRESENCE_WEIGHT))
            
        # Add Critical Types result
        breakdown.append(types_result)
            
        # 3. Entity Depth Check
        try:
            depth_result = self._analyze_entity_depth(all_schemas)
            breakdown.append(depth_result)
        except Exception as e:
            errors.append(f"Entity depth check failed: {str(e)}")
            breakdown.append(self._create_error_breakdown("Entity Depth", self.ENTITY_DEPTH_WEIGHT))
            
        # Calculate total dimension score
        total_score = sum(item.weighted_score for item in breakdown)
        
        # STRICT CAP: If no critical types, cap at 30
        if types_result.raw_score == 0:
            total_score = min(30.0, total_score)
        
        return DetectorResult(
            dimension=self.dimension_name,
            score=total_score,
            weight=self.weight,
            contribution=self.calculate_contribution(total_score),
            breakdown=breakdown,
            errors=errors,
        )
    
    def _analyze_presence(self, schemas: List[Dict[str, Any]], has_critical_types: bool) -> ScoreBreakdown:
        """Check if any valid schema is present (Priority: JSON-LD)."""
        syntaxes = list(set(s.get('_syntax', 'unknown') for s in schemas))
        has_jsonld = 'json-ld' in syntaxes
        
        raw_score = 0.0
        explanation = ""
        recommendations = []
        
        if has_jsonld:
            raw_score = 100.0
            explanation = f"Correct JSON-LD implementation detected ({len([s for s in schemas if s.get('_syntax') == 'json-ld'])} items)."
        elif has_critical_types:
            # Enforce 0 score for RDFa-only even if critical types are present
            raw_score = 0.0
            explanation = "Detected critical types in Microdata/RDFa, but JSON-LD (preferred) is missing. Score: 0."
            recommendations.append("Move your structured data to JSON-LD format for better Google compatibility.")
            recommendations.append("⚠️ Weak Schema Detected (RDFa/Microdata only) - Google might ignore this.")
        else:
            raw_score = 0.0
            explanation = "No valid JSON-LD detected. Generic RDFa/Microdata items were ignored."
            recommendations.append("Implement JSON-LD Schema (Article, NewsArticle, etc.) to help LLMs understand your content.")

        return ScoreBreakdown(
            name="Schema Presence",
            raw_score=raw_score,
            weight=self.SCHEMA_PRESENCE_WEIGHT,
            weighted_score=raw_score * self.SCHEMA_PRESENCE_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
    
    def _analyze_critical_types(self, schemas: List[Dict[str, Any]]) -> ScoreBreakdown:
        """Check for critical content types (Article, FAQ, etc.)."""
        found_types = set()
        
        for item in schemas:
            item_type = item.get('@type')
            if isinstance(item_type, str):
                found_types.add(item_type)
            elif isinstance(item_type, list):
                found_types.update(item_type)
        
        matched_critical = found_types.intersection(self.CRITICAL_TYPES)
        
        if matched_critical:
            raw_score = 100.0
            explanation = (
                f"Critical Schema types found: {', '.join(matched_critical)}. "
                "Excellent for content discoverability."
            )
            recommendations = []
        else:
            raw_score = 0.0
            explanation = "No critical Schema types (Article, FAQPage) detected."
            recommendations = [
                f"Add one of the following Schema types: {', '.join(list(self.CRITICAL_TYPES)[:3])}."
            ]
            
        return ScoreBreakdown(
            name="Critical Schema Types",
            raw_score=raw_score,
            weight=self.CRITICAL_TYPES_WEIGHT,
            weighted_score=raw_score * self.CRITICAL_TYPES_WEIGHT,
            explanation=explanation,
            recommendations=recommendations,
        )
        
    def _analyze_entity_depth(self, schemas: List[Dict[str, Any]]) -> ScoreBreakdown:
        """Check for Author/Publisher signals (Person, Organization)."""
        found_entities = set()
        
        # Helper to recursively search for types
        def find_types(data, target_set):
            if isinstance(data, dict):
                t = data.get('@type')
                if t:
                    if isinstance(t, str):
                        target_set.add(t)
                    elif isinstance(t, list):
                        target_set.update(t)
                for v in data.values():
                    find_types(v, target_set)
            elif isinstance(data, list):
                for item in data:
                    find_types(item, target_set)

        find_types(schemas, found_entities)
        
        matched_entities = found_entities.intersection(self.ENTITY_TYPES)
        
        if matched_entities:
            raw_score = 100.0
            explanation = (
                f"Author/Publisher signals detected: {', '.join(matched_entities)}. "
                "Helps establish E-E-A-T."
            )
            recommendations = []
        else:
            raw_score = 0.0
            explanation = "No Person or Organization schema detected."
            recommendations = [
                "Define an Author (Person) or Publisher (Organization) in your schema.",
                "This reinforces Authority and Trustworthiness."
            ]
            
        return ScoreBreakdown(
            name="Entity Depth (E-E-A-T)",
            raw_score=raw_score,
            weight=self.ENTITY_DEPTH_WEIGHT,
            weighted_score=raw_score * self.ENTITY_DEPTH_WEIGHT,
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
