"""
store.py - In-memory Context & Conversation Store
Complies with magicpin challenge-testing-brief.md
"""

from __future__ import annotations
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ConversationRecord:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    messages: list[Dict[str, Any]] = field(default_factory=list)
    state: str = "active"  # "active", "waiting", "ended"
    auto_reply_count: int = 0
    last_turn: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ContextStore:
    def __init__(self):
        # Maps context_id -> {"version": int, "payload": dict, "delivered_at": str}
        self.categories: Dict[str, Dict[str, Any]] = {}
        self.merchants: Dict[str, Dict[str, Any]] = {}
        self.customers: Dict[str, Dict[str, Any]] = {}
        self.triggers: Dict[str, Dict[str, Any]] = {}
        
        # Track active conversations
        self.conversations: Dict[str, ConversationRecord] = {}
        self.sent_suppression_keys: set[str] = set()
        self.start_time = time.time()

    def get_counts(self) -> Dict[str, int]:
        return {
            "category": len(self.categories),
            "merchant": len(self.merchants),
            "customer": len(self.customers),
            "trigger": len(self.triggers),
        }

    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def put_context(self, scope: str, context_id: str, version: int, payload: Dict[str, Any], delivered_at: str) -> Tuple[bool, str, Optional[int]]:
        """
        Idempotent by (context_id, version).
        Higher version replaces prior version atomically.
        Lower version returns 409 conflict.
        Returns: (accepted: bool, reason/ack_id: str, current_version: Optional[int])
        """
        store_map = {
            "category": self.categories,
            "merchant": self.merchants,
            "customer": self.customers,
            "trigger": self.triggers,
        }.get(scope)

        if store_map is None:
            return False, f"invalid_scope: {scope}", None

        existing = store_map.get(context_id)
        if existing:
            curr_version = existing["version"]
            if version == curr_version:
                # Idempotent re-post
                return True, f"ack_{context_id}_v{version}_noop", curr_version
            elif version < curr_version:
                # Stale version
                return False, "stale_version", curr_version

        # Store or replace atomically
        store_map[context_id] = {
            "version": version,
            "payload": payload,
            "delivered_at": delivered_at,
        }
        return True, f"ack_{context_id}_v{version}", version

    def get_context(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        store_map = {
            "category": self.categories,
            "merchant": self.merchants,
            "customer": self.customers,
            "trigger": self.triggers,
        }.get(scope)
        if store_map and context_id in store_map:
            return store_map[context_id]["payload"]
        return None

    def get_or_create_conversation(self, conversation_id: str, merchant_id: str, customer_id: Optional[str] = None) -> ConversationRecord:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = ConversationRecord(
                conversation_id=conversation_id,
                merchant_id=merchant_id,
                customer_id=customer_id
            )
        return self.conversations[conversation_id]

    def claim_suppression(self, suppression_key: str) -> bool:
        """Claim a suppression key for one proactive send."""
        if not suppression_key or suppression_key in self.sent_suppression_keys:
            return False
        self.sent_suppression_keys.add(suppression_key)
        return True


# Global singleton instance
store = ContextStore()
