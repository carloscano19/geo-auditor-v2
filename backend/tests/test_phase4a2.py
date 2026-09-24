import pytest
from src.models.schemas import PageData
from src.detectors.evidence_density import EvidenceDensityDetector
from src.detectors.entity import EntityDetector
from datetime import datetime, timezone


def make_page(html: str, text: str = "", url: str = "https://example.com/article") -> PageData:
    return PageData(
        url=url,
        final_url=url,
        html_raw=html,
        html_rendered=html,
        text_content=text or "Sample content for testing purposes.",
        status_code=200,
        load_time_ms=200.0,
        word_count=len(text.split()) if text else 50,
        is_ssr=True,
        is_https=True,
        ttfb_ms=250.0,
        scraped_at=datetime.now(timezone.utc)
    )


def test_nav_boilerplate_excluded_from_claims():
    """Verify that claims inside nav/header/footer boilerplate are excluded from evidence density."""
    detector = EvidenceDensityDetector()
    html = """
    <html>
        <head><title>Test Page</title></head>
        <body>
            <header>
                <nav>
                    <ul>
                        <li><a href="/stats">According to 2026 studies, 95% of users use our menu</a></li>
                    </ul>
                </nav>
            </header>
            <main>
                <p>This is a regular descriptive paragraph that discusses technology trends in general terms.</p>
            </main>
            <footer>
                <p>According to survey data, 80% prefer our footer links.</p>
            </footer>
        </body>
    </html>
    """
    breakdown = detector._analyze_claims(
        text="According to 2026 studies, 95% of users use our menu. This is a regular descriptive paragraph.",
        html=html
    )
    # The claims inside nav and footer should be stripped out by clean_html_for_analysis
    assert "No strong claims or statistics detected requiring verification" in breakdown.explanation
    assert breakdown.raw_score == 50.0


def test_h2_not_concatenated_with_paragraph():
    """Verify that H2 heading text is not concatenated with the following paragraph when extracting sentences."""
    detector = EvidenceDensityDetector()
    html = """
    <html>
        <body>
            <main>
                <h2>Recent Statistics on AI Adoption</h2>
                <p>According to 2026 industry research, over 75% of enterprises have deployed LLMs in production.</p>
            </main>
        </body>
    </html>
    """
    breakdown = detector._analyze_claims(
        text="Recent Statistics on AI Adoption According to 2026 industry research, over 75% of enterprises have deployed LLMs in production.",
        html=html
    )
    assert "Found 0/1 verified claims" in breakdown.explanation or "Found 1/1 verified claims" in breakdown.explanation
    # Heading text must not be prepended to the claim sentence
    assert "Recent Statistics on AI Adoption" not in breakdown.explanation.split("Claims identified:")[1]
    assert "According to 2026 industry research" in breakdown.explanation


def test_title_case_without_false_entities():
    """Verify that in Title Case titles, common capitalized words (verbs, nouns) are not recognized as entities."""
    detector = EntityDetector()
    title = "Chiliz Introduces CHZ Buybacks to Reinforce Long-Term Value Across Fan Token Ecosystem"
    body = (
        "Today Chiliz announced that they will perform token buybacks. "
        "The announcement by Chiliz reinforces the token ecosystem with $CHZ in circulation. "
        "They expect buybacks to continue through next year."
    )
    
    # 1. Detection of Title Case
    assert detector._is_title_case(title) is True
    
    # 2. Entity extraction
    entities = detector._extract_title_entities(title, text=body)
    
    # Valid entities present
    assert "Chiliz" in entities
    assert "CHZ" in entities
    
    # False positive words must NOT be in entities
    false_positives = ["Introduces", "Buybacks", "Reinforce", "Long-Term", "Value", "Across", "Ecosystem"]
    for word in false_positives:
        assert word not in entities, f"False entity detected: {word}"
        
    # 3. Analyze title entities does not contain value terms in factors or recommendations
    breakdown = detector._analyze_title_entities(title, text=body)
    assert "value terms" not in breakdown.explanation.lower()
    for rec in breakdown.recommendations:
        assert "value terms" not in rec.lower()


