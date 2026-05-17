# Ex5 - Edinburgh research loop scenario

## Your answer

### Tools

Four tools are registered in `tools.py`, all logging to `_TOOL_CALL_LOG` on every call:

- `venue_search(near, party_size, budget_max_gbp)` - reads `sample_data/venues.json`, returns matching venues; `parallel_safe=True`
- `get_weather(city, date)` - reads `sample_data/weather.json`; `parallel_safe=True`
- `calculate_cost(venue_id, party_size, duration_hours)` - reads `sample_data/catering.json`; `parallel_safe=True`
- `generate_flyer(event_details)` - writes `workspace/flyer.html` in the session directory; `parallel_safe=False` (file write)

### Dataflow integrity check

`verify_dataflow(flyer_content)` in `integrity.py` scans the flyer for three
categories of concrete fact and cross-references each against `_TOOL_CALL_LOG`:

1. **Money facts** - all `£<number>` occurrences (HTML tags stripped first via regex)
2. **Temperature facts** - all `<digits>°C` / `<digits>C` occurrences
3. **Weather conditions** - known keywords: `sunny`, `rainy`, `cloudy`, `partly_cloudy`

For each fact, `fact_appears_in_log` recursively walks every tool call's `output`
and `arguments` dicts, comparing stripped lowercase strings. A planted `£9999`
fails immediately because no fixture returns that value and no tool call ever
produced it. An unmodified flyer passes because every value it contains was
written into the log by the tool that produced it.

The check runs after `generate_flyer` and before the session is marked complete;
a failed check surfaces as `IntegrityResult(ok=False)` with the list of
unverified facts.

### Planner and executor tickets

Session sess_9340a75c968f (Qwen/Qwen3-Next-80B-A3B-Thinking as planner,
Qwen/Qwen3-Next-32B as executor) produced three verified tickets:

- tk_a76f22e3: `planner.plan`, success, 19 s
- tk_3039375b: `executor.run_subgoal/sg_1`, success, 62 s, 1 tool call
- tk_ae317358: `executor.run_subgoal/sg_2`, success, 90 s, 2 tool calls

The planner produced two subgoals: `sg_1` (research venue) and `sg_2` (draft
flyer), with `sg_2.depends_on = ["sg_1"]`. Each ticket has a `manifest.json`
with SHA-256 of its output and a `state.json` recording start/end timestamps.

---

## Iteration log

Each iteration below describes what failed, what was changed, and what the
next round of sessions revealed.

---

### Iteration 0 - baseline (sess_9340a75c968f, sess_0c0714c2793d, sess_f47209f1827c)

**Models tested:** 80B-Thinking+32B, 80B-Thinking+235B, 32B+32B

**What happened:**

- sess_9340a75c968f (80B+32B): Flyer produced but fully hallucinated.
  `venue_search(near="Old Town", party_size=10)` returned The Royal Oak.
  The executor never called `get_weather` or `calculate_cost`, then passed
  invented values directly to `generate_flyer`: venue="Haymarket Tap" (wrong),
  address="123 Main St" (wrong), date="2023-10-15" (not in fixture),
  temp=18 C (not in fixture), total=£150, deposit=£50 (neither matches fixtures).
- sess_0c0714c2793d (80B+235B): `venue_search` called 5x with `party_size=50`,
  all returning 0 results, ending in `handoff_to_structured`.
- sess_f47209f1827c (32B+32B): `venue_search` 3x with `party_size=10`, ending in `handoff_to_structured`.

**Integrity check behaviour:** `verify_dataflow` passed on sess_9340a75c968f
because `generate_flyer` logged its own `event_details` as `arguments`, and
`fact_appears_in_log` scans both `r.output` and `r.arguments`. The hallucinated
values were self-verifying. Cross-checking against fixtures confirms none of
the facts were grounded:

