"""
Tests for Bilingual (English / Spanish) Support.

Validates that language detection works seamlessly and that
evidence, authorship, experience, dates, and interrogative H2s
are properly detected in both English and Spanish.
"""

import pytest
from datetime import datetime, timezone
from src.models.schemas import PageData
from src.utils.lang_patterns import (
    detect_language,
    is_interrogative_h2,
    parse_date_string,
    get_lang_patterns,
    resolve_language,
)
from src.detectors.evidence_density import EvidenceDensityDetector
from src.detectors.authority import AuthorityDetector
from src.detectors.freshness import FreshnessDetector
from src.detectors.aeo_structure import AEOStructureDetector
from src.detectors.entity import EntityDetector


def create_page_data(
    text: str,
    html: str = "",
    h1: str = "",
    h2s: list[str] = None,
    language: str = None
) -> PageData:
    h2_markup = "".join(f"<h2>{h}</h2>" for h in (h2s or []))
    title_markup = f"<h1>{h1}</h1>" if h1 else ""
    full_html = html or f"<html><body>{title_markup}{h2_markup}<p>{text}</p></body></html>"
    
    data = PageData(
        url="https://test.local",
        final_url="https://test.local",
        html_raw=full_html,
        html_rendered=full_html,
        text_content=text,
        status_code=200,
        load_time_ms=100.0,
        word_count=len(text.split()),
        is_https=True,
        is_ssr=True,
        ttfb_ms=200.0,
    )
    if language:
        data.language = language
    return data


# --- 1. Language Detection Tests ---
def test_detect_language():
    en_sample = "This is a comprehensive study about search engine optimization and large language models."
    es_sample = "Este es un estudio exhaustivo sobre la optimización para motores de respuesta y modelos de lenguaje."
    
    assert detect_language(en_sample) == "en"
    assert detect_language(es_sample) == "es"
    assert detect_language("") == "en"
    assert detect_language("Hello") == "en"


# --- 2. Evidence Density in English and Spanish ---
@pytest.mark.asyncio
async def test_evidence_density_english():
    detector = EvidenceDensityDetector()
    en_text = (
        "According to a 2026 report by TechCorp, cloud spending increased by 35% this quarter. "
        "The survey shows that over 5 million developers actively use the platform daily."
    )
    en_html = (
        f"<p>{en_text} <a href='https://example.com/source'>[Source]</a></p>"
    )
    page_en = create_page_data(text=en_text, html=en_html)
    assert resolve_language(page_en) == "en"
    
    res_en = await detector.analyze(page_en)
    assert res_en.score > 50.0
    mapping = next(b for b in res_en.breakdown if b.name in ("Evidence Density", "Evidence Mapping"))
    assert mapping.raw_score >= 60.0


@pytest.mark.asyncio
async def test_evidence_density_spanish():
    detector = EvidenceDensityDetector()
    es_text = (
        "Según un estudio de 2026 realizado por Gartner, la adopción de IA creció un 40% este año. "
        "Los datos muestran que más de 3 millones de usuarios utilizan la plataforma activamente."
    )
    es_html = (
        f"<p>{es_text} <a href='https://example.com/fuente'>[Fuente]</a></p>"
    )
    page_es = create_page_data(text=es_text, html=es_html)
    assert resolve_language(page_es) == "es"
    
    res_es = await detector.analyze(page_es)
    assert res_es.score > 50.0
    mapping = next(b for b in res_es.breakdown if b.name in ("Evidence Density", "Evidence Mapping"))
    assert mapping.raw_score >= 60.0


# --- 3. Authority and Experience in English and Spanish ---
@pytest.mark.asyncio
async def test_authority_english():
    detector = AuthorityDetector()
    en_text = (
        "Written by Alice Smith for our research team. "
        "We tested the new architecture and we found significant performance gains. "
        "In our experience, latency dropped substantially."
    )
    page_en = create_page_data(text=en_text)
    res_en = await detector.analyze(page_en)
    
    auth_breakdown = next(b for b in res_en.breakdown if b.name == "Authorship Verification")
    exp_breakdown = next(b for b in res_en.breakdown if b.name == "Experience Signals")
    
    assert auth_breakdown.raw_score == 100.0
    assert exp_breakdown.raw_score >= 60.0


@pytest.mark.asyncio
async def test_authority_spanish():
    detector = AuthorityDetector()
    es_text = (
        "Artículo escrito por Carlos Cano para el equipo de análisis. "
        "Hemos probado la nueva arquitectura y comprobamos mejoras significativas. "
        "En nuestra experiencia, los tiempos de respuesta se redujeron notablemente."
    )
    page_es = create_page_data(text=es_text)
    res_es = await detector.analyze(page_es)
    
    auth_breakdown = next(b for b in res_es.breakdown if b.name == "Authorship Verification")
    exp_breakdown = next(b for b in res_es.breakdown if b.name == "Experience Signals")
    
    assert auth_breakdown.raw_score == 100.0
    assert exp_breakdown.raw_score >= 60.0


