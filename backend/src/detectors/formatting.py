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
    weight = 0.10
    
    # Text Wall Thresholds - GOLD STANDARD: Raised to 7 lines (~700 chars)
    MAX_CHARS_PER_BLOCK = 700  # Approx 7 lines / 100-120 words
    
    async def analyze(self, page_data: PageData) -> DetectorResult:
        breakdown = []
        errors = []
        recommendations = []
        
        from bs4 import BeautifulSoup
        html = page_data.html_rendered
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. Scannability (Lists & Tables) - 40%
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
            weight=0.40,
            weighted_score=scannability_score * 0.40,
            explanation=f"{'✅' if total_lists > 0 else '❌'} Found {total_lists} lists/tables. {'⚠️ ' + str(text_walls_found) + ' text walls.' if text_walls_found else ''}",
            recommendations=scan_recs
        ))
        
        # 2. Visual Hierarchy (Bold Highlights) - 30%
        # ----------------------------------------------------------------
        bold_elements = soup.find_all(['strong', 'b'])
        
        bold_count = len(bold_elements)
        bold_score = 0.0
        bold_explanation = ""
        
        if bold_count == 0:
            bold_score = 0.0
            bold_explanation = "No bold functionality used."
        else:
            good_bolds = 0
            for bold in bold_elements:
                clean_content = bold.get_text(strip=True)
                words = len(clean_content.split())
                if 1 <= words <= 15: # Highlighter length
                    good_bolds += 1
            
            if good_bolds >= 2:
                bold_score = 100.0
                bold_explanation = f"Found {good_bolds} keyword highlights."
            elif good_bolds == 1:
                bold_score = 50.0
                bold_explanation = "Found minimal highlighting."
            else:
                bold_score = 30.0
                bold_explanation = "Bold usage detected but texts are too long (scan-blockers)."
                
        bold_recs = []
        if bold_score < 80:
            bold_recs.append("Use bold (<strong>) to highlight key concepts, not full sentences.")
            
        breakdown.append(ScoreBreakdown(
            name="Bold Highlights",
            raw_score=bold_score,
            weight=0.30,
            weighted_score=bold_score * 0.30,
            explanation=f"{'✅' if bold_score >= 50 else '❌'} {bold_explanation}",
            recommendations=bold_recs
        ))
        
        # 3. Multimedia Content - 30%
        # ----------------------------------------------------------------
        img_elements = soup.find_all('img')
        video_elements = soup.find_all(['video', 'iframe', 'embed'])
        
        imgs_with_alt = 0
        for img in img_elements:
            alt = img.get('alt', '').strip()
            # Ignore placeholder alt or empty
            if alt and alt.lower() not in ['image', 'img', 'picture', 'photo']:
                imgs_with_alt += 1
                
        total_media = len(img_elements) + len(video_elements)
        media_score = 0.0
        status = ""
        
        if total_media > 0:
            if len(img_elements) > 0:
                if imgs_with_alt == len(img_elements):
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
        if len(img_elements) > 0 and imgs_with_alt < len(img_elements):
            media_recs.append("Ensure all images have descriptive 'alt' text.")
            
        breakdown.append(ScoreBreakdown(
            name="Multimedia Content",
            raw_score=media_score,
            weight=0.30,
            weighted_score=media_score * 0.30,
            explanation=f"{'✅' if total_media > 0 else '❌'} {status}: {total_media} items found.",
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
