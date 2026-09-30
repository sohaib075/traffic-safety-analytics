from roadguard import nlq
from roadguard.analytics import risk_score


def test_parse_serious_evening_window():
    p = nlq.parse("Serious events between 5 PM and 8 PM")
    assert p["severities"] == ["high", "medium"]
    assert (p["hour_from"], p["hour_to"]) == (17, 20)
    assert p["types"] is None


def test_parse_types_and_period():
    p = nlq.parse("wrong-way and red light events this evening")
    assert set(p["types"]) == {"wrong_way", "red_light"}
    assert (p["hour_from"], p["hour_to"]) == (17, 21)


def test_parse_shared_ampm():
    p = nlq.parse("near misses between 7 and 9 am")
    assert p["types"] == ["near_miss"] and (p["hour_from"], p["hour_to"]) == (7, 9)


def test_risk_score_levels():
    low = risk_score({}, 1000)
    assert low["level"] == "LOW" and low["score"] == 0
    high = risk_score({"near_miss": {"high": 10}, "ped_conflict": {"medium": 5}}, 1000)
    # 10*5*2 + 5*6*1 = 130 points per 1000 vehicles
    assert high["score"] == 130 and high["level"] == "CRITICAL"
    # minimum denominator protects quiet periods
    assert risk_score({"red_light": {"medium": 1}}, 10)["denominator"] == 200
