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

    page_issues, site_wide_issues = aggregate_issues_by_topic(results)
    assert len(page_issues) == 3
    assert len(site_wide_issues) == 0

    # Check Schema Presence in page_issues: affected pages = p1, p2 (count = 2), impact = 0.04 * 2 = 0.08
    schema_issue = next(i for i in page_issues if i["submetric"] == "Schema Presence")
    assert schema_issue["dimension"] == "metadata_schema"
    assert schema_issue["affected_count"] == 2
    assert "https://example.com/p1" in schema_issue["affected_urls"]
    assert "https://example.com/p2" in schema_issue["affected_urls"]
    assert "https://example.com/p3" not in schema_issue["affected_urls"]
    assert schema_issue["top_recommendation"] == "Implement JSON-LD Schema (Article, NewsArticle, etc.)"
    assert schema_issue["impact"] == 0.08

    # Check External Links Found in page_issues: affected pages = p1, p3 (count = 2), impact = 0.06 * 2 = 0.12
    links_issue = next(i for i in page_issues if i["submetric"] == "External Links Found")
    assert links_issue["affected_count"] == 2
    assert links_issue["impact"] == 0.12

    # Check AI Bot Access in page_issues: affected pages = p2 (count = 1), impact = 0.10 * 1 = 0.10
    bot_issue = next(i for i in page_issues if i["submetric"] == "AI Bot Access")
    assert bot_issue["affected_count"] == 1
    assert bot_issue["impact"] == 0.10

    # Check ordering by impact descending in page_issues:
    # 1. External Links Found (impact 0.12)
    # 2. AI Bot Access (impact 0.10)
    # 3. Schema Presence (impact 0.08)
    assert page_issues[0]["submetric"] == "External Links Found"
    assert page_issues[1]["submetric"] == "AI Bot Access"
    assert page_issues[2]["submetric"] == "Schema Presence"


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


def test_schema_dependency_collapse():
    """
    If a page has Schema Presence < 70, Critical Schema Types and Author/Publisher Schema
    are NOT counted for that page.
    If another page has Schema Presence >= 70, but Critical Schema Types < 70, it IS counted.
    """
    results = [
        {
            "url": "https://example.com/no-schema",
            "status": "done",
            "result": {
                "url": "https://example.com/no-schema",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {"name": "Schema Presence", "raw_score": 0.0, "recommendations": ["Add Schema"]},
                        {"name": "Critical Schema Types", "raw_score": 0.0, "recommendations": ["Add Article"]},
                        {"name": "Author/Publisher Schema", "raw_score": 0.0, "recommendations": ["Add Author"]},
                    ])
                ]
            }
        },
        {
            "url": "https://example.com/has-schema-wrong-type",
            "status": "done",
            "result": {
                "url": "https://example.com/has-schema-wrong-type",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {"name": "Schema Presence", "raw_score": 100.0, "recommendations": []},
                        {"name": "Critical Schema Types", "raw_score": 0.0, "recommendations": ["Add Article"]},
                    ])
                ]
            }
        }
    ]

    page_issues, site_wide = aggregate_issues_by_topic(results)

    # "Schema Presence" affected by 1 page (/no-schema)
    presence_issue = next((i for i in page_issues if i["submetric"] == "Schema Presence"), None)
    assert presence_issue is not None
    assert presence_issue["affected_count"] == 1
    assert presence_issue["affected_urls"] == ["https://example.com/no-schema"]

    # "Critical Schema Types" affected by ONLY /has-schema-wrong-type (collapsed for /no-schema)
    critical_issue = next((i for i in page_issues if i["submetric"] == "Critical Schema Types"), None)
    assert critical_issue is not None
    assert critical_issue["affected_count"] == 1
    assert critical_issue["affected_urls"] == ["https://example.com/has-schema-wrong-type"]

    # "Author/Publisher Schema" was suppressed for /no-schema and not present in /has-schema-wrong-type
    author_issue = next((i for i in page_issues if i["submetric"] == "Author/Publisher Schema"), None)
    assert author_issue is None


def test_site_wide_issues_separated_and_counted_once():
    """
    Submetrics in SITE_WIDE_SUBMETRICS ('Trust Pages') are placed in site_wide_issues
    and excluded from page_issues. Page-level submetrics (including 'AI Bot Access')
    go to page_issues.
    """
    results = [
        {
            "url": f"https://example.com/page{i}",
            "status": "done",
            "result": {
                "url": f"https://example.com/page{i}",
                "detector_results": [
                    create_mock_detector_result("authority_signals", 0.10, [
                        {"name": "Trust Pages", "raw_score": 0.0, "recommendations": ["Add About/Contact"]}
                    ]),
                    create_mock_detector_result("technical_infrastructure", 0.10, [
                        {"name": "AI Bot Access", "raw_score": 0.0, "recommendations": ["Unblock AI bots"]}
                    ]),
                    create_mock_detector_result("links_verifiability", 0.06, [
                        {"name": "External Links Found", "raw_score": 40.0, "recommendations": ["Add links"]}
                    ])
                ]
            }
        }
        for i in range(1, 4)
    ]

    page_issues, site_wide_issues = aggregate_issues_by_topic(results)

    # page_issues should have AI Bot Access and External Links Found
    assert len(page_issues) == 2
    page_submetrics = {p["submetric"] for p in page_issues}
    assert page_submetrics == {"AI Bot Access", "External Links Found"}
    bot_issue = next(p for p in page_issues if p["submetric"] == "AI Bot Access")
    assert bot_issue["affected_count"] == 3
    links_issue = next(p for p in page_issues if p["submetric"] == "External Links Found")
    assert links_issue["affected_count"] == 3

    # site_wide_issues should only have Trust Pages
    assert len(site_wide_issues) == 1
    assert site_wide_issues[0]["submetric"] == "Trust Pages"
    assert site_wide_issues[0]["affected_count"] == 3
    assert len(site_wide_issues[0]["affected_urls"]) == 3


