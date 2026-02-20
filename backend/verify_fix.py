
import asyncio
from playwright.async_api import async_playwright
from src.utils.text_processing import extract_clean_text, extract_headers
from src.detectors.evidence_density import EvidenceDensityDetector
from src.models.schemas import PageData

async def verify_discrepancy():
    url = "https://www.fantokens.com/newsroom/how-citys-bi-weekly-gain-reflects-growing-confidence-amid-bitcoins-macro-driven-rebound"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        html_rendered = await page.content()
        await browser.close()
        
    print(f"Captured HTML length: {len(html_rendered)}")
    
    # Check headers
    headers = extract_headers(html_rendered)
    print("\n--- Headers Detected ---")
    for h in headers:
        print(f"{h['tag'].upper()}: {h['text']}")
        
    # Check text content
    text_content = extract_clean_text(html_rendered)
    print(f"\nText content length: {len(text_content)}")
    print(f"Text snippet: {text_content[:200]}...")
    
    # Check Evidence Density
    page_data = PageData(
        url=url,
        final_url=url,
        html_raw="",
        html_rendered=html_rendered,
        text_content=text_content,
        headers={},
        status_code=200,
        load_time_ms=0,
        is_ssr=True,
        is_https=True
    )
    
    detector = EvidenceDensityDetector()
    result = await detector.analyze(page_data)
    print("\n--- Evidence Density Result ---")
    print(result.breakdown[0].explanation)
    
    # Check Entity Density counts manually for some terms
    title = headers[0]['text'] if headers else ""
    print(f"\nTitle used for entities: {title}")
    
    entities = ["Bi-weekly", "Gain", "Reflects", "Growing", "Confidence"]
    for e in entities:
        count = text_content.lower().count(e.lower())
        print(f"Entity '{e}' count in text: {count}")

if __name__ == "__main__":
    asyncio.run(verify_discrepancy())
