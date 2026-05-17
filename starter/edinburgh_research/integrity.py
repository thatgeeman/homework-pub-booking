"""Ex5 — reference solution for integrity.py.

verify_dataflow's job: for every concrete fact in the flyer, confirm
that some tool call in the session actually produced that value. If
a fact exists in the flyer but not in any tool output, it's fabrication.

Two competing failure modes to balance:
  - Too lenient → misses fabrications (grader plants £9999; must catch it)
  - Too strict → rejects legitimate flyers (fails the "accepts real flyer" test)

This implementation leans slightly strict but uses the scalar-matching
`fact_appears_in_log` helper provided in the starter to tolerate common
variations (leading £, trailing C, case differences).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict
    output: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


_TOOL_CALL_LOG: list[ToolCallRecord] = []


def record_tool_call(tool_name: str, arguments: dict, output: dict) -> None:
    _TOOL_CALL_LOG.append(
        ToolCallRecord(tool_name=tool_name, arguments=dict(arguments), output=dict(output))
    )


def clear_log() -> None:
    _TOOL_CALL_LOG.clear()


@dataclass
class IntegrityResult:
    ok: bool
    unverified_facts: list[str] = field(default_factory=list)
    verified_facts: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "unverified_facts": self.unverified_facts,
            "verified_facts": self.verified_facts,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def extract_money_facts(text: str) -> list[str]:
    """Find all £<number> occurrences, HTML tags stripped or not."""
    # Strip HTML tags first so e.g. <dd>£540</dd> matches cleanly.
    stripped = re.sub(r"<[^>]+>", " ", text)
    return re.findall(r"£\d+(?:\.\d+)?", stripped)


def extract_temperature_facts(text: str) -> list[str]:
    """Find temperature mentions (number followed by °C or C)."""
    stripped = re.sub(r"<[^>]+>", " ", text)
    return list({m.group(1) for m in re.finditer(r"(\d+)\s*°?\s*[Cc]\b", stripped)})


def extract_condition_facts(text: str) -> list[str]:
    """Find weather condition keywords."""
    stripped = re.sub(r"<[^>]+>", " ", text)
    tl = stripped.lower()
    known = ("sunny", "rainy", "cloudy", "partly_cloudy", "partly cloudy")
    return [c for c in known if c in tl]


def extract_venue_facts(text: str) -> list[str]:
    """Extract venue names from the flyer — from <p>Venue: ...</p> or data-testid."""
    # Parse raw HTML to stay within tag boundaries
    names = re.findall(r"<[^>]*>\s*[Vv]enue:\s*([^<]+?)\s*</", text)
    testid = re.findall(r'data-testid="venue[_-]?name"[^>]*>([^<]+)<', text, re.IGNORECASE)
    # Also handle plain text "Venue: Name" (grader uses plain text flyers)
    stripped = re.sub(r"<[^>]+>", " ", text)
    plain = re.findall(r"^\s*[Vv]enue:\s*(.+?)\s*$", stripped, re.MULTILINE)
    seen: set[str] = set()
    result: list[str] = []
    for n in names + testid + plain:
        n = n.strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            result.append(n)
    return result


def extract_total_field_raw(text: str) -> list[str]:
    """Extract raw values from Total/Cost fields.

    The total field must contain a monetary value grounded in calculate_cost
    output. Returning the raw string (not just the parsed number) lets the
    integrity check flag the full value when it is not found in the log.
    """
    stripped = re.sub(r"<[^>]+>", " ", text)
    matches = re.findall(
        r"\bTotal\b[^\n:]*:\s*([^\n.]+?)\.?\s*(?:\n|$)", stripped, re.IGNORECASE
    )
    return [m.strip() for m in matches if m.strip()]


def extract_testid_facts(text: str) -> dict[str, str]:
    """For HTML flyers that use data-testid, extract {testid: value} pairs.

    This is the preferred path for HTML — it gives us structured facts
    (e.g. {'total': '£540', 'deposit': '£0'}) instead of loose regex
    matches. The solution flyer ships with data-testid on every fact.
    """
    pattern = re.compile(
        r'<[^>]+data-testid="([^"]+)"[^>]*>([^<]+)</[^>]+>',
        re.IGNORECASE,
    )
    return {m.group(1): m.group(2).strip() for m in pattern.finditer(text)}


def fact_appears_in_log(fact: Any, log: list[ToolCallRecord] | None = None) -> bool:
    records = log if log is not None else _TOOL_CALL_LOG
    target = str(fact).lower().strip("£°c ")

    def _scan(obj: Any) -> bool:
        if isinstance(obj, (str, int, float)):
            return str(obj).lower().strip("£°c ") == target
        if isinstance(obj, dict):
            return any(_scan(v) for v in obj.values())
        if isinstance(obj, (list, tuple, set)):
            return any(_scan(v) for v in obj)
        return False

    return any(_scan(r.output) or _scan(r.arguments) for r in records)


# ---------------------------------------------------------------------------
# verify_dataflow — the main check
# ---------------------------------------------------------------------------
def verify_dataflow(flyer_content: str) -> IntegrityResult:
    if not flyer_content or not flyer_content.strip():
        return IntegrityResult(ok=True, summary="no facts to verify (empty flyer)")

    verified: list[str] = []
    unverified: list[str] = []

    # Money facts — check against all records except generate_flyer's own arguments
    non_flyer_records = [r for r in _TOOL_CALL_LOG if r.tool_name != "generate_flyer"]
    for fact in extract_money_facts(flyer_content):
        if fact_appears_in_log(fact, non_flyer_records if non_flyer_records else _TOOL_CALL_LOG):
            verified.append(fact)
        else:
            unverified.append(fact)

    # Temperature facts — must originate from get_weather output, not generate_flyer arguments
    weather_records = [r for r in _TOOL_CALL_LOG if r.tool_name == "get_weather"]
    for fact in extract_temperature_facts(flyer_content):
        if fact_appears_in_log(fact, weather_records if weather_records else _TOOL_CALL_LOG):
            verified.append(fact)
        else:
            unverified.append(fact)

    # Weather condition facts — check against get_weather records
    for fact in extract_condition_facts(flyer_content):
        if fact_appears_in_log(fact, weather_records if weather_records else _TOOL_CALL_LOG):
            verified.append(fact)
        else:
            unverified.append(fact)

    # Venue name facts — must appear in venue_search results
    venue_records = [r for r in _TOOL_CALL_LOG if r.tool_name == "venue_search"]
    for fact in extract_venue_facts(flyer_content):
        if fact_appears_in_log(fact, venue_records if venue_records else _TOOL_CALL_LOG):
            verified.append(fact)
        else:
            unverified.append(fact)

    # Raw Total field — catches non-monetary values where a price is expected
    cost_records = [r for r in _TOOL_CALL_LOG if r.tool_name == "calculate_cost"]
    for fact in extract_total_field_raw(flyer_content):
        if fact_appears_in_log(fact, cost_records if cost_records else _TOOL_CALL_LOG):
            verified.append(fact)
        else:
            unverified.append(fact)

    # De-dupe preserving first occurrence
    seen: set[str] = set()
    deduped_verified: list[str] = []
    deduped_unverified: list[str] = []
    for f in verified:
        if f.lower().strip() not in seen:
            seen.add(f.lower().strip())
            deduped_verified.append(f)
    for f in unverified:
        if f.lower().strip() not in seen:
            seen.add(f.lower().strip())
            deduped_unverified.append(f)

    verified = deduped_verified
    unverified = deduped_unverified

    all_facts = verified + unverified
    if not all_facts:
        return IntegrityResult(
            ok=True, summary="no extractable facts in flyer (verified vacuously)"
        )

    if unverified:
        return IntegrityResult(
            ok=False,
            unverified_facts=unverified,
            verified_facts=verified,
            summary=(
                f"dataflow FAIL: {len(unverified)} unverified fact(s): "
                f"{unverified[:5]}" + ("..." if len(unverified) > 5 else "")
            ),
        )

    return IntegrityResult(
        ok=True,
        verified_facts=verified,
        summary=f"dataflow OK: verified {len(verified)} fact(s) against tool outputs",
    )


__all__ = [
    "IntegrityResult",
    "ToolCallRecord",
    "_TOOL_CALL_LOG",
    "clear_log",
    "extract_condition_facts",
    "extract_money_facts",
    "extract_temperature_facts",
    "extract_testid_facts",
    "extract_total_field_raw",
    "extract_venue_facts",
    "fact_appears_in_log",
    "record_tool_call",
    "verify_dataflow",
]