def test_schema_recommendations_by_content_type():
    from src.detectors.metadata import MetadataDetector
    detector = MetadataDetector()

    # news -> NewsArticle
    res_news = detector._analyze_critical_types([], content_type="news")
    assert any("NewsArticle" in r for r in res_news.recommendations)

    # guide_blog -> Article or BlogPosting (and FAQPage if FAQs)
    res_blog = detector._analyze_critical_types([], content_type="guide_blog")
    assert any("Article" in r or "BlogPosting" in r for r in res_blog.recommendations)
    assert any("FAQPage" in r for r in res_blog.recommendations)

    # review -> Review
    res_review = detector._analyze_critical_types([], content_type="review")
    assert any("Review" in r for r in res_review.recommendations)

    # product -> Product
    res_product = detector._analyze_critical_types([], content_type="product")
    assert any("Product" in r for r in res_product.recommendations)


def test_schema_presence_recommendations_by_content_type():
    """
    When no schema is present, Schema Presence recommendations must be tailored
    to content_type without changing the raw score (0.0).
    """
    from src.detectors.metadata import MetadataDetector
    detector = MetadataDetector()

    # news -> "Add JSON-LD NewsArticle Schema with author, publisher and datePublished."
    res_news = detector._analyze_presence([], has_critical_types=False, content_type="news")
    assert res_news.raw_score == 0.0
    assert "Add JSON-LD NewsArticle Schema with author, publisher and datePublished." in res_news.recommendations

    # guide_blog -> "Add JSON-LD Article or BlogPosting Schema with author and publisher (and FAQPage if the page has FAQs)."
    res_blog = detector._analyze_presence([], has_critical_types=False, content_type="guide_blog")
    assert res_blog.raw_score == 0.0
    assert "Add JSON-LD Article or BlogPosting Schema with author and publisher (and FAQPage if the page has FAQs)." in res_blog.recommendations

    # review -> "Add JSON-LD Review Schema with itemReviewed, rating and author."
    res_review = detector._analyze_presence([], has_critical_types=False, content_type="review")
    assert res_review.raw_score == 0.0
    assert "Add JSON-LD Review Schema with itemReviewed, rating and author." in res_review.recommendations

    # product -> "Add JSON-LD Product Schema with price, availability and brand."
    res_product = detector._analyze_presence([], has_critical_types=False, content_type="product")
    assert res_product.raw_score == 0.0
    assert "Add JSON-LD Product Schema with price, availability and brand." in res_product.recommendations


