# GEO-AUDITOR AI

A production-ready auditor and optimization engine for Generative Engine Optimization (GEO) and Answer Engine Optimization (AEO).

---

## 1. What It Is

**GEO-AUDITOR AI** scores how ready a web page is to be cited and recommended by AI answer engines—including ChatGPT, Google Gemini, Anthropic Claude, and Perplexity. It explains why a page received its score across deterministic on-page dimensions and generates concrete, actionable fixes.

Built for **SEO, content, and editorial teams** who need to adapt their content strategy beyond traditional search engine rankings towards AI visibility and answer-engine citability.

- **Live URL:** [https://geo-auditor-v2.vercel.app](https://geo-auditor-v2.vercel.app)
- **Legacy Redirect:** Traffic to `carloscanofernandez.com/geo-auditor/` is automatically redirected to the Vercel app.

---

## 2. Features

- **Single URL & Pasted Text Audits:** Audit any live web page by URL (rendered via headless Playwright) or paste raw HTML/plain text directly to analyze staging content or pages behind strict CAPTCHAs.
- **Target Query Optimization:** Optional query input that enables the **Query Match** scoring dimension and seeds real Google SERP retrieval.
- **Batch Audits:** Analyze up to 20 URLs concurrently with background job processing, progress reporting, aggregated issues grouped by topic, domain-wide recurring issues, CSV exports, and direct "Analyze with AI" triggers.
- **Unified AI Recommendations (Single Call):** Generates a complete editorial action plan in a single AI roundtrip:
  - Suggested opening lead paragraph (with strict numerical hallucination protection, investor advice filtering, and non-distorting prose).
  - Content inconsistencies and factual contradictions.
  - Questions to answer (incorporating real Google People Also Ask data).
  - Recommended H2 outline structure.
  - Comparison/summary tables ready for Markdown/HTML.
  - High-value data opportunities.
  - Authoritative sources to cite (filtered against image banks, e-commerce stores, and Google domains).
  - Draft paragraphs to add.
  - A single, deduplicated, consolidated Schema.org JSON-LD structure (`Article`/`NewsArticle`/`Review`/`Product`).
- **Dynamic Search Modification / Retry with Google Data:** Change target queries on the fly or retry live Google SERP extraction if previous external calls timed out.
- **Off-Page Authority via Ahrefs API v3:** Evaluates domain rating, page URL rating, total search traffic, referring domains, and incoming backlink anchor text, returning rule-based off-page recommendations.
- **Downloadable Word Report (.docx):** Export a client-ready Word document containing the executive summary, score breakdown, failing metrics, and AI recommendations.
- **Access Code Gatekeeper:** Optional HMAC-based password protection with IP rate limiting (429 response after 10 consecutive failed attempts within 15 minutes).
- **Server Cold-Start Management:** The frontend actively checks backend health and displays an informative *"Waking up the server… this can take up to a minute"* state when Render spins up from idle.

---

## 3. How the Score Works

### Scoring Principle
The **Citation Score** (0–100) is **strictly deterministic and heuristic**. Calls to LLMs, Google SERP data, or Ahrefs **NEVER** alter the Citation Score. An audit produces identical scores regardless of external API quotas, token status, or network connectivity.

### The 11 Dimensions & Exact Weights
Weights are configured in `backend/config/scoring_weights.json`. When a `target_query` is provided, all 11 dimensions are evaluated (total weight = 1.00). When no query is provided, the first 10 dimensions are evaluated and normalized to 100%:

| Dimension | Key in JSON | Weight | What It Measures |
|:---|:---|:---:|:---|
| **Technical Infrastructure** | `technical_infrastructure` | **10%** (0.10) | HTTPS protocol, server-side rendering readiness, crawlability, AI bot access (robots.txt), and TTFB speed. |
| **Metadata Intelligence** | `metadata_schema` | **4%** (0.04) | Presence, syntax validity, and completeness of structured Schema.org data and social meta tags. |
| **AEO Structure** | `aeo_structure` | **12%** (0.12) | Direct answers within the opening 200 characters, question-based H2/H3 subheadings, and lead conciseness. |
| **Passage Quality** | `passage_quality` | **12%** (0.12) | Lexical richness, complete standalone sentence structure, content depth, and autonomous extractable blocks. |
| **Evidence Density** | `evidence_density` | **18%** (0.18) | Frequency of verified factual claims, verifiable numbers, percentages, dates, and external source citations. |
| **E-E-A-T Authority** | `eeat_authority` | **12%** (0.12) | Verified author attribution, transparent editorial credentials, first-hand experience cues, and trust pages. |
| **Entity Identification** | `entity_identification` | **6%** (0.06) | Prominence of named entities, semantic subject definition, and canonical organization references. |
| **Freshness Signals** | `freshness` | **4%** (0.04) | Visible publication dates, recent modification timestamps, and content currency. |
| **Format Citability** | `format_citability` | **6%** (0.06) | Scannable formatting (bulleted lists, comparison tables, bold text) and multimedia with descriptive alt text. |
| **Links & Verifiability** | `links_verifiability` | **6%** (0.06) | Outbound reference link ratio, citation quality, and diverse authoritative external references. |
| **Query Match** *(optional)* | `query_match` | **10%** (0.10) | Semantic similarity between the user target query, the lead paragraph, and the highest-scoring passage. |

> **Critical Bot Block Cap:** If `robots.txt` or meta robots explicitly block search/AI crawlers (`OAI-SearchBot`, `GPTBot`, etc.), the overall score is strictly capped at **30/100**.

### Content-Type Detection
The classifier inspects Schema.org entities, URL paths, and opening text in `src/utils/content_type.py`:
- `news`: Press releases or journalistic articles (detected via `NewsArticle`, path keywords like `/news/`, `/press/`, or press release datelines such as `"PARIS, Oct 5 —"`).
- `review`: Product reviews or assessments (`Review` Schema or title markers).
- `product`: E-commerce items (`Product` Schema or `/shop/` paths).
- `guide_blog`: Default fallback for general articles and long-form guides.

### Main Content & Featured Image Extraction
`src/utils/text_processing.py` isolates genuine editorial content by prioritizing `<article>`, `[role=main]`, and `<main>` tags while stripping navigation bars, headers, footers, comment threads, related post cards, and sidebars. 
`src/detectors/formatting.py` detects hero/featured images located outside the extracted article container by matching keywords (`hero`, `featured`, `post-thumbnail`, `wp-post-image`) or the OpenGraph `og:image` URL.

### Anti-Bot Challenge Detection
`src/utils/challenge_detection.py` detects Cloudflare, Incapsula, PerimeterX, and SiteGround captcha screens without throwing unhandled exceptions, alerting the user to use the **Paste Text** fallback.

### What Is NOT Measured by This Tool
- Live LLM Share of Voice (SoV) or citation tracking across proprietary chatbot indexes over time.
- Off-page backlink graphs (unless Ahrefs is manually queried).
- Internal domain-level link equity or sitewide XML sitemap architectures.

---

## 4. Architecture

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
|                   FastAPI + Python 3.11/3.14                |
|                    Headless Chromium Engine                 |
+--------------+-------------------+-------------------+------+
               |                   |                   |
               v                   v                   v
+-----------------------+ +-----------------+ +-----------------------+
|  Internal LLM Gateway | |   DataForSEO    | |     Ahrefs API v3     |
|   hub.culturabuilder  | |  SERP Live Adv  | |   Off-page metrics &  |
|  (SSE Streamed Comps) | | (PAA, Overview) | |   backlink anchors    |
+-----------------------+ +-----------------+ +-----------------------+
```

- **Frontend:** Next.js 14 static export (`output: 'export'`, `trailingSlash: true`) deployed on Vercel at project `geo-auditor-v2` with Root Directory set to `frontend`.
- **Backend:** FastAPI application running on Render, with Playwright browser dependencies for headless DOM scraping.
- **External Services:**
  - **Company LLM Gateway:** OpenAI-compatible API running via SSE streaming (`"stream": true`) through Cloudflare.
  - **DataForSEO:** Live Advanced Google SERP queries retrieving People Also Ask, organic competitors, and AI Overview citations.
  - **Ahrefs API v3:** Domain Rating, URL Rating, search volume, and referring domains.
- **Legacy Redirect:** GitHub Actions FTP deploy action that pushes a redirect `index.html` referencing `vars.NEW_FRONTEND_URL` to Hostinger on each push to `main`.
- **Keep-Alive:** Periodic pinging of `/api/health` keeps the Render instance warm.

---

## 5. Repository Structure

```
├── .agent/                       # Development rules and system directives
├── .github/workflows/deploy.yml  # Legacy Hostinger FTP redirect deployment
├── AGENTS.md                     # Engineering and Git workflow rules
├── README.md                     # Central handover and operations manual
├── backend/
│   ├── config/
│   │   ├── scoring_weights.json  # Dimensions and subdimension weight definitions
│   │   └── settings.py           # Pydantic BaseSettings loading all environment variables
│   ├── main.py                   # FastAPI app, routing, CORS, and auth middleware
│   ├── requirements.txt          # Python dependencies
│   ├── src/
│   │   ├── detectors/            # 11 isolated audit dimension detectors
│   │   ├── models/schemas.py     # Pydantic request/response models
│   │   ├── scrapers/             # Playwright headless scraper & base scraper
│   │   ├── services/             # Core audit pipeline, LLM, SERP, and Ahrefs clients
│   │   └── utils/                # Linguistic patterns, text extraction, challenges, docx generator
│   └── tests/                    # Pytest test suite (>200 tests)
└── frontend/
    ├── app/                      # Next.js 14 App Router pages and layouts
    ├── components/               # React UI components (AuditForm, AuditResults, etc.)
    ├── lib/api.ts                # Client API adapter and error interceptor
    ├── next.config.mjs           # Next.js export configuration
    └── package.json              # Node dependencies and build scripts
```

---

## 6. Environment Variables

All backend variables use the `GEO_AUDITOR_` prefix and are managed in `backend/config/settings.py`:

| Variable | Required | Default | Purpose | Location |
|:---|:---:|:---:|:---|:---|
| `GEO_AUDITOR_HOST` | No | `0.0.0.0` | Backend bind host address | Render |
| `GEO_AUDITOR_PORT` | No | `8000` | Backend bind port | Render |
| `GEO_AUDITOR_CORS_ORIGINS` | No | `["http://localhost:3000", ...]` | Allowed CORS origins JSON list | Render |
| `GEO_AUDITOR_CORS_ORIGIN_REGEX` | No | `""` | Regex for dynamic CORS origin matching (e.g. Vercel previews) | Render |
| `GEO_AUDITOR_ACCESS_CODE` | No | `""` | Access code password required in `X-Access-Code` header | Render |
| `GEO_AUDITOR_LLM_BASE_URL` | No | `""` | Base URL of OpenAI-compatible LLM gateway | Render |
| `GEO_AUDITOR_LLM_MODEL` | No | `""` | LLM model name (e.g. `gpt-4o`, `claude-3-5-sonnet`) | Render |
| `GEO_AUDITOR_LLM_API_KEY` | No | `""` | Bearer token for LLM provider authentication | Render |
| `GEO_AUDITOR_LLM_TIMEOUT_SECONDS` | No | `45.0` | Max duration for LLM completions | Render |
| `GEO_AUDITOR_LLM_DAILY_LIMIT` | No | `200` | Maximum LLM requests per UTC calendar day | Render |
| `GEO_AUDITOR_LLM_MAX_TOKENS` | No | `16000` | Max tokens requested per LLM completion | Render |
| `GEO_AUDITOR_LLM_STREAMING` | No | `True` | Enables Server-Sent Events (SSE) streaming | Render |
| `GEO_AUDITOR_DATAFORSEO_LOGIN` | No | `""` | DataForSEO API account login | Render |
| `GEO_AUDITOR_DATAFORSEO_PASSWORD` | No | `""` | DataForSEO API account password | Render |
| `GEO_AUDITOR_SERP_DAILY_LIMIT` | No | `100` | Maximum DataForSEO calls per UTC calendar day | Render |
| `GEO_AUDITOR_SERP_TIMEOUT_SECONDS`| No | `90.0` | Timeout for live SERP scraping | Render |
| `GEO_AUDITOR_AHREFS_API_KEY` | No | `""` | Ahrefs API v3 token | Render |
| `GEO_AUDITOR_AHREFS_DAILY_LIMIT` | No | `50` | Maximum Ahrefs calls per UTC calendar day | Render |
| `NEXT_PUBLIC_API_URL` | **Yes** | `http://localhost:8000` | Target backend URL used by frontend API client | Vercel |
| `NEW_FRONTEND_URL` | **Yes** | `https://geo-auditor-v2.vercel.app` | Target URL for legacy Hostinger redirect | GitHub Actions Repo Var |

---

## 7. API Endpoints

All endpoints except health and version checks enforce `X-Access-Code` authentication if `GEO_AUDITOR_ACCESS_CODE` is set.

| Method | Path | Purpose | Requires Auth |
|:---|:---|:---|:---:|
| `GET` | `/api/health` | Health and keep-alive probe | No |
| `GET` | `/api/version` | Reports app version, AI enabled, and SERP enabled status | No |
| `POST` | `/api/auth/check` | Validates provided access code | Yes |
| `GET` | `/api/scoring-weights` | Returns current weights configuration JSON | Yes |
| `POST` | `/api/audit` | Executes full on-page analysis for a URL or text | Yes |
| `POST` | `/api/ai/fixes` | Legacy/isolated quick fixes generator (cached 24h) | Yes |
| `POST` | `/api/ai/plan` | Generates unified editorial improvement plan (cached 24h) | Yes |
| `POST` | `/api/export/brief` | Generates downloadable Word document report | Yes |
| `POST` | `/api/offpage` | Retrieves Ahrefs off-page authority metrics | Yes |
| `POST` | `/api/batch` | Initiates asynchronous batch audit (max 20 URLs) | Yes |
| `GET` | `/api/batch/{job_id}` | Polls progress and results for a batch audit job | Yes |
| `GET` | `/api/batch/{job_id}/csv` | Downloads CSV summary of batch results | Yes |
| `GET` | `/api/batch/{job_id}/issues.csv`| Downloads aggregated topic issues CSV | Yes |

---

## 8. Costs and Quotas

| User Action | External APIs Triggered | Paid Credits Consumed? |
|:---|:---|:---:|
| **Single On-Page Audit** | Headless Playwright scraper | None (Local Compute) |
| **Batch Audit (up to 20 URLs)** | Headless Playwright scraper | None (Local Compute) |
| **Generate AI Plan** | DataForSEO (SERP) + Company LLM Gateway | **DataForSEO credits** (LLM is zero marginal cost) |
| **Regenerate / Change Query** | DataForSEO (SERP) + Company LLM Gateway | **DataForSEO credits** |
| **Check Off-Page Signals** | Ahrefs API v3 | **Ahrefs plan units** |
| **Export Word Report / CSV**| None | None (Local Compute) |

### Daily Limits & Caches
- **Company LLM:** 200 requests/day limit. Plans cached for 24 hours in memory by content hash.
- **DataForSEO:** 100 requests/day limit. Live SERP cached for 24 hours in memory by query and market.
- **Ahrefs:** 50 requests/day limit. Off-page signals cached for 7 days in memory by URL.
- **Important:** All caches and quota trackers reside in Python memory and reset whenever the Render service restarts or redeploys.

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
3. Extract the `"access"` string. *(Current token expiration: 28 March 2027).*
4. Update `GEO_AUDITOR_LLM_API_KEY` in the Render environment settings. **Never commit or log this token.**

### Switching the AI Model or Gateway Provider
1. Update `GEO_AUDITOR_LLM_BASE_URL` to point to the new OpenAI-compatible `/v1` endpoint.
2. Update `GEO_AUDITOR_LLM_MODEL` with the target model string (e.g., `gpt-4o`, `deepseek-chat`).
3. Update `GEO_AUDITOR_LLM_API_KEY` accordingly.

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
- Set up an external uptime monitor (e.g., UptimeRobot) pinging `https://<backend-url>/api/health` every 5 minutes.
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

- **"Waking up the server…":** Render instance is resuming from spin-down. Wait up to 60 seconds for the service to answer `/api/health`.
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
- **Render Free Tier Quotas:** Free instances provide 512 MB RAM and sleep after inactivity.
- **In-Memory Volatility:** Rate limits, batch job summaries, and response caches are lost upon service restarts.
- **Mandatory Editorial Review:** AI-generated paragraphs, schema changes, and leads must be reviewed by humans before publication, especially for regulated or financial topics.
- **Vercel Hobby Plan:** Intended for non-commercial evaluation; must upgrade to Vercel Pro if officially institutionalized across corporate teams.

---

## 14. Roadmap

- **Phase 7 Empirical Score Validation:** Batch audit sets of cited versus non-cited URLs extracted from company LLM tracking to correlate dimensional scores with real-world AI citations.
- **Daily Editorial CMS Workflow:** Streamline one-click exports directly into WordPress or Ghost CMS instances.
- **LLM Tracker Integration:** Integrate GEO-Auditor directly as an on-demand audit module within the central LLM tracking dashboard.
- **Slack Alert Integration:** Slack bot that automatically audits newly published articles and alerts editors to missing schema or weak lead paragraphs.
- **Dedicated Backend Infrastructure:** Move Render instance to a persistent, paid node with Redis-backed caching and job queues.
