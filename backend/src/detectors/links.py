"""
GEO-AUDITOR AI - Links & Verifiability Detector

Phase 8: Links (Layer 9 - 10%)
Evaluates citation quality, external links, and authority sources.
"""

import re
from urllib.parse import urlparse
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown

class LinksDetector(BaseDetector):
    """
    Detector for Links & Verifiability.
    
    Evaluates:
    1. External Link Quality: Presence of valid external links.
    2. Authority Sources: Links to high-authority domains (.edu, .gov, wikipedia, etc.).
    """
    
    dimension_name = "links_verifiability"
    weight = 0.06
    
    # Authority Markers
    AUTHORITY_DOMAINS = [
        "wikipedia.org",
        "nytimes.com", "bbc.com", "reuters.com", "forbes.com",
        "wsj.com", "techcrunch.com", "nature.com", "science.org",
        "nih.gov", "cdc.gov", "who.int", "arxiv.org",
        "searchengineland.com", "searchenginejournal.com", "ahrefs.com/blog", "moz.com/blog", # Industry specific
    ]
    
    AUTHORITY_TLDS = [".edu", ".gov", ".mil", ".ac.uk"]
    
    # Social & Utility Domains (filtered from citation count)
    SOCIAL_DOMAINS = [
        "facebook.com", "twitter.com", "x.com", "instagram.com", 
        "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com",
        "t.me", "discord.gg", "whatsapp.com", "telegram.org",
        "bsky.app", "threads.net", "wa.me", "reddit.com"
    ]
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        
        # Parse links from main article content using BeautifulSoup
        from bs4 import BeautifulSoup
        from src.utils.text_processing import extract_main_content
        html = page_data.html_rendered
        scoped_html, _ = extract_main_content(html)
        soup = BeautifulSoup(scoped_html if scoped_html else html, 'lxml')
        hrefs = [a.get('href', '') for a in soup.find_all('a')]
        
        base_domain = ""
        try:
            target_url = page_data.final_url or page_data.url
            if target_url and target_url.startswith("http"):
                base_domain = urlparse(target_url).netloc.lower().replace("www.", "")
        except:
            pass
            
        external_links = []
        internal_links = []
        
        for href in hrefs:
            href = href.strip()
            if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
                continue
                
            try:
                # Basic classification
                if href.startswith("http"):
                    domain = urlparse(href).netloc.lower().replace("www.", "")
                    if base_domain and (domain == base_domain or domain.endswith("." + base_domain)):
                        internal_links.append(href)
                    else:
                        external_links.append(href)
                elif href.startswith("/"):
                    internal_links.append(href)
                else:
                    # Relative path without slash
                    internal_links.append(href)
            except:
                continue

        # --- Refine Classification (Filter Utility/Social) ---
        citation_links = []
        utility_links = []
        
        for link in external_links:
            try:
                domain = urlparse(link).netloc.lower()
                is_utility = False
                
                # Check Social
                for social in self.SOCIAL_DOMAINS:
                    if social in domain:
                        is_utility = True
                        break
                            
                if is_utility:
                    utility_links.append(link)
                else:
                    citation_links.append(link)
            except:
                citation_links.append(link) # Fallback

        # 1. External Link Quality (50%)
        # ----------------------------------------------------------------
        ext_count = len(citation_links)
        
        if ext_count >= 3:
            link_score = 100.0
            link_status = "Excellent"
        elif ext_count >= 1:
            link_score = 60.0
            link_status = "Good"
        else:
            link_score = 0.0
            link_status = "Missing"
            
        link_recs = []
        if ext_count < 3:
            link_recs.append("Add at least 2-3 links to independent external sources to support your claims.")
            
        explanation_ext = f"{'✅' if link_score > 0 else '❌'} {link_status}: Found {ext_count} citation links."
        if utility_links:
            explanation_ext += f" (Note: {len(utility_links)} social links ignored as citations)."
            
        breakdown.append(ScoreBreakdown(
            name="External Links Found",
            raw_score=link_score,
            weight=0.50,
            weighted_score=link_score * 0.50,
            explanation=explanation_ext,
            recommendations=link_recs
        ))
        
        # 2. Source Diversity (50%)
        # ----------------------------------------------------------------
        cited_domains = set()
        for link in citation_links:
            try:
                dom = urlparse(link).netloc.lower().replace("www.", "")
                if dom:
                    cited_domains.add(dom)
            except Exception:
                continue

        unique_external_domains = sorted(list(cited_domains))
        num_domains = len(unique_external_domains)

        if num_domains >= 3:
            diversity_score = 100.0
            diversity_status = "High Diversity"
        elif num_domains == 2:
            diversity_score = 70.0
            diversity_status = "Moderate Diversity"
        elif num_domains == 1:
            diversity_score = 40.0
            diversity_status = "Low Diversity"
        else:
            diversity_score = 0.0
            diversity_status = "No Diversity"

        div_recs = []
        if num_domains < 3:
            div_recs.append("Cite at least 3 distinct external sources to improve source diversity.")

        domains_sample = f" ({', '.join(unique_external_domains[:3])})" if unique_external_domains else ""
        explanation_div = f"{'✅' if diversity_score >= 70 else '⚠️' if diversity_score > 0 else '❌'} {diversity_status}: Found {num_domains} distinct external domain(s){domains_sample}."

        breakdown.append(ScoreBreakdown(
            name="Source Diversity",
            raw_score=diversity_score,
            weight=0.50,
            weighted_score=diversity_score * 0.50,
            explanation=explanation_div,
            recommendations=div_recs
        ))
        
        # Calculate Total
        score = sum(item.weighted_score for item in breakdown)
        
        for item in breakdown:
            recommendations.extend(item.recommendations)

        return DetectorResult(
            dimension=self.dimension_name,
            score=score,
            weight=self.weight,
            contribution=self.calculate_contribution(score),
            breakdown=breakdown,
            errors=errors,
            debug_info={
                "citation_links": citation_links[:10],
                "utility_links": utility_links[:10],
                "internal_links_count": len(internal_links),
                "distinct_domains_found": unique_external_domains,
            }
        )
