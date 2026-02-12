"""Scrapers package for GEO-AUDITOR AI."""

from .base_scraper import BaseScraper
from .playwright_scraper import PlaywrightScraper

__all__ = ["BaseScraper", "PlaywrightScraper"]
