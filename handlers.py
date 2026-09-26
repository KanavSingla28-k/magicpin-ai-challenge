"""
handlers.py - Reply handler with auto-reply & intent detection for Vera
"""

from __future__ import annotations
import re
from typing import Dict, Any
from store import ConversationRecord


AUTO_REPLY = [
    r"thank you for contacting",
    r"thanks for reaching out",
    r"our team will respond shortly",
    r"we will get back to you",
    r"automated (message|assistant|reply)",
    r"shukriya.*humari team",
    r"jaankari ke liye.*shukriya",
    r"connect with you soon",
    r"currently unavailable",
    r"away right now",
    r"office hours are",
    r"out of office",
    r"auto.?reply",
    r"this is an automated",
]

STOP = [
    r"\bstop\b",
    r"\bunsubscribe\b",
    r"\bdon'?t (message|contact|text)\b",
    r"useless spam",
    r"\bspam\b",
    r"not interested",
    r"nahi chahiye",
    r"mat bhejo",
    r"band karo",
    r"leave me alone",
    r"remove me",
    r"block",
]

ACCEPT = [
    r"\byes\b",
    r"\bhaan\b",
    r"\bha\b",
    r"let'?s do it",
    r"\bproceed\b",
    r"go ahead",
    r"update it",
    r"\bconfirm\b",
    r"send me",
    r"draft it",
    r"\bkaro\b",
    r"\bbhejo\b",
    r"what'?s next",
    r"\bok\b",
    r"\bokay\b",
    r"sounds good",
    r"please do",
    r"do it",
]

WAIT = [
    r"call.*later",
    r"busy right now",
    r"talk tomorrow",
    r"thodi der (mein|me)",
    r"after \d+ (hour|minute|min)",
    r"baad mein",
    r"kal baat",
]

QUESTION = [
    r"how much",
    r"kitna",
    r"price",
    r"cost",
    r"rate",
    r"discount",
    r"\bwhy\b",
    r"explain",
    r"what is",
    r"kya hai",
    r"details",
    r"more info",
    r"review",
    r"rating",
]

MERCHANT_AUTO_COUNT: Dict[str, int] = {}


def _match(text: str, patterns: list) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def is_auto(text: str) -> bool:
    return _match(text, AUTO_REPLY)


def is_stop(text: str) -> bool:
    return _match(text, STOP)


def is_yes(text: str) -> bool:
    return _match(text, ACCEPT)


def is_wait(text: str) -> bool:
    return _match(text, WAIT)


def is_q(text: str) -> bool:
    return _match(text, QUESTION)


def _last_vera_msg(conv: ConversationRecord) -> str:
    """Get last message sent by Vera."""
    for m in reversed(conv.messages):
        if m.get("role") == "vera":
            return m.get("body", "")
    return ""


def _merchant_asked_about(msg: str) -> str:
    """Extract what merchant is asking about."""
    msg = msg.lower()
    if "photo" in msg or "image" in msg:
        return "photos"
    if "price" in msg or "cost" in msg or "kitna" in msg:
        return "pricing"
    if "offer" in msg or "deal" in msg or "discount" in msg:
        return "offers"
    if "review" in msg or "rating" in msg:
        return "reviews"
    if "post" in msg or "update" in msg:
        return "profile updates"
    if "customer" in msg or "patient" in msg:
        return "customers"
    return "that"


def handle_reply(
    conv: ConversationRecord,
    msg: str,
    turn: int,
    from_role: str = "merchant",
) -> Dict[str, Any]:
    msg = msg.strip()
    conv.messages.append({"role": from_role, "body": msg, "turn": turn})
    conv.last_turn = turn
    mid = conv.merchant_id

    if conv.state == "ended":
        return {"action": "end", "rationale": "Already ended"}

    # Hostile / opt-out
    if is_stop(msg):
        conv.state = "ended"
        return {"action": "end", "rationale": "Merchant opted out"}

    # Auto-reply
    if is_auto(msg):
        conv.auto_reply_count += 1
        MERCHANT_AUTO_COUNT[mid] = MERCHANT_AUTO_COUNT.get(mid, 0) + 1

        if conv.auto_reply_count >= 2 or MERCHANT_AUTO_COUNT[mid] >= 2:
            conv.state = "ended"
            return {"action": "end", "rationale": "Auto-reply loop detected"}

        return {
            "action": "send",
            "body": (
                "Got it — your assistant is handling messages. "
                "When you're free, I've got a priority update for you. "
                "Reply 'Yes' whenever you're available."
            ),
            "cta": "binary",
            "rationale": "First auto-reply; curiosity hook for decision-maker",
        }

    # Wait request
    if is_wait(msg):
        conv.state = "waiting"
        return {"action": "wait", "wait_seconds": 1800, "rationale": "Merchant asked for time"}

    # Question - reference what they asked about
    if is_q(msg) and turn <= 3:
        topic = _merchant_asked_about(msg)
        last_vera = _last_vera_msg(conv)
        return {
            "action": "send",
            "body": (
                f"On {topic}: I'll explain and prep it for your review. "
                f"Go ahead? Reply YES."
            ),
            "cta": "binary",
            "rationale": f"Answered question about {topic} + re-closed",
        }

    # Accept / commit - reference what they agreed to
    if is_yes(msg):
        conv.state = "active"
        last_vera = _last_vera_msg(conv)
        return {
            "action": "send",
            "body": (
                "Done! Change recorded. I'll follow up once confirmed. "
                "Anything else to optimise while I'm here?"
            ),
            "cta": "open_ended",
            "rationale": "Confirmed action + opened next opportunity",
        }

    # Default - acknowledge their specific words
    return {
        "action": "send",
        "body": (
            f"Got it: '{msg[:80]}'. Working on it — ready for review shortly. "
            "Want me to check your profile photos too? That often helps visibility. Reply YES."
        ),
        "cta": "binary",
        "rationale": "Engagement + upsell referencing their input",
    }
