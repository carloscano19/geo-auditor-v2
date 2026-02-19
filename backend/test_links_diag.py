"""Diagnostic: Run the actual LinksDetector to see what it reports."""
import asyncio
import json
from src.scrapers.playwright_scraper import PlaywrightScraper
from src.detectors.links import LinksDetector

async def test():
    scraper = PlaywrightScraper()
    data = await scraper.scrape(
        "https://www.fantokens.com/newsroom/how-gal-and-juv-trade-volumes-soared-as-galatasaray-secure-huge-ucl-win"
    )
    
    print(f"page_data.url = {data.url}")
    print(f"page_data.final_url = {data.final_url}")
    
    detector = LinksDetector()
    result = await detector.analyze(data)
    
    print(f"\nDimension: {result.dimension}")
    print(f"Score: {result.score}")
    print(f"Contribution: {result.contribution}")
    for b in result.breakdown:
        print(f"\n  [{b.name}]")
        print(f"  raw_score={b.raw_score}, weight={b.weight}, weighted_score={b.weighted_score}")
        print(f"  explanation: {b.explanation}")
        print(f"  recommendations: {b.recommendations}")
    
    await scraper.close()

asyncio.run(test())
