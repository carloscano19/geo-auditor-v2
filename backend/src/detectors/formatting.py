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
        
        html_lower = page_data.html_raw.lower()
        text_content = page_data.text_content
        
        # 1. Scannability (Lists & Tables) - 40% (DRACONIAN: No menus, no short lists)
        # ----------------------------------------------------------------
        all_lists = re.findall(r'<(ul|ol|table)([^>]*)>(.*?)</\1>', page_data.html_raw, re.IGNORECASE | re.DOTALL)
        
        valid_lists = []
        for tag, attrs, content in all_lists:
            # 1. Class/ID Blacklist
            attrs_lower = attrs.lower()
            blacklist = ['menu', 'nav', 'social', 'related', 'footer', 'share', 'breadcrumb']
            if any(kw in attrs_lower for kw in blacklist):
                continue
            
            # 2. Structure Check: Count <li> for lists
            if tag in ['ul', 'ol']:
                items = re.findall(r'<li[^>]*>(.*?)</li>', content, re.IGNORECASE | re.DOTALL)
                if len(items) <= 3:
                    continue
                
                # 3. Quality Check: Average words per item
                total_words = 0
                for item in items:
                    clean_item = re.sub(r'<[^>]+>', '', item).strip()
                    total_words += len(clean_item.split())
                
                avg_words = total_words / len(items) if items else 0
                if avg_words < 15:
                    continue
            else: # table
                # Check rows
                rows = re.findall(r'<tr[^>]*>', content, re.IGNORECASE)
                if len(rows) <= 3:
                    continue
                
            # If reached here, it's a "real" content list
            valid_lists.append(tag)
        
        total_lists = len(valid_lists)
        
        scannability_score = 100.0 if total_lists >= 1 else 0.0
        
        # Check for Text Walls (part of scannability here)
        # We assume text content is plain text. Splits by double newlines usually.
        # But `page_data.text_content` might be a single blob if not processed.
        # Let's rely on splitting by \n\n or analyzing paragraph tags if available in HTML.
        # Better: Count chars in P tags in HTML.
        p_tags = re.findall(r'<p[^>]*>(.*?)</p>', page_data.html_raw, re.IGNORECASE | re.DOTALL)
        text_walls_found = 0
        for p_content in p_tags:
            # Strip tags
            clean_text = re.sub(r'<[^>]+>', '', p_content).strip()
            if len(clean_text) > self.MAX_CHARS_PER_BLOCK:
                text_walls_found += 1
                
        # Text Wall Scoring Inversion (0=100, 1=50, 2+=0)
        wall_score = 100.0
        if text_walls_found == 1:
            wall_score = 50.0
        elif text_walls_found >= 2:
            wall_score = 0.0
            
        # Combine with list check (simplified for now as per user prompt context)
        # Lists give 100, walls penalized it.
        # User wants a general fix for 'Text Walls' score. 
        # In formatting.py, walls were a penalty. Let's make it a dedicated part or override.
        if total_lists >= 1:
            scannability_score = wall_score
        else:
            scannability_score = min(50.0, wall_score) # Penalize lack of lists too
            
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
        # Look for <strong> or <b> tags
        bold_tags = re.findall(r'<(strong|b)[^>]*>(.*?)</\1>', page_data.html_raw, re.IGNORECASE | re.DOTALL)
        
        bold_count = len(bold_tags)
        bold_score = 0.0
        bold_explanation = ""
        
        if bold_count == 0:
            bold_score = 0.0
            bold_explanation = "No bold functionality used."
        else:
            # Analyze quality: Are they short phrases?
            good_bolds = 0
            bad_bolds = 0 # Too long
            
            for _, content in bold_tags:
                clean_content = re.sub(r'<[^>]+>', '', content).strip()
                words = len(clean_content.split())
                if words > 15: # Arbitrary threshold for "Highlighter" abuse vs Sentence
                    bad_bolds += 1
                else:
                    good_bolds += 1
            
            if good_bolds >= 2:
                bold_score = 100.0
                bold_explanation = f"Found {good_bolds} keyword highlights."
            elif good_bolds == 1:
                bold_score = 50.0
                bold_explanation = "Found minimal highlighting."
            else:
                bold_score = 30.0 # Only long bolds
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
        # Only relevant for full HTML check (URL mode usually, but check content anyway)
        img_tags = re.findall(r'<img[^>]*>', html_lower)
        video_tags = re.findall(r'<(video|iframe|embed)[^>]*>', html_lower)
        
        has_media = False
        media_score = 0.0
        
        # Check Alt Text
        imgs_with_alt = 0
        for img in img_tags:
            if 'alt=' in img and 'alt=""' not in img and "alt=''" not in img:
                imgs_with_alt += 1
                
        total_media = len(img_tags) + len(video_tags)
        
        if total_media > 0:
            # Quality check: Images need Alt
            if len(img_tags) > 0:
                if imgs_with_alt == len(img_tags):
                    media_score = 100.0
                    status = "Optimized"
                elif imgs_with_alt > 0:
                    media_score = 70.0
                    status = "Partial Alt Text"
                else:
                    media_score = 50.0
                    status = "Missing Alt Text"
            else:
                # Just video?
                media_score = 100.0
                status = "Video Content"
        else:
            media_score = 0.0
            status = "No Media"
            
        media_recs = []
        if total_media == 0:
            media_recs.append("Add relevant images or video to improve engagement.")
        if len(img_tags) > 0 and imgs_with_alt < len(img_tags):
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
