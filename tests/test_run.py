"""Цялостен цикъл: няколко проверки върху фикстурите с промени между тях."""
import json
import sqlite3
from datetime import date

import pytest

from tests.conftest import FakeFetcher
from tracker import main as tracker_main
from tracker.db import Database
from tracker.fetch import BlockedError, is_challenge

TODAY = date(2026, 11, 14)

URL_GE = "https://travelwithus.bg/tour/gruzia/"
URL_NP = "https://travelwithus.bg/tour/nepal-butan-tour/"
URL_BR = "https://travelwithus.bg/tour/brazilia-karnaval-rio-argentina-urugvai/"

CONFIG = f"""
settings:
  combination: мъж
  request_delay: 0
travels:
  - url: {URL_GE}
    name: Грузия
  - {URL_NP}
  - {URL_BR}
"""

CHALLENGE = ("<!DOCTYPE html><html><head><title>One moment, please...</title></head>"
             "<body><script>var q='wsidchk';</script></body></html>")


class SlackSpy:
    mode = "bot"

    def __init__(self):
        self.messages = []

    def send(self, text, blocks=None):
        self.messages.append((text, blocks))
        return True


@pytest.fixture
def env(tmp_path, monkeypatch, fixture_html):
    cfg = tmp_path / "travels.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    db_path = tmp_path / "travels.db"
    out = tmp_path / "summary.json"
    spy = SlackSpy()
    monkeypatch.setattr(tracker_main, "SlackNotifier", lambda: spy)
    monkeypatch.setenv("DASHBOARD_URL", "https://example.github.io/twu/")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)
    pages = {URL_GE: fixture_html("gruzia"), URL_NP: fixture_html("nepal-butan-tour"),
             URL_BR: fixture_html("brazilia-karnaval-rio-argentina-urugvai")}

    def run(pages_now, **kw):
        return tracker_main.run(cfg, db_path, out, dry_run=False, notify=True, fetcher=FakeFetcher(pages_now),
                                today=TODAY, **kw)
    return {"run": run, "pages": pages, "db": db_path, "out": out, "spy": spy, "cfg": cfg}


def blocks_text(msgs) -> str:
    return json.dumps([b for _, b in msgs], ensure_ascii=False)


