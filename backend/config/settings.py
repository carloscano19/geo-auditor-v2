"""
GEO-AUDITOR AI - Configuration Settings

Centralized configuration module for the application.
Follows 12-factor app principles with environment variable support.
"""

import json
from pathlib import Path
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Configuration
    app_name: str = "GEO-AUDITOR AI"
    app_version: str = "2.0.0"
    debug: bool = False
    
    # AI Keys
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS Configuration
    # In production, set GEO_AUDITOR_CORS_ORIGINS='["https://your-frontend.vercel.app"]'
    cors_origins: list[str] = ["http://localhost:3000"]
    
    # Scraping Configuration
    scraper_timeout_ms: int = 30000
    scraper_wait_until: str = "networkidle"
    max_content_length: int = 5000000  # 5MB max
    
    # Performance Targets (from SRS)
    max_analysis_time_seconds: int = 60
    
    # Scoring Configuration
    scoring_weights_path: Path = Path(__file__).parent / "scoring_weights.json"
    
    class Config:
        env_prefix = "GEO_AUDITOR_"
        env_file = ".env"
    
    @property
    def scoring_weights(self) -> dict:
        """Load scoring weights from JSON config file."""
        return load_scoring_weights(self.scoring_weights_path)


@lru_cache()
def load_scoring_weights(path: Path) -> dict:
    """
    Load and cache scoring weights from JSON file.
    
    Args:
        path: Path to the scoring_weights.json file
        
    Returns:
        Dictionary containing scoring weights for all dimensions
        
    Raises:
        FileNotFoundError: If the weights file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings instance."""
    return Settings()
