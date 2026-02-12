"""
GEO-AUDITOR AI - Base Detector Interface

Abstract base class for all detector modules.
Each detector evaluates one of the 10 citability dimensions
and produces a DetectorResult with transparent scoring breakdown.

Following the modular architecture from best practices:
"Cada una de las 10 dimensiones debe ser un módulo independiente
con su propio detector/scorer."
"""

from abc import ABC, abstractmethod
from src.models.schemas import PageData, DetectorResult


class BaseDetector(ABC):
    """
    Abstract base class for citability detectors.
    
    All dimension detectors inherit from this class.
    Each detector is responsible for:
    1. Analyzing a specific aspect of page content
    2. Producing transparent, explainable scores
    3. Generating actionable recommendations
    
    The detector pattern allows:
    - Independent testing of each dimension
    - Easy weight adjustment via config
    - Graceful failure isolation (one detector failing doesn't break others)
    
    Example:
        >>> detector = InfrastructureDetector()
        >>> result = await detector.analyze(page_data)
        >>> print(f"Score: {result.score}, Status: {result.status}")
        Score: 85.0, Status: green
        
    Attributes:
        dimension_name: Human-readable name of this dimension
        weight: Contribution to total score (0-1)
    """
    
    dimension_name: str = "base"
    weight: float = 0.0
    
    @abstractmethod
    async def analyze(self, page_data: PageData) -> DetectorResult:
        """
        Analyze page data and return scored result.
        
        Args:
            page_data: Scraped page content and metadata
            
        Returns:
            DetectorResult containing:
            - dimension: Name of evaluated dimension
            - score: 0-100 score
            - weight: Dimension weight
            - contribution: score * weight
            - breakdown: List of ScoreBreakdown items
            - errors: Any errors encountered
        """
        pass
    
    def calculate_contribution(self, score: float) -> float:
        """
        Calculate this dimension's contribution to total score.
        
        Args:
            score: Raw dimension score (0-100)
            
        Returns:
            Weighted contribution to total score
        """
        return score * self.weight
