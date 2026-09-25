"""
GEO-AUDITOR AI - Batch Issue Aggregator

Aggregates submetric breakdowns across audited pages in a batch.
Identifies submetrics scoring < 70, counts affected URLs, determines the
most frequent recommendation, and ranks issues by impact.
Impact = dimension_weight * number_of_affected_pages.
"""

from collections import Counter
from typing import List, Dict, Any, Optional
from src.models.schemas import AuditResponse


def aggregate_issues_by_topic(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Given a list of batch item results (which may include AuditResponse dicts or errors),
    aggregates submetrics with raw_score < 70.
    
    Args:
        results: List of dicts representing BatchItemResult (each with url, status, result, error)
        
    Returns:
        List of dicts representing TopicIssue, sorted descending by impact (and affected_count).
    """
    # Key: (dimension, submetric_name) -> dict with dimension, submetric, weight, urls, recommendations
    issue_map: Dict[tuple, Dict[str, Any]] = {}

    for item in results:
        # Only inspect successful audits
        if item.get("status") != "done" or not item.get("result"):
            continue
        
        audit_res = item["result"]
        url = item.get("url") or audit_res.get("url", "")
        detector_results = audit_res.get("detector_results", [])

        for d in detector_results:
            dimension = d.get("dimension", "")
            dim_weight = float(d.get("weight", 0.0))
            breakdown = d.get("breakdown", [])

            for b in breakdown:
                raw_score = float(b.get("raw_score", 0.0))
                submetric_name = b.get("name", "")

                if raw_score < 70.0:
                    key = (dimension, submetric_name)
                    if key not in issue_map:
                        issue_map[key] = {
                            "dimension": dimension,
                            "submetric": submetric_name,
                            "dimension_weight": dim_weight,
                            "affected_urls": [],
                            "recommendations": []
                        }
                    
                    if url not in issue_map[key]["affected_urls"]:
                        issue_map[key]["affected_urls"].append(url)
                    
                    for rec in b.get("recommendations", []):
                        if rec and rec.strip():
                            issue_map[key]["recommendations"].append(rec.strip())

    aggregated: List[Dict[str, Any]] = []
    for (dim, submetric), data in issue_map.items():
        affected_count = len(data["affected_urls"])
        dim_weight = data["dimension_weight"]
        impact = round(dim_weight * affected_count, 4)

        # Determine most frequent recommendation
        recs = data["recommendations"]
        top_recommendation: Optional[str] = None
        if recs:
            top_rec, _ = Counter(recs).most_common(1)[0]
            top_recommendation = top_rec

        aggregated.append({
            "dimension": dim,
            "submetric": submetric,
            "affected_count": affected_count,
            "affected_urls": data["affected_urls"],
            "top_recommendation": top_recommendation,
            "impact": impact
        })

    # Sort primarily by impact descending, then affected_count descending, then submetric ascending
    aggregated.sort(key=lambda x: (x["impact"], x["affected_count"]), reverse=True)
    return aggregated
