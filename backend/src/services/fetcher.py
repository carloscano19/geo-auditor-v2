"""
GEO-AUDITOR AI - Fetcher & Anti-Bot Challenge Detection

Provides utilities to identify anti-bot challenge / captcha verification screens
(Cloudflare, Incapsula, SiteGround, PerimeterX, etc.) and handle retries or controlled errors.
"""

import re
from typing import Optional
from src.scrapers.base_scraper import ScraperError, ChallengePageError

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
    - Title or text contains typical challenge markers, or status 403 with 'Access denied'.
    - HTML contains challenge scripts or elements (Cloudflare, Incapsula, SG Captcha, PX).
    - AND main text has fewer than 150 words (to prevent false positives on legitimate articles).
    """
    title = title or ""
    text = text or ""
    html = html or ""

    if not title and html:
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m_title:
            title = m_title.group(1).strip()

    if text:
        word_count = len(text.split())
    elif html:
        from src.utils.text_processing import extract_clean_text
        word_count = len(extract_clean_text(html).split())
    else:
        word_count = 0

    # Legitimate substantive articles with >= 150 words are not challenge pages
    if word_count >= 150:
        return False

    title_lower = title.lower()
    text_lower = text.lower()
    combined_text = f"{title_lower} {text_lower}"
    html_lower = html.lower()

    for marker in CHALLENGE_TEXT_MARKERS:
        if marker in combined_text or marker in html_lower:
            return True

    if status_code == 403 and ("access denied" in combined_text or "access denied" in html_lower):
        return True

    for marker in CHALLENGE_HTML_MARKERS:
        if marker in html_lower:
            return True

    return False
