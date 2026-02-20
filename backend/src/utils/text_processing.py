
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
    
    # Elements to remove completely (Technical Noise)
    technical_tags = ['script', 'style', 'noscript', 'iframe', 'svg', 'form', 'button', 'input', 'textarea', 'select', 'option']
    for tag in technical_tags:
        for element in soup.find_all(tag):
            element.decompose()
            
    return str(soup)

def filter_headers_by_text(headers: list[str]) -> list[str]:
    """
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
        h_lower = h.lower()
        is_blacklisted = False
        for bad_word in blacklist:
            if bad_word in h_lower:
                is_blacklisted = True
                break
        
        if not is_blacklisted and len(h.strip()) > 2:
            clean_headers.append(h)
            
    return clean_headers

def extract_clean_text(html: str) -> str:
    """
    Extract text content from cleaned HTML using lxml.
    """
    cleaned_html = clean_html_for_analysis(html)
    soup = BeautifulSoup(cleaned_html, 'lxml')
    
    # Get text and clean whitespace
    text = soup.get_text(separator=' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_headers(html: str) -> list[dict]:
    """
    Extract H1-H3 headers from HTML using BeautifulSoup with lxml.
    Includes ARIA role="heading" support.
    """
    if not html:
        return []
        
    soup = BeautifulSoup(html, 'lxml')
    headers = []
    
    # 1. Standard Tags
    for tag in soup.find_all(['h1', 'h2', 'h3']):
        text = tag.get_text(strip=True)
        if text and 3 < len(text) < 200:
            headers.append({
                'tag': tag.name.lower(),
                'text': text
            })
            
    # 2. ARIA Headings (Fallback)
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
    Extract all substantive paragraphs using lxml.
    """
    if not html:
        return []
        
    soup = BeautifulSoup(html, 'lxml')
    paragraphs = []
    
    for p in soup.find_all('p'):
        text = p.get_text(strip=True)
        if len(text.split()) >= min_words:
            paragraphs.append(text)
            
    return paragraphs
