
import asyncio
from src.detectors.freshness import FreshnessDetector
from src.models.schemas import PageData

async def test():
    print("Testing FreshnessDetector...")
    
    # 1. Test FRESH Content (2026)
    # ---------------------------
    print("\n--- TEST CASE 1: Fresh Content ---")
    detector = FreshnessDetector()
    
    # Simulate content published "today" (Feb 6 2026 in our mock)
    html_fresh = """
    <html>
        <head>
            <title>SEO Strategies for 2026</title>
            <meta property="article:published_time" content="2026-02-01T10:00:00Z" />
        </head>
        <body>
            <h1>Ultimate Guide 2026</h1>
        </body>
    </html>
    """
    
    data_fresh = PageData(
        url="http://test.com/fresh",
        final_url="http://test.com/fresh",
        html_raw=html_fresh,
        html_rendered=html_fresh,
        text_content="Content...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_fresh = await detector.analyze(data_fresh)
    print(f"Score: {result_fresh.score}/100")
    print("Breakdown:")
    for item in result_fresh.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")
        
    assert result_fresh.score > 90, "Expected high score for fresh content"
    
    # 2. Test STALE Content (2023)
    # ---------------------------
    print("\n--- TEST CASE 2: Stale Content ---")
    
    html_stale = """
    <html>
        <head>
            <title>SEO Strategies for 2023</title>
            <meta property="article:published_time" content="2023-01-01" />
        </head>
        <body>
            <h1>Guide 2023</h1>
        </body>
    </html>
    """
    
    data_stale = PageData(
        url="http://test.com/stale",
        final_url="http://test.com/stale",
        html_raw=html_stale,
        html_rendered=html_stale,
        text_content="...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_stale = await detector.analyze(data_stale)
    print(f"Score: {result_stale.score}/100")
    print("Breakdown:")
    for item in result_stale.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")

    assert result_stale.score < 20, "Expected low score for old content"
    
    # 3. Test UNDATED Content
    # ---------------------------
    print("\n--- TEST CASE 3: Undated Content ---")
    
    html_undated = "<html><body>Just content.</body></html>"
    
    data_undated = PageData(
        url="http://test.com/undated",
        final_url="http://test.com/undated",
        html_raw=html_undated,
        html_rendered=html_undated,
        text_content="...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_undated = await detector.analyze(data_undated)
    print(f"Score: {result_undated.score}/100")

    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test())
