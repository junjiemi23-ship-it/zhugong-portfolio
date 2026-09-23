# Architecture: one entry point, many workers

## The three layers

1. **You** — express intent only. You talk to exactly one assistant, from your phone, from anywhere.
2. **Cloud assistant (the dispatcher)** — understands intent, splits it into tasks, picks the right worker agent per task, sets acceptance criteria, tracks execution, verifies results, and reports back.
3. **Your own computer (execution)** — runs the worker agents (coding CLIs, scripts, models) and reports back in real time over an encrypted channel you control.

You are never required to sit in front of the execution machine. The chain keeps moving while you're away.

## Design principles

1. **Single entry point.** You never juggle five agents in five apps; you talk to one dispatcher. Every other agent is behind that door.
2. **Orchestration decoupled from execution.** The dispatcher doesn't care which worker runs a task. When a cheaper / faster / stronger agent appears, you swap the worker — your entry point, habits, and the assistant's memory of you stay untouched. No vendor lock-in.
3. **Agents talk in protocol, not vibes.** Human → agent can be fuzzy; agent → agent must be structured. Instructions go out as objective / constraints / acceptance criteria; reports come back as done / evidence / risks. Structured I/O is what makes the "99%" reliable instead of lucky.
4. **Acceptance is a gate, not a feeling.** The loop is dispatch → track → accept → advise. A second, independent model scores completion and quality; the dispatcher makes the final call. Failed acceptance goes back for rework — "the agent said it's done" is never sufficient.
5. **Red lines are hardcoded, not prompted.** Spending money, sending messages on your behalf, touching accounts — never automatic, no matter how nicely the task is phrased.

## Known limitations (the remaining 1%)

- Offline, power cut, or the machine asleep = channel down. A periodic patrol marks the outage and resumes automatically on recovery. The rest is physics, not software.
- Intent understanding is the single bottleneck: everything downstream depends on the dispatcher truly getting what you meant. That's why principle 1 matters — one assistant that remembers you beats five that don't.