@pytest.mark.asyncio
async def test_csv_bom_and_headers_and_issues_csv():
    """
    Test BOM UTF-8 (\\xef\\xbb\\xbf) and legible headers in both CSVs:
    1. /api/batch/{job_id}/csv
    2. /api/batch/{job_id}/issues.csv
    Also verifies 404 for missing/expired job on issues.csv.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    job_id = "test-job-csv"
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "done",
        "total": 2,
        "completed": 2,
        "results": [
            {
                "url": "https://example.com/p1",
                "status": "done",
                "result": {
                    "url": "https://example.com/p1",
                    "total_score": 85.0,
                    "content_type": "guide_blog",
                    "language": "en",
                    "scoring_version": "v2.3",
                    "dimensions": [
                        {
                            "name": "metadata_schema",
                            "score": 60.0,
                            "weight": 0.04,
                            "contribution": 2.4,
                            "status": "yellow"
                        }
                    ],
                    "detector_results": [
                        create_mock_detector_result("metadata_schema", 0.04, [
                            {"name": "Schema Presence", "raw_score": 0.0, "recommendations": ["Add schema"]}
                        ])
                    ]
                },
                "error": None
            },
            {
                "url": "https://example.com/p2",
                "status": "done",
                "result": {
                    "url": "https://example.com/p2",
                    "total_score": 90.0,
                    "content_type": "news",
                    "language": "es",
                    "scoring_version": "v2.3",
                    "dimensions": [],
                    "detector_results": []
                },
                "error": None
            }
        ],
        "issues_by_topic": [
            {
                "dimension": "metadata_schema",
                "submetric": "Schema Presence",
                "affected_count": 1,
                "affected_urls": ["https://example.com/p1"],
                "top_recommendation": "Add schema",
                "impact": 0.04
            }
        ],
        "site_wide_issues": [
            {
                "dimension": "eeat_authority",
                "submetric": "Trust Pages",
                "affected_count": 2,
                "affected_urls": ["https://example.com/p1", "https://example.com/p2"],
                "top_recommendation": "Add About and Contact pages",
                "impact": 0.24
            }
        ],
        "created_at": now.isoformat(),
        "completed_at": now.isoformat()
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Test results CSV
        csv_res = await client.get(f"/api/batch/{job_id}/csv")
        assert csv_res.status_code == 200
        assert csv_res.content.startswith(b"\xef\xbb\xbf")
        text = csv_res.content.decode("utf-8-sig")
        header_line = text.splitlines()[0]
        # Check legible dimension name and fields
        assert "Content Type" in header_line
        assert "Language" in header_line
        assert "Technical Infrastructure" in header_line
        assert "Metadata & Schema" in header_line
        assert "Guide/Blog" in text
        assert "News" in text
        assert "EN" in text
        assert "ES" in text

        # 2. Test issues CSV
        issues_res = await client.get(f"/api/batch/{job_id}/issues.csv")
        assert issues_res.status_code == 200
        assert issues_res.content.startswith(b"\xef\xbb\xbf")
        issues_text = issues_res.content.decode("utf-8-sig")
        lines = issues_text.strip().splitlines()

        # Verify columns
        assert lines[0] == "Priority,Scope,Topic,Dimension,Pages affected,Impact,Recommendation,Affected URLs"

        # Verify Site-wide comes first
        assert "Site-wide" in lines[1]
        assert "Trust Pages" in lines[1]
        assert "E-E-A-T Authority" in lines[1]
        assert "0.24" in lines[1]
        assert "https://example.com/p1 | https://example.com/p2" in lines[1]

        # Verify Page issue comes next
        assert "Page" in lines[2]
        assert "Schema Presence" in lines[2]
        assert "Metadata & Schema" in lines[2]
        assert "0.04" in lines[2]

        # 3. Test 404 for missing job
        not_found_res = await client.get("/api/batch/non-existent-job/issues.csv")
        assert not_found_res.status_code == 404
        assert "not found or expired" in not_found_res.json()["detail"].lower()


def test_content_type_classification_news_vs_guide_and_spanish():
    from datetime import datetime, timezone
    from src.models.schemas import PageData
    from src.utils.content_type import detect_content_type

    def make_test_page(url: str, h1: str, schema_type: str = None) -> PageData:
        schema_json = ""
        if schema_type:
            schema_json = f'<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "{schema_type}"}}</script>'
        html = f"""
        <html>
        <head>{schema_json}</head>
        <body>
            <h1>{h1}</h1>
            <p>Some body content explaining the concepts in detail.</p>
        </body>
        </html>
        """
        return PageData(
            url=url,
            final_url=url,
            html_raw=html,
            html_rendered=html,
            text_content=f"{h1}\nSome body content explaining the concepts in detail.",
            status_code=200,
            load_time_ms=100.0,
            word_count=50,
            is_ssr=True,
            is_https=True,
            ttfb_ms=100.0,
            scraped_at=datetime.now(timezone.utc)
        )

    # 1. /newsroom/ + H1 "What are the differences between fan tokens and regular digital assets" -> guide_blog
    p1 = make_test_page(
        url="https://example.com/newsroom/fan-tokens-vs-assets",
        h1="What are the differences between fan tokens and regular digital assets"
    )
    assert detect_content_type(p1) == "guide_blog"

    # 2. /newsroom/ + H1 "Chiliz introduces CHZ buybacks to reinforce long-term value" -> news
    p2 = make_test_page(
        url="https://example.com/newsroom/chiliz-buybacks-announcement",
        h1="Chiliz introduces CHZ buybacks to reinforce long-term value"
    )
    assert detect_content_type(p2) == "news"

    # 3. schema NewsArticle + H1 "What is a fan token" -> news (Schema always wins!)
    p3 = make_test_page(
        url="https://example.com/articles/what-is-a-fan-token",
        h1="What is a fan token",
        schema_type="NewsArticle"
    )
    assert detect_content_type(p3) == "news"

    # 4. Spanish cases:
    # /noticias/ + H1 "Qué son los fan tokens y cómo funcionan" -> guide_blog
    p4 = make_test_page(
        url="https://example.com/noticias/que-son-los-fan-tokens",
        h1="Qué son los fan tokens y cómo funcionan"
    )
    assert detect_content_type(p4) == "guide_blog"

    # /noticias/ + H1 "Chiliz presenta la recompra de tokens" -> news
    p5 = make_test_page(
        url="https://example.com/noticias/recompra-chiliz",
        h1="Chiliz presenta la recompra de tokens"
    )
    assert detect_content_type(p5) == "news"

    # Schema NewsArticle + H1 "Qué es un fan token" -> news
    p6 = make_test_page(
        url="https://example.com/noticias/que-es-un-fan-token",
        h1="Qué es un fan token",
        schema_type="NewsArticle"
    )
    assert detect_content_type(p6) == "news"


def test_recommendation_breakdown_two_page_types():
    """
    Test recommendation_breakdown with two page types failing Schema Presence:
    3 news pages (NewsArticle recommendation) + 1 guide page (Article/BlogPosting recommendation).
    Verifies that:
    - affected_count = 4
    - top_recommendation is the news one (3 pages)
    - recommendation_breakdown has both distinct recommendations with page counts 3 and 1.
    """
    news_rec = "Add JSON-LD NewsArticle Schema with author, publisher and datePublished."
    guide_rec = "Add JSON-LD Article or BlogPosting Schema with author and publisher (and FAQPage if the page has FAQs)."

    results = [
        {
            "url": f"https://example.com/news-{i}",
            "status": "done",
            "result": {
                "url": f"https://example.com/news-{i}",
                "detector_results": [
                    create_mock_detector_result("metadata_schema", 0.04, [
                        {"name": "Schema Presence", "raw_score": 0.0, "recommendations": [news_rec]}
                    ])
                ]
            }
        }
        for i in range(1, 4)
    ]
    results.append({
        "url": "https://example.com/guide-1",
        "status": "done",
        "result": {
            "url": "https://example.com/guide-1",
            "detector_results": [
                create_mock_detector_result("metadata_schema", 0.04, [
                    {"name": "Schema Presence", "raw_score": 0.0, "recommendations": [guide_rec]}
                ])
            ]
        }
    })

    page_issues, site_wide = aggregate_issues_by_topic(results)
    schema_issue = next(i for i in page_issues if i["submetric"] == "Schema Presence")

    assert schema_issue["affected_count"] == 4
    assert schema_issue["top_recommendation"] == news_rec

    breakdown = schema_issue["recommendation_breakdown"]
    assert len(breakdown) == 2
    assert breakdown[0]["recommendation"] == news_rec
    assert breakdown[0]["page_count"] == 3
    assert breakdown[1]["recommendation"] == guide_rec
    assert breakdown[1]["page_count"] == 1


@pytest.mark.asyncio
async def test_issues_csv_multiple_recommendations():
    """
    Test that GET /api/batch/{job_id}/issues.csv includes all recommendations
    separated by ' | ' with their page counts in parentheses when there are multiple.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    job_id = "test-job-multi-rec-csv"
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "done",
        "total": 4,
        "completed": 4,
        "results": [],
        "site_wide_issues": [],
        "issues_by_topic": [
            {
                "dimension": "metadata_schema",
                "submetric": "Schema Presence",
                "affected_count": 4,
                "affected_urls": ["https://example.com/p1", "https://example.com/p2", "https://example.com/p3", "https://example.com/p4"],
                "top_recommendation": "Add JSON-LD NewsArticle Schema with author, publisher and datePublished.",
                "recommendation_breakdown": [
                    {
                        "recommendation": "Add JSON-LD NewsArticle Schema with author, publisher and datePublished.",
                        "page_count": 3
                    },
                    {
                        "recommendation": "Add JSON-LD Article or BlogPosting Schema with author and publisher (and FAQPage if the page has FAQs).",
                        "page_count": 1
                    }
                ],
                "impact": 0.16
            }
        ],
        "created_at": now.isoformat(),
        "completed_at": now.isoformat()
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/api/batch/{job_id}/issues.csv")
        assert res.status_code == 200
        text = res.content.decode("utf-8-sig")
        expected_rec = (
            "Add JSON-LD NewsArticle Schema with author, publisher and datePublished. (3 pages) | "
            "Add JSON-LD Article or BlogPosting Schema with author and publisher (and FAQPage if the page has FAQs). (1 page)"
        )
        assert expected_rec in text


