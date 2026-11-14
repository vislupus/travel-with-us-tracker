import sqlite3

from tracker.changes import (AVAILABLE_AGAIN, COMBO_APPEARED, COMBO_GONE, GROUP_CONFIRMED, NEW_DEPARTURE,
                             PRICE_CHANGE, SEATS_CHANGE, SOLD_OUT, combo_matches, detect_changes, wants_alert,
                             wants_digest)
from tracker.config import Settings
from tracker.parser import Departure


def dep(**kw) -> Departure:
    base = dict(key="k", start_date="2027-04-08", end_date="2027-04-22", name="", price=3930.0,
                currency="EUR", action="ИМА МЕСТА", heading="h", seats=None, seats_text="има места",
                available=True, combo=None, combo_text=None, badges=[])
    base.update(kw)
    return Departure(**base)


def row(**kw) -> sqlite3.Row:
    """Имитира ред от snapshots."""
    cols = dict(price=3930.0, currency="EUR", action="ИМА МЕСТА", seats=None, seats_text="има места",
                available=1, combo=None, combo_text=None, badges="[]")
    cols.update(kw)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    sel = ", ".join(f"? AS {k}" for k in cols)
    return conn.execute(f"SELECT {sel}", list(cols.values())).fetchone()


def kinds(changes):
    return [c.kind for c in changes]


def test_new_departure_without_combo():
    ch = detect_changes(None, dep(), is_new=True)
    assert kinds(ch) == [NEW_DEPARTURE]


def test_new_departure_with_combo_fires_alert():
    ch = detect_changes(None, dep(combo="мъж", combo_text="мъж за комбинация"), is_new=True)
    assert kinds(ch) == [NEW_DEPARTURE, COMBO_APPEARED]
    assert ch[1].detail["combo"] == "мъж"


def test_no_changes():
    assert detect_changes(row(), dep(), is_new=False) == []


def test_price_change():
    ch = detect_changes(row(price=3930.0), dep(price=3850.0), is_new=False)
    assert kinds(ch) == [PRICE_CHANGE]
    assert ch[0].detail["old"] == 3930.0 and ch[0].detail["new"] == 3850.0
    assert ch[0].detail["diff"] == -80.0 and ch[0].detail["pct"] == -2.0


def test_combo_appeared_and_gone():
    ch = detect_changes(row(combo=None), dep(combo="мъж"), is_new=False)
    assert kinds(ch) == [COMBO_APPEARED] and ch[0].detail["prev_combo"] is None
    ch = detect_changes(row(combo="мъж"), dep(combo=None), is_new=False)
    assert kinds(ch) == [COMBO_GONE] and ch[0].detail["prev_combo"] == "мъж"


def test_combo_gender_switch_counts_as_appeared():
    ch = detect_changes(row(combo="жена"), dep(combo="мъж"), is_new=False)
    assert kinds(ch) == [COMBO_APPEARED]
    assert ch[0].detail["prev_combo"] == "жена"


def test_sold_out_and_available_again():
    ch = detect_changes(row(available=1, seats=1, seats_text="последно 1 място"),
                        dep(available=False, seats=0, seats_text="няма места", action="НЯМА МЕСТА"), is_new=False)
    assert kinds(ch) == [SOLD_OUT]
    ch = detect_changes(row(available=0, seats=0, seats_text="няма места"),
                        dep(available=True, seats=None, seats_text="има места"), is_new=False)
    assert kinds(ch) == [AVAILABLE_AGAIN]


def test_seats_change():
    ch = detect_changes(row(seats=4, seats_text="4 свободни места"), dep(seats=1, seats_text="последно 1 място"), is_new=False)
    assert kinds(ch) == [SEATS_CHANGE]
    assert ch[0].detail["old"] == 4 and ch[0].detail["new"] == 1
    # „има места“ -> „последни места“ (без брой) също е промяна
    ch = detect_changes(row(seats=None, seats_text="има места"), dep(seats=None, seats_text="последни места"), is_new=False)
    assert kinds(ch) == [SEATS_CHANGE]
    assert ch[0].detail["old_text"] == "има места" and ch[0].detail["new_text"] == "последни места"
    # същият текст с други главни букви не е промяна
    assert detect_changes(row(seats_text="ИМА МЕСТА"), dep(seats_text="има места"), is_new=False) == []


