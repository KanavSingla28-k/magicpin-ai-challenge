"""
server.py - FastAPI server for Vera (magicpin challenge)
Endpoints: healthz, metadata, context, tick, reply
"""

from __future__ import annotations
import uuid
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from store import store
from composer import compose
from handlers import handle_reply

DATA_DIR = Path(__file__).parent / "dataset"
CUST_CACHE: Dict[str, Any] = {}
MERCH_CACHE: Dict[str, Any] = {}


def _load_cache():
    global CUST_CACHE, MERCH_CACHE
    try:
        cpath = DATA_DIR / "customers_seed.json"
        if cpath.exists():
            data = json.loads(cpath.read_text(encoding="utf-8"))
            for c in data.get("customers", []):
                CUST_CACHE[c["customer_id"]] = c
        mpath = DATA_DIR / "merchants_seed.json"
        if mpath.exists():
            data = json.loads(mpath.read_text(encoding="utf-8"))
            for m in data.get("merchants", []):
                MERCH_CACHE[m["merchant_id"]] = m
    except Exception:
        pass


_load_cache()

app = FastAPI(title="Vera Bot", version="1.0.0")


class CtxReq(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str


class TickReq(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = Field(default_factory=list)


class ReplyReq(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 1

@app.get("/")
def root():
    return {
        "service": "Vera Bot",
        "status": "ok",
        "health": "/v1/healthz",
        "docs": "/docs"
    }

@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": store.uptime_seconds(),
        "contexts_loaded": store.get_counts()
    }


@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Kanav Singla",
        "team_members": ["Kanav Singla"],
        "model": "custom-template-engine",
        "approach": "template-based composer with context-aware rules, auto-reply detection, and Hindi-English code-mix for Indian merchants",
        "contact_email": "kanav.singla@magicpin.in",
        "version": "1.0.0",
        "submitted_at": "2026-09-27T03:40:00Z"
    }


@app.post("/v1/context")
def push_context(req: CtxReq):
    accepted, reason, curr_ver = store.put_context(
        scope=req.scope,
        context_id=req.context_id,
        version=req.version,
        payload=req.payload,
        delivered_at=req.delivered_at
    )

    if not accepted:
        if reason == "stale_version":
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"accepted": False, "reason": "stale_version", "current_version": curr_ver}
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"accepted": False, "reason": reason}
            )

    return {
        "accepted": True,
        "ack_id": reason,
        "stored_at": req.delivered_at
    }


@app.post("/v1/tick")
def tick(req: TickReq):
    actions = []

    for trg_id in req.available_triggers:
        trigger = store.get_context("trigger", trg_id)
        if not trigger:
            continue

        mid = trigger.get("merchant_id")
        cid = trigger.get("customer_id")

        merchant = store.get_context("merchant", mid) if mid else None
        if not merchant and mid and mid in MERCH_CACHE:
            merchant = MERCH_CACHE[mid]

        customer = store.get_context("customer", cid) if cid else None
        if not customer and cid and cid in CUST_CACHE:
            customer = CUST_CACHE[cid]

        cat_slug = (merchant.get("category_slug") if merchant else None) or trigger.get("payload", {}).get("category")
        category = store.get_context("category", cat_slug) if cat_slug else None

        if not merchant or not category:
            continue

        if trigger.get("scope") == "customer":
            if not customer or customer.get("merchant_id") != mid:
                continue
            consent_scopes = set(customer.get("consent", {}).get("scope", []))
            kind = trigger.get("kind", "")
            required_scope = (
                "recall_reminders" if "recall" in kind
                else "appointment_reminders" if "appointment" in kind
                else "promotional_outreach"
            )
            if required_scope not in consent_scopes:
                continue

        # Compose message
        composed = compose(category=category, merchant=merchant, trigger=trigger, customer=customer)

        if not store.claim_suppression(composed["suppression_key"]):
            continue

        conv_id = f"conv_{trg_id}_{uuid.uuid4().hex[:6]}"
        conv = store.get_or_create_conversation(conv_id, mid, cid)
        conv.messages.append({"role": "vera", "body": composed["body"], "turn": 1})

        action_dict = {
            "conversation_id": conv_id,
            "merchant_id": mid,
            "customer_id": cid,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trg_id,
            "template_name": (
                f"merchant_{trigger.get('kind', 'generic')}_v1"
                if trigger.get("scope") == "customer"
                else f"vera_{trigger.get('kind', 'generic')}_v1"
            ),
            "template_params": [
                (customer or {}).get("identity", {}).get("name")
                or merchant.get("identity", {}).get("name", ""),
                composed["body"],
            ],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        }
        actions.append(action_dict)

    return {"actions": actions}


@app.post("/v1/reply")
def reply(req: ReplyReq):
    conv = store.get_or_create_conversation(req.conversation_id, req.merchant_id, req.customer_id)
    resp = handle_reply(conv, req.message, req.turn_number, req.from_role)
    return resp


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
