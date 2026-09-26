# Vera Bot — magicpin AI Challenge Submission

**Team:** Kanav Singla  
**Model:** Custom deterministic template engine (no LLM calls)  
**Approach:** Template-based composer with context-aware rules, auto-reply detection, Hindi-English code-mix

---

## Architecture

| Component | Purpose |
|-----------|---------|
| `bot.py` | Thin wrapper exposing `compose()` per §7.1 contract |
| `composer.py` | 18 trigger-specific templates with signal/customer/peer anchors |
| `handlers.py` | Multi-turn reply handler: auto-reply, hostile, wait, question, commit |
| `server.py` | FastAPI: `healthz`, `metadata`, `context`, `tick`, `reply` |
| `store.py` | In-memory context store with versioned idempotent writes |

---

## Key Features

**Specificity (≥2 verifiable facts/message)**  
- JIDA Oct 2026 p.14, 2100-patient RCT, 38% caries reduction
- Merchant signals: `stale_posts:22d`, `ctr_below_peer_median`, `high_risk_adult_cohort`
- Customer aggregate: 78 lapsed 180d+, 38% 6mo retention, 540 unique YTD
- Peer gaps: CTR 2.1% vs 3.0% (-29%), rating 4.2★ vs 4.4★

**Category Fit**  
- Clinical peer tone for dentists ("Dr. Meera", "caries recurrence", "recall")
- No promotional language; taboos avoided ("cure", "guaranteed")

**Merchant Fit**  
- Owner name, locality, actual performance metrics, active offers, subscription status
- Conversation history checked for anti-repetition

**Trigger Relevance**  
- Explicit trigger kind + suppression_key in every message
- Urgency 1-5 modulates tone (direct → curious → gentle)

**Engagement Compulsion**  
- Binary CTA consistently (`Reply YES` / `YES reply karein`)
- Social proof (`3 dentists in Lajpat Nagar...`)
- Merchant question (`What's your most-asked treatment this week?`)
- Hindi-English code-mix for `hi`/`hi-en mix` merchants
- Handler replies reference merchant's actual question topic

**Behavioral Compliance**  
- Auto-reply: 2-turn detection → graceful exit (Pattern B)
- Intent transition: immediate action on "Ok lets do it" (avoids Pattern D failure)
- Hostile/opt-out: immediate `end`
- Wait request: 30-min backoff

---

## Deployment

```bash
pip install -r requirements.txt  # fastapi, uvicorn, pydantic
uvicorn server:app --host 0.0.0.0 --port 8080
```

Endpoints:
- `GET  /v1/healthz`
- `GET  /v1/metadata`
- `POST /v1/context` — idempotent by (scope, context_id, version)
- `POST /v1/tick` — returns `actions[]`
- `POST /v1/reply` — returns `action: send|wait|end`

---

## Tradeoffs

- **No LLM** — deterministic, <50ms latency, zero API cost. Sacrifices open-ended creativity for consistency.
- **Shallow code-mix** — word-replacement only; structural Hinglish would need LLM.
- **Static social proof counts** — randomized per category; real peer data would need graph queries.
- **Conversation history** — checked for repetition but not used to personalize follow-ups deeply.

---

## Additional Context Wishlist

1. Real peer network graph (which merchants are true locality peers)
2. Merchant's actual WhatsApp language history per turn
3. Competitor GBP data (photos, posts, offers) for true counter-campaigns
4. Customer-level lifetime value for winback prioritization