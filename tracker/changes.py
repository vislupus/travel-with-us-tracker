"""Какво се е променило между две проверки и кое от него заслужава известие.

Известията са само при *промяна* (преход) – когато нещо се появи за първи път.
Ако утре е същото, не се праща пак. Ако изчезне и след месец се появи отново,
това е нова възможност и идва ново известие.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .parser import is_last_seats

# Видове събития (пазят се в таблица events и се виждат в сайта)
NEW_DEPARTURE = "new_departure"        # нова дата на страницата
PRICE_CHANGE = "price_change"          # цената е различна от последната проверка
COMBO_APPEARED = "combo_appeared"      # появи се „мъж/жена за комбинация“ (или смени пола)
COMBO_GONE = "combo_gone"              # бележката за комбинация изчезна
SEATS_CHANGE = "seats_change"          # смени се текстът/броят за местата
SOLD_OUT = "sold_out"                  # вече няма места
AVAILABLE_AGAIN = "available_again"    # отново има места
GROUP_CONFIRMED = "group_confirmed"    # появи се „ОФОРМЕНА / ПОТВЪРДЕНА ГРУПА“
DEPARTURE_GONE = "departure_gone"      # датата изчезна от страницата

KIND_LABELS = {
    NEW_DEPARTURE: "Нова дата",
    PRICE_CHANGE: "Промяна в цената",
    COMBO_APPEARED: "Търси се човек за комбинация",
    COMBO_GONE: "Комбинацията вече я няма",
    SEATS_CHANGE: "Промяна в местата",
    SOLD_OUT: "Няма места",
    AVAILABLE_AGAIN: "Отново има места",
    GROUP_CONFIRMED: "Групата е оформена",
    DEPARTURE_GONE: "Датата е свалена",
}

CONFIRMED_RE = re.compile(r"потвърден|подтвърден|гарантиран|оформен|сформиран", re.I)


@dataclass
class Change:
    kind: str
    detail: dict = field(default_factory=dict)


def _badges(row) -> list[str]:
    if row is None or not row["badges"]:
        return []
    try:
        return list(json.loads(row["badges"]))
    except (TypeError, ValueError):
        return []


def combo_matches(combo: str | None, wanted: str) -> bool:
    """Търсиш „мъж“: пасва „мъж за комбинация“ и неуточнено „за комбинация“ (може да е всеки)."""
    if not combo:
        return False
    if wanted == "any":
        return True
    return combo in (wanted, "any")


def _seats_key(seats, seats_text) -> tuple:
    return seats, (seats_text or "").strip().lower() or None


def detect_changes(prev, dep, *, is_new: bool) -> list[Change]:
    """`prev` е последната снимка от базата (sqlite3.Row или None), `dep` – какво виждаме сега."""
    changes: list[Change] = []
    state = {"price": dep.price, "currency": dep.currency, "seats": dep.seats, "seats_text": dep.seats_text,
             "available": dep.available, "combo": dep.combo, "combo_text": dep.combo_text,
             "badges": list(dep.badges), "action": dep.action, "page_price": bool(dep.price_from_page)}

    if prev is None or is_new:
        changes.append(Change(NEW_DEPARTURE, dict(state)))
        if dep.combo:
            changes.append(Change(COMBO_APPEARED, {"combo": dep.combo, "combo_text": dep.combo_text,
                                                   "prev_combo": None, **_short(state)}))
        return changes

    prev_price, prev_combo = prev["price"], prev["combo"]
    prev_avail = None if prev["available"] is None else bool(prev["available"])
    prev_seats = prev["seats"]

    if dep.price is not None and prev_price is not None and abs(dep.price - prev_price) >= 0.005:
        diff = round(dep.price - prev_price, 2)
        pct = round(diff / prev_price * 100, 1) if prev_price else None
        changes.append(Change(PRICE_CHANGE, {"old": prev_price, "new": dep.price, "diff": diff, "pct": pct,
                                             "currency": dep.currency, **_short(state)}))

    if dep.combo != prev_combo:
        if dep.combo:
            changes.append(Change(COMBO_APPEARED, {"combo": dep.combo, "combo_text": dep.combo_text,
                                                   "prev_combo": prev_combo, **_short(state)}))
        else:
            changes.append(Change(COMBO_GONE, {"prev_combo": prev_combo, **_short(state)}))

    if prev_avail is not False and dep.available is False:
        changes.append(Change(SOLD_OUT, {"prev_seats": prev_seats, **_short(state)}))
    elif prev_avail is False and dep.available is True:
        changes.append(Change(AVAILABLE_AGAIN, {**_short(state)}))
    elif _seats_key(dep.seats, dep.seats_text) != _seats_key(prev_seats, prev["seats_text"]):
        changes.append(Change(SEATS_CHANGE, {"old": prev_seats, "new": dep.seats,
                                             "old_text": prev["seats_text"], "new_text": dep.seats_text,
                                             **_short(state)}))

    old_b, new_b = _badges(prev), list(dep.badges)
    if any(CONFIRMED_RE.search(b) for b in new_b) and not any(CONFIRMED_RE.search(b) for b in old_b):
        changes.append(Change(GROUP_CONFIRMED, {"badges": new_b, **_short(state)}))

    return changes


def _short(state: dict) -> dict:
    return {"price": state["price"], "currency": state["currency"], "seats": state["seats"],
            "seats_text": state["seats_text"], "available": state["available"],
            "page_price": state["page_price"]}


# ---- политика за известия -------------------------------------------------

def wants_alert(change: Change, settings) -> bool:
    """Силно известие (отделно съобщение): появи се комбинация с този, когото търсиш."""
    if change.kind != COMBO_APPEARED:
        return False
    combo = change.detail.get("combo")
    if combo_matches(combo, settings.combination):
        return True
    return bool(settings.notify_any_combination)


def wants_digest(change: Change, settings, *, baseline: bool) -> bool:
    """По-тихи новини – събират се в едно общо съобщение за проверката."""
    if baseline:
        return False  # първата проверка на екскурзия – не заливаме с „нови дати“
    k, d = change.kind, change.detail
    if k == NEW_DEPARTURE:
        return bool(settings.notify_new_dates)
    if k == PRICE_CHANGE:
        return bool(settings.notify_price_changes)
    if k == AVAILABLE_AGAIN:
        return bool(settings.notify_available_again)
    if k == SEATS_CHANGE and settings.notify_last_seats:
        n = settings.notify_last_seats
        return (is_last_seats(d.get("new"), d.get("new_text"), n)
                and not is_last_seats(d.get("old"), d.get("old_text"), n))
    if k == COMBO_GONE:
        return combo_matches(d.get("prev_combo"), settings.combination)
    return False


def last_seats_hit(dep, settings) -> bool:
    return bool(settings.notify_last_seats) and is_last_seats(dep.seats, dep.seats_text, settings.notify_last_seats)
