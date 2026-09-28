"""
GEO-AUDITOR AI - Content Type Classifier

Detects page content type:
- 'news': News/press release (NewsArticle in Schema, /news/, /newsroom/, /press/, /noticias/)
- 'review': Review / evaluation (Review in Schema, /reviews/, review in title)
- 'product': E-commerce product (Product in Schema, /product/, /producto/, /shop/)
- 'guide_blog': Default for articles, guides, blog posts
"""

import json
import re
from urllib.parse import urlparse
from typing import Optional
from bs4 import BeautifulSoup
from src.models.schemas import PageData
from src.utils.lang_patterns import is_explanatory_h1, is_press_release_dateline
from src.utils.text_processing import extract_main_content


def detect_content_type(page_data: PageData) -> str:
    """
    Detect the content classification of a page.
    Priority:
    1. Schema.org structured data (JSON-LD and Microdata)
    2. Press release dateline in first 400 chars of main content
    3. URL path indicators (with explanatory H1 override for news paths)
    4. Title / H1 indicators
    5. Default: 'guide_blog'
    """
    html = page_data.html_rendered or page_data.html_raw or ''
    soup = None
    h1_text = ''
    if html:
        try:
            soup = BeautifulSoup(html, 'lxml')
            h1 = soup.find('h1')
            if h1:
                h1_text = h1.get_text(strip=True)
        except Exception:
            soup = None

    # 1. Schema.org check (Priority 1)
    if soup:
        try:
            # JSON-LD scripts
            for script in soup.find_all('script', type='application/ld+json'):
                if not script.string:
                    continue
                try:
                    data = json.loads(script.string.strip())
                    items = []
                    if isinstance(data, dict):
                        if '@graph' in data and isinstance(data['@graph'], list):
                            items.extend(data['@graph'])
                        items.append(data)
                    elif isinstance(data, list):
                        items.extend(data)

                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        raw_type = item.get('@type', '')
                        types = [raw_type] if isinstance(raw_type, str) else (raw_type if isinstance(raw_type, list) else [])
                        types_lower = [str(t).lower() for t in types]

                        if any(t in types_lower for t in ['newsarticle', 'pressrelease']):
                            return 'news'
                        if any(t in types_lower for t in ['review', 'productreview', 'criticreview']):
                            return 'review'
                        if any(t in types_lower for t in ['product', 'individualproduct', 'productmodel', 'offer', 'aggregateoffer']):
                            return 'product'
                        if any(t in types_lower for t in ['blogposting', 'blog']):
                            return 'guide_blog'
                except Exception:
                    continue

            # Microdata itemtype check
            for elem in soup.find_all(attrs={'itemtype': True}):
                itemtype = str(elem.get('itemtype', '')).lower()
                if 'newsarticle' in itemtype or 'pressrelease' in itemtype:
                    return 'news'
                if 'review' in itemtype:
                    return 'review'
                if 'product' in itemtype:
                    return 'product'
                if 'blogposting' in itemtype or 'blog' in itemtype:
                    return 'guide_blog'
        except Exception:
            pass

    # 2. Press release dateline check (Priority 2)
    main_text = ""
    if html:
        try:
            _, main_text = extract_main_content(html)
        except Exception:
            main_text = ""
    if not main_text and page_data.text_content:
        main_text = page_data.text_content

    if main_text and is_press_release_dateline(main_text[:400]):
        return 'news'

    # 3. URL Path check (Priority 3)
    url_target = page_data.final_url or page_data.url or ''
    path = ''
    try:
        if url_target.startswith('http'):
            path = urlparse(url_target).path.lower()
        else:
            path = url_target.lower()
    except Exception:
        path = url_target.lower()

    news_paths = ['/news/', '/newsroom/', '/press/', '/noticias/', '/prensa/']
    if any(np in path for np in news_paths) or path.endswith(('/news', '/newsroom', '/press', '/noticias', '/prensa')):
        # Explanatory H1 pattern override: if H1 is educational/guide, return guide_blog
        if h1_text and is_explanatory_h1(h1_text):
            return 'guide_blog'
        return 'news'

    review_paths = ['/review/', '/reviews/', '/resena/', '/resenas/']
    if any(rp in path for rp in review_paths) or path.endswith(('/review', '/reviews', '/resena', '/resenas')):
        return 'review'

    product_paths = ['/product/', '/products/', '/producto/', '/productos/', '/shop/', '/tienda/', '/item/']
    if any(pp in path for pp in product_paths):
        return 'product'

    # 4. Title indicators check (Priority 4)
    if h1_text:
        if re.search(r'\b(review|reviews|reseña|reseñas)\b', h1_text, re.IGNORECASE):
            return 'review'

    # 5. Default (Priority 5)
    return 'guide_blog'
