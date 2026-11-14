"""Четецът върху записани страници от travelwithus.bg (tests/fixtures) и върху малки примери."""
from datetime import date

import pytest

from tracker.parser import (PAGE_NOTE_KEY, ParseError, find_prices, is_last_seats, parse_combo, parse_seats,
                            parse_travel)

TODAY = date(2026, 11, 14)   # денят, в който са записани страниците


def page(fixture_html, name):
    return parse_travel(fixture_html(name), today=TODAY)


def by_start(p, start, name=None):
    found = [d for d in p.departures if d.start_date == start and (name is None or d.name == name)]
    assert len(found) == 1, found
    return found[0]


# ---- записани страници -------------------------------------------------------

def test_single_card_with_status(fixture_html):
    p = page(fixture_html, "gruzia")
    assert p.title == "Армения и Грузия – великия Кавказ"
    assert p.price_from == 1470
    assert p.image and p.image.startswith("https://")
    assert len(p.departures) == 1
    d = p.departures[0]
    assert (d.start_date, d.end_date, d.has_end) == ("2027-05-22", "2027-05-30", True)
    assert d.available is True and d.seats is None and d.seats_text == "има места"
    assert d.combo is None
    # на картата няма цена – ползва се общата „от … €“ на екскурзията
    assert d.price == 1470 and d.price_from_page is True
    assert d.key == "2027-05-22_2027-05-30" and d.post_id == "12446"


def test_combo_note_in_date_card(fixture_html):
    p = page(fixture_html, "nepal-butan-tour")
    assert len(p.departures) == 1
    d = p.departures[0]
    assert d.start_date == "2027-05-01" and d.has_end is False and d.end_date == "2027-05-01"
    assert d.combo == "жена" and d.combo_text == "жена за комбинация"
    assert d.available is True


def test_combo_note_after_status_on_same_line(fixture_html):
    p = page(fixture_html, "ekskurzia-brazil-argentina-patagonia")
    assert len(p.departures) == 8
    d = by_start(p, "2027-10-10")
    assert d.combo == "жена" and d.available is True
    assert [x.start_date for x in p.departures if x.combo] == ["2027-10-10"]
    sold = by_start(p, "2027-01-24")
    assert sold.available is False and sold.seats == 0 and sold.badges == ["КАРНАВАЛ В РИО"]
    # сбъркана година в края на периода („07.11.2027 – 26.11.2026“) се оправя
    assert by_start(p, "2027-11-07").end_date == "2027-11-26"
    # цените в акордеона „Цени“ са по варианти, не по дати – остава общата цена
    assert all(x.price == 3145 and x.price_from_page for x in p.departures)


def test_short_ranges_seat_counts_and_prices(fixture_html):
    p = page(fixture_html, "brazilia-karnaval-rio-argentina-urugvai")
    assert [(d.start_date, d.end_date) for d in p.departures] == [
        ("2027-01-30", "2027-02-12"), ("2027-02-02", "2027-02-15"),
        ("2027-02-05", "2027-02-17"), ("2027-03-21", "2027-04-03")]
    one = by_start(p, "2027-02-05")
    assert one.seats == 1 and one.available is True and one.price == 4090 and not one.price_from_page
    two = by_start(p, "2027-03-21")
    assert two.seats == 2 and two.price == 3890
    # картата казва „няма места“, таблицата по-долу само допълва цената
    first = by_start(p, "2027-01-30")
    assert first.available is False and first.price == 4090
    # картите с дати са с предимство пред таблицата по-долу („Има места“ за 02.02)
    assert by_start(p, "2027-02-02").available is False


def test_variants_with_group_price(fixture_html):
    p = page(fixture_html, "costa-rika-panama")
    assert len(p.departures) == 6
    short = by_start(p, "2027-03-14", "КРАТЪК ВАРИАНТ")
    long_ = by_start(p, "2027-03-14", "ДЪЛЪГ ВАРИАНТ")
    assert (short.end_date, short.price) == ("2027-03-28", 3240)
    assert (long_.end_date, long_.price) == ("2027-04-02", 3890)
    assert short.seats_text == "последни места" and short.available is True and short.seats is None
    assert by_start(p, "2027-01-10", "КРАТЪК ВАРИАНТ").available is False


