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
async def test_rule_of_60():
    print("\n--- Testing Rule of 60 ---")
    detector = AEOStructureDetector()
    
    # Test without narrative filler (direct answer)
    direct_text = "Vector search uses dense embeddings to find semantically similar documents in multi-dimensional space."
    res_direct = detector._analyze_rule_of_60(direct_text)
    assert res_direct.raw_score == 100.0
    assert "Direct Answer" in res_direct.explanation

    # Test with narrative filler
    filler_text = "In today's fast-paced world, finding information quickly has become more important than ever before."
    res_filler = detector._analyze_rule_of_60(filler_text)
    assert res_filler.raw_score == 40.0
    assert "Narrative Warning" in res_filler.explanation

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
