# Agent Gateway Protocol Bridge

Give an Anthropic-style agent client (e.g. a CLI that speaks `POST /v1/messages` with
`tools` + `tool_choice`) real tool-calling over an upstream that **does not support
function calling** — typically a web-reverse ChatGPT-style pool whose OpenAI-face endpoint
silently drops the `tools` array.

The bridge sits between the two. It translates the Anthropic request into a one-shot XML
pseudo-protocol prompt, coerces the upstream into emitting a parseable tool-call envelope,
validates it against the caller's tool whitelist, and renders it back as a proper
Anthropic `tool_use` block. When the upstream refuses or emits garbage, a repair ladder
re-prompts (with nonce rotation + assistant prefill) before honestly giving up — **it never
fabricates a tool call or fake command output.**

```
Anthropic client  ──/v1/messages──▶  Bridge (:3460)  ──OpenAI-face, no tools──▶  Your upstream (:3000)
   (ZCode, etc.)      tools+choice       protocol translation       web-reverse / official pool
```

## When you need this (and when you don't)

- **You DON'T need it** if your upstream is an official API (DeepSeek, OpenAI, Anthropic, …)
  that natively supports `tools`. Point your client straight at it — native function calling
  beats any translation layer.
- **You DO need it** only when your upstream is a web-reverse endpoint that discards `tools`,
  and you still want your agent client to drive local tools (Bash/Read/Write/Grep/…).

## Prerequisites

- Python 3.12+
- **Your own upstream**: a web-reverse pool or any OpenAI-face `/chat/completions` endpoint.
  The bridge does not ship or proxy anyone else's account — you bring your own.
- An Anthropic-face client to drive it (the bridge exposes `/v1/messages`).

## Quickstart

```bash
# 1. Create the venv + install deps (portable; uses uv if present, else stdlib venv+pip)
bash setup-venv.sh

# 2. Configure via environment variables (see the full table below), then start:
#    Windows example launcher (copy + edit the example, never commit your real key):
cp bridge-env.example.cmd bridge-env.cmd    # then edit placeholders
cmd //c bridge-env.cmd

#    Or start directly on POSIX:
BRIDGE_UPSTREAM="http://localhost:3000/v1" \
BRIDGE_WEBPOOL_KEY="<your-key>" \
BRIDGE_MODELS="auto,gpt-5-5" \
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 3460 --app-dir .
```

Verify:

```bash
curl --noproxy '*' http://127.0.0.1:3460/health      # status line incl. cooldown state
curl --noproxy '*' http://127.0.0.1:3460/v1/models    # whitelisted models
```

> **Proxy gotcha:** if your shell exports `HTTP_PROXY`/`HTTPS_PROXY` without `NO_PROXY`,
> requests to `127.0.0.1` get routed through the proxy and you'll see a fast (~2s) false
> `502`. Always test localhost with `curl --noproxy '*'` or set `NO_PROXY=127.0.0.1,localhost`.
> The bridge's own upstream client disables env proxies (`trust_env=False`), so this only
> affects your manual `curl`/client, not the bridge.

## Configuration (all env, all optional — sensible defaults)

