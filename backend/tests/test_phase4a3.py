import pytest
from datetime import datetime, timezone
from src.models.schemas import PageData
from src.detectors.evidence_density import EvidenceDensityDetector
from src.detectors.entity import EntityDetector
from src.detectors.formatting import FormattingDetector
from src.utils.text_processing import extract_main_content


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


@pytest.mark.asyncio
async def test_claims_nav_footer_links_do_not_verify_article_claims():
    """
    Página con 3 claims, sin enlaces externos en el artículo pero con enlaces en nav/footer:
    debe resultar en 0/3 verificadas.
    """
    detector = EvidenceDensityDetector()
    html = """
    <html>
        <body>
            <header>
                <nav>
                    <a href="https://external-resource.com/nav-link">External Nav Link</a>
                </nav>
            </header>
            <main>
                <article>
                    <h1>Market Growth in 2026</h1>
                    <p>According to 2026 research data, market adoption increased by 45% across all regions.</p>
                    <p>Studies show that 80% of companies have integrated artificial intelligence into daily workflows.</p>
                    <p>Recent survey data shows that more than 60% of executives anticipate higher budgets next year.</p>
                </article>
            </main>
            <footer>
                <a href="https://external-partner.org/footer-link">External Footer Partner</a>
            </footer>
        </body>
    </html>
    """
    page = make_page(html=html, url="https://example.com/market-growth")
    result = await detector.analyze(page)
    
    breakdown = result.breakdown[0]
    # Must report 0/3 verified claims
    assert "Found 0/3 verified claims" in breakdown.explanation


def test_claims_verification_markers_and_external_links():
    """Verify that claims count as verified with markers or external non-social links, but not internal or social links."""
    detector = EvidenceDensityDetector()
    
    # 1. Explicit citation markers [1] or (Source: / (Fuente:
    bd_marker1 = detector._analyze_claims(
        text="According to 2026 research, 75% of users prefer search assistants [1].",
        html="<p>According to 2026 research, 75% of users prefer search assistants [1].</p>",
        base_url="https://example.com"
    )
    assert "Found 1/1 verified claims" in bd_marker1.explanation

    bd_marker2 = detector._analyze_claims(
        text="Un estudio de 2026 muestra que el 65% prefiere IA (Fuente: Gartner, 2026).",
        html="<p>Un estudio de 2026 muestra que el 65% prefiere IA (Fuente: Gartner, 2026).</p>",
        base_url="https://example.com"
    )
    assert "Found 1/1 verified claims" in bd_marker2.explanation

    # 2. External non-social link in same block verifies
    html_ext = """
    <p>According to research, 50% of traffic increased in 2026 <a href="https://reuters.com/report">Reuters Report</a>.</p>
    """
    bd_ext = detector._analyze_claims(
        text="According to research, 50% of traffic increased in 2026.",
        html=html_ext,
        base_url="https://example.com"
    )
    assert "Found 1/1 verified claims" in bd_ext.explanation

    # 3. Internal link does NOT verify
    html_int = """
    <p>According to research, 50% of traffic increased in 2026 <a href="https://example.com/internal-post">Our Blog</a>.</p>
    """
    bd_int = detector._analyze_claims(
        text="According to research, 50% of traffic increased in 2026.",
        html=html_int,
        base_url="https://example.com"
    )
    assert "Found 0/1 verified claims" in bd_int.explanation

    # 4. Social link does NOT verify
    html_soc = """
    <p>According to research, 50% of traffic increased in 2026 <a href="https://twitter.com/intent/tweet?text=hello">Tweet</a>.</p>
    """
    bd_soc = detector._analyze_claims(
        text="According to research, 50% of traffic increased in 2026.",
        html=html_soc,
        base_url="https://example.com"
    )
    assert "Found 0/1 verified claims" in bd_soc.explanation


def test_fantokens_title_entities():
    """
    El título de fantokens debe dar Chiliz, $CHZ (o CHZ) y, solo si aparece >= 2 veces en el cuerpo, Fan Token.
    """
    detector = EntityDetector()
    title = "Chiliz Introduces $CHZ Buybacks to Reinforce Long-Term Value Across Fan Token Ecosystem"
    
    # Body with Fan Token >= 2 times
    body_with_fan_token = (
        "Today Chiliz announced buybacks to reinforce long-term stability. "
        "The $CHZ token powers the whole Fan Token network. "
        "Each Fan Token provides holders with voting rights on major club decisions."
    )
    entities_yes = detector._extract_title_entities(title, text=body_with_fan_token)
    assert "Chiliz" in entities_yes
    assert "$CHZ" in entities_yes or "CHZ" in entities_yes
    assert "Fan Token" in entities_yes

    # Body with Fan Token only 1 time (< 2 times)
    body_without_fan_token = (
        "Today Chiliz announced that they will perform token buybacks. "
        "The announcement by Chiliz reinforces the token ecosystem with $CHZ in circulation. "
        "They expect buybacks to continue through next year."
    )
    entities_no = detector._extract_title_entities(title, text=body_without_fan_token)
    assert "Chiliz" in entities_no
    assert "$CHZ" in entities_no or "CHZ" in entities_no
    assert "Fan Token" not in entities_no


