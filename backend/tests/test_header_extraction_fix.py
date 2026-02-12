import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import asyncio
from src.utils.text_processing import extract_headers
from src.detectors.aeo_structure import AEOStructureDetector
from src.models.schemas import PageData

# Mock HTML similar to a typical blog post
MOCK_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <header>
        <nav>Menu</nav>
    </header>
    <main>
        <h1>Guía Completa de SEO 2026</h1>
        <p>SEO (Search Engine Optimization) es el proceso de optimizar tu sitio web.</p>
        
        <h2>¿Qué es el SEO Técnico?</h2>
        <p>El SEO técnico se refiere a...</p>
        
        <h3>Velocidad de carga</h3>
        <p>Es crucial para la experiencia de usuario.</p>
        
        <h2>Factores de Ranking</h2>
        <p>Existen múltiples factores...</p>
        
        <div class="sidebar">
            <h3>Artículos Relacionados</h3>
            <ul><li>Link 1</li></ul>
        </div>
    </main>
    <footer>Copyright 2026</footer>
</body>
</html>
"""

def test_extract_headers():
    headers = extract_headers(MOCK_HTML)
    print("\nExtracted Headers:", headers)
    
    assert len(headers) >= 4
    
    tags = [h['tag'] for h in headers]
    assert 'h1' in tags
    assert 'h2' in tags
    assert 'h3' in tags
    
    texts = [h['text'] for h in headers]
    assert "Guía Completa de SEO 2026" in texts
    assert "¿Qué es el SEO Técnico?" in texts
    assert "Velocidad de carga" in texts

@pytest.mark.asyncio
async def test_aeo_structure_integration():
    detector = AEOStructureDetector()
    
    page_data = PageData(
        url="http://test.local",
        final_url="http://test.local",
        html_raw=MOCK_HTML,
        html_rendered=MOCK_HTML,
        text_content="Extract text content mocked",
        status_code=200,
        load_time_ms=100
    )
    
    result = await detector.analyze(page_data)
    
    print("\nDetector Result Debug Info:", result.debug_info)
    
    # Verify structure_metrics presence
    assert "structure_metrics" in result.debug_info
    metrics = result.debug_info["structure_metrics"]
    
    assert metrics["h1_count"] == 1
    assert metrics["h2_count"] == 2
    assert metrics["h3_count"] > 0 # At least 1, maybe 2 if sidebar H3 is caught (simplified logic catches all)
    assert metrics["h1_text"] == "Guía Completa de SEO 2026"

if __name__ == "__main__":
    # Manual run wrapper
    test_extract_headers()
    asyncio.run(test_aeo_structure_integration())
    print("\nAll tests passed successfully!")