def test_tokenize_variations():
    """
    Test tokenize() with the 4 exact prompt requirements:
    1. 'buy $CHZ now' -> removes '$'
    2. 'CHZ's buyback' -> removes possessive ''s'
    3. 'chz-token price' -> returns 'chz-token', 'chz', 'token', 'price'
    4. 'qué es un fan token' -> keeps accents and words with len > 1
    """
    from src.detectors.query_match import tokenize

    assert tokenize("buy $CHZ now") == ["buy", "chz", "now"]
    assert tokenize("CHZ's buyback") == ["chz", "buyback"]
    assert tokenize("chz-token price") == ["chz-token", "chz", "token", "price"]
    assert tokenize("qué es un fan token") == ["qué", "es", "un", "fan", "token"]


@pytest.mark.asyncio
async def test_query_match_chz_matches_chz_based():
    """
    Test that a query 'chz' finds a match in a text that only contains '$CHZ-based'.
    """
    from datetime import datetime, timezone
    from src.models.schemas import PageData
    from src.detectors.query_match import QueryMatchDetector

    page = PageData(
        url="https://example.com/crypto",
        final_url="https://example.com/crypto",
        html_raw="<html><body><p>$CHZ-based ecosystem mechanisms are active.</p></body></html>",
        html_rendered="<html><body><p>$CHZ-based ecosystem mechanisms are active.</p></body></html>",
        text_content="$CHZ-based ecosystem mechanisms are active.",
        status_code=200,
        load_time_ms=100.0,
        word_count=5,
        is_ssr=True,
        is_https=True,
        ttfb_ms=100.0,
        scraped_at=datetime.now(timezone.utc)
    )

    detector = QueryMatchDetector(target_query="chz")
    result = await detector.analyze(page)

    assert result.score > 0.0
    # Both full content match and lead paragraph should identify the 'chz' subpart
    breakdown_map = {b.name: b.raw_score for b in result.breakdown}
    assert breakdown_map.get("Full Content Match", 0.0) >= 70.0
    assert breakdown_map.get("Opening Paragraph Match", 0.0) == 100.0