| Env var | Default | Meaning |
|---|---|---|
| `BRIDGE_UPSTREAM` | `http://localhost:3000/v1` | Upstream OpenAI-face base URL. |
| `BRIDGE_WEBPOOL_KEY` | *(empty)* | Key for your upstream, if it needs one. **Never commit this.** |
| `BRIDGE_TOKEN` | *(empty)* | If set, clients must send it to use the bridge. Empty = loopback trust. **Set this before exposing the bridge beyond localhost.** |
| `BRIDGE_MODELS` | `gpt-5-5,gpt-5-6,gpt-5-5-instant,auto` | Comma-separated model whitelist. |
| `BRIDGE_UP_TIMEOUT` | `90` | Per-call upstream timeout (s). |
| `BRIDGE_UP_RETRY` | `2` | Transport retries on timeout/net/5xx/429 (an HTTP-200 empty body is handled separately by `BRIDGE_EMPTY_RETRY`). |
| `BRIDGE_UP_RETRY_BACKOFF` | `3` | Backoff base (s) between transport retries. |
| `BRIDGE_REPAIR_MAX` | `2` | Max repair-ladder re-prompts on a refusal/malformed reply. |
| `BRIDGE_EMPTY_RETRY` | `1` | Re-send once (fresh nonce, no prefill) when the upstream returns 200 with an empty body. `0` disables. |
| `BRIDGE_PREFILL` | `on` | Assistant-prefill ladder (scaffold → deep). `off` reverts to plain re-prompt. |
| `BRIDGE_PRUNE` | `on` | Task-level minimal tool list (prune to the one relevant tool). `off` sends the full list. |
| `BRIDGE_ANTIREFUSAL` | `on` | Anti-refusal clause in the protocol prompt. |
| `BRIDGE_CD` | `on` | Text-cooldown ledger (pool-level). |
| `BRIDGE_CD_THRESHOLD` | `3` | Consecutive retryable failures before cooldown engages. |
| `BRIDGE_CD_MIN_SEC` / `BRIDGE_CD_MAX_SEC` | `600` / `1800` | Random cooldown window bounds (s). |
| `BRIDGE_LEASE_WINDOW` / `_FORWARDS` / `_TOOLROUNDS` | `900` / `36` / `12` | Per-task lease caps (anti-runaway). |
| `BRIDGE_BUDGET_TOKENS` | `12000` | Prompt budget before 3-tier compression kicks in. |
| `BRIDGE_LOG_DIR` | `./logs` | Audit + server logs (JSONL, daily rotate, 7-day keep). Gitignored. |

## Endpoints

- `POST /v1/messages` — Anthropic face (the main path; carries `tools` + `tool_choice`).
- `POST /v1/chat/completions` — OpenAI face passthrough.
- `GET /v1/models` — whitelisted models.
- `GET /health` — status line (cooldown state, etc.).
- `GET /stats` — counters (forwards, repairs, `empty_retry`, malformed, …).

## Tests

```bash
.venv/bin/python -m pytest tests/ -q     # offline contract + regression suite, no upstream needed
```

The suite is fully offline (upstream is mocked): protocol well-formedness, malformed-envelope
rejection, repair-ladder nonce rotation, prefill escalation, refusal detection (incl. curly
quotes), empty-completion retry, and the strict-retry tool-list alignment.

## How it works

See [METHOD.md](METHOD.md) for the full playbook: the XML pseudo-protocol, tool pruning,
the prefill + repair ladder, empty-completion retry, the text-cooldown ledger, and the
honesty invariants (never fabricate a call, never fake output).

## Layout

```
config.py       env-driven configuration (no hardcoded secrets)
protocol.py     XML protocol templates + lenient-but-strict envelope parser + pruning + prefill
translate.py    Anthropic <-> OpenAI rendering; 3-tier budget compression
upstream.py     upstream client (OpenAI face, no tools, transport retry, trust_env=False)
guard.py        task lease, spin breaker, tool_choice policy, action-request / refusal detectors
cooldown.py     pool-level text-cooldown ledger (persisted, survives restart)
audit.py        redacted JSONL audit (hash + length + head/tail, daily rotate)
server.py       FastAPI app: /v1/messages, /v1/chat/completions, /v1/models, /health, /stats
tests/          offline contract + regression suite
```

## Security notes

- The bridge executes **no tools itself** — it only translates. Tools run on the *client's*
  machine, driven by the client. Sharing a bridge shares upstream quota, not local execution.
- Keep `BRIDGE_WEBPOOL_KEY` out of source control. It lives only in your local launcher
  (`bridge-env.cmd`, gitignored); ship `bridge-env.example.cmd` with placeholders instead.
- Default bind is `127.0.0.1`. Before any external exposure, set `BRIDGE_TOKEN` and put it
  behind TLS / a tunnel (e.g. Tailscale Funnel). Loopback trust is not a security boundary.

## Known limitations

- The cooldown ledger is **pool-level**, not account-level (the OpenAI-face response carries no
  account id to attribute failures to). Fine for single-user self-hosting; a shared multi-account
  pool would want account-level granularity.
- Tool pruning is a regex heuristic over the task text (Write/Grep/Read, default Bash). It picks
  the *relevant* tool to keep the prompt short; the parser still accepts any whitelisted tool the
  model legitimately emits.
