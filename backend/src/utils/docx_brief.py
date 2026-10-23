"""
GEO-AUDITOR AI - Word (.docx) Editor Brief Generator

Generates a content brief in Microsoft Word format (.docx) tailored for
non-technical editors, including:
1. Title with URL, date, content type, and Citation Score.
2. Top actions: max 8 submetrics with worst impact (dimension_weight * (100 - score)),
   excluding technical submetrics, with friendly names and recommendations.
3. Suggested opening paragraph (if Quick fixes present) with original and suggested.
4. Plan sections in screen order (inconsistencies, questions, H2 structure,
   suggested table, data opportunities, sources to cite, paragraphs to add),
   each with its explanatory note in italics.
5. "For the developer" annex with Quick fixes JSON-LD and Plan combined schema in monospaced font.
6. Footer: "AI-generated suggestions. Review before publishing. They do not affect the Citation Score."
"""

import io
import ipaddress
import json
import socket
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, urljoin

import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from src.models.schemas import (
    AuditResponse,
    AIFixesResponse,
    AIPlanResponse,
    AhrefsOffpageResponse,
    AhrefsLinkingPage,
    DetectorResult,
    ScoreBreakdown,
)

# Dimensions excluded from Top Actions (technical, cannot be touched by content editors)
EXCLUDED_TECHNICAL_DIMENSIONS = {
    "technical_infrastructure",
    "metadata_schema",
}

# Submetric keywords to exclude if they appear in other dimensions
EXCLUDED_SUBMETRIC_KEYWORDS = {
    "https",
    "render",
    "crawl",
    "bot",
    "speed",
    "schema",
}

# Mapping of technical submetric names to friendly editor-oriented names
FRIENDLY_SUBMETRIC_NAMES: Dict[str, str] = {
    "Rule of 60 (Answer First)": "Answer First in Intro",
    "Interrogative H2s": "Question-based Headings",
    "Heading Hierarchy": "Heading Structure",
    "Power Lead (Entity in Lead)": "Main Topic in Opening Sentence",
    "Lexical Richness (MTLD)": "Vocabulary Variety",
    "Autonomous Passages": "Self-contained Sections",
    "Complete Sentences": "Complete Sentences",
    "Content Depth": "Content Depth & Substance",
    "Evidence Density": "Facts & Evidence Density",
    "Numeric Specificity": "Specific Data & Figures",
    "Attribution Signals": "Source Attributions",
    "Author Signals": "Author Information",
    "Freshness Signals": "Publication & Update Dates",
    "Formatting Citability": "Scannable Formatting",
    "Links Verifiability": "Source Links & Citations",
    "Direct Answers": "Direct Answers",
    "Query Relevance": "Search Query Relevance",
    "Keyword Coverage": "Topic Coverage",
    "Entity Identification": "Clear Key Entities",
    "Trust Pages": "About & Editorial Policy",
}


def sanitize_domain_for_filename(url: str) -> str:
    """Extract clean domain for filename: e.g. 'carloscanofernandez.com'."""
    try:
        if not url or url == "text-mode":
            return "text-content"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        cleaned = "".join(c if c.isalnum() or c in ".-" else "_" for c in domain)
        return cleaned.strip(".-_") or "site"
    except Exception:
        return "site"


def get_top_non_technical_actions(
    detector_results: List[DetectorResult], max_actions: int = 8
) -> List[Tuple[str, str, float]]:
    """
    Calculate top non-technical submetrics by impact:
    impact = detector.weight * (100.0 - submetric.raw_score).
    Returns list of (friendly_name, recommendation, impact).
    """
    candidates = []

    for det in detector_results:
        dim = getattr(det, "dimension", "")
        if dim in EXCLUDED_TECHNICAL_DIMENSIONS:
            continue

        raw_w = getattr(det, "weight", None)
        det_weight = 0.10 if raw_w is None else float(raw_w)
        breakdowns = getattr(det, "breakdown", []) or []

        for b in breakdowns:
            name = getattr(b, "name", "")
            raw = getattr(b, "raw_score", None)
            raw_score = 100.0 if raw is None else float(raw)

            # Check if name contains technical keywords
            name_lower = name.lower()
            if any(kw in name_lower for kw in EXCLUDED_SUBMETRIC_KEYWORDS):
                continue

            # Only consider submetrics with raw_score < 70 and with at least one recommendation
            if raw_score >= 70.0:
                continue

            recs = getattr(b, "recommendations", []) or []
            valid_recs = [r.strip() for r in recs if isinstance(r, str) and r.strip()]
            if not valid_recs:
                continue
            rec_text = valid_recs[0]

            impact = det_weight * (100.0 - raw_score)
            friendly_name = FRIENDLY_SUBMETRIC_NAMES.get(name, name)
            candidates.append((friendly_name, rec_text, impact))

    # Merge Heading Structure and Text Walls if both are among candidates
    heading_cand = None
    text_walls_cand = None
    for c in candidates:
        if c[0] == "Heading Structure" and heading_cand is None:
            heading_cand = c
        elif c[0] == "Text Walls" and text_walls_cand is None:
            text_walls_cand = c

    if heading_cand is not None and text_walls_cand is not None:
        merged_impact = max(heading_cand[2], text_walls_cand[2])
        merged_rec = heading_cand[1]
        merged_action = ("Add H2 headings to break up the text", merged_rec, merged_impact)
        candidates = [c for c in candidates if c is not heading_cand and c is not text_walls_cand]
        candidates.append(merged_action)

    # Sort descending by impact
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[:max_actions]


def set_cell_background(cell, color_hex: str):
    """Set shading color for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Set cell padding in twentieths of a point (dxa)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def add_callout(doc: Document, text: str, title: Optional[str] = None):
    """Add a shaded callout block for notes or disclaimers."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "F3F4F6")
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15

    if title:
        run_title = p.add_run(f"{title}\n")
        run_title.bold = True
        run_title.font.size = Pt(10)
        run_title.font.color.rgb = RGBColor(55, 65, 81)

    run = p.add_run(text)
    run.font.size = Pt(9.5)
    run.font.italic = True
    run.font.color.rgb = RGBColor(75, 85, 99)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)


