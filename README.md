# Zhugong's Granary

> Plugging AI into real workflows — automation projects that run and can be verified.

[中文版 → README.zh-CN.md](README.zh-CN.md)

Focused on **applied AI, multi-agent collaboration, and automation practice**, with lightweight web development and deployment skills. This is not a project-count list, but a personal portfolio organized around real problems, public evidence, and review write-ups.

[Live portfolio (Cloudflare Pages)](https://zhugong-portfolio.pages.dev/) · [GitHub profile](https://github.com/junjiemi23-ship-it) · [Email](mailto:junjiemi23@gmail.com)

## Featured

| Project | Problem it solves | My role & public evidence | Status |
|---|---|---|---|
| [codex-quota-monitor](codex-quota-monitor/) | AI tools don't push status alerts; watching signals by hand means missed or duplicate nudges | Defined alert boundaries and acceptance scenarios; drove the state machine, flip dedup, and debounce design; published a zero-dependency Python script, config templates, and three offline self-test entries | Practiced |
| [phone-automation](phone-automation/) | Under WebView, custom-drawn UI, or dark mode, element trees and color detection can't reliably locate targets | Provided labels and verified results; chose the "human labeling + pixel diff" approach and set low-risk automation boundaries; published methodology, pseudocode, and sanitized diagrams | Practiced |

Every case shows "problem — role — process — verification" right on the homepage. Project directories carry the full code, methods, limitations, and public evidence.

## Capability matrix

| Capability | Practiced evidence |
|---|---|
| Applied AI & automation | Python status monitoring, SMTP notifications, cron patrols, state machines with flip dedup |
| Multi-agent collaboration | Written mandates, role split, handoff files, human review gates, pre-publish verification |
| Device & browser workflows | ADB / scrcpy phone control chain, Chrome access, proxy rule routing and fault localization |
| Lightweight web delivery | Pure HTML / CSS / JavaScript, responsive bilingual pages, Cloudflare Pages and GitHub Pages |
| Research & docs | Open-source intel verification, decision-chain records, privacy sanitization, reviewable hands-on docs |

## Practiced / more

- [chat2api-sft-toolkit](chat2api-sft-toolkit/): turn idle Chat subscription quota into SFT datasets — batch Q&A generation, data cleaning, and pitfall notes around the open-source chat2api project ([中文版](chat2api-sft-toolkit/README.zh-CN.md)).
- [overseas-deploy](overseas-deploy/): deployment choices, Cloudflare Pages / GitHub Pages, SEO migration and incident review; this site is itself the deliverable.
- [web-research](web-research/): open-web resource discovery and structured write-ups; the first case documents evaluating a free cloud resource, claiming it, and preventing renewal charges.
- [docs](docs/): multi-agent co-management protocol and public collaboration method — role boundaries, review gates, risk red lines.
- [二手数码套利监控实战文档](docs/articles/二手数码套利监控从零搭建实战.md) (Chinese): sanitized review from requirements breakdown to an automated pipeline.

## Repo index

```text
zhugong-portfolio/
├── index.html             # Bilingual static portfolio homepage
├── assets/                # Public assets such as social preview images
├── chat2api-sft-toolkit/  # Turn Chat quota into SFT datasets (bilingual)
├── codex-quota-monitor/   # Python status monitoring & notifications
├── phone-automation/      # ADB / scrcpy and human-in-the-loop vision
├── overseas-deploy/       # Lightweight web deployment & reachability review
├── web-research/          # Open-web resource discovery & verification
└── docs/                  # Method docs, articles, collaboration agreements
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
