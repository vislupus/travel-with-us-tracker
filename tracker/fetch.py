"""HTTP заявки към travelwithus.bg.

Проверката е веднъж дневно, по една заявка на страница, с пауза между тях и с
User-Agent, който казва какво е – без да се представя за браузър.

Хостингът на сайта има защита срещу ботове: понякога вместо страницата връща
„One moment, please…“ (проверка с JavaScript). Тракерът НЕ се опитва да я
заобиколи – такава страница се брои за непрочетена днес, старите данни се
пазят и на следващия ден се пробва пак. Обикновено страниците идват от кеша на
сайта и проверката не се появява.
"""
from __future__ import annotations

import re
import time

import requests

UA = "travel-date-checker/1.0 (personal use; one request per page per day)"


class FetchError(Exception):
    pass


class BlockedError(FetchError):
    """Сайтът не даде страницата (защита срещу ботове, 403, 429…)."""


CHALLENGE_RE = re.compile(r"<title>\s*(One moment, please|Just a moment|Attention Required|Access denied)", re.I)


def is_challenge(html: str) -> bool:
    """Страница „докажи, че не си робот“ вместо съдържанието."""
    head = html[:3000]
    if CHALLENGE_RE.search(head):
        return True
    return len(html) < 40_000 and "single_tour_content" not in html and "wsidchk" in html


def describe_block(resp) -> str:
    h = {k.lower(): v for k, v in resp.headers.items()}
    parts = [f"HTTP {resp.status_code}"]
    if h.get("server"):
        parts.append(f"server={h['server']}")
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text or "", re.S | re.I)
    if m:
        parts.append(f"title='{' '.join(m.group(1).split())[:60]}'")
    return ", ".join(parts)


class Fetcher:
    def __init__(self, timeout: float = 40, log=print):
        self.timeout = timeout
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
        })

    def get(self, url: str) -> str:
        last = "неизвестна грешка"
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                last = f"Мрежова грешка: {e}"
                time.sleep(5 * (attempt + 1))
                continue
            code = resp.status_code
            if code == 200:
                resp.encoding = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else "utf-8"
                html = resp.text
                if is_challenge(html):
                    raise BlockedError("Сайтът поиска проверка „не си робот“ вместо да покаже страницата – "
                                       "ще се опита пак при следващата проверка.")
                return html
            if code == 404:
                raise FetchError("Страницата не съществува (404) – линкът вероятно е сменен.")
            if code in (401, 403, 429):
                raise BlockedError(f"Сайтът отказа достъп ({describe_block(resp)}).")
            if code >= 500:
                last = f"Сайтът върна грешка ({describe_block(resp)})."
                time.sleep(10 * (attempt + 1))
                continue
            raise FetchError(f"Сайтът върна HTTP {code}.")
        raise FetchError(last)
