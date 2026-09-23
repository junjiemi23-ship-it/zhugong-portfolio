# Worker-agent report-back template

The worker agent replies in this shape — no free-form "all done".

```text
## Done
[What was completed, in one paragraph.]

## Evidence
- [One bullet per acceptance criterion, with the artifact that proves it.
  e.g. "data/clean.csv: 1,832 rows (was 2,000); filter reasons listed in
  data/filter_reasons.txt; 20-row sample reviewed, 0 format errors."]

## Risks & open questions
- [Anything uncertain, skipped, approximated, or needing a human decision.
  e.g. "3 rows had conflicting user_id timestamps; kept the latest — confirm?"]
- [If none: write "None."]
```
