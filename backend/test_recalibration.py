
import asyncio
from src.models.schemas import PageData
from src.detectors.metadata import MetadataDetector
from src.detectors.aeo_structure import AEOStructureDetector

async def test_recalibration():
    # Test 1: Weak Schema (RDFa only, no Critical Types)
    html_weak = """
    <html>
        <head><title>Test</title></head>
        <body vocab="http://schema.org/">
            <div typeof="Thing">
                <span property="name">Just a Thing</span>
            </div>
        </body>
    </html>
    """
    page_weak = PageData(
        url="http://test.com", 
        final_url="http://test.com",
        status_code=200,
        load_time_ms=100,
        html_raw=html_weak, 
        html_rendered=html_weak, 
        text_content="Just a Thing", 
        platform_target="universal"
    )
    
    meta_detector = MetadataDetector()
    res_meta = await meta_detector.analyze(page_weak)
    print(f"\n--- Metadata Strict Test (No Critical, No JSON-LD) ---")
    print(f"Score: {res_meta.score} (Expected <= 30)")
    for b in res_meta.breakdown:
        print(f" - {b.name}: {b.raw_score}")
        if b.recommendations:
            print(f"    Recs: {b.recommendations}")

    # Test 2: Rule of 60 without H1 keywords
    html_aeo = """
    <html>
        <body>
            <h1>Geopolitical Audit Tool</h1>
            <p>Welcome to our professional platform. We are going to explore some features today that are very important for your business success and growth.</p>
        </body>
    </html>
    """
    text_aeo = "Welcome to our professional platform. We are going to explore some features today that are very important for your business success and growth."
    page_aeo = PageData(
        url="http://test.com", 
        final_url="http://test.com",
        status_code=200,
        load_time_ms=100,
        html_raw=html_aeo, 
        html_rendered=html_aeo, 
        text_content=text_aeo, 
        platform_target="universal"
    )
    
    aeo_detector = AEOStructureDetector()
    res_aeo = await aeo_detector.analyze(page_aeo)
    print(f"\n--- AEO Semantic Test (Missing H1 Keywords) ---")
    rule_60 = next(b for b in res_aeo.breakdown if "Rule of 60" in b.name)
    print(f"Rule of 60 Score: {rule_60.raw_score} (Expected < 80 due to fluff + missing H1 context)")
    print(f"Explanation: {rule_60.explanation}")

if __name__ == "__main__":
    asyncio.run(test_recalibration())
