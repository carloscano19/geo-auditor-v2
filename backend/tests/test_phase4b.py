import pytest
from datetime import datetime, timezone
from src.models.schemas import PageData
from src.detectors.query_match import QueryMatchDetector, BM25
from src.detectors.passage_quality import PassageQualityDetector, compute_mtld
from src.detectors.authority import AuthorityDetector
from src.detectors.evidence_density import EvidenceDensityDetector
from src.detectors.entity import EntityDetector
from src.detectors.links import LinksDetector
from src.utils.content_type import detect_content_type


def make_page(
    html: str,
    text: str = "",
    url: str = "https://example.com/article",
    final_url: str = ""
) -> PageData:
    return PageData(
        url=url,
        final_url=final_url or url,
        html_raw=html,
        html_rendered=html,
        text_content=text or "Sample text for test.",
        status_code=200,
        load_time_ms=200.0,
        word_count=len((text or html).split()),
        is_ssr=True,
        is_https=True,
        ttfb_ms=250.0,
        scraped_at=datetime.now(timezone.utc)
    )


# 1. Query Match: Relevant vs Irrelevant
@pytest.mark.asyncio
async def test_query_match_relevant_vs_irrelevant():
    article_text = (
        "Chiliz and Fan Tokens are creating sustainable value across modern sports ecosystems. "
        "Through token buybacks and utility incentives, the Chiliz network strengthens the long-term utility of . "
        "Fans utilize Fan Tokens to vote on club decisions, earn rewards, and access exclusive community benefits. "
        "In summary, the strategic buybacks reinforce value for all token holders worldwide."
    )
    html = f"""
    <html>
        <body>
            <article>
                <h1>Chiliz Fan Tokens and Long-Term Ecosystem Value</h1>
                <p>Chiliz and Fan Tokens are creating sustainable value across modern sports ecosystems through strategic buybacks.</p>
                <p>Through token buybacks and utility incentives, the Chiliz network strengthens the long-term utility of .</p>
                <p>Fans utilize Fan Tokens to vote on club decisions, earn rewards, and access exclusive community benefits.</p>
            </article>
        </body>
    </html>
    """
    page = make_page(html=html, text=article_text)

    # Relevant query
    detector_rel = QueryMatchDetector(target_query="chiliz fan tokens buybacks value")
    res_rel = await detector_rel.analyze(page)
    assert res_rel.score >= 80.0
    # Must show best passage in explanation
    best_passage_bd = next(b for b in res_rel.breakdown if b.name == "Best Passage Match")
    assert "Best Passage Match" in best_passage_bd.explanation
    assert "Chiliz" in best_passage_bd.explanation

    # Irrelevant query
    detector_irrel = QueryMatchDetector(target_query="receta tradicional paella marisco valenciana")
    res_irrel = await detector_irrel.analyze(page)
    assert res_irrel.score == 0.0
    for bd in res_irrel.breakdown:
        assert bd.raw_score == 0.0


# 2. MTLD in EN and ES
def test_mtld_en_and_es():
    # English diverse prose
    text_en = (
        "Artificial intelligence models fundamentally transform how digital knowledge is retrieved, "
        "synthesized, and presented to users across modern conversational interfaces. "
        "Rather than relying solely on traditional inverted indexes and link graph popularity algorithms, "
        "neural answer engines utilize semantic vector spaces to assess contextual authority and direct relevance."
    )
    tokens_en = [w.lower() for w in text_en.split()]
    mtld_en = compute_mtld(tokens_en)
    assert mtld_en > 30.0

    # Spanish diverse prose
    text_es = (
        "La optimización para motores de respuesta artificial exige transformar la arquitectura editorial "
        "hacia párrafos concisos, datos verificables y citabilidad estructurada sin ambigüedades. "
        "Los sistemas neuronales seleccionan pasajes autónomos con alta densidad de evidencia, "
        "evaluando simultáneamente la reputación del autor y las fuentes independientes citadas."
    )
    tokens_es = [w.lower() for w in text_es.split()]
    mtld_es = compute_mtld(tokens_es)
    assert mtld_es > 30.0

    # Repetitive text should have significantly lower MTLD
    rep_tokens = ["token", "good", "token", "good", "the", "token", "is", "good"] * 10
    mtld_rep = compute_mtld(rep_tokens)
    assert mtld_rep < mtld_en


