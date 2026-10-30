"""A meal-plan calendar feed (iCalendar, RFC 5545), written by hand: no dependency needed for a
handful of events.

Times are "floating" (no time zone): 19:00 shows as 19:00 wherever the calendar is, which is
what a meal time means. Each event's UID is its date and meal, so when the plan changes the
calendar replaces the event instead of adding a second one.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

__all__ = ["CalendarMeal", "calendar"]

PRODID = "-//Mealwright//Meal plan//EN"


@dataclass(frozen=True, slots=True)
class CalendarMeal:
    on: date
    slot: str  # larder_core.meals.Slot
    starts: time
    minutes: int
    title: str  # "Dinner: Irish stew"
    description: str
    url: str | None = None


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines over 75 octets continue on the next line after a space (RFC 5545 3.1)."""
    out: list[str] = []
    current = ""
    for char in line:
        limit = 75 if not out else 74  # continuation lines start with a space
        if len((current + char).encode()) > limit:
            out.append(current)
            current = char
        else:
            current += char
    out.append(current)
    return "\r\n ".join(out)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S")


def calendar(name: str, meals: Iterable[CalendarMeal], *, now: datetime, domain: str) -> str:
    """The whole feed as text (CRLF line ends). `now` is UTC; `domain` makes UIDs unique."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for meal in meals:
        start = datetime.combine(meal.on, meal.starts)
        end = start + timedelta(minutes=meal.minutes)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{meal.on.isoformat()}-{meal.slot}@{domain}",
            f"DTSTAMP:{_stamp(now)}Z",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            f"SUMMARY:{_escape(meal.title)}",
            f"DESCRIPTION:{_escape(meal.description)}",
            *([f"URL:{meal.url}"] if meal.url else []),
            "TRANSP:TRANSPARENT",  # a meal doesn't make you busy
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)
