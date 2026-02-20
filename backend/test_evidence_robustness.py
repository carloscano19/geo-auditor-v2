
import asyncio
from src.detectors.evidence_density import EvidenceDensityDetector
from src.models.schemas import PageData

async def test_robust_verification():
    # Scenario: Claim text has tags inside it in the HTML
    claim = "The token grew to 26% gain over 14 days."
    # HTML has <strong> inside the claim and a link right after
    html = f"<p>The token <strong>grew to 26%</strong> gain over 14 days. <a href='https://source.com'>[1]</a></p>"
    text = "The token grew to 26% gain over 14 days."
    
    page_data = PageData(
        url="https://test.com",
        final_url="https://test.com",
        html_raw="",
        html_rendered=html,
        text_content=text,
        headers={},
        status_code=200,
        load_time_ms=0,
        is_ssr=True,
        is_https=True
    )
    
    detector = EvidenceDensityDetector()
    result = await detector.analyze(page_data)
    
    print("\n--- Mock Test Result ---")
    print(f"Claim: {claim}")
    explanation = result.breakdown[0].explanation
    print(f"Explanation: {explanation}")
    
    if "✅ Verified" in explanation:
        print("SUCCESS: Claim verified despite tags inside and nearby link.")
    else:
        print("FAILURE: Claim NOT verified.")

if __name__ == "__main__":
    asyncio.run(test_robust_verification())
