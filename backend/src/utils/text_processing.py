
import re
from bs4 import BeautifulSoup

def extract_main_content(html: str) -> tuple[str, str]:
    """
    Centralized extraction of article/main content.
    Used across all detectors (aeo_structure, evidence_density, entity, formatting, links).
    
    Priority:
    1. <article>
    2. [role=main]
    3. <main>
    4. Block with the most text if none of the above exist (div, section, or body).
    
    Sanity check (applied after semantic selection):
    - Compute the densest div/section by summing <p> text (paragraph-text).
    - If the chosen semantic container has less than 40 % of that paragraph-text,
      the semantic tag is decorative/redundant (e.g. a blog-card <article> in a
      related-posts widget) and the dense block is used instead.
    
    Header & Footer preservation:
    - Preserves <header> and <footer> INSIDE <article> or <main> (contains H1, date, author).
    - Removes <header> and <footer> that are OUTSIDE the main content.
    
    Boilerplate & Noise exclusion:
    - Removes technical noise: script, style, noscript, iframe, svg, form, button, input, textarea, select, option.
    - Always excludes: nav, aside, and elements whose class or id contains:
      sidebar, widget, related, relacionad, author-box, author-bio, post-navigation,
      nav-links, comments, share, newsletter, breadcrumb.
    - Protection: never removes an element that contains the H1 or more than 50 % of
      the container's own paragraph-text.
      
    Returns:
        tuple[str, str]: (scoped_html, scoped_clean_text)
    """
    if not html:
        return "", ""
        
    soup = BeautifulSoup(html, 'lxml')
    
    # 1. Technical noise to remove everywhere
    technical_tags = [
        'script', 'style', 'noscript', 'iframe', 'svg', 'form',
        'button', 'input', 'textarea', 'select', 'option'
    ]
    for tag in technical_tags:
        for el in soup.find_all(tag):
            el.decompose()

    def _paragraph_text_len(el) -> int:
        """Sum of character length of all <p> text nodes inside el."""
        return sum(len(p.get_text(separator=' ', strip=True)) for p in el.find_all('p'))

    def _densest_block(soup_obj) -> tuple:
        """Return (element, paragraph_text_len) for the div/section whose content is
        most "paragraph-pure" among those with substantial paragraph text.

        Strategy:
        1. Compute the maximum paragraph-text length across all div/section candidates.
        2. Keep only candidates with at least 60 % of that maximum (substantial content).
        3. Among those, rank by paragraph-text / total-text ratio (higher = more
           article-like, less polluted by navigation / footer / banner text).
        4. Tie-break by minimum total text (innermost / most specific block).

        Examples:
        - div#page (wraps entire page): ratio ~0.86, because it also contains nav text.
        - div.entry-content (article body): ratio ~0.99 — almost entirely <p> text.
        - Result: div.entry-content wins.
        """
        candidates = soup_obj.find_all(['div', 'section'])
        if not candidates:
            return None, 0

        scored = []
        for cand in candidates:
            p_len = _paragraph_text_len(cand)
            t_len = len(cand.get_text(separator=' ', strip=True))
            scored.append((cand, p_len, t_len))

        max_pt = max(p for _, p, _ in scored) if scored else 0
        if max_pt == 0:
            return None, 0

        # Keep only candidates with ≥ 60 % of the max paragraph-text
        threshold = 0.60 * max_pt
        dense = [(cand, p_len, t_len) for cand, p_len, t_len in scored if p_len >= threshold]

        # Pick the block with the best p-text/total-text ratio (most paragraph-pure),
        # tie-broken by minimum total text (most interior).
        best = max(
            dense,
            key=lambda x: (x[1] / x[2] if x[2] else 0, -x[2])
        )
        return best[0], best[1]



    # 2. Select main content container by priority
    # If multiple <article>, [role=main], or <main> tags exist, pick the one with the most text
    articles = soup.find_all('article')
    target = None
    is_article_or_main = False
    
    if articles:
        target = max(articles, key=lambda a: len(a.get_text(separator=' ', strip=True)))
        is_article_or_main = True
    else:
        roles_main = soup.find_all(attrs={"role": "main"})
        if roles_main:
            target = max(roles_main, key=lambda m: len(m.get_text(separator=' ', strip=True)))
            is_article_or_main = True
        else:
            mains = soup.find_all('main')
            if mains:
                target = max(mains, key=lambda m: len(m.get_text(separator=' ', strip=True)))
                is_article_or_main = True
            else:
                dense_el, dense_pt = _densest_block(soup)
                if dense_el is not None and dense_pt > 100:
                    target = dense_el
                else:
                    target = soup.body or soup


    # 2b. Sanity check: if the chosen semantic container holds less than 40 % of
    # the paragraph-text of the densest div/section, it is likely a decorative tag
    # (e.g. a blog-card <article> inside a related-posts widget) rather than the
    # real article body. Swap to the denser block.
    if is_article_or_main:
        chosen_pt = _paragraph_text_len(target)
        dense_el, dense_pt = _densest_block(soup)
        if dense_pt > 0 and (chosen_pt / dense_pt) < 0.40 and dense_el is not None:
            target = dense_el
            is_article_or_main = False  # treat as fallback (remove outer header/footer)

    # Work on a clone/scoped parse to isolate the container
    scoped_soup = BeautifulSoup(str(target), 'lxml')
    root = scoped_soup.body if scoped_soup.body else scoped_soup

    # Paragraph-text length of root (used for exclusion protection)
    root_paragraph_text_len = _paragraph_text_len(root)
    # Total text length in root for legacy protection checks
    root_text_len = len(root.get_text(separator=' ', strip=True))

    # 3. Header and footer scoping:
    # Preserve <header> and <footer> inside <article> or <main>, remove only if outside
    if not is_article_or_main:
        for el in root.find_all(['header', 'footer']):
            el.decompose()

    # 4. Always exclude nav and aside
    for el in root.find_all(['nav', 'aside']):
        el.decompose()

    # 5. Always exclude elements whose class or id contains prohibited noise keywords
    # Protection: Do NOT delete an element if it contains the H1 or >50% of the
    # container's paragraph-text (prevents removing the article body itself).
    prohibited_keywords = [
        'sidebar', 'widget', 'related', 'relacionad', 'author-box', 'author-bio',
        'post-navigation', 'nav-links', 'comments', 'share', 'newsletter', 'breadcrumb',
        'about-author', 'author-info', 'sobre-autor', 'caja-autor', 'autor-box', 'author-card'
    ]
    
    for el in root.find_all(True):
        attrs = getattr(el, 'attrs', None)
        if not attrs:
            continue
        classes = " ".join(attrs.get('class', [])).lower() if isinstance(attrs.get('class'), list) else str(attrs.get('class', '')).lower()
        elem_id = str(attrs.get('id', '')).lower()
        combined_attrs = f"{classes} {elem_id}"
        
        if any(kw in combined_attrs for kw in prohibited_keywords):
            has_h1 = bool(el.find('h1')) or el.name == 'h1'
            el_paragraph_text = _paragraph_text_len(el)
            # Protect if element holds >50 % of the container's paragraph text
            is_substantial = (
                root_paragraph_text_len > 0
                and (el_paragraph_text / root_paragraph_text_len) > 0.50
            ) or (
                root_text_len > 0
                and (len(el.get_text(separator=' ', strip=True)) / root_text_len) > 0.40
            )
            if has_h1 or is_substantial:
                continue
            el.decompose()
            
    # Also remove landmark navigation/complementary roles if any remain
    for el in root.find_all(attrs={"role": ['navigation', 'complementary', 'menu']}):
        el.decompose()

    scoped_html = str(root)
    text = root.get_text(separator=' ')
    scoped_text = re.sub(r'\s+', ' ', text).strip()
    
    return scoped_html, scoped_text

def clean_html_for_analysis(html: str) -> str:
    """
    Perform aggressive cleaning and scoping of HTML returning scoped HTML.
    Delegates to extract_main_content.
    """
    return extract_main_content(html)[0]

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
    Extract text content from cleaned main article content.
    Delegates to extract_main_content.
    """
    return extract_main_content(html)[1]

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
