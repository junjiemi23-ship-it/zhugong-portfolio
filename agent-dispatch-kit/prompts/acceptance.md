# Acceptance workflow: dispatch → track → accept → advise

## The loop

1. **Dispatch** — send a structured instruction ([dispatch-template.md](dispatch-template.md)) to a worker agent. One task, one instruction, no chatty follow-ups mid-run.
2. **Track** — poll for progress. A task that produces no output for too long gets flagged exactly once (in my setup: ~30 minutes of silence triggers one alert), then a human decides whether to wait, kill, or re-dispatch.
3. **Accept** — verify against the acceptance criteria, in two passes:
   - the dispatcher checks the evidence itself, then
   - a **second, independent model scores the report**: completion score (0–1), quality score, and an outcome classification (`success` / `partial` / `failed`).
   - The dispatcher makes the final call. Below the bar → back for rework. "The agent said it's done" is never sufficient evidence.
4. **Advise** — summarize for the human in five fixed sections: progress / goal met + scores / positive effects / negative effects & risks / suggestions and ideas.

## Why a second scorer

One model grading its own homework drifts toward "looks done". An independent scorer with no stake in the result catches what the worker — and the dispatcher — missed. In my own setup this role is played by the jev model; the sanitized pattern is in [scripts/jev-score-example.py](../scripts/jev-score-example.py). Any capable model works; the point is independence, not the brand.

## Cost note

Scoring calls cost money or quota, so score **at acceptance time only**, not continuously. For high-stakes acceptances, run the scorer twice (e.g. once in English, once in your own language) and compare the two before deciding.
