# Worker-agent dispatch template

Copy the block below, fill in the `[BRACKETS]`, and paste it to your worker agent.
(Technical instructions are in English on purpose — it's the working language most models follow best.)

```text
## Objective
[One paragraph: what "done" looks like. Be concrete.
e.g. "Clean data/raw.csv into data/clean.csv: drop rows with empty email,
dedupe by user_id keeping the latest row."]

## Constraints
- [e.g. Read-only on data/raw.csv; write only to data/clean.csv]
- [e.g. Do not install new packages; do not access the network]
- [e.g. If blocked for more than [N] minutes, stop and report instead of guessing]
- [e.g. Never spend money, send messages, or touch accounts]

## Acceptance criteria
- [e.g. data/clean.csv exists, header row unchanged, row count reported]
- [e.g. A 20-row random sample passes manual review with zero format errors]

## Context (optional)
[Repo path, relevant docs, prior decisions — or "none".]

## Report-back format
Reply using prompts/report-template.md: Done / Evidence / Risks & open questions.
Do not mark the task done without evidence for every acceptance criterion.
```