def test_variants_in_nested_tables(fixture_html):
    p = page(fixture_html, "agrentina-tour-patagonia-ushuaia")
    assert len(p.departures) == 16
    assert sum(d.name == "КЪС ВАРИАНТ" for d in p.departures) == 8
    assert sum(d.name == "ДЪЛЪГ ВАРИАНТ" for d in p.departures) == 8
    assert by_start(p, "2027-01-15").name == "КЪС ВАРИАНТ"
    assert all(not d.has_end and d.available is None for d in p.departures)


def test_same_date_from_two_cities(fixture_html):
    p = page(fixture_html, "sry-lanka")
    assert len(p.departures) == 19
    sofia = by_start(p, "2027-01-22", "от София")
    varna = by_start(p, "2027-01-22", "от Варна")
    assert sofia.price == 1531.5 and sofia.seats_text == "последни места"
    assert varna.price == 1641 and varna.available is None
    assert sofia.key != varna.key


def test_struck_through_old_price_is_ignored(fixture_html):
    p = page(fixture_html, "nepal-mustang-butan")
    assert len(p.departures) == 6
    assert all(d.price == 4990 and not d.price_from_page for d in p.departures)


def test_cards_first_table_fills_missing_prices(fixture_html):
    p = page(fixture_html, "singapore-malaysia-java-bali")
    assert len(p.departures) == 9
    assert by_start(p, "2027-02-17").badges == ["ОФОРМЕНА ГРУПА"]
    assert by_start(p, "2027-09-10").price == 3308


def test_program_days_are_not_departures(fixture_html):
    # в програмата по дни има „2 ДЕН … 05.12.2026“ – това не са дати на тръгване
    p = page(fixture_html, "bali")
    assert [(d.start_date, d.end_date) for d in p.departures] == [("2026-12-04", "2026-12-17")]
    assert p.departures[0].seats_text == "ограничени места"


def test_no_upcoming_dates(fixture_html):
    # „Дати: очаквайте нови дати“ + стара дата в таблицата с цени
    assert page(fixture_html, "india-nepal-butan").departures == []
    # само минали дати и срокове за плащане („до 31.05.2026“)
    assert page(fixture_html, "pakistan-tour").departures == []


def test_faq_dates_only_when_nothing_else(fixture_html):
    p = page(fixture_html, "ekskurzia-sri-lanka-madivi")
    assert [d.start_date for d in p.departures] == ["2026-11-15"]


def test_past_dates_are_dropped(fixture_html):
    p = parse_travel(fixture_html("gruzia"), today=date(2027, 6, 1))
    assert p.departures == []


# ---- малки примери -----------------------------------------------------------

def html(content: str, price: str = "от € 2000") -> str:
    return (f'<html><head><meta property="og:title" content="Екскурзия до Тест | Travel With Us"></head>'
            f'<body class="single-tour postid-1"><div class="single_tour_price">{price}</div>'
            f'<div class="single_tour_content">{content}</div></body></html>')


@pytest.mark.parametrize("note, expected", [
    ("● мъж за комбинация", "мъж"),
    ("● Мъж за комбинация", "мъж"),
    ("ИМА МЕСТА • Mъж за комбинация", "мъж"),          # латинско M – среща се на сайта
    ("търсим мъж за комбинация в двойна стая", "мъж"),
    ("възможност за комбинация с мъж", "мъж"),
    ("● жена за комбинация", "жена"),
    ("търси се дама за комбинация", "жена"),
    ("мъж или жена за комбинация", "any"),
    ("има място за комбинация", "any"),
])
def test_combo_wordings_in_card(note, expected):
    p = parse_travel(html(f"<h3>ДАТИ:</h3><div><div><div>10.10.2027 – 28.10.2027</div><div>{note}</div></div>"
                          f"<div><div>15.10.2027 – 02.11.2027</div><div>има места</div></div></div>"), today=TODAY)
    assert [d.combo for d in p.departures] == [expected, None]


def test_combo_requires_gender_outside_cards():
    assert parse_combo("чудесна комбинация от природа и култура") == (None, None)
    assert parse_combo("фирмата не поема ангажимент да осигури второ лице за комбинация", allow_any=False) == (None, None)
    assert parse_combo("Търсим мъж за комбинация!", allow_any=False)[0] == "мъж"