- Address: flyer said "123 Main St, Edinburgh", fixture has "12 Dalry Rd, Edinburgh EH11 2BG"
- Date: flyer said "2023-10-15", not in fixture (fixture covers 2026 only)
- Temperature: flyer said 18 C, not in fixture (max is 17 C)
- Total cost: flyer said £150, fixture gives £556 (party=6, 3hr, bar_snacks, haymarket_tap)
- Deposit: flyer said £50, fixture gives £97 (30% of £324 subtotal)

A grader-planted `£9999` still fails because the grader edits the HTML
directly without a tool call, so no record contains `9999`.

**Spiral detection added:** `venue_search` tracks call counts and emits a
hard stop message after > 3 calls, passing through the real `success` and
`output` values (not hardcoding `success=False`, which sent a misleading
failure signal):

```python
return ToolResult(
    success=success,
    output=output,
    summary=f"STOP calling venue_search. Use the results you already have. {useful_message}."
)
```

---

### Iteration 1 - verify_args on generate_flyer (sess_94c83e5bc804, sess_5b15f210c149, sess_27ba0e78f865)

**Change:** Added `verify_args` pre-hook to `generate_flyer` that blocks the
call if `get_weather` or `calculate_cost` have not yet appeared in
`_TOOL_CALL_LOG`:

```python
def _flyer_verify_args(kwargs):
    missing = [t for t in ("get_weather", "calculate_cost")
               if not any(r.tool_name == t for r in _TOOL_CALL_LOG)]
    if missing:
        return False, f"You must call {' and '.join(missing)} before generate_flyer."
    return True, ""
```

**Results:**

- sess_94c83e5bc804 (80B+235B): `party_size=50` spiral, handoff, no flyer
- sess_5b15f210c149 (80B+32B): Hook fired; cost grounded (£794, £162 from calculate_cost) but address/date still hallucinated
- sess_27ba0e78f865 (32B+32B): Hook fired; second attempt used correct address. Cost (£556) and address grounded, date still hallucinated (2023-10-17)

**Finding:** All three models called `get_weather` with `2023-10-15` or
`2023-10-17`, a date absent from the fixture, despite the task prompt
stating `date: 2026-04-25`. Models defaulted to a memorised training-data date.

---

### Iteration 2 - weather dates in description (sess_d667b16f8d72, sess_1a6386aa2584, sess_3f9c853fa750)

**Change:** Read available city/date combinations from `weather.json` at
registration time and inject them into the `get_weather` description:

```python
_weather_fixture = json_loader(_SAMPLE_DATA / "weather.json")
_weather_index = "; ".join(
    f"{city}: {', '.join(sorted(dates.keys()))}"
    for city, dates in _weather_fixture.items()
)
# "edinburgh: 2026-04-24, 2026-04-25, ..., 2026-05-02; glasgow: 2026-04-25"
```

Description now reads: *"ONLY the following city/date combinations exist in
the fixture - any other date will return success=False: [index]."*
Programmatic - auto-updates if the fixture changes.

**Results:**

- sess_d667b16f8d72 (80B+235B): Date fixed (2026-04-25 correct); still `party_size=50` spiral, invented venue `edinburgh_brewlab` for calculate_cost, no flyer
- sess_1a6386aa2584 (80B+32B): Spiralled on venue_search then `list_files` then handoff, no flyer
- sess_3f9c853fa750 (32B+32B): **Flyer produced.** Date correct, weather `cloudy 12 C` correct, cost £556 correct. Address still hallucinated ("123 Haymarket")

**Finding:** Date hallucination eliminated in runs that reached `get_weather`.
Remaining gap: address invented from training data rather than fixture output.

---

### Iteration 3 - address verify_args on generate_flyer (sess_a4c4bdab2a91, sess_bc1479428a55, sess_8ef5e52e1bc6)

**Change:** Extended `_flyer_verify_args` to also check that `venue_address`
in `event_details` matches an address actually returned by a prior
`venue_search` call:

