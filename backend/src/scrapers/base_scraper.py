"""
GEO-AUDITOR AI - Base Scraper Interface

Abstract base class defining the scraper interface.
Allows swapping between different scraper implementations
(BeautifulSoup, Playwright, Selenium) without changing dependent code.

Following the Agnosticismo de APIs principle from best practices.
"""

from abc import ABC, abstractmethod
from src.models.schemas import PageData


class BaseScraper(ABC):
    """
    Abstract base class for web scrapers.
    
    All scraper implementations must inherit from this class and implement
    the scrape method. This allows for easy swapping between scraping
    strategies (e.g., BeautifulSoup for simple pages, Playwright for SPAs).
    
    Example:
        >>> scraper = PlaywrightScraper()
        >>> page_data = await scraper.scrape("https://example.com")
        >>> print(page_data.is_ssr)
        True
    """
    
    @abstractmethod
    async def scrape(self, url: str) -> PageData:
        """
        Scrape a URL and return structured page data.
        
        Args:
            url: The URL to scrape (must be valid HTTP/HTTPS)
            
        Returns:
            PageData object containing all scraped information
            
        Raises:
            ScraperError: If scraping fails due to network or parsing issues
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """
        Clean up scraper resources.
        
        Should be called when the scraper is no longer needed.
        Implementations should handle browser cleanup, connection closing, etc.
        """
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.close()


class ScraperError(Exception):
    """
    Custom exception for scraper failures.
    
    Attributes:
        url: The URL that failed to scrape
        reason: Human-readable failure reason
        original_error: The underlying exception, if any
    """
    
    def __init__(self, url: str, reason: str, original_error: Exception = None):
        self.url = url
        self.reason = reason
        self.original_error = original_error
        super().__init__(f"Failed to scrape {url}: {reason}")
