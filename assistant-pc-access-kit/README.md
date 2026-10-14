# assistant-pc-access-kit · Give your AI assistant a computer

> Companion to the X thread: "How I let Muse use my computer" (link TBD after publishing)
>
> [中文版 → README.zh-CN.md](README.zh-CN.md)

## What is this

A practical kit for one idea: **an AI assistant becomes a different species once it can use your computer** — not just answer questions, but run commands, reach your accounts, take instructions from your phone, and keep working on a schedule while you sleep.

This kit documents the access layers, the order to connect them, the security rules, and the task-instruction templates. Everything here runs in a real daily setup — nothing is hypothetical.

## The four access layers

1. **The assistant's own cloud computer** — terminal, browser, filesystem, always on. For research, scripts, files.
2. **Your connected accounts** — email, calendar, etc. Read-first permissions; writes need approval.
3. **Your paired phone** — the remote control. Instruct from anywhere; progress and results come back to it.
4. **Your PC, via a private bridge** — your computer becomes its hands. It dispatches work to the agents already on your machine: dispatch → track → accept → report.

Details: [docs/architecture.md](docs/architecture.md)

## What's inside

- [docs/architecture.md](docs/architecture.md) — the four layers and how tasks flow through them
- [docs/access-checklist.md](docs/access-checklist.md) — connect in this order, with acceptance criteria per step
- [docs/security.md](docs/security.md) — the non-negotiable security rules
- [docs/scheduling.md](docs/scheduling.md) — the scheduled-task pattern: set once, runs forever
- [prompts/task-template.md](prompts/task-template.md) — how to instruct your assistant so work actually finishes

Related: [agent-dispatch-kit](../agent-dispatch-kit/) — the other half: the methodology for dispatching worker agents on your PC (dispatch → track → accept → advise).

## What this is NOT

- **Not remote-access software.** This kit contains no server code, no tunneling, no credentials. The private bridge in my own setup is private infrastructure and stays private for security reasons.
- **Not a shortcut around approvals.** Every sensitive action (spending money, sending messages, touching your accounts) needs your explicit approval first. Convenience never overrides consent.

## Security notes

- All templates use `[PLACEHOLDERS]` only. Never paste tokens, API keys, IPs, or personal paths into them.
- Credentials belong in a secure vault, never in chat, repos, or logs. If a secret ever appears in a chat screenshot or message, treat it as permanently leaked: revoke and rotate.

## License

MIT — see the repository root [LICENSE](../LICENSE). This directory's contents © 2026 Junjie Mi.
