# Operations: hard-won lessons from running this daily

Everything below was learned the painful way, on a setup that runs every day.
None of it is hypothetical. Adapt the specifics to your own channel.

## 1. Restart discipline: never kill the server from inside the channel

The single most expensive mistake: issuing a "restart the server" command
*through the channel the server itself is serving*. The client hangs waiting
for a response that will never come, and the whole channel goes dark — the
only recovery is physical access to the machine.

The fix is a **delayed, detached restart**: a separate script that sleeps a few
seconds, kills the old server process, waits again, then launches a fresh one.
The thing that kills the service must never be the service itself.

## 2. The blocking red line

Never run a potentially unbounded wait inside the control channel — no
unlimited stream reads, no waiting on process exit without a hard timeout.
One stuck call wedges the entire channel, and again the only fix is walking
over to the machine. Put hard timeouts on the *script side*, not in your head.

## 3. Timeouts: degraded is not dead

Under a degraded network, a simple "list tasks" call can take minutes to
return. Lessons:

- Give health probes a generous timeout (in my setup: at least 200 seconds)
  before declaring the channel dead. A 25-second probe that gives up is a
  misdiagnosis, not a diagnosis.
- Before announcing death, check the independent patrol state (a separate
  scheduled checker is the ground truth). If the patrol succeeds while your
  manual probe fails, the problem is your probe or your environment — not
  the channel.

## 4. Environment inheritance traps

On Windows, `setx` writes to the registry but does **not** affect already
running processes — and a new process spawned by the old server inherits the
old environment. Consequences:

- After changing the runner whitelist, the server **must** be restarted, or it
  keeps enforcing the old one.
- Make the start script re-read configuration from the registry on every
  launch, so restarts never go stale.
- After a restart, wait 8–10 seconds before verifying: a probe fired too early
  hits the not-yet-dead old process with the old whitelist.

## 5. Whitelist workflow

- The whitelist is data, not code: a JSON map of runner name → executable +
  fixed arguments.
- The per-task instruction is appended as a **single argument** after the
  whitelisted argv. It cannot carry CLI flags (they break argument parsing).
  Fixed flags belong in the whitelist entry or the runner's own config file —
  never in the per-task text.
- After any whitelist change, verify each runner with a **minimal task** before
  trusting it. Silent zero-execution failures (exit 0, nothing actually ran)
  are the worst kind — the whitelist looked fine.
- Pin models to free tiers in the whitelist entry. A runner's default model
  can change or hit a quota wall; an explicit pin keeps costs predictable.

## 6. Acceptance operations

- A task that produces no log output for ~30 minutes gets flagged **once**,
  then a human decides: wait, kill, or re-dispatch. Alerting every cycle is
  noise; alerting once is signal.
- The second scorer only scores. The dispatcher makes the final call, and a
  failed acceptance goes back for rework — no exceptions for "but it said
  it's done".
- For high-stakes acceptances, run the scorer twice (e.g. once in English,
  once in your own language) and compare before deciding.

## 7. Token and audit hygiene, from day one

- The channel token lives in an environment variable or a `0600` file. It
  never enters code, chat logs, or screenshots. If it ever does, treat it as
  compromised and rotate — there is no "but I was careful".
- Keep an append-only local audit log of every call, including rejected ones.
  When something goes wrong at 2am, the log is the difference between
  debugging and guessing.

---

*These notes describe operational experience, not a product. Your channel,
your machine, your responsibility — start conservative (whitelist-first,
async-by-default, audit-from-day-one) and widen only after the basics are
boring.*