def test_first_run_is_baseline_and_silent_without_matching_combo(env):
    code = env["run"](env["pages"])
    assert code == 0
    # Търси се мъж, а на страниците има само „жена за комбинация“ – няма известие;
    # „нови дати“ от първата проверка не заливат Slack.
    assert env["spy"].messages == []

    conn = sqlite3.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM departures").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 6
    kinds = dict(conn.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind").fetchall())
    assert kinds == {"new_departure": 6, "combo_appeared": 1}

    summary = json.loads(env["out"].read_text(encoding="utf-8"))
    assert summary["settings"]["combination"] == "мъж"
    assert len(summary["travels"]) == 3
    assert summary["highlights"]["combo_matches"] == []
    assert summary["highlights"]["other_combos"] == ["nepal-butan-tour/2027-05-01"]
    assert len(summary["highlights"]["last_seats"]) == 2      # Бразилия: 1 място и 2 места
    ge = next(t for t in summary["travels"] if t["slug"] == "gruzia")
    assert ge["name"] == "Грузия" and ge["title"].startswith("Армения и Грузия")
    assert next(t for t in summary["travels"] if t["slug"].startswith("brazilia"))["title"].startswith("Бразилия и Аржентина")
    assert ge["price_from"] == 1470 and ge["fail_streak"] == 0 and ge["last_ok"]
    d = ge["departures"][0]
    assert d["days"] == 9 and d["page_price"] is True and d["undated"] is False
    np_dep = next(t for t in summary["travels"] if t["slug"] == "nepal-butan-tour")["departures"][0]
    assert np_dep["days"] is None and np_dep["combo"] == "жена" and np_dep["combo_match"] is False


def test_first_run_alerts_on_matching_combo(env):
    pages = {**env["pages"], URL_NP: env["pages"][URL_NP].replace("жена за комбинация", "мъж за комбинация")}
    env["run"](pages)
    texts = [t for t, _ in env["spy"].messages]
    assert len(texts) == 1
    assert "мъж за комбинация" in texts[0] and "Непал и Бутан" in texts[0] and "01.05.2027" in texts[0]
    assert URL_NP in texts[0]
    assert "от 3 340 €" in texts[0]
    conn = sqlite3.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM events WHERE notified = 1").fetchone()[0] == 1


def test_second_run_without_changes_is_silent(env):
    env["run"](env["pages"])
    env["run"](env["pages"])
    assert env["spy"].messages == []
    conn = sqlite3.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 7  # нищо ново


def test_changes_between_runs(env):
    env["run"](env["pages"])
    env["spy"].messages.clear()
    first_run_events = sqlite3.connect(env["db"]).execute("SELECT MAX(id) FROM events").fetchone()[0]

    # 1) Непал: „жена за комбинация“ -> „Mъж за комбинация“ (с латинско M, както се среща на сайта)
    np_page = env["pages"][URL_NP].replace("● жена за комбинация", "● Mъж за комбинация")
    assert np_page != env["pages"][URL_NP]
    # 2) Грузия: „има места“ -> „последни места“, нова дата и по-ниска обща цена „от … €“
    ge = env["pages"][URL_GE]
    ge2 = ge.replace("• има места</div>\n</div>",
                     "• последни места</div>\n</div>\n<div>\n<div>02.10.2027 – 10.10.2027</div>\n"
                     "<div> • има места</div>\n</div>", 1).replace("от € 1470", "от € 1390")
    assert ge2 != ge and "02.10.2027" in ge2
    # 3) Бразилия: цената на картата 3890 -> 3790; датата 02.02 – 15.02 изчезва
    br = env["pages"][URL_BR]
    br2 = br.replace("<div>3890 €</div>", "<div>3790 €</div>").replace("<div>02.02 – 15.02.2027</div>",
                                                                       "<div>03.02 – 16.02.2027</div>")
    assert br2 != br
    pages = {URL_NP: np_page, URL_GE: ge2, URL_BR: br2}

    assert env["run"](pages) == 0
    msgs = env["spy"].messages
    alerts = [t for t, _ in msgs if "Търси се мъж за комбинация" in t]
    digests = [t for t, _ in msgs if t.startswith("📋")]
    assert len(alerts) == 1 and "Непал и Бутан" in alerts[0] and "01.05.2027" in alerts[0]
    assert len(digests) == 1 and len(msgs) == 2
    body = blocks_text(msgs)
    assert "преди пишеше „жена за комбинация“" in body
    assert "Последни места" in body and "последни места" in body      # Грузия
    assert "Нова дата" in body and "02.10 – 10.10.2027" in body        # Грузия
    assert "цената „от“ на екскурзията" in body and "1 390 €" in body  # Грузия, общата цена – един ред
    assert "3 790 €" in body                                           # Бразилия
    assert "03.02 – 16.02.2027" in body                                # Бразилия, нова дата

    conn = sqlite3.connect(env["db"])
    kinds = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM events WHERE id > ? GROUP BY kind", (first_run_events,)).fetchall())
    assert kinds == {"combo_appeared": 1, "price_change": 2, "seats_change": 1,
                     "new_departure": 2, "departure_gone": 1}
    gone = conn.execute("SELECT start_date FROM departures WHERE gone_since IS NOT NULL").fetchall()
    assert gone == [("2027-02-02",)]

    summary = json.loads(env["out"].read_text(encoding="utf-8"))
    assert summary["highlights"]["combo_matches"] == ["nepal-butan-tour/2027-05-01"]
    nepal = next(d for t in summary["travels"] for d in t["departures"] if d["id"] == "nepal-butan-tour/2027-05-01")
    assert nepal["combo"] == "мъж" and nepal["combo_match"] is True and len(nepal["history"]) == 2
    cheaper = next(d for t in summary["travels"] for d in t["departures"] if d["start"] == "2027-03-21")
    assert cheaper["price"] == 3790 and cheaper["price_first"] == 3890 and cheaper["price_changes"] == 1

    # трета проверка със същите страници – тишина
    env["spy"].messages.clear()
    env["run"](pages)
    assert env["spy"].messages == []


def test_page_note_without_date_alerts_once(env):
    env["run"](env["pages"])
    ge = env["pages"][URL_GE].replace("<h3>ДАТИ:</h3>", "<p>Търсим мъж за комбинация в двойна стая!</p>\n<h3>ДАТИ:</h3>")
    pages = {**env["pages"], URL_GE: ge}
    env["run"](pages)
    texts = [t for t, _ in env["spy"].messages]
    assert len(texts) == 1 and "мъж за комбинация" in texts[0] and "бележка без посочена дата" in texts[0]
    env["spy"].messages.clear()
    env["run"](pages)
    assert env["spy"].messages == []
    summary = json.loads(env["out"].read_text(encoding="utf-8"))
    note = next(d for t in summary["travels"] for d in t["departures"] if d["undated"])
    assert note["id"] in summary["highlights"]["combo_matches"]


def test_missing_page_is_reported_at_once(env):
    pages = dict(env["pages"])
    del pages[URL_NP]
    assert env["run"](pages) == 0  # останалите минаха
    errs = [t for t, _ in env["spy"].messages if t.startswith("⚠️")]
    assert len(errs) == 1 and "1 от 3" in errs[0]
    db = Database(env["db"])
    last = db.last_run()
    assert last["fail_count"] == 1 and "404" in last["errors"]
    db.close()


def test_bot_check_keeps_old_data_and_reports_only_when_it_persists(env):
    assert is_challenge(CHALLENGE)
    env["run"](env["pages"])
    blocked = {**env["pages"], URL_BR: BlockedError("Сайтът поиска проверка „не си робот“ вместо да покаже страницата.")}

    # 1-ви и 2-ри ден: тихо; датите на Бразилия си остават, не са „свалени“
    for streak in (1, 2):
        assert env["run"](blocked) == 0
        assert env["spy"].messages == []
        summary = json.loads(env["out"].read_text(encoding="utf-8"))
        br = next(t for t in summary["travels"] if t["slug"].startswith("brazilia"))
        assert br["fail_streak"] == streak and "не си робот" in br["last_error"]
        assert len(br["departures"]) == 4 and all(d["gone_since"] is None for d in br["departures"])
    # 3-ти пореден ден: едно съобщение
    env["run"](blocked)
    errs = [t for t, _ in env["spy"].messages]
    assert len(errs) == 1 and errs[0].startswith("⚠️")
    assert "3 поредни проверки" in blocks_text(env["spy"].messages)
    # 4-ти ден: пак тихо
    env["spy"].messages.clear()
    env["run"](blocked)
    assert env["spy"].messages == []
    # страницата пак се чете – броячът се нулира, няма фалшиви „нови дати“
    env["run"](env["pages"])
    assert env["spy"].messages == []
    summary = json.loads(env["out"].read_text(encoding="utf-8"))
    assert all(t["fail_streak"] == 0 for t in summary["travels"])
    conn = sqlite3.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'departure_gone'").fetchone()[0] == 0


def test_new_dates_on_a_tour_that_had_none_are_announced(env, fixture_html):
    empty = fixture_html("india-nepal-butan")
    env["run"]({**env["pages"], URL_NP: empty})
    assert env["spy"].messages == []
    env["run"](env["pages"])   # сега на същия линк има дата
    digests = [t for t, _ in env["spy"].messages if t.startswith("📋")]
    assert len(digests) == 1 and "Нова дата" in blocks_text(env["spy"].messages)


def test_passed_dates_are_not_reported_as_removed(env):
    env["run"](env["pages"])
    code = tracker_main.run(env["cfg"], env["db"], env["out"], dry_run=False, notify=True,
                            fetcher=FakeFetcher(env["pages"]), today=date(2027, 2, 10))
    assert code == 0 and env["spy"].messages == []
    conn = sqlite3.connect(env["db"])
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'departure_gone'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM departures WHERE gone_since IS NOT NULL").fetchone()[0] == 3


def test_all_fail_returns_1(env):
    assert env["run"]({}) == 1


def test_dry_run_writes_nothing(env):
    code = tracker_main.run(env["cfg"], env["db"], env["out"], dry_run=True, notify=True,
                            fetcher=FakeFetcher(env["pages"]), today=TODAY)
    assert code == 0
    assert not env["db"].exists() and not env["out"].exists()
    assert env["spy"].messages == []