@pytest.mark.asyncio
async def test_authorship_negative_cases():
    detector = AuthorityDetector()
    
    # Negative EN case
    text_en_neg = "The results were achieved by using this method in production."
    page_en = create_page_data(text=text_en_neg)
    res_en = await detector.analyze(page_en)
    auth_en = next(b for b in res_en.breakdown if b.name == "Authorship Verification")
    assert auth_en.raw_score == 0.0

    # Negative ES case
    text_es_neg = "Por ejemplo, por tanto las páginas mejoran por completo su rendimiento."
    page_es = create_page_data(text=text_es_neg)
    res_es = await detector.analyze(page_es)
    auth_es = next(b for b in res_es.breakdown if b.name == "Authorship Verification")
    assert auth_es.raw_score == 0.0


@pytest.mark.asyncio
async def test_authorship_positive_spanish_por():
    detector = AuthorityDetector()
    text_es_pos = "Guía completa de auditoría web. Por María López en nuestro blog de tecnología."
    page_es = create_page_data(text=text_es_pos)
    res_es = await detector.analyze(page_es)
    auth_es = next(b for b in res_es.breakdown if b.name == "Authorship Verification")
    assert auth_es.raw_score == 100.0


# --- 4. Date Extraction and Freshness in English and Spanish ---
def test_date_parsing_bilingual():
    # Spanish date
    date_es = parse_date_string("24 de septiembre de 2026", lang="es")
    assert date_es is not None
    assert date_es.year == 2026
    assert date_es.month == 9
    assert date_es.day == 24

    # Spanish date with 'del'
    date_es_del = parse_date_string("15 de enero del 2026", lang="es")
    assert date_es_del is not None
    assert date_es_del.year == 2026
    assert date_es_del.month == 1
    assert date_es_del.day == 15

    # English date
    date_en = parse_date_string("September 24, 2026", lang="en")
    assert date_en is not None
    assert date_en.year == 2026
    assert date_en.month == 9
    assert date_en.day == 24


@pytest.mark.asyncio
async def test_freshness_spanish_visual_date():
    detector = FreshnessDetector()
    current_year = datetime.now(timezone.utc).year
    es_text = f"Publicado el 24 de septiembre de {current_year}. Guía completa de auditoría."
    page_es = create_page_data(
        text=es_text,
        h1=f"Guía SEO {current_year}"
    )
    res_es = await detector.analyze(page_es)
    date_breakdown = next(b for b in res_es.breakdown if b.name == "Date Currency")
    assert date_breakdown.raw_score == 100.0


# --- 5. Interrogative H2s in English and Spanish ---
def test_interrogative_h2_detection():
    # English questions
    assert is_interrogative_h2("What is Answer Engine Optimization?")
    assert is_interrogative_h2("How to optimize content for LLMs")
    assert is_interrogative_h2("Why does latency matter for crawlers")
    assert not is_interrogative_h2("Technical Infrastructure Overview")

    # Spanish questions
    assert is_interrogative_h2("¿Cómo optimizar el contenido para IA?")
    assert is_interrogative_h2("Cómo mejorar la citabilidad web")
    assert is_interrogative_h2("Qué es el Answer Engine Optimization")
    assert is_interrogative_h2("Por qué es importante la velocidad")
    assert is_interrogative_h2("Por que elegir esta plataforma")
    assert is_interrogative_h2("Cuál es la mejor solución")
    assert not is_interrogative_h2("Introducción a la plataforma")
    assert not is_interrogative_h2("Resumen del proyecto")


@pytest.mark.asyncio
async def test_aeo_structure_spanish():
    detector = AEOStructureDetector()
    es_text = (
        "GEO Auditor es una herramienta diseñada para optimizar páginas web para citabilidad en IA. "
        "Por tanto, los creadores de contenido pueden entender cómo los motores de búsqueda citan sus fuentes. "
        "Sin embargo, muchas páginas web no cuentan con la estructura necesaria. "
        "Además, un estudio reciente muestra que la claridad semántica es decisiva."
    )
    page_es = create_page_data(
        text=es_text,
        h1="Optimización GEO en 2026",
        h2s=[
            "¿Cómo funciona la citabilidad en IA?",
            "Por qué es importante la optimización",
            "Métricas clave de evaluación"
        ]
    )
    res_es = await detector.analyze(page_es)
    h2_breakdown = next(b for b in res_es.breakdown if b.name == "Interrogative H2s")
    assert h2_breakdown.raw_score == 100.0  # 2 out of 3 = 66% >= 30% threshold
    
    conn_breakdown = next(b for b in res_es.breakdown if b.name == "Logical Connectors")
    assert conn_breakdown.raw_score == 100.0  # por tanto, sin embargo, además >= 3
