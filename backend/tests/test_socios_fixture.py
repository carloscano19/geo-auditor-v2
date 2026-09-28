"""
Tests for the socios_securitize.html fixture, verifying that extract_main_content
correctly identifies the article body (not a blog-card <article>).
"""
import os
import pytest
from src.utils.text_processing import extract_main_content

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "socios_securitize.html")


@pytest.fixture(scope="module")
def socios_html():
    """Load the socios.com/securitize article fixture once per module."""
    if not os.path.exists(FIXTURE_PATH):
        pytest.skip(f"Fixture not found: {FIXTURE_PATH}")
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_socios_extract_word_count(socios_html):
    """
    extract_main_content must return >500 words for the Socios/Securitize article.
    The page has ~700 words of body text; previously it returned only 51 words
    because it selected a related-post blog-card <article> instead of the
    entry-content div.
    """
    _, text = extract_main_content(socios_html)
    words = len(text.split())
    assert words > 500, (
        f"Expected >500 words but got {words}. "
        "extract_main_content is likely selecting a blog-card article instead of the body."
    )


def test_socios_extract_contains_dreyfus(socios_html):
    """
    The article body mentions CEO 'Alexandre Dreyfus'.
    If the wrong container is chosen, this string will be absent.
    """
    _, text = extract_main_content(socios_html)
    assert "Alexandre Dreyfus" in text, (
        "'Alexandre Dreyfus' not found in extracted text. "
        "Likely extracting the wrong container."
    )


def test_socios_extract_contains_about_securitize(socios_html):
    """
    The article includes an 'About Securitize' section header.
    If the wrong container is chosen, this heading will be absent.
    """
    _, text = extract_main_content(socios_html)
    assert "About Securitize" in text, (
        "'About Securitize' not found in extracted text. "
        "Likely extracting the wrong container."
    )


def test_socios_extract_contains_external_links(socios_html):
    """
    The article body contains links to forbes.com and cnbc.com.
    These must be present in the extracted HTML.
    """
    scoped_html, _ = extract_main_content(socios_html)
    assert "forbes.com" in scoped_html, (
        "forbes.com link not found in extracted HTML."
    )
    assert "cnbc.com" in scoped_html, (
        "cnbc.com link not found in extracted HTML."
    )
