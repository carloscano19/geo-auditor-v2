"""
Tests for the socios_securitize.html fixture, verifying that extract_main_content
correctly identifies the article body (not a blog-card <article> or a site wrapper).
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


# ---------------------------------------------------------------------------
# Existing tests (kept intact)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# New tests: site-wrapper noise must NOT appear in extracted text
# ---------------------------------------------------------------------------

def test_socios_no_nav_boilerplate(socios_html):
    """
    The extracted text must NOT contain navigation/header boilerplate that
    belongs to the site shell (div#page wrapper) rather than the article body.
    These strings appear in the nav, header and related-post sections.
    """
    _, text = extract_main_content(socios_html)
    boilerplate_phrases = [
        "Get Updates",
        "How it Works",
        "Skip to content",
        "Palermo F.C. joins",
        "Italiano",         # language switcher
        "Português",        # language switcher
    ]
    for phrase in boilerplate_phrases:
        assert phrase not in text, (
            f"Boilerplate phrase '{phrase}' found in extracted text. "
            "_densest_block is likely selecting the outer site wrapper instead of the article body."
        )


def test_socios_lead_paragraph_near_start(socios_html):
    """
    The article opens with the partnership announcement.  The first 30 words of
    the extracted text must contain 'Partnership combines' or 'Securitize',
    confirming that the extracted container starts at the article body and not
    at the site-wide navigation or header.
    """
    _, text = extract_main_content(socios_html)
    first_30 = " ".join(text.split()[:30])
    assert "Partnership combines" in first_30 or "Securitize" in first_30, (
        f"Expected article lead in first 30 words but got: {first_30!r}. "
        "The extractor is likely starting from a site wrapper instead of the article body."
    )


# ---------------------------------------------------------------------------
# Generic synthetic test: innermost dense block is preferred
# ---------------------------------------------------------------------------

def test_densest_block_picks_innermost_content_div():
    """
    Regression test for _densest_block selecting the innermost block.

    HTML structure:
      div#page (outermost)
        ├── div.banner  — one short <p> (banner/hero blurb)
        ├── nav         — no <p>
        └── div.content — six long article paragraphs (the real content)

    Before the fix, _densest_block picked div#page because it accumulated all
    its children's paragraph text.  After the fix it must pick div.content,
    which has ≥ 85 % of the max p-text with the smallest total text footprint.
    """
    long_para = (
        "This is a substantive paragraph about generative engine optimization "
        "strategies that should be extracted as part of the main article body. "
        "It contains enough words to be counted as meaningful content."
    )
    html = f"""
    <html>
      <body>
        <div id="page">
          <div class="banner">
            <p>Latest news: short promo blurb here.</p>
          </div>
          <nav>
            <ul><li>Home</li><li>Blog</li><li>About</li></ul>
          </nav>
          <div class="content">
            <h1>Main Article Title</h1>
            <p>{long_para}</p>
            <p>{long_para}</p>
            <p>{long_para}</p>
            <p>{long_para}</p>
            <p>{long_para}</p>
            <p>{long_para}</p>
          </div>
        </div>
      </body>
    </html>
    """
    _, text = extract_main_content(html)
    # Article content must be present
    assert "Main Article Title" in text, "H1 of article not found in extracted text."
    assert "generative engine optimization" in text, "Article body text not found."
    # Navigation noise must NOT be present
    assert "Latest news: short promo blurb here" not in text, (
        "Banner <p> should not appear — the innermost dense block (div.content) "
        "does not include the banner."
    )
