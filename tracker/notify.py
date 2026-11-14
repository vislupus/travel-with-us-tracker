"""Известия в Slack.

Поддържат се два начина (първият намерен се ползва):
  1. Бот токен  – SLACK_BOT_TOKEN (xoxb-...) + SLACK_CHANNEL_ID
  2. Webhook    – SLACK_WEBHOOK_URL (https://hooks.slack.com/services/...)

Стойностите се четат от променливи на средата. В GitHub Actions те идват от
Settings → Secrets and variables → Actions и никога не се пазят в кода.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from .changes import (AVAILABLE_AGAIN, COMBO_APPEARED, COMBO_GONE, KIND_LABELS, NEW_DEPARTURE, PRICE_CHANGE,
                      SEATS_CHANGE)

SOFIA = ZoneInfo("Europe/Sofia")


class SlackNotifier:
    def __init__(self):
        self.token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        self.channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
        self.webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    @property
    def mode(self) -> str | None:
        if self.token and self.channel:
            return "bot"
        if self.webhook:
            return "webhook"
        return None

    def send(self, text: str, blocks: list | None = None) -> bool:
        """Връща True при успех. Грешките се логват, но не спират скрипта."""
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            if self.mode == "bot":
                resp = requests.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {self.token}",
                             "Content-Type": "application/json; charset=utf-8"},
                    json={"channel": self.channel, "unfurl_links": False, **payload},
                    timeout=15,
                )
                data = resp.json()
                if not data.get("ok") and data.get("error") == "invalid_blocks" and blocks:
                    return self.send(text)
                if not data.get("ok"):
                    print(f"::warning ::Slack отказа съобщението: {data.get('error')}")
                    return False
                return True
            if self.mode == "webhook":
                resp = requests.post(self.webhook, json=payload, timeout=15)
                if resp.status_code == 400 and "invalid_blocks" in resp.text and blocks:
                    return self.send(text)
                if resp.status_code != 200:
                    print(f"::warning ::Slack webhook върна {resp.status_code}: {resp.text[:200]}")
                    return False
                return True
        except requests.RequestException as e:
            print(f"::warning ::Неуспешна връзка със Slack: {e}")
            return False
        print("ℹ️  Slack не е настроен – съобщението само се показва тук:\n" + text)
        return False


# ---- форматиране ---------------------------------------------------------

def fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def fmt_range(start: str, end: str) -> str:
    """„22.05 – 30.05.2027 (9 дни)“; само датата на тръгване, ако краят не е обявен."""
    if not start:
        return "бележка без посочена дата"
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end or start)
    except ValueError:
        return f"{start} – {end}"
    if e <= s:
        return s.strftime("%d.%m.%Y")
    days = (e - s).days + 1
    if s.year == e.year:
        return f"{s.strftime('%d.%m')} – {e.strftime('%d.%m.%Y')} ({days} дни)"
    return f"{s.strftime('%d.%m.%Y')} – {e.strftime('%d.%m.%Y')} ({days} дни)"


def fmt_price(value: float | None, currency: str | None = "EUR", page_price: bool = False) -> str:
    """`page_price` = общата цена „от … €“ на екскурзията (за датата няма отделна)."""
    if value is None:
        return "—"
    cur = "€" if (currency or "EUR") == "EUR" else (currency or "")
    s = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return ("от " if page_price else "") + f"{s.replace(',', ' ')} {cur}".strip()


def dep_label(name: str | None, start: str, end: str) -> str:
    """„КЪС ВАРИАНТ, 15.01.2027“ – вариантът често липсва."""
    when = fmt_range(start, end)
    return f"{name}, {when}" if name else when


def fmt_seats(seats: int | None, seats_text: str | None, available: bool | None) -> str:
    if seats_text:
        return seats_text.lower()
    if seats is not None:
        return "няма места" if seats == 0 else f"{seats} свободни места"
    if available is True:
        return "има места"
    if available is False:
        return "няма места"
    return "места: неизвестно"


def fmt_when(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(SOFIA).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def combo_phrase(combo: str | None) -> str:
    return {"мъж": "мъж за комбинация", "жена": "жена за комбинация",
            "any": "човек за комбинация (полът не е посочен)"}.get(combo or "", "човек за комбинация")


def signup_url(travel_url: str) -> str:
    """Формата за запитване е на самата страница на екскурзията."""
    return travel_url


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def combo_alert_message(*, travel_name: str, travel_url: str, dep, change_detail: dict, dashboard_url: str | None,
                        price_history: dict | None = None):
    """Отделно, силно съобщение – точно това, за което е целият проект."""
    combo = change_detail.get("combo") or dep.combo
    who = combo_phrase(combo)
    emoji = "🧔" if combo == "мъж" else ("👩" if combo == "жена" else "🧑‍🤝‍🧑")
    price = fmt_price(dep.price, dep.currency, dep.price_from_page)
    if dep.start_date:
        text = (f"{emoji} Търси се {who}: {travel_name} – {dep_label(dep.name, dep.start_date, dep.end_date)}, "
                f"{price}, {fmt_seats(dep.seats, dep.seats_text, dep.available)}. "
                f"Виж: {signup_url(travel_url)}")
    else:
        text = (f"{emoji} Търси се {who}: {travel_name} – бележка без посочена дата"
                + (f" („{dep.combo_text}“)" if dep.combo_text else "") + f". Виж: {signup_url(travel_url)}")

    facts = [
        f"*Дати:* {fmt_range(dep.start_date, dep.end_date)}",
        f"*Цена:* {price}",
        f"*Места:* {fmt_seats(dep.seats, dep.seats_text, dep.available)}",
    ]
    if not dep.start_date:
        facts = ["*Дата:* не е посочена до бележката – виж страницата"]
    if dep.badges:
        facts.append(f"*Група:* {', '.join(b.lower() for b in dep.badges)}")
    if dep.combo_text:
        facts.append(f"На сайта пише: _„{dep.combo_text}“_")
    if change_detail.get("prev_combo"):
        facts.append(f"(преди пишеше „{change_detail['prev_combo']} за комбинация“)")
    if price_history and price_history.get("min") is not None and price_history.get("min") != dep.price:
        facts.append(f"*Цената досега:* {fmt_price(price_history['min'], dep.currency)} – "
                     f"{fmt_price(price_history['max'], dep.currency)}")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "emoji": True,
                                    "text": _cut(f"{emoji} Търси се {who}!", 150)}},
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"*<{travel_url}|{travel_name}>*" + (f"\n{dep.name}" if dep.name else "")}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(facts)}},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary", "url": signup_url(travel_url),
             "text": {"type": "plain_text", "emoji": True, "text": "КЪМ ЕКСКУРЗИЯТА →"}},
        ]},
    ]
    if dashboard_url:
        blocks[-1]["elements"].append(
            {"type": "button", "url": dashboard_url,
             "text": {"type": "plain_text", "emoji": True, "text": "Всички дати"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                   "text": "Обади им се бързо – търси се точно един човек за стаята."}]})
    return text, blocks


def _digest_line(item: dict) -> str:
    """item: {kind, detail, dep(dict), travel_url}"""
    d, dep, k = item["detail"], item["dep"], item["kind"]
    where = f"<{signup_url(item['travel_url'])}|{dep_label(dep['name'], dep['start_date'], dep['end_date'])}>"
    if k == NEW_DEPARTURE:
        extra = (f"{fmt_price(d.get('price'), d.get('currency'), bool(d.get('page_price')))}, "
                 f"{fmt_seats(d.get('seats'), d.get('seats_text'), d.get('available'))}")
        return f"🆕 Нова дата: {where} – {extra}"
    if k == PRICE_CHANGE:
        arrow = "▼" if d["diff"] < 0 else "▲"
        pct = f" ({d['pct']:+.1f} %)" if d.get("pct") is not None else ""
        if item.get("all_dates"):
            # общата цена „от … €“ на екскурзията – един ред вместо по един за всяка дата
            where = f"<{signup_url(item['travel_url'])}|цената „от“ на екскурзията>"
        return (f"{'💚' if d['diff'] < 0 else '🔺'} Цена {arrow}: {where} – "
                f"{fmt_price(d['old'], d.get('currency'))} → *{fmt_price(d['new'], d.get('currency'))}*{pct}")
    if k == SEATS_CHANGE:
        return f"⏳ Последни места: {where} – *{fmt_seats(d.get('new'), d.get('new_text'), True)}*"
    if k == AVAILABLE_AGAIN:
        return f"🔓 Отново има места: {where} – {fmt_seats(d.get('seats'), d.get('seats_text'), True)}"
    if k == COMBO_GONE:
        return f"🚪 Бележката „{d.get('prev_combo') or 'човек'} за комбинация“ вече я няма: {where}"
    if k == COMBO_APPEARED:
        return f"🧑‍🤝‍🧑 Търси се {combo_phrase(d.get('combo'))}: {where}"
    return f"• {KIND_LABELS.get(k, k)}: {where}"


def digest_message(groups: dict[str, list[dict]], dashboard_url: str | None):
    """groups: {travel_name: [item, ...]} – едно общо съобщение за проверката."""
    total = sum(len(v) for v in groups.values())
    text = f"📋 {total} {'промяна' if total == 1 else 'промени'} по екскурзиите, които следиш"
    sections = []
    for travel_name, items in groups.items():
        lines = [_digest_line(i) for i in items[:12]]
        if len(items) > 12:
            lines.append(f"…и още {len(items) - 12}")
        sections.append(f"*{travel_name}*\n" + "\n".join(lines))
    body = "\n\n".join(sections)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": _cut(f"*{text}*\n\n{body}", 2900)}}]
    if dashboard_url:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": f"<{dashboard_url}|Всички дати и цени>"}]})
    return text, blocks


def reminder_message(matches: list[dict], dashboard_url: str | None):
    """При repeat_alerts_daily: кратко напомняне за всички текущи комбинации."""
    text = f"🔁 Напомняне: {len(matches)} дати, на които се търси човек за комбинация"
    lines = []
    for m in matches:
        dep = m["dep"]
        lines.append(f"• <{signup_url(m['travel_url'])}|{m['travel_name']} – "
                     f"{dep_label(dep['name'], dep['start_date'], dep['end_date'])}> – "
                     f"{fmt_price(dep['price'], dep['currency'], bool(dep.get('price_from_page')))}, "
                     f"{fmt_seats(dep['seats'], dep['seats_text'], dep['available'])}, {combo_phrase(dep['combo'])}")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": _cut(f"*{text}*\n" + "\n".join(lines), 2900)}}]
    if dashboard_url:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{dashboard_url}|Сайтът>"}]})
    return text, blocks


def errors_message(errors: list[dict], total: int):
    """errors: [{slug, url, name, error, streak}] – само тези, които не се четат от няколко поредни проверки."""
    text = f"⚠️ {len(errors)} от {total} екскурзии не могат да бъдат прочетени"
    reasons = {e["error"] for e in errors}
    if len(errors) > 1 and len(reasons) == 1:
        reason = reasons.pop()
        names = ", ".join(f"<{e['url']}|{_cut(e['name'] or e['slug'], 40)}>" for e in errors[:10])
        body = f"Причина: {_cut(reason, 400)}\n{names}"
    else:
        body = "\n".join(f"• <{e['url']}|{_cut(e['name'] or e['slug'], 50)}> – {_cut(e['error'], 180)}"
                         + (f" ({e['streak']} поредни проверки)" if e.get("streak", 1) > 1 else "")
                         for e in errors[:10])
    if len(errors) > 10:
        body += f"\n…и още {len(errors) - 10}"
    hint = "Провери линковете в travels.yaml."
    if any("не си робот" in e["error"] or "отказа достъп" in e["error"] for e in errors):
        hint = ("Сайтът не пуска проверката до тези страници (защита срещу ботове). Старите данни се пазят; "
                "виж README → „Ако сайтът не пуска проверката“.")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": _cut(f"*{text}*\n{body}", 2900)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": hint}]},
    ]
    return text, blocks