def test_recommendation_breakdown_normal_submetric_collapsed():
    """
    Test that a normal submetric (e.g. 'Logical Connectors') with multiple
    distinct recommendations across pages collapses to a single recommendation
    in recommendation_breakdown with page_count equal to affected_count.
    """
    rec_a = "Add transition words (furthermore, however, therefore) between paragraphs."
    rec_b = "Improve connective phrasing to strengthen logical flow."

    results = [
        {
            "url": "https://example.com/p1",
            "status": "done",
            "result": {
                "url": "https://example.com/p1",
                "detector_results": [
                    create_mock_detector_result("passage_quality", 0.10, [
                        {"name": "Logical Connectors", "raw_score": 40.0, "recommendations": [rec_a]}
                    ])
                ]
            }
        },
        {
            "url": "https://example.com/p2",
            "status": "done",
            "result": {
                "url": "https://example.com/p2",
                "detector_results": [
                    create_mock_detector_result("passage_quality", 0.10, [
                        {"name": "Logical Connectors", "raw_score": 40.0, "recommendations": [rec_b]}
                    ])
                ]
            }
        },
        {
            "url": "https://example.com/p3",
            "status": "done",
            "result": {
                "url": "https://example.com/p3",
                "detector_results": [
                    create_mock_detector_result("passage_quality", 0.10, [
                        {"name": "Logical Connectors", "raw_score": 40.0, "recommendations": [rec_a]}
                    ])
                ]
            }
        },
    ]

    page_issues, site_wide = aggregate_issues_by_topic(results)
    issue = next(i for i in page_issues if i["submetric"] == "Logical Connectors")

    assert issue["affected_count"] == 3
    assert issue["top_recommendation"] == rec_a
    breakdown = issue["recommendation_breakdown"]
    assert len(breakdown) == 1
    assert breakdown[0]["recommendation"] == rec_a
    assert breakdown[0]["page_count"] == 3


def test_press_release_dateline_detection():
    """
    Test press release dateline detection in detect_content_type.
    1) socios fixture -> news
    2) text starting with "MADRID, 2 de septiembre de 2026 — Socios.com anuncia…" -> news
    3) guide mentioning date mid-paragraph -> guide_blog
    4) page with schema BlogPosting and dateline -> guide_blog (schema takes priority)
    """
    import os
    from datetime import datetime, timezone
    from src.models.schemas import PageData
    from src.utils.content_type import detect_content_type

    # 1. Socios fixture
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "socios_securitize.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        socios_html = f.read()

    p_socios = PageData(
        url="https://www.socios.com/socios-securitize-partner-tokenized-sports-equity-offerings/",
        final_url="https://www.socios.com/socios-securitize-partner-tokenized-sports-equity-offerings/",
        html_raw=socios_html,
        html_rendered=socios_html,
        text_content="",
        status_code=200,
        load_time_ms=100.0,
        word_count=700,
        is_ssr=True,
        is_https=True,
        ttfb_ms=100.0,
        scraped_at=datetime.now(timezone.utc)
    )
    assert detect_content_type(p_socios) == "news"

    # 2. Text starting with Madrid dateline
    html_madrid = """
    <html><body>
    <h1>Socios.com anuncia acuerdo</h1>
    <p>MADRID, 2 de septiembre de 2026 — Socios.com anuncia una nueva colaboración estratégica en el sector deportivo.</p>
    </body></html>
    """
    p_madrid = PageData(
        url="https://example.com/articulos/acuerdo-deportivo",
        final_url="https://example.com/articulos/acuerdo-deportivo",
        html_raw=html_madrid,
        html_rendered=html_madrid,
        text_content="",
        status_code=200,
        load_time_ms=100.0,
        word_count=50,
        is_ssr=True,
        is_https=True,
        ttfb_ms=100.0,
        scraped_at=datetime.now(timezone.utc)
    )
    assert detect_content_type(p_madrid) == "news"

    # 3. Guide mentioning date mid-paragraph -> guide_blog
    html_guide = """
    <html><body>
    <h1>Guía de optimización de motores de búsqueda</h1>
    <p>Esta guía ofrece un análisis detallado sobre algoritmos de búsqueda. El 2 de septiembre de 2026 se llevó a cabo una actualización importante de los motores.</p>
    </body></html>
    """
    p_guide = PageData(
        url="https://example.com/articulos/guia-motores-busqueda",
        final_url="https://example.com/articulos/guia-motores-busqueda",
        html_raw=html_guide,
        html_rendered=html_guide,
        text_content="",
        status_code=200,
        load_time_ms=100.0,
        word_count=50,
        is_ssr=True,
        is_https=True,
        ttfb_ms=100.0,
        scraped_at=datetime.now(timezone.utc)
    )
    assert detect_content_type(p_guide) == "guide_blog"

    # 4. Schema BlogPosting + dateline -> guide_blog (Schema wins!)
    html_blog_dateline = """
    <html>
    <head>
    <script type="application/ld+json">{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Blog title"}</script>
    </head>
    <body>
    <h1>Blog Post Title</h1>
    <p>MADRID, 2 de septiembre de 2026 — Socios.com anuncia algo en su blog personal.</p>
    </body></html>
    """
    p_blog = PageData(
        url="https://example.com/blog/post",
        final_url="https://example.com/blog/post",
        html_raw=html_blog_dateline,
        html_rendered=html_blog_dateline,
        text_content="",
        status_code=200,
        load_time_ms=100.0,
        word_count=50,
        is_ssr=True,
        is_https=True,
        ttfb_ms=100.0,
        scraped_at=datetime.now(timezone.utc)
    )
    assert detect_content_type(p_blog) == "guide_blog"

    # 5. False positive blog metadata / author lines must return False
    from src.utils.lang_patterns import is_press_release_dateline

    assert is_press_release_dateline("By John Smith, June 5, 2026 - 8 min read. In this guide…") is False
    assert is_press_release_dateline("Updated, March 3, 2026 - Here is how to buy fan tokens") is False
    assert is_press_release_dateline("María, 5 de junio de 2026 – 6 min de lectura. Qué es un fan token") is False
    assert is_press_release_dateline("Guide to SEO. Posted by admin, 12 May 2026 - 3 comments") is False

    # 6. True positives must return True
    assert is_press_release_dateline("MIAMI and MADRID, September 2nd, 2026 — Securitize…") is True
    assert is_press_release_dateline("MADRID, 2 de septiembre de 2026 — Socios.com anuncia…") is True
    assert is_press_release_dateline("Madrid, 2 de septiembre de 2026 — Socios.com anuncia…") is True
    assert is_press_release_dateline("LONDON, Sept. 2, 2026 /PRNewswire/ — …") is True