# 3. Non-autonomous paragraph starting with 'Como hemos visto'
@pytest.mark.asyncio
async def test_non_autonomous_paragraph_starts_with_como_hemos_visto():
    html = """
    <html>
        <body>
            <article>
                <h1>Análisis de rendimiento en sistemas distribuidos</h1>
                <p>Como hemos visto, el rendimiento de las aplicaciones mejora de forma sustancial cuando se optimiza la infraestructura técnica y se distribuyen los recursos adecuadamente en los centros de datos.</p>
                <p>Las pruebas empíricas demuestran de manera concluyente que la latencia disminuye notablemente al emplear caché en el borde de la red y técnicas avanzadas de renderizado estático.</p>
            </article>
        </body>
    </html>
    """
    text = (
        "Como hemos visto, el rendimiento de las aplicaciones mejora de forma sustancial cuando se optimiza la infraestructura técnica y se distribuyen los recursos adecuadamente en los centros de datos. "
        "Las pruebas empíricas demuestran de manera concluyente que la latencia disminuye notablemente al emplear caché en el borde de la red y técnicas avanzadas de renderizado estático."
    )
    page = make_page(html=html, text=text, url="https://example.com/es/analisis")
    page.language = "es"

    detector = PassageQualityDetector()
    result = await detector.analyze(page)

    auto_bd = next(b for b in result.breakdown if b.name == "Autonomous Passages")
    # One of the two paragraphs starts with 'Como hemos visto' -> 50% autonomous
    assert auto_bd.raw_score == 50.0
    assert "50%" in auto_bd.explanation
    assert any("Como hemos visto" in s for s in result.debug_info.get("non_autonomous_samples", []))


# 4. Newsroom page detected as news without Experience Signals
@pytest.mark.asyncio
async def test_newsroom_page_detected_as_news_without_experience_signals():
    url = "https://www.fantokens.com/newsroom/chiliz-introduces-chz-buybacks-to-reinforce-long-term-value"
    html = """
    <html>
        <body>
            <article>
                <h1>Chiliz Introduces  Buybacks</h1>
                <p>Written by Alice Smith</p>
                <p>Leading sports blockchain Chiliz today announced token buybacks.</p>
                <a href="/about-us">About Us</a>
                <a href="/editorial">Editorial Staff</a>
                <a href="/privacy">Privacy Policy</a>
            </article>
        </body>
    </html>
    """
    page = make_page(html=html, url=url)
    
    # 1. Verify content type is detected as news
    c_type = detect_content_type(page)
    assert c_type == "news"
    page.content_type = c_type

    # 2. Verify AuthorityDetector omits Experience Signals
    detector = AuthorityDetector()
    result = await detector.analyze(page)
    breakdown_names = [b.name for b in result.breakdown]

    assert "Experience Signals" not in breakdown_names
    assert "Authorship Verification" in breakdown_names
    assert "Trust Pages" in breakdown_names
    assert len(result.breakdown) == 2

    # Verify weights sum to 1.0 (approx 0.6154 + 0.3846)
    total_weights = sum(b.weight for b in result.breakdown)
    assert abs(total_weights - 1.0) < 0.01


