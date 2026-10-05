"""
GEO-AUDITOR AI - Configuration Settings

Centralized configuration module for the application.
Follows 12-factor app principles with environment variable support.
"""

import json
from pathlib import Path
from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Configuration
    app_name: str = "GEO-AUDITOR AI"
    app_version: str = "v2.3"
    debug: bool = False
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS Configuration
    # In production, set GEO_AUDITOR_CORS_ORIGINS='["https://your-frontend.vercel.app"]'
    cors_origins: list[str] = ["http://localhost:3000", "https://carloscanofernandez.com", "http://carloscanofernandez.com"]
    
    # Scraping Configuration
    scraper_timeout_ms: int = 30000
    scraper_wait_until: str = "load"
    max_content_length: int = 5000000  # 5MB max
    challenge_retry_delay_seconds: float = 5.0
    
    # Performance Targets (from SRS)
    max_analysis_time_seconds: int = 60
    
    # Scoring Configuration
    scoring_weights_path: Path = Path(__file__).parent / "scoring_weights.json"

    # AI / LLM Layer Configuration
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_timeout_seconds: float = 45.0
    llm_daily_limit: int = 200

    # DataForSEO / SERP Configuration
    dataforseo_login: str = ""
    dataforseo_password: str = Field(default="", repr=False)
    serp_daily_limit: int = 100
    serp_timeout_seconds: float = 90.0

    # Security / Access Protection Configuration
    access_code: str = Field(default="", repr=False)

    # Ahrefs Configuration
    ahrefs_api_key: str = Field(default="", repr=False)
    ahrefs_daily_limit: int = 50

    @property
    def ahrefs_enabled(self) -> bool:
        """True only if an Ahrefs API key is configured."""
        return bool(self.ahrefs_api_key and self.ahrefs_api_key.strip())

    @property
    def access_required(self) -> bool:
        """True if an access code has been configured."""
        return bool(self.access_code and self.access_code.strip())

    @property
    def ai_enabled(self) -> bool:
        """True only if llm_base_url, llm_model, and llm_api_key are all non-empty."""
        return bool(
            self.llm_base_url and self.llm_base_url.strip() and
            self.llm_model and self.llm_model.strip() and
            self.llm_api_key and self.llm_api_key.strip()
        )

    @property
    def serp_enabled(self) -> bool:
        """True only if dataforseo_login and dataforseo_password have values AND ai_enabled is True."""
        return bool(
            self.ai_enabled and
            self.dataforseo_login and self.dataforseo_login.strip() and
            self.dataforseo_password and self.dataforseo_password.strip()
        )
    
    class Config:

        env_prefix = "GEO_AUDITOR_"
        env_file = ".env"
        extra = "ignore"
    
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