@pytest.mark.asyncio
async def test_site_wide_issues_grouped_by_domain_and_csv():
    """
    Test batch audit with multiple domains:
    3 pages of a.com and 2 of b.com.
    Trust Pages fails in 3 of a.com and 1 of b.com.
    -> Two separate site issue entries with their counts.
    -> CSV issues export has Scope "Site-wide (a.com)" and "Site-wide (b.com)".
    """
    from datetime import datetime, timezone
    from httpx import AsyncClient, ASGITransport
    from main import app, batch_jobs

    results = [
        # 3 pages on a.com (all fail Trust Pages)
        {
            "url": "https://a.com/page1",
            "status": "done",
            "result": {
                "url": "https://a.com/page1",
                "detector_results": [
                    create_mock_detector_result("eeat_authority", 0.12, [
                        {"name": "Trust Pages", "raw_score": 30.0, "recommendations": ["Create About Us page"]}
                    ])
                ]
            }
        },
        {
            "url": "https://a.com/page2",
            "status": "done",
            "result": {
                "url": "https://a.com/page2",
                "detector_results": [
                    create_mock_detector_result("eeat_authority", 0.12, [
                        {"name": "Trust Pages", "raw_score": 30.0, "recommendations": ["Create About Us page"]}
                    ])
                ]
            }
        },
        {
            "url": "https://a.com/page3",
            "status": "done",
            "result": {
                "url": "https://a.com/page3",
                "detector_results": [
                    create_mock_detector_result("eeat_authority", 0.12, [
                        {"name": "Trust Pages", "raw_score": 30.0, "recommendations": ["Create About Us page"]}
                    ])
                ]
            }
        },
        # 2 pages on b.com (only 1 fails Trust Pages)
        {
            "url": "https://b.com/page1",
            "status": "done",
            "result": {
                "url": "https://b.com/page1",
                "detector_results": [
                    create_mock_detector_result("eeat_authority", 0.12, [
                        {"name": "Trust Pages", "raw_score": 30.0, "recommendations": ["Create Team page"]}
                    ])
                ]
            }
        },
        {
            "url": "https://b.com/page2",
            "status": "done",
            "result": {
                "url": "https://b.com/page2",
                "detector_results": [
                    create_mock_detector_result("eeat_authority", 0.12, [
                        {"name": "Trust Pages", "raw_score": 100.0, "recommendations": []}
                    ])
                ]
            }
        },
    ]

    page_issues, site_wide = aggregate_issues_by_topic(results)

    # Must produce 2 separate site-wide issue entries
    assert len(site_wide) == 2

    # First entry: a.com with 3 affected pages out of 3
    issue_a = next(i for i in site_wide if i["domain"] == "a.com")
    assert issue_a["submetric"] == "Trust Pages"
    assert issue_a["affected_count"] == 3
    assert issue_a["total_domain_pages"] == 3
    assert len(issue_a["affected_urls"]) == 3

    # Second entry: b.com with 1 affected page out of 2
    issue_b = next(i for i in site_wide if i["domain"] == "b.com")
    assert issue_b["submetric"] == "Trust Pages"
    assert issue_b["affected_count"] == 1
    assert issue_b["total_domain_pages"] == 2
    assert len(issue_b["affected_urls"]) == 1

    # Verify CSV issues export contains Scope by domain
    job_id = "test-domain-grouping-csv"
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "done",
        "total": 5,
        "completed": 5,
        "results": results,
        "issues_by_topic": page_issues,
        "site_wide_issues": site_wide,
        "created_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/batch/{job_id}/issues.csv")
        assert res.status_code == 200
        text = res.content.decode("utf-8-sig")
        lines = text.strip().splitlines()

        # Header
        assert lines[0].startswith("Priority,Scope,Topic,Dimension")

        # Must have Site-wide (a.com) and Site-wide (b.com)
        scopes = [line.split(",")[1] for line in lines[1:]]
        assert "Site-wide (a.com)" in scopes
        assert "Site-wide (b.com)" in scopes