@pytest.mark.asyncio
async def test_article_h2_excludes_aside_related_h2():
    """HTML with <article> containing 2 H2 and <aside> with 3 H2 of related posts: only 2 H2s must be counted."""
    from src.detectors.aeo_structure import AEOStructureDetector
    detector = AEOStructureDetector()
    html = """
    <html>
        <body>
            <header><h1>Site Brand</h1></header>
            <main>
                <article>
                    <h2>First Main Section</h2>
                    <p>Substantive text content about the primary topic of the guide with details and analysis.</p>
                    <h2>Second Main Section</h2>
                    <p>Further substantive text explaining the details of the implementation for users.</p>
                </article>
                <aside class="related-posts">
                    <h2>Related Post 1</h2>
                    <h2>Related Post 2</h2>
                    <h2>Related Post 3</h2>
                </aside>
            </main>
        </body>
    </html>
    """
    page = make_page(html=html, text="First Main Section text Second Main Section text")
    result = await detector.analyze(page)
    h2_list = result.debug_info.get("detected_headers", [])
    assert len(h2_list) == 2
    assert result.debug_info["structure_metrics"]["h2_count"] == 2
    assert "First Main Section" in h2_list
    assert "Second Main Section" in h2_list
    assert not any("Related" in h for h in h2_list)


@pytest.mark.asyncio
async def test_article_header_h1_detected():
    """HTML with <article><header><h1>Título</h1></header>: H1 must be detected by AEO and Entity detectors."""
    from src.detectors.aeo_structure import AEOStructureDetector
    aeo_detector = AEOStructureDetector()
    entity_detector = EntityDetector()
    html = """
    <html>
        <body>
            <article>
                <header>
                    <h1>Título del Artículo GEO</h1>
                    <p class="author">Por Carlos Cano</p>
                </header>
                <p>Contenido principal del artículo con detalles completos sobre optimización.</p>
                <h2>Sección Primera</h2>
                <p>Texto de la sección primera con datos y explicaciones relevantes.</p>
            </article>
        </body>
    </html>
    """
    page = make_page(html=html, text="Título del Artículo GEO. Contenido principal del artículo.")
    
    aeo_result = await aeo_detector.analyze(page)
    assert aeo_result.debug_info["structure_metrics"]["h1_text"] == "Título del Artículo GEO"
    assert aeo_result.debug_info["structure_metrics"]["h1_count"] == 1
    
    entity_result = await entity_detector.analyze(page)
    assert "Título del Artículo GEO" in entity_result.debug_info.get("title_entities", "")


def test_multiword_entity_ai_overview():
    """'Qué hace que Google te cite en un AI Overview': 'AI Overview' must be extracted as a single entity."""
    detector = EntityDetector()
    title = "Qué hace que Google te cite en un AI Overview"
    entities = detector._extract_title_entities(title)
    
    # Must contain "AI Overview" as a single entity
    assert "AI Overview" in entities
    # Must contain "Google"
    assert "Google" in entities
    # Must not contain individual fragments like "AI" separately when part of "AI Overview"
    assert "AI" not in entities
    # Must not contain "Qué" (<= 4 chars / common starter)
    assert "Qué" not in entities


def test_multiple_articles_picks_longest():
    """HTML with short related <article> before the main long <article>: the longest one must be chosen."""
    from src.utils.text_processing import extract_main_content
    html = """
    <html>
        <body>
            <header>Site Header</header>
            <article class="related-card">
                <h3>Short Related Post</h3>
                <p>Snippet of unrelated card.</p>
            </article>
            <article class="primary-post">
                <h1>Main Comprehensive Article</h1>
                <p>This is the actual article content containing deep analysis, facts, figures, and full explanations for readers.</p>
                <p>Additional paragraphs providing context and practical advice for search optimization.</p>
            </article>
        </body>
    </html>
    """
    scoped_html, scoped_text = extract_main_content(html)
    assert "Main Comprehensive Article" in scoped_text
    assert "Additional paragraphs providing context" in scoped_text
    assert "Short Related Post" not in scoped_text


def test_elementor_widget_content_preserved():
    """HTML with content inside <div class='elementor-widget-theme-post-content'>: content must be preserved."""
    from src.utils.text_processing import extract_main_content
    html = """
    <html>
        <body>
            <main>
                <div class="elementor-widget-theme-post-content">
                    <h1>Optimizing Content for GEO</h1>
                    <p>This article lives inside an Elementor page builder widget but represents the primary core content of the page.</p>
                    <p>It contains multiple sentences detailing generative engine optimization strategies.</p>
                </div>
                <div class="sidebar-widget">
                    <p>Subscribe to our newsletter</p>
                </div>
            </main>
        </body>
    </html>
    """
    scoped_html, scoped_text = extract_main_content(html)
    assert "Optimizing Content for GEO" in scoped_text
    assert "This article lives inside an Elementor page builder widget" in scoped_text
    assert "Subscribe to our newsletter" not in scoped_text


