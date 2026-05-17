# Ex6 - Rasa structured half

## Your answer

`RasaStructuredHalf` subclasses `StructuredHalf` and overrides `run()` to
route a booking dict through Rasa's REST webhook and interpret the response as
a `HalfResult`.

**Payload flow.** The loop half hands off raw booking data. `run()` calls
`normalise_booking_payload` (validator.py) to produce a canonical Rasa message:
- `sender` - stable SHA-1 of `(venue_id, date, time)` so the Rasa tracker is
  consistent across retries within one session
- `message` - the literal string `/confirm_booking`
- `metadata.booking` - the cleaned dict

This message is POSTed via `urllib` to Rasa's REST webhook. The response is a
JSON array of bot messages; `run()` scans each for `custom.action == "committed"`
or `custom.action == "rejected"` (and also checks the text fallback for
"booking confirmed" / "can't accept").

**Rasa side.** A single CALM flow `confirm_booking` handles the programmatic
trigger. It calls the custom action `action_validate_booking`, which reads
`tracker.latest_message.metadata.booking`, sets every slot explicitly
(venue_id, date, time, party_size, deposit_gbp), then validates against
policy rules:
- `party_size > 8` sets `validation_error = "party_too_large"`
- `deposit_gbp > 300` sets `validation_error = "deposit_too_high"`
- any required field missing sets `validation_error = "missing_<field>"`
- otherwise `validation_error = None` and `booking_reference` is set

The flow branches on `validation_error`: null gives `utter_booking_confirmed`;
non-null gives `utter_booking_rejected`. Both utterances interpolate the relevant
slot into the response text, which the HTTP layer in `run()` then parses.

`resume_from_loop` and `request_research` flows were intentionally omitted from
the Rasa project; reverse handoffs are handled at the bridge level in Ex7
(Python, not CALM dialog steps), which keeps the Rasa model simple and teaches
the multi-process boundary pattern.

**Validator normalisation (all 5 fields).** `normalise_booking_payload` covers:
1. `date` - "25th April 2026", "today", "tomorrow", ISO-8601 into `YYYY-MM-DD`
2. `deposit` (currency) - "£200", "200 GBP", 200.0 into `int` pounds
3. `party_size` - "6 people", "6", 6 into `int`; rejects < 1
4. `time` - "7:30pm", "1930", "noon" into `HH:MM` 24-hour
5. `venue_id` - "Haymarket Tap", "haymarket-tap" into `haymarket_tap`

`ValidationFailed` (a `ValueError`) is raised for unrecoverable input and caught
in `run()`, which returns `HalfResult(success=False, next_action="escalate")`
so the caller always gets a typed result rather than an exception.

**Offline / mock mode.** `spawn_mock_rasa` launches a stdlib `ThreadingHTTPServer`
that exposes the same JSON contract as Rasa's REST webhook. It applies the same
validation rules (`party_size > 8`, `deposit > 300`) so mock and real paths
produce identical outcomes for a given input. This lets unit tests exercise
both the happy path and rejection without a Rasa license.

**Error handling.** HTTP errors return `SA_EXT_SERVICE_UNAVAILABLE`; timeouts
return `SA_EXT_TIMEOUT`. Both set `success=False` and leave `next_action` as
`"escalate"` - the caller decides whether to retry.

## Citations

- `starter/rasa_half/validator.py` - `normalise_booking_payload` + field helpers
- `starter/rasa_half/structured_half.py` - `RasaStructuredHalf.run`, `spawn_mock_rasa`, `RasaHostLifecycle`
- `rasa_project/data/flows.yml` - `confirm_booking` CALM flow
- `rasa_project/actions/actions.py` - `ActionValidateBooking` with business rules
- `rasa_project/domain.yml` - slots, `utter_booking_confirmed`, `utter_booking_rejected`
