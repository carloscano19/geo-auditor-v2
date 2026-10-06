"""
GEO-AUDITOR AI - Formatting & Visual UX Detector

Phase 6: Visual Formatting Scannability (Layer 8 - 10%)
Evaluates if content is visually scannable and rich.
"""

import re
from src.detectors.base_detector import BaseDetector
from src.models.schemas import PageData, DetectorResult, ScoreBreakdown

class FormattingDetector(BaseDetector):
    """
    Detector for Visual formatting and Scannability.
    
    Evaluates:
    1. Scannability (Lists/Tables): >1 list/table expected.
    2. Visual Hierarchy (Bold usage): Keywords highlighted, not full paragraphs.
    3. Multimedia: Images with alt text, videos.
    4. Text Walls: Blocks >80 words (approx 500 chars) without break/header.
    """
    
    dimension_name = "format_citability"
    weight = 0.06

    def __init__(self, config_override: dict = None):
        try:
            from config.settings import get_settings
            weights = config_override or get_settings().scoring_weights
            fc_config = weights.get("dimensions", {}).get(self.dimension_name, {})
            self.weight = fc_config.get("weight", self.weight)
        except Exception:
            pass
    
    # Text Wall Thresholds - GOLD STANDARD: Raised to 7 lines (~700 chars)
    MAX_CHARS_PER_BLOCK = 700  # Approx 7 lines / 100-120 words
    
    # Sub-dimension weights (Redistributed: 0.40/0.70 and 0.30/0.70)
    SCANNABILITY_WEIGHT = 4.0 / 7.0
    MULTIMEDIA_WEIGHT = 3.0 / 7.0
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        
        from bs4 import BeautifulSoup
        from src.utils.text_processing import extract_main_content
        html = page_data.html_rendered
        scoped_html, _ = extract_main_content(html)
        soup = BeautifulSoup(scoped_html if scoped_html else html, 'lxml')
        
        # 1. Scannability (Lists & Tables) - 57.14%
        # ----------------------------------------------------------------
        valid_lists = []
        
        # Find ul, ol, and table
        for tag in soup.find_all(['ul', 'ol', 'table']):
            # 1. Class/ID Blacklist
            attrs_str = str(tag.attrs).lower()
            blacklist = ['menu', 'nav', 'social', 'related', 'footer', 'share', 'breadcrumb', 'cookie', 'consent']
            if any(kw in attrs_str for kw in blacklist):
                continue
            
            # 2. Structure Check
            if tag.name in ['ul', 'ol']:
                items = tag.find_all('li', recursive=False)
                if len(items) <= 3:
                    continue
                
                # 3. Quality Check: Average words per item
                total_words = 0
                for item in items:
                    clean_item = item.get_text(strip=True)
                    total_words += len(clean_item.split())
                
                avg_words = total_words / len(items) if items else 0
                if avg_words < 10: # Slightly more lenient for lists
                    continue
            else: # table
                rows = tag.find_all('tr')
                if len(rows) <= 2:
                    continue
            
            valid_lists.append(tag.name)
        
        total_lists = len(valid_lists)
        scannability_score = 100.0 if total_lists >= 1 else 0.0
        
        # Check for Text Walls
        text_walls_found = 0
        for p in soup.find_all('p'):
            clean_text = p.get_text(strip=True)
            if len(clean_text) > self.MAX_CHARS_PER_BLOCK:
                text_walls_found += 1
                
        # Text Wall Scoring Inversion
        wall_score = 100.0
        if text_walls_found == 1:
            wall_score = 50.0
        elif text_walls_found >= 2:
            wall_score = 0.0
            
        if total_lists >= 1:
            scannability_score = wall_score
        else:
            scannability_score = min(50.0, wall_score)
            
        scan_recs = []
        if total_lists == 0:
            scan_recs.append("Add lists (<ul>, <ol>) or tables to break up content.")
        if text_walls_found > 0:
            scan_recs.append(f"Found {text_walls_found} large text blocks. Break paragraphs >4-5 lines.")
            
        breakdown.append(ScoreBreakdown(
            name="Lists/Tables Used",
            raw_score=scannability_score,
            weight=self.SCANNABILITY_WEIGHT,
            weighted_score=scannability_score * self.SCANNABILITY_WEIGHT,
            explanation=f"{'✅' if total_lists > 0 else '❌'} Found {total_lists} lists/tables. {'⚠️ ' + str(text_walls_found) + ' text walls.' if text_walls_found else ''}",
            recommendations=scan_recs
        ))
        
        # 2. Multimedia Content - 42.86%
        # ----------------------------------------------------------------
        img_elements = soup.find_all('img')
        video_elements = soup.find_all(['video', 'iframe', 'embed'])
        
        imgs_with_alt = 0
        for img in img_elements:
            alt = img.get('alt', '').strip()
            # Ignore placeholder alt or empty
            if alt and alt.lower() not in ['image', 'img', 'picture', 'photo']:
                imgs_with_alt += 1

        # Check for article featured image when outside the extracted content
        existing_img_srcs = set()
        for img in img_elements:
            for attr in ['src', 'data-src', 'data-lazy-src']:
                val = (img.get(attr) or '').strip()
                if val:
                    existing_img_srcs.add(val)

        featured_img_found = None
        if html:
            full_soup = BeautifulSoup(html, 'lxml')
            og_img_tag = full_soup.find('meta', property='og:image') or full_soup.find('meta', attrs={'name': 'og:image'})
            og_img_url = (og_img_tag.get('content') or '').strip() if og_img_tag else ''
            featured_keywords = ['hero', 'featured', 'post-thumbnail', 'wp-post-image']

            def _is_in_excluded_section(tag) -> bool:
                for parent in tag.parents:
                    if parent.name in ['nav', 'footer', 'aside']:
                        return True
                    if parent.name == 'header':
                        pattrs = " ".join([str(v) for v in parent.attrs.values()]).lower()
                        if any(k in pattrs for k in ['site', 'global', 'banner', 'main-header']):
                            return True
                        if parent.parent and parent.parent.name == 'body':
                            return True
                    if parent.name in ['section', 'div', 'aside']:
                        pattrs = " ".join([str(v) for v in parent.attrs.values()]).lower()
                        if any(k in pattrs for k in ['related', 'recommend', 'social', 'share']):
                            return True
                return False

            for img in full_soup.find_all('img'):
                if _is_in_excluded_section(img):
                    continue

                img_attrs_str = " ".join([str(v) for v in img.attrs.values()]).lower()
                is_featured = any(kw in img_attrs_str for kw in featured_keywords)

                if not is_featured:
                    for parent in img.parents:
                        if parent.name in ['body', 'html', '[document]']:
                            break
                        pattrs = " ".join([str(v) for v in parent.attrs.values()]).lower()
                        if any(kw in pattrs for kw in featured_keywords):
                            is_featured = True
                            break

                if not is_featured and og_img_url:
                    for attr in ['src', 'data-src', 'data-lazy-src']:
                        val = (img.get(attr) or '').strip()
                        if val and (val in og_img_url or og_img_url in val or val.split('/')[-1] == og_img_url.split('/')[-1]):
                            is_featured = True
                            break

                if is_featured:
                    src_candidates = [(img.get(a) or '').strip() for a in ['src', 'data-src', 'data-lazy-src'] if img.get(a)]
                    already_in_content = any(s in existing_img_srcs for s in src_candidates)
                    if not already_in_content:
                        featured_img_found = img
                        break

        total_imgs = len(img_elements)
        if featured_img_found is not None:
            total_imgs += 1
            feat_alt = featured_img_found.get('alt', '').strip()
            if feat_alt and feat_alt.lower() not in ['image', 'img', 'picture', 'photo']:
                imgs_with_alt += 1
                
        total_media = total_imgs + len(video_elements)
        media_score = 0.0
        status = ""
        
        if total_media > 0:
            if total_imgs > 0:
                if imgs_with_alt == total_imgs:
                    media_score = 100.0
                    status = "Optimized"
                elif imgs_with_alt > 0:
                    media_score = 70.0
                    status = "Partial Alt Text"
                else:
                    media_score = 50.0
                    status = "Missing Alt Text"
            else:
                media_score = 100.0
                status = "Video Content"
        else:
            media_score = 0.0
            status = "No Media"
            
        media_recs = []
        if total_media == 0:
            media_recs.append("Add relevant images or video to improve engagement.")
        if total_imgs > 0 and imgs_with_alt < total_imgs:
            media_recs.append("Ensure all images have descriptive 'alt' text.")
            
        if total_media == 0:
            media_icon = "❌"
        elif status in ["Partial Alt Text", "Missing Alt Text"]:
            media_icon = "⚠️"
        else:
            media_icon = "✅"
            
        breakdown.append(ScoreBreakdown(
            name="Multimedia Content",
            raw_score=media_score,
            weight=self.MULTIMEDIA_WEIGHT,
            weighted_score=media_score * self.MULTIMEDIA_WEIGHT,
            explanation=f"{media_icon} {status}: {total_media} items found.",
            recommendations=media_recs
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
            errors=errors
        )
