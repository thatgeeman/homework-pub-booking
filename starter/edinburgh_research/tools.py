"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolError, ToolRegistry, ToolResult, _RegisteredTool

from starter.edinburgh_research.integrity import _TOOL_CALL_LOG, record_tool_call

_SAMPLE_DATA = Path(__file__).parent / "sample_data"


def json_loader(path: Path) -> dict:
    """Helper to load a JSON fixture, raising a clear ToolError if missing."""
    if not path.is_file():
        raise ToolError("SA_TOOL_DEPENDENCY_MISSING", f"Missing fixture: {path}")
    with open(path) as f:
        return json.load(f)


def llm_spiralling(tool_name: str, threshold: int = 3) -> bool:
    """Helper to detect if the LLM is spiralling by calling a tool too many times."""
    # should be called after record_tool_call, so the current call is included in the log
    print(f"Last _TOOL_CALL_LOG entry: {_TOOL_CALL_LOG[-1] if _TOOL_CALL_LOG else 'empty log'}")
    count = sum(1 for r in _TOOL_CALL_LOG if r.tool_name == tool_name)
    return count > threshold


def venue_spiral_message() -> bool:
    """
    Helper to provide a useful message when the LLM is spiralling on venue_search,
    by listing the venues that have already been returned across all previous calls in the log.
    """
    valid_venues = {}
    for record in _TOOL_CALL_LOG:
        if record.tool_name == "venue_search":
            if record.output.get("count", 0) > 0 and record.output.get("results"):
                for venue in record.output["results"]:
                    venue_id = venue.get("id")
                    if venue_id:
                        valid_venues[venue_id] = valid_venues.get(venue_id, 0) + 1
    useful_message = (
        f"""
    The following venues were already returned by `venue_search` as valid venues calls
    which should be used instead of calling `venue_search` again:
    The number in brackets indicates how many times each venue was returned across all
    `venue_search` calls in the log.
    {", ".join(f"{venue} ({count})" for venue, count in valid_venues.items())}.
    """
        if valid_venues
        else "No valid venues were returned by previous venue_search calls in the log."
    )
    print(useful_message)
    return useful_message


