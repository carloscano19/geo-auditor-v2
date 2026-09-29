"""
GEO-AUDITOR AI - Anti-Bot Challenge Detection

Provides utilities to identify anti-bot challenge / captcha verification screens
(Cloudflare, Incapsula, SiteGround, PerimeterX, etc.) without importing from
scrapers or services layers.
"""

import re
from typing import Optional

CHALLENGE_TEXT_MARKERS = [
    "one moment, please",
    "just a moment",
    "checking your browser",
    "attention required",
    "verifying you are human",
    "please enable javascript and cookies",
    "ddos protection by",
]

CHALLENGE_HTML_MARKERS = [
    "cf-challenge",
    "cf_chl_",
    "challenge-platform",
    "sgcaptcha",
    "/.well-known/sgcaptcha",
    "_incapsula_resource",
    "px-captcha",
]

CHALLENGE_PAGE_ERROR_MESSAGE = (
    "This page is protected by an anti-bot challenge and could not be analyzed. "
    "Try again later or use Paste Text."
)


def is_challenge_page(
    title: str = "",
    text: str = "",
    html: str = "",
    status_code: int = 200,
) -> bool:
    """
    Check if the page is an anti-bot challenge or verification screen.
    
    Returns True if:
    - Main text has fewer than 150 words (to prevent false positives on legitimate articles).
    - AND either:
      1) The title or visible text contains a challenge text marker, or status is 403 with 'Access denied'.
      2) The HTML contains an anti-bot script/element marker AND (status is 403, 429, or 503, or
         the title/visible text contains a text marker).
    
    Text markers are evaluated only against title and visible text, never the entire raw HTML.
    """
    title = title or ""
    text = text or ""
    html = html or ""
    status_code = status_code if status_code is not None else 200

    # Extract title from HTML if not explicitly supplied
    if not title and html:
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m_title:
            title = m_title.group(1).strip()

    # Determine word count of visible text
    if text:
        word_count = len(text.split())
    elif html:
        from src.utils.text_processing import extract_clean_text
        text = extract_clean_text(html)
        word_count = len(text.split())
    else:
        word_count = 0

    # Legitimate substantive content with >= 150 words is never marked as challenge
    if word_count >= 150:
        return False

    title_lower = title.lower()
    text_lower = text.lower()
    combined_text = f"{title_lower} {text_lower}"

    # Text markers checked ONLY in title and visible text
    has_text_marker = any(marker in combined_text for marker in CHALLENGE_TEXT_MARKERS)
    if status_code == 403 and "access denied" in combined_text:
        has_text_marker = True

    if has_text_marker:
        return True

    # HTML markers only count if status is 403/429/503 or a text marker is present
    html_lower = html.lower()
    has_html_marker = any(marker in html_lower for marker in CHALLENGE_HTML_MARKERS)
    if has_html_marker:
        if status_code in (403, 429, 503) or has_text_marker:
            return True

    return False