def generate_editor_brief_docx(
    audit_result: AuditResponse,
    ai_fixes: Optional[AIFixesResponse] = None,
    ai_plan: Optional[AIPlanResponse] = None,
    ahrefs_offpage: Optional[AhrefsOffpageResponse] = None,
) -> bytes:
    """
    Build the complete Word (.docx) document and return as raw bytes.
    """
    doc = Document()

    # Set standard margins (1 inch)
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # 1. Document Title & Header
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    run_title = title_p.add_run("Content improvement report")
    run_title.font.name = "Arial"
    run_title.font.size = Pt(24)
    run_title.bold = True
    run_title.font.color.rgb = RGBColor(17, 24, 39)

    # Metadata subtitle
    meta_p = doc.add_paragraph()
    meta_p.paragraph_format.space_after = Pt(14)
    meta_p.paragraph_format.line_spacing = 1.25

    # Content type formatting
    ct_map = {
        "guide_blog": "Guide / Blog",
        "news": "News / Press",
        "review": "Review",
        "product": "Product",
    }
    content_type_str = ct_map.get(audit_result.content_type, audit_result.content_type or "Guide / Blog")
    
    # Date formatting
    date_str = audit_result.analyzed_at.strftime("%B %d, %Y") if hasattr(audit_result.analyzed_at, "strftime") else str(audit_result.analyzed_at)
    score_display = f"Citation Score: {audit_result.total_score:.0f}/100"

    run_url = meta_p.add_run(f"URL: {audit_result.url}\n")
    run_url.font.size = Pt(10)
    run_url.font.color.rgb = RGBColor(75, 85, 99)

    run_meta = meta_p.add_run(f"Date: {date_str}   |   Type: {content_type_str}   |   ")
    run_meta.font.size = Pt(10)
    run_meta.font.color.rgb = RGBColor(75, 85, 99)

    run_score = meta_p.add_run(score_display)
    run_score.font.size = Pt(10.5)
    run_score.bold = True
    if audit_result.total_score >= 80:
        run_score.font.color.rgb = RGBColor(16, 120, 70)
    elif audit_result.total_score >= 50:
        run_score.font.color.rgb = RGBColor(180, 100, 10)
    else:
        run_score.font.color.rgb = RGBColor(190, 30, 30)

    # 1.1 Notes / Plan Warnings (if any)
    if ai_plan and ai_plan.warnings and len(ai_plan.warnings) > 0:
        h2_notes = doc.add_heading(level=1)
        h2_notes.paragraph_format.space_before = Pt(8)
        h2_notes.paragraph_format.space_after = Pt(4)
        run_h2_notes = h2_notes.add_run("Notes")
        run_h2_notes.font.name = "Arial"
        run_h2_notes.font.size = Pt(14)
        run_h2_notes.bold = True
        run_h2_notes.font.color.rgb = RGBColor(180, 83, 9)

        for w in ai_plan.warnings:
            p_w = doc.add_paragraph(style="List Bullet")
            p_w.paragraph_format.space_before = Pt(1)
            p_w.paragraph_format.space_after = Pt(2)
            r_w = p_w.add_run(w)
            r_w.font.name = "Arial"
            r_w.font.size = Pt(9.5)
            r_w.font.color.rgb = RGBColor(146, 64, 14)

    # 2. Top actions (Max 8 non-technical)
    h2_actions = doc.add_heading(level=1)
    h2_actions.paragraph_format.space_before = Pt(12)
    h2_actions.paragraph_format.space_after = Pt(4)
    run_h2 = h2_actions.add_run("Top actions")
    run_h2.font.name = "Arial"
    run_h2.font.size = Pt(16)
    run_h2.bold = True
    run_h2.font.color.rgb = RGBColor(31, 41, 55)

    sub_actions = doc.add_paragraph()
    sub_actions.paragraph_format.space_after = Pt(8)
    run_sub = sub_actions.add_run(
        "Priority content improvements ranked by their direct impact on AI engine citation."
    )
    run_sub.font.italic = True
    run_sub.font.size = Pt(9.5)
    run_sub.font.color.rgb = RGBColor(107, 114, 128)

    top_actions = get_top_non_technical_actions(audit_result.detector_results, max_actions=8)
    if top_actions:
        for friendly_name, rec, _impact in top_actions:
            bullet = doc.add_paragraph(style="List Bullet")
            bullet.paragraph_format.space_before = Pt(2)
            bullet.paragraph_format.space_after = Pt(4)
            bullet.paragraph_format.line_spacing = 1.15
            
            run_name = bullet.add_run(f"{friendly_name}: ")
            run_name.bold = True
            run_name.font.size = Pt(10)
            run_name.font.color.rgb = RGBColor(17, 24, 39)
            
            run_rec = bullet.add_run(rec)
            run_rec.font.size = Pt(10)
            run_rec.font.color.rgb = RGBColor(55, 65, 81)
    else:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run("No high-priority content actions needed! The page content meets all quality thresholds.")
        r.font.size = Pt(10)
        r.font.italic = True

    # 2.1 Off-page signals (Ahrefs) (if Ahrefs data present)
    if ahrefs_offpage:
        h2_offpage = doc.add_heading(level=1)
        h2_offpage.paragraph_format.space_before = Pt(16)
        h2_offpage.paragraph_format.space_after = Pt(4)
        run_h2_off = h2_offpage.add_run("Off-page signals (Ahrefs)")
        run_h2_off.font.name = "Arial"
        run_h2_off.font.size = Pt(16)
        run_h2_off.bold = True
        run_h2_off.font.color.rgb = RGBColor(31, 41, 55)

        sub_off = doc.add_paragraph()
        sub_off.paragraph_format.space_after = Pt(8)
        run_sub_off = sub_off.add_run("Data from Ahrefs. Not included in the Citation Score.")
        run_sub_off.font.italic = True
        run_sub_off.font.size = Pt(9.5)
        run_sub_off.font.color.rgb = RGBColor(107, 114, 128)

        # Off-page Metrics Table
        table_off = doc.add_table(rows=1, cols=2)
        table_off.alignment = WD_TABLE_ALIGNMENT.CENTER
        table_off.autofit = True

        hdr_cells = table_off.rows[0].cells
        hdr_cells[0].text = "Signal"
        hdr_cells[1].text = "Value"
        for c in hdr_cells:
            set_cell_background(c, "F9FAFB")
            set_cell_margins(c, 100, 100, 150, 150)
            for p in c.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(9.5)
                    r.font.color.rgb = RGBColor(55, 65, 81)

        def _fmt(v: Any) -> str:
            if v is None:
                return "n/a"
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            if isinstance(v, (int, float)):
                return f"{v:,.0f}" if isinstance(v, int) else f"{v:,.1f}"
            return str(v)

        metrics_list = [
            ("Domain Rating", _fmt(ahrefs_offpage.domain_rating)),
            ("URL Rating", _fmt(ahrefs_offpage.url_rating)),
            ("Referring domains", _fmt(ahrefs_offpage.referring_domains)),
            ("Backlinks", _fmt(ahrefs_offpage.backlinks)),
            ("Organic keywords", _fmt(ahrefs_offpage.organic_keywords)),
            ("Top 3 keywords", _fmt(ahrefs_offpage.top3_keywords)),
            ("Organic traffic/month", _fmt(ahrefs_offpage.organic_traffic)),
        ]

        for label, val_str in metrics_list:
            row_cells = table_off.add_row().cells
            row_cells[0].text = label
            row_cells[1].text = val_str
            for c in row_cells:
                set_cell_margins(c, 80, 80, 150, 150)
                for p in c.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(9.5)
                        r.font.color.rgb = RGBColor(55, 65, 81)
            for p in row_cells[1].paragraphs:
                for r in p.runs:
                    r.bold = True

        doc.add_paragraph().paragraph_format.space_after = Pt(4)

        if ahrefs_offpage.recommendations:
            p_rec_title = doc.add_paragraph()
            p_rec_title.paragraph_format.space_before = Pt(6)
            p_rec_title.paragraph_format.space_after = Pt(2)
            r_rec_title = p_rec_title.add_run("Off-page recommendations:")
            r_rec_title.bold = True
            r_rec_title.font.size = Pt(10)
            r_rec_title.font.color.rgb = RGBColor(31, 41, 55)

            for rec in ahrefs_offpage.recommendations:
                b_rec = doc.add_paragraph(style="List Bullet")
                b_rec.paragraph_format.space_before = Pt(2)
                b_rec.paragraph_format.space_after = Pt(4)
                r_b = b_rec.add_run(rec)
                r_b.font.size = Pt(9.5)
                r_b.font.color.rgb = RGBColor(55, 65, 81)

        # Backlinks Table ("Who links to this page")
        if ahrefs_offpage.linking_pages:
            p_bl_title = doc.add_paragraph()
            p_bl_title.paragraph_format.space_before = Pt(10)
            p_bl_title.paragraph_format.space_after = Pt(4)
            r_bl_title = p_bl_title.add_run("Who links to this page:")
            r_bl_title.bold = True
            r_bl_title.font.size = Pt(10)
            r_bl_title.font.color.rgb = RGBColor(31, 41, 55)

            table_bl = doc.add_table(rows=1, cols=6)
            table_bl.alignment = WD_TABLE_ALIGNMENT.CENTER
            table_bl.autofit = True

            bl_hdr = table_bl.rows[0].cells
            bl_hdr_titles = ["Domain", "DR", "Linking page", "Anchor", "Type", "First seen"]
            for idx, title in enumerate(bl_hdr_titles):
                bl_hdr[idx].text = title
                set_cell_background(bl_hdr[idx], "F9FAFB")
                set_cell_margins(bl_hdr[idx], 80, 80, 100, 100)
                for p in bl_hdr[idx].paragraphs:
                    for r in p.runs:
                        r.bold = True
                        r.font.size = Pt(8.5)
                        r.font.color.rgb = RGBColor(55, 65, 81)

            for lp in ahrefs_offpage.linking_pages[:20]:
                r_cells = table_bl.add_row().cells
                is_sp = getattr(lp, "spam", False) if not isinstance(lp, dict) else lp.get("spam", False)
                dom = (getattr(lp, "domain", "") if not isinstance(lp, dict) else lp.get("domain", "")) or ""
                dom_display = f"{dom} [Spam]" if is_sp else dom
                dr_val = getattr(lp, "domain_rating", None) if not isinstance(lp, dict) else lp.get("domain_rating")
                url_f = (getattr(lp, "url_from", "") if not isinstance(lp, dict) else lp.get("url_from", "")) or ""
                anch = (getattr(lp, "anchor", "") if not isinstance(lp, dict) else lp.get("anchor", "")) or "—"
                is_df = getattr(lp, "dofollow", False) if not isinstance(lp, dict) else lp.get("dofollow", False)
                type_str = "Dofollow" if is_df else "Nofollow"
                if is_sp:
                    type_str += " (Spam)"
                fseen = (getattr(lp, "first_seen", "") if not isinstance(lp, dict) else lp.get("first_seen", "")) or "—"

                r_cells[0].text = dom_display
                r_cells[1].text = _fmt(dr_val)
                r_cells[2].text = url_f
                r_cells[3].text = anch
                r_cells[4].text = type_str
                r_cells[5].text = fseen

                for c in r_cells:
                    set_cell_margins(c, 60, 60, 100, 100)
                    for p in c.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(8)
                            r.font.color.rgb = RGBColor(55, 65, 81)

    # 3. Suggested opening paragraph (from Plan or Quick fixes)
    lp = None
    if ai_plan and getattr(ai_plan, "suggested_lead", None):
        lp = ai_plan.suggested_lead
    elif ai_fixes and ai_fixes.lead_paragraph:
        lp = ai_fixes.lead_paragraph

    if lp:
        h2_lead = doc.add_heading(level=1)
        h2_lead.paragraph_format.space_before = Pt(16)
        h2_lead.paragraph_format.space_after = Pt(4)
        run_h2_lead = h2_lead.add_run("Suggested opening paragraph")
        run_h2_lead.font.name = "Arial"
        run_h2_lead.font.size = Pt(16)
        run_h2_lead.bold = True
        run_h2_lead.font.color.rgb = RGBColor(31, 41, 55)

        sub_lead = doc.add_paragraph()
        sub_lead.paragraph_format.space_after = Pt(8)
        run_sub_lead = sub_lead.add_run(
            "Rewrite the opening paragraph to answer the primary topic immediately (inverted pyramid structure)."
        )
        run_sub_lead.font.italic = True
        run_sub_lead.font.size = Pt(9.5)
        run_sub_lead.font.color.rgb = RGBColor(107, 114, 128)

        if lp.original:
            p_orig = doc.add_paragraph()
            p_orig.paragraph_format.space_before = Pt(4)
            p_orig.paragraph_format.space_after = Pt(2)
            run_lbl_orig = p_orig.add_run("Original opening:\n")
            run_lbl_orig.bold = True
            run_lbl_orig.font.size = Pt(10)
            run_lbl_orig.font.color.rgb = RGBColor(107, 114, 128)
            run_txt_orig = p_orig.add_run(f"\"{lp.original}\"")
            run_txt_orig.font.size = Pt(10)
            run_txt_orig.font.color.rgb = RGBColor(107, 114, 128)

        p_sug = doc.add_paragraph()
        p_sug.paragraph_format.space_before = Pt(4)
        p_sug.paragraph_format.space_after = Pt(4)
        run_lbl_sug = p_sug.add_run("Suggested revision:\n")
        run_lbl_sug.bold = True
        run_lbl_sug.font.size = Pt(10.5)
        run_lbl_sug.font.color.rgb = RGBColor(16, 120, 70)
        run_txt_sug = p_sug.add_run(f"\"{lp.suggested}\"")
        run_txt_sug.font.size = Pt(10.5)
        run_txt_sug.bold = True
        run_txt_sug.font.color.rgb = RGBColor(17, 24, 39)

        if lp.rationale:
            p_rat = doc.add_paragraph()
            p_rat.paragraph_format.space_after = Pt(8)
            run_lbl_rat = p_rat.add_run("Rationale: ")
            run_lbl_rat.bold = True
            run_lbl_rat.font.size = Pt(9.5)
            run_lbl_rat.font.color.rgb = RGBColor(75, 85, 99)
            run_txt_rat = p_rat.add_run(lp.rationale)
            run_txt_rat.font.size = Pt(9.5)
            run_txt_rat.font.italic = True
            run_txt_rat.font.color.rgb = RGBColor(75, 85, 99)

    # 4. Plan Sections (if AI Plan present)
    if ai_plan:
        # 4.1 Inconsistencies found on the page
        if ai_plan.inconsistencies and len(ai_plan.inconsistencies) > 0:
            h2_inc = doc.add_heading(level=1)
            h2_inc.paragraph_format.space_before = Pt(16)
            h2_inc.paragraph_format.space_after = Pt(4)
            run_h2_inc = h2_inc.add_run("Inconsistencies found on the page")
            run_h2_inc.font.name = "Arial"
            run_h2_inc.font.size = Pt(16)
            run_h2_inc.bold = True
            run_h2_inc.font.color.rgb = RGBColor(31, 41, 55)

            sub_inc = doc.add_paragraph()
            sub_inc.paragraph_format.space_after = Pt(8)
            run_sub_inc = sub_inc.add_run(
                "The page contradicts itself here. Pick one version and use it everywhere, so AI engines extract a single answer."
            )
            run_sub_inc.font.italic = True
            run_sub_inc.font.size = Pt(9.5)
            run_sub_inc.font.color.rgb = RGBColor(107, 114, 128)

            for inc in ai_plan.inconsistencies:
                p_inc = doc.add_paragraph(style="List Bullet")
                p_inc.paragraph_format.space_before = Pt(2)
                p_inc.paragraph_format.space_after = Pt(4)
                
                r_issue = p_inc.add_run(f"{inc.issue}\n")
                r_issue.bold = True
                r_issue.font.size = Pt(10)
                
                vals_str = " vs ".join([f"\"{v}\"" for v in inc.values])
                r_vals = p_inc.add_run(f"Conflicting values: {vals_str}\n")
                r_vals.font.size = Pt(9.5)
                r_vals.font.color.rgb = RGBColor(180, 50, 50)
                
                r_sug = p_inc.add_run(f"Recommendation: {inc.suggestion}")
                r_sug.font.size = Pt(9.5)
                r_sug.font.color.rgb = RGBColor(55, 65, 81)

        # 4.2 Questions your page should answer
        if ai_plan.questions_to_answer and len(ai_plan.questions_to_answer) > 0:
            h2_q = doc.add_heading(level=1)
            h2_q.paragraph_format.space_before = Pt(16)
            h2_q.paragraph_format.space_after = Pt(4)
            run_h2_q = h2_q.add_run("Questions your page should answer")
            run_h2_q.font.name = "Arial"
            run_h2_q.font.size = Pt(16)
            run_h2_q.bold = True
            run_h2_q.font.color.rgb = RGBColor(31, 41, 55)

            sub_q = doc.add_paragraph()
            sub_q.paragraph_format.space_after = Pt(8)
            run_sub_q = sub_q.add_run(
                "Add these as an FAQ block. Short, direct answers are what AI engines quote."
            )
            run_sub_q.font.italic = True
            run_sub_q.font.size = Pt(9.5)
            run_sub_q.font.color.rgb = RGBColor(107, 114, 128)

            for q in ai_plan.questions_to_answer:
                p_q = doc.add_paragraph()
                p_q.paragraph_format.space_before = Pt(4)
                p_q.paragraph_format.space_after = Pt(2)

                # Badge text
                badge = (
                    "Info already on the page — rewrite it as a Q&A"
                    if q.answer_source == "page"
                    else "Missing from the page — needs new content"
                )
                paa_extra = " · Real Google question" if q.origin == "google_paa" else ""

                r_qtitle = p_q.add_run(f"Q: {q.question}\n")
                r_qtitle.bold = True
                r_qtitle.font.size = Pt(10.5)
                r_qtitle.font.color.rgb = RGBColor(17, 24, 39)

                r_qbadge = p_q.add_run(f"[{badge}{paa_extra}]\n")
                r_qbadge.font.size = Pt(9)
                r_qbadge.bold = True
                if q.answer_source == "page":
                    r_qbadge.font.color.rgb = RGBColor(16, 120, 70)
                else:
                    r_qbadge.font.color.rgb = RGBColor(180, 100, 10)

                # Check if draft answer contains [EDITOR: ...] gaps
                r_prefix = p_q.add_run("A: ")
                r_prefix.font.size = Pt(10)
                r_prefix.font.color.rgb = RGBColor(55, 65, 81)

                import re
                chunks = re.split(r'(\[EDITOR:[^\]]*\])', q.draft_answer)
                for chunk in chunks:
                    if not chunk:
                        continue
                    r_chunk = p_q.add_run(chunk)
                    r_chunk.font.size = Pt(10)
                    if chunk.startswith("[EDITOR:") and chunk.endswith("]"):
                        r_chunk.font.highlight_color = WD_COLOR_INDEX.YELLOW
                        r_chunk.bold = True
                        r_chunk.font.color.rgb = RGBColor(140, 70, 0)
                    else:
                        r_chunk.font.color.rgb = RGBColor(55, 65, 81)

        # 4.3 Suggested H2 structure
        if ai_plan.suggested_h2_structure and len(ai_plan.suggested_h2_structure) > 0:
            h2_h2 = doc.add_heading(level=1)
            h2_h2.paragraph_format.space_before = Pt(16)
            h2_h2.paragraph_format.space_after = Pt(4)
            run_h2_h2 = h2_h2.add_run("Suggested H2 structure")
            run_h2_h2.font.name = "Arial"
            run_h2_h2.font.size = Pt(16)
            run_h2_h2.bold = True
            run_h2_h2.font.color.rgb = RGBColor(31, 41, 55)

            sub_h2 = doc.add_paragraph()
            sub_h2.paragraph_format.space_after = Pt(8)
            run_sub_h2 = sub_h2.add_run(
                "Use these headings to organise the page. 'Already on the page' means keep it as is. 'Exists — add the heading' means the topic is discussed but needs an H2. 'New' means the section has to be written."
            )
            run_sub_h2.font.italic = True
            run_sub_h2.font.size = Pt(9.5)
            run_sub_h2.font.color.rgb = RGBColor(107, 114, 128)

            for item in ai_plan.suggested_h2_structure:
                p_item = doc.add_paragraph(style="List Bullet")
                p_item.paragraph_format.space_before = Pt(2)
                p_item.paragraph_format.space_after = Pt(3)

                if item.status == "present":
                    status_label = "Already on the page — keep it"
                    badge_color = RGBColor(16, 120, 70)
                elif item.status == "rename":
                    status_label = f"Already on the page — consider renaming to: {item.h2}"
                    badge_color = RGBColor(217, 119, 6)
                elif item.status == "existing":
                    status_label = "Exists — add the heading"
                    badge_color = RGBColor(107, 114, 128)
                else:
                    status_label = "New — write this section"
                    badge_color = RGBColor(100, 100, 180)

                r_title = p_item.add_run(f"{item.h2} ")
                r_title.bold = True
                r_title.font.size = Pt(10)
                r_title.font.color.rgb = RGBColor(17, 24, 39)

                r_st = p_item.add_run(f"[{status_label}]\n")
                r_st.font.size = Pt(9)
                r_st.bold = True
                r_st.font.color.rgb = badge_color

                r_purp = p_item.add_run(f"Purpose: {item.purpose}")
                r_purp.font.size = Pt(9.5)
                r_purp.font.color.rgb = RGBColor(75, 85, 99)

        # 4.4 Suggested table
        if ai_plan.suggested_table:
            st = ai_plan.suggested_table
            h2_tbl = doc.add_heading(level=1)
            h2_tbl.paragraph_format.space_before = Pt(16)
            h2_tbl.paragraph_format.space_after = Pt(4)
            run_h2_tbl = h2_tbl.add_run(f"Suggested table: {st.title}")
            run_h2_tbl.font.name = "Arial"
            run_h2_tbl.font.size = Pt(16)
            run_h2_tbl.bold = True
            run_h2_tbl.font.color.rgb = RGBColor(31, 41, 55)

            sub_tbl = doc.add_paragraph()
            sub_tbl.paragraph_format.space_after = Pt(8)
            run_sub_tbl = sub_tbl.add_run(
                "Add this table to the page. All values come from the page itself."
            )
            run_sub_tbl.font.italic = True
            run_sub_tbl.font.size = Pt(9.5)
            run_sub_tbl.font.color.rgb = RGBColor(107, 114, 128)

            if st.headers and st.rows and len(st.rows) > 0:
                tbl = doc.add_table(rows=len(st.rows) + 1, cols=len(st.headers))
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                tbl.autofit = True

                # Header row
                hdr_cells = tbl.rows[0].cells
                for i, header_text in enumerate(st.headers):
                    cell = hdr_cells[i]
                    set_cell_background(cell, "E5E7EB")
                    set_cell_margins(cell, top=100, bottom=100, left=120, right=120)
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    r = p.add_run(str(header_text))
                    r.bold = True
                    r.font.size = Pt(9.5)
                    r.font.color.rgb = RGBColor(17, 24, 39)

                # Data rows
                for r_idx, row_data in enumerate(st.rows):
                    row_cells = tbl.rows[r_idx + 1].cells
                    for c_idx, cell_value in enumerate(row_data):
                        if c_idx < len(row_cells):
                            cell = row_cells[c_idx]
                            set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
                            # Alternate row shading
                            if r_idx % 2 == 1:
                                set_cell_background(cell, "F9FAFB")
                            p = cell.paragraphs[0]
                            p.paragraph_format.space_before = Pt(0)
                            p.paragraph_format.space_after = Pt(0)
                            r = p.add_run(str(cell_value))
                            r.font.size = Pt(9.5)
                            r.font.color.rgb = RGBColor(55, 65, 81)

                doc.add_paragraph().paragraph_format.space_after = Pt(6)
            elif st.table_idea:
                p_idea = doc.add_paragraph()
                p_idea.paragraph_format.space_after = Pt(6)
                r_lbl = p_idea.add_run("Table Idea: ")
                r_lbl.bold = True
                r_lbl.font.size = Pt(10)
                r_txt = p_idea.add_run(st.table_idea)
                r_txt.font.size = Pt(10)
                r_txt.font.italic = True

        # 4.5 Data that would enrich the text
        if ai_plan.data_opportunities and len(ai_plan.data_opportunities) > 0:
            h2_data = doc.add_heading(level=1)
            h2_data.paragraph_format.space_before = Pt(16)
            h2_data.paragraph_format.space_after = Pt(4)
            run_h2_data = h2_data.add_run("Data that would enrich the text")
            run_h2_data.font.name = "Arial"
            run_h2_data.font.size = Pt(16)
            run_h2_data.bold = True
            run_h2_data.font.color.rgb = RGBColor(31, 41, 55)

            sub_data = doc.add_paragraph()
            sub_data.paragraph_format.space_after = Pt(8)
            run_sub_data = sub_data.add_run(
                "Information worth adding. No figures are suggested: find them in the type of source shown."
            )
            run_sub_data.font.italic = True
            run_sub_data.font.size = Pt(9.5)
            run_sub_data.font.color.rgb = RGBColor(107, 114, 128)

            for d in ai_plan.data_opportunities:
                p_d = doc.add_paragraph(style="List Bullet")
                p_d.paragraph_format.space_before = Pt(2)
                p_d.paragraph_format.space_after = Pt(3)

                r_sug = p_d.add_run(f"{d.suggestion} ")
                r_sug.bold = True
                r_sug.font.size = Pt(10)
                r_sug.font.color.rgb = RGBColor(17, 24, 39)

                r_src = p_d.add_run(f"(Recommended Source: {d.source_type})")
                r_src.font.size = Pt(9.5)
                r_src.font.italic = True
                r_src.font.color.rgb = RGBColor(75, 85, 99)

        # 4.6 Sources to cite or link
        if ai_plan.sources_to_cite and len(ai_plan.sources_to_cite) > 0:
            h2_src = doc.add_heading(level=1)
            h2_src.paragraph_format.space_before = Pt(16)
            h2_src.paragraph_format.space_after = Pt(4)
            run_h2_src = h2_src.add_run("Sources to cite or link")
            run_h2_src.font.name = "Arial"
            run_h2_src.font.size = Pt(16)
            run_h2_src.bold = True
            run_h2_src.font.color.rgb = RGBColor(31, 41, 55)

            sub_src = doc.add_paragraph()
            sub_src.paragraph_format.space_after = Pt(8)
            run_sub_src = sub_src.add_run(
                "Real pages that Google ranks or cites for this topic. Link or cite the relevant ones."
            )
            run_sub_src.font.italic = True
            run_sub_src.font.size = Pt(9.5)
            run_sub_src.font.color.rgb = RGBColor(107, 114, 128)

            for s in ai_plan.sources_to_cite:
                p_s = doc.add_paragraph(style="List Bullet")
                p_s.paragraph_format.space_before = Pt(2)
                p_s.paragraph_format.space_after = Pt(4)

                title_text = s.title if s.title else s.domain
                r_title = p_s.add_run(f"{title_text} ({s.domain})\n")
                r_title.bold = True
                r_title.font.size = Pt(10)
                r_title.font.color.rgb = RGBColor(17, 24, 39)

                r_url = p_s.add_run(f"URL: {s.url}\n")
                r_url.font.size = Pt(9)
                r_url.font.color.rgb = RGBColor(37, 99, 235)

                found_label = s.found_in if s.found_in else "Organic top 10"
                r_found = p_s.add_run(f"Found in: {found_label}\n")
                r_found.font.size = Pt(9)
                r_found.font.color.rgb = RGBColor(107, 114, 128)

                if s.why:
                    r_why = p_s.add_run(f"Why: {s.why}")
                    r_why.font.size = Pt(9.5)
                    r_why.font.italic = True
                    r_why.font.color.rgb = RGBColor(75, 85, 99)

        # 4.7 Paragraphs to add
        if ai_plan.paragraphs_to_add and len(ai_plan.paragraphs_to_add) > 0:
            h2_p = doc.add_heading(level=1)
            h2_p.paragraph_format.space_before = Pt(16)
            h2_p.paragraph_format.space_after = Pt(4)
            run_h2_p = h2_p.add_run("Paragraphs to add")
            run_h2_p.font.name = "Arial"
            run_h2_p.font.size = Pt(16)
            run_h2_p.bold = True
            run_h2_p.font.color.rgb = RGBColor(31, 41, 55)

            sub_p = doc.add_paragraph()
            sub_p.paragraph_format.space_after = Pt(8)
            run_sub_p = sub_p.add_run(
                "Ready-to-paste paragraphs, written only with facts from the page."
            )
            run_sub_p.font.italic = True
            run_sub_p.font.size = Pt(9.5)
            run_sub_p.font.color.rgb = RGBColor(107, 114, 128)

            for i, p_item in enumerate(ai_plan.paragraphs_to_add, 1):
                p_para = doc.add_paragraph()
                p_para.paragraph_format.space_before = Pt(6)
                p_para.paragraph_format.space_after = Pt(2)

                r_head = p_para.add_run(f"Paragraph {i}: Addressing \"{p_item.target_issue}\"\n")
                r_head.bold = True
                r_head.font.size = Pt(10.5)
                r_head.font.color.rgb = RGBColor(17, 24, 39)

                r_place = p_para.add_run(f"Placement: {p_item.placement}\n")
                r_place.font.size = Pt(9.5)
                r_place.font.italic = True
                r_place.font.color.rgb = RGBColor(107, 114, 128)

                # Shaded text block for the paragraph
                add_callout(doc, p_item.suggested_text)

    # 5. Annex: "For the developer" (Schema.org JSON-LD)
    dev_schema = None
    if ai_plan and ai_plan.combined_schema:
        dev_schema = ai_plan.combined_schema
    elif ai_fixes and ai_fixes.json_ld:
        dev_schema = ai_fixes.json_ld

    if dev_schema:
        h2_dev = doc.add_heading(level=1)
        h2_dev.paragraph_format.space_before = Pt(20)
        h2_dev.paragraph_format.space_after = Pt(4)
        run_h2_dev = h2_dev.add_run("For the developer")
        run_h2_dev.font.name = "Arial"
        run_h2_dev.font.size = Pt(16)
        run_h2_dev.bold = True
        run_h2_dev.font.color.rgb = RGBColor(31, 41, 55)

        sub_dev = doc.add_paragraph()
        sub_dev.paragraph_format.space_after = Pt(8)
        run_sub_dev = sub_dev.add_run(
            "Structured Data (Schema.org JSON-LD) to add inside <script type=\"application/ld+json\"> in the page <head>."
        )
        run_sub_dev.font.italic = True
        run_sub_dev.font.size = Pt(9.5)
        run_sub_dev.font.color.rgb = RGBColor(107, 114, 128)

        p_lbl = doc.add_paragraph()
        p_lbl.paragraph_format.space_before = Pt(4)
        p_lbl.paragraph_format.space_after = Pt(2)
        r = p_lbl.add_run("Schema.org JSON-LD:")
        r.bold = True
        r.font.size = Pt(10)

        p_code = doc.add_paragraph()
        p_code.paragraph_format.space_after = Pt(8)
        r_code = p_code.add_run(json.dumps(dev_schema, indent=2))
        r_code.font.name = "Courier New"
        r_code.font.size = Pt(8.5)
        r_code.font.color.rgb = RGBColor(30, 41, 59)

    # 6. Footer disclaimer
    for sec in doc.sections:
        footer = sec.footer
        p_foot = footer.paragraphs[0]
        p_foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_foot.paragraph_format.space_before = Pt(6)
        r_foot = p_foot.add_run(
            "AI-generated suggestions. Review before publishing. They do not affect the Citation Score."
        )
        r_foot.font.name = "Arial"
        r_foot.font.size = Pt(8.5)
        r_foot.font.italic = True
        r_foot.font.color.rgb = RGBColor(156, 163, 175)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def _is_ip_allowed(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
        return True
    except ValueError:
        return False


def _is_host_safe(hostname: str) -> bool:
    if not hostname:
        return False
    h = hostname.strip().lower()
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local") or h.endswith(".internal"):
        return False

    # Check direct IP literals (e.g. 127.0.0.1, 10.0.0.1, 169.254.169.254)
    try:
        ip = ipaddress.ip_address(h)
        return _is_ip_allowed(str(ip))
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(h, None)
        if not addr_info:
            return False
        for res in addr_info:
            sockaddr = res[4]
            ip_str = sockaddr[0]
            if not _is_ip_allowed(ip_str):
                return False
        return True
    except Exception:
        return False


def _download_safe_image(
    url: str,
    max_bytes: int = 5 * 1024 * 1024,
    max_redirects: int = 3,
    timeout: float = 4.0,
) -> Optional[bytes]:
    """
    Safely download an external image with strict security boundaries:
    - Only http/https.
    - Hostname resolved and checked against private, loopback, link-local, reserved, multicast IPs.
    - Manual redirect handling (maximum 3 redirects) with validation of each target.
    - Streaming download capped at max_bytes (5 MB).
    - Only accepts Content-Type: image/*.
    """
    import httpx

    current_url = url
    for _ in range(max_redirects + 1):
        try:
            parsed = urlparse(current_url)
            if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
                return None
            if not _is_host_safe(parsed.hostname):
                return None

            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream("GET", current_url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            return None
                        current_url = urljoin(current_url, loc)
                        continue

                    if resp.status_code != 200:
                        return None

                    content_type = (resp.headers.get("content-type") or "").strip().lower()
                    if not content_type.startswith("image/"):
                        return None

                    content_len_header = resp.headers.get("content-length")
                    if content_len_header:
                        try:
                            if int(content_len_header) > max_bytes:
                                return None
                        except ValueError:
                            pass

                    content = bytearray()
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            return None

                    if not content:
                        return None

                    return bytes(content)
        except Exception:
            return None

    return None


def generate_rewrite_draft_docx(
    url: Optional[str],
    draft_markdown: str,
    warnings: list[str],
    score_comparison: Optional[Any] = None,
) -> bytes:
    """
    Generate Word (.docx) document for an AI article rewrite draft:
    1. Title with domain / URL and date.
    2. Before/After score comparison table (if provided).
    3. Warnings callout box (if warnings present).
    4. Rendered draft with real headings (H1, H2, H3), paragraphs, Markdown tables,
       and [EDITOR: ...] placeholders highlighted in yellow bold.
    """
    import re
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # 1. Title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    run_title = title_p.add_run("Article Rewrite Draft")
    run_title.font.name = "Arial"
    run_title.font.size = Pt(24)
    run_title.bold = True
    run_title.font.color.rgb = RGBColor(17, 24, 39)

    meta_p = doc.add_paragraph()
    meta_p.paragraph_format.space_after = Pt(14)
    r_sub = meta_p.add_run(f"Generated draft for {url or 'manual input'} • {datetime.now(timezone.utc).strftime('%B %d, %Y')}")
    r_sub.font.size = Pt(10)
    r_sub.font.color.rgb = RGBColor(107, 114, 128)

    # 2. Score comparison table
    if score_comparison:
        h2_score = doc.add_heading(level=2)
        h2_score.paragraph_format.space_before = Pt(12)
        h2_score.paragraph_format.space_after = Pt(4)
        run_h2s = h2_score.add_run("Content Score Comparison (Before vs After)")
        run_h2s.font.name = "Arial"
        run_h2s.font.size = Pt(14)
        run_h2s.bold = True
        run_h2s.font.color.rgb = RGBColor(31, 41, 55)

        note_p = doc.add_paragraph()
        note_p.paragraph_format.space_after = Pt(6)
        r_note = note_p.add_run("Content-only comparison: technical, metadata, freshness and authority dimensions are not included.")
        r_note.font.italic = True
        r_note.font.size = Pt(9)
        r_note.font.color.rgb = RGBColor(107, 114, 128)

        dims = getattr(score_comparison, "dimensions", [])
        table = doc.add_table(rows=1 + len(dims) + 1, cols=4)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False

        headers = ["Dimension", "Original", "Draft", "Change"]
        col_widths = [Inches(2.8), Inches(1.2), Inches(1.2), Inches(1.3)]
        for i, (title, width) in enumerate(zip(headers, col_widths)):
            cell = table.cell(0, i)
            cell.width = width
            set_cell_background(cell, "1F2937")
            set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if i > 0 else WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(title)
            run.font.name = "Arial"
            run.font.size = Pt(9.5)
            run.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)

        from src.utils.batch_aggregator import DIMENSION_DISPLAY_NAMES

        for row_idx, dim in enumerate(dims, start=1):
            dim_key = getattr(dim, "name", "")
            dim_name = DIMENSION_DISPLAY_NAMES.get(dim_key, dim_key.replace("_", " ").title())
            s_before = round(getattr(dim, "score_before", 0.0))
            s_after = round(getattr(dim, "score_after", 0.0))
            diff = s_after - s_before

            diff_str = f"+{diff}" if diff > 0 else f"{diff}"
            row_data = [dim_name, f"{s_before}/100", f"{s_after}/100", diff_str]
            bg_color = "F9FAFB" if row_idx % 2 == 1 else "FFFFFF"

            for i, (val, width) in enumerate(zip(row_data, col_widths)):
                cell = table.cell(row_idx, i)
                cell.width = width
                set_cell_background(cell, bg_color)
                set_cell_margins(cell, top=80, bottom=80, left=140, right=140)
                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if i > 0 else WD_ALIGN_PARAGRAPH.LEFT
                run = p.add_run(val)
                run.font.name = "Arial"
                run.font.size = Pt(9)
                if i == 3:
                    run.bold = True
                    if diff > 0:
                        run.font.color.rgb = RGBColor(16, 149, 106)
                    elif diff < 0:
                        run.font.color.rgb = RGBColor(230, 57, 70)

        # Total row
        tot_idx = len(dims) + 1
        t_before = round(getattr(score_comparison, "total_score_before", 0.0))
        t_after = round(getattr(score_comparison, "total_score_after", 0.0))
        t_diff = t_after - t_before
        t_diff_str = f"+{t_diff}" if t_diff > 0 else f"{t_diff}"

        tot_data = ["Total Citation Score (Normalized)", f"{t_before}/100", f"{t_after}/100", t_diff_str]
        for i, (val, width) in enumerate(zip(tot_data, col_widths)):
            cell = table.cell(tot_idx, i)
            cell.width = width
            set_cell_background(cell, "E5E7EB")
            set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if i > 0 else WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(val)
            run.font.name = "Arial"
            run.font.size = Pt(9.5)
            run.bold = True
            if i == 3:
                if t_diff > 0:
                    run.font.color.rgb = RGBColor(16, 149, 106)
                elif t_diff < 0:
                    run.font.color.rgb = RGBColor(230, 57, 70)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # 3. Warnings
    if warnings:
        warn_text = "\n".join(f"• {w}" for w in warnings)
        add_callout(doc, warn_text, title="Editorial Warnings:")

    # 4. Article Draft Heading
    h2_draft = doc.add_heading(level=1)
    h2_draft.paragraph_format.space_before = Pt(16)
    h2_draft.paragraph_format.space_after = Pt(6)
    run_h2d = h2_draft.add_run("Draft Article Content")
    run_h2d.font.name = "Arial"
    run_h2d.font.size = Pt(16)
    run_h2d.bold = True
    run_h2d.font.color.rgb = RGBColor(17, 24, 39)

    # Parse and write markdown lines
    def _add_hyperlink(paragraph, text: str, url: str, bold: bool = False):
        """Append a real clickable hyperlink run to the paragraph."""
        r_id = paragraph.part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        new_run = OxmlElement("w:r")
        r_pr = OxmlElement("w:rPr")
        r_style = OxmlElement("w:color")
        r_style.set(qn("w:val"), "0563C1")
        r_pr.append(r_style)
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        r_pr.append(underline)
        if bold:
            r_pr.append(OxmlElement("w:b"))
        new_run.append(r_pr)
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        new_run.append(t)
        hyperlink.append(new_run)
        paragraph._p.append(hyperlink)

    def _add_highlighted_text(paragraph, text: str, default_bold: bool = False):
        """Append runs to paragraph, highlighting [EDITOR: ...] in yellow bold and
        rendering Markdown links [text](url) as real hyperlinks."""
        pattern = re.compile(r'(\[EDITOR:[^\]]*\]|!\[[^\]]*\]\(https?://[^)\s]+\)|\[[^\]]*\]\(https?://[^)\s]+\))')
        parts = pattern.split(text)
        for part in parts:
            if not part:
                continue
            if part.startswith("[EDITOR:") and part.endswith("]"):
                run = paragraph.add_run(part)
                run.bold = True
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                run.font.color.rgb = RGBColor(146, 64, 14)
                continue
            img_m = re.fullmatch(r'!\[([^\]]*)\]\((https?://[^)\s]+)\)', part)
            if img_m:
                run = paragraph.add_run(f"[Image: {img_m.group(1) or 'Image'} — {img_m.group(2)}]")
                run.italic = True
                run.font.color.rgb = RGBColor(107, 114, 128)
                continue
            link_m = re.fullmatch(r'\[([^\]]*)\]\((https?://[^)\s]+)\)', part)
            if link_m:
                _add_hyperlink(paragraph, link_m.group(1) or link_m.group(2), link_m.group(2), bold=default_bold)
            else:
                run = paragraph.add_run(part)
                if default_bold:
                    run.bold = True

    lines = draft_markdown.split("\n")
    i = 0
    in_table = False
    table_lines: list[str] = []
    downloaded_images_count = 0
    MAX_DOCX_IMAGES = 15

    def _flush_table(t_lines: list[str]):
        if not t_lines:
            return
        # Parse markdown table
        rows_data = []
        for tl in t_lines:
            tl = tl.strip()
            if not tl.startswith("|"):
                continue
            cols = [c.strip() for c in tl.strip("|").split("|")]
            # Skip separator line |---|---|
            if all(re.match(r'^-+$', c) for c in cols):
                continue
            rows_data.append(cols)

        if not rows_data:
            return

        max_cols = max(len(r) for r in rows_data)
        doc_tbl = doc.add_table(rows=len(rows_data), cols=max_cols)
        doc_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        col_w = Inches(6.5 / max(max_cols, 1))

        for r_idx, row in enumerate(rows_data):
            for c_idx in range(max_cols):
                val = row[c_idx] if c_idx < len(row) else ""
                cell = doc_tbl.cell(r_idx, c_idx)
                cell.width = col_w
                set_cell_margins(cell, top=70, bottom=70, left=100, right=100)
                if r_idx == 0:
                    set_cell_background(cell, "F3F4F6")
                p = cell.paragraphs[0]
                _add_highlighted_text(p, val, default_bold=(r_idx == 0))

        doc.add_paragraph().paragraph_format.space_after = Pt(6)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check table
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            table_lines.append(stripped)
            i += 1
            continue
        elif in_table:
            in_table = False
            _flush_table(table_lines)
            table_lines = []

        if not stripped:
            i += 1
            continue

        # Check standalone markdown image
        img_match = re.match(r'^!\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+"[^"]*")?\)$', stripped)
        if img_match:
            alt_text = img_match.group(1).strip()
            img_url = img_match.group(2).strip()
            inserted = False
            if downloaded_images_count < MAX_DOCX_IMAGES:
                img_bytes = _download_safe_image(img_url)
                if img_bytes:
                    try:
                        img_stream = io.BytesIO(img_bytes)
                        doc.add_picture(img_stream, width=Inches(5.5))
                        inserted = True
                        downloaded_images_count += 1
                    except Exception:
                        inserted = False

            p_img = doc.add_paragraph()
            p_img.paragraph_format.space_after = Pt(6)
            if inserted:
                if alt_text:
                    r_caption = p_img.add_run(f"Figure: {alt_text}")
                    r_caption.font.size = Pt(8.5)
                    r_caption.font.italic = True
                    r_caption.font.color.rgb = RGBColor(107, 114, 128)
            else:
                r_fallback = p_img.add_run(f"[Image: {alt_text or 'Image'} — {img_url}]")
                r_fallback.font.size = Pt(9)
                r_fallback.font.italic = True
                r_fallback.font.color.rgb = RGBColor(107, 114, 128)
            i += 1
            continue

        if stripped.startswith("# "):
            h1 = doc.add_heading(level=1)
            h1.paragraph_format.space_before = Pt(14)
            h1.paragraph_format.space_after = Pt(4)
            _add_highlighted_text(h1, stripped[2:].strip())
        elif stripped.startswith("## "):
            h2 = doc.add_heading(level=2)
            h2.paragraph_format.space_before = Pt(12)
            h2.paragraph_format.space_after = Pt(4)
            _add_highlighted_text(h2, stripped[3:].strip())
        elif stripped.startswith("### "):
            h3 = doc.add_heading(level=3)
            h3.paragraph_format.space_before = Pt(10)
            h3.paragraph_format.space_after = Pt(3)
            _add_highlighted_text(h3, stripped[4:].strip())
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_after = Pt(3)
            _add_highlighted_text(p, stripped[2:].strip())
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.15
            _add_highlighted_text(p, stripped)

        i += 1

    if in_table and table_lines:
        _flush_table(table_lines)

    # Footer
    for sec in doc.sections:
        footer = sec.footer
        p_foot = footer.paragraphs[0]
        p_foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_foot.paragraph_format.space_before = Pt(6)
        r_foot = p_foot.add_run(
            "AI-generated draft for editorial review before publishing."
        )
        r_foot.font.name = "Arial"
        r_foot.font.size = Pt(8.5)
        r_foot.font.italic = True
        r_foot.font.color.rgb = RGBColor(156, 163, 175)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
