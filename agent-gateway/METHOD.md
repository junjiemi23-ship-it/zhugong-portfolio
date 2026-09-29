# METHOD — how the bridge fakes function-calling on a tools-less upstream

This is the playbook behind the code. Everything here is derived from the tracked source
(`protocol.py`, `server.py`, `guard.py`, `cooldown.py`, `upstream.py`); no external secrets.
Read it before you modify the ladder — the invariants at the end are what keep the bridge honest.

## 0. The problem

An Anthropic-face client sends `tools` + `tool_choice` and expects `tool_use` blocks back.
A web-reverse upstream exposes an OpenAI-face `/chat/completions` that drops `tools` and can
only return prose. So the bridge must:

1. describe the tools inside the prompt and get the model to emit a machine-parseable call,
2. validate that call against the caller's real whitelist,
3. render it back as a genuine Anthropic `tool_use`,
4. feed the client's `tool_result` back to the model on the next turn,
5. and never invent a call or fake output when the model refuses or emits garbage.

## 1. One-shot XML pseudo-protocol (`protocol.py`)

The bridge appends a protocol section to the system prompt (`protocol_prompt`) and asks for a
single, byte-for-byte well-formed envelope. The envelope uses four nested tags: an outer
`tool_calls` wrapper, a `tool_call` block, a `tool_name`, and a `parameters` block holding ONE
JSON object. Tag fragments are built by string concatenation in the source so this file is not
itself mistaken for an envelope.

The prompt lists each tool as a compact signature line (`- Name(param=type, optional?) : desc`)
built from the caller's `input_schema`, plus one worked example, plus hard rules:

- `TOOL_NAME` must be exactly one of the listed names.
- `parameters` holds ONE JSON object with the exact required keys.
- A call means nothing until the host replies with a message starting `Tool result `; only then
  may the model answer in prose, grounded ONLY in that result.
- Never write file listings / command output / "I have done X" without a real call and its result.

A per-request `bridge-nonce` is embedded in the tail so every attempt is byte-unique (see §5).

### Parsing is lenient about shape, strict about validity (`parse`)

- The parser tolerates prefill continuations (a bare fragment with missing opening tags is
  re-joined to the prefill prefix before matching) and markdown-ish noise.
- It runs a **tag-pairing health check**: if any open-tag count != its close-tag count, the reply
  is flagged malformed with a diagnostic. This prevents a duplicated-close fragment from being
  silently dropped (a silent-drop = a vanished call, which is worse than a loud failure).
- A candidate call is accepted only if: the name is in the whitelist, `parameters` is valid JSON,
  it is a non-empty object, and it passes `validate_params` (required keys present, declared types
  match). Anything else → treated as **no call** with a recorded malformed reason. The bridge never
  guesses parameters.

## 2. Tool pruning — short prompts win (`prune`, `prune_tools`)

The single biggest compliance lever is **list length**, not prefill depth: a controlled A/B (E vs F)
measured 92% first-pass with a minimal one-tool list vs 65% with the full list. So the bridge prunes
the caller's tools down to the one relevant to the task before prompting.

`prune(task)` is a bilingual regex heuristic over the task text: write-ish → `Write`, search-ish →
`Grep`, read-ish → `Read`, otherwise the conservative default `Bash`. `prune_tools` keeps the picked
tool if it exists in the caller's list; if the pick is not offered, it safely falls back to the full
list (never prunes to nothing). `BRIDGE_PRUNE=off` disables pruning.

CRITICAL asymmetry rule (learned the hard way, see §6): the **prompt** shows the pruned single tool,
but the **parser whitelist stays the full list** — so if the model legitimately emits a different
whitelisted tool it is accepted (parsed), not falsely rejected as malformed.

## 3. Assistant prefill ladder (`prefill_scaffold`, `prefill_deep`)

A degraded backend often will not start the envelope on its own. The classic fix is to send the
envelope opening as an assistant prefix and force the model to continue it. Two levels, from more
autonomy to less:

- **D-level scaffold**: prefill up to the open `tool_name` tag; the model still chooses the tool.
- **C-level deep**: prefill through the tool name and up to the open `parameters` tag; the model only
  supplies the JSON args and closes the tags. Deep prefill is used ONLY when a specific tool is named
  (from `tool_choice`, or when pruning left exactly one tool) — the bridge does not guess a tool name.

`BRIDGE_PREFILL=off` reverts to plain re-prompting.

## 4. The repair ladder (`server.py` `_agent_loop`)

Per request, the bridge loops:

- **attempt 0** — native: plain protocol prompt, no prefill (preserves the model's autonomy; ~65% of
  tasks resolve here).
- **attempt 1** — scaffold prefill (D-level).
- **attempt ≥2** — deep prefill (C-level) when a tool is named, else scaffold.

