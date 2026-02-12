import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import asyncio
from src.detectors.aeo_structure import AEOStructureDetector
from src.models.schemas import PageData

# Mock Content
LONG_SENTENCES_TEXT = "This is a very long sentence that goes on and on without any pause or break which makes it incredibly difficult for an artificial intelligence or even a human reader to follow the logic effectively because there are simply too many words packed into a single construct without adequate punctuation. " * 5

SHORT_SENTENCES_TEXT = "This is short. Ideally under 20 words. AI loves this. It is clear. It is concise."

NO_CONNECTORS_TEXT = "I went to the store. I bought milk. I came home. It was raining. I got wet."

MANY_CONNECTORS_TEXT = "I went to the store; however, it was closed. Therefore, I went to another one. Because it was raining, I took an umbrella. Consequently, I stayed dry."

GENERIC_HEADERS_HTML = """
<html>
<body>
    <h1>Title</h1>
    <p>Intro...</p>
    <h2>Introduction</h2>
    <p>Content...</p>
    <h2>Conclusion</h2>
    <p>End...</p>
</body>
</html>
"""

GOOD_HEADERS_HTML = """
<html>
<body>
    <h1>Title</h1>
    <p>Intro...</p>
    <h2>Bitcoin History</h2>
    <p>Content...</p>
    <h2>SEO Strategy Conclusion</h2>
    <p>End...</p>
</body>
</html>
"""

@pytest.mark.asyncio
async def test_sentence_length():
    print("\n--- Testing Sentence Length ---")
    detector = AEOStructureDetector()
    
    # Test Long Sentences
    res_long, avg = detector._analyze_sentence_length(LONG_SENTENCES_TEXT)
    print(f"Long Text Score: {res_long.raw_score} (Expected < 50)")
    assert res_long.raw_score < 50
    assert "Simplify sentences" in res_long.recommendations[0]

    # Test Short Sentences
    res_short, avg = detector._analyze_sentence_length(SHORT_SENTENCES_TEXT)
    print(f"Short Text Score: {res_short.raw_score} (Expected > 80)")
    assert res_short.raw_score >= 80

@pytest.mark.asyncio
async def test_logical_connectors():
    print("\n--- Testing Logical Connectors ---")
    detector = AEOStructureDetector()
    
    # Test No Connectors
    res_none, count = detector._analyze_logical_connectors(NO_CONNECTORS_TEXT)
    print(f"No Connectors Score: {res_none.raw_score} (Expected <= 20)")
    assert res_none.raw_score <= 20
    assert "Use logical connectors" in res_none.recommendations[0]

    # Test Many Connectors
    res_many, count = detector._analyze_logical_connectors(MANY_CONNECTORS_TEXT)
    print(f"Many Connectors Score: {res_many.raw_score} (Expected 100)")
    assert res_many.raw_score == 100

@pytest.mark.asyncio
async def test_generic_headers():
    print("\n--- Testing Generic Headers ---")
    detector = AEOStructureDetector()
    
    # Test Generic Headers
    bad_headers = ['Introduction', 'Conclusion', 'Summary']
    res_bad = detector._analyze_generic_headers(bad_headers)
    print(f"Bad Headers Score: {res_bad.raw_score} (Expected 0)")
    assert res_bad.raw_score == 0
    assert "Avoid generic headers" in res_bad.recommendations[0]

    # Test Good Headers
    good_headers = ['Bitcoin History', 'SEO Strategy Conclusion']
    res_good = detector._analyze_generic_headers(good_headers)
    print(f"Good Headers Score: {res_good.raw_score} (Expected 100)")
    assert res_good.raw_score == 100

@pytest.mark.asyncio
async def test_robustness():
    print("\n--- Testing Robustness (No Crash) ---")
    detector = AEOStructureDetector()
    
    # Empty Page Data
    empty_data = PageData(
        url="http://test.local",
        final_url="http://test.local",
        html_raw="",
        html_rendered="",
        text_content="",
        status_code=200,
        load_time_ms=100.0
    )
    
    # Should not raise exception
    try:
        result = await detector.analyze(empty_data)
        print("Empty Analysis Result:", result.debug_info)
        assert result.score is not None
        assert "structure_metrics" in result.debug_info
    except Exception as e:
        pytest.fail(f"Detector crashed on empty input: {e}")

if __name__ == "__main__":
    asyncio.run(test_sentence_length())
    asyncio.run(test_logical_connectors())
    asyncio.run(test_generic_headers())
    asyncio.run(test_robustness())
    print("\nAll readability tests passed!")
