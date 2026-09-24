import pytest
import httpx
from datetime import datetime, timezone
from src.models.schemas import PageData, AuditRequest
from src.detectors.infrastructure import InfrastructureDetector
from src.detectors.authority import AuthorityDetector
from src.detectors.metadata import MetadataDetector
from main import app
from httpx import AsyncClient, ASGITransport


def create_page_data(
    url="https://example.com/test",
    html="",
    text="",
    robots_txt=None
) -> PageData:
    return PageData(
        url=url,
        final_url=url,
        html_raw=html or f"<html><body><p>{text}</p></body></html>",
        html_rendered=html or f"<html><body><p>{text}</p></body></html>",
        text_content=text,
        status_code=200,
        load_time_ms=200.0,
        word_count=len(text.split()) if text else 50,
        is_ssr=True,
        is_https=True,
        ttfb_ms=300.0,
        robots_txt_content=robots_txt,
        scraped_at=datetime.now(timezone.utc)
    )


@pytest.mark.asyncio
async def test_robots_txt_blocking_oai_searchbot_caps_score_at_30():
    """Test that blocking OAI-SearchBot in robots.txt sets critical flag and caps total audit score at 30."""
    robots_blocked = """
User-agent: OAI-SearchBot
Disallow: /
User-agent: *
Allow: /
"""
    # 1. Check InfrastructureDetector directly
    infra_detector = InfrastructureDetector()
    page = create_page_data(
        url="https://example.com/blog/article",
        robots_txt=robots_blocked
    )
    result = await infra_detector.analyze(page)
    
    assert result.debug_info.get("has_critical_bot_block") is True
    bot_breakdown = next(b for b in result.breakdown if b.name == "AI Bot Access")
    assert bot_breakdown.raw_score == 0.0
    assert "Blocked" in bot_breakdown.explanation
    assert any("CRITICAL" in r for r in bot_breakdown.recommendations)

    # 2. Check full audit endpoint with mock scraping/robots
    rich_text = (
        "Artificial intelligence and vector search are transforming how information is discovered. "
        "According to research published in 2026, over 45% of technical queries are answered by AI models. "
        "We tested this in our laboratory and we found significant improvements. "
        "Written by Dr. Alice Smith: Principal AI Researcher. "
        "Furthermore, modern search architectures rely on semantic embeddings. "
        "Consequently, content citability is now essential for every enterprise."
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        from unittest.mock import patch, AsyncMock
        mock_scraper = AsyncMock()
        mock_scraper.scrape = AsyncMock(return_value=create_page_data(
            url="https://example.com/blog/article",
            text=rich_text,
            robots_txt=robots_blocked
        ))
        with patch("main.fetch_robots_txt", return_value=robots_blocked), \
             patch("main.measure_ttfb", return_value=250.0), \
             patch("main.scraper", mock_scraper):
            response = await client.post("/api/audit", json={"url": "https://example.com/blog/article"})
            assert response.status_code == 200
            data = response.json()
            assert data["total_score"] <= 30.0
            assert data["score_capped"] is True
            assert "OAI-SearchBot" in data["cap_reason"]
            assert any("CRITICAL" in rec for rec in data["recommendations"])
            assert "OAI-SearchBot" in data["recommendations"][0]


@pytest.mark.asyncio
async def test_authorship_priority_schema_over_text_in_middle():
    """Test that author in JSON-LD has priority over another name with 'por' in the middle of text."""
    detector = AuthorityDetector()
    
    schema_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Estudio de Citabilidad en IA",
            "author": {
                "@type": "Person",
                "name": "Mj Cachon"
            }
        }
        </script>
    </head>
    <body>
        <h1>Estudio de Citabilidad en IA</h1>
        <p>Introducción al estudio de visibilidad en modelos generativos y motores de búsqueda.</p>
        <p>Este informe fue revisado por Pedro Gomez a mitad del proceso de redacción de los resultados obtenidos.</p>
        <p>Conclusiones finales sobre la optimización de contenido para respuestas de IA en 2026.</p>
    </body>
    </html>
    """
    page = create_page_data(
        html=schema_html,
        text="Introducción al estudio de visibilidad en modelos generativos y motores de búsqueda. Este informe fue revisado por Pedro Gomez a mitad del proceso de redacción de los resultados obtenidos. Conclusiones finales sobre la optimización de contenido para respuestas de IA en 2026."
    )
    
    result = await detector.analyze(page)
    auth_breakdown = next(b for b in result.breakdown if b.name == "Authorship Verification")
    
    assert auth_breakdown.raw_score == 100.0
    assert "Author found in schema: Mj Cachon" in auth_breakdown.explanation
    assert "Pedro Gomez" not in auth_breakdown.explanation


@pytest.mark.asyncio
async def test_training_bots_blocked_only_informational():
    """Test that blocking only training bots (GPTBot) does not set critical block nor cap total score."""
    robots_training_blocked = """
User-agent: GPTBot
Disallow: /
User-agent: *
Allow: /
"""
    infra_detector = InfrastructureDetector()
    page = create_page_data(
        url="https://example.com/test",
        robots_txt=robots_training_blocked
    )
    result = await infra_detector.analyze(page)
    assert result.debug_info.get("has_critical_bot_block") is not True
    bot_breakdown = next(b for b in result.breakdown if b.name == "AI Bot Access")
    assert bot_breakdown.raw_score == 80.0
    assert "Training bots restricted" in bot_breakdown.explanation


@pytest.mark.asyncio
async def test_metadata_score_not_capped_at_30():
    """Test that missing critical schema types does NOT cap the dimension score at 30 anymore."""
    detector = MetadataDetector()
    html_with_entity_only = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Acme Corp"
        }
        </script>
    </head>
    <body><p>Hello world</p></body>
    </html>
    """
    page = create_page_data(html=html_with_entity_only, text="Hello world")
    result = await detector.analyze(page)
    assert result.score > 30.0


@pytest.mark.asyncio
async def test_high_value_trust_pages_expansion():
    """Test that new high-value trust paths (sobre-mi, quien-soy, etc.) are recognized as high value."""
    detector = AuthorityDetector()
    html_trust = """
    <html><body>
        <a href="/sobre-mi">Sobre mí</a>
        <a href="/privacidad">Privacidad</a>
        <a href="/contacto">Contacto</a>
    </body></html>
    """
    page = create_page_data(html=html_trust, text="Acerca de nosotros")
    result = await detector.analyze(page)
    trust_breakdown = next(b for b in result.breakdown if b.name == "Trust Pages")
    assert trust_breakdown.raw_score == 100.0
