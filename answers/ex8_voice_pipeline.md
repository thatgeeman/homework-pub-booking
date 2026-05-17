# Ex8 - Voice pipeline

## Your answer

### Two modes, one trace contract

`run_text_mode` (reads stdin, writes stdout) and `run_voice_mode` (mic, Speechmatics STT, Rime TTS) write identical trace events. Every user turn emits `voice.utterance_in` and every manager reply emits `voice.utterance_out`, both with payload `{text, turn, mode}`. The `mode` field is `"text"` or `"voice"`, which lets downstream grading distinguish transports without caring which ran.

### Graceful degradation - three levels

Voice mode degrades in three distinct steps, each falling through to a working state rather than crashing:

1. `SPEECHMATICS_KEY` missing: warning printed to stderr, falls through to `run_text_mode`. The session still completes with valid trace events.
2. `speechmatics-python` not installed: `ImportError` caught, install hint printed, falls through to `run_text_mode`.
3. `RIME_API_KEY` missing: `rime_enabled = False`, STT and LLM still run but the manager's replies are printed rather than spoken. Trace events are identical.

This means CI passes without any audio credentials, and a user with only a Speechmatics key gets voice input but text output.

### Voice capture and VAD

`_record_until_silence(sd, session, turn)` reads 100 ms chunks from the default mic at 16 kHz mono 16-bit PCM. A simple RMS threshold (500 int16 units) decides speech vs silence. Two consecutive seconds of silence ends the turn; 15 s is the hard cap. If no speech is detected in the first 3 s the function returns an empty byte string and the conversation ends cleanly. Each captured turn is saved as `session/workspace/turn_{N}_input.wav` for debugging.

After transcription via `_transcribe_speechmatics`, voice mode checks if the text is "goodbye", "bye", or "cheerio" (case-insensitive, punctuation stripped) and exits before sending to the manager.

### Speechmatics STT

`_transcribe_speechmatics` wraps the Speechmatics realtime WebSocket API using the batch-via-realtime pattern: one connection, all PCM bytes pushed at once, `AddTranscript` events collected. The blocking client is run in an executor so it doesn't block the asyncio event loop. Errors (HTTP 403 = free-tier cap exhausted) surface with a diagnostic message.

### Rime.ai TTS

`_speak_rime(text, api_key, sd)` POSTs to the Rime API with `modelId="arcana"` and `speaker="luna"`, receives MP3, decodes via pydub (resampled to 16 kHz mono int16), and plays via sounddevice. If pydub is missing a warning is printed and the turn continues without audio.

### ManagerPersona

`ManagerPersona` wraps `meta-llama/Llama-3.3-70B-Instruct` on Nebius at `temperature=0`. Every `respond()` call appends the new turn to `self.history` and re-builds the full message list for the next call.

`MANAGER_SYSTEM_PROMPT` defines Alasdair MacLeod (gruff Edinburgh pub manager) with explicit booking rules. Parties of 8 or fewer with a deposit under 300 GBP are accepted; the manager asks for a contact number. Parties of 9 or more are declined with a suggestion to try a larger venue. Deposits over 300 GBP are declined citing head office sign-off.

`condense_history()` is called inside `_build_messages` when `len(self.history) > 2`. It calls the same LLM with a summarisation prompt that outputs XML slots (`<party_size>`, `<date>`, `<time>`, `<contact_number>`, `<missing_info>`, `<booking_confirmation>`), clears the raw history list, and stores the XML string as `self.condensed_context`. On the next turn the condensed context is injected as a second system message before the now-empty history. This keeps the context window bounded for long conversations without losing booking details.

### Session trace (text mode)

`sess_37e2828f3efe` is a 6-turn text-mode conversation. The manager accepted a booking for 7 people (under the 8-person limit, no deposit mentioned) and collected a contact number, ending with "Cheerio." The trace shows alternating `voice.utterance_in` and `voice.utterance_out` events with `mode: "text"` and turn indices 0-5.

## Citations

- `starter/voice_pipeline/voice_loop.py` - `run_text_mode`, `run_voice_mode`, `_record_until_silence`, `_transcribe_speechmatics`, `_speak_rime`
- `starter/voice_pipeline/manager_persona.py` - `ManagerPersona`, `MANAGER_SYSTEM_PROMPT`, `condense_history`
- `sessions/sess_37e2828f3efe/logs/trace.jsonl` - 6-turn text-mode session, turns 0-5, mode="text"
