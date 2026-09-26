"""Deterministic text signals: numbers, hype, material events, prices."""

from ai_api.verify import signals


def test_headline_numbers_missing_from_the_body():
    assert signals.headline_numbers(
        "Apple revenue soars 120% in blowout quarter",
        "Apple Inc. (AAPL) said revenue rose 12% to $85.1 billion.",
    ) == ["120%"]


def test_amounts_match_across_units():
    assert (
        signals.headline_numbers(
            "Apple reports Q3 revenue of $85.1B, up 12% from a year ago",
            "revenue reached $85.1 billion, up 12% from a year earlier",
        )
        == []
    )
    assert signals.headline_numbers(
        "Visa announces $4.5B buyback", "a $45 billion repurchase"
    ) == ["$4,500,000,000"]


def test_sensational_headlines():
    assert signals.sensational(
        "Apple stock set to EXPLODE after shock announcement"
    ) == ["set to EXPLODE", "shock", "EXPLODE"]
    assert signals.sensational("Stocks rally!") == ["!"]
    # Names the story uses in capitals aren't shouting.
    assert (
        signals.sensational(
            "NVIDIA raises its dividend", "NVIDIA Corporation (NVDA) said"
        )
        == []
    )
    assert signals.sensational("[SYNTHETIC] CEO names new CFO") == []


def test_material_events():
    assert signals.material_event(
        "The CEO resigned with immediate effect as regulators opened an "
        "inquiry."
    ) == ["resigned", "inquiry"]
    assert signals.material_event("Apple raises its dividend") == []


def test_price_moves():
    moves = signals.price_moves("Shares of Apple jumped 20% on Monday.")
    assert [(m.percent, m.down) for m in moves] == [(20.0, False)]
    assert signals.price_moves("The stock fell 3.5%")[0].down


def test_overlap_of_content_words():
    story = "Apple board approves breakup into three companies"
    assert signals.overlap(story, "Apple approves a breakup, three firms") > 0.5
    assert signals.overlap(story, "Microsoft earnings") == 0.0
