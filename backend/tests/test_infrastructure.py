"""
Tests for Infrastructure Detector.

Validates the Layer 1 Technical Infrastructure detector
against ground truth test cases.

Target: >85% code coverage per best practices.
"""

import pytest
from datetime import datetime

from src.models.schemas import PageData
from src.detectors.infrastructure import InfrastructureDetector


# Mock PageData for testing
def create_mock_page_data(
    url: str = "https://example.com",
    is_https: bool = True,
    is_ssr: bool = True,
    load_time_ms: float = 1500.0,
    html_raw: str = "<html><head></head><body><h1>Title</h1><p>Content</p></body></html>",
    html_rendered: str = "<html><head></head><body><h1>Title</h1><p>Content</p></body></html>",
    headers: dict = None,
) -> PageData:
    """Create a mock PageData for testing."""
    return PageData(
        url=url,
        final_url=url,
        html_raw=html_raw,
        html_rendered=html_rendered or html_raw,
        text_content="Title Content",
        headers=headers or {},
        status_code=200,
        load_time_ms=load_time_ms,
        scraped_at=datetime.utcnow(),
        is_https=is_https,
        is_ssr=is_ssr,
        word_count=2,
    )


class TestInfrastructureDetector:
    """Test suite for InfrastructureDetector."""
    
    @pytest.fixture
    def detector(self):
        """Create detector instance."""
        return InfrastructureDetector()
    
    @pytest.mark.asyncio
    async def test_https_detection_positive(self, detector):
        """Test HTTPS detection for secure sites."""
        page_data = create_mock_page_data(
            url="https://example.com",
            is_https=True,
        )
        
        result = await detector.analyze(page_data)
        
        # Find HTTPS breakdown
        https_breakdown = next(
            (b for b in result.breakdown if "HTTPS" in b.name),
            None
        )
        
        assert https_breakdown is not None
        assert https_breakdown.raw_score == 100.0
        assert len(https_breakdown.recommendations) == 0
    
    @pytest.mark.asyncio
    async def test_https_detection_negative(self, detector):
        """Test HTTPS detection for insecure sites."""
        page_data = create_mock_page_data(
            url="http://example.com",
            is_https=False,
        )
        
        result = await detector.analyze(page_data)
        
        https_breakdown = next(
            (b for b in result.breakdown if "HTTPS" in b.name),
            None
        )
        
        assert https_breakdown is not None
        assert https_breakdown.raw_score == 0.0
        assert len(https_breakdown.recommendations) > 0
        assert "CRÍTICO" in https_breakdown.recommendations[0]
    
    @pytest.mark.asyncio
    async def test_ssr_detection_positive(self, detector):
        """Test SSR detection for server-rendered sites."""
        page_data = create_mock_page_data(is_ssr=True)
        
        result = await detector.analyze(page_data)
        
        ssr_breakdown = next(
            (b for b in result.breakdown if "Rendering" in b.name or "SSR" in b.name),
            None
        )
        
        assert ssr_breakdown is not None
        assert ssr_breakdown.raw_score == 100.0
    
    @pytest.mark.asyncio
    async def test_ssr_detection_csr(self, detector):
        """Test SSR detection for client-side rendered sites."""
        page_data = create_mock_page_data(
            is_ssr=False,
            html_raw="<html><head></head><body><div id='root'></div></body></html>",
        )
        
        result = await detector.analyze(page_data)
        
        ssr_breakdown = next(
            (b for b in result.breakdown if "Rendering" in b.name or "SSR" in b.name),
            None
        )
        
        assert ssr_breakdown is not None
        assert ssr_breakdown.raw_score < 100.0
        assert len(ssr_breakdown.recommendations) > 0
    
    @pytest.mark.asyncio
    async def test_speed_excellent(self, detector):
        """Test speed scoring for fast pages (<2s)."""
        page_data = create_mock_page_data(load_time_ms=1500.0)
        
        result = await detector.analyze(page_data)
        
        speed_breakdown = next(
            (b for b in result.breakdown if "Speed" in b.name),
            None
        )
        
        assert speed_breakdown is not None
        assert speed_breakdown.raw_score == 100.0
    
    @pytest.mark.asyncio
    async def test_speed_good(self, detector):
        """Test speed scoring for good pages (2-4s)."""
        page_data = create_mock_page_data(load_time_ms=3000.0)
        
        result = await detector.analyze(page_data)
        
        speed_breakdown = next(
            (b for b in result.breakdown if "Speed" in b.name),
            None
        )
        
        assert speed_breakdown is not None
        assert speed_breakdown.raw_score == 80.0
    
    @pytest.mark.asyncio
    async def test_speed_poor(self, detector):
        """Test speed scoring for slow pages (>10s)."""
        page_data = create_mock_page_data(load_time_ms=12000.0)
        
        result = await detector.analyze(page_data)
        
        speed_breakdown = next(
            (b for b in result.breakdown if "Speed" in b.name),
            None
        )
        
        assert speed_breakdown is not None
        assert speed_breakdown.raw_score == 0.0
    
    @pytest.mark.asyncio
    async def test_crawlability_noindex(self, detector):
        """Test crawlability detection for noindex pages."""
        html_with_noindex = '''
        <html>
        <head>
            <meta name="robots" content="noindex, nofollow">
        </head>
        <body><p>Content</p></body>
        </html>
        '''
        page_data = create_mock_page_data(
            html_raw=html_with_noindex,
            html_rendered=html_with_noindex,
        )
        
        result = await detector.analyze(page_data)
        
        crawl_breakdown = next(
            (b for b in result.breakdown if "Crawlability" in b.name),
            None
        )
        
        assert crawl_breakdown is not None
        assert crawl_breakdown.raw_score == 0.0
        assert "BLOQUEADO" in crawl_breakdown.explanation
    
    @pytest.mark.asyncio
    async def test_crawlability_clean(self, detector):
        """Test crawlability detection for clean pages."""
        html_clean = '''
        <html>
        <head>
            <link rel="canonical" href="https://example.com/page">
        </head>
        <body><p>Content</p></body>
        </html>
        '''
        page_data = create_mock_page_data(
            html_raw=html_clean,
            html_rendered=html_clean,
        )
        
        result = await detector.analyze(page_data)
        
        crawl_breakdown = next(
            (b for b in result.breakdown if "Crawlability" in b.name),
            None
        )
        
        assert crawl_breakdown is not None
        assert crawl_breakdown.raw_score == 100.0
    
    @pytest.mark.asyncio
    async def test_full_score_calculation(self, detector):
        """Test that total score is calculated correctly."""
        page_data = create_mock_page_data(
            is_https=True,
            is_ssr=True,
            load_time_ms=1500.0,
        )
        
        result = await detector.analyze(page_data)
        
        # Score should be sum of weighted sub-scores
        expected_sum = sum(b.weighted_score for b in result.breakdown)
        assert result.score == pytest.approx(expected_sum, abs=0.01)
        
        # Contribution should be score * weight
        expected_contribution = result.score * detector.weight
        assert result.contribution == pytest.approx(expected_contribution, abs=0.01)
    
    @pytest.mark.asyncio
    async def test_result_has_all_breakdowns(self, detector):
        """Test that result includes all 4 sub-dimensions."""
        page_data = create_mock_page_data()
        
        result = await detector.analyze(page_data)
        
        assert len(result.breakdown) == 4
        
        breakdown_names = [b.name for b in result.breakdown]
        assert any("HTTPS" in n for n in breakdown_names)
        assert any("Rendering" in n or "SSR" in n for n in breakdown_names)
        assert any("Crawlability" in n for n in breakdown_names)
        assert any("Speed" in n for n in breakdown_names)
    
    @pytest.mark.asyncio
    async def test_status_color_coding(self, detector):
        """Test that status returns correct color based on score."""
        # Good score
        good_page = create_mock_page_data(
            is_https=True,
            is_ssr=True,
            load_time_ms=1500.0,
        )
        good_result = await detector.analyze(good_page)
        assert good_result.status == "green"
        
        # Poor score (HTTP, CSR, slow)
        poor_page = create_mock_page_data(
            is_https=False,
            is_ssr=False,
            load_time_ms=12000.0,
            html_raw="<html><body><div id='root'></div></body></html>",
        )
        poor_result = await detector.analyze(poor_page)
        assert poor_result.status in ("yellow", "red")
