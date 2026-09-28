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


def test_elementor_multi_section_article():
    """
    Test an Elementor-style article layout:
    div.wrapper containing 3 div.section, each with an H2, 2 long paragraphs,
    and a 4-item list, plus an external promo banner and nav.
    The chosen container must be div.wrapper (containing all 3 sections),
    not a single div.section.
    """
    html = """
    <html>
      <body>
        <div class="banner">
          <p>Important global announcement banner outside main content.</p>
        </div>
        <nav>
          <ul>
            <li><a href="/">Home</a></li>
            <li><a href="/blog">Blog</a></li>
            <li><a href="/contact">Contact</a></li>
          </ul>
        </nav>
        <div class="wrapper">
          <div class="section">
            <h2>Section One: Generative Architecture</h2>
            <p>First substantive paragraph in section one explaining technical infrastructure and crawler access protocols for AI search engines in detail.</p>
            <p>Second substantive paragraph in section one providing further operational recommendations and architectural blueprints.</p>
            <ul>
              <li>Technical factor alpha</li>
              <li>Technical factor beta</li>
              <li>Technical factor gamma</li>
              <li>Technical factor delta</li>
            </ul>
          </div>
          <div class="section">
            <h2>Section Two: Citability Mechanics</h2>
            <p>First substantive paragraph in section two detailing claims extraction density and evidence linkage patterns across knowledge graphs.</p>
            <p>Second substantive paragraph in section two demonstrating verifiable factual statements and consensus checking algorithms.</p>
            <ul>
              <li>Citability signal one</li>
              <li>Citability signal two</li>
              <li>Citability signal three</li>
              <li>Citability signal four</li>
            </ul>
          </div>
          <div class="section">
            <h2>Section Three: Optimization Strategy</h2>
            <p>First substantive paragraph in section three presenting structured implementation steps for digital marketing and content teams.</p>
            <p>Second substantive paragraph in section three summarizing longitudinal performance tracking and generative engine auditing.</p>
            <ul>
              <li>Strategy item first</li>
              <li>Strategy item second</li>
              <li>Strategy item third</li>
              <li>Strategy item fourth</li>
            </ul>
          </div>
        </div>
      </body>
    </html>
    """
    _, text = extract_main_content(html)

    # All 3 sections must be included (wrapper chosen, not a single section)
    assert "Section One: Generative Architecture" in text
    assert "Section Two: Citability Mechanics" in text
    assert "Section Three: Optimization Strategy" in text
    assert "Technical factor alpha" in text
    assert "Citability signal one" in text
    assert "Strategy item first" in text

    # External banner and nav must NOT be present
    assert "Important global announcement banner outside" not in text


def test_article_with_many_lists():
    """
    Test an article with multiple long lists:
    div.post containing 2 paragraphs and 3 long lists.
    Since lists (li) count as content text, div.post must be chosen in its entirety.
    """
    html = """
    <html>
      <body>
        <div class="banner">
          <p>Quick site notification alert.</p>
        </div>
        <div class="post">
          <h1>Comprehensive Checklist for AI Optimization</h1>
          <p>Introductory paragraph describing the scope of this checklist and how practitioners can apply it across large web platforms.</p>
          <ul>
            <li>Prerequisite audit of robots.txt for AI search bots</li>
            <li>Verification of server-side rendering and hydration consistency</li>
            <li>Assessment of Time to First Byte and Core Web Vitals</li>
            <li>Validation of JSON-LD Schema against Schema.org standards</li>
            <li>Inspection of canonical headers and protocol redirection</li>
          </ul>
          <p>Intermediary transition paragraph discussing content formatting and information extraction heuristics.</p>
          <ol>
            <li>Structure passages with clear declarative topic sentences</li>
            <li>Embed specific numerical claims backed by authoritative sources</li>
            <li>Maintain high entity density throughout descriptive sections</li>
            <li>Format comparative data into accessible HTML tables</li>
          </ol>
          <ul>
            <li>Follow-up analysis of brand mention consensus</li>
            <li>Evaluation of secondary citation channels</li>
            <li>Monitoring of search share across leading generative engines</li>
          </ul>
        </div>
      </body>
    </html>
    """
    _, text = extract_main_content(html)

    # All parts of div.post must be present
    assert "Comprehensive Checklist for AI Optimization" in text
    assert "Prerequisite audit of robots.txt" in text
    assert "Structure passages with clear declarative" in text
    assert "Follow-up analysis of brand mention" in text

    # External banner must not be present
    assert "Quick site notification alert" not in text

