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


@pytest.fixture(autouse=True)
def clean_batch_jobs_state():
    batch_jobs.clear()
    yield
    batch_jobs.clear()


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


@pytest.mark.asyncio
async def test_cleanup_expired_jobs_after_2_hours():
    """
    Test that jobs completed more than 2 hours ago are deleted upon querying
    and creating batch jobs.
    """
    from datetime import datetime, timezone, timedelta
    batch_jobs.clear()

    now = datetime.now(timezone.utc)
    old_job_id = "job-old-expired"
    recent_job_id = "job-recent"

    # Completed 3 hours ago
    batch_jobs[old_job_id] = {
        "job_id": old_job_id,
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [{"url": "https://example.com/old", "status": "done", "result": None, "error": None}],
        "issues_by_topic": [],
        "created_at": (now - timedelta(hours=3, minutes=10)).isoformat(),
        "completed_at": (now - timedelta(hours=3)).isoformat(),
    }

    # Completed 30 minutes ago
    batch_jobs[recent_job_id] = {
        "job_id": recent_job_id,
        "status": "done",
        "total": 1,
        "completed": 1,
        "results": [{"url": "https://example.com/recent", "status": "done", "result": None, "error": None}],
        "issues_by_topic": [],
        "created_at": (now - timedelta(minutes=40)).isoformat(),
        "completed_at": (now - timedelta(minutes=30)).isoformat(),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Querying the expired job should trigger cleanup and return 404
        res_old = await client.get(f"/api/batch/{old_job_id}")
        assert res_old.status_code == 404
        assert "not found or expired" in res_old.json()["detail"].lower()
        assert old_job_id not in batch_jobs

        # Querying recent job should succeed
        res_recent = await client.get(f"/api/batch/{recent_job_id}")
        assert res_recent.status_code == 200
        assert res_recent.json()["job_id"] == recent_job_id

        # Also verify that creating a new batch triggers cleanup of expired jobs
        expired_job_2 = "job-old-2"
        batch_jobs[expired_job_2] = {
            "job_id": expired_job_2,
            "status": "done",
            "total": 1,
            "completed": 1,
            "results": [],
            "issues_by_topic": [],
            "created_at": (now - timedelta(hours=4)).isoformat(),
            "completed_at": (now - timedelta(hours=3, minutes=30)).isoformat(),
        }
        assert expired_job_2 in batch_jobs
        with patch("main.process_batch_job", new=AsyncMock()):
            post_res = await client.post("/api/batch", json={"urls": ["https://example.com/test-cleanup"]})
            assert post_res.status_code == 200
            assert expired_job_2 not in batch_jobs


@pytest.mark.asyncio
async def test_cleanup_max_10_jobs():
    """
    Test that batch_jobs stores at most 10 jobs; if exceeded, the oldest completed jobs are deleted.
    """
    from datetime import datetime, timezone, timedelta
    batch_jobs.clear()

    now = datetime.now(timezone.utc)

    # Populate 10 completed jobs
    for i in range(10):
        jid = f"job-{i}"
        batch_jobs[jid] = {
            "job_id": jid,
            "status": "done",
            "total": 1,
            "completed": 1,
            "results": [{"url": f"https://example.com/{i}", "status": "done", "result": None, "error": None}],
            "issues_by_topic": [],
            "created_at": (now - timedelta(minutes=60 - i * 2)).isoformat(),
            "completed_at": (now - timedelta(minutes=55 - i * 2)).isoformat(),
        }

    assert len(batch_jobs) == 10
    assert "job-0" in batch_jobs  # oldest job

    # Create an 11th job via POST /api/batch
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("main.process_batch_job", new=AsyncMock()):
            res = await client.post("/api/batch", json={"urls": ["https://example.com/new"]})
            assert res.status_code == 200
            new_job_id = res.json()["job_id"]

            # Max 10 constraint maintained
            assert len(batch_jobs) <= 10
            # Oldest job-0 should have been pruned
            assert "job-0" not in batch_jobs
            # New job is present
            assert new_job_id in batch_jobs


@pytest.mark.asyncio
async def test_batch_rate_limit_max_2_active():
    """
    Test that if there are already 2 batches in pending or running state,
    POST /api/batch returns 429 with the exact message:
    "Too many batch audits running. Please try again in a few minutes."
    """
    from datetime import datetime, timezone
    batch_jobs.clear()
    now = datetime.now(timezone.utc)

    # Add 2 running/pending jobs
    batch_jobs["active-1"] = {
        "job_id": "active-1",
        "status": "running",
        "total": 5,
        "completed": 2,
        "results": [],
        "issues_by_topic": [],
        "created_at": now.isoformat(),
    }
    batch_jobs["active-2"] = {
        "job_id": "active-2",
        "status": "pending",
        "total": 3,
        "completed": 0,
        "results": [],
        "issues_by_topic": [],
        "created_at": now.isoformat(),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/batch", json={"urls": ["https://example.com/blocked"]})
        assert res.status_code == 429
        assert res.json()["detail"] == "Too many batch audits running. Please try again in a few minutes."

        # Complete one job
        batch_jobs["active-1"]["status"] = "done"

        # Now creating should succeed
        with patch("main.process_batch_job", new=AsyncMock()):
            res_allowed = await client.post("/api/batch", json={"urls": ["https://example.com/allowed"]})
            assert res_allowed.status_code == 200
            assert "job_id" in res_allowed.json()


@pytest.mark.asyncio
async def test_batch_unexpected_exception_masked():
    """
    Test that unexpected errors (generic exceptions) in process_batch_job
    mask details and return 'Internal error while auditing this URL.' to the client.
    """
    urls = ["https://example.com/crashed"]

    async def mock_run_crashed(request, scraper, semaphore, **kwargs):
        raise RuntimeError("Secret DB password or internal crash details")

    with patch("main.run_single_audit", side_effect=mock_run_crashed):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post_res = await client.post("/api/batch", json={"urls": urls})
            assert post_res.status_code == 200
            job_id = post_res.json()["job_id"]

            import asyncio
            for _ in range(10):
                status_res = await client.get(f"/api/batch/{job_id}")
                assert status_res.status_code == 200
                data = status_res.json()
                if data["status"] == "done":
                    break
                await asyncio.sleep(0.05)

            assert data["status"] == "done"
            assert data["results"][0]["status"] == "error"
            # Must return exact generic message, not internal exception string
            assert data["results"][0]["error"] == "Internal error while auditing this URL."
            assert "Secret DB" not in data["results"][0]["error"]
