from datetime import UTC, date, datetime, time

from larder_core.ical import CalendarMeal, calendar

NOW = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


def meal(**kw: object) -> CalendarMeal:
    fields: dict[str, object] = {
        "on": date(2026, 10, 20),
        "slot": "dinner",
        "starts": time(19, 0),
        "minutes": 45,
        "title": "Dinner: Irish stew",
        "description": "650 kcal",
        "url": "https://mealwright.app/recipes/7/cook?servings=2",
    } | kw
    return CalendarMeal(**fields)  # type: ignore[arg-type]


def test_a_feed_with_one_floating_time_event() -> None:
    text = calendar("Mealwright meals", [meal()], now=NOW, domain="mealwright.app")
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-2:] == ["END:VCALENDAR", ""]
    assert "UID:2026-10-20-dinner@mealwright.app" in lines
    assert "DTSTART:20261020T190000" in lines  # floating: no Z, no TZID
    assert "DTEND:20261020T194500" in lines
    assert "DTSTAMP:20261020T093000Z" in lines
    assert "SUMMARY:Dinner: Irish stew" in lines
    assert "URL:https://mealwright.app/recipes/7/cook?servings=2" in lines
    assert "\n" not in text.replace("\r\n", "")  # CRLF only


def test_text_is_escaped() -> None:
    text = calendar(
        "x", [meal(title="Lunch: Fish, chips; peas", description="a\nb\\c")], now=NOW, domain="d"
    )
    assert "SUMMARY:Lunch: Fish\\, chips\\; peas" in text
    assert "DESCRIPTION:a\\nb\\\\c" in text


def test_long_lines_fold_at_75_octets_without_splitting_characters() -> None:
    description = "Ingredients: " + ", ".join(["crème fraîche"] * 20)
    text = calendar("x", [meal(description=description)], now=NOW, domain="d")
    lines = text.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    start = next(i for i, line in enumerate(lines) if line.startswith("DESCRIPTION:"))
    unfolded = lines[start] + "".join(
        line[1:] for line in lines[start + 1 :] if line.startswith(" ")
    )
    assert unfolded == "DESCRIPTION:" + description.replace(",", "\\,")
