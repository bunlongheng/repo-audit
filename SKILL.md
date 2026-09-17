---
icon: fa-magnifying-glass-chart
name: repo-audit
description: Reverse-engineer ANY repo through 10 lenses (architect, infra, security, performance, code quality, tests, docs, UI/UX, features, good/bad/ugly) into one clean HTML report
argument-hint: "[github-url|owner/repo|path] [--branch=main] [--only=lens[,lens...]]"
user-invocable: true
---

# repo-audit - Reverse Engineer any repo, 10 lenses, one HTML report

Point this at ANY repository (a local path, an `owner/repo`, or a GitHub URL) and it
reverse-engineers the codebase across 10 audit lenses, then renders ONE clean
light-theme HTML report. This is the general, stack-agnostic auditor: Next.js, Node,
Python, Go, anything.

## The 10 lenses (the "Reverse Engineer" mindmap)

1. **Architect Audit** - how it is built: layering, modules, data flow, key dependencies, design patterns, coupling/cohesion, where the seams are. Grade A-F.
2. **Infra Audit** - build, CI/CD, deploy, containers, env/config handling, hosting, scripts, IaC. Grade A-F.
3. **Security Audit** - committed secrets, auth gaps, injection (SQL/command/XSS/SSRF), dependency CVEs, missing headers, OWASP-style issues, exposed service keys. Grade A-F.
4. **Performance Audit** - N+1 queries, missing indexes, bundle size, render/hydration cost, sync I/O on hot paths, caching, chatty network. Grade A-F.
5. **Code Quality Audit** (label: "Code") - type coverage, lint, dead code, duplication, naming, complexity, error handling. Grade A-F, plus a few metrics. (Tests moved to their own lens.)
6. **Tests Audit** (label: "Tests") - what tests the repo HAS and what it SHOULD have. Inventory the existing suite: frameworks (jest/pytest/go test/junit), test types (unit/integration/e2e), file counts, coverage signals (coverage configs, committed reports, CI test steps). Then judge the gaps: untested critical paths (cross-reference the churn hotspots), missing error-path tests, no e2e on the core user flow, assertion-free or snapshot-only spam. Judged STATICALLY - never execute the suite (see Rules). Grade A-F: zero tests on a code repo = F, never N/A.
7. **Docs Audit** (label: "Docs") - judge the documentation AND the currency of any external-facing interface. Two halves: (a) **Docs** - is the README + other docs + diagrams actually helpful, honest, and matched to the code? Or is it thin, bloated with useless detail, or stale (describing files/commands/features that no longer exist)? (b) **Interfaces** - if the repo exposes an **MCP server, a CLI, or a REST/HTTP API**, how current is its documented surface? Stale or drifted interface docs are a real, high-priority issue because agents and consumers call the thing based on those docs. Grade A-F.
8. **UI/UX Audit** - ONLY when the repo has a user-facing surface (web pages, mobile screens, desktop UI): visual consistency (spacing/typography/color discipline, design-system usage vs one-off styles), UX states (loading/empty/error states, form validation feedback), accessibility (semantic HTML, alt text, focus/keyboard nav, contrast), responsiveness (breakpoints, overflow). Judge from the components/styles/templates in the code. Grade A-F. **BE-only repos (APIs, workers, Lambdas, CLIs, libraries): grade is `N/A` - the lens is then OMITTED from the report and scoring completely** (no card, no donut, excluded from the overall %). Nice docs do not mean nice UI/UX and vice versa - this lens is deliberately separate from Docs.
9. **Features Supported** - reverse-engineer WHAT the app actually does, rendered as a feature tree (the mindmap). Grade A-F = feature coherence: are the features complete, consistent, and scoped (A) - or a sprawl of half-built, overlapping, or abandoned features (D/F)? The tree stays the map; the grade judges its shape.
10. **Good, Bad, Ugly** - the CLOSING verdict, written LAST and rendered LAST: what is genuinely good, what is mediocre/risky, what is painful/embarrassing. It is the only lens that records POSITIVES (the other 9 emit problems and nothing else) and the only one that reports the character of the codebase rather than discrete findings. NO grade - report-only (owner request 2026-07-02: a verdict letter dilutes the honesty of the three columns). It never appears in the scorecard donuts.

## Usage

```
/repo-audit                              # audit the current working directory (all lenses)
/repo-audit ~/code/my-app                # audit a local path
/repo-audit owner/repo                    # clone + audit a GitHub repo
/repo-audit https://github.com/x/y       # same, from a URL
/repo-audit . --branch=feature/x         # audit a specific branch
/repo-audit --issues                     # audit + file the top fixes as GitHub issues (personal repos only)
/repo-audit --only=infra                 # run ONLY the infra lens - skip all others
/repo-audit --only=security              # run ONLY security
/repo-audit --only=infra,security        # run exactly these 2 lenses, nothing else
/repo-audit --only=tests,quality,docs    # any comma-separated subset of the 10 lens keys
/repo-audit ~/code/my-app --verify       # thorough MODE: parallel + adversarial refute-pass on high findings
/repo-audit ~/code/my-app --sequential   # rare MODE: force one-lens-at-a-time (default is parallel)
```

**Execution modes (ONE skill, no second workflow to maintain):** how the lenses run is a mode, not a separate tool. All modes use the same lens definitions + `render.py`.
- **Default = parallel:** fan the 10 lenses out to concurrent agents on the strong model via the `Workflow` tool, barrier, then synthesize + render. Same token cost as sequential, just faster. This is automatic - no flag needed.
- **`--verify` (aka "be thorough" / "ultracode"):** parallel PLUS an adversarial refute-pass that spends extra agents to disprove each high/critical finding. This is where a token surplus goes - higher confidence, more spend.
- **`--sequential`:** force one-lens-at-a-time. Rarely needed (tiny repos, debugging); the default parallel path is preferred.
Never fork a `repo-audit-parallel` copy - "parallel" is this skill's default mode, and duplicating it only causes drift.

**Valid lens keys for `--only`:** `architect`, `infra`, `security`, `performance`, `quality`, `tests`, `docs`, `uiux`, `features`, `gbu`

When `--only` is set: run ONLY the listed lenses. Skip scoping signals irrelevant to those lenses (e.g. skip Lighthouse if `performance` is not in the list). The report renders only the requested lens cards - the scorecard shows only those lenses, and `top_fixes` ranks only findings from them. This is the same full-depth judgment, just scoped - never a shallow pass.

Always READ-ONLY: it never edits the target repo, never opens PRs, never creates
tickets. It only reads code and produces the report.

## Step 0: Prereq check

