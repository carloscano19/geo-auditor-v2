
import asyncio
from src.detectors.evidence_density import EvidenceDensityDetector
from src.models.schemas import PageData

async def test():
    try:
        print("Importing...")
        detector = EvidenceDensityDetector()
        print("Instantiated.")
        
        data = PageData(
            url="http://test.com",
            final_url="http://test.com",
            html_raw="<html><body>Test</body></html>",
            html_rendered="<html><body>The market grew by 50%. [1]</body></html>",
            text_content="The market grew by 50%. [1]",
            status_code=200,
            load_time_ms=100,
            word_count=100,
            is_ssr=True,
            is_https=True
        )
        
        print("Analyzing...")
        result = await detector.analyze(data)
        print("Result:", result)
        print("Breakdown:", result.breakdown)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
