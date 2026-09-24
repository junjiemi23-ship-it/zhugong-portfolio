# Quickstart: the smallest setup that works

You don't need the perfect setup. You need a conservative one that you can
widen later. Five steps, in order — don't skip step 5.

## 1. Get the two ends on the same private network

Install Tailscale (or any private mesh network you trust) on both your
computer and your cloud machine. Approve the cloud machine on the admin
console. Confirm each side sees the other's private IP (e.g. `100.x.y.z`).

*Why this first:* no public ports, no port forwarding, nothing for scanners
to find. If you can't explain why your alternative is equally closed, don't
use the alternative.

## 2. Bind the server to the private IP, token via environment

Run your control server bound **only** to the private IP. The auth token goes
in an environment variable or a `0600` file — never in code, chat, or
screenshots. Start it, then verify from the other end that the private IP
responds and the public internet doesn't.

## 3. Whitelist one or two runners, nothing more

Start with one or two worker agents in the whitelist (a JSON map of name →
executable + fixed args). Pin each to an explicit model, preferably a free
tier. You can add more runners later; every entry is attack surface until
proven otherwise.

## 4. Verify each runner with a minimal task

Send the smallest real task ("create a file with content X in directory Y,
then report back") and check the full loop: dispatch → track → accept →
advise. Watch specifically for silent zero-execution (exit 0, nothing ran).
Only widen after the basics are boring.

## 5. Turn on the audit log on day one

Append-only, local, every call including rejected ones. You will not regret
this at 2am.

## Conservative defaults (until bored)

- Whitelist-first: if it isn't whitelisted, it doesn't run.
- Async by default: long tasks never block the conversation.
- Write the acceptance checklist *before* dispatching real work.
- One alert per stuck task, then a human decides.
- Token hygiene is binary: leaked once = rotated, no exceptions.

When all of the above feels uneventful, you're ready to widen — add runners,
loosen permissions, automate more. Not before.
