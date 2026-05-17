# Ex9 - Reflection

## Q1 - Planner failure modes

### Your answer

I hit three distinct failure modes in Ex5, all visible in session traces.

**Tool-call omission with immediate hallucination (sess_9340a75c968f, trace lines 3-4).** The executor called `venue_search(near="Old Town", party_size=10)` and then jumped directly to `generate_flyer`, skipping `get_weather` and `calculate_cost` entirely. The flyer it produced invented every data point: address "123 Main St, Edinburgh" (fixture: "12 Dalry Rd, Edinburgh EH11 2BG"), date "2023-10-15" (fixture covers 2026 only), temperature 18 C (fixture max 17 C), total £150 (fixture: £556 for the same party/duration/tier). This is the failure mode where the model treats the task as a writing exercise rather than a data-retrieval exercise, fabricating plausible-sounding outputs that bypass the whole tool pipeline. Tickets tk_3039375b and tk_ae317358 both show `state: success` despite no weather or cost data having been retrieved.

**Spiral on empty results (sess_0c0714c2793d, trace lines 3-8).** The 235B executor invented `party_size=50` and then called `venue_search` five times across different Edinburgh neighbourhoods (Old Town, New Town, Haymarket, Grassmarket, then Edinburgh city-wide) receiving zero results each time. After the fourth call the spiral-detection stop message fired, but the model ignored it and made a fifth call before giving up with `handoff_to_structured`. The model was stuck in a loop because its internal premise (party of 50) was never challenged - it kept searching rather than questioning the party size.

**Training-data date anchoring (sess_5b15f210c149, sess_27ba0e78f865).** After the verify_args hook forced the executor to call `get_weather`, all three model configurations called it with dates from 2023 (2023-10-15 or 2023-10-17) despite the task prompt specifying `date: 2026-04-25`. The model potentially had a strong prior from training data that overrode the in-context instruction. This was only fixed in iteration 2 by injecting the available fixture dates into the tool description itself, making the correct date the path of least resistance.

### Citations

- `sessions/sess_9340a75c968f/logs/trace.jsonl` lines 3-5 - omission + hallucination
- `sessions/sess_0c0714c2793d/logs/trace.jsonl` lines 3-8 - five-call spiral
- `sessions/sess_9340a75c968f/logs/tickets/tk_ae317358/state.json` - ticket marked success despite no tool data

---

## Q2 - Dataflow integrity catch

### Your answer

The check exposed a real structural weakness before it caught any fabricated values.

In sess_9340a75c968f the flyer was fully hallucinated but `verify_dataflow` returned `ok=True`. The reason: `fact_appears_in_log` scans both `r.output` and `r.arguments` for every tool call record. When `generate_flyer` is called it logs its own `event_details` dict as the `arguments` field of the record. Every fact the flyer contains - "£150", "18C", "123 Main St" - is present verbatim in `generate_flyer`'s own log entry. The check found all of them and passed. The values are self-verifying. A human reading the flyer would notice "2023-10-15" is a strange date for a 2026 booking; the automated check did not.

The grader's planted-fabrication test still works correctly, and I confirmed this. A grader editing `flyer.html` directly to insert `£9999` does not produce a corresponding tool call record, so `fact_appears_in_log` finds no record containing `9999` and `verify_dataflow` returns `ok=False` with `unverified_facts=["£9999"]`. The distinction is: the self-verification weakness only applies to values that the model itself passed through a tool call. Values inserted without any tool call - exactly what a grader would do - are correctly caught.

The practical fix for the self-verification gap is the `verify_args` hooks on `generate_flyer`, which block the call unless upstream tools have run first and the address matches a real venue_search result. This does not fix `verify_dataflow` itself but it prevents the scenario: if `generate_flyer` can only be called with values that originated in real tool outputs, self-verification is no longer a weakness. Session sess_ea380b4df4f4 shows this working: `generate_flyer` was rejected twice (lines 4 and 7 of the trace) before the model retrieved real data and the third call succeeded.

### Citations

- `sessions/sess_9340a75c968f/logs/trace.jsonl` line 4 - generate_flyer with hallucinated args that passed verify_dataflow
- `sessions/sess_ea380b4df4f4/logs/trace.jsonl` lines 4, 7 - verify_args rejections; line 9 - success after real data retrieved
- `starter/edinburgh_research/integrity.py` - `fact_appears_in_log` scans `r.arguments`, which is the root of the self-verification weakness

---

## Q3 - Removing one framework primitive

### Your answer

I would drop Ex6. The Rasa integration is the most setup-heavy exercise for what it teaches. Most of the implementation is boilerplate, and too docused on Rasa specifics rather than general principles. 