# 5. First-party data claims: >=2 methodology signals verify claims, except third-party attributions
@pytest.mark.asyncio
async def test_first_party_data_claim_with_methodology_verified():
    html = """
    <html>
        <body>
            <article>
                <h1>Estudio de Visibilidad y Citabilidad en IA</h1>
                <p>He lanzado un estudio de 500 consultas y he medido 50 aspectos técnicos.</p>
                <p>El 84% de las frases no conserva las palabras originales del texto analizado.</p>
                <p>Según Statista, el 60% de usuarios utiliza motores de inteligencia artificial.</p>
            </article>
        </body>
    </html>
    """
    text = (
        "He lanzado un estudio de 500 consultas y he medido 50 aspectos técnicos. "
        "El 84% de las frases no conserva las palabras originales del texto analizado. "
        "Según Statista, el 60% de usuarios utiliza motores de inteligencia artificial."
    )
    page = make_page(html=html, text=text, url="https://example.com/es/estudio")
    page.language = "es"

    detector = EvidenceDensityDetector()
    result = await detector.analyze(page)

    evidence_bd = next(b for b in result.breakdown if b.name == "Evidence Density")
    assert "Verified (first-party data)" in evidence_bd.explanation
    # 3 claims found: 84% and the study description are verified first-party, while 60% is unverified because it is according to Statista without link
    assert "Found 2/3 verified claims" in evidence_bd.explanation
    assert 'Verified (first-party data): "El 84% de las frases no conserva las palabras' in evidence_bd.explanation
    assert 'Unverified: "Según Statista, el 60% de usuarios utiliza' in evidence_bd.explanation


# 6. Title Entities: Recognizable entities (70) and proper length (30) without number/year factors
def test_title_entities_without_number_or_year_factors():
    detector = EntityDetector()
    title = "Comprehensive Architectural Guide for Google and Gemini Search Citations"
    text = "Google and Gemini evaluate search citations across modern technical platforms."

    bd = detector._analyze_title_entities(title, text=text)
    assert bd.raw_score == 100.0  # 70 entities + 30 good length
    assert "specific number" not in bd.explanation
    assert "current year" not in bd.explanation
    assert not any("number" in r.lower() for r in bd.recommendations)


# 7. Source Diversity in LinksDetector
@pytest.mark.asyncio
async def test_source_diversity_submetric():
    detector = LinksDetector()
    
    # 3 distinct external domains -> 100
    html_3 = """
    <article>
        <p>Text referencing <a href="https://reuters.com/news">Reuters</a>, 
           <a href="https://bloomberg.com/market">Bloomberg</a>, and 
           <a href="https://techcrunch.com/article">TechCrunch</a>.</p>
    </article>
    """
    page_3 = make_page(html=html_3)
    res_3 = await detector.analyze(page_3)
    div_bd_3 = next(b for b in res_3.breakdown if b.name == "Source Diversity")
    assert div_bd_3.raw_score == 100.0

    # 2 distinct external domains -> 70
    html_2 = """
    <article>
        <p>Text referencing <a href="https://reuters.com/news">Reuters</a> and 
           <a href="https://bloomberg.com/market">Bloomberg</a>.</p>
    </article>
    """
    page_2 = make_page(html=html_2)
    res_2 = await detector.analyze(page_2)
    div_bd_2 = next(b for b in res_2.breakdown if b.name == "Source Diversity")
    assert div_bd_2.raw_score == 70.0

    # 1 distinct external domain -> 40
    html_1 = """
    <article>
        <p>Text referencing only <a href="https://reuters.com/news">Reuters</a>.</p>
    </article>
    """
    page_1 = make_page(html=html_1)
    res_1 = await detector.analyze(page_1)
    div_bd_1 = next(b for b in res_1.breakdown if b.name == "Source Diversity")
    assert div_bd_1.raw_score == 40.0


# 8. Title indicators check: review vs guide_blog (análisis should not trigger review)
def test_content_type_title_classification():
    # 1. Title with "Review of the iPhone 17" -> review
    html_review = """
    <html>
        <body>
            <article>
                <h1>Review of the iPhone 17</h1>
                <p>In-depth look at the performance, camera, and battery improvements.</p>
            </article>
        </body>
    </html>
    """
    page_review = make_page(html=html_review, url="https://example.com/gadgets/iphone-17")
    assert detect_content_type(page_review) == "review"

    # 2. Title with "Análisis de citas en AI Overviews" -> guide_blog (not review)
    html_analysis = """
    <html>
        <body>
            <article>
                <h1>Análisis de citas en AI Overviews</h1>
                <p>Estudio detallado sobre los factores de citabilidad e inclusión en motores de IA.</p>
            </article>
        </body>
    </html>
    """
    page_analysis = make_page(html=html_analysis, url="https://example.com/blog/analisis-citas")
    assert detect_content_type(page_analysis) == "guide_blog"

