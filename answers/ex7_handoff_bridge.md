# Ex7 — Handoff bridge

## Your answer

The HandoffBridge orchestrates round-trips between the loop half and
structured half. Each round: loop runs, if next_action=handoff_to_structured
the bridge writes a forward handoff file, invokes structured, and then
either marks the session complete (structured confirmed) or builds a
reverse task and loops back (structured escalated).

The reverse-task path is the interesting one. On escalation, the
bridge rewrites the initial_task into a dict that contains
prior_result + rejection_reason + retry=True. The loop half sees
this via the new executor invocation and — in a real LLM setting —
would produce a different subgoal. In the scripted offline demo we
hardcode the retry choice (royal_oak with 16 seats) so the test is
deterministic.

Every half transition emits a session.state_changed trace event via
session.append_trace_event(). The integrity check (integrity.py)
verifies the trace has at least one round_start, at least one
state_changed, and at least one tool call — catching the case where
the bridge reports success without doing real work.

The stale-handoff cleanup moves old ipc/handoff_to_structured.json
files into logs/handoffs/ instead of deleting them, preserving the
audit trail.

## Citations

- starter/handoff_bridge/bridge.py — HandoffBridge.run + helpers
- starter/handoff_bridge/integrity.py — verify_dataflow
- sessions/sess_35c2e3ea6b82/logs/trace.jsonl
