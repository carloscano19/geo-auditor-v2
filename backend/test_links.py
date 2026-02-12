
import asyncio
from src.detectors.links import LinksDetector
from src.models.schemas import PageData

async def test():
    print("Testing LinksDetector...")
    
    # 1. Test HIGH Authority
    # ---------------------------
    print("\n--- TEST CASE 1: High Authority ---")
    detector = LinksDetector()
    
    html_high = """
    <html>
        <body>
            <p>Read more on <a href="https://wikipedia.org/wiki/SEO">Wikipedia</a></p>
            <p>Data from <a href="https://www.cdc.gov/data">CDC.gov</a></p>
            <p>Check our <a href="/blog/post1">internal post</a>.</p>
             <p>Check <a href="https://test.com/about">Internal Absolute</a>.</p>
             <p>Another <a href="https://google.com">external link</a>.</p>
        </body>
    </html>
    """
    
    data_high = PageData(
        url="https://test.com/page",
        final_url="https://test.com/page",
        html_raw=html_high,
        html_rendered=html_high,
        text_content="...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_high = await detector.analyze(data_high)
    print(f"Score: {result_high.score}/100")
    print("Breakdown:")
    for item in result_high.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")
        
    assert result_high.score > 90, "Expected high score for authority links"
    
    # 2. Test LOW Authority / No External
    # ---------------------------
    print("\n--- TEST CASE 2: Low Authority ---")
    
    html_low = """
    <html>
        <body>
            <a href="/internal1">Internal 1</a>
            <a href="https://unknown-blog.com/post">Some blog</a>
        </body>
    </html>
    """
    
    data_low = PageData(
        url="https://test.com/page2",
        final_url="https://test.com/page2",
        html_raw=html_low,
        html_rendered=html_low,
        text_content="...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_low = await detector.analyze(data_low)
    print(f"Score: {result_low.score}/100")
    print("Breakdown:")
    for item in result_low.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")

    assert result_low.score < 50, "Expected low score for weak links"
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test())
