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
    weight = 0.10
    
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
        "t.me", "discord.gg", "whatsapp.com", "telegram.org"
    ]
    
    # Partner/Ecosystem domains (filtered from citation count)
    PARTNER_DOMAINS = ["socios.com", "chiliz.com", "mediarex.com"]
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        
        # Parse links from rendered HTML using BeautifulSoup
        from bs4 import BeautifulSoup
        html = page_data.html_rendered
        soup = BeautifulSoup(html, 'lxml')
        hrefs = [a.get('href', '') for a in soup.find_all('a')]
        
        base_domain = ""
        try:
            if page_data.url and page_data.url.startswith("http"):
                base_domain = urlparse(page_data.url).netloc.lower()
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
                    domain = urlparse(href).netloc.lower()
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
                
                # Check Partners
                if not is_utility:
                    for partner in self.PARTNER_DOMAINS:
                        if partner in domain:
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
            explanation_ext += f" (Note: {len(utility_links)} social/partner links ignored as citations)."
            
        breakdown.append(ScoreBreakdown(
            name="External Links Found",
            raw_score=link_score,
            weight=0.50,
            weighted_score=link_score * 0.50,
            explanation=explanation_ext,
            recommendations=link_recs
        ))
        
        # 2. Authority Sources (50%)
        # ----------------------------------------------------------------
        authority_links_found = []
        
        # Only check citation links for authority
        for link in citation_links:
            try:
                domain = urlparse(link).netloc.lower()
                is_auth = False
                
                # Check predefined domains
                for auth_dom in self.AUTHORITY_DOMAINS:
                    if auth_dom in domain:
                        is_auth = True
                        break
                
                # Check TLDs
                if not is_auth:
                    for tld in self.AUTHORITY_TLDS:
                        if domain.endswith(tld):
                            is_auth = True
                            break
                            
                if is_auth:
                    authority_links_found.append(domain)
            except:
                continue
                
        auth_count = len(set(authority_links_found)) # Unique domains
        
        if auth_count >= 2:
            auth_score = 100.0
            auth_status = "High Authority"
        elif auth_count == 1:
            auth_score = 50.0
            auth_status = "Medium Authority"
        else:
            auth_score = 0.0
            auth_status = "Low Authority"
            
        auth_recs = []
        if auth_count < 2:
            auth_recs.append("Link to high-authority domains (.edu, .gov, major citations) to boost trust.")
            
        breakdown.append(ScoreBreakdown(
            name="Authority Sources Detected",
            raw_score=auth_score,
            weight=0.50,
            weighted_score=auth_score * 0.50,
            explanation=f"{'✅' if auth_score > 0 else '❌'} {auth_status}: Found {auth_count} sources ({', '.join(list(set(authority_links_found))[:3])}).",
            recommendations=auth_recs
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
                "authority_domains_found": list(set(authority_links_found)),
            }
        )
