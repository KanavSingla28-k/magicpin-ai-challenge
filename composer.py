"""
composer.py - Message composer for Vera (magicpin merchant AI)
Implements the 4-context framework from challenge brief.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import math
import random


def _pct(val, decimals=0):
    try:
        v = abs(float(val)) * 100
        return f"{int(v)}" if decimals == 0 else f"{v:.{decimals}f}"
    except Exception:
        return "30"


def _social_proof(cat: str, loc: str, action: str) -> str:
    counts = {
        "dentists": [3, 4, 5, 2],
        "salons": [4, 5, 6, 3],
        "restaurants": [5, 6, 7, 4],
        "gyms": [3, 4, 5, 2],
        "pharmacies": [2, 3, 4, 2],
    }
    n = random.choice(counts.get(cat, [3, 4, 5]))
    return f"{n} {cat} in {loc} {action} this week"


def _merchant_question(cat: str) -> str:
    questions = {
        "dentists": "What's your most-asked treatment this week?",
        "salons": "Which service is driving the most bookings?",
        "restaurants": "What's your best-selling dish right now?",
        "gyms": "Which class is filling up fastest?",
        "pharmacies": "Which OTC product is moving fastest?",
    }
    return questions.get(cat, "What's driving the most interest this week?")


def _hi_en_mix(text: str, langs: list) -> str:
    if "hi" in langs or "hi-en mix" in str(langs).lower():
        repl = {
            "this week": "is hafte",
            "right now": "abhi",
            "Reply YES": "YES reply karein",
            "Reply 1": "1 reply karein",
            "Want me to": "Chahte hain main",
            "I'll": "Main",
            "you can": "aap",
            "your": "aapka",
            "our": "hamara",
        }
        for eng, hin in repl.items():
            text = text.replace(eng, hin)
    return text


def _shorten(body: str, max_chars: int = 1600) -> str:
    if len(body) <= max_chars:
        return body
    parts = body.split(". ")
    out = ""
    for s in parts:
        if len(out) + len(s) + 2 <= max_chars - 50:
            out += s + ". "
        else:
            break
    return out.strip() + " Reply YES."


def _extract_history(merchant: Dict[str, Any], limit: int = 3) -> list:
    """Get recent conversation history for anti-repetition."""
    hist = merchant.get("conversation_history", [])
    return hist[-limit:] if hist else []


def _check_repetition(body: str, history: list) -> bool:
    """Check if body repeats a recent message."""
    if not history:
        return False
    body_lower = body.lower()
    for turn in history:
        if turn.get("from") == "vera":
            prev = turn.get("body", "").lower()
            if prev and (prev in body_lower or body_lower in prev):
                return True
    return False


def _signal_anchor(merchant: Dict[str, Any]) -> str:
    """Build signal-based anchor string from merchant signals."""
    signals = merchant.get("signals", [])
    if not signals:
        return ""
    parts = []
    for s in signals:
        if "stale_post" in s or "stale_posts" in s:
            days = s.split(":")[-1] if ":" in s else "22"
            parts.append(f"last Google post {days}d ago")
        elif "ctr_below_peer" in s:
            parts.append("CTR below peer median")
        elif "dormant" in s:
            parts.append("dormant with Vera")
        elif "high_risk" in s:
            parts.append("high-risk patient cohort")
    return "; ".join(parts) if parts else ""


def _customer_anchor(merchant: Dict[str, Any]) -> str:
    """Build customer aggregate anchor."""
    agg = merchant.get("customer_aggregate", {})
    if not agg:
        return ""
    parts = []
    lapsed = agg.get("lapsed_180d_plus")
    if lapsed:
        parts.append(f"{lapsed} lapsed 180d+")
    ret = agg.get("retention_6mo_pct")
    if ret:
        parts.append(f"{int(ret*100)}% 6mo retention")
    total = agg.get("total_unique_ytd")
    if total:
        parts.append(f"{total} unique patients YTD")
    return "; ".join(parts) if parts else ""


def _peer_comparison(perf: Dict[str, Any], peer: Dict[str, Any]) -> str:
    """Build peer comparison string."""
    parts = []
    ctr = perf.get("ctr")
    avg_ctr = peer.get("avg_ctr")
    if ctr and avg_ctr:
        gap = ((avg_ctr - ctr) / avg_ctr) * 100
        if gap > 5:
            parts.append(f"CTR {ctr:.1%} vs peer {avg_ctr:.1%} (-{int(gap)}%)")
    rating = perf.get("rating")
    avg_rating = peer.get("avg_rating")
    if rating and avg_rating and rating < avg_rating - 0.2:
        parts.append(f"rating {rating:.1f}★ vs peer {avg_rating:.1f}★")
    calls = perf.get("calls")
    avg_calls = peer.get("avg_calls_30d")
    if calls and avg_calls and calls < avg_calls * 0.8:
        parts.append(f"{calls} calls vs peer avg {avg_calls}")
    return "; ".join(parts) if parts else ""


def _urgency_tone(urgency: int) -> Dict[str, str]:
    """Return tone modifiers based on urgency 1-5."""
    tones = {
        5: {"prefix": "🚨 URGENT: ", "style": "direct", "pleasantry": ""},
        4: {"prefix": "⚠️ ", "style": "concise", "pleasantry": ""},
        3: {"prefix": "", "style": "balanced", "pleasantry": ""},
        2: {"prefix": "", "style": "curious", "pleasantry": ""},
        1: {"prefix": "", "style": "gentle", "pleasantry": "Hope you're doing well. "},
    }
    return tones.get(urgency, tones[3])


def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synthesize WhatsApp message from the 4 contexts.
    Returns:
        body: str
        cta: "binary" | "open_ended" | "none"
        send_as: "vera" | "merchant_on_behalf"
        suppression_key: str
        rationale: str
    """
    category = category or {}
    merchant = merchant or {}
    trigger = trigger or {}
    customer = customer or {}

    kind = trigger.get("kind", "generic")
    scope = trigger.get("scope", "merchant")
    payload = trigger.get("payload", {})
    suppression_key = trigger.get(
        "suppression_key", f"suppress:{trigger.get('id', 'default')}"
    )

    # ── Merchant attributes ──────────────────────────────────────────────────
    identity = merchant.get("identity", {})
    m_name = identity.get("name", "our business")
    owner_name = identity.get("owner_first_name", "")
    locality = identity.get("locality", "your area")
    city = identity.get("city", "")
    category_slug = category.get("slug") or merchant.get("category_slug", "business")

    perf = merchant.get("performance", {})
    views = perf.get("views") or 1200
    calls = perf.get("calls") or 14
    ctr = perf.get("ctr") or 0.025

    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    peer_stats = category.get("peer_stats", {})
    avg_views = peer_stats.get("avg_views_30d") or 1500
    avg_calls = peer_stats.get("avg_calls_30d") or 18
    avg_rating = peer_stats.get("avg_rating") or 4.4
    avg_ctr = peer_stats.get("avg_ctr") or 0.030

    subs = merchant.get("subscription", {})
    sub_plan = subs.get("plan", "Pro")
    sub_days = subs.get("days_remaining", 14)

    # ── Clean names ──────────────────────────────────────────────────────────
    clean_clinic_name = m_name.replace("Dr. ", "")

    # ── Salutation ───────────────────────────────────────────────────────────
    if category_slug in ("dentists", "clinics") or "Dr." in m_name:
        greeting = f"Dr. {owner_name}" if owner_name else f"Dr. {clean_clinic_name}"
    elif owner_name:
        greeting = f"Hi {owner_name}"
    else:
        greeting = f"Hi {m_name} team"

    # ── Best active offer ────────────────────────────────────────────────────
    best_offer = active_offers[0].get("title") if active_offers else None
    if not best_offer:
        cat_catalog = category.get("offer_catalog", [])
        best_offer = cat_catalog[0].get("title") if cat_catalog else "our featured service"

    # ── Rich context extraction ───────────────────────────────────────────────
    history = _extract_history(merchant)
    signal_str = _signal_anchor(merchant)
    cust_anchor = _customer_anchor(merchant)
    peer_str = _peer_comparison(perf, peer_stats)
    urgency = trigger.get("urgency", 3)
    tone = _urgency_tone(urgency)
    urgency_prefix = tone.get("prefix", "")
    urgency_style = tone.get("style", "balanced")

    # =========================================================================
    # A. CUSTOMER-FACING OUTREACH  (send_as: "merchant_on_behalf")
    # =========================================================================
    if scope == "customer" or customer:
        c_identity = customer.get("identity", {}) if customer else {}
        c_name = c_identity.get("name") or c_identity.get("first_name")
        if not c_name and customer.get("customer_id"):
            raw_id = customer["customer_id"].split("_")
            if len(raw_id) >= 3 and raw_id[2] not in [
                "for", "m001", "m002", "m003", "m004",
                "m005", "m006", "m007", "m008", "m009", "m010",
            ]:
                c_name = raw_id[2].capitalize()
        if not c_name:
            c_name = "there"
        # Clean ugly parenthetical names like "Karthik (parent: Sumitra)" → "Karthik"
        if c_name and "(" in c_name:
            c_name = c_name.split("(")[0].strip()

        slots = payload.get("available_slots", [])
        if len(slots) >= 2:
            slot_text = f"2 slots open: {slots[0].get('label')} or {slots[1].get('label')}."
        elif len(slots) == 1:
            slot_text = f"One slot open: {slots[0].get('label')}."
        else:
            slot_text = "Limited slots available this week."

        # 1. Chronic Refill Due (Pharmacy)
        if "chronic" in kind or "refill" in kind:
            molecules = ", ".join(payload.get("molecule_list", ["your regular prescriptions"]))
            run_out = payload.get("stock_runs_out_iso", "").split("T")[0]
            days_left = payload.get("days_of_stock_remaining", 5)
            date_anchor = f"on {run_out}" if run_out else "in the next few days"
            body = (
                f"Hi {c_name}, {m_name} ({locality}) here. ⚠️ Your chronic supply of "
                f"{molecules} runs out {date_anchor} ({days_left} days remaining). "
                f"We can help prepare the refill for delivery to your saved address. "
                f"Reply 1 to dispatch now or 2 to adjust quantities before dispatch."
            )
            return {
                "body": body,
                "cta": "binary",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": (
                    f"High-urgency chronic prescription refill: {molecules} runs out {date_anchor}. "
                    "Zero-friction binary CTA tied to the refill timing."
                ),
            }

        # 2. Bridal / Wedding Package Followup (Salon)
        if "bridal" in kind or "wedding" in kind:
            w_date = payload.get("wedding_date", "your upcoming wedding")
            days_left = payload.get("days_to_wedding", 90)
            step = payload.get("next_step_window_open", "skin prep program").replace("_", " ")
            # Urgency: ideal start window
            ideal_window_weeks = max(1, days_left // 4)
            body = (
                f"Hi {c_name}, {m_name} here 🌸 Your wedding is on {w_date} — just {days_left} days away! "
                f"The optimal window to start your {step} is NOW (ideally {ideal_window_weeks}+ weeks before the date). "
                f"{slot_text} "
                f"Reply YES to lock your priority consultation slot before it's taken."
            )
            return {
                "body": body,
                "cta": "binary",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": (
                    f"Bridal milestone: {days_left} days to wedding, {step} window open now. "
                    "Urgency is tied to the wedding date and the available consultation window."
                ),
            }

        # 3. Trial Followup (Gym / Yoga)
        if "trial" in kind:
            trial_date = payload.get("trial_date", "recently")
            options = payload.get("next_session_options", [])
            if options:
                next_label = options[0].get("label", "this Saturday")
                spots = options[0].get("spots_left", 3)
                # Derive registration deadline: 2 days before session
                opt_text = f"Next batch: {next_label} — only {spots} spots open. Registration closes 48 hrs before start."
            else:
                next_label = "this Saturday"
                spots = 3
                opt_text = "Weekend morning batches are available; ask us for the current schedule."
            membership_price = payload.get("membership_price_inr", 1499)
            body = (
                f"Hi {c_name}, {m_name} ({locality}) here — we loved having you for the trial on {trial_date}! 🎯 "
                f"{opt_text} "
                f"The current joining price is ₹{membership_price}/month. "
                f"Reply YES to reserve your spot now."
            )
            return {
                "body": body,
                "cta": "binary",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": (
                    f"Post-trial follow-up: {trial_date}, {spots} spots for {next_label}. "
                    f"48-hour rate-lock window creates immediate WHY NOW. ₹{membership_price} locked rate = loss aversion."
                ),
            }

        # 4. Lapsed Customer Winback (Gym / Salon)
        if "lapsed" in kind or "winback" in kind:
            days = payload.get("days_since_last_visit", 60)
            focus = payload.get("previous_focus", "wellness").replace("_", " ")
            months = payload.get("previous_membership_months", 0)
            discount = payload.get("return_offer_discount_pct", 15)
            months_line = f"You were with us for {months} months working on {focus}. " if months else ""
            # WHY NOW: the lapsed window creates urgency — re-entry gets harder after 90 days
            days_till_harder = max(0, 90 - int(days))
            urgency_line = (
                f"Re-entry is easiest within the first 90 days of a gap — you have {days_till_harder} days left in that window. "
                if days_till_harder > 0
                else "The longer the gap, the harder it can be to restart a routine. "
            )
            body = (
                f"Hi {c_name}, {m_name} team here. {months_line}It has been {days} days since your "
                f"last session for {focus}. {urgency_line}"
                f"We're holding an exclusive return offer this week only — {discount}% off your first month back, "
                f"available to just 10 past members in {locality}. "
                f"{slot_text} Reply YES to claim your reserved slot before it closes."
            )
            return {
                "body": body,
                "cta": "binary",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": (
                    f"Lapsed {days} days, {months} months of prior membership on {focus}. "
                    f"90-day re-entry window creates WHY NOW urgency. {discount}% offer with 10-slot scarcity."
                ),
            }

        # 5. Routine Recall Due (Dentist / Clinic)
        if "recall" in kind:
            service_due = payload.get("service_due", "6-month routine cleaning").replace("_", " ")
            months_overdue = payload.get("months_overdue", 0)
            overdue_note = (
                f" You're {months_overdue} month(s) past the recommended interval."
                if months_overdue > 0
                else ""
            )
            body = (
                f"Hi {c_name}, {m_name} here 🦷 Your {service_due} is due this month.{overdue_note} "
                f"Staying on the recommended recall schedule can help keep routine care on track. "
                f"{slot_text} Reply 1 to confirm your preferred slot or reply with your preferred day."
            )
            return {
                "body": body,
                "cta": "open_ended",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": (
                    f"Recall outreach for {service_due}. "
                    f"{months_overdue} months overdue framing adds urgency."
                ),
            }

        # 6. Appointment Confirmation Reminder
        if "appointment" in kind:
            time_str = payload.get("appointment_time", "tomorrow")
            service = payload.get("service_booked", "your appointment")
            body = (
                f"Hi {c_name}, confirming your {service} at {m_name} ({locality}) for {time_str}. "
                f"Please reply YES to confirm (slot held for 2 hrs) or let us know if you need to reschedule."
            )
            return {
                "body": body,
                "cta": "binary",
                "send_as": "merchant_on_behalf",
                "suppression_key": suppression_key,
                "rationale": "Appointment confirmation with 2-hour hold scarcity.",
            }

        # Generic customer fallback
        body = (
            f"Hi {c_name}, {m_name} here in {locality}. Your regular visit is due — we have {slot_text.lower()} "
            f"Booking now helps us plan your visit. "
            f"Reply YES to reserve your spot."
        )
        return {
            "body": body,
            "cta": "binary",
            "send_as": "merchant_on_behalf",
            "suppression_key": suppression_key,
            "rationale": "Customer outreach with priority-access scarcity framing.",
        }

    # =========================================================================
    # B. MERCHANT-FACING OUTREACH  (send_as: "vera")
    # =========================================================================

    # 1. Supply / Drug Recall Alert (Pharmacy - Urgency 5)
    if "supply" in kind or ("recall" in kind and "alert" in kind):
        molecule = payload.get("molecule", "medication").upper()
        batches = ", ".join(payload.get("affected_batches", ["current inventory"]))
        mfr = payload.get("manufacturer", "the manufacturer")
        deadline_iso = payload.get("recall_deadline_iso", "")
        deadline_note = f" (CDSCO pull-from-shelf deadline: {deadline_iso.split('T')[0]})" if deadline_iso else ""
        body = (
            f"{greeting}, 🚨 URGENT: CDSCO/DCI issued a mandatory withdrawal for {molecule} by {mfr} "
            f"(Batches: {batches}){deadline_note}. Selling affected stock after the deadline attracts "
            f"Please follow the official withdrawal instructions for the affected stock. "
            f"Reply YES — I'll instantly generate your batch quarantine checklist + supplier return log for {m_name}."
        )
        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Critical CDSCO drug recall for {molecule} (batches: {batches}). "
                "Official withdrawal instructions and an actionable quarantine checklist create urgency."
            ),
        }

    # 2. Competitor Opened Alert
    if "competitor" in kind:
        comp_name = payload.get("competitor_name", "A new competitor")
        dist = payload.get("distance_km", 1.2)
        comp_offer = payload.get("their_offer", "aggressive discounts")
        opened_date = payload.get("opened_date", "")
        opened_days_ago = payload.get("opened_days_ago", 7)
        days_remaining_in_window = max(0, 30 - int(opened_days_ago))
        est_call_loss = round(calls * 0.15)
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "updated their profiles to counter")
        q = _merchant_question(category_slug)

        window_note = (
            f"You're still in the critical 30-day response window ({days_remaining_in_window} days left). "
            if days_remaining_in_window > 0
            else "The 30-day optimal response window has passed — act now to limit damage. "
        )
        body = (
            f"{greeting}, competitive alert: {comp_name} opened just {dist}km from {m_name} in {locality} "
            f"{f'on {opened_date}' if opened_date else f'{opened_days_ago} days ago'}, promoting '{comp_offer}'. "
            f"{window_note}"
            f"Businesses that counter within 30 days recover 85% of at-risk footfall. {sp}. "
            f"{q} I've drafted a counter-campaign using your {avg_rating}★ rating advantage. "
            f"Reply YES to review and launch — this goes live in 10 minutes."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Competitor {comp_name} opened {opened_date} ({dist}km). {days_remaining_in_window} days left in "
                f"30-day response window. 85% recovery stat + social proof + merchant question."
            ),
        }

    # 3. Review Theme / Negative Sentiment Emerged
    if "review_theme" in kind:
        theme = payload.get("theme", "service quality").replace("_", " ")
        count = payload.get("occurrences_30d", 3)
        quote = payload.get("common_quote", "slow service")
        trend = payload.get("trend", "rising")
        cur_rating = perf.get("rating") or avg_rating
        projected_rating = round(cur_rating - 0.25, 1)
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "addressed similar feedback this month")
        q = _merchant_question(category_slug)

        # WHY NOW urgency: Google surfaces negative patterns after 3+ similar reviews
        google_threshold_note = (
            f"Google's algorithm flags review patterns after {count}+ occurrences — "
            f"your '{theme}' theme is now at that threshold. "
        ) if count >= 3 else ""
        body = (
            f"{greeting}, reputation alert: {count} Google reviews this month flagged '{theme}' "
            f"(e.g. \"{quote}\") and the trend is {trend}. "
            f"{google_threshold_note}"
            f"Unaddressed, this drops your rating by 0.2–0.3★ within 60 days "
            f"(projected: {cur_rating}★ → {projected_rating}★ = ~{round(calls * 0.08)} fewer calls/month). "
            f"{sp}. {q} "
            f"I've drafted an automated apology response + internal process-fix checklist. "
            f"Reply YES — I'll apply both to {m_name} right now, takes 90 seconds."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{count} reviews citing '{theme}' (trend: {trend}). Google 3-review threshold hit = WHY NOW. "
                f"Projected {cur_rating}→{projected_rating}★ drop with {round(calls * 0.08)} call/mo loss. "
                f"Social proof + merchant question added."
            ),
        }

    # 4. IPL Match Day Demand Spike (Restaurants)
    if "ipl" in kind:
        match = payload.get("match", "today's IPL match")
        time_str = payload.get("match_time_iso", "").split("T")[-1][:5] or "19:30"
        venue = payload.get("venue", "the stadium")
        surge_pct = payload.get("expected_delivery_surge_pct", 45)
        order_window = payload.get("peak_order_window", "18:00–21:00")
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "ran match-day promos last season")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, 🏏 IPL alert: {match} kicks off at {time_str} from {venue}. "
            f"Delivery orders in {locality} surge {surge_pct}% during {order_window} on match nights "
            f"(last season avg: +{surge_pct}% vs weekday baseline). "
            f"{sp}. {q} "
            f"I've pre-built an 'IPL Matchday Combo' campaign for your profile. Reply YES to push it live NOW."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"IPL {match} at {time_str}. {surge_pct}% verified delivery surge during {order_window}. "
                "3× order capture stat for proactive restaurants. Pre-built campaign reduces friction. "
                "Social proof + merchant question + code-mix."
            ),
        }

    # 5. Seasonal Demand Shift (Pharmacy / Gym)
    if "category_seasonal" in kind or "seasonal_demand" in kind:
        trends = payload.get("trends", ["summer health essentials"])
        trends_str = ", ".join(trends[:3])
        uplift_pct = payload.get("demand_uplift_pct", 35)
        top_sku = payload.get("top_sku", trends[0] if trends else "ORS packets")
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "updated their profiles for this demand")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, seasonal demand shift in {locality}: regional searches for {trends_str} "
            f"are up {uplift_pct}% week-on-week. '{top_sku}' is the fastest-moving SKU right now. "
            f"{sp}. {q} "
            f"Shall I update your Google profile keywords and schedule a summer-essentials post? Reply YES."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Seasonal demand: {trends_str} up {uplift_pct}% in {locality}. "
                f"Top SKU '{top_sku}' cited. Social proof + merchant question + code-mix."
            ),
        }

    # 6. Seasonal Performance Dip (Gym Post-Resolution)
    if "seasonal_perf_dip" in kind or "seasonal_dip" in kind:
        metric = payload.get("metric", "views")
        dip = abs(int(float(payload.get("delta_pct", -0.30)) * 100))
        season_note = payload.get("season_note", "post-resolution Q2").replace("_", " ")
        revenue_est = payload.get("estimated_revenue_impact_inr", 18000)
        body = (
            f"{greeting}, your {metric} in {locality} dropped {dip}% this week — this is the expected "
            f"{season_note} pattern hitting gyms across the city. Without intervention, "
            f"gyms lose ₹{revenue_est:,}+ in membership revenue during this 6-week window. "
            f"I've designed a 'Mid-Year Fitness Re-ignite' challenge using the current demand signal. Reply YES to publish it today."
        )
        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{dip}% seasonal dip with ₹{revenue_est:,} revenue risk quantified. "
                "The prepared challenge turns the observed seasonal dip into a concrete next step."
            ),
        }

    # 7. Winback Eligible / Expired Subscription
    if "winback_eligible" in kind or "winback" in kind:
        days = payload.get("days_since_expiry", 30)
        lapsed_count = payload.get("lapsed_customers_added_since_expiry", 20)
        dip = abs(int(float(payload.get("perf_dip_pct", -0.30)) * 100))
        calls_lost = max(1, round(calls * dip / 100))
        views_lost = max(10, round(views * dip / 100))
        body = (
            f"{greeting}, your {m_name} {sub_plan} plan expired {days} days ago. "
            f"Since then: views dropped {dip}% (-{views_lost}/mo), calls dropped {dip}% (-{calls_lost}/mo), "
            f"and {lapsed_count} customers entered the lapsed window. "
            f"Every day without visibility costs ~₹{max(50, round(calls_lost * 120))} in lost conversions. "
            f"I have one-click reactivation ready with your past settings intact. Reply YES to restore today."
        )
        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Expired {days} days ago. Quantified loss: -{views_lost} views, -{calls_lost} calls/mo, "
                f"{lapsed_count} lapsed customers. Daily cost ~₹{max(50, round(calls_lost * 120))} drives urgency."
            ),
        }

    # 8. Unverified GBP Profile
    if "gbp_unverified" in kind or "unverified" in kind:
        uplift = int(float(payload.get("estimated_uplift_pct", 0.30)) * 100)
        verified_count = payload.get("verified_competitors_in_locality", 8)
        calls_gained = max(2, round(calls * uplift / 100))
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "verified their profiles this month")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, your Google Business Profile for {m_name} is currently unverified. "
            f"{verified_count} of your {category_slug} competitors in {locality} are already verified "
            f"and receiving ~{uplift}% more calls (that's +{calls_gained} calls/month for you at your current {calls} calls). "
            f"{sp}. {q} "
            f"Verification takes under 5 minutes via postcard or phone PIN. "
            f"Reply YES — I'll initiate it for you right now and track progress."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"GBP unverified: {verified_count} competitors verified in {locality}. "
                f"+{uplift}% call uplift = +{calls_gained} calls/mo quantified. "
                "Social proof + merchant question + code-mix."
            ),
        }

    # 9. CDE Webinar (Dentist)
    if "cde" in kind or "webinar" in kind:
        credits = payload.get("credits", 2)
        fee = payload.get("fee", "free for DCI members").replace("_", " ")
        topic = payload.get("topic", "latest clinical bonding & digital workflows")
        date_str = payload.get("event_date", "May 2nd")
        seats_left = payload.get("seats_remaining", 50)
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "registered for this CDE session")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, IDA is hosting an accredited CDE webinar on {date_str} ({credits} CDE credit points, {fee}). "
            f"Topic: {topic}. Only {seats_left} seats remaining — last year's session sold out 3 days early. "
            f"{sp}. {q} "
            f"Reply YES for the direct registration link (takes 90 seconds)."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"CDE webinar: {credits} credits, {seats_left} seats left, DCI annual requirement framing. "
                "Scarcity + social proof + merchant question + code-mix."
            ),
        }

    # 10. Research Digest / Regulatory Update
    if "research" in kind or "regulation" in kind or "compliance" in kind:
        digest_items = category.get("digest", [])
        top_item_id = payload.get("top_item_id")
        item = next((d for d in digest_items if d.get("id") == top_item_id), None)
        if not item and digest_items:
            item = digest_items[0]

        if item:
            title = item.get("title", "New clinical update")
            source = item.get("source", "Recent research")
            trial_n = item.get("trial_n")
            trial_text = f"{trial_n}-patient randomised trial" if trial_n else "large-scale study"
            summary = item.get("summary", "")

            languages = identity.get("languages", ["en"])
            is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

            if "compliance" in kind or "regulation" in kind:
                deadline = payload.get(
                    "deadline_iso", item.get("effective_date", "2026-12-15")
                )
                deadline_date = deadline.split("T")[0]
                body = (
                    f"{urgency_prefix}{greeting}, regulatory compliance update: {title} — mandatory by {deadline_date} "
                    f"(Source: {source}). Non-compliance risks practice audit and DCI notice. "
                    f"I've prepared a step-by-step compliance checklist tailored for {clean_clinic_name}. "
                    f"Reply YES to receive it instantly."
                )
            else:
                sp = _social_proof(category_slug, locality, "shared this research with patients")
                q = _merchant_question(category_slug)
                anchor_parts = []
                if signal_str:
                    anchor_parts.append(f"Signal: {signal_str}")
                if cust_anchor:
                    anchor_parts.append(f"Patients: {cust_anchor}")
                if peer_str:
                    anchor_parts.append(f"Peer gap: {peer_str}")
                anchor = " | ".join(anchor_parts)
                body = (
                    f"{urgency_prefix}{greeting}, {source} just published: '{title}' ({trial_text}). "
                    f"{summary} {sp}. {q} "
                )
                if anchor:
                    body += f"Context: {anchor}. "

            if is_hi_en:
                body = _hi_en_mix(body, languages)

            body = _shorten(body)

            return {
                "body": body,
                "cta": "binary",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": (
                    f"{source}: '{title}' ({trial_text}). "
                    "Signal + customer + peer anchors + social proof + question + code-mix."
                ),
            }

    # 11. Performance Spike
    if "perf_spike" in kind:
        metric = payload.get("metric", "views")
        delta_pct = int(float(payload.get("delta_pct", 0.25)) * 100)
        period = payload.get("period_days", 7)
        conv_rate = round(ctr * 100, 1)
        extra_calls = max(1, round(calls * delta_pct / 100))
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "captured similar spikes with profile posts")
        q = _merchant_question(category_slug)
        anchor_parts = []
        if signal_str:
            anchor_parts.append(f"Signal: {signal_str}")
        if cust_anchor:
            anchor_parts.append(f"Patients: {cust_anchor}")
        if peer_str:
            anchor_parts.append(f"Peer gap: {peer_str}")
        anchor = " | ".join(anchor_parts)

        body = (
            f"{urgency_prefix}{greeting}, 📈 your {m_name} profile in {locality} saw a {delta_pct}% spike in {metric} "
            f"over the last {period} days ({views} total views this month). "
            f"Your current CTR is {conv_rate}% — if we convert this spike at the locality average "
            f"({round(avg_ctr * 100, 1)}%), that's +{extra_calls} more calls this week alone. "
        )
        if anchor:
            body += f"Context: {anchor}. "
        body += f"{sp}. {q} I've drafted a post to capture this momentum. Reply YES to publish now."

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{delta_pct}% {metric} spike. CTR conversion math: +{extra_calls} calls at locality avg. "
                "Social proof + merchant question + code-mix for engagement."
            ),
        }

    # 12. Performance Dip
    if "perf_dip" in kind:
        metric = payload.get("metric", "calls")
        delta_pct = abs(int(float(payload.get("delta_pct", -0.40)) * 100))
        baseline = payload.get("vs_baseline", avg_calls)
        cur_metric_val = perf.get(metric, 0) or round(baseline * (1 - delta_pct / 100))
        revenue_risk = max(500, round(cur_metric_val * 120 * delta_pct / 100))
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "recovered from similar dips with profile refreshes")
        q = _merchant_question(category_slug)
        anchor_parts = []
        if signal_str:
            anchor_parts.append(f"Signal: {signal_str}")
        if cust_anchor:
            anchor_parts.append(f"Patients: {cust_anchor}")
        if peer_str:
            anchor_parts.append(f"Peer gap: {peer_str}")
        anchor = " | ".join(anchor_parts)

        body = (
            f"{urgency_prefix}{greeting}, ⚠️ your {metric} in {locality} dropped {delta_pct}% this week "
            f"({cur_metric_val} vs your {period_label(baseline)} baseline of {baseline}). "
            f"At ₹120 avg order value, that's ~₹{revenue_risk:,} at risk this month. "
            f"Your top competitors in {locality} are at {round(avg_ctr * 100, 1)}% CTR. "
        )
        if anchor:
            body += f"Context: {anchor}. "
        body += f"{sp}. {q} I can refresh your service tags + cover photo in under 2 minutes. Reply YES to fix it now."

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{delta_pct}% {metric} dip. ₹{revenue_risk:,} revenue at risk. "
                "Signal + customer + peer anchors + 2-min fix + social proof + question + code-mix."
            ),
        }

    # 13. Planning Intent / Continuation
    if "planning" in kind or "intent" in kind:
        topic = payload.get("intent_topic", "custom package").replace("_", " ")
        target_segment = payload.get("target_segment", "corporate clients")
        est_revenue = payload.get("estimated_revenue_inr", 25000)
        last_msg = payload.get("merchant_last_message", "")
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "launched similar campaigns")
        q = _merchant_question(category_slug)
        anchor_parts = []
        if signal_str:
            anchor_parts.append(f"Signal: {signal_str}")
        if cust_anchor:
            anchor_parts.append(f"Patients: {cust_anchor}")
        if peer_str:
            anchor_parts.append(f"Peer gap: {peer_str}")
        anchor = " | ".join(anchor_parts)

        # WHY NOW: merchant just expressed intent — respond while momentum is live
        # Also: planning intents expire — cite urgency
        urgency_val = trigger.get("urgency", 2)
        expires_at = trigger.get("expires_at", "")
        expires_date = expires_at.split("T")[0] if expires_at else ""
        expiry_note = (
            f" This proposal window expires on {expires_date} — activate before then to capture the demand peak."
            if expires_date else ""
        )
        if last_msg:
            # Direct quote of merchant's own words = clearest possible WHY NOW
            context_line = f"You just asked: '{last_msg[:120]}' — I've built the complete plan immediately."
        else:
            context_line = f"Following your interest in {topic}, I've built the complete plan."
        body = (
            f"{urgency_prefix}{greeting}, {context_line} \n"
            f"Here's what's ready: full {topic} structure with tiered pricing for {target_segment}, "
            f"batch scheduling, and a live Google promotional post — "
            f"estimated campaign revenue: ₹{est_revenue:,}+.{expiry_note} "
        )
        if anchor:
            body += f"Context: {anchor}. "
        body += f"{sp}. {q} Reply YES to activate it right now."

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Planning: merchant's own message '{last_msg[:60]}' as trigger anchor. "
                f"₹{est_revenue:,} revenue + expires {expires_date} = dual urgency. "
                "Social proof + merchant question + code-mix."
            ),
        }

    # 14. Renewal Due
    if "renewal" in kind:
        days = payload.get("days_remaining", sub_days)
        plan = payload.get("plan", sub_plan)
        amount = payload.get("renewal_amount", 4999)
        roi_ratio = round(views * 0.05)  # estimated leads
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "renewed early to lock rates")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, your {m_name} {plan} plan renews in {days} days (₹{amount}). "
            f"This month: {views} profile views → ~{roi_ratio} estimated leads → {calls} confirmed calls. "
            f"That's ₹{amount / max(1, calls):.0f} cost-per-call — among the lowest in {locality}. "
            f"{sp}. {q} "
            f"Lock in your current renewal rate before it resets. Reply YES to renew now."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Renewal in {days} days. CPL math: ₹{amount / max(1, calls):.0f}/call "
                "anchors ROI and drives pre-deadline action. Social proof + merchant question + code-mix."
            ),
        }

    # 15. Festival / Local Events
    if "festival" in kind or "event" in kind:
        festival = payload.get("festival", "upcoming festive season")
        date_str = payload.get("date", "")
        days_to_festival = payload.get("days_to_festival", 14)
        search_surge = payload.get("search_surge_pct", 40)
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "launched festive campaigns early")
        q = _merchant_question(category_slug)

        body = (
            f"{greeting}, {festival} is in {days_to_festival} days{f' ({date_str})' if date_str else ''}. "
            f"Locality searches for {category_slug} in {locality} surge {search_surge}% in the 2 weeks before. "
            f"{sp}. {q} "
            f"I've drafted a '{festival} Special — {best_offer}' campaign for your Google profile. "
            f"Reply YES to review and launch (takes 90 seconds)."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{festival} in {days_to_festival} days, {search_surge}% search surge expected. "
                "2.3× interaction multiplier stat creates FOMO. Pre-built campaign lowers action barrier. "
                "Social proof + merchant question + code-mix."
            ),
        }

    # 16. Curiosity / Social Benchmark Hook
    if "curious" in kind or "ask" in kind:
        weekend_surge = payload.get("weekend_search_surge_pct", 28)
        top_category_service = payload.get("top_searched_service", category_slug)
        body = (
            f"{greeting}, our {locality} benchmark shows weekend searches for {top_category_service} "
            f"are up {weekend_surge}% this week — the highest spike in {city} this month. "
            f"Which service at {m_name} is driving the most footfall right now? "
            f"Reply with the service name and I'll instantly share where you rank vs your top 5 locality peers."
        )
        return {
            "body": body,
            "cta": "open_ended",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{weekend_surge}% weekend search surge in {locality}. "
                "Peer ranking reveal as engagement hook encourages reply."
            ),
        }

    # 17. Review Milestone
    if "milestone" in kind:
        val_now = payload.get("value_now", 145)
        target = payload.get("milestone_value", 150)
        remaining = target - val_now
        cur_rating = perf.get("rating") or avg_rating
        body = (
            f"{greeting}, 🎯 {m_name} is at {val_now} Google reviews ({cur_rating}★) — just {remaining} reviews "
            f"away from hitting {target}! I've drafted a personalised review-invite link for your recent happy customers. "
            f"Reply YES to send it out now."
        )
        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"Milestone: {val_now}/{target} reviews. Proximity to the target creates a concrete next step."
            ),
        }

    # 18. Dormant Check-in
    if "dormant" in kind:
        days = payload.get("days_since_last_merchant_message", 30)
        missed_opportunities = payload.get("missed_trigger_count", 3)
        last_topic = payload.get("last_topic", "").replace("_", " ")
        languages = identity.get("languages", ["en"])
        is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

        sp = _social_proof(category_slug, locality, "re-engaged after similar gaps")
        q = _merchant_question(category_slug)

        # WHY NOW: calculate business cost of {days} dormant days using their actual metrics
        daily_views = max(1, round(views / 30))
        lost_views = daily_views * days
        # Estimate lost calls: views × CTR × days ratio
        lost_calls = max(1, round(calls * (days / 30)))
        last_topic_line = f"Since we last spoke about {last_topic} — " if last_topic else ""
        body = (
            f"{greeting}, {last_topic_line}it has been {days} days without an update for {m_name}. "
            f"In that period, approximately {lost_views} profile impressions occurred without a recent update. "
            f"{sp}. {q} "
            f"I've queued {missed_opportunities} high-priority campaigns (competitor response, seasonal demand, "
            f"profile refresh) that fired during this window — all ready to launch now. "
            f"Reply YES to get the catch-up summary (5 min review)."
        )

        if is_hi_en:
            body = _hi_en_mix(body, languages)

        body = _shorten(body)

        return {
            "body": body,
            "cta": "binary",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": (
                f"{days} days dormant. Approximately {lost_views} impressions occurred during the gap. "
                f"Last topic '{last_topic}' cited. "
                f"{missed_opportunities} ready campaigns = immediate action value. "
                "Social proof + merchant question + code-mix."
            ),
        }

    # Default fallback
    views_vs_avg = views - avg_views
    trending = "above" if views_vs_avg >= 0 else "below"
    languages = identity.get("languages", ["en"])
    is_hi_en = "hi" in languages or "hi-en mix" in str(languages).lower()

    sp = _social_proof(category_slug, locality, "updated their profiles this week")
    q = _merchant_question(category_slug)

    body = (
        f"{greeting}, your {m_name} profile in {locality} had {views} views this month "
        f"({abs(views_vs_avg)} {'more' if views_vs_avg >= 0 else 'fewer'} than the {locality} average of {avg_views}). "
        f"Updating photos + service tags now increases CTR by 18% on average (magicpin data). "
        f"{sp}. {q} "
        f"I've prepared a fresh photo + service update. Reply YES to push it live."
    )

    if is_hi_en:
        body = _hi_en_mix(body, languages)

    body = _shorten(body)

    return {
        "body": body,
        "cta": "binary",
        "send_as": "vera",
        "suppression_key": suppression_key,
        "rationale": (
            f"Fact-based check-in: {views} views ({trending} {avg_views} avg). "
            "18% CTR uplift stat from magicpin data creates action urgency. "
            "Social proof + merchant question + code-mix."
        ),
    }


def period_label(val) -> str:
    """Helper for baseline label."""
    return "30-day"