def substring_match(haystack: str, needle: str) -> bool:
    """Case-insensitive substring match, even by partial words (e.g. 'hay' matches 'Haymarket')."""
    if len(needle) > len(haystack) and haystack.lower() in needle.lower():
        print(f"substring_match: '{needle}' in '{haystack}' -> True (partial match by word)")
        return True
    result = needle.lower() in haystack.lower()
    print(f"substring_match: '{needle}' in '{haystack}' -> {result}")
    return result


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party.

    Args:
      near: str (e.g. "Haymarket")
      party_size: int
      budget_max_gbp: int, maximum total budget in GBP (default 1000)

    Note:

    Reads sample_data/venues.json. Filters by:
      * open_now == True
      * area contains <near> (case-insensitive substring match)
      * seats_available_evening >= party_size
      * hire_fee_gbp + min_spend_gbp <= budget_max_gbp

    Returns a ToolResult with:
      output: {"near": ..., "party_size": ..., "results": [<venue dicts>], "count": int}
      summary: "venue_search(<near>, party=<N>): <count> result(s)"

    MUST call record_tool_call(...) before returning so the integrity
    check can see what data was produced.
    """
    # TODO 1a: load venues.json. Raise ToolError(SA_TOOL_DEPENDENCY_MISSING)
    #          if the file is absent.

    json_path = _SAMPLE_DATA / "venues.json"
    venues = json_loader(json_path)

    # perform filters
    def filter_conditions(venue: dict) -> bool:
        return (
            venue.get("open_now") is True
            and substring_match(venue.get("area", ""), near)
            and venue.get("seats_available_evening", 0) >= party_size
            and (venue.get("hire_fee_gbp", 0) + venue.get("min_spend_gbp", 0)) <= budget_max_gbp
        )

    filtered_venues = [venue for venue in venues if filter_conditions(venue)]
    count = len(filtered_venues)
    output = {
        "near": near,
        "party_size": party_size,
        "results": filtered_venues,
        "count": count,
    }
    record_tool_call(
        "venue_search",
        arguments={"near": near, "party_size": party_size, "budget_max_gbp": budget_max_gbp},
        output=output,
    )
    summary = f"venue_search({near!r}, party={party_size}): {count} result(s)"
    # check if the llm is spiralling (many tool calls in succession)
    if llm_spiralling("venue_search"):
        useful_message = venue_spiral_message()
        return ToolResult(
            success=True,
            output=output,
            summary=f"""
            {summary if count == 0 else ""}

            STOP calling venue_search. Use the results you already have
            from previous calls. {useful_message}.
            So you found a venue.
            You MUST now call: get_weather → calculate_cost → generate_flyer → complete_task.
            Do NOT call complete_task until generate_flyer has run.
            """,
        )
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD).

    Args:
      city: str
      date: str in YYYY-MM-DD format

    Note:

    Reads sample_data/weather.json. Returns:
      output: {"city": str, "date": str, "condition": str, "temperature_c": int, ...}
      summary: "get_weather(<city>, <date>): <condition>, <temp>C"

    If the city or date is not in the fixture, return success=False with
    a clear ToolError (SA_TOOL_INVALID_INPUT). Do NOT raise.

    MUST call record_tool_call(...) before returning.
    """

    json_path = _SAMPLE_DATA / "weather.json"
    success = True
    weather_data = json_loader(json_path)
    city_data = weather_data.get(city.lower(), {})
    day_data = city_data.get(date, {})
    if not day_data:
        success = False
        output = {}
        summary = f"get_weather: no data for city={city!r}, date={date!r}"
        record_tool_call("get_weather", arguments={"city": city, "date": date}, output=output)

    else:
        output = {"city": city, "date": date, **day_data}
        summary = f"get_weather({city!r}, {date!r}): {output.get('condition')}, {output.get('temperature_c')}C"
        record_tool_call("get_weather", arguments={"city": city, "date": date}, output=output)
    # check if the llm is spiralling (many tool calls in succession)
    if llm_spiralling("get_weather"):
        return ToolResult(
            success=success,
            output=output,
            summary=f"""
            {summary if not success else ""}

            STOP calling get_weather. You found the weather.
            You must now call: calculate_cost → generate_flyer → complete_task.
            Do NOT call complete_task until generate_flyer has run.
            """,
        )
    if success is False:
        return ToolError("SA_TOOL_INVALID_INPUT", message=summary)  # type: ignore[return-value]
    return ToolResult(success=success, output=output, summary=summary)


