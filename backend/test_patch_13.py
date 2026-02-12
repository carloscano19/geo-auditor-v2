
import asyncio
from src.models.schemas import PageData
from src.detectors.evidence_density import EvidenceDensityDetector
from src.detectors.aeo_structure import AEOStructureDetector
from src.detectors.formatting import FormattingDetector

async def test_patch_13():
    print("=== PHASE 13 VERIFICATION SUITE ===")
    
    # 1. Evidence Neutrality (Empty Claims)
    page_empty = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw="<html></html>", html_rendered="<html></html>", text_content="Just some random words with no stats.", platform_target="universal"
    )
    ev_detector = EvidenceDensityDetector()
    res_ev = await ev_detector.analyze(page_empty)
    print(f"\n[1] Evidence Neutrality:")
    print(f"Score: {res_ev.score} (Expected 50.0)")

    # 2. Text Walls (AEO & Formatting)
    # 0 walls
    html_0_walls = "<html><body><p>Short paragraph.</p><p>Another short one.</p></body></html>"
    page_0 = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_0_walls, html_rendered=html_0_walls, text_content="Short paragraph. Another short one.", platform_target="universal"
    )
    # 2 walls (>500 words for AEO logic, but here we test the logic logic)
    text_long = "word " * 600
    html_2_walls = f"<html><body><p>{text_long}</p><h2>Mid Header</h2><p>{text_long}</p></body></html>"
    page_2 = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_2_walls, html_rendered=html_2_walls, text_content=text_long*2, platform_target="universal"
    )
    
    aeo_detector = AEOStructureDetector()
    fmt_detector = FormattingDetector()
    
    res_aeo_0 = await aeo_detector.analyze(page_0)
    res_aeo_2 = await aeo_detector.analyze(page_2)
    
    print(f"\n[2] Text Walls Scoring (AEO):")
    wall_0 = next(b for b in res_aeo_0.breakdown if "Text Walls" in b.name)
    wall_2 = next(b for b in res_aeo_2.breakdown if "Text Walls" in b.name)
    print(f"0 Walls Score: {wall_0.raw_score} (Expected 100)")
    print(f"2+ Walls Score: {wall_2.raw_score} (Expected 0)")

    # Formatting Walls (chars > 500)
    # To trigger lists check, we add a <ul>
    html_fmt_1 = "<html><body><ul><li>Item</li></ul><p>" + ("a" * 600) + "</p></body></html>"
    page_fmt_1 = PageData(
        url="http://test.com", final_url="http://test.com", status_code=200, load_time_ms=100,
        html_raw=html_fmt_1, html_rendered=html_fmt_1, text_content="Item. " + ("a" * 600), platform_target="universal"
    )
    res_fmt_1 = await fmt_detector.analyze(page_fmt_1)
    wall_fmt_1 = next(b for b in res_fmt_1.breakdown if "Lists/Tables" in b.name)
    print(f"\n[3] Text Walls Scoring (Formatting):")
    print(f"1 Wall Score: {wall_fmt_1.raw_score} (Expected 50)")

if __name__ == "__main__":
    asyncio.run(test_patch_13())
