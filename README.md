# Zhugong's Granary

> Plugging AI into real workflows — automation projects that run and can be verified.

[中文版 → README.zh-CN.md](README.zh-CN.md)

Focused on **applied AI, multi-agent collaboration, and automation practice**, with lightweight web development and deployment skills. This is not a project-count list, but a personal portfolio organized around real problems, public evidence, and review write-ups.

[Live portfolio (Cloudflare Pages)](https://zhugong-portfolio.pages.dev/) · [GitHub profile](https://github.com/junjiemi23-ship-it) · [Email](mailto:junjiemi23@gmail.com)

## Featured

| Project | Problem it solves | My role & public evidence | Status |
|---|---|---|---|
| [chat2api-sft-toolkit](chat2api-sft-toolkit/) | Chat subscription quota goes unused every month, while SFT data labeling is expensive | Built batch Q&A generation and data-cleaning scripts (stdlib only) around the open-source chat2api project; published wiring pitfalls from real testing; bilingual docs | Practiced |
| [agent-dispatch-kit](agent-dispatch-kit/) | No unified way to dispatch, track, and verify work across multiple AI agents | Designed the three-layer architecture and structured dispatch/report prompt templates; dispatch → track → accept → advise workflow with independent second-model scoring | Practiced |

Every case shows "problem — role — process — verification" right on the homepage. Project directories carry the full code, methods, limitations, and public evidence.

## Capability matrix

| Capability | Practiced evidence |
|---|---|
| SFT & distillation data pipelines | Batch Q&A generation (resumable, exponential-backoff retries), data cleaning with dedup and filter stats, wiring pitfalls documented from real testing |
| Multi-agent dispatch & ops | Three-layer architecture, structured dispatch/report prompt templates, dispatch → track → accept → advise workflow with independent second-model scoring |
| Agent-oriented prompt design | One-click lazy prompt, acceptance criteria design, reusable bilingual technical docs |
| Lightweight web delivery | Pure HTML / CSS / JavaScript, responsive bilingual pages, Cloudflare Pages and GitHub Pages |

## Repo index

```text
zhugong-portfolio/
├── index.html             # Bilingual static portfolio homepage
├── assets/                # Public assets such as social preview images
├── chat2api-sft-toolkit/  # Turn Chat quota into SFT datasets (bilingual)
└── agent-dispatch-kit/    # One entry point to dispatch all agents (bilingual)
```

## Authenticity & AI collaboration

- I own the real requirements, the choice of approach, the public/risk boundaries, and the final human acceptance.
- AI tools (Codex, Work1, Work2, etc.) help with research, design discussion, drafting code or docs, debugging, and cross-review; AI-assisted content is never presented as fully hand-written.
- Only work that has run, been tested, or produced public evidence is marked "practiced"; plans and experiments are never dressed up as finished results.
- Numbers and statuses rest on code, self-test entries, repo files, or deployment results first; whatever can't be publicly verified is described qualitatively.

## Privacy & compliance

- Public content contains no real name, school, major, grade, phone number, address, IDs, student number, server IPs, device identifiers, keys, or auth codes.
- Projects touching login state, real business, or third-party platforms publish only methodology, placeholder configs, and sanitized examples — never raw data or scripts that could operate real business directly.
- Automation is limited to low-risk assistance and follows the relevant platforms' terms; trading cores, messaging, and other high-risk actions stay behind human confirmation.

## Run & contact

No build tools needed — just open `index.html` to preview locally. The live site is [zhugong-portfolio.pages.dev](https://zhugong-portfolio.pages.dev/).

Looking for an **internship in applied AI / agent automation**, also open to lightweight web development and deployment work: <junjiemi23@gmail.com>
