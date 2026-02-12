
import asyncio
from src.detectors.formatting import FormattingDetector
from src.models.schemas import PageData

async def test():
    print("Testing FormattingDetector (Visual UX)...")
    
    # 1. Test with Good Formatting
    # ---------------------------
    print("\n--- TEST CASE 1: Good Formatting ---")
    detector = FormattingDetector()
    
    html_good = """
    <html>
        <body>
            <p>Here is a list of features:</p>
            <ul>
                <li>Feature 1</li>
                <li>Feature 2</li>
            </ul>
            <p>Ensure you use <strong>bold keywords</strong> for emphasis.</p>
            <img src="test.jpg" alt="A test image" />
        </body>
    </html>
    """
    
    data_good = PageData(
        url="http://test.com/good",
        final_url="http://test.com/good",
        html_raw=html_good,
        html_rendered=html_good,
        text_content="Here is a list...",
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_good = await detector.analyze(data_good)
    print(f"Score: {result_good.score}/100")
    print("Breakdown:")
    for item in result_good.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")
        
    assert result_good.score > 80, "Expected high score for good formatting"
    
    # 2. Test with Text Wall (Bad)
    # ---------------------------
    print("\n--- TEST CASE 2: Text Wall ---")
    
    long_text = "word " * 100 # 100 words > 80 words threshold approx
    html_bad = f"""
    <html>
        <body>
            <p>{long_text}</p>
            <p>Another paragraph.</p>
        </body>
    </html>
    """
    
    data_bad = PageData(
        url="http://test.com/bad",
        final_url="http://test.com/bad",
        html_raw=html_bad,
        html_rendered=html_bad,
        text_content=long_text,
        status_code=200,
        load_time_ms=100,
        word_count=500,
        is_ssr=True,
        is_https=True
    )
    
    result_bad = await detector.analyze(data_bad)
    print(f"Score: {result_bad.score}/100")
    print("Breakdown:")
    for item in result_bad.breakdown:
        print(f"  - {item.name}: {item.raw_score} ({item.explanation})")

    assert result_bad.score < 50, "Expected low score for text wall"
    
    # 3. Test with Over-Bolding (Bad)
    # ---------------------------
    print("\n--- TEST CASE 3: Over-Bolding ---")
    
    html_bold = """
    <html>
        <body>
            <p><strong>This entire paragraph is bolded and it is very long and annoying to read because everything is highlighted.</strong></p>
        </body>
    </html>
    """
    
    data_bold = PageData(
        url="http://test.com/bold",
        final_url="http://test.com/bold",
        html_raw=html_bold,
        html_rendered=html_bold,
        text_content="...",
        status_code=200,
        load_time_ms=100,
        word_count=50,
        is_ssr=True,
        is_https=True
    )
    
    result_bold = await detector.analyze(data_bold)
    print(f"Score: {result_bold.score}/100")
    print("Breakdown:")
    for item in result_bold.breakdown:
        if item.name == "Bold Highlights":
            print(f"  - {item.name}: {item.raw_score} ({item.explanation})")
            assert item.raw_score < 50, "Expected low score for over-bolding"

    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test())
