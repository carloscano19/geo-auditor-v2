
import asyncio
from src.detectors.authority import AuthorityDetector
from src.models.schemas import PageData

async def test():
    print("Testing AuthorityDetector...")
    
    # 1. Test with Strong Signals
    # ---------------------------
    print("\n--- TEST CASE 1: Strong Signals ---")
    detector = AuthorityDetector()
    
    html_strong = """
    <html>
        <body>
            <div class="author">By <a href="/author/jane" rel="author">Jane Doe</a></div>
            <footer>
                <a href="/about-us">About Us</a>
                <a href="/contact">Contact</a>
                <a href="/privacy-policy">Privacy Policy</a>
            </footer>
        </body>
    </html>
    """
    
    text_strong = """
    The State of SEO in 2026.
    Written by Jane Doe.
    
    In my experience, analyzing over 500 sites, I found that...
    I tested this feature independently and discovered significant improvements.
    We also evaluated the competitors.
    """
    
    data_strong = PageData(
        url="http://test.com/strong",
        final_url="http://test.com/strong",
        html_raw=html_strong,
        html_rendered=html_strong,
        text_content=text_strong,
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_strong = await detector.analyze(data_strong)
    print(f"Score: {result_strong.score}/100")
    print("Breakdown:")
    for item in result_strong.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")
        
    # Assertions for Strong
    assert result_strong.score > 80, "Expected high score for strong signals"
    
    # 2. Test with Weak Signals
    # ---------------------------
    print("\n--- TEST CASE 2: Weak Signals ---")
    
    html_weak = "<html><body>Just content.</body></html>"
    text_weak = "This is a generic article about something. It is said that..."
    
    data_weak = PageData(
        url="http://test.com/weak",
        final_url="http://test.com/weak",
        html_raw=html_weak,
        html_rendered=html_weak,
        text_content=text_weak,
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_weak = await detector.analyze(data_weak)
    print(f"Score: {result_weak.score}/100")
    print("Breakdown:")
    for item in result_weak.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")

    # Assertions for Weak
    assert result_weak.score < 20, "Expected low score for weak signals"
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test())
