# agent-dispatch-kit · One entry point to dispatch all your agents

> Companion to the X thread: "It solved 99% of my 'can't use my computer while away' problem"
> X thread: https://x.com/jiemi232/status/2102741959148445825?s=46
>
> Technical companion: "A single entry point to dispatch all your agents — Muse as dispatcher, Jev as acceptance, Bridge as the execution layer"
> X thread: https://x.com/jiemi232/status/2103153535206797342?s=46
>
> Lazy-mode companion: "Copy-paste this prompt and your agent sets up the whole project"
> X thread: https://x.com/jiemi232/status/2103163429951594855?s=46

[中文版 → README.zh-CN.md](README.zh-CN.md)

## What is this

A methodology kit for a simple idea: **instead of installing one app per AI agent, keep a single entry point — a cloud assistant that truly understands your intent — and let it dispatch the agents running on your own computer.**

You say one sentence from your phone. The assistant breaks it into tasks, picks the right worker agent for each, sets acceptance criteria, tracks execution, verifies the result (with a second model scoring independently), and reports back. The loop is: **dispatch → track → accept → advise**.

Everything here is from a setup that actually runs daily — nothing is hypothetical.

## What's inside

- [docs/architecture.md](docs/architecture.md) — the three-layer architecture and design principles
- [docs/quickstart.md](docs/quickstart.md) — the smallest conservative setup that works ([中文](docs/quickstart.zh-CN.md))
- [docs/operations.md](docs/operations.md) — hard-won operational lessons: restart discipline, timeouts, whitelist workflow ([中文](docs/operations.zh-CN.md))
- [prompts/dispatch-template.md](prompts/dispatch-template.md) — structured instruction template for worker agents (objective / constraints / acceptance criteria)
- [prompts/report-template.md](prompts/report-template.md) — structured report-back template (done / evidence / risks)
- [prompts/acceptance.md](prompts/acceptance.md) — the acceptance workflow, including independent second-model scoring
- [scripts/jev-score-example.py](scripts/jev-score-example.py) — sanitized example of second-model scoring (API key via environment variable, stdlib only)

## What this is NOT

- **Not a remote-access tool.** This kit contains no server code, no tunneling, no credentials. The control channel in my own setup is private infrastructure and stays private for security reasons.
- **Not a lock-in breaker by itself** — it's the reverse: because orchestration is decoupled from execution, you can switch worker agents whenever a better or cheaper one appears, without changing your habits or losing the assistant's memory of you.

## Who it's for

- People running multiple AI coding agents (opencode / codex / CLIs) on their own machine
- People who are often away from their computer and want tasks to keep moving
- People who want a real acceptance gate instead of "the agent said it's done"

## Security notes

- Templates use `[PLACEHOLDERS]` only. Never paste tokens, API keys, IPs, or personal paths into them.
- The example scoring script reads its key from `DISPATCH_SCORER_API_KEY`. If it isn't set, the script refuses to run.

## Roadmap

- Generalizing the private control channel into something safely publishable is under evaluation. It is **not** in this repo today, and it won't be until the security design is right. The methodology here is useful with any channel you already trust.
