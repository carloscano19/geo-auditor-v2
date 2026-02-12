
import asyncio
from src.models.schemas import PageData
from src.detectors.metadata import MetadataDetector
from src.detectors.aeo_structure import AEOStructureDetector
from src.detectors.freshness import FreshnessDetector
from src.detectors.authority import AuthorityDetector
from src.utils.text_processing import extract_clean_text

async def test_mega_patch():
    print("=== MEGA PATCH VERIFICATION SUITE ===")
    
    # 1. Scraping Cleaning Test
    html_noisy = """
    <html>
        <nav><li>Home</li><li>Blog</li></nav>
        <header><div class="menu-container">Main Menu</div></header>
        <body>
            <div class="share-buttons">Twitter Facebook</div>
            <article>
                <h1>Main Content Title</h1>
                <p>This is the real content we want to analyze.</p>
            </article>
            <aside class="sidebar-advertisement">Buy now!</aside>
        </body>
        <footer>Contact Info</footer>
    </html>
    """
    clean_text = extract_clean_text(html_noisy)
    print(f"\n[1] Scraping Cleaning:")
    print(f"Cleaned Text: '{clean_text}'")
    if "Menu" not in clean_text and "Twitter" not in clean_text and "Contact" not in clean_text:
        print("✅ SUCCESS: Noise removed.")
    else:
        print("❌ FAILURE: Noise still present.")

    # 2. Freshness Regex Fallback
    html_no_meta = "<html><body><h1>News</h1><p>Published on February 6, 2026. Today we discuss...</p></body></html>"
    page_fresh = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_no_meta, html_rendered=html_no_meta, text_content="Published on February 6, 2026. Today we discuss...", platform_target="universal"
    )
    fresh_detector = FreshnessDetector()
    res_fresh = await fresh_detector.analyze(page_fresh)
    print(f"\n[2] Freshness Regex:")
    print(f"Score: {res_fresh.score} (Expected > 50 if date found via Regex)")
    
    # 3. Deep Authorship & Credential
    text_author_bottom = "This is a long article... " + ("filler " * 100) + "Ronnie McCluskey: Fan Tokens Market Reporter"
    page_auth = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<html></html>", html_rendered="<html></html>", text_content=text_author_bottom, platform_target="universal"
    )
    auth_detector = AuthorityDetector()
    res_auth = await auth_detector.analyze(page_auth)
    print(f"\n[3] Deep Authorship:")
    auth_breakdown = next(b for b in res_auth.breakdown if "Authorship" in b.name)
    print(f"Score: {auth_breakdown.raw_score} (Expected 100)")
    print(f"Explanation: {auth_breakdown.explanation}")

    # 4. Strict Trust (Basic vs High Value)
    html_basic_trust = '<html><body><a href="/privacy">Privacy</a> <a href="/terms">Terms</a></body></html>'
    page_basic = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_basic_trust, html_rendered=html_basic_trust, text_content="Privacy Terms", platform_target="universal"
    )
    res_basic = await auth_detector.analyze(page_basic)
    trust_breakdown = next(b for b in res_basic.breakdown if "Trust Pages" in b.name)
    print(f"\n[4] Strict Trust:")
    print(f"Basic Only Score: {trust_breakdown.raw_score} (Expected 40)")

    # 5. Schema RDFa-only
    html_rdfa = '<div vocab="http://schema.org/" typeof="Article"><span property="name">Title</span></div>'
    page_rdfa = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_rdfa, html_rendered=html_rdfa, text_content="Title", platform_target="universal"
    )
    meta_detector = MetadataDetector()
    res_meta = await meta_detector.analyze(page_rdfa)
    print(f"\n[5] Metadata RDFa-only:")
    presence_breakdown = next(b for b in res_meta.breakdown if "Presence" in b.name)
    print(f"Presence Score: {presence_breakdown.raw_score} (Expected 0)")

    # 6. AEO Storytelling
    text_story = "Once upon a time, there was a great business. In this article we are going to tell you how it grew. The answer is hard work."
    page_aeo = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<html></html>", html_rendered="<html></html>", text_content=text_story, platform_target="universal"
    )
    aeo_detector = AEOStructureDetector()
    res_aeo = await aeo_detector.analyze(page_aeo)
    rule_60 = next(b for b in res_aeo.breakdown if "Rule of 60" in b.name)
    print(f"\n[6] AEO Storytelling:")
    print(f"Rule 60 Score: {rule_60.raw_score} (Expected < 50)")

if __name__ == "__main__":
    asyncio.run(test_mega_patch())
