
import re
from bs4 import BeautifulSoup

def clean_html_for_analysis(html: str) -> str:
    """
    Perform aggressive cleaning and SCOPING of HTML.
    
    1. Scope Restriction: Attempts to find the main content container (<article>, <main>, .post-content).
       If found, it discards the rest of the separate DOM tree.
    2. Noise Removal: Removes nav, footer, aside, and noise classes from the scoped content.
    """
    if not html:
        return ""
        
    soup = BeautifulSoup(html, 'lxml')
    
    # --- BRUTE FORCE LAYER 1: MINIMAL CLEANING ---
    # User Request: "Elimina OBLIGATORIAMENTE solo lo obvio: <script>, <style>, <svg>, <noscript>."
    # "NO elimines <header>, <footer> o <nav> todavía."
    
    # Elements to remove completely (Technical Noise)
    technical_tags = ['script', 'style', 'noscript', 'iframe', 'svg', 'form', 'button', 'input', 'textarea', 'select', 'option']
    for tag in technical_tags:
        for element in soup.find_all(tag):
            element.decompose()
            
    # We DO NOT remove nav/footer/aside yet to ensure we capture content in bad layouts.
    # The filtering will happen at the extraction level (Layer 3).

    return str(soup)

def filter_headers_by_text(headers: list[str]) -> list[str]:
    """
    Layer 3: Post-Extraction Filtering.
    Excludes headers containing prohibited words (navigation terms).
    """
    blacklist = [
        "subscribe", "login", "sign up", "sign in", "menu", "search", 
        "related", "recent posts", "footer", "cookie", "privacy policy",
        "contact", "about us", "newsletter", "follow us", "share",
        "comments", "leave a reply", "table of contents", "author",
        "posted by", "categories", "tags", "loading"
    ]
    
    clean_headers = []
    for h in headers:
        # Check if header text contains any blacklist word (case insensitive)
        h_lower = h.lower()
        # Strict equality might be too strict, 'contains' is safer for things like "Subscribe to our newsletter"
        # But we don't want to kill "About Bitcoin" if "About" is blacklisted.
        # Let's check for exact matches OR distinct phrases
        
        is_blacklisted = False
        for bad_word in blacklist:
            # Check for exact matches or distinct phrase presence
            # e.g. "Related Posts" == "related posts" -> match
            # "Login" in "User Login" -> match
            if bad_word in h_lower:
                is_blacklisted = True
                break
        
        if not is_blacklisted and len(h.strip()) > 2: # Ignore empty/tiny headers
            clean_headers.append(h)
            
    return clean_headers

def extract_clean_text(html: str) -> str:
    """
    Extract text content from cleaned HTML.
    """
    cleaned_html = clean_html_for_analysis(html)
    soup = BeautifulSoup(cleaned_html, 'html.parser') # Use html.parser for compatibility
    
    # Get text and clean whitespace
    text = soup.get_text(separator=' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_headers(html: str) -> list[dict]:
    """
    Extract H1-H3 headers from HTML using BeautifulSoup.
    
    Robustness improvements:
    1. Uses html.parser (more forgiving in some environments)
    2. Checks for tags (h1, h2, h3)
    3. Checks for aria-level attributes on role="heading"
    """
    if not html:
        return []
        
    soup = BeautifulSoup(html, 'html.parser')
    headers = []
    
    # 1. Standard Tags
    for tag in soup.find_all(['h1', 'h2', 'h3']):
        text = tag.get_text(strip=True)
        if text and 3 < len(text) < 200:
            headers.append({
                'tag': tag.name.lower(),
                'text': text
            })
            
    # 2. ARIA Headings (Fallback for some SPAs)
    # Only add if not already captured by tags
    existing_texts = {h['text'] for h in headers}
    for tag in soup.find_all(attrs={"role": "heading"}):
        level = tag.get("aria-level")
        if level in ['1', '2', '3']:
            text = tag.get_text(strip=True)
            if text and text not in existing_texts and 3 < len(text) < 200:
                headers.append({
                    'tag': f'h{level}',
                    'text': text
                })
            
    return headers

def extract_substantive_paragraphs(html: str, min_words: int = 10) -> list[str]:
    """
    Extract all substantive paragraphs from HTML using BeautifulSoup.
    Skips short fragments like CTAs, buttons, and navigation.
    """
    if not html:
        return []
        
    soup = BeautifulSoup(html, 'html.parser')
    paragraphs = []
    
    for p in soup.find_all('p'):
        text = p.get_text(strip=True)
        if len(text.split()) >= min_words:
            paragraphs.append(text)
            
    return paragraphs