def test_press_release_dateline_author_name_rejection():
    """
    Capitalized location datelines (DATELINE_CAP_REGEX) must reject blog author lines
    where a surname is mistaken for a location (e.g. María López, Carlos Cano),
    and only accept capitalized datelines at the beginning of text or after a sentence boundary.
    """
    from src.utils.lang_patterns import is_press_release_dateline

    # Blog author lines followed by em-dash must return False
    assert is_press_release_dateline("María López, 5 de junio de 2026 — Hoy te explico qué es un fan token") is False
    assert is_press_release_dateline("Carlos Cano, 3 de mayo de 2026 — En esta guía") is False

    # Valid capitalized datelines at start or after sentence boundary must return True
    assert is_press_release_dateline("Madrid, 2 de septiembre de 2026 — Socios.com anuncia…") is True
    assert is_press_release_dateline("Nueva alianza. Madrid, 2 de septiembre de 2026 — Socios.com anuncia…") is True


def test_is_challenge_page_detection():
    """
    Test is_challenge_page anti-bot detection logic:
    - Synthetic HTML with title 'One moment, please...' and 20 words -> True
    - HTML with script of challenge-platform of Cloudflare -> True
    - 800-word article mentioning 'Just a moment' in a paragraph -> False
    """
    from src.services.fetcher import is_challenge_page

    # 1. Synthetic HTML with title "One moment, please..." and 20 words -> True
    html_cf_title = (
        "<!DOCTYPE html><html><head><title>One moment, please...</title></head>"
        "<body><p>" + " ".join(["security", "verification"] * 10) + "</p></body></html>"
    )
    text_cf_title = " ".join(["security", "verification"] * 10)
    assert is_challenge_page("One moment, please...", text_cf_title, html_cf_title) is True

    # 2. HTML with Cloudflare challenge-platform script -> True
    html_cf_script = (
        "<!DOCTYPE html><html><head>"
        "<script src=\"/cdn-cgi/challenge-platform/scripts/jsd/main.js\"></script>"
        "</head><body><div>Verification required</div></body></html>"
    )
    assert is_challenge_page(title="Just a moment...", text="Verification required", html=html_cf_script) is True

    # 3. An 800-word substantive article mentioning "Just a moment" in a paragraph -> False
    long_body = "Just a moment while we explore this topic. " + " ".join(["content"] * 800)
    html_article = f"<!DOCTYPE html><html><head><title>Valid Article</title></head><body><p>{long_body}</p></body></html>"
    assert is_challenge_page(title="Valid Article", text=long_body, html=html_article) is False


def test_press_release_dateline_with_colon():
    """
    Test dateline detection with optional colon/dot before dash, and colon alone for uppercase.
    """
    from src.utils.lang_patterns import is_press_release_dateline

    # True for uppercase location with colon-dash and colon alone
    assert is_press_release_dateline("LONDON, September 16th 2026:— Socios.com, the leading…") is True
    assert is_press_release_dateline("LONDON, September 16th 2026: Socios.com…") is True

    # All blog author and metadata cases must remain False
    assert is_press_release_dateline("By John Smith, June 5, 2026 - 8 min read. In this guide…") is False
    assert is_press_release_dateline("Updated, March 3, 2026 - Here is how to buy fan tokens") is False
    assert is_press_release_dateline("María, 5 de junio de 2026 – 6 min de lectura. Qué es un fan token") is False
    assert is_press_release_dateline("Guide to SEO. Posted by admin, 12 May 2026 - 3 comments") is False
    assert is_press_release_dateline("María López, 5 de junio de 2026 — Hoy te explico qué es un fan token") is False
    assert is_press_release_dateline("Carlos Cano, 3 de mayo de 2026 — En esta guía") is False


