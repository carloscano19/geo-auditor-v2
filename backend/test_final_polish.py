
import asyncio
from src.models.schemas import PageData
from src.detectors.authority import AuthorityDetector
from src.detectors.formatting import FormattingDetector
from src.detectors.aeo_structure import AEOStructureDetector

async def test_final_polish():
    print("=== PHASE 14 FINAL POLISH VERIFICATION ===")
    
    # 1. Authorship Strictness
    auth_detector = AuthorityDetector()
    page_faulty_auth = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<html>By expanding our reach...</html>", html_rendered="<html>By expanding our reach...</html>", 
        text_content="By expanding our reach, we found that...", platform_target="universal"
    )
    res_auth_faulty = await auth_detector.analyze(page_faulty_auth)
    print(f"\n[1] Authorship (False Positive Check):")
    print(f"'By expanding' Score: {res_auth_faulty.score} (Expected 0.0)")

    page_good_auth = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<html>By John Doe</html>", html_rendered="<html>By John Doe</html>", 
        text_content="By John Doe", platform_target="universal"
    )
    res_auth_good = await auth_detector.analyze(page_good_auth)
    print(f"'By John Doe' Score: {res_auth_good.score} (Expected >0)")

    # 2. Formatting (Menu Filtering)
    fmt_detector = FormattingDetector()
    html_menu = '<html><body><ul class="nav-menu"><li>Home</li><li>About</li></ul><p>Some text content</p></body></html>'
    page_menu = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_menu, html_rendered=html_menu, text_content="Home About Some text content", platform_target="universal"
    )
    res_fmt_menu = await fmt_detector.analyze(page_menu)
    list_breakdown = next(b for b in res_fmt_menu.breakdown if "Lists/Tables" in b.name)
    print(f"\n[2] Formatting (Menu Filtering):")
    print(f"Menu-only List Count: {res_fmt_menu.score} (Expected low score if only menus present)")

    # 3. AEO (Rule of 60 Strictness)
    aeo_detector = AEOStructureDetector()
    # Temporal start
    page_temporal = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<h1>SEO Guide</h1><p>Yesterday, we saw a change in trends...</p>", 
        html_rendered="<h1>SEO Guide</h1><p>Yesterday, we saw a change in trends...</p>", 
        text_content="SEO Guide. Yesterday, we saw a change in trends...", platform_target="universal"
    )
    res_aeo_temporal = await aeo_detector.analyze(page_temporal)
    rule_60 = next(b for b in res_aeo_temporal.breakdown if "Rule of 60" in b.name)
    print(f"\n[3] AEO (Rule of 60 Temporal):")
    print(f"Temporal Intro Score: {rule_60.raw_score} (Expected 40.0)")

    # Copulative/Entity start
    page_perfect = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<h1>SEO Guide</h1><p>SEO is the process of optimizing websites...</p>", 
        html_rendered="<h1>SEO Guide</h1><p>SEO is the process of optimizing websites...</p>", 
        text_content="SEO Guide. SEO is the process of optimizing websites...", platform_target="universal"
    )
    res_aeo_perfect = await aeo_detector.analyze(page_perfect)
    rule_60_p = next(b for b in res_aeo_perfect.breakdown if "Rule of 60" in b.name)
    print(f"Perfect Intro Score: {rule_60_p.raw_score} (Expected 100.0 or high)")

if __name__ == "__main__":
    asyncio.run(test_final_polish())
