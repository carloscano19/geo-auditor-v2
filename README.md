# GEO-AUDITOR AI

A production-ready auditor and optimization engine for Generative Engine Optimization (GEO) and Answer Engine Optimization (AEO).

---

## 1. What It Is

**GEO-AUDITOR AI** scores how ready a web page is to be cited and recommended by AI engines—including ChatGPT, Google Gemini, Anthropic Claude, and Perplexity. It explains why a page received its score across deterministic on-page dimensions and generates concrete, editorial-ready fixes.

Built for **SEO, content, and editorial teams** who need to adapt their content strategies beyond traditional search engine rankings toward AI visibility and answer-engine citability.

- **Production URL:** [https://geo-auditor-v2.vercel.app](https://geo-auditor-v2.vercel.app)
- **Backend API:** [https://geo-auditor-v2.onrender.com](https://geo-auditor-v2.onrender.com)
- **Legacy Redirect:** Traffic to `carloscanofernandez.com/geo-auditor/` is automatically redirected to the Vercel production deployment.

---

## 2. Features

- **Single URL & Pasted Text Audits:** Audit any live web page by URL (rendered via headless Playwright) or paste raw HTML/plain text directly to analyze staging content or pages behind strict anti-bot protections.
- **Target Query Optimization:** Optional query input that adds the **Query Match** dimension and determines the Google search query used for competitive discovery.
- **Batch Audits:** Analyze up to 20 URLs concurrently with background job processing, progress reporting, aggregated issues grouped by topic, site-wide recurring issues by domain, CSV exports, and direct "Analyze with AI" triggers.
- **AI Recommendations in One Call (`POST /api/ai/plan`):** Generates a complete editorial action plan in a single AI roundtrip:
  - **Suggested opening lead paragraph (`suggested_lead`):** Inverted-pyramid answer capsule with strict numerical hallucination protection and non-distorting prose.
  - **Inconsistencies (`inconsistencies`):** Factual contradictions or conflicting statements detected within the text.
  - **Questions to answer (`questions_to_answer`):** Relevant editorial queries incorporating real Google People Also Ask data.
  - **Suggested H2 structure (`suggested_h2_structure`):** Recommended topical outline and question-based headings.
  - **Suggested table (`suggested_table`):** Structured comparison or data summary table with headers and rows.
  - **Data opportunities (`data_opportunities`):** High-value numerical, statistical, or primary-source data points to add.
  - **Sources to cite (`sources_to_cite`):** Authoritative candidate references from Google search results, strictly filtered against image/video stock banks, e-commerce shops, and Google domains.
  - **Paragraphs to add (`paragraphs_to_add`):** Ready-to-use editorial paragraphs addressing identified content gaps.
  - **Consolidated Schema.org JSON-LD (`combined_schema`):** A single, unified `@graph` structure combining `Article` (or `NewsArticle`/`Review`/`Product`), `FAQPage`, and `Organization`.
- **Change Search / Retry with Google Data:** Change target queries dynamically or re-fetch live Google SERP data if external queries timed out.
- **Off-Page Signals via Ahrefs API v3 (`POST /api/offpage`):** On-demand evaluation of Domain Rating (DR), URL Rating (UR), search traffic, referring domains, backlink counts, and top linking pages.
- **Editorial Report in Word (.docx) (`POST /api/export/brief`):** Downloadable client-ready Word document containing executive summary, score breakdown, failing metrics, and AI recommendations.
- **Access Code Gatekeeper:** Optional HMAC-based password protection with IP rate limiting (HTTP 429 response after 10 consecutive failed attempts within 15 minutes).
- **Server Cold-Start Management:** The frontend actively monitors backend health and displays a *"Waking up the server… this can take up to a minute"* notification when Render spins up from idle.

---

## 3. Scoring Dimensions & Weights

### Scoring Principle
The **Citation Score** (0–100) is **strictly deterministic and heuristic**. Calls to LLMs, Google SERP data, or Ahrefs **NEVER** alter the Citation Score. An audit produces identical scores regardless of external API quotas, token status, or network connectivity.

### The 11 Dimensions (`scoring_version`: `v2.3`)
Weights and subdimensions are defined in `backend/config/scoring_weights.json` and evaluated by modular detectors in `backend/src/detectors/`:

| Dimension | Key in JSON | Weight | What It Measures (from `backend/src/detectors/`) |
|:---|:---|:---:|:---|
| **Technical Infrastructure** | `technical_infrastructure` | **10%** (0.10) | HTTPS protocol, server-side rendering (SSR), crawlability, AI bot access in `robots.txt`, and TTFB render speed. Subdimensions: `https` (0.20), `ssr_detection` (0.20), `crawlability` (0.20), `ai_bot_access` (0.20), `render_speed` (0.20). |
| **Metadata & Schema** | `metadata_schema` | **4%** (0.04) | Presence and syntax validity of meta tags (title, description, canonical, OpenGraph, Twitter) and Schema.org structured data (JSON-LD and Microdata). |
| **AEO Structure** | `aeo_structure` | **12%** (0.12) | Heading hierarchy (H1-H6), answer capsules directly under headers, inverted pyramid lead structure, and list/table scannability. |
| **Passage Quality** | `passage_quality` | **12%** (0.12) | Lexical richness, complete sentences, content depth, and standalone autonomous passages for AI retrieval. Subdimensions: `lexical_richness` (0.25), `complete_sentences` (0.25), `content_depth` (0.25), `autonomous_passages` (0.25). |
| **Evidence Density** | `evidence_density` | **18%** (0.18) | Presence of verifiable factual claims, statistical data points, external source citations, and quantitative evidence. |
| **E-E-A-T Authority** | `eeat_authority` | **12%** (0.12) | Authorship verification (author bios, bylines), experience signals, and trust pages (about, contact, editorial policy). Subdimensions: `authorship_verification` (0.40), `experience_signals` (0.35), `trust_pages` (0.25). |
| **Entity Identification** | `entity_identification` | **6%** (0.06) | Named entity recognition, entity salience, disambiguation, Wikidata/Schema grounding, and topic relevance. |
| **Freshness** | `freshness` | **4%** (0.04) | Date currency: explicit publication/update dates in metadata/schema/body, temporal markers, and content recency. Subdimension: `date_currency` (1.00). |
| **Format Citability** | `format_citability` | **6%** (0.06) | Content formatting scannability (bullet lists, tables, bold key terms) and multimedia (relevant images, figures, descriptive alt text). Subdimensions: `scannability` (0.5714), `multimedia` (0.4286). |
| **Links & Verifiability** | `links_verifiability` | **6%** (0.06) | External link quality (non-broken, reputable outbound links) and source diversity (variety of citing external domains). Subdimensions: `external_link_quality` (0.50), `source_diversity` (0.50). |
| **Query Match** *(optional)* | `query_match` | **10%** (0.10) | Evaluated **only** when a Target query is provided. BM25 similarity. Subdimensions: `full_content_similarity` (0.40), `best_passage_similarity` (0.40), `first_paragraph_presence` (0.20). |

### Score Normalization Without Target Query
When no `target_query` is provided:
- The `query_match` dimension (weight 0.10) is omitted from the evaluation.
- The sum of active dimension weights is `0.90` (1.00 - 0.10).
- In `backend/src/services/audit_service.py`, each dimension's contribution is computed as:
  $$\text{contribution} = \frac{\text{score} \times \text{weight}}{\sum \text{active\_weights}}$$
- Dividing by `0.90` scales all 10 active dimensions up proportionally (multiplying each by approximately 1.111), ensuring the total score is always normalized to 100%.

> **Critical Bot Block Cap:** If `robots.txt` or meta robots explicitly block search/AI crawlers (`OAI-SearchBot`, `GPTBot`, etc.), the overall score is capped at **30/100**.

### Content-Type Classification (`backend/src/utils/content_type.py`)
Content classification is determined automatically according to priority rules:
1. `news`: News or press releases (`NewsArticle` or `PressRelease` in Schema.org, press release dateline in the first 400 characters such as `"PARIS, Oct 5 —"`, or URL paths `/news/`, `/newsroom/`, `/press/`, `/noticias/`, `/prensa/`).
2. `guide_blog`: General articles, guides, and blog posts (default fallback; also overrides news paths if an educational/guide H1 is detected).
3. `product`: E-commerce product pages (`Product` in Schema.org, or URL paths `/product/`, `/producto/`, `/shop/`, `/tienda/`).
4. `review`: Review and evaluation pages (`Review` in Schema.org, `/reviews/`, `/resenas/`, or review keywords in title/H1).

---

## 4. Architecture & Services

```
                    +------------------------------------+
                    |        User Browser (Client)       |
                    +-----------------+------------------+
                                      |
         HTTPS Requests               | Redirects (Meta Refresh)
               |                      v
               v        +-----------------------------+
+-----------------------------+ |  carloscanofernandez.com    |
|   Vercel (Production Host)  | |  /public_html/geo-auditor/  |
|   Project: geo-auditor-v2   | +-----------------------------+
|   Next.js 14 Static Export  |
+--------------+--------------+
               |
               | REST API calls (X-Access-Code)
               v
+-------------------------------------------------------------+
|                     Render (Backend Host)                   |
|              https://geo-auditor-v2.onrender.com            |
|                   FastAPI + Python 3.11/3.14                |
|                    Headless Chromium Engine                 |
+--------------+-------------------+-------------------+------+
               |                   |                   |
               v                   v                   v
+-----------------------+ +-----------------+ +-----------------------+
|  Company LLM Gateway  | |   DataForSEO    | |     Ahrefs API v3     |
| hub.culturabuilder.com| |  SERP Live Adv  | |  backlinks-stats,     |
|  (SSE Streamed Comps) | | (PAA, Overview) | |  metrics, DR, UR,     |
|                       | |                 | |  all-backlinks        |
+-----------------------+ +-----------------+ +-----------------------+
               ^
               | Kept awake via
+--------------+--------------+
|     UptimeRobot Monitor     |
|   (GET / HEAD /api/health)  |
+-----------------------------+
```

- **Frontend:** Next.js 14 static export (`output: 'export'`, `trailingSlash: true`) deployed on Vercel at project `geo-auditor-v2` with Root Directory set to `frontend`.
- **Backend:** FastAPI application running on Render (`https://geo-auditor-v2.onrender.com`), with Playwright browser dependencies for headless DOM scraping.
- **External Services:**
  - **Company LLM Gateway (`hub.culturabuilder.com`):** OpenAI-compatible API running via SSE streaming (`"stream": true`) through Cloudflare.
  - **DataForSEO:** Live Advanced Google SERP queries (`v3/serp/google/organic/live/advanced` with `load_async_ai_overview: True`) retrieving People Also Ask, organic competitors, and AI Overview citations.
  - **Ahrefs API v3:** Endpoints `/site-explorer/backlinks-stats`, `/site-explorer/metrics`, `/site-explorer/domain-rating`, `/site-explorer/url-rating-history`, and `/site-explorer/all-backlinks`.
- **Legacy Hostinger Redirect:** GitHub Actions FTP deploy action that pushes a redirect `index.html` referencing `vars.NEW_FRONTEND_URL` to Hostinger on each push to `main`.
- **Keep-Alive:** UptimeRobot monitor pinging `/api/health` via GET or HEAD every 5 minutes keeps the Render backend awake.

---

## 5. Repository Structure

```
├── .agent/                       # Development rules and system directives
├── .github/workflows/deploy.yml  # Legacy Hostinger FTP redirect deployment
├── AGENTS.md                     # Engineering and Git workflow rules
├── README.md                     # Central handover and operations manual
├── backend/
│   ├── config/
│   │   ├── scoring_weights.json  # Dimensions and subdimension weight definitions (v2.3)
│   │   └── settings.py           # Pydantic BaseSettings loading all environment variables
│   ├── main.py                   # FastAPI app, routing, CORS, and auth middleware
│   ├── requirements.txt          # Python dependencies
│   ├── src/
│   │   ├── detectors/            # 11 isolated audit dimension detectors
│   │   │   ├── infrastructure.py     # technical_infrastructure
│   │   │   ├── metadata.py           # metadata_schema
│   │   │   ├── aeo_structure.py      # aeo_structure
│   │   │   ├── passage_quality.py    # passage_quality
│   │   │   ├── evidence_density.py   # evidence_density
│   │   │   ├── authority.py          # eeat_authority
│   │   │   ├── entity.py             # entity_identification
│   │   │   ├── freshness.py          # freshness
│   │   │   ├── formatting.py         # format_citability
│   │   │   ├── links.py              # links_verifiability
│   │   │   ├── query_match.py        # query_match
│   │   │   └── base_detector.py      # Base detector interface
│   │   ├── models/
│   │   │   └── schemas.py            # Pydantic request/response models
│   │   ├── scrapers/
│   │   │   ├── playwright_scraper.py # Headless Playwright scraper
│   │   │   └── base_scraper.py       # Base scraper definitions and exceptions
│   │   ├── services/
│   │   │   ├── audit_service.py      # Core audit pipeline orchestration
│   │   │   ├── llm_client.py         # Streaming client for company LLM gateway
│   │   │   ├── serp_client.py        # DataForSEO Google Live SERP client
│   │   │   └── ahrefs_client.py      # Ahrefs API v3 client
│   │   └── utils/
│   │       ├── content_type.py       # Content classification heuristics
│   │       ├── lang_patterns.py      # Bilingual patterns (EN/ES) and text rules
│   │       ├── text_processing.py    # DOM content isolation and boilerplate removal
│   │       ├── challenge_detection.py# Anti-bot detection (Cloudflare, etc.)
│   │       ├── batch_aggregator.py   # Batch topic aggregation logic
│   │       └── docx_brief.py         # Word (.docx) report generator
│   └── tests/                    # Pytest test suite (>200 tests)
└── frontend/
    ├── app/                      # Next.js 14 App Router pages and layouts
    ├── components/               # React UI components (AuditForm, AuditResults, etc.)
    ├── lib/                      # Client API adapter and helpers (lib/api.ts)
    ├── next.config.mjs           # Next.js export configuration
    └── package.json              # Node dependencies and build scripts
```

---

## 6. Environment Variables

All backend variables use the `GEO_AUDITOR_` prefix and are defined in `backend/config/settings.py`:

| Variable | Default Value | Description |
|:---|:---:|:---|
| `GEO_AUDITOR_APP_NAME` | `"GEO-AUDITOR AI"` | Application name. |
| `GEO_AUDITOR_APP_VERSION` | `"v2.3"` | Application version (single source of truth). |
| `GEO_AUDITOR_DEBUG` | `False` | Debug mode toggle. |
| `GEO_AUDITOR_HOST` | `"0.0.0.0"` | Server bind host address. |
| `GEO_AUDITOR_PORT` | `8000` | Server bind port. |
| `GEO_AUDITOR_CORS_ORIGINS` | `["http://localhost:3000", "https://carloscanofernandez.com", "http://carloscanofernandez.com"]` | Allowed CORS origins JSON list. |
| `GEO_AUDITOR_CORS_ORIGIN_REGEX` | `""` | Regex for dynamic CORS origin matching (e.g. `https://geo-auditor-v2(-[a-z0-9-]+)?\.vercel\.app`). |
| `GEO_AUDITOR_SCRAPER_TIMEOUT_MS` | `30000` | Scraper timeout in milliseconds (30 s). |
| `GEO_AUDITOR_SCRAPER_WAIT_UNTIL` | `"load"` | Playwright page load condition (`"load"`, `"domcontentloaded"`, `"networkidle"`). |
| `GEO_AUDITOR_MAX_CONTENT_LENGTH` | `5000000` | Maximum raw content size (5 MB). |
| `GEO_AUDITOR_CHALLENGE_RETRY_DELAY_SECONDS` | `5.0` | Delay in seconds before retrying when a challenge is detected. |
| `GEO_AUDITOR_MAX_ANALYSIS_TIME_SECONDS` | `60` | Maximum analysis timeout budget in seconds. |
| `GEO_AUDITOR_SCORING_WEIGHTS_PATH` | `Path(__file__).parent / "scoring_weights.json"` | Path to the weights JSON file. |
| `GEO_AUDITOR_LLM_BASE_URL` | `""` | Base URL of the OpenAI-compatible LLM gateway. |
| `GEO_AUDITOR_LLM_MODEL` | `""` | Target model identifier configured in Render. |
| `GEO_AUDITOR_LLM_API_KEY` | `""` | Bearer authorization token for the LLM gateway. |
| `GEO_AUDITOR_LLM_TIMEOUT_SECONDS` | `45.0` | Timeout for LLM calls (set to `240` in production on Render). |
| `GEO_AUDITOR_LLM_DAILY_LIMIT` | `200` | Maximum LLM requests per UTC calendar day. |
| `GEO_AUDITOR_LLM_MAX_TOKENS` | `16000` | Maximum token ceiling for model completions. |
| `GEO_AUDITOR_LLM_STREAMING` | `True` | Enables Server-Sent Events (SSE) streaming to prevent proxy timeouts. |
| `GEO_AUDITOR_DATAFORSEO_LOGIN` | `""` | DataForSEO API account login. |
| `GEO_AUDITOR_DATAFORSEO_PASSWORD` | `""` | DataForSEO API account password. |
| `GEO_AUDITOR_SERP_DAILY_LIMIT` | `100` | Maximum DataForSEO requests per UTC calendar day. |
| `GEO_AUDITOR_SERP_TIMEOUT_SECONDS` | `90.0` | Timeout in seconds for live Google SERP extraction. |
| `GEO_AUDITOR_ACCESS_CODE` | `""` | Required password for API endpoints when protection is active. |
| `GEO_AUDITOR_AHREFS_API_KEY` | `""` | Ahrefs API v3 bearer authorization token. |
| `GEO_AUDITOR_AHREFS_DAILY_LIMIT` | `50` | Maximum Ahrefs requests per UTC calendar day. |

### Dynamic Feature Activation
There are **no** `GEO_AUDITOR_AI_ENABLED` or `GEO_AUDITOR_SERP_ENABLED` environment variables. Features activate automatically via settings properties:
- **AI Recommendations (`ai_enabled`):** Automatically activates `True` only when `GEO_AUDITOR_LLM_BASE_URL`, `GEO_AUDITOR_LLM_MODEL`, and `GEO_AUDITOR_LLM_API_KEY` are all non-empty strings.
- **Google SERP Data (`serp_enabled`):** Automatically activates `True` only when `ai_enabled` is `True` AND both `GEO_AUDITOR_DATAFORSEO_LOGIN` and `GEO_AUDITOR_DATAFORSEO_PASSWORD` are non-empty strings.
- **Ahrefs Off-Page Metrics (`ahrefs_enabled`):** Automatically activates `True` when `GEO_AUDITOR_AHREFS_API_KEY` is non-empty.
- **Access Code Gatekeeper (`access_required`):** Automatically activates `True` when `GEO_AUDITOR_ACCESS_CODE` is non-empty.

### External Infrastructure Variables
- `PLAYWRIGHT_BROWSERS_PATH`: Configured in Render build/runtime environment so Playwright uses pre-installed browser binaries across deployments.
- `NEXT_PUBLIC_API_URL`: Configured in Vercel to point the frontend to the Render backend (`https://geo-auditor-v2.onrender.com`).
- `NEW_FRONTEND_URL`: GitHub Actions repository variable (`vars.NEW_FRONTEND_URL` = `https://geo-auditor-v2.vercel.app`) used to build the legacy redirect file.

---

## 7. API Endpoints

All endpoints except `/api/health` and `/api/version` enforce `X-Access-Code` authentication when `GEO_AUDITOR_ACCESS_CODE` is configured:

| Method | Path | Purpose | Requires Auth |
|:---|:---|:---|:---:|
| `GET`, `HEAD` | `/api/health` | Health and keep-alive probe (HEAD returns HTTP 200 without body) | **No** (exempt) |
| `GET` | `/api/version` | Reports app version, AI enabled, and SERP enabled status | **No** (exempt) |
| `POST` | `/api/auth/check` | Validates provided access code | Yes |
| `GET` | `/api/scoring-weights` | Returns current scoring weights configuration JSON | Yes |
| `POST` | `/api/audit` | Executes full on-page analysis for a URL or text | Yes |
| `POST` | `/api/ai/plan` | Generates unified editorial improvement plan (used by the frontend) | Yes |
| `POST` | `/api/ai/fixes` | Legacy quick fixes endpoint (kept for backward compatibility) | Yes |
| `POST` | `/api/offpage` | Retrieves Ahrefs off-page authority metrics | Yes |
| `POST` | `/api/export/brief` | Generates downloadable Word document (.docx) report | Yes |
| `POST` | `/api/batch` | Initiates asynchronous batch audit (max 20 URLs) | Yes |
| `GET` | `/api/batch/{job_id}` | Polls progress and results for a batch audit job | Yes |
| `GET` | `/api/batch/{job_id}/csv` | Downloads CSV summary of batch results | Yes |
| `GET` | `/api/batch/{job_id}/issues.csv` | Downloads aggregated topic issues CSV | Yes |

---

## 8. Costs and Quotas

| User Action | External APIs Triggered | Paid Credits Consumed? |
|:---|:---|:---:|
| **Single On-Page Audit** | Headless Playwright scraper | None (Local Compute) |
| **Batch Audit (up to 20 URLs)** | Headless Playwright scraper | None (Local Compute) |
| **Generate AI Plan** | DataForSEO (SERP) + Company LLM Gateway | **DataForSEO credits** (Company LLM has zero marginal cost) |
| **Regenerate / Change Query** | DataForSEO (SERP) + Company LLM Gateway | **DataForSEO credits** |
| **Check with Ahrefs** | Ahrefs API v3 | **Ahrefs plan units** |
| **Export Word Report / CSV** | None | None (Local Compute) |

### External Services Details
- **Company LLM Gateway (`hub.culturabuilder.com`):**
  - **No cost per use and NOT billed by tokens.** Handled internally by company infrastructure.
  - Quota limit: 200 requests/day (`GEO_AUDITOR_LLM_DAILY_LIMIT`).
  - Cache: In-memory cache for 24 hours keyed by content hash (max 100 entries).
- **DataForSEO:**
  - Endpoint: `https://api.dataforseo.com/v3/serp/google/organic/live/advanced` with `"load_async_ai_overview": True`.
  - Cost: A few cents or less per plan; check the DataForSEO dashboard for exact usage.
  - Triggered **once per AI plan** (not per audit) and upon each "Regenerate plan" or "Retry with Google data".
  - Quota limit: 100 requests/day (`GEO_AUDITOR_SERP_DAILY_LIMIT`).
  - Cache: In-memory cache for 24 hours keyed by query and market (max 100 entries).
- **Ahrefs API v3:**
  - Endpoints: `/site-explorer/backlinks-stats`, `/site-explorer/metrics`, `/site-explorer/domain-rating`, `/site-explorer/url-rating-history`, `/site-explorer/all-backlinks`.
  - Triggered **only** when the user clicks "Check with Ahrefs" in the frontend (never during single audits or batch audits).
  - Quota limit: 50 requests/day (`GEO_AUDITOR_AHREFS_DAILY_LIMIT`).
  - Cache: In-memory cache for 7 days keyed by URL (max 200 entries). Consumes corporate Ahrefs Workspace API units.
- **Important:** All in-memory caches and daily counters reset whenever the Render backend service restarts or redeploys.

---

## 9. Operations Runbook

### Changing the Access Code
1. Open the Render Dashboard -> `geo-auditor-v2` backend service -> **Environment**.
2. Modify `GEO_AUDITOR_ACCESS_CODE` with the new passkey.
3. Save changes. Render restarts the service automatically.

### Renewing the LLM Token
The company gateway uses an authorization bearer token generated by the CLI:
1. Run `chiliz auth login` on an authorized terminal.
2. Locate the token at:
   `~/Library/Application Support/Chiliz/opencode/data/opencode/auth.json`
3. Extract the `"access"` token string for `builder-ai`. Copy it without printing or logging it. *(Current token expiration: **28 March 2027**).*
4. Update `GEO_AUDITOR_LLM_API_KEY` in the Render environment settings. **Never commit or log this token.**

### Changing the AI Model
To switch models on the gateway:
1. Update `GEO_AUDITOR_LLM_MODEL` in Render with one of the models supported by the gateway (`builder-fast`, `builder-code`, `builder-plan`, `builder-auto`).
2. Save changes and redeploy.

### Replacing DataForSEO Credentials
1. Update `GEO_AUDITOR_DATAFORSEO_LOGIN` and `GEO_AUDITOR_DATAFORSEO_PASSWORD` in Render.
2. > [!CAUTION]
   > Do **NOT** regenerate the DataForSEO API password in the DataForSEO control panel unless you are also updating the LLM Tracking dashboard, as credentials are shared across projects.

### Replacing the Ahrefs API Key
1. Generate an API v3 key in the corporate Ahrefs Workspace settings.
2. Update `GEO_AUDITOR_AHREFS_API_KEY` in Render.

### Disabling LLM Streaming
If the LLM gateway proxy fails to support Server-Sent Events, set:
`GEO_AUDITOR_LLM_STREAMING=false` in Render to revert to standard synchronous JSON POST requests.

### Keeping the Backend Awake
On free Render tiers, instances sleep after 15 minutes of inactivity:
- Set up an external uptime monitor (e.g., UptimeRobot) pinging `https://geo-auditor-v2.onrender.com/api/health` via GET or HEAD every 5 minutes.
- Alternatively, upgrade the Render instance to a paid *Starter* plan.

### Deployment Flow
1. Never commit or push directly to `main`.
2. Work in a feature branch -> run tests and builds -> open Pull Request.
3. Fast-forward merge to `main`.
4. Render automatically builds and deploys backend commits on `main`.
5. Vercel automatically deploys frontend static updates from `main`.
6. GitHub Actions uploads the legacy Hostinger redirect page automatically.

---

## 10. Local Development

### Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Running the backend API server:
```bash
uvicorn main:app --reload --port 8000
```

Running backend tests:
```bash
pytest tests/
```

### Frontend Setup
```bash
cd frontend
npm install
```

Create `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Running the development server:
```bash
npm run dev
```

Building the static site:
```bash
npm run build
```
> [!IMPORTANT]
> Do **NOT** execute `npm run build` while `npm run dev` is active in the same terminal directory, as it can corrupt the Next.js cache. If corruption occurs, run `rm -rf .next` and rebuild.

---

## 11. Development Workflow (`AGENTS.md`)

- **Branching:** Always branch off `main` with a descriptive name. Never commit directly to `main`.
- **Merge Restrictions:** Merge to `main` only upon explicit instruction.
- **Validation Gates:** 
  - Every backend modification must pass `pytest` before commit.
  - Every frontend modification must pass `npm run build` before commit.
- **Language Integrity:** Linguistic patterns must be registered in `backend/src/utils/lang_patterns.py` in English and Spanish. Explanations returned by the API must always be in English.
- **App Version:** Sourced strictly from `settings.app_version`.
- **Documentation:** The README must be updated whenever environment variables, endpoints, or user-facing behavior change.

---

## 12. Troubleshooting

- **"Waking up the server…":** Render instance is resuming from spin-down. Wait up to 60 seconds for the service to answer `/api/health` (check UptimeRobot monitor status).
- **401 Unauthorized / Invalid Access Code:** Check the access code modal on the frontend and verify that `X-Access-Code` matches `GEO_AUDITOR_ACCESS_CODE`.
- **"The AI took too long to respond" (Error 524):** The upstream LLM gateway timed out behind Cloudflare (100 s limit). Ensure `GEO_AUDITOR_LLM_STREAMING=true` so tokens stream back immediately.
- **401 Unauthorized from LLM Provider:** The company gateway authorization token has expired or was revoked. Re-authenticate via `chiliz auth login` and update `GEO_AUDITOR_LLM_API_KEY`.
- **"Could not extract valid JSON from AI response":** The completion was truncated or returned malformed JSON. The client automatically attempts `json-repair` and retries once with concise instructions. Check backend logs for `finish_reason=length`.
- **"Ahrefs rejected the API key":** Ensure `GEO_AUDITOR_AHREFS_API_KEY` is valid and the corporate workspace subscription has remaining units.
- **"Google data unavailable":** DataForSEO timed out or exceeded daily quotas. Use the "Retry with Google data" button in the plan view to query again.
- **"Protected by an anti-bot challenge":** Cloudflare or Incapsula blocked the headless scraper. Copy the rendered text or HTML and use the **Paste Text** tab.
- **CORS Errors:** Verify that the frontend domain matches `GEO_AUDITOR_CORS_ORIGINS` or matches `GEO_AUDITOR_CORS_ORIGIN_REGEX` (e.g. `https://geo-auditor-v2(-[a-z0-9-]+)?\.vercel\.app`).

---

## 13. Known Limitations

- **Heuristic On-Page Scoring:** The score evaluates structural and semantic readiness for AI engines; it does not guarantee that a specific LLM will cite the page for every prompt.
- **Single Page Scope:** The auditor assesses the target URL in isolation rather than sitewide domain authority.
- **Render Free Tier Quotas:** Free instances provide 512 MB RAM and sleep after inactivity without the keep-alive monitor.
- **In-Memory Volatility:** Rate limits, batch job summaries, and response caches are lost upon service restarts.
- **Mandatory Editorial Review:** AI-generated paragraphs, schema changes, and leads must be reviewed by humans before publication, especially for regulated or financial topics.
- **Vercel Hobby Plan:** Intended for non-commercial evaluation; must upgrade to Vercel Pro if officially institutionalized across corporate teams.

---

## 14. Roadmap

- **Phase 7 Empirical Score Validation:** Batch audit sets of cited versus non-cited URLs extracted from company LLM tracking to correlate dimensional scores with real-world AI citations.
- **Daily Editorial Workflow:** Enhance daily editorial UX and recommendations review workflows.
- **LLM Tracker Integration:** Integrate GEO-Auditor directly as an on-demand audit module within the central LLM tracking dashboard.
- **Slack Alert Integration:** Slack bot idea to automatically audit newly published articles and alert editors to missing schema or weak lead paragraphs.
- **Dedicated Backend Infrastructure:** Move Render instance to a persistent, paid plan to eliminate cold starts and resource limits.