The ladder only escalates when `need=True`, computed in `guard.py`:
`need = (is_action_request(task) OR looks_like_refusal(reply)) AND NOT result_present(msgs_in)`.

- `is_action_request` / `looks_like_refusal` are regex detectors. They must handle **curly quotes**
  (`can’t`) — the model emits typographic apostrophes, and an ASCII-only refusal regex silently misses
  nearly all real refusals (a real bug that made the ladder never fire on ~4/6 refusals).
- `result_present(msgs_in)` is True when the trailing user message is only a `tool_result` with no new
  instruction. On such a round the bridge deliberately does NOT force a call (the model already has
  what it needs to answer in prose) — forcing there causes spurious fake calls.

When the ladder is exhausted without a valid call, the bridge returns an honest `end_turn`. If the
model produced prose that *claims* an action ("I ran the command and saw…"), the bridge prepends a
`[bridge] this reply was not verified by any tool call` honesty marker rather than letting a
fabricated result stand.

## 5. Nonce rotation (anti-cache-replay)

Every attempt — including repair retries and empty-completion re-sends — mints a fresh
`bridge-nonce` and swaps it into the system tail. Without this, a retry reuses the same upstream
cache key and gets back the *same failed reply* (a fatal, silent loop). Fresh nonce per attempt is
the contract that makes retries meaningful.

## 6. Strict-retry tool-list alignment (a fixed bug worth knowing)

When a first-turn refusal triggers a strict retry, the strict system prompt must list the **same
pruned tool set** as the first turn (`prompt_tools`), not the full whitelist. An earlier version
passed the full list on the strict branch; the model, seeing all four tools, grabbed `Bash` for a
task that had pruned to `Grep`/`Read` — producing "wrong tool" misses. The fix: the strict branch
uses `prompt_tools if (inject and tools) else tools`. The parse whitelist stays full (a legal
off-pick is parsed, not malformed). A/B-validated: this flipped all such wrong-tool cases correct.

## 7. Empty-completion retry (`BRIDGE_EMPTY_RETRY`)

Distinct from the repair ladder. Sometimes the upstream returns HTTP 200 with an **empty body**
(`completion_tokens=0`) — common on result-回填 turns. The transport layer treats a 200 as success,
so it never retries; and `result_present` suppresses the repair ladder on that round; net effect was
a blank assistant message to the client.

The fix is orthogonal: if there are no calls AND the **raw** text is empty (judge on raw `text`, NOT
`visible_text` — a malformed envelope strips to empty visible text and would hijack the malformed
repair count), swap the nonce and re-send once, with no prefill. Capped by `BRIDGE_EMPTY_RETRY`
(default 1; 0 disables). This lifted multi-turn grounding from 80% to 95–100% in live A/B, confirming
most empty bodies are transient pool jitter that a single re-send recovers.

## 8. Text-cooldown ledger (`cooldown.py`)

A web pool's own "rate limit" state typically tracks only image-gen quota, not text usage — so real
text throttling is invisible to the client, which keeps hammering during a throttle window and makes
the风控 worse. The bridge keeps a **pool-level** ledger: consecutive retryable failures
(timeout/net/5xx/429) reaching `BRIDGE_CD_THRESHOLD` (default 3) open a random cooldown window
(`BRIDGE_CD_MIN_SEC`..`MAX_SEC`, default 600..1800s). During the window, `call_upstream` fast-fails
without touching the upstream. Any success clears the consecutive count; window expiry auto-clears
and re-learns. State persists to `state/cooldown.json` so a bridge restart does not lose the window.
A 429 (explicit rate signal) trips immediately rather than accumulating.

Scope is pool-level because the OpenAI-face response carries no account id to attribute failures to;
account-level granularity is future work for shared multi-account pools.

## 9. Budget compression (`translate.py`)

When the estimated prompt exceeds `BRIDGE_BUDGET_TOKENS`, a 3-tier compression applies: keep
everything → excerpt old tool rounds (head/tail keep) → drop old chitchat. System prompt and the
most recent rounds are protected.

## 10. Honesty invariants (do not break these)

1. **Never fabricate a tool call.** A malformed or absent envelope is "no call", never a guessed one.
2. **Never fake command output / file listings.** Prose that claims an unverified action gets the
   `[bridge]` honesty marker.
3. **Never silently drop a call.** Tag-count mismatch is loud (malformed + diagnostic), not swallowed.
4. **Never retry with a stale nonce.** Every attempt rotates the nonce.
5. **Never force a call on a pure tool_result round** (`result_present`) — answer in prose instead.
6. **A 200 is not automatically a useful answer** — an empty body is retried once, not passed through.
