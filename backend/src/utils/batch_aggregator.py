"""
GEO-AUDITOR AI - Batch Issue Aggregator

Aggregates submetric breakdowns across audited pages in a batch.
Identifies submetrics scoring < 70, counts affected URLs, determines the
most frequent recommendation, and ranks issues by impact.
Impact = dimension_weight * number_of_affected_pages.
"""

from collections import Counter
from typing import List, Dict, Any, Optional, Set, Tuple

# Centralized dimension display names
DIMENSION_DISPLAY_NAMES: Dict[str, str] = {
    "technical_infrastructure": "Content Architecture",
    "aeo_structure": "AEO Readability",
    "metadata_schema": "Metadata & Schema",
    "passage_quality": "Passage Quality",
    "evidence_density": "Evidence Density",
    "eeat_authority": "EEAT & Authority",
    "entity_identification": "Entity Identification",
    "freshness": "Content Freshness",
    "format_citability": "Citability & Formatting",
    "links_verifiability": "Links & Verifiability",
    "query_match": "Query Match",
}

# Submetric dependencies: parent submetric -> list of child submetrics that should
# be ignored for a page if the parent submetric fails (< 70).
SUBMETRIC_DEPENDENCIES: Dict[str, List[str]] = {
    "Schema Presence": [
        "Critical Schema Types",
        "Author/Publisher Schema",
        "Entity Depth (E-E-A-T)",
    ]
}

# Submetrics that pertain to site-wide configuration rather than individual pages
SITE_WIDE_SUBMETRICS: Set[str] = {
    "Trust Pages",
    "AI Bot Access",
}


def aggregate_issues_by_topic(
    results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Given a list of batch item results (which may include AuditResponse dicts or errors),
    aggregates submetrics with raw_score < 70.
    
    Applies dependency collapsing (e.g. if Schema Presence fails on a page, its child
    submetrics are ignored for that page) and separates site-wide issues from page-level issues.
    
    Args:
        results: List of dicts representing BatchItemResult (each with url, status, result, error)
        
    Returns:
        Tuple of (page_issues, site_wide_issues), each sorted descending by impact.
    """
    page_issue_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    site_issue_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for item in results:
        # Only inspect successful audits
        if item.get("status") != "done" or not item.get("result"):
            continue
        
        audit_res = item["result"]
        url = item.get("url") or audit_res.get("url", "")
        detector_results = audit_res.get("detector_results", [])

        # Step 1: Collect all failing submetrics on this page
        page_failed_submetrics: Set[str] = set()
        page_submetric_items: Dict[str, Dict[str, Any]] = {}

        for d in detector_results:
            dimension = d.get("dimension", "")
            dim_weight = float(d.get("weight", 0.0))
            breakdown = d.get("breakdown", [])

            for b in breakdown:
                raw_score = float(b.get("raw_score", 0.0))
                submetric_name = b.get("name", "")
                if submetric_name == "Entity Depth (E-E-A-T)":
                    submetric_name = "Author/Publisher Schema"

                if raw_score < 70.0:
                    page_failed_submetrics.add(submetric_name)
                    page_submetric_items[submetric_name] = {
                        "dimension": dimension,
                        "dim_weight": dim_weight,
                        "recommendations": [r.strip() for r in b.get("recommendations", []) if r and r.strip()]
                    }

        # Step 2: Apply dependency collapsing for this page
        suppressed_submetrics: Set[str] = set()
        for parent, children in SUBMETRIC_DEPENDENCIES.items():
            if parent in page_failed_submetrics:
                for child in children:
                    suppressed_submetrics.add(child)

        active_submetrics = page_failed_submetrics - suppressed_submetrics

        # Step 3: Record active issues for this page into respective maps
        for submetric_name in active_submetrics:
            sub_data = page_submetric_items[submetric_name]
            dimension = sub_data["dimension"]
            dim_weight = sub_data["dim_weight"]
            recs = sub_data["recommendations"]

            target_map = site_issue_map if submetric_name in SITE_WIDE_SUBMETRICS else page_issue_map
            key = (dimension, submetric_name)
            if key not in target_map:
                target_map[key] = {
                    "dimension": dimension,
                    "submetric": submetric_name,
                    "dimension_weight": dim_weight,
                    "affected_urls": [],
                    "recommendations": []
                }
            if url not in target_map[key]["affected_urls"]:
                target_map[key]["affected_urls"].append(url)
            target_map[key]["recommendations"].extend(recs)

    def build_sorted_issues(raw_map: Dict[Tuple[str, str], Dict[str, Any]]) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        for (dim, submetric), data in raw_map.items():
            affected_count = len(data["affected_urls"])
            dim_weight = data["dimension_weight"]
            impact = round(dim_weight * affected_count, 4)

            top_recommendation: Optional[str] = None
            if data["recommendations"]:
                top_rec, _ = Counter(data["recommendations"]).most_common(1)[0]
                top_recommendation = top_rec

            output.append({
                "dimension": dim,
                "submetric": submetric,
                "affected_count": affected_count,
                "affected_urls": data["affected_urls"],
                "top_recommendation": top_recommendation,
                "impact": impact
            })
        output.sort(key=lambda x: (x["impact"], x["affected_count"]), reverse=True)
        return output

    page_issues = build_sorted_issues(page_issue_map)
    site_wide_issues = build_sorted_issues(site_issue_map)

    return page_issues, site_wide_issues
