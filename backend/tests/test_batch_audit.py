"""
Tests for Phase 5: Batch Audit & Issues by Topic Aggregation.

Covers:
1. Issues by topic aggregation with 3 simulated pages.
2. Error on a single URL does not stop or break the batch.
3. Maximum 20 URLs constraint enforcement.
4. CSV export endpoint structure.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from main import app, batch_jobs
from src.utils.batch_aggregator import aggregate_issues_by_topic
from src.scrapers.base_scraper import ScraperError


def create_mock_detector_result(dimension: str, weight: float, breakdowns: list):
    return {
        "dimension": dimension,
        "score": 50.0,
        "weight": weight,
        "contribution": 5.0,
        "breakdown": [
            {
                "name": b["name"],
                "raw_score": b["raw_score"],
                "weight": 0.5,
                "weighted_score": b["raw_score"] * 0.5,
                "explanation": "Test explanation",
                "recommendations": b.get("recommendations", [])
            }
            for b in breakdowns
        ]
    }


def test_aggregate_issues_by_topic_3_pages():
    """
    Test aggregation of issues by topic across 3 simulated pages:
    - Page 1 has submetrics: Schema Presence (raw_score=0), External Links Found (raw_score=60)
    - Page 2 has submetrics: Schema Presence (raw_score=0), AI Bot Access (raw_score=0)
    - Page 3 has submetrics: External Links Found (raw_score=0), Schema Presence (raw_score=100 - healthy)
    
    Verifies:
    - Only submetrics < 70 are aggregated.
    - Affected counts and affected URLs list.
    - Most frequent recommendation selection.
    - Impact = dimension_weight * affected_pages.
    """
    results = [
        {
            "url": "https://example.com/p1",
            "status": "done",
            "result": {
                "url": "https://example.com/p1",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {
                            "name": "Schema Presence",
                            "raw_score": 0.0,
                            "recommendations": ["Implement JSON-LD Schema (Article, NewsArticle, etc.)"]
                        }
                    ]),
                    create_mock_detector_result("links_verifiability", 0.06, [
                        {
                            "name": "External Links Found",
                            "raw_score": 60.0,
                            "recommendations": ["Add at least 2-3 links to independent external sources."]
                        }
                    ]),
                ]
            }
        },
        {
            "url": "https://example.com/p2",
            "status": "done",
            "result": {
                "url": "https://example.com/p2",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {
                            "name": "Schema Presence",
                            "raw_score": 0.0,
                            "recommendations": ["Implement JSON-LD Schema (Article, NewsArticle, etc.)"]
                        }
                    ]),
                    create_mock_detector_result("technical_infrastructure", 0.10, [
                        {
                            "name": "AI Bot Access",
                            "raw_score": 0.0,
                            "recommendations": ["Unblock AI search bots in robots.txt"]
                        }
                    ]),
                ]
            }
        },
        {
            "url": "https://example.com/p3",
            "status": "done",
            "result": {
                "url": "https://example.com/p3",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {
                            "name": "Schema Presence",
                            "raw_score": 100.0,  # Healthy! should NOT be included
                            "recommendations": []
                        }
                    ]),
                    create_mock_detector_result("links_verifiability", 0.06, [
                        {
                            "name": "External Links Found",
                            "raw_score": 0.0,
                            "recommendations": ["Add at least 2-3 links to independent external sources."]
                        }
                    ]),
                ]
            }
        },
    ]

    issues = aggregate_issues_by_topic(results)
    assert len(issues) == 3

    # Check Schema Presence: affected pages = p1, p2 (count = 2), impact = 0.04 * 2 = 0.08
    schema_issue = next(i for i in issues if i["submetric"] == "Schema Presence")
    assert schema_issue["dimension"] == "metadata_schema"
    assert schema_issue["affected_count"] == 2
    assert "https://example.com/p1" in schema_issue["affected_urls"]
    assert "https://example.com/p2" in schema_issue["affected_urls"]
    assert "https://example.com/p3" not in schema_issue["affected_urls"]
    assert schema_issue["top_recommendation"] == "Implement JSON-LD Schema (Article, NewsArticle, etc.)"
    assert schema_issue["impact"] == 0.08

    # Check External Links Found: affected pages = p1, p3 (count = 2), impact = 0.06 * 2 = 0.12
    links_issue = next(i for i in issues if i["submetric"] == "External Links Found")
    assert links_issue["affected_count"] == 2
    assert links_issue["impact"] == 0.12

    # Check AI Bot Access: affected pages = p2 (count = 1), impact = 0.10 * 1 = 0.10
    bot_issue = next(i for i in issues if i["submetric"] == "AI Bot Access")
    assert bot_issue["affected_count"] == 1
    assert bot_issue["impact"] == 0.10

    # Check ordering by impact descending:
    # 1. External Links Found (impact 0.12)
    # 2. AI Bot Access (impact 0.10)
    # 3. Schema Presence (impact 0.08)
    assert issues[0]["submetric"] == "External Links Found"
    assert issues[1]["submetric"] == "AI Bot Access"
    assert issues[2]["submetric"] == "Schema Presence"


@pytest.mark.asyncio
async def test_batch_url_limit_20():
    """Verify that submitting more than 20 URLs returns 400."""
    urls = [f"https://example.com/page{i}" for i in range(21)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/batch", json={"urls": urls})
        assert res.status_code == 400
        assert "20 URLs" in res.json()["detail"]


@pytest.mark.asyncio
async def test_batch_error_does_not_stop_batch():
    """
    Test that when one URL in the batch fails with ScraperError or network error,
    it is recorded as an error and the remaining URLs continue processing.
    """
    urls = [
        "https://example.com/success1",
        "https://example.com/failing",
        "https://example.com/success2",
    ]

    async def mock_run_single(request, scraper, semaphore, **kwargs):
        if "failing" in request.url:
            raise ScraperError("Connection timed out after 30s", reason="Timeout")
        
        # Return a lightweight mock AuditResponse
        from src.models.schemas import AuditResponse, DimensionScore
        return AuditResponse(
            url=request.url,
            total_score=85.0,
            dimensions=[
                DimensionScore(
                    name="technical_infrastructure",
                    score=90.0,
                    weight=0.10,
                    contribution=9.0,
                    status="green"
                )
            ],
            scoring_version="v2.3",
            language="en",
            content_type="guide_blog",
            analysis_time_ms=150.0,
            recommendations=["All good"],
            detector_results=[]
        )

    with patch("main.run_single_audit", side_effect=mock_run_single):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post_res = await client.post("/api/batch", json={"urls": urls})
            assert post_res.status_code == 200
            job_id = post_res.json()["job_id"]

            # Poll/wait until complete
            import asyncio
            for _ in range(10):
                status_res = await client.get(f"/api/batch/{job_id}")
                assert status_res.status_code == 200
                data = status_res.json()
                if data["status"] == "done":
                    break
                await asyncio.sleep(0.05)

            assert data["status"] == "done"
            assert data["total"] == 3
            assert data["completed"] == 3

            results = data["results"]
            assert results[0]["status"] == "done"
            assert results[0]["result"]["total_score"] == 85.0

            assert results[1]["status"] == "error"
            assert "Timeout" in results[1]["error"]

            assert results[2]["status"] == "done"
            assert results[2]["result"]["total_score"] == 85.0

            # Test CSV export
            csv_res = await client.get(f"/api/batch/{job_id}/csv")
            assert csv_res.status_code == 200
            assert "text/csv" in csv_res.headers["content-type"]
            csv_content = csv_res.text
            assert "https://example.com/success1" in csv_content
            assert "https://example.com/failing" in csv_content
            assert "Timeout" in csv_content
            assert "https://example.com/success2" in csv_content
