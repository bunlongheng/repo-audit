<div align="center">

<img src="logo-96.png" width="88" alt="repo-audit logo">

# repo-audit

**Reverse-engineer any repo through 10 audit lenses into one clean, self-contained HTML report.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8+-3776ab?logo=python&logoColor=white)
![Claude Code Skill](https://img.shields.io/badge/Claude_Code-skill-d97757)
![Read-only](https://img.shields.io/badge/mode-read--only-1a7f37)

</div>

Point it at **any** repository - a local path, an `owner/repo`, or a GitHub URL - and it reads the real
code across 10 audit lenses, grades each one A-F, and renders a single light-theme HTML report you can
open, share, or archive. Stack-agnostic: Next.js, Node, Python, Go, Rust, Java, anything.

It is strictly **read-only** - it never edits the target, never opens PRs, never runs the repo's own
code. It reads, judges, and renders.

See [`golden/sample.html`](golden/sample.html) for a full example report.

## The 10 lenses

1. **Architect** - layering, data flow, coupling, seams, plus an evidence-pinned architecture diagram.
2. **Good / Bad / Ugly** - an honest three-column read (report-only, never graded).
3. **Infra** - build, CI/CD, deploy, containers, env/config handling.
4. **Security** - secrets, auth gaps, injection, dependency CVEs, headers (defensive review only).
5. **Performance** - N+1 queries, bundle size, hot-path I/O, caching; optional Lighthouse on a live URL.
6. **Code** - type coverage, lint, dead code, duplication, complexity, churn hotspots.
7. **Tests** - what the suite has vs what it should have (judged statically, never executed).
8. **Docs** - README/docs currency, env-var drift, and MCP/CLI/REST interface staleness.
9. **UI/UX** - visual consistency, UX states, a11y, responsiveness (skipped for BE-only repos).
10. **Features** - a reverse-engineered feature tree, graded on coherence.

Each finding is anchored at `path:line`, carries a severity/confidence/effort badge, and the top fixes
across all lenses are ranked into a "Top Fixes First" action list.

## Quick start

```bash
# 1. Produce a data JSON for the repo (see the contract at the top of render.py).
#    Running as a Claude Code skill does this for you across the 10 lenses.
# 2. Render it to a self-contained HTML report:
python3 render.py path/to/data.json
# -> writes reports/repo-audit-<repo>-<date>.html
```

**Requirements:** Python 3.8+ (standard library only). Node + Playwright are optional, and only
needed for the README-screenshot helper (`node render-readme-shot.mjs <repoPath>`).

## As a Claude Code skill

Install:

```bash
cp -R repo-audit ~/.claude/skills/repo-audit
```

`SKILL.md` is the full operating spec. Drop this repo into `~/.claude/skills/repo-audit` (a symlink
works) and invoke it:

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
architecture diagram, and writes one self-contained file (all CSS/JS/icons inlined). Nothing about
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