def test_combo_note_without_date_becomes_page_note():
    p = parse_travel(html("<h3>ДАТИ:</h3><div><div><div>10.10.2027 – 28.10.2027</div><div>има места</div></div>"
                          "<div><div>15.10.2027 – 02.11.2027</div><div>има места</div></div></div>"
                          "<p><strong>Търсим мъж за комбинация в двойна стая!</strong></p>"
                          "<p>Туристът се записва сам, фирмата не осигурява второ лице за комбинация.</p>"),
                     today=TODAY)
    assert [d.combo for d in p.departures] == [None, None, "мъж"]
    note = p.departures[-1]
    assert note.key == PAGE_NOTE_KEY and note.start_date == "" and "Търсим мъж" in note.combo_text


def test_combo_note_with_date_outside_dates_section_is_attached():
    p = parse_travel(html("<h3>ДАТИ:</h3><div><div><div>10.10.2027 – 28.10.2027</div><div>има места</div></div>"
                          "<div><div>15.10.2027 – 02.11.2027</div><div>има места</div></div></div>"
                          "<h3>Важно</h3><p>За 15.10.2027 търсим мъж за комбинация.</p>"), today=TODAY)
    assert [(d.start_date, d.combo) for d in p.departures] == [("2027-10-10", None), ("2027-10-15", "мъж")]


def test_several_dates_in_one_line_share_the_note():
    p = parse_travel(html("<h3>Дати</h3><p>12.03.2027 • 03.09.2027 – мъж за комбинация</p>"), today=TODAY)
    assert [(d.start_date, d.combo) for d in p.departures] == [("2027-03-12", "мъж"), ("2027-09-03", "мъж")]


def test_deadlines_are_not_departures():
    p = parse_travel(html("<h3>Дати и цени</h3><p>Ранни записвания до 31.01.2027</p>"
                          "<div><div>20.02.2027</div><div>има места</div></div>"), today=TODAY)
    assert [d.start_date for d in p.departures] == ["2027-02-20"]


def test_range_over_new_year():
    p = parse_travel(html("<h3>Дати</h3><div><div>28.12 – 08.01.2028</div><div>НЯМА МЕСТА</div></div>"), today=TODAY)
    d = p.departures[0]
    assert (d.start_date, d.end_date, d.available, d.seats) == ("2027-12-28", "2028-01-08", False, 0)


def test_range_with_day_only_start():
    p = parse_travel(html("<h3>Дати</h3><div><div>17 – 25.05.2027</div><div>3359 € · има места</div></div>"), today=TODAY)
    d = p.departures[0]
    assert (d.start_date, d.end_date, d.price) == ("2027-05-17", "2027-05-25", 3359)


def test_not_a_tour_page():
    with pytest.raises(ParseError):
        parse_travel("<html><body><h1>Блог</h1></body></html>")


def test_parse_seats():
    assert parse_seats("● НЯМА МЕСТА") == (0, False, "няма места")
    assert parse_seats("● ПОСЛЕДНО 1 МЯСТО") == (1, True, "последно 1 място")
    assert parse_seats("● ПОСЛЕДНИ 2 МЕСТА") == (2, True, "последни 2 места")
    assert parse_seats("●ПОСЛЕДНИ места") == (None, True, "последни места")
    assert parse_seats("ограничени места") == (None, True, "ограничени места")
    assert parse_seats("• има места") == (None, True, "има места")
    assert parse_seats("3 свободни места") == (3, True, "3 свободни места")
    assert parse_seats("остават 2 места") == (2, True, "остават 2 места")
    assert parse_seats("очаквайте нови дати")[:2] == (None, None)
    assert parse_seats("15 дни / 13 нощувки") == (None, None, None)


def test_is_last_seats():
    assert is_last_seats(None, "последни места", 2)
    assert is_last_seats(None, "ограничени места", 2)
    assert is_last_seats(2, "последни 2 места", 2)
    assert not is_last_seats(5, "5 свободни места", 2)
    assert not is_last_seats(None, "има места", 2)
    assert not is_last_seats(0, "няма места", 2)


def test_find_prices():
    assert find_prices("3359 €") == [(3359.0, "EUR")]
    assert find_prices("1531,50€ от София") == [(1531.5, "EUR")]
    assert find_prices("4090.00 € 5140.00 €") == [(4090.0, "EUR"), (5140.0, "EUR")]
    assert find_prices("3 890 евро") == [(3890.0, "EUR")]
    assert find_prices("от € 3 259") == [(3259.0, "EUR")]
    assert find_prices("€3259 +442 евро / 864.48 лв.") == [(3259.0, "EUR"), (864.48, "BGN")]
    assert find_prices("15 дни / 13 нощувки") == []
