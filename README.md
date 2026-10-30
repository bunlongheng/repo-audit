<div align="center">

<img src="logo-96.png" width="88" alt="repo-audit logo">

# repo-audit

**Reverse-engineer any repo through 10 audit lenses into one clean HTML report.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8+-3776ab?logo=python&logoColor=white)
![Claude Code Skill](https://img.shields.io/badge/Claude_Code-skill-d97757)
![Read-only](https://img.shields.io/badge/mode-read--only-1a7f37)

</div>

Point it at **any** repository - a local path, an `owner/repo`, or a GitHub URL - and it reads the real
code across 10 audit lenses, grades each one A-F, and renders a single light-theme HTML report you can
open, share, or archive. Stack-agnostic: Next.js, Node, Python, Go, Rust, Java, anything.

It is **read-only** - it never edits the target, never commits, never opens PRs, and never runs the
repo's own code. It reads, judges, and writes one report to `./reports/` in the directory you run it
from. Two things are opt-in and off by default, because both leave a trace outside the report:
`--issues` files the top fixes as GitHub issues, and `--shot` writes a README screenshot.

See [`golden/sample.html`](golden/sample.html) for a full example report.

## The 10 lenses

1. **Architect** - layering, data flow, coupling, seams, plus an evidence-pinned architecture diagram.
2. **Infra** - build, CI/CD, deploy, containers, env/config handling.
3. **Security** - secrets, auth gaps, injection, dependency CVEs, headers (defensive review only).
4. **Performance** - N+1 queries, bundle size, hot-path I/O, caching; optional Lighthouse on a live URL.
5. **Code** - type coverage, lint, dead code, duplication, complexity, churn hotspots.
6. **Tests** - what the suite has vs what it should have (judged statically, never executed).
7. **Docs** - README/docs currency, env-var drift, and MCP/CLI/REST interface staleness.
8. **UI/UX** - visual consistency, UX states, a11y, responsiveness (skipped for BE-only repos).
9. **Features** - a reverse-engineered feature tree, graded on coherence.

10. **Good / Bad / Ugly** - the closing verdict: an honest three-column read, written last from the other 9 lenses and the files none of them own. The only lens that records what is GOOD (report-only, never graded).
Each finding is anchored at `path:line`, carries a severity/confidence/effort badge, and the top fixes
across all lenses are ranked into a "Top Fixes First" action list. Every critical/high finding is
adversarially verified by a second agent whose only job is to refute it, and every citation is then
checked mechanically by `verify.py` before the report is rendered - a claim that cannot be pinned to
real code does not ship as fact.

## Quick start

```bash
# 1. Produce a data JSON for the repo (see the contract at the top of render.py).
#    Running as a Claude Code skill does this for you across the 10 lenses.
# 2. Run the evidence gate. Every path:line is checked against the real tree - inside it,
#    absolute and ../ citations FAIL - and the quoted snippet is looked for within 20 lines
#    of the cited line. FAIL is dropped; WARN (nothing could be confirmed, including
#    evidence that quotes no code) is kept at Low confidence. Deterministic, zero tokens,
#    exits 0 so it can sit inside a pipeline.
python3 verify.py path/to/data.json --repo /path/to/repo --prune
# -> writes path/to/data.verified.json and prints PASS / NEAR / WARN / FAIL per finding
# 3. Render the verified data to one HTML report:
python3 render.py path/to/data.verified.json
# -> writes reports/repo-audit-<repo>-<date>.html   (--out names it, --no-open keeps it closed)
```

Run the contract tests (standard library only, same as CI):

```bash
python3 -m unittest discover -s tests -v
```

**Requirements**

| Need | Used for |
|------|----------|
| **Claude Code** | required - `SKILL.md` is the operating spec an agent follows across the 10 lenses. The Python here only renders and verifies what that agent produces; it makes no judgments of its own. |
| **Python 3.8+** | `render.py` and `verify.py`, standard library only - nothing to install |
| `gh` CLI, signed in | optional - live GitHub signals in the infra lens, and `--issues` |
| Node + Playwright | optional - only for `--shot`, the README screenshot helper |

## As a Claude Code skill

Install:

```bash
git clone https://github.com/bunlongheng/repo-audit.git ~/.claude/skills/repo-audit
# or, without git history:
npx degit bunlongheng/repo-audit ~/.claude/skills/repo-audit
```

`SKILL.md` is the full operating spec. The repo IS the skill folder - clone it straight into
`~/.claude/skills/repo-audit` (a symlink works too) and invoke it:

```
/repo-audit                     # audit the current directory
/repo-audit owner/repo          # clone + audit a GitHub repo
/repo-audit . --only=security   # run a single lens
/repo-audit --issues            # file the top fixes as GitHub issues (allowlisted owners only)
```

The skill fans the 10 lenses out to parallel agents (read-only, independent), then synthesizes the
top fixes and the overall grade.

## How the report is built

The renderer is the single source of truth for the HTML. You hand it a JSON object (the judgment);
`render.py` maps grades to scores, draws the donuts and grade badges, lays out the findings and the
architecture diagram, and writes one self-contained file (all CSS and report data inlined; Font Awesome, Chart.js and the brand logos load from public CDNs, so the layout and every word survive offline while the icons and donuts do not). Nothing about
the look lives outside `render.py` - edit it there.

## Optional integrations

All off by default - the report always writes to disk regardless:

| Env var | Effect |
|---------|--------|
| `AUDIT_POST_URL` + `AUDIT_POST_TOKEN` | POST the rendered report as `{title, content, type: "html"}` to your own endpoint |
| `REPO_AUDIT_ICON_REGISTRY` | A directory of `<repo-short>.png` icons to resolve a header badge when the repo has none |
| `REPO_AUDIT_ISSUE_OWNERS` | Comma-separated GitHub owners allowed to receive `--issues` filings |

## License

MIT - see [LICENSE](LICENSE).

## Try it first

```bash
python3 render.py golden/sample-data.json   # -> reports/repo-audit-orders-api-<date>.html
```

---

<div align="center">

<a href="https://bunlongheng.com"><img src="https://img.shields.io/badge/-bunlongheng.com-3A3A3C?style=for-the-badge&amp;labelColor=2A2A2C&amp;logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAMAAABF0y%2BmAAADAFBMVEXx8vLq6v%2F19fX09PT8%2Ff309PT5%2BfnAwMBMaXHx8vL19fX5%2Bfny8vL09PT39%2Ff6%2Bfn6%2Bvr09PTx8fH4%2BPn%2F8vLy8%2FP09PTz8%2FPy8vL%2F%2F%2F%2Fz9PTz9PP19fby8vP19PXz8%2FT19%2Fb08%2FTx8vLy8vL09vby8%2FL29vf19fTv8PDz9vb7%2Bvn%2F%2Ff%2F9%2Ff3w8vH29fb%2F%2FP339%2Ff5%2Bfn59%2Ff19PT09PR7rao3VF3%2F%2Fv8AKDR6sqsBV1vv8fL4%2BPiux8b8%2Bvq90NDy8%2FR%2BlpppnZyZqrACLTxclZJSkI9en5ssZ2luqaUAeWgqbW4BX1gCfG0%2Fa3QaVG0MN0UKNUKUpKsGpYMAKjoRQ1UDf3AQRloJqIgEm32d0cUBg3ElbnQIln8eVWgrmIdP0KzF5d5s2acdfHwppJCP5MMXl4Tz8%2FLv8%2FP39%2FiewL5%2BqahYf4IrTFZkk5KlxsREiIYAHiqDnKFmnJowc3IdVllvpKK7zc3D2tnk5%2BmuycdwpKKuub2yv8Ly%2B%2FkAMT7z%2Bvjq7e09gH93q6kGdWpGgoJZmJSlw8M7c3WwyceTw76w1M8mYmpFfX8lW2AFOEpGiYhxqqRrqaRb2rdIsZ8AVE91jpU7d3t3saqBoKhako4AWVEcUlg3aWwDupAHb2YwmIkPP1ERSVA7WmZ8tq8HT14oZW%2BYuLsMl3wQT10ROksENUc8Z3MJSGVLh4dqpJ%2BXr7U51awUgHM4v6ad1MkPuJZAiowVd3IEhnZH0aoYrI05p5sDtYwkzZ8EPViYxsRel5USbHAIgmwIM0gQamzU4uF2malQi4oWQFQ1zaYrp4UXlYwfiHoyxqFE1q4qeX4yn5JIxKkdrX1b1rAbWGvd5Oh91sRijpomsJEVc3Ukc34dqIcwuJVKwZIXkoQZcXlNv5g%2BqZUZvpNl2rPG9N0WkIoNqouW4sVPwp%2BM0b6h0ssfq4d%2F1r8hpo%2Fh9e4AamUjnI9avaBixqgklYWSwL4xtItUxplYl5qZ58mq78wMgnYXfnlOmJaR1L%2Bj78ny9fS%2FrXQPAAAAFXRSTlP7Brvx%2FsJhAgD87r4U72C4uGH8vhRDodYHAAAACXBIWXMAAAsTAAALEwEAmpwYAAAC6UlEQVQokS2Sd3BUVRSHb0KS3QRCiZw5t%2By9j33zXjZkyUs2uekhEAi9dwRCL4JUEQRFAQUs9A4WOopKU0GpFoqCBZUivaqoFKkWLIS5GX7%2FfnPO78yZj%2Fj8UTViK6HggvNgSGuluEZRKbZqlN9H%2FFWiWUzIFQK5fhjOIRTDoqv4ia86S4q3KSByHdSqIhxofBKr5iNxLMm2bQqWVkorJ%2BAkO46nkQJhceSRmCTDvKJIJBLJzMxMLU6POJ4eBPF1KpNEbdt2Cms4LCcnZ%2FX6D3d%2BsKJJ7VSlNLoqgbjUtmkKKxlVmpf3bsFXW3d1b77gueJAQIPQBCilkMKemNi23Ts9T35%2FaMe2rsvmTypylGUFCSIYWJLXrm2nUwOPfNO5w%2B73Okxnjqe0JigQEL3JizoeONr%2F2u99vju4fd1rdZnyspQmnGvAUBprWNqz348%2FhXN%2F6P1%2By4Uvs%2FJkpRQRwpJBRVn7vf16Dfitz5XevQqWt3yalXtKaRIUQmglWfsu5y7%2BMrDs0TMftWo1ZVy64xioOVpcIdt8%2Fvqvf9%2F859KJsrLmrzA%2BOKC0IkFEtJza7JOfr%2FYd0P9G98tdOxe0Hp9qJrOIBgDuOeEtp%2F%2B4d%2FvWX%2F%2F9u%2B%2FtlaUTmOWZg7SQEEyuFe52%2BML9O3cZO%2F5xl06zn2VcadOJUqJTzt7a82XfP7sx9vmGNm1m1MstV4IHCVAAoTLqL1372ddn%2Fz%2B2v%2FWq12c1fSpsaeQWAZAANntxzuI3e3zbo8XGpm%2FMnNqiXrh%2BljaPd6UUabkjps19tdGnX2zKb9b4pTFDCzOMLmYtpW5h%2BpCRTeYtyV%2BT36zx808OL4xYGoFrkqDTbJpSXLdRgwbPZL%2BQnT129OOPFVEEsAMJpHKdeKMJgJSAiALdjJANQKnRJI4R6boAKEwLCiGoBBegQjBftQo1KQWOlplFKSV9qGaF1NpAE7QQESTlMSy6pp%2F4%2FFFVYxMNRBTaiM0tkImxNaL8vgfDR8gvoYRaxgAAAABJRU5ErkJggg%3D%3D" alt="bunlongheng.com"></a>
<a href="https://www.linkedin.com/in/bunlongheng/"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white" alt="LinkedIn"></a>
<a href="https://www.instagram.com/ibunlong/"><img src="https://img.shields.io/badge/Instagram-C13584?style=for-the-badge&logo=instagram&logoColor=white" alt="Instagram"></a>
<a href="mailto:bheng.code@gmail.com"><img src="https://img.shields.io/badge/Email-2E7D32?style=for-the-badge&logo=gmail&logoColor=white" alt="Email"></a>

<br>

Built by **[Bunlong](https://bunlongheng.com)** &nbsp;&middot;&nbsp; [more apps](https://bunlongheng.com/projects)

</div>