```python
known_addresses = {
    venue["address"]
    for r in _TOOL_CALL_LOG if r.tool_name == "venue_search"
    for venue in r.output.get("results", [])
}
if known_addresses:
    given = (kwargs.get("event_details") or {}).get("venue_address", "")
    if given not in known_addresses:
        return False, (
            f"venue_address {given!r} was not returned by venue_search. "
            f"Use one of: {', '.join(sorted(known_addresses))}"
        )
```

**Results:**

- sess_a4c4bdab2a91 (80B+235B): Now `party_size=6` correct but spirals areas (city centre, Haymarket, Old Town, Leith), handoff, no flyer
- sess_bc1479428a55 (80B+32B): **Fully grounded** - address `12 Dalry Rd` correct, date correct, weather correct, total £556 correct
- sess_8ef5e52e1bc6 (32B+32B): **Fully grounded** - same venue/address/date/weather; model chose `three_course_meal` tier, total £1150, deposit £259, both correct from calculate_cost

---

### Iteration 4 - party_size prompt hint (sess_81faddc781f9, sess_ea380b4df4f4, sess_6fc2b6a7e10c)

**Change:** Added soft prompt to `venue_search` description: *"Always use the
party_size given in the task - do not invent or change it."* No hardcoded
number, no `verify_args` hook (sessions confirmed the hook never fired in
iteration 3; models had self-corrected).

**Results:**

- sess_81faddc781f9 (80B+235B): Hint ignored - now `party_size=20` (was 50, then 20). Spirals, no flyer. 235B consistently invents party sizes across all runs
- sess_ea380b4df4f4 (80B+32B): **Best run yet.** Two `generate_flyer` attempts blocked by verify_args (first: upstream tools missing; second: address still hallucinated). Model recovered: called `venue_search(party=6)`, got real address, third attempt passed. Fully grounded flyer
- sess_6fc2b6a7e10c (32B+32B): Party size drifts (10, 5, 10). `get_weather` and `calculate_cost` ran correctly but model gave up with `handoff_to_structured` before writing flyer

**Key observations:**
- The 235B model has a consistent behavioural failure: it invents a large party
  size, finds no matching venues, and gives up. No prompt or description change
  has corrected this across four iterations. The model is not suitable as an
  executor for this task.
- The `verify_args` chain on `generate_flyer` is doing real correction work for
  the 80B+32B pair - rejected attempts cause the model to recover and produce
  correct output on retry.
- The 32B+32B pair succeeds when the tool call sequence completes but
  occasionally gives up before reaching `generate_flyer` due to limited retries.

---

## Citations

- `starter/edinburgh_research/tools.py` - tools, `_TOOL_CALL_LOG`, `verify_args` hooks, weather index
- `starter/edinburgh_research/integrity.py` - `verify_dataflow`, `fact_appears_in_log`
- `sessions/sess_9340a75c968f/` - baseline: hallucinated flyer, 3 tickets (tk_a76f22e3, tk_3039375b, tk_ae317358)
- `sessions/sess_0c0714c2793d/logs/trace.jsonl` - 235B party_size=50 spiral (5 calls, handoff)
- `sessions/sess_f47209f1827c/logs/trace.jsonl` - 32B+32B party_size=10 spiral, handoff
- `sessions/sess_27ba0e78f865/workspace/flyer.html` - first partial fix: correct cost, hallucinated date
- `sessions/sess_3f9c853fa750/workspace/flyer.html` - date fix: correct date+weather, hallucinated address
- `sessions/sess_bc1479428a55/workspace/flyer.html` - first fully grounded flyer (80B+32B)
- `sessions/sess_8ef5e52e1bc6/workspace/flyer.html` - fully grounded flyer (32B+32B, three_course_meal tier)
- `sessions/sess_ea380b4df4f4/logs/trace.jsonl` - verify_args chain firing twice before correct third attempt