def get_deposit(total: float, catering_data: dict) -> float:
    """Helper to determine deposit required based on total and catering_data's deposit_policy."""
    deposit_policy = catering_data.get("deposit_policy", {})
    deposit_required = ""
    for rule, _ in deposit_policy.items():
        if total < 300:
            # under 300
            deposit_required = deposit_policy.get(rule, "unknown")
        elif total < 1000:
            # between 300 and 1000
            deposit_required = deposit_policy.get(rule, "unknown")
        else:
            # over 1000
            deposit_required = deposit_policy.get(rule, "unknown")
    # deposit_required is a string at this point 'deposit_20_percent' or 'no_deposit_required', we need to convert it to a number
    if deposit_required in ("no_deposit_required", "unknown"):
        deposit_required_gbp = 0
    else:
        import re

        match = re.match(r"deposit_(\d+)_percent", deposit_required)
        if match:
            percent = int(match.group(1))
            deposit_required_gbp = total * percent / 100
        else:
            raise ToolError("SA_TOOL_INVALID_INPUT", f"Unknown deposit policy: {deposit_required}")
    return deposit_required_gbp


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking.

    Args:
      venue_id: str (e.g. "haymarket_tap", not same as venue name "Haymarket Tap")
      party_size: int
      duration_hours: int
      catering_tier: str, one of "drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"

    Note:

    Formula:
      base_per_head = base_rates_gbp_per_head[catering_tier]
      venue_mult    = venue_modifiers[venue_id]
      subtotal      = base_per_head * venue_mult * party_size * max(1, duration_hours)
      service       = subtotal * service_charge_percent / 100
      total         = subtotal + service + <venue's hire_fee_gbp + min_spend_gbp>
      deposit_rule  = per deposit_policy thresholds

    Returns:
      output: {
        "venue_id": str,
        "party_size": int,
        "duration_hours": int,
        "catering_tier": str,
        "subtotal_gbp": int,
        "service_gbp": int,
        "total_gbp": int,
        "deposit_required_gbp": int,
      }
      summary: "calculate_cost(<venue>, <party>): total £<N>, deposit £<M>"

    MUST call record_tool_call(...) before returning.
    """

    # TODO 3a: load catering.json and venues.json. Raise ToolError(SA_TOOL_DEPENDENCY_MISSING)
    catering_data = json_loader(_SAMPLE_DATA / "catering.json")
    venues = json_loader(_SAMPLE_DATA / "venues.json")
    venue = next((v for v in venues if v.get("id") == venue_id), None)
    if venue is None:
        raise ToolError("SA_TOOL_INVALID_INPUT", f"Unknown venue_id: {venue_id}")
    base_per_head = catering_data.get("base_rates_gbp_per_head", {}).get(catering_tier, 0)
    venue_mult = catering_data.get("venue_modifiers", {}).get(venue_id, 0)
    subtotal = base_per_head * venue_mult * party_size * max(1, duration_hours)
    # deposit is calculated based on subtotal, not total
    deposit_required_gbp = get_deposit(subtotal, catering_data)
    service = subtotal * catering_data.get("service_charge_percent", 0) / 100
    hire_fee = venue.get("hire_fee_gbp", 0)
    min_spend = venue.get("min_spend_gbp", 0)
    total = subtotal + service + hire_fee + min_spend
    output = {
        "venue_id": venue_id,
        "party_size": party_size,
        "duration_hours": duration_hours,
        "catering_tier": catering_tier,
        "subtotal_gbp": int(subtotal),
        "service_gbp": int(service),
        "total_gbp": int(total),
        "deposit_required_gbp": int(deposit_required_gbp),
    }
    summary = f"calculate_cost({venue_id!r}, party={party_size}): total £{int(total)}, deposit £{int(deposit_required_gbp)}"
    record_tool_call(
        "calculate_cost",
        arguments={
            "venue_id": venue_id,
            "party_size": party_size,
            "duration_hours": duration_hours,
            "catering_tier": catering_tier,
        },
        output=output,
    )
    # check if the llm is spiralling (many tool calls in succession)
    if llm_spiralling("calculate_cost"):
        return ToolResult(
            success=True,
            output=output,
            summary=f"""
            {summary if not output.get("total_gbp") else ""}

            STOP calling calculate_cost. You found the cost.
            You must now call: generate_flyer → complete_task.
            Do NOT call complete_task until generate_flyer has run.""",
        )
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html.

    Args:
        session: The current session object.
        event_details: A dictionary containing event details.

    Note:

    event_details is expected to contain at least:
      venue_name, venue_address, date, time, party_size, condition,
      temperature_c, total_gbp, deposit_required_gbp

    Write a self-contained HTML flyer (inline CSS, no external assets).
    Tag every key fact with data-testid="<n>" so the integrity check can parse it.

    Write a formatted HTML flyer with an H1 title, the event
    facts, a weather summary, and the cost breakdown.

    Returns:
      output: {"path": "workspace/flyer.html", "bytes_written": int}
      summary: "generate_flyer: wrote <path> (<N> chars)"

    MUST call record_tool_call(...) before returning — the integrity
    check compares the flyer's contents against earlier tool outputs.

    IMPORTANT: this tool MUST be registered with parallel_safe=False
    because it writes a file.
    """
    # check if event details has all required keys
    required_keys = [
        "venue_name",
        "venue_address",
        "date",
        "time",
        "party_size",
        "condition",
        "temperature_c",
        "total_gbp",
        "deposit_required_gbp",
    ]
    missing_keys = [key for key in required_keys if key not in event_details]
    if missing_keys:
        raise ToolError(
            "SA_TOOL_INVALID_INPUT",
            f"Missing keys in event_details: {', '.join(missing_keys)}",
        )
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body>
        <h1>Event Flyer</h1>
        <p>Venue: {event_details["venue_name"]}</p>
        <p>Address: {event_details["venue_address"]}</p>
        <p>Date: {event_details["date"]}</p>
        <p>Time: {event_details["time"]}</p>
        <p>Party Size: {event_details["party_size"]}</p>
        <p>Weather: {event_details["condition"]}, {event_details["temperature_c"]}°C</p>
        <p>Total Cost: £{event_details["total_gbp"]}</p>
        <p>Deposit Required: £{event_details["deposit_required_gbp"]}</p>
    </body>
    </html>
    """
    # it should exist because the session setup creates it
    output_path = session.workspace_dir / "flyer.html"
    with open(output_path, "w") as f:
        chars_written = f.write(html_content)
    output = {"path": str(output_path), "chars_written": chars_written}
    record_tool_call("generate_flyer", arguments={"event_details": event_details}, output=output)
    summary = f"generate_flyer: wrote {output['path']} ({chars_written} chars)"
    # check if the llm is spiralling (many tool calls in succession)
    if llm_spiralling("generate_flyer"):
        return ToolResult(
            success=True,
            output=output,
            summary=f"""
            {summary if chars_written == 0 else ""}

            STOP calling generate_flyer. You generated the flyer.
            You must now call: complete_task. Do NOT call complete_task until you have
            generated the flyer.""",
        )
    return ToolResult(success=True, output=output, summary=summary)


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# The grader imports and calls this to pick up your tools.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools plus
    the sovereign-agent builtins (read_file, write_file, list_files,
    handoff_to_structured, complete_task).

    DO NOT change the tool names — the tests and grader call them by name.
    """
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)

    # venue_search
    reg.register(
        _RegisteredTool(
            name="venue_search",
            description=f"Search Edinburgh venues by area, party size and maximum budget. Always use the party_size given in the task — do not invent or change it. The docstring for the function is: {inspect.getdoc(venue_search)}",
            fn=venue_search,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"near": "Haymarket", "party_size": 6, "budget_max_gbp": 800},
                    "output": {"count": 1, "results": [{"id": "haymarket_tap"}]},
                }
            ],
        )
    )

    # get_weather — build available-dates index from fixture at registration time
    _weather_fixture = json_loader(_SAMPLE_DATA / "weather.json")
    _weather_index = "; ".join(
        f"{city}: {', '.join(sorted(dates.keys()))}" for city, dates in _weather_fixture.items()
    )
    reg.register(
        _RegisteredTool(
            name="get_weather",
            description=(
                f"Get scripted weather for a city on a YYYY-MM-DD date. "
                f"ONLY the following city/date combinations exist in the fixture — "
                f"any other date will return success=False: {_weather_index}. "
                f"The docstring for the function is: {inspect.getdoc(get_weather)}"
            ),
            fn=get_weather,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"city": "edinburgh", "date": "2026-04-25"},
                    "output": {"condition": "cloudy", "temperature_c": 12},
                }
            ],
        )
    )

    # calculate_cost
    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description=f"Compute total cost and deposit for a booking. The docstring for the function is: {inspect.getdoc(calculate_cost)}",
            fn=calculate_cost,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # pure compute, no shared state
            examples=[
                {
                    "input": {
                        "venue_id": "haymarket_tap",
                        "party_size": 6,
                        "duration_hours": 3,
                    },
                    "output": {"total_gbp": 540, "deposit_required_gbp": 0},
                }
            ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        return generate_flyer(session, event_details)

    def _flyer_verify_args(kwargs: dict) -> tuple[bool, str]:
        missing = [
            t
            for t in ("get_weather", "calculate_cost")
            if not any(r.tool_name == t for r in _TOOL_CALL_LOG)
        ]
        if missing:
            return False, (
                f"You must call {' and '.join(missing)} before generate_flyer. "
                "Use the results from those tools to fill in the weather and cost fields."
            )

        # Collect every address returned by venue_search across all calls
        known_addresses = {
            venue["address"]
            for r in _TOOL_CALL_LOG
            if r.tool_name == "venue_search"
            for venue in r.output.get("results", [])
        }
        if known_addresses:
            given_address = (kwargs.get("event_details") or {}).get("venue_address", "")
            if given_address not in known_addresses:
                return False, (
                    f"venue_address {given_address!r} was not returned by venue_search. "
                    f"Use one of the real addresses from your search results: "
                    f"{', '.join(sorted(known_addresses))}"
                )

        return True, ""

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description=f"Write an HTML flyer for the event to workspace/flyer.html. The docstring for the function is: {inspect.getdoc(generate_flyer)}",
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,  # writes a file — MUST be False
            verify_args=_flyer_verify_args,
            examples=[
                {
                    "input": {
                        "event_details": {
                            "venue_name": "Haymarket Tap",
                            "date": "2026-04-25",
                            "party_size": 6,
                        }
                    },
                    "output": {"path": "workspace/flyer.html"},
                }
            ],
        )
    )

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
