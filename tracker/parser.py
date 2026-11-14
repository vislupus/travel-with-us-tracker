"""Четене на страница на екскурзия в travelwithus.bg.

Страниците са писани на ръка и всяка изглежда малко по-различно, затова не се
разчита на конкретни класове, а на това как изглежда една „карта с дата“:

    22.05.2027 – 30.05.2027            30.01 – 12.02.2027            01.05.2027
    • има места                        КАРНАВАЛА В РИО               ● ИМА МЕСТА
                                       ● ПОСЛЕДНО 1 МЯСТО            ● жена за комбинация
                                       4090 €

Карта е най-големият елемент, в който има точно една дата (или период). От
текста ѝ се вадят състоянието на местата, цената, бележката „мъж/жена за
комбинация“ и останалите етикети („ОФОРМЕНА ГРУПА“, „от Варна“…).

Датите идват от първата секция с дати на страницата („ДАТИ:“, „Дати на
екскурзията“, „Дати и цени“). По-долните таблици с цени само допълват вече
намерените дати (цена, наличност) – така остарели дати от „Въпроси и отговори“
не се броят за нови групи. Изключение: дата с бележка за комбинация се взима,
където и да е на страницата, а бележка за комбинация без дата се пази като
отделен ред „без посочена дата“ – за да не се изпусне.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from bs4 import BeautifulSoup, NavigableString, Tag

# ---- дати ------------------------------------------------------------------

_DASH = r"[-–—]"
_RANGE = (r"(?<![\d.,])(?P<d1>\d{1,2})(?:\.(?P<m1>\d{1,2})(?:\.(?P<y1>\d{4}|\d{2}))?)?\.?\s*(?:г\.?\s*)?"
          + _DASH + r"\s*(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y2>\d{4}|\d{2})(?!\d)")
_SINGLE = r"(?<![\d.,])(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4}|\d{2})(?!\d)"
DATE_EXPR_RE = re.compile(f"{_RANGE}|{_SINGLE}")

# „до 30.04.2027“, „след 30.04.2027“, „валидна до…“ са срокове, не дати на тръгване
_NOT_A_DEPARTURE_RE = re.compile(r"(?:\bдо|\bслед|\bпреди|\bкъм|валидн\w*|записван\w*|плащан\w*|доплащан\w*|"
                                 r"депозит\w*|публикуван\w*|актуализиран\w*)\s*(?:на\s+|до\s+|от\s+)?$", re.I)

# ---- цени ------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[ \xa0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{3})*(?:[.,]\d{1,2})?"
_CUR = r"€|EUR|EURO|евро|лв\.?|лева|BGN"
PRICE_RE = re.compile(rf"(?P<plus>\+\s*)?(?:(?P<cur1>€)\s*(?P<n1>{_NUM})|(?P<n2>{_NUM})\s*(?P<cur2>{_CUR}))(?![\w])",
                      re.I)

# ---- места и комбинации ------------------------------------------------------

_GENDER = r"(?:[мm]ъж\w*|жен\w*|дам\w*|господин\w*|момч\w*|момич\w*)"
_GENDERS = rf"(?P<g>{_GENDER}(?:\s*(?:и|или|/|,)\s*{_GENDER})*)"
COMBO_RES = [
    re.compile(rf"{_GENDERS}\s+(?:за|-|–)\s*комбин\w+", re.I),
    re.compile(rf"комбин\w+\s+(?:с|със|за)\s+{_GENDERS}", re.I),
    re.compile(rf"(?:търси(?:м|ме|\s+се)?|има)\s+{_GENDERS}\s+за\s+(?:комбин\w+|споделян\w+|настаняван\w+|"
               rf"двойна|стая)", re.I),
]
COMBO_ANY_RE = re.compile(r"(?:за|възможност\s+за|търсим)\s+комбинац\w+|комбинация\s+в\s+(?:двойна\s+)?стая", re.I)

SEATS_NUM_RE = re.compile(r"(?:последн\w*|остава\w*|само|свободн\w*)?\s*(\d{1,2})\s*(?:свободн\w*\s*)?(?:места|място)", re.I)
SEATS_FREE_RE = re.compile(r"(\d{1,2})\s*свободн", re.I)
STATUS_RE = re.compile(r"няма\s+(?:свободни\s+)?места|изчерпан\w*|запълнен\w*|разпродаден\w*|sold\s*out|"
                       r"последн\w*\s+\d{0,2}\s*(?:свободн\w*\s*)?(?:места|място)|ограничен\w*\s+(?:брой\s+)?места|"
                       r"(?:остава\w*\s+|само\s+)?\d{1,2}\s*(?:свободн\w*\s*)?(?:места|място)|"
                       r"има\s+(?:свободни\s+)?места|свободни\s+места|"
                       r"на\s+запитване|лист\s+на\s+чакащи|очаквайте(?:\s+нови\s+дати)?", re.I)
BADGE_WORDS_RE = re.compile(r"потвърден|подтвърден|гарантиран|оформен|сформиран|нова\s+група|промо|карнавал|"
                            r"нова\s+година|велик|коледа|ваканц|чартър|директен", re.I)

VARIANT_RE = re.compile(r"вариант", re.I)
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BLOCK_TAGS = ("div", "p", "li", "td", "th", "tr", "table", "tbody", "ul", "ol", "section", "article", "dd", "dt",
              "blockquote", "figure", "details", "summary")
DATES_HEADING_RE = re.compile(r"\bдат[аи]", re.I)
MAX_CARD_TEXT = 320          # повече от това не е карта, а абзац текст

# „1 ДЕН: 04.12.2026“, „Ден 12 : 16.09.2025 г.“ – дата от програмата по дни, не тръгване
PROGRAM_DAY_RE = re.compile(r"\bден\s*\d{1,2}\b|\b\d{1,2}\s*(?:-?\s*(?:ви|ри|ти|ми))?\s*ден\b", re.I)

PAGE_NOTE_KEY = "page-note"


class ParseError(Exception):
    pass


@dataclass
class Departure:
    key: str                     # стабилен ключ: дати + вариант (+ град на тръгване)
    start_date: str              # ISO 8601 (2027-05-22); "" = бележка без дата
    end_date: str                # ISO; = start_date, ако на страницата е само датата на тръгване
    name: str                    # вариант на програмата („КЪС ВАРИАНТ“, „от Варна“) – може да е празно
    price: float | None
    currency: str
    action: str                  # за съвместимост с базата: ИМА МЕСТА | НЯМА МЕСТА | …
    heading: str                 # текстът на картата, както е на страницата
    seats: int | None = None     # брой свободни места, ако е посочен
    seats_text: str | None = None
    available: bool | None = None  # True = има места, False = няма, None = неизвестно
    combo: str | None = None     # None | мъж | жена | any
    combo_text: str | None = None
    badges: list[str] = field(default_factory=list)
    post_id: str | None = None
    in_grid: bool = True         # True = от секцията с дати (а не само от таблица по-долу)
    has_end: bool = True         # False = на страницата е само датата на тръгване
    price_from_page: bool = False  # True = цената е общата „от … €“ на екскурзията, не на тази дата

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TravelPage:
    title: str | None
    image: str | None
    description: str | None
    departures: list[Departure]
    price_from: float | None = None


# ---- помощни -----------------------------------------------------------------

def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").replace("\u202f", " ").split())


def _year(y: str) -> int:
    return int(y) + 2000 if len(y) == 2 else int(y)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_expr(m: re.Match) -> tuple[date, date | None] | None:
    """Съвпадение на DATE_EXPR_RE -> (начало, край или None)."""
    if m.group("d") is not None:
        start = _safe_date(_year(m.group("y")), int(m.group("m")), int(m.group("d")))
        return (start, None) if start else None
    y2 = _year(m.group("y2"))
    end = _safe_date(y2, int(m.group("m2")), int(m.group("d2")))
    if not end:
        return None
    d1 = int(m.group("d1"))
    m1 = int(m.group("m1")) if m.group("m1") else end.month   # „17 – 25.05.2027“
    if m.group("y1"):
        start = _safe_date(_year(m.group("y1")), m1, d1)
    else:
        # „28.12 – 08.01.2027“ -> тръгва се предната година
        start = _safe_date(y2 - 1 if m1 > end.month else y2, m1, d1)
    if not start:
        return None
    if end < start:
        # сбъркана година в края („07.11.2027 – 26.11.2026“) – приемаме годината на тръгване
        fixed = _safe_date(start.year, end.month, end.day)
        if fixed and fixed < start:
            fixed = _safe_date(start.year + 1, end.month, end.day)
        end = fixed
        if not end or (end - start).days > 120:
            return (start, None)
    if (end - start).days > 120:
        return None  # това е период („01.05.2027 – 30.09.2027“), не екскурзия
    return start, end


def _price(raw: str) -> float | None:
    """„3930“, „1 250,50“, „2.990“, „1531,50“, „4090.00“ -> число."""
    s = raw.replace(" ", "").replace("\u202f", "").replace("\xa0", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")   # 1.250,50
        else:
            s = s.replace(",", "")                     # 1,250.50
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _currency(raw: str) -> str:
    r = raw.upper().rstrip(".")
    if r in ("€", "EUR", "EURO", "ЕВРО"):
        return "EUR"
    if r in ("BGN", "ЛВ", "ЛЕВА"):
        return "BGN"
    return r


def find_prices(text: str) -> list[tuple[float, str]]:
    """Всички цени в текста по реда им. Доплащанията („+442 евро“) се пропускат."""
    out = []
    for m in PRICE_RE.finditer(text):
        if m.group("plus"):
            continue
        value = _price(m.group("n1") or m.group("n2"))
        if value is None or value < 50:
            continue
        out.append((value, _currency(m.group("cur1") or m.group("cur2"))))
    return out


def pick_price(text: str) -> tuple[float | None, str]:
    prices = find_prices(text)
    for value, cur in prices:
        if cur == "EUR":
            return value, cur
    return prices[0] if prices else (None, "EUR")


def normalize_name(name: str) -> str:
    return re.sub(r"[^\wа-я]+", " ", name.lower(), flags=re.I).strip()


def make_key(start_iso: str, end_iso: str | None, name: str) -> str:
    key = start_iso + (f"_{end_iso}" if end_iso else "")
    suffix = normalize_name(name).replace(" ", "-")
    return f"{key}_{suffix}" if suffix else key


def _gender(word: str) -> str | None:
    w = word.lower().replace("m", "м")   # „Mъж“ с латинско M се среща на сайта
    if w.startswith(("мъж", "господин", "момч")):
        return "мъж"
    if w.startswith(("жен", "дам", "момич")):
        return "жена"
    return None


def parse_combo(text: str, *, allow_any: bool = True) -> tuple[str | None, str | None]:
    """„ИМА МЕСТА • жена за комбинация“ -> ('жена', 'жена за комбинация').

    Ако са посочени и двата пола – 'any'. `allow_any=False` иска изрично посочен
    пол (за текст извън картите с дати, където „комбинация“ е честа дума).
    """
    genders: set[str] = set()
    snippet = None
    for rx in COMBO_RES:
        for m in rx.finditer(text):
            for word in re.findall(_GENDER, m.group("g"), re.I):
                g = _gender(word)
                if g:
                    genders.add(g)
            snippet = snippet or _clean(m.group(0))
    if genders:
        return ("any" if len(genders) > 1 else genders.pop()), snippet
    if allow_any:
        m = COMBO_ANY_RE.search(text)
        if m:
            return "any", _clean(m.group(0))
    return None, None


def parse_seats(text: str) -> tuple[int | None, bool | None, str | None]:
    """-> (брой места, има ли места, текстът за местата)."""
    t = _clean(text)
    m = STATUS_RE.search(t)
    if not m:
        return None, None, None
    label = _clean(m.group(0)).lower()
    if re.search(r"няма|изчерпан|запълнен|разпродаден|sold|чакащи", label):
        return 0, False, label
    if "очаквайте" in label or "запитване" in label:
        return None, None, label
    n = SEATS_FREE_RE.search(label) or SEATS_NUM_RE.search(label)
    if n and n.group(1):
        seats = int(n.group(1))
        return seats, seats > 0, label
    if "последн" in label and "място" in label:
        return 1, True, label
    return None, True, label


def is_last_seats(seats: int | None, seats_text: str | None, threshold: int) -> bool:
    """„последни места“, „ограничени места“ или брой <= прага."""
    if seats is not None:
        return 0 < seats <= threshold if threshold else False
    return bool(seats_text) and bool(re.search(r"последн|ограничен", seats_text, re.I))


# ---- намиране на картите -----------------------------------------------------

def _text(el) -> str:
    return _clean(el.get_text(" ", strip=True))


def _count_dates(text: str) -> int:
    return sum(1 for m in DATE_EXPR_RE.finditer(text) if parse_date_expr(m))


@dataclass
class _Card:
    el: Tag
    text: str
    start: date
    end: date | None
    section: int                # пореден номер на секцията (по заглавията)
    section_title: str
    variant: str = ""
    group_text: str = ""        # текст на групата (общ за няколко карти), напр. обща цена
    table_header: str = ""
    order: int = 0
    multi: bool = False         # няколко дати в един елемент („За дати: 07.01.27, 05.03.27“)


def _strip_noise(root: Tag) -> None:
    for t in root(["script", "style", "svg", "noscript", "template", "iframe", "form", "del", "s", "strike"]):
        t.decompose()


def _own_lines(el: Tag) -> list[str]:
    """Текстът на картата по редове (всеки блоков елемент / <br> е нов ред), без заглавия."""
    parts: list[str] = []
    buf: list[str] = []

    def flush():
        line = _clean(" ".join(buf))
        buf.clear()
        if line:
            parts.append(line)

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                buf.append(str(child))
            elif isinstance(child, Tag):
                if child.name in HEADING_TAGS:
                    flush()
                    continue
                if child.name == "br":
                    flush()
                elif child.name in BLOCK_TAGS:
                    flush()
                    walk(child)
                    flush()
                else:
                    walk(child)
    walk(el)
    flush()
    return parts


def _find_cards(content: Tag) -> list[_Card]:
    # Секции: всяко заглавие h1–h6 започва нова
    section_of: dict[int, tuple[int, str]] = {}
    idx, title = 0, ""
    for node in content.descendants:
        if isinstance(node, Tag):
            if node.name in HEADING_TAGS:
                idx += 1
                title = _text(node)
            section_of[id(node)] = (idx, title)

    cards: dict[int, _Card | None] = {}
    order = 0
    for node in list(content.descendants):
        if not isinstance(node, NavigableString):
            continue
        if not DATE_EXPR_RE.search(str(node)):
            continue
        el = node.parent
        if el is None or el is content:
            continue
        if any(p.name in HEADING_TAGS for p in [el, *el.parents] if isinstance(p, Tag)):
            continue
        # секцията е тази, в която стои самата дата (картата може да обхваща и заглавието си)
        sec = section_of.get(id(el), (0, ""))
        # нагоре, докато в елемента има точно една дата и още прилича на карта
        while el.parent is not None and el.parent is not content:
            parent_text = _text(el.parent)
            if _count_dates(parent_text) != 1 or len(parent_text) > MAX_CARD_TEXT:
                break
            el = el.parent
        if id(el) in cards:
            continue
        cards[id(el)] = None  # елементът е обработен
        text = _text(el)
        matches = [m for m in DATE_EXPR_RE.finditer(text) if parse_date_expr(m)]
        multi = len(matches) != 1
        if len(text) > (2 * MAX_CARD_TEXT if multi else MAX_CARD_TEXT):
            continue  # дата насред дълъг абзац – не е карта
        if not multi and PROGRAM_DAY_RE.search(text):
            continue
        for m in matches:
            if _NOT_A_DEPARTURE_RE.search(text[:m.start()]):
                continue
            parsed = parse_date_expr(m)
            order += 1
            cards[-order] = _Card(el=el, text=m.group(0) if multi else text, start=parsed[0], end=parsed[1],
                                  section=sec[0], section_title=sec[1], order=order, multi=multi)

    out = sorted((c for c in cards.values() if c is not None), key=lambda c: c.order)
    for card in out:
        _annotate_group(card, content)
    return out


def _annotate_group(card: _Card, content: Tag) -> None:
    """Вариант („КЪС ВАРИАНТ“), обща цена на групата и заглавен ред на таблицата."""
    el = card.el
    branch = el
    for anc in el.parents:
        if anc is content or not isinstance(anc, Tag):
            break
        if anc.name == "table" and not card.table_header:
            first = anc.find("tr")
            if first is not None and _count_dates(_text(first)) == 0:
                card.table_header = _text(first)
        siblings = [c for c in anc.children if isinstance(c, Tag)]
        date_free = [c for c in siblings if c is not branch and _count_dates(_text(c)) == 0]
        if not card.variant:
            before = []
            for c in siblings:
                if c is branch:
                    break
                before.append(c)
            for c in reversed(before):
                t = _text(c)
                if t and len(t) <= 70 and VARIANT_RE.search(t) and _count_dates(t) == 0:
                    card.variant = t.strip(" :•●·-–")
                    break
        if not card.group_text and len(siblings) > 1 and any(c is not branch and _count_dates(_text(c)) for c in siblings):
            # групата: няколко карти + (по избор) общ ред с цената
            texts = [_text(c) for c in date_free if c.name not in HEADING_TAGS]
            card.group_text = " | ".join(t for t in texts if t and len(t) <= 60 and find_prices(t))
        if card.variant and card.group_text:
            break
        branch = anc


_FROM_CITY_RE = re.compile(r"(?:отпътуване\s+)?от\s+(София|Варна|Пловдив|Бургас)\b", re.I)


def _card_to_departure(card: _Card) -> Departure:
    if card.multi:
        lines = [card.text]
    else:
        lines = _own_lines(card.el)
        if len(_clean(" ".join(lines))) < len(card.text) // 2:
            lines = [card.text]
    joined = " | ".join(lines)
    without_dates = DATE_EXPR_RE.sub(" | ", joined)

    if card.multi:
        # „10.10 и 15.10.2027 – мъж за комбинация“: не е ясно за коя дата е, важи за всички в реда
        combo, combo_text = parse_combo(_text(card.el), allow_any=False)
    else:
        combo, combo_text = parse_combo(without_dates)
    seats, available, seats_text = parse_seats(without_dates)
    price, currency = pick_price(without_dates)

    name_parts = [card.variant] if card.variant else []
    city = _FROM_CITY_RE.search(without_dates)
    if city:
        name_parts.append(f"от {city.group(1).capitalize()}")

    # етикети: каквото остане от картата след датата, местата, цената и комбинацията
    badges: list[str] = []
    rest = without_dates
    for rx in (*COMBO_RES, COMBO_ANY_RE, STATUS_RE, PRICE_RE, _FROM_CITY_RE):
        rest = rx.sub(" | ", rest)
    for piece in re.split(r"[|•●·→]+", rest):
        piece = _clean(piece).strip(" :;,.-–—/")
        if not piece or len(piece) > 45 or not re.search(r"[A-Za-zА-Яа-я]{3}", piece):
            continue
        letters = re.sub(r"[^A-Za-zА-Яа-я]", "", piece)
        if not (BADGE_WORDS_RE.search(piece) or (letters.isupper() and len(piece) <= 30)):
            continue
        if DATES_HEADING_RE.match(piece) or VARIANT_RE.search(piece):
            continue
        if piece.upper() not in (b.upper() for b in badges):
            badges.append(piece)
    badges = badges[:4]

    start_iso = card.start.isoformat()
    end_iso = card.end.isoformat() if card.end else None
    name = ", ".join(name_parts)
    action = "НЯМА МЕСТА" if available is False else ("ИМА МЕСТА" if available else "—")
    return Departure(
        key=make_key(start_iso, end_iso, name), start_date=start_iso, end_date=end_iso or start_iso, name=name,
        price=price, currency=currency, action=action, heading=_clean(joined.replace("|", "·"))[:300],
        seats=seats, seats_text=seats_text, available=available, combo=combo, combo_text=combo_text,
        badges=badges, has_end=card.end is not None,
    )


def _section_tier(card: _Card) -> int:
    """1 = секция с дати („ДАТИ:“, „Дати и цени“, таблица с колона „Дати“);
    2 = въпрос за датите във „Въпроси и отговори“ (ползва се, само ако няма друго); 0 = не е секция с дати."""
    title = card.section_title
    if card.table_header and DATES_HEADING_RE.search(card.table_header):
        return 1
    if title and DATES_HEADING_RE.search(title):
        return 2 if title.rstrip().endswith("?") else 1
    if not card.multi and re.search(r"\bдат[аи]\w*[^.?!]*\?", card.text, re.I):
        return 2
    return 0


def _merge(into: Departure, other: Departure) -> None:
    """Допълва липсващото в `into` с данни от същата дата в друга секция."""
    if into.price is None and other.price is not None:
        into.price, into.currency = other.price, other.currency
    if into.available is None and other.available is not None:
        into.available, into.seats, into.seats_text, into.action = (other.available, other.seats, other.seats_text,
                                                                    other.action)
    if not into.combo and other.combo:
        into.combo, into.combo_text = other.combo, other.combo_text
    if not into.has_end and other.has_end:
        into.end_date, into.has_end = other.end_date, True


def _same_departure(a: Departure, b: Departure) -> bool:
    if a.start_date != b.start_date:
        return False
    if a.has_end and b.has_end and a.end_date != b.end_date:
        return False
    return True


def parse_departures(content: Tag, *, today: date | None = None) -> list[Departure]:
    today = today or date.today()
    cards = [c for c in _find_cards(content) if c.start >= today]
    tiers = {id(c): _section_tier(c) for c in cards}

    # първата секция с дати на страницата; въпросите за датите – само ако няма друга
    primary = None
    for tier in (1, 2):
        sections = sorted({c.section for c in cards if tiers[id(c)] == tier})
        if sections:
            primary = sections[0]
            break

    result: list[Departure] = []
    seen: set[str] = set()
    for card in cards:
        if primary is None or card.section != primary or not tiers[id(card)]:
            continue
        dep = _card_to_departure(card)
        # обща цена за групата („15 дни / 13 нощувки · 3240 €“ под картите на варианта)
        if dep.price is None and card.group_text:
            dep.price, dep.currency = pick_price(card.group_text)
        if dep.key in seen:
            # същата дата два пъти в една секция – различни групи (напр. друга цена)
            n = 2
            while f"{dep.key}_{n}" in seen:
                n += 1
            dep.key = f"{dep.key}_{n}"
            dep.name = (dep.name + f" #{n}").strip()
        seen.add(dep.key)
        result.append(dep)

    # останалите секции само допълват намерените дати (цена, наличност);
    # нова дата оттам се взима единствено ако носи бележка за комбинация
    for card in cards:
        if primary is not None and card.section == primary and tiers[id(card)]:
            continue
        dep = _card_to_departure(card)
        if not tiers[id(card)] and not dep.combo:
            continue
        matches = [d for d in result if _same_departure(d, dep)]
        if matches and dep.name:
            named = [d for d in matches if normalize_name(d.name) == normalize_name(dep.name)]
            matches = named or matches
        if len(matches) == 1:
            _merge(matches[0], dep)
        elif matches:
            # няколко групи на същата дата и не е ясно за коя е редът – пренася се само комбинацията
            if dep.combo:
                for d in matches:
                    if not d.combo:
                        d.combo, d.combo_text = dep.combo, dep.combo_text
        elif dep.combo and dep.key not in seen:
            dep.in_grid = False
            seen.add(dep.key)
            result.append(dep)

    result.sort(key=lambda d: (d.start_date, d.end_date, d.name))
    return result


def _page_note(content: Tag, departures: list[Departure]) -> Departure | None:
    """Бележка „мъж/жена за комбинация“ извън картите с дати – пази се като ред без дата."""
    # намираме най-малкия елемент с бележка, който няма дата в себе си
    for el in content.find_all(True):
        if el.name in HEADING_TAGS or any(isinstance(c, Tag) and c.name in BLOCK_TAGS for c in el.children):
            continue
        text = _text(el)
        if not text or len(text) > 400 or _count_dates(text):
            continue
        combo, combo_text = parse_combo(text, allow_any=False)
        if not combo:
            continue
        # бележката е част от карта с дата? тогава вече е отчетена
        parent_has_date = False
        for anc in el.parents:
            if anc is content:
                break
            t = _text(anc)
            if len(t) > MAX_CARD_TEXT:
                break
            if _count_dates(t) == 1:
                parent_has_date = True
                break
        if parent_has_date:
            continue
        return Departure(key=PAGE_NOTE_KEY, start_date="", end_date="", name="", price=None,
                         currency="EUR", action="—", heading=text[:300], combo=combo, combo_text=_clean(text)[:160],
                         in_grid=False, has_end=False)
    return None


def parse_travel(html: str, url: str | None = None, *, today: date | None = None) -> TravelPage:
    soup = BeautifulSoup(html, "html.parser")

    title = None
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = _clean(og["content"])
    elif soup.title and soup.title.string:
        title = _clean(soup.title.string)
    if title:
        title = re.split(r"\s*\|\s*Travel\s*with\s*us.*$", title, flags=re.I)[0].strip()
        title = re.sub(r"^Екскурзия\s+(?:(?:до|в|из)\s+)?", "", title).strip() or title
        title = title[:1].upper() + title[1:]

    image = None
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        image = og_img["content"].strip()
    desc = None
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = _clean(og_desc["content"])

    content = soup.select_one(".single_tour_content")
    if content is None:
        raise ParseError("На страницата няма описание на екскурзия (single_tour_content) – "
                         "това не прилича на страница от travelwithus.bg/tour/.")

    price_from = None
    price_el = soup.select_one(".single_tour_price")
    if price_el is not None:
        price_from, _cur = pick_price(_text(price_el))

    body_cls = " ".join(soup.body.get("class", [])) if soup.body else ""
    post = re.search(r"postid-(\d+)", body_cls)
    post_id = post.group(1) if post else None

    _strip_noise(content)

    departures = parse_departures(content, today=today)
    note = _page_note(content, departures)
    if note:
        departures.append(note)

    for dep in departures:
        dep.post_id = post_id
        if dep.price is None and price_from is not None and dep.start_date:
            dep.price, dep.currency, dep.price_from_page = price_from, "EUR", True

    return TravelPage(title=title, image=image, description=desc, departures=departures,
                      price_from=price_from)
