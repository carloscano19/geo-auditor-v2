
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def diagnose_url(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print(f"Loading {url}...")
        await page.goto(url, wait_until="domcontentloaded")
        raw_html = await page.content()
        
        await page.wait_for_load_state("networkidle")
        rendered_html = await page.content()
        
        print(f"Raw HTML length: {len(raw_html)}")
        print(f"Rendered HTML length: {len(rendered_html)}")
        
        # Helper to count tags correctly
        def count_tags(html, parser):
            soup = BeautifulSoup(html, parser)
            h1s = len(soup.find_all('h1'))
            h2s = len(soup.find_all('h2'))
            ps = len(soup.find_all('p'))
            return h1s, h2s, ps

        p1_h1, p1_h2, p1_p = count_tags(rendered_html, 'html.parser')
        p2_h1, p2_h2, p2_p = count_tags(rendered_html, 'lxml')
        
        print("\n--- Parser Comparison (Rendered HTML) ---")
        print(f"html.parser: H1={p1_h1}, H2={p1_h2}, P={p1_p}")
        print(f"lxml:        H1={p2_h1}, H2={p2_h2}, P={p2_p}")
        
        print("\n--- Regex Check (Rendered HTML) ---")
        re_h2 = len(re.findall(r'<h2[^>]*>', rendered_html, re.I))
        re_p = len(re.findall(r'<p[^>]*>', rendered_html, re.I))
        print(f"Regex:       H2={re_h2}, P={re_p}")
        
        # Check first 500 chars of body
        soup = BeautifulSoup(rendered_html, 'html.parser')
        body = soup.find('body')
        if body:
            print("\n--- Body Snippet (First 200 chars) ---")
            print(body.get_text()[:200].replace('\n', ' '))
            
        await browser.close()

if __name__ == "__main__":
    url = "https://www.fantokens.com/newsroom/how-citys-bi-weekly-gain-reflects-growing-confidence-amid-bitcoins-macro-driven-rebound"
    asyncio.run(diagnose_url(url))