```bash
# render.py present (hard)
[ -f ~/.claude/skills/repo-audit/render.py ] && echo "OK: render.py" \
  || { echo "MISSING: render.py"; exit 1; }
```

## Step 1: Resolve + scope the target

- **Local path or `.`**: use it directly. Confirm it is a git repo (`git -C <path> rev-parse`); if not, audit the files anyway and note "not a git repo".
- **`owner/repo` or URL**: clone (shallow) into `~/code/<repo>` if not already present; never under `/tmp`. Use the existing clone if it is there and on the right branch.
- Capture: repo display name, `repo_url` (if it has a GitHub remote, so file links work), branch, short commit SHA, and the local `path` (the renderer uses it to find the app's icon).
- **App icon (MUST - owner requirement): the report ALWAYS shows the icon of the app it audited, pinned top-right of the header.** The renderer resolves it automatically - it prefers the audited repo's own icon assets (`public/app-icons/<repo>.png`, `public/icon.png`, `public/logo.png`, favicon, `app/icon.png`, root `icon.png`/`logo.png`), then falls back to an OPTIONAL local icon registry (a directory of `<repo-short>.png` files pointed at by the `REPO_AUDIT_ICON_REGISTRY` env var; unset by default), then a monogram of the repo's initial - so it is NEVER empty. You normally do nothing beyond passing a correct `path`. To override, set `app_icon` in the JSON to an `https://`/`data:` URL, a filesystem path, or a bare registry key. If the app has no icon anywhere and you use a registry, drop one into `$REPO_AUDIT_ICON_REGISTRY/<repo-short>.png` so future audits resolve it.
- Detect the stack from manifest files: `package.json` (Next/React/Node), `requirements.txt`/`pyproject.toml` (Python), `go.mod` (Go), `pom.xml`/`build.gradle` (Java), `Gemfile`, `Cargo.toml`, etc. Record a short `stack` list.
- Build a richer `tech_stack` for the report's Tech Stack table (rendered above the Architect lens). Each entry is `{name, slug, url, category, version}`:
  - `slug` is the [Simple Icons](https://simpleicons.org) slug so the renderer can pull a clean brand icon from `https://cdn.simpleicons.org/<slug>` (e.g. `nextdotjs`, `react`, `typescript`, `tailwindcss`, `supabase`, `vercel`, `postgresql`, `python`, `go`, `docker`). If a tool has no Simple Icons match, omit `slug` and the renderer draws a monogram instead.
  - `url` is the tech's official site - the icon AND name link out to it (new tab). Always include it so each icon embeds to its source.
  - `category` (Framework, Language, Styling, Database, Hosting, Tests, etc.) is optional.
  - **`version` is REQUIRED - always fill it (owner request 2026-07-16: a blank version hides where the stack stands and is where real migration risk hides).** Dig it out, do not leave `-`: read lockfiles + manifests (`package.json`/lock, `requirements.txt`, `go.mod`, `Gemfile.lock`), pinned CDN/script URLs (`jquery-3.7.1.min.js`, `datejs/1.0`), asset/vendor version banners and headers, and framework version fields (a Shopify theme's `themeVersion` in `layout/theme.liquid`, a theme's `settings_schema.json` `theme_version`). Surface stale/mismatched versions as a real signal (e.g. USF assets generated for theme `5.0.0` inside a `9.1.0` theme). When a tech genuinely has no semver, use an honest marker instead of blank: a platform tier (`OS 2.0`), a language baseline (`ES6+`, `CSS3`), an account/portal id (`portal 21814028`), or a generation/runtime note (`gen v5.0.0`, `runtime`). Only leave `-` after a real attempt turned up nothing, and say so.
  - **Be comprehensive - list the WHOLE stack, not just 3-5 headline techs (owner request 2026-07-16).** Aim for the full real surface (often 15-25 entries): languages, framework(s), UI libraries and vendored JS/CSS libs (carousels, lightboxes, lazy-load, date utils), styling system, **fonts** (brand + Adobe/Google), **analytics** (GA4/gtag, Clarity, Hotjar), **marketing/embeds** (HubSpot, Klaviyo), **third-party apps/services and their CDNs**, hosting/CDN, and databases. Discover them, do not guess: grep external script/style hosts (`src=`/`href=` to non-local domains), `@font-face` families and `use.typekit.net`, pinned CDN URLs (they carry versions), lockfiles/manifests, and vendored-asset banners. List real dependencies even when vendored or app-injected - label the version honestly (`vendored`, `runtime`, `legacy`, `gen v5.0.0`).
  - **Always include the testing / QA stack (owner request 2026-07-16).** Add entries for the test runner (jest, pytest, go test, vitest), e2e/visual (**Playwright**, Cypress, the repo's own visual-regression harness), and linters/type-checkers (eslint, theme-check, tsc, ruff). Use the version when pinned; for a QA tool that lives in a sibling/parent harness rather than the audited dir, still list it and label it honestly (`v9-regression`, `parent harness`). If a standard-expected QA tool for this stack is MISSING, you may list it with version `absent` to surface the gap at a glance (e.g. `Shopify theme-check - absent`) - this complements, not replaces, the Tests lens finding.
  - **Every entry MUST carry BOTH a real logo and a version - otherwise DROP it (owner request 2026-07-16: no blank logos, no blank versions).** Before locking an entry, verify it has (a) a working logo: a Simple Icons `slug` whose `cdn.simpleicons.org/<slug>` returns 200, OR a `url` whose favicon resolves - never a monogram; and (b) a version or honest marker per the rule above. If a tech cannot get a real logo OR cannot get any version/marker, do not render it blank - OMIT the row entirely. Better a shorter table of fully-populated, verified entries than rows with a missing logo or a `-`. State in the summary if you dropped any ("2 minor deps omitted - no verifiable logo/version").
  - When `tech_stack` is present it replaces the plain `stack` tags in the overview; keep `stack` too as a cheap fallback.
- **MANDATORY - scan scope (owner rule 2026-08-23: a report without Files + LOC is useless and will be rejected).** Fill `scanned.files` and `scanned.loc` in data.json EVERY run, no exceptions: `git ls-files | wc -l` for files, `cloc` if available else `git ls-files | grep -vE 'node_modules|vendor|dist|build|\.next|lock' | xargs wc -l` for LOC. render.py now HARD-FAILS if either is missing (it self-heals from `path` when it can, but never rely on that - compute and pass both).
- Gather **vitality signals** (git repos only - skip silently otherwise) into a `vitality` object, rendered as ONE quiet meta line under the pills (never a second pill row - owner request). Three cheap commands, big "is this repo alive" signal:
  - `git log -1 --format=%cr` -> `last_commit` (relative, e.g. "2 days ago" -> "2d ago")
  - `git rev-list --count --since=90.days HEAD` -> `commits_90d`
  - `git shortlog -sn --no-merges | head -10` -> `contributors` (line count of full output) and `bus_factor` (top author's share of total commits, e.g. "68% 1 author"; flag it in the architect lens as a finding when one author owns > 80% of a multi-user repo)
  - `git for-each-ref --format='%(committerdate:unix) %(refname:short)' refs/heads refs/remotes | awk` (or equivalent) -> `stale_branches` = branches with no commit in 90 days
- ALWAYS exclude from scans, greps, and LOC counts: `node_modules`, `vendor`, `dist`, `build`, `.next`, `.git`, coverage output, lockfiles, and generated/minified files. They blow context and poison findings.
- **Scale guard (monorepos / huge repos):** if source LOC > ~150k or files > ~3,000, do NOT pretend to read everything. Switch to sampling: audit the top-level packages/dirs by size plus the churn-hotspot files, fan the rest to sub-agents by subtree, and STATE THE SAMPLING in the report ("audited 4 of 11 packages: a, b, c, d - selected by size + churn"). A shallow audit that admits its scope beats a silent one that implies full coverage.

## Step 2: Run the lenses (this is the judgment - YOUR job)

**`--only` scoping (checked before Step 2):** if `--only=<lens>[,<lens>...]` was passed,
run ONLY those lenses. Parse the comma-separated list against the 10 valid keys
(`architect`, `infra`, `security`, `performance`, `quality`, `tests`, `docs`,
`uiux`, `features`). Error loudly on an unrecognized key. All other lenses are SKIPPED
completely - no stub, no N/A, just absent from the JSON and the report. `top_fixes` ranks
only findings from the requested lenses. The scorecard and overall % include only the
requested (graded) lenses. This is full-depth judgment on the selected scope, not a
shallow pass.

Read the real code. Do not guess. For each lens, form a grade (where graded) and write
a tight summary plus concrete points/findings. Anchor findings at `path:line` so the
report can link them. Use `frontend-design` sensibilities only for the OUTPUT, not the
analysis.

Per lens, gather:
- **architect**: `summary`, `points[]` (structure/flow observations, each anchored at `path:line`), optional `table` (e.g. Layer/Role), `grade`, an `arch_canvas` (MANDATORY - every repo, every run, no exceptions), and (when the repo has a clear core operation) a `critical_path`. The renderer leads the section with the diagram.
  - **`arch_canvas` is REQUIRED on EVERY audit run - no repo is exempt, no fallback to `stack_flow` (owner 2026-08-13).** Format: `{width, height, nodes:[{id,x,y,name,role,icon,color}], edges:[{from,to,label,dashed?}]}`. Free-form SVG node-graph - real brand icons, colored node borders, labeled arrows. Width 900, height sized to fit (400-600 typical).
  - **LOGO RULE - arch_canvas nodes MUST use the EXACT same verified icon as the tech_stack entry for that technology (owner 2026-08-13).** The `icon` field on each node must be `https://cdn.simpleicons.org/<slug>/<hexcolor>` using the SAME slug that was verified for the tech_stack table. Same priority order as tech_stack: verified simpleicons slug first (`https://cdn.simpleicons.org/<slug>`), then Iconify (`https://api.iconify.design/logos:<name>.svg`), then DuckDuckGo favicon (`https://icons.duckduckgo.com/ip3/<domain>.ico`) as last resort. NEVER use a generic placeholder, a monogram, or an unverified slug - if the slug returns 404 on simpleicons, use the next fallback. The diagram and the tech stack table must always show the same logo for the same technology - they are one consistent brand system. Known-correct slugs: `nodedotjs` (Node.js, green #339933), `express` (Express, black #000000), `react` (React, cyan #61dafb), `typescript` (TS, blue #3178c6), `nextdotjs` (Next.js, black #000000), `auth0` (Auth0, orange #eb5424), `docker` (Docker, blue #2496ed), `mysql` (MySQL, blue #4479a1), `postgresql` (Postgres, blue #4169e1), `amazondynamodb` -> use Iconify `logos:aws-dynamodb`, `amazons3` -> use Iconify `logos:aws-s3`.
  - Color-code node borders by role: `#3b82f6` blue for the app itself, `#f97316` orange for auth, `#8b5cf6` purple for external APIs, `#f59e0b` amber for databases, `#10b981` green for downstream services, `#ef4444` red for billing/payments. When `arch_canvas` is present it takes priority over `stack_flow` in the renderer.
  - **EVIDENCE-PINNED - the archify rule (owner 2026-07-29). Every node and every edge MUST trace to real code; never invent topology or claim runtime behavior you did not read.** Give each node a `src` (the `path:line` where it is actually wired up - the client component, the route handler, the `new Pool()`, the `pusher.trigger()`), and derive each `links[i]` protocol from the ACTUAL call site (open the fetch/query/subscribe line), not a guess. A node or arrow you cannot anchor to a file does not belong in the diagram. This is what makes the architecture verifiable instead of plausible-looking fiction.
  - `stack_flow` is DEPRECATED - never output it. `arch_canvas` replaces it on every repo type (FE, BE, mobile, CLI, monorepo). The visual node-graph is always more useful than a tier list.
  - `critical_path` = `{title, steps:[{n, label, src, note?}]}` (optional but strongly preferred). Trace the app's single most important operation end to end - e.g. "Create a note", "Serve a public share", "Auth a request" - as an ordered sequence with EACH hop pinned to `path:line`. This "how one real request actually flows" view catches architecture drift and dead/duplicate paths the static tier diagram hides.
  - **FAIL CLOSED (archify's ownership profile).** If you cannot establish a piece's placement, ownership, DB scope, or boundary crossing, SAY SO in the `summary` ("could not confirm X") - never paper over an unknown with a clean-looking edge. An honest gap beats an invented connection.
  - The `table` (file/module layers) still renders below the canvas as the detailed view.
- **gbu**: `good[]`, `bad[]`, `ugly[]` - specific, not generic. Name files/patterns. NO grade - report-only.
  **Runs LAST, after the other 9 have joined, and is handed their full findings digest.** Its job is
  what the lenses structurally cannot produce:
  - `good[]` is its own territory - 3-6 things the codebase genuinely does well, each pinned to
    `path:line`. No other lens reports a positive, so if GBU does not write it down the report never
    says anything good about working code.
  - `bad[]` / `ugly[]`: **do NOT restate a finding another lens already made** - you have the digest,
    so a duplicate is a choice, not an accident. Two things belong here instead: (a) defects in the
    files no lens owns - sweep `scripts/`, `public/`, root config, service workers, one-off utilities,
    anything that fell between the disciplines; (b) character observations that are not a discrete
    finding - "the biggest component holds 25 hook slots", "no design tokens, 8 hand-rolled button
    styles", "the same regex copy-pasted 3 times".
  Measured on a real run (2026-09-17): roughly half of GBU's bad/ugly restated findings from other
  lenses, while 5 real defects were caught by GBU ALONE because nothing else reads across territory -
  a `rejectUnauthorized: false` DB default, WHERE/ORDER BY built by string interpolation, a
  copy-pasted regex, an unreviewed service worker, and a script hardcoding a path into another repo's
  `node_modules`. That gap is what this lens exists to close.
- **uiux**: `summary`, `findings[]`, `grade`. Only judge repos WITH a user-facing UI - components, styles, templates, screens. Look for design-system discipline vs one-off styles, missing loading/empty/error states, a11y gaps (no alt text, no focus states, div-buttons), broken responsiveness. **BE-only repo: set `grade` to `"N/A"`** - the renderer then omits the lens from the report and scoring completely.
- **features**: `summary`, `tree[]` (the mindmap), `grade` (feature coherence - complete/consistent/scoped vs sprawl of half-built or abandoned features).
- **infra**: `summary`, `findings[]`, `grade`. Look at CI config, Dockerfiles, deploy scripts, env handling. If the repo has a GitHub remote AND `gh auth status` passes, add live GitHub health (all read-only, warn-only - skip silently if gh is absent/unauthed or the repo is not on GitHub): `gh pr list --state open --json number,updatedAt` (open PR count + how many are stale > 30 days), `gh run list --limit 5 --json conclusion` (is CI currently red?), `gh api repos/{owner}/{repo}/branches/<default>/protection` (404 = unprotected default branch - a finding for a multi-contributor repo). Config files say what SHOULD happen; these say what IS happening.
- **security**: `summary`, `findings[]`, `grade`. Grep for secrets, check auth on routes, deps.
  **Always open these by name, they are where the misses happen:** the DB/connection module (TLS
  verification defaults - a `rejectUnauthorized: false` is a finding, not a config choice), EVERY
  query-construction site (any WHERE/ORDER BY/LIMIT built by string concatenation or template
  interpolation is a finding even when today's inputs happen to be safe), the session/cookie module,
  and every handler that writes (is the row scoped to the owner, or addressed by id alone?). If `gitleaks` is installed (`command -v gitleaks`), also run `gitleaks detect --source <path> --no-banner --report-format json --report-path /tmp/gitleaks.json --exit-code 0` and fold its hits into findings - entropy-based detection catches tokens manual grep misses. Warn-only: if gitleaks is absent, note "gitleaks not installed, grep-only secret scan" in the summary and move on (same pattern as the dep scanners). NEVER print a real secret value in the report - cite the file:line and say "hardcoded token" instead. For dependency CVEs, do not guess from version strings - run the stack's real scanner when available (warn-only, never fix): `npm audit --json`, `pip-audit`, `govulncheck ./...`, `cargo audit`, `bundle audit`. If none is available, say the dep check was skipped instead of inventing CVEs.
- **performance**: `summary`, `findings[]`, `grade`, optional `metrics[]`. **Run Lighthouse when a homepage/domain URL applies (owner request 2026-07-16).** If the project is web-facing AND you have a public homepage/deployed URL - `package.json` `homepage`, a README badge/link, a known prod domain, or one the user gives - run it headless, warn-only: `npx --yes lighthouse <url> --quiet --only-categories=performance,accessibility,best-practices,seo --chrome-flags="--headless=new" --output=json --output-path=/tmp/lh.json` then read the four category scores (0-100). Put them in the performance lens `metrics` (`["Lighthouse Perf","82"], ["A11y","91"], ["Best Practices","83"], ["SEO","95"]`) so they render, and turn any weak score (< 80) into a finding. ONLY for a real homepage/domain URL - skip for libraries, CLIs, BE-only repos, or any repo with no deployed site, and skip (noting it) if `lighthouse`/`npx` is unavailable or the URL 404s. Never guess scores - omit the metrics if Lighthouse did not actually run.
- **quality**: `summary`, optional `metrics[]` (e.g. ["Types","strict"], ["Lint","eslint"]), `findings[]`, `grade`. Include **churn hotspot analysis** (git repos only): `git log --format= --name-only --since=6.months | sort | uniq -c | sort -rn | head -15` gives the most-changed files. Read the top 3-5 that are source files (skip lockfiles/docs) - a file that is BOTH high-churn AND complex/untested is where the next bug lives; flag those as findings ("hotspot: changed 41x in 6 months, 400 lines, zero tests"). A hot file that is clean is not a finding. Also check **dependency freshness** (separate from CVEs - a dep can be 3 majors behind with zero CVEs and still be a finding): `npm outdated --json` / `pip list --outdated` / `go list -u -m all` when the stack's tool is available (warn-only, skip if not). Report majors-behind counts as a metric (e.g. ["Deps outdated","6 major / 14 minor"]) and flag any core framework (React, Next, Django, the main runtime) more than one major behind as a finding with severity medium.
- **tests**: `summary`, optional `metrics[]` (e.g. ["Test files","42"], ["Framework","jest"], ["E2E","none"]), `findings[]`, `grade`. Inventory what EXISTS (frameworks, unit/integration/e2e split, coverage config + committed reports, CI test steps, test-file to source-file ratio) and flag what SHOULD exist: churn hotspots with zero tests, uncovered error paths, missing e2e on the core flow, snapshot-only suites with no real assertions. Static judgment only - NEVER run the suite (never-execute rule). Zero tests on a code repo = F, never N/A.
- **docs**: `summary`, optional `metrics[]` (e.g. ["README","320 lines"], ["Docs","4 files"], ["Diagrams","2 mermaid"]), `findings[]`, `grade`. Two halves:
  - **Env var drift** - inventory the env vars the code actually reads (`process.env.X`, `os.environ`, `os.getenv`, `ENV[`, `getenv(`) and diff against what is documented (`.env.example`, `.env.sample`, README setup section, docker-compose `environment:`). Two findings come out of this diff: **undocumented required vars** (code reads it, nothing documents it - the #1 "cannot run this repo" failure, severity high if the app crashes without it) and **dead documented vars** (in `.env.example` but nothing reads it - stale, severity low). List the exact var names in the evidence.
  - **Docs quality** - read `README.md` and every other doc (`docs/`, `*.md`, `CONTRIBUTING`, `ARCHITECTURE`, wikis, ADRs) and any diagrams (mermaid, images, excalidraw). Judge, do not summarize: does it help a newcomer run and understand the repo in minutes? Flag the three failure modes as findings - **unhelpful/missing** (no README, no quick-start, undocumented env vars), **bloated** (walls of low-signal detail, duplicated across files, auto-generated noise), and **stale** (references files/dirs/commands/flags/endpoints that no longer exist - verify each claim against the tree; a README listing `src/`, `lib/` that are not there is a finding). Note orphaned docs for removed features and dead diagrams.
  - **Interface currency** (only if the repo exposes one) - detect an **MCP server** (`mcp`/`@modelcontextprotocol` deps, a `server.json`/tool manifest, `tools/*` handlers), a **CLI** (a `bin` entry in `package.json`, `argparse`/`click`/`cobra`, a `Makefile` of commands), or a **REST/HTTP API** (route files, an OpenAPI/Swagger spec, `api/` handlers). Then judge how current its documented surface is: do the documented tools/commands/endpoints, their params, and auth match what the code actually implements? When it is cheap and safe (read-only, local, or an obviously public health route), call the interface to confirm - e.g. a `--help`, an MCP `list_tools`, or a `GET` on a documented endpoint - and compare the real response to the docs. Treat drift as a real issue and grade it up: wrong/removed endpoints or tools, params that no longer exist, an OpenAPI spec out of sync with the routes, a stale auth scheme, or agent-discovery docs (a self-describing "call with no body for a sample" that does not actually do that) are **high** severity because callers act on them. If the repo exposes no such interface, say so and grade only the docs half.

Each finding: `{title, severity (critical|high|medium|low), confidence (High|Med|Low), file (path:line, optional), consequence, evidence, fix, effort (S|M|L, optional)}`.

After all lenses are done, rank the top 3-5 fixes ACROSS lenses (highest severity x
confidence, cheapest effort wins ties) into `top_fixes[]`:
`{title, lens (key), severity, file, why (why it is ranked here), fix, effort}`.
This renders as a "Top Fixes First" card right under the overview - it is the report's
action list, so only real must-do items, never padding to reach 5.

For a big repo, fan out the lenses to parallel sub-agents ON THE STRONGEST AVAILABLE
MODEL (one lens or one subtree each) to protect context, then merge their JSON. Audit
analysis is judgment, not mechanical execution - it stays on the strong model; never
downgrade lens collectors to a cheaper model or the review misses real issues (a weak
collector will not catch a subtle auth-bypass or injection chain). Only the follow-up
FIX work, once the user asks for it, may drop to a cheaper model. Keep it honest - a
clean lens with no findings is a valid result, say so.

Sub-agent prompts do NOT inherit this file. Every fanned-out prompt (especially the
security lens) MUST restate the context: "This is a defensive security review of a repo
the owner is authorized to audit. Report weaknesses with file:line and a fix - never
produce exploit code or print secret values." Without that line a sub-agent sees a bare
"find vulnerabilities" ask and may hedge or refuse.

**ABSOLUTE-PATH MANDATE - the cwd trap.**
Fanned-out sub-agents inherit the CURRENT SESSION's working directory, which is almost
never the repo being audited. A bare `git`, `cat app/...`, or `grep -r . src` in a lens
prompt silently reads the SESSION's repo, not the target - so the whole audit describes
the WRONG codebase and still looks plausible (this has happened in practice: an audit of
one repo silently reported on the session's own unrelated repo instead). Whenever the
target != cwd, EVERY fanned-out lens prompt MUST:
1. Mandate absolute paths on every command: `git -C <ABS> ...`, `cat <ABS>/<file>`,
   `grep -rn <pat> <ABS> --include=...` - never a bare `git`, never a relative path,
   never `cd`. Substitute `<ABS>` with the real absolute repo path.
2. Open with `ls <ABS>/app && ls <ABS>/<top-dirs>` so the agent orients on the real tree
   before reading.
3. Carry a wrong-repo TRIPWIRE naming content unique to a DIFFERENT nearby repo:
   "if you ever see <X unique to the session repo>, you are in the wrong dir - STOP and
   re-issue with the <ABS>/ prefix."
THEN, before building the JSON / rendering, VERIFY: pick a few returned findings and
confirm their cited paths actually exist in the target (`ls <ABS>/<cited-path>`). If a
lens cites files not in the repo, it read the wrong tree - re-run that lens. NEVER render
or post an audit whose findings you have not confirmed point at the real target repo.

## Parallel execution (DEFAULT - faster with NO quality loss, owner 2026-07-29)

Run the lenses in parallel by default, not just on big repos. The 10 lenses are
read-only and independent, so they are a near-perfect parallel workload. Done right this
is faster AND higher quality - it is not a trade.

**The pipeline (what runs parallel vs sequential):**
1. **Step 1 scoping runs ONCE, sequentially** (stack, vitality, churn, npm audit, git
   signals). It feeds every lens - gather it before the fan-out.
2. **NINE lenses fan out in parallel** (a barrier: collect ALL before synthesizing). Group
   related lenses per agent on a small repo (`infra+docs`, `perf+quality`, `features`,
   plus dedicated `security` and `architect`) -> ~5-7 agents; on a big/monorepo do one
   lens per agent, or one subtree per agent, +1 completeness critic. **`gbu` is NOT in
   this wave.**
3. **`gbu` runs AFTER the barrier, fed every other lens's findings**, so it can be told
   what NOT to restate and can spend its read on the files no lens owns. Running it in
   the parallel wave was the old shape and it cost a duplicate full read of the repo
   while still colliding with half the findings.
4. **Synthesis runs sequentially AFTER the barrier** on the strong/orchestrating model:
   top_fixes ranking, the `delta` diff, and the overall grade all need every lens result
   in hand. Never rank or grade before the join completes.

**The two rules that keep quality from dropping (the whole point):**
- **Never downgrade the tier to go faster.** Every lens agent stays on the strong
  model. Speed comes from concurrency, not a smaller model - a cheap collector misses
  the subtle auth-bypass, injection chain, broken-privacy, or dead/duplicate topology,
  which is exactly what the audit exists to catch.
- **Fresh context per lens is a quality GAIN, not a risk.** One agent holding all 10
  lenses dilutes its window; N focused agents each get a full one. Parallelism improves
  depth as a side effect - do not "simplify" a lens prompt just because it now runs
  concurrently.

**Cost honesty: parallel is the SAME token cost as sequential - audit
is audit.** The same 10 lenses read the same code either way; concurrency only changes
wall-clock, never token count. So the default parallel run costs exactly what the old
one-after-another run did - a pure speed upgrade, no extra spend. The ONLY things that
add tokens are (a) an optional verify stage and (b) re-running - neither is caused by
parallelism. Do not expect parallel to be cheaper; expect it to be faster at equal cost.

**Adversarial verify is OPT-IN, not default.** A refute-pass on the
high/critical findings raises confidence but spends extra agents, so run it ONLY when the
user asks for it (`--verify`, "high-confidence", "be thorough") or the target is high-
stakes. The default audit is: scope once -> fan out lenses on the strong model -> barrier ->
synthesize. Adding verify must be a deliberate choice, never automatic - keep the default
at token parity with the old sequential run.

**Token savings live in the CACHE, not parallelism.** A `Workflow` resumes from cache
(same script + args = cached agent results for $0), so re-auditing an UNCHANGED repo is
nearly free and only changed lenses re-run. That is the real efficiency lever.

**Preferred mechanism:** the `Workflow` tool - a deterministic fan-out with a real
barrier (and an opt-in verify stage). Hand-launching background `Agent` calls works too
(that is how this skill has been run), but a Workflow makes the barrier, the join, and
the cache explicit and reproducible. Either way: scope once -> fan out on the strong
model -> barrier -> synthesize; add verify only on request.

## Step 2b: Onboarding Brief (merged from repo-recon, 2026-08-17)

Collect the onboarding data IN THE SAME RUN as the 10 lenses - no separate `/repo-recon`
invocation needed. Add a top-level `"recon"` block to the JSON (all fields optional;
omit any you cannot populate rather than leaving blank). This runs in parallel with the lens agents as one additional agent during the fan-out.

```bash
# churn hotspots - where work actually happens (6 months)
git -C <path> log --format= --name-only --since=6.months | grep -vE 'lock|\.snap' | sort | uniq -c | sort -rn | head -20
# file-type mix
git -C <path> ls-files | grep -vE 'node_modules|dist|\.lock' | sed -E 's/.*\.//' | sort | uniq -c | sort -rn | head -10
# PR mechanics: last 50 merged PRs
gh pr list --repo <owner/repo> --state merged --limit 50 \
  --json number,additions,deletions,changedFiles,author,mergedAt,createdAt > /tmp/recon_prs.json
gh pr list --repo <owner/repo> --state merged --limit 40 --json number,reviews > /tmp/recon_reviews.json
# CODEOWNERS
gh api repos/<owner/repo>/contents/.github/CODEOWNERS 2>/dev/null
```

Compute: median + p90 of (additions+deletions), median changedFiles, median merge time, who approves most (state==APPROVED). Branch convention from recent head names.

**`recon` JSON schema** (put this inside the top-level data object alongside the lenses):
```json
"recon": {
  "get_started": {
    "prereqs": ["Node 22+", "..."],
    "commands": [["npm install", "install deps"], ["npm run dev", "start server"]],
    "env": [["DATABASE_URL", "required, undocumented"], ["AUTH0_SECRET", "required"]],
    "first_hour": ["Run tests with npm test", "Read src/routes/"]
  },
  "where_to_work": {
    "hotspots": [["src/routes/account.ts", 34, "most-touched file"]],
    "key_dirs": [["src/routes", "Express route handlers"], ["src/services", "business logic"]],
    "ticket_map": [["Add an endpoint", "src/routes/ + src/services/"]]
  },
  "pr_process": {
    "branch_convention": "ACME-####-short-description",
    "median_loc": 76,
    "p90_loc": 320,
    "median_files": 4,
    "median_merge": "same-day",
    "approvals_note": "1 approval required",
    "review_model": "peer review, no CODEOWNERS",
    "top_reviewers": [["Alex Rivera", 29], ["Sam Chen", 12]],
    "ci_gates": ["lint", "typecheck", "unit tests"],
    "codeowners": "none"
  },
  "who_is_who": [["Sam Chen", "feature work, 25 PRs"], ["Alex Rivera", "reviews + infra"]],
  "work_nature": {
    "summary": "Mostly business-logic TypeScript with some Knex migrations",
    "breakdown": [["TypeScript business logic", "60%"], ["Config/YAML", "20%"], ["Tests", "20%"]]
  },
  "glossary": [["ORE", "Order Routing Engine - Acme's booking service"], ["BFF", "Backend-for-Frontend"]],
  "first_prs": [
    ["Add input validation to POST /account", "Low-risk, touches src/routes/account.ts", "src/routes/account.ts, src/middleware/validate.ts"],
    ["Add a missing unit test for recurly.service", "Tests lens gap", "src/services/recurly.service.ts, test/"]
  ]
}
```

`render.py` automatically renders the `recon` block as an "Onboarding Brief" section at the bottom of the report if the key is present. If `recon` is absent (e.g. `--only` scoped run), no section is rendered. **This replaces `/repo-recon` entirely - do not invoke that skill.**

## Step 2d: PRE-RENDER SELF-CHECK (MANDATORY before writing JSON - owner 2026-08-13)

Before writing `reports/repo-audit-data.json` or calling `render.py`, stop and run this checklist against your own output. Fix any failures before proceeding.

**Icon consistency (most common error):**
- [ ] Every `arch_canvas` node `icon` URL uses the EXACT same simpleicons slug as the `tech_stack` entry for that technology. Look up each node's technology name in `tech_stack`, copy the slug from there, and use `https://cdn.simpleicons.org/<SAME_SLUG>/<color>`. Do NOT pick an icon independently for the diagram.
- [ ] No `tech_stack` row has a blank `slug` AND no fallback `icon` URL - if simpleicons 404s, use Iconify or DDG favicon, never a monogram.
- [ ] Node.js: slug is `nodedotjs`, color is `339933` (green). Never purple.
- [ ] All slugs checked against the SLUG_FIX dict in `render.py` (dead slugs remapped there).

**Completeness:**
- [ ] `arch_canvas` is present - it is mandatory on every run, no fallback to `stack_flow`.
- [ ] Every arch_canvas node and edge traces to a real `src` file:line (not invented).
- [ ] No `tech_stack` entry has version `-` without a note explaining the search attempt.

**State before proceeding:** write one line: `self-check: passed` OR `self-check: corrected X` (list what you fixed). Then proceed to build the JSON.

## Step 3: Build the JSON + render (never hand-build HTML)

Write the run data to `reports/repo-audit-data.json` in the contract documented at the top
of `render.py`, then render. **Always set `data.args`** to the argument string that was passed (e.g. `"--only=infra"`) - it is rendered as a badge next to the chip in the top-left so the run scope is visible at a glance. **Always set `data.model`** to the name of the
model that performed the lens judgment for this run (match whatever ran the fan-out
lens agents, not the orchestrating session model if they differ). The renderer shows it
as a small colored badge next to the header chip - lets re-audits of the same repo by a
different model be told apart at a glance when comparing reports over time. The renderer
owns ALL html/css and writes the report to disk. Posting it somewhere else is optional -
see `AUDIT_POST_URL` / `AUDIT_POST_TOKEN` in `render.py`, off unless both are set.

```bash
python3 ~/.claude/skills/repo-audit/render.py reports/repo-audit-data.json
```

If the look must change, edit `render.py` - never inline HTML in this skill or in chat.

After rendering, archive the run data for re-audit deltas (gitignored, never synced):

```bash
mkdir -p ~/.claude/logs/repo-audit
cp reports/repo-audit-data.json ~/.claude/logs/repo-audit/<repo>-$(date +%Y-%m-%d).json
```

On a RE-audit (a previous JSON exists for this repo): diff findings by title+file
BEFORE rendering and put the result in the data JSON as `delta`
(`{prev_date, fixed[], new[], still, grade_moves[[lens,old,new]]}`) so the report
itself carries a "Since Last Audit" card - the HTML is the artifact that gets kept
and shared, not the chat. Then also lead the chat summary with the same delta.
Grades that moved get an arrow (C -> B).

## Step 3c: File the top fixes as GitHub issues (opt-in flag, PERSONAL repos ONLY)

Turn `top_fixes` into a living GitHub-issue backlog - but ONLY when explicitly asked via
the `--issues` flag, and ONLY on the owner's own personal repos. Default (no flag) files
NOTHING. This is a personal-testing feature; gate it strictly.

**Hard gate:**
1. **Opt-in flag present:** the invocation args include `--issues` (or `--file-issues`).
   No flag -> skip entirely, silently, no mention (the user did not ask). Filing is never
   automatic.
2. **Owner-allowlisted:** the owner parsed from `repo_url` is in the `REPO_AUDIT_ISSUE_OWNERS`
   allowlist (comma-separated GitHub owners you control; unset means no repo qualifies). NEVER
   run for any owner outside that allowlist - work/org repos never get filed issues, full stop,
   even with the flag.
3. **Write access:** `gh auth status` passes AND
   `gh api repos/<owner>/<repo> --jq '.permissions.push'` returns `true`.

**When `--issues` IS passed, check every prereq FIRST and THROW A CLEAR ERROR on ANY
unmet one - never a silent no-op, never a partial run.** The user explicitly opted in, so
tell them exactly which prereq failed and stop (create nothing):
- **gh not installed** (`command -v gh` empty): `ERROR: cannot file issues - gh CLI is
  not installed (brew install gh).`
- **gh not authenticated** (`gh auth status` fails): `ERROR: cannot file issues - gh is
  not authenticated (run 'gh auth login').`
- **owner not allowlisted** (owner not in `REPO_AUDIT_ISSUE_OWNERS`): `ERROR: refusing to
  file issues - <owner>/<repo> is not in REPO_AUDIT_ISSUE_OWNERS. Issue-filing is allowlist-only.`
- **no write access** (`.permissions.push` != true): `ERROR: cannot file issues - you do
  not have write access to <owner>/<repo> (permissions.push=false).`
- **no top_fixes** (empty array): `ERROR: nothing to file - the audit produced no
  top_fixes.`
Detect each explicitly, print the matching error, and stop. Only gate 1 (flag absent) is
silent.

**Upsert (idempotent - safe to re-run on every audit):**
- Ensure the marker label exists once:
  `gh label create repo-audit --color 5319e7 --description "Filed by /repo-audit" --force`.
- For each entry in `top_fixes`:
  - Search OPEN issues by exact title
    (`gh issue list --state open --search '"<title>" in:title'`). If a match exists, SKIP
    (never duplicate on re-audit).
  - Else create it: title = the fix title verbatim; body = the finding shape (lens,
    severity, `file`, why, fix, effort) followed by a trailing `<!-- repo-audit -->`
    marker line; labels = `repo-audit` + the lens key + a severity->priority map
    (critical/high -> `priority:high`, medium -> `priority:medium`, low ->
    `priority:low`). Create any missing label with `--force` first.
- Do NOT auto-close anything. On a re-audit, list in the Step 4 summary any open
  `repo-audit`-labelled issues whose title is no longer in `top_fixes` (likely fixed) so
  the user can close them by hand - closing stays a human decision.

Report created / skipped / stale issue numbers in the Step 4 chat summary.

## Step 3b: HD README screenshot (always)

ALWAYS capture a full-page 2x-retina PNG of the repo's `README.md` (rendered with
GitHub markdown CSS and Mermaid diagrams). This is a standing requirement on every
audit run.

```bash
node ~/.claude/skills/repo-audit/render-readme-shot.mjs <repoPath>
# -> writes <repoPath>/docs/screenshots/readme.png (2x retina, full page)
```

The script is portable: it finds README.md case-insensitively, resolves Playwright
from the target repo (then this skill, then global), and prints `SKIP` + exits 0 if
Playwright is not installed - it must never fail the audit. Mermaid/marked/CSS load
from a CDN, so network is required for diagram rendering. After it runs, surface the
PNG to the user (SendUserFile) alongside the report.

## Step 4: Chat summary

Tight: the repo name + stack, the per-lens grades on one line, total findings by
severity, the 2-3 biggest things to fix, and the report file path. No fluff.

## Golden sample lock (no UI drift)

On the FIRST successful run, after the HTML is generated to `/tmp`, lock the layout:
```bash
GOLDEN=~/.claude/skills/repo-audit/golden/sample.html
mkdir -p "$(dirname "$GOLDEN")"
[ -f "$GOLDEN" ] || cp reports/repo-audit-*-$(date +%Y-%m-%d).html "$GOLDEN"
```
- Every run: match the structure of `golden/sample.html`. Never auto-overwrite it; only
  refresh when the user explicitly says to update the master/golden sample.

## Output style invariants (owner-locked - keep these in render.py)

These are hard requirements the owner set for the report look. Any edit to `render.py`
must preserve them, and `golden/sample.html` must reflect them:

- **Whole report renders at 67% scale.** `body { zoom:0.67 }` in render.py - the owner
  found 100% too zoomed-in and 67% "fits all, cleanly" (2026-07-02). All px sizes below
  are pre-zoom values. Never remove the zoom.
- **Finding badges float right, always.** Each finding `.head` is title (left, `flex:1`)
  + a `.badges` group pushed right via `margin-left:auto`. Never let badges wrap into the
  title's flow on the left.
- **Every badge is `icon + result`, consistently styled, with a border.** Format is a
  Font Awesome icon then the value, no text label word:
  severity = `fa-bug` + level (High/Medium/...), confidence = `fa-bullseye` + value,
  effort = `fa-hourglass-half` + S/M/L. All badge variants (green/red/yellow/blue/grey)
  carry a matching `border-color` - no borderless badges.
- **Every lens carries a grade EXCEPT Good/Bad/Ugly (owner request 2026-07-02).** GBU is report-only - never grade it, never show it in the scorecard, and it renders LAST as the closing verdict. features = feature coherence; uiux = only when the repo has a user-facing UI; on a BE-only repo its grade is "N/A" and the renderer omits the lens from the report + scoring completely.
- **Score donuts (owner request 2026-07-02).** The overview card is a flex row: repo info left, an animated Chart.js donut RIGHT (overall score % centered, "Overall Score" label under) filling the old whitespace. Below the pills sits the scorecard: one SOLID color-coded grade circle per graded lens (the letter grade filled in the lens's grade color, lens name below) - NOT a chart (owner request 2026-07-15: the donut chart is the overall score ONLY; per-lens mini rings were disliked). No % on the per-lens circles - the % lives solely on the overall ring. Overall % = mean of GRADE_SCORE-mapped grades (A+ 100 ... F 50); overall ring color by band (90+ green, 80+ blue, 70+ amber, 60+ orange, else red). The old grade-pill strip is replaced by the mini donuts - do not bring the table back. Ring thickness is VERY THIN (owner request 2026-07-15, 50% thinner than the old 79%): Chart.js `cutout: "89%"` - never chunkier. The scorecard is ONE non-wrapping row (`.scorecard` flex-wrap:nowrap, overflow-x:auto) with small 72px mini-donuts, never wrapping to a second line.
- **Grade badges (A-F) are CIRCLES (owner request), color-coded and chunky.** Colors come
  from `GRADE_BADGE` (A green, B blue, C amber, D orange, F red), **graduated per letter so
  +/base/- differ: minus = lighter, base = medium, plus = darkest** (e.g. A- light green, A
  medium, A+ darkest green - same idea for B olives and C ambers). Badge is `font-size:19px`,
  a true circle: `width:52px; height:52px; border-radius:50%` with a soft shadow - the SAME
  size as the scorecard grade circles (owner request 2026-07-15, header + scorecard match).
  Never a square, rounded-square, or thin tag.
- **Finding body copy (`.kv`) is small (10.5px).** The owner asked body text 2px below the
  old 12.5px. Keep detail lines (Where/Impact/Evidence/Fix) at 10.5px.
- **Features mindmap colors per top-level branch, never monochrome.** Each top-level branch
  seeds its own family from `BRANCH_PAL`; descendants + connector lines inherit it. Row
  height (`ROWH`) must exceed the tallest node box (a node with a note is ~38px) so rows
  never overlap - currently `ROWH=52`.

## Rules

- **Context: this is defensive security review.** The target is always a repo the person running the audit owns, maintains, or is authorized to review. Findings exist ONLY for remediation - never produce exploit code, working payloads, or attack instructions; describe the weakness, cite the location, and state the fix.
- READ-ONLY against the target repo. Never edit, commit, push, open PRs, or create tickets.
- **NEVER execute the target repo's own code.** No `npm test`, `npm run build`, `make`, install scripts, or any script defined BY the repo - a cloned third-party repo's test suite is arbitrary code execution. The only things that run are trusted external scanners READING the tree (`npm audit`, `pip-audit`, `gitleaks`, `cloc`, `gh`) and git itself. Interface probes from the docs lens stay within the already-allowed scope (`--help`, `list_tools`, a GET on a documented public route) - never "just run the app to see".
- Public-readiness (LICENSE, secrets in git HISTORY, personal-info leaks) is `/repo-public-audit`'s job - do not duplicate it here. If the audit reveals the user is prepping the repo to go public, point them there.
- NEVER print a real secret value in the report - cite `file:line` + describe it. Secrets are findings, not content.
- Light theme only. Avatar-only (no name text) if people ever appear.
- No em/en/n dashes anywhere - plain hyphen only. No AI attribution.
- **Report title is the `owner/repo` slug ONLY - no "Repo Audit -" prefix, no date.** render.py derives it from `repo_url` (e.g. `acme/orders-api`), falling back to the bare `repo` name when there is no GitHub URL. **Scoped runs append the lens list:** when `data.args` contains `--only=<lenses>`, render.py appends it to the title, e.g. `acme/orders-api (infra)` - so it is clear at a glance whether a run was scoped. Do not pass a `post.title` override unless the user asks for a custom one; let the default slug stand.
- The renderer is the single source of truth for the HTML. Do the judgment, hand it JSON.
- Be honest with grades. A real F is more useful than a polite C.
- **GOLDEN RULE - every tech in the Tech Stack table MUST show a real logo, never a monogram.** A single monogram is a fail. Before rendering, give each `tech_stack` entry a working logo source, in this priority: explicit `icon` (a direct logo URL you verified returns 200) -> Simple Icons `slug` (only if `cdn.simpleicons.org/<slug>` is live - many were removed, e.g. all AWS-family slugs) -> the renderer's automatic DuckDuckGo favicon fallback from the entry's `url` domain. Always set a real `url` so the favicon fallback can fire. Known-good sources: AWS service icons via Iconify (`https://api.iconify.design/logos:aws.svg`, `logos:aws-dynamodb`, `logos:aws-sqs`, etc. - the AWS architecture icon set), `logos:launchdarkly-icon`, the project's own logo SVG, or `https://icons.duckduckgo.com/ip3/<domain>.ico` for any brand. Verify each icon URL with a quick `curl -sL -o /dev/null -w '%{http_code}'` before locking the JSON.

## Optional: posting the report elsewhere

The report always writes to disk (`render.py` prints its path). Posting a copy
somewhere else - a note board, a wiki, a Slack channel - is entirely optional and off
by default. `render.py` supports one generic hook: set BOTH `AUDIT_POST_URL` (the
endpoint) and `AUDIT_POST_TOKEN` (a bearer token) in your own environment, and it POSTs
`{title, content, type: "html"}` there after rendering. Leave both unset to skip
posting entirely - `render.py` prints `post: skipped` and that is a normal, successful
run.