def test_group_confirmed():
    ch = detect_changes(row(badges='["КАРНАВАЛ В РИО"]'), dep(badges=["ОФОРМЕНА ГРУПА"]), is_new=False)
    assert kinds(ch) == [GROUP_CONFIRMED]
    assert detect_changes(row(badges='["ОФОРМЕНА ГРУПА"]'), dep(badges=["ОФОРМЕНА ГРУПА"]), is_new=False) == []
    assert kinds(detect_changes(row(), dep(badges=["ПОТВЪРДЕНА ГРУПА"]), is_new=False)) == [GROUP_CONFIRMED]


def test_many_changes_at_once():
    ch = detect_changes(row(price=3930.0, combo=None, seats=4, seats_text="4 свободни места"),
                        dep(price=3990.0, combo="мъж", seats=1, seats_text="последно 1 място"), is_new=False)
    assert set(kinds(ch)) == {PRICE_CHANGE, COMBO_APPEARED, SEATS_CHANGE}


def test_combo_matches():
    assert combo_matches("мъж", "мъж")
    assert combo_matches("any", "мъж")        # без посочен пол може да е и мъж
    assert not combo_matches("жена", "мъж")
    assert combo_matches("жена", "any")
    assert not combo_matches(None, "мъж")


def test_alert_policy():
    s = Settings(combination="мъж")
    ch = detect_changes(row(), dep(combo="мъж"), is_new=False)[0]
    assert wants_alert(ch, s)
    ch = detect_changes(row(), dep(combo="жена"), is_new=False)[0]
    assert not wants_alert(ch, s)
    assert wants_alert(ch, Settings(combination="мъж", notify_any_combination=True))
    assert wants_alert(ch, Settings(combination="any"))
    ch = detect_changes(row(), dep(price=1.0), is_new=False)[0]
    assert not wants_alert(ch, s)


def test_digest_policy():
    s = Settings(combination="мъж", notify_last_seats=2)
    price = detect_changes(row(price=3930.0), dep(price=3850.0), is_new=False)[0]
    assert wants_digest(price, s, baseline=False)
    assert not wants_digest(price, s, baseline=True)
    assert not wants_digest(price, Settings(notify_price_changes=False), baseline=False)

    new = detect_changes(None, dep(), is_new=True)[0]
    assert wants_digest(new, s, baseline=False)
    assert not wants_digest(new, s, baseline=True)

    seats = detect_changes(row(seats=4, seats_text="4 свободни места"),
                           dep(seats=2, seats_text="последни 2 места"), is_new=False)[0]
    assert wants_digest(seats, s, baseline=False)
    seats = detect_changes(row(seats=2, seats_text="последни 2 места"),
                           dep(seats=1, seats_text="последно 1 място"), is_new=False)[0]
    assert not wants_digest(seats, s, baseline=False)  # вече беше под прага – не повтаряме
    seats = detect_changes(row(seats=6, seats_text="6 свободни места"),
                           dep(seats=5, seats_text="5 свободни места"), is_new=False)[0]
    assert not wants_digest(seats, s, baseline=False)
    # „има места“ -> „последни места“ (без брой) също е известие за последни места
    words = detect_changes(row(), dep(seats_text="последни места"), is_new=False)[0]
    assert wants_digest(words, s, baseline=False)
    assert not wants_digest(words, Settings(notify_last_seats=0), baseline=False)
    back = detect_changes(row(seats_text="последни места"), dep(seats_text="има места"), is_new=False)[0]
    assert not wants_digest(back, s, baseline=False)

    gone = detect_changes(row(combo="мъж"), dep(combo=None), is_new=False)[0]
    assert wants_digest(gone, s, baseline=False)
    gone = detect_changes(row(combo="жена"), dep(combo=None), is_new=False)[0]
    assert not wants_digest(gone, s, baseline=False)