def test_google_ai_overview_mini_estudio_split():
    """
    'Qué hace que Google te cite en un AI Overview [Mini-Estudio]' debe dar Google y AI Overview,
    sin pegarse a Mini-Estudio.
    """
    detector = EntityDetector()
    title = "Qué hace que Google te cite en un AI Overview [Mini-Estudio]"
    body = (
        "En este artículo analizamos cómo Google selecciona fuentes para un AI Overview. "
        "Los datos muestran que un AI Overview suele citar dominios con alta autoridad."
    )
    entities = detector._extract_title_entities(title, text=body)
    
    assert "Google" in entities
    assert "AI Overview" in entities
    # Must NOT attach to Mini-Estudio
    for ent in entities:
        assert "Mini" not in ent
        assert "Estudio" not in ent
        assert "[" not in ent
        assert "]" not in ent


@pytest.mark.asyncio
async def test_entity_detector_debug_info_same_as_submetrics():
    """La lista 'Found entities' en debug_info debe ser exactamente la misma usada en las submétricas."""
    detector = EntityDetector()
    title = "Cómo optimizar tu contenido para Google y Gemini con técnicas avanzadas"
    html = f"""
    <html>
        <body>
            <article>
                <h1>{title}</h1>
                <p>Google y Gemini analizan la semántica del contenido minuciosamente.</p>
                <p>Para posicionar con Google y Gemini se requiere estructura clara.</p>
            </article>
        </body>
    </html>
    """
    page = make_page(html=html, text="Google y Gemini analizan contenido. Para Google y Gemini...")
    result = await detector.analyze(page)
    
    extracted_entities = detector._extract_title_entities(title, text=page.text_content)
    debug_entities = result.debug_info.get("detected_entities", [])
    
    assert debug_entities == extracted_entities[:15]
    assert "Google" in debug_entities


@pytest.mark.asyncio
async def test_multimedia_icon_warning_when_alt_missing():
    """Si no hay alt text ('Missing Alt Text' o 'Partial Alt Text'), el icono en la explicación debe ser ⚠️, no ✅."""
    detector = FormattingDetector()
    
    # 1. Missing alt text -> ⚠️
    html_missing_alt = """
    <html>
        <body>
            <article>
                <p>Article text here.</p>
                <img src="/photo1.jpg">
            </article>
        </body>
    </html>
    """
    page_missing = make_page(html=html_missing_alt)
    res_missing = await detector.analyze(page_missing)
    media_breakdown = next(b for b in res_missing.breakdown if b.name == "Multimedia Content")
    assert media_breakdown.explanation.startswith("⚠️")
    assert "Missing Alt Text" in media_breakdown.explanation

    # 2. Partial alt text -> ⚠️
    html_partial_alt = """
    <html>
        <body>
            <article>
                <p>Article text here.</p>
                <img src="/photo1.jpg" alt="Valid descriptive caption">
                <img src="/photo2.jpg">
            </article>
        </body>
    </html>
    """
    page_partial = make_page(html=html_partial_alt)
    res_partial = await detector.analyze(page_partial)
    media_breakdown_partial = next(b for b in res_partial.breakdown if b.name == "Multimedia Content")
    assert media_breakdown_partial.explanation.startswith("⚠️")
    assert "Partial Alt Text" in media_breakdown_partial.explanation

    # 3. Optimized alt text -> ✅
    html_optimized = """
    <html>
        <body>
            <article>
                <p>Article text here.</p>
                <img src="/photo1.jpg" alt="Valid caption 1">
                <img src="/photo2.jpg" alt="Valid caption 2">
            </article>
        </body>
    </html>
    """
    page_opt = make_page(html=html_optimized)
    res_opt = await detector.analyze(page_opt)
    media_breakdown_opt = next(b for b in res_opt.breakdown if b.name == "Multimedia Content")
    assert media_breakdown_opt.explanation.startswith("✅")
    assert "Optimized" in media_breakdown_opt.explanation


def test_prohibited_author_keywords():
    """Verify that new author noise keywords are stripped from main content."""
    html = """
    <html>
        <body>
            <article>
                <h1>Main Post Title</h1>
                <p>Valuable content discussing optimization techniques and performance metrics in detail.</p>
                <div class="about-author"><p>Bio of author John Doe</p></div>
                <div class="author-info"><p>Author info section</p></div>
                <div class="sobre-autor"><p>Sección sobre el autor</p></div>
                <div class="caja-autor"><p>Caja del autor</p></div>
                <div class="autor-box"><p>Autor box details</p></div>
                <div class="author-card"><p>Author card social links</p></div>
            </article>
        </body>
    </html>
    """
    scoped_html, scoped_text = extract_main_content(html)
    assert "Valuable content discussing optimization techniques" in scoped_text
    assert "Bio of author John Doe" not in scoped_text
    assert "Author info section" not in scoped_text
    assert "Sección sobre el autor" not in scoped_text
    assert "Caja del autor" not in scoped_text
    assert "Autor box details" not in scoped_text
    assert "Author card social links" not in scoped_text