@pytest.mark.asyncio
async def test_batch_audit_challenge_page_error_and_issues_omission():
    """
    Test that a challenge page in batch audit:
    - Results in status 'error'
    - Has error message: 'This page is protected by an anti-bot challenge and could not be analyzed. Try again later or use Paste Text.'
    - Has no score (result is None, total score 'N/A' in CSV)
    - The URL does not count in issues_by_topic or site_wide_issues.
    """
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch
    from httpx import AsyncClient, ASGITransport
    from main import app, batch_jobs, process_batch_job
    from src.models.schemas import AuditResponse
    from src.scrapers.base_scraper import ChallengePageError
    from src.utils.batch_aggregator import aggregate_issues_by_topic

    challenge_msg = (
        "This page is protected by an anti-bot challenge and could not be analyzed. "
        "Try again later or use Paste Text."
    )

    # Mock run_single_audit to simulate 1 normal page and 1 challenge page
    normal_audit = AuditResponse(
        url="https://example.com/ok",
        total_score=85.0,
        dimensions=[],
        scoring_version="v2.3",
        analysis_time_ms=100.0,
        detector_results=[
            create_mock_detector_result("technical_infrastructure", 0.10, [
                {"name": "AI Bot Access", "raw_score": 60.0, "recommendations": ["Unblock AI bots"]}
            ])
        ]
    )

    async def mock_run_single_audit(req, scraper, semaphore, **kwargs):
        if req.url == "https://example.com/blocked":
            raise ChallengePageError(url=req.url, reason=challenge_msg)
        return normal_audit

    job_id = "test-challenge-batch"
    urls = ["https://example.com/ok", "https://example.com/blocked"]
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "total": 2,
        "completed": 0,
        "results": [
            {"url": u, "status": "pending", "result": None, "error": None}
            for u in urls
        ],
        "issues_by_topic": [],
        "site_wide_issues": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "target_query": None,
    }

    with patch("main.run_single_audit", side_effect=mock_run_single_audit):
        await process_batch_job(job_id, urls, None)

    job = batch_jobs[job_id]
    assert job["status"] == "done"
    assert job["completed"] == 2

    # Normal item
    item_ok = job["results"][0]
    assert item_ok["status"] == "done"
    assert item_ok["result"] is not None

    # Challenge item
    item_blocked = job["results"][1]
    assert item_blocked["status"] == "error"
    assert item_blocked["result"] is None
    assert item_blocked["error"] == challenge_msg

    # Blocked URL must NOT appear in issues_by_topic or site_wide_issues
    all_affected_urls = [
        u
        for issue in (job["issues_by_topic"] + job["site_wide_issues"])
        for u in issue.get("affected_urls", [])
    ]
    assert "https://example.com/blocked" not in all_affected_urls

    # Check CSV export output
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/batch/{job_id}/csv")
        assert res.status_code == 200
        content = res.content.decode("utf-8-sig")
        lines = content.strip().splitlines()
        # Find the line for the blocked URL
        blocked_line = next(line for line in lines if "https://example.com/blocked" in line)
        cols = [c.strip('"') for c in blocked_line.split(",")]
        # Total Score must be N/A
        assert cols[1] == "N/A"
        # Status must be error
        assert "error" in blocked_line
        # Error column must contain challenge_msg
        assert challenge_msg in blocked_line


@pytest.mark.asyncio
async def test_single_audit_challenge_page_error():
    """
    Test that a challenge page in single audit returns HTTP 400 with the exact challenge message.
    """
    from unittest.mock import patch
    from httpx import AsyncClient, ASGITransport
    from main import app
    from src.scrapers.base_scraper import ChallengePageError

    challenge_msg = (
        "This page is protected by an anti-bot challenge and could not be analyzed. "
        "Try again later or use Paste Text."
    )

    async def mock_run_single_audit(req, scraper, semaphore, **kwargs):
        raise ChallengePageError(url=req.url, reason=challenge_msg)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("main.run_single_audit", side_effect=mock_run_single_audit):
            res = await client.post("/api/audit", json={"url": "https://example.com/challenge"})
            assert res.status_code == 400
            data = res.json()
            assert data["detail"] == challenge_msg


@pytest.mark.asyncio
async def test_fetcher_retry_on_challenge_page():
    """
    Test that PlaywrightScraper retries after 5 seconds upon receiving a challenge page.
    If still challenge page, raises ChallengePageError.
    """
    from unittest.mock import AsyncMock, patch, MagicMock
    from src.scrapers.playwright_scraper import PlaywrightScraper
    from src.scrapers.base_scraper import ChallengePageError

    scraper = PlaywrightScraper()
    scraper.settings.challenge_retry_delay_seconds = 0.01  # fast in test

    mock_page = AsyncMock()
    mock_page.on = MagicMock()
    mock_page.url = "https://example.com/captcha"
    mock_page.title.return_value = "One moment, please..."
    mock_page.content.return_value = "<html><head><title>One moment, please...</title></head><body>Verify</body></html>"
    mock_page.goto.return_value = MagicMock(status=200, headers={})

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context
    scraper._browser = mock_browser

    with patch("src.scrapers.playwright_scraper.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(scraper, "_extract_text_content", return_value="Verify"):
            with pytest.raises(ChallengePageError) as exc_info:
                await scraper.scrape("https://example.com/captcha")

            assert "This page is protected by an anti-bot challenge and could not be analyzed." in str(exc_info.value)
            # Must have retried with sleep
            assert mock_sleep.called





