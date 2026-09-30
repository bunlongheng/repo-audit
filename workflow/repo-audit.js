export const meta = {
  name: 'repo-audit',
  description: 'Reverse-engineer a repo through 10 lenses on the strong model, then render + post the report deterministically',
  whenToUse: 'Full /repo-audit of a GitHub repo or local path. Pass args {target, out?, only?, model?, noPost?}.',
  phases: [
    { title: 'Scope', detail: 'clone/refresh, measure, dependency advisories (orchestrate.py scope)' },
    { title: 'Lenses', detail: '10 read-only lens agents + onboarding recon, all on the strong model, longest-first' },
    { title: 'Synthesis', detail: 'strong model ranks top fixes, verifies tech-stack logos, de-dups Good/Bad/Ugly' },
    { title: 'Finish', detail: 'evidence gate, Flows/Sequences/Mindmaps diagrams, render, archive, Stickies (orchestrate.py finish)' },
  ],
}

// ---------------------------------------------------------------------------- inputs
// args: { target: "owner/repo" | url | path (required),
//         out?: run dir (default /tmp/repo-audit/<name>),
//         only?: ["security", ...] subset of lenses,
//         model?: model for lens + synthesis agents (default: inherit = the session's strong model),
//         noPost?: true to skip the Stickies post,
//         stamp?: "YYYY-MM-DD HH:MM" (workflows cannot read the clock) }
const A = args || {}
if (!A.target) throw new Error('args.target is required (owner/repo, GitHub URL, or local path)')
const ORCH = '~/Sites/repo-audit/orchestrate.py'
const STRONG = A.model ? { model: A.model } : {}
const RUNNER = { model: 'haiku', effort: 'low' }   // script runners only - never judgment

const LENS_KEYS = ['architect', 'security', 'quality', 'features', 'infra', 'performance', 'tests', 'docs', 'uiux', 'gbu']
const ONLY = Array.isArray(A.only) && A.only.length ? A.only : null

// ---------------------------------------------------------------------------- Scope
phase('Scope')
const SCOPE_SCHEMA = {
  type: 'object',
  properties: {
    abs: { type: 'string' }, name: { type: 'string' }, slug: { type: 'string' }, branch: { type: 'string' },
    commit: { type: 'string' }, files: { type: 'number' }, loc: { type: 'number' }, has_ui: { type: 'boolean' },
    scale_guard: { type: 'boolean' }, stack_hint: { type: 'array', items: { type: 'string' } },
    top_level: { type: 'array', items: { type: 'string' } }, src_dirs: { type: 'array', items: { type: 'string' } },
    existing_lens_files: { type: 'array', items: { type: 'string' } },
    dep_audit_tool: { type: 'string' }, dep_audit_summary: { type: 'string' },
    churn_top: { type: 'array', items: { type: 'string' } }, out: { type: 'string' },
  },
  required: ['abs', 'name', 'slug', 'branch', 'commit', 'files', 'loc', 'has_ui', 'stack_hint', 'out'],
}
const outDir = A.out || `/tmp/repo-audit/${String(A.target).split('/').pop().replace(/\.git$/, '')}`
const scope = await agent(
  `Run exactly this command and return its JSON output as the structured result (fill "out" with ${outDir}; ` +
  `flatten dep_audit.tool -> dep_audit_tool and JSON.stringify(dep_audit.summary) -> dep_audit_summary; ` +
  `churn_top as "path (count)" strings). Do not read the repo yourself, do not fix anything:\n\n` +
  `mkdir -p ${outDir} && python3 ${ORCH} scope ${JSON.stringify(A.target)} --out ${outDir}\n\n` +
  `If the command fails, return the error text in dep_audit_summary and set files=0.`,
  { label: 'scope', phase: 'Scope', schema: SCOPE_SCHEMA, ...RUNNER })
if (!scope || !scope.files) throw new Error('scope failed: ' + JSON.stringify(scope).slice(0, 300))
log(`scoped ${scope.slug} @ ${scope.commit}: ${scope.files} files, ${scope.loc} LOC, stack ${scope.stack_hint.join(', ')}`)

// ---------------------------------------------------------------------------- Lenses
const ABS = scope.abs
const OUT = scope.out
const IAC = scope.stack_hint.includes('Terraform')
const tripwire = IAC
  ? 'If you ever see `package.json`, `.jsx`/`.tsx` files, `src/views`, or `pyproject.toml`, you are in the WRONG repo.'
  : 'If you ever see `terraform/`, `src/ioc`, `pyproject.toml` (unless this is a Python repo), or a different app name in package.json, you are in the WRONG repo.'
const sampling = scope.scale_guard
  ? `SCALE GUARD: ${scope.files} files / ${scope.loc} LOC. Do not pretend to read everything: read the boot path, config, CI and the churn hotspots (${(scope.churn_top || []).slice(0, 10).join('; ')}) in full, cover the rest by scoped grep, and STATE the sampling in your summary.`
  : `Small enough to read in full (${scope.files} files / ${scope.loc} LOC) - do so.`

const preamble = (lensName) =>
  `You are the ${lensName} lens of a read-only repo audit. Defensive review of a repo the owner is authorized to audit: ${scope.slug} ` +
  `(branch ${scope.branch}, commit ${scope.commit}; stack: ${scope.stack_hint.join(', ') || 'unknown'}). Report weaknesses with file:line and a fix - ` +
  `never produce exploit code, never print secret values (cite file:line and the KIND of credential).\n\n` +
  `TARGET REPO (absolute): ${ABS}\n` +
  `ABSOLUTE-PATH MANDATE: your cwd is a DIFFERENT repo. Every command uses absolute paths: \`git -C ${ABS} ...\`, \`cat ${ABS}/<file>\`, ` +
  `\`grep -rn <pat> ${ABS}/src\` - never a bare git, never a relative path, never cd. Start with \`ls ${ABS}\` (top level: ${scope.top_level.join(' ')}` +
  `${scope.src_dirs.length ? '; src: ' + scope.src_dirs.join(' ') : ''}).\n` +
  `TRIPWIRE: ${tripwire} Stop and re-issue with the absolute prefix.\n` +
  `READ-ONLY. Never run the repo's own scripts (no install/build/test/plan). Only trusted scanners that READ the tree, git, and gh (read-only) are allowed. ` +
  `Exclude node_modules, dist, build, .terraform and lockfiles from every grep.\n${sampling}\n` +
  `Dependency advisories were already scanned by the orchestrator (${scope.dep_audit_tool || 'n/a'}: ${scope.dep_audit_summary || 'n/a'}) - cite that, do not re-run or invent CVEs.\n\n`

const evidenceRule =
  `\nEVIDENCE RULE: each finding = {title, severity: critical|high|medium|low, confidence: High|Med|Low, file: "path:line", consequence, ` +
  `evidence, fix, effort: S|M|L}. The evidence MUST contain at least one line shaped \`path:line  <verbatim snippet>\` (repo-relative path) ON ITS OWN LINE, ` +
  `commentary on separate lines - the file gate matches the snippet mechanically. Findings you cannot quote are not proved. A clean area is a valid result - say so. ` +
  `Findings whose subject is GitHub state (branch rules, PRs, runs) set file to "GitHub <thing>" and quote the gh output. ` +
  `Prefix any Good/Bad/Ugly item you suspect another lens also found with "[likely dup] ".`

const LENS = {
  architect: `LENS: ARCHITECT - how it is built: layering, data flow, key dependencies, patterns, coupling, seams, bootstrap/auth path, state, HTTP layer, env access. Bus factor: \`git -C ${ABS} shortlog -sn --no-merges HEAD | head\`; flag > 80% single owner.
OUTPUT JSON to ${OUT}/architect.json:
{"summary", "grade": "A+..F", "points": ["path:line - observation"], "table": [["Layer","Dir","Role"], ...one row per real layer/dir],
 "arch_graph": {"nodes":[{"id","name","role","icon","color","src":"path:line"}], "edges":[{"from","to","label","dashed":bool}]},
 "critical_path": {"title", "steps":[{"n","label","src":"path:line","note"}]}, "findings":[...]}
arch_graph is MANDATORY (it becomes a Flows diagram): 8-20 nodes, every node/edge pinned to a real src path:line you read, edge labels from actual call sites. Icons: https://cdn.simpleicons.org/<slug>/<hex> (verify with curl -s -o /dev/null -w '%{http_code}'; if 404 use https://api.iconify.design/logos:<name>.svg, e.g. logos:aws-ecs, logos:launchdarkly-icon, logos:terraform-icon). Never a favicon under 96px, never an emoji. Colors: #3b82f6 app, #f97316 auth, #8b5cf6 external, #f59e0b data store, #10b981 downstream/CI, #ef4444 billing/security. critical_path: 6-10 steps tracing the single most important operation. FAIL CLOSED: say in summary anything you could not place.`,
  security: `LENS: SECURITY. Open by name: auth config and token attach, secrets/config files, every place untrusted input reaches a sink (HTML, shell, SQL, redirect, postMessage, iframe), storage of tokens/PII, security headers (nginx/CSP/HSTS), Dockerfile/CI supply chain (unpinned actions, curl | sh, secrets in build args), IAM/wildcards and public exposure for IaC. semgrep/gitleaks are not installed - say "grep-only secret scan". Fold the orchestrator's dependency advisories into ONE finding with the module names.
OUTPUT JSON to ${OUT}/security.json: {"summary","grade","metrics":[["Secret scan","grep-only"],...],"findings":[...]}`,
  quality: `LENS: CODE QUALITY. Type safety (strict flags, any count, ignores), lint config and whether CI enforces it, largest/most complex files (\`git -C ${ABS} ls-files | xargs wc -l | sort -rn | head -20\` on source), churn hotspots (${(scope.churn_top || []).slice(0, 8).join('; ') || 'compute with git log --name-only'}) read the top 3 and flag hot+complex+untested, duplication, dead code (unused exports, commented blocks), TODO/FIXME, console/debug output, swallowed catches, error boundaries, dependency freshness (majors behind, duplicate majors in the lockfile), placeholder/tooling packages in runtime deps.
OUTPUT JSON to ${OUT}/quality.json: {"summary","grade","metrics":[["Types",...],["Lint",...],["Largest file",...]],"findings":[...]}`,
  features: `LENS: FEATURES SUPPORTED - what the app/infra actually does as a tree: 4-15 top-level branches using REAL names from routes/views/dirs/roots, children = concrete capabilities, each top-level pinned to a path, notes for feature flags, mock-only, half-built (TODO-heavy, placeholder), dead (no route/importer), env drift. Grade = coherence (complete/consistent/scoped vs sprawl/abandoned). State plainly whether it reads shipped-and-stable or parked-mid-flight, with evidence.
OUTPUT JSON to ${OUT}/features.json: {"summary","grade","tree":[{"name","src":"path:line","note","children":[...]}],"findings":[...]} (findings only for incoherence).`,
  infra: `LENS: INFRA - build, CI/CD, deploy, containers, env/config: what really gates a merge and a deploy, frozen lockfiles, node/runtime pinning, Dockerfile hygiene, nginx/headers, env generation, drift between envs. Live GitHub health (read-only, warn-only): \`gh pr list --repo ${scope.slug} --state open --json number,updatedAt,title\`, \`gh run list --repo ${scope.slug} --limit 10 --json conclusion,name,event\` (read the log of the latest failed run with \`gh run view --repo ${scope.slug} <id> --log-failed | tail -40\` and state the real cause), \`gh api repos/${scope.slug}/rules/branches/${scope.branch}\`, \`gh api repos/${scope.slug}/branches/${scope.branch}/protection\`, \`gh api repos/${scope.slug}/environments\`.
OUTPUT JSON to ${OUT}/infra.json: {"summary","grade","metrics":[["CI",...],["Branch protection",...],["Open PRs",...]],"findings":[...]}`,
  performance: `LENS: PERFORMANCE (and cost for IaC). Frontend: code splitting, bundle-heavy deps and import style, asset weight (\`git -C ${ABS} ls-files -z | xargs -0 du -k | sort -rn | head -15\`; base64 images disguised as SVG/TSX), boot waterfalls, query/cache config, blocking third-party scripts, re-render risks. Backend: N+1, sync I/O on hot paths, caching, connection pools. IaC: autoscaling, sizing, env parity waste, log retention, NAT/VPC endpoints, CloudFront cache policy. No Lighthouse unless a public unauthenticated homepage exists - say so.
OUTPUT JSON to ${OUT}/performance.json: {"summary","grade","metrics":[...],"findings":[...]}`,
  tests: `LENS: TESTS (static, never execute). Inventory frameworks, test files vs source files, assertion style (real vs render-only vs snapshot), mocks (msw etc.), coverage config + thresholds and whether CI gates on them, e2e presence, IaC: tftest/validations/preconditions/scanners. Gaps: hot files without tests, untested money/auth/error paths, both flag states. Zero tests on a code repo = F.
OUTPUT JSON to ${OUT}/tests.json: {"summary","grade","metrics":[["Test files",...],["Coverage gate",...],["E2E",...]],"findings":[...]}`,
  docs: `LENS: DOCS. README (is it stock template / empty / accurate - verify every claim against the tree), other docs, diagrams, module docs for IaC; env var drift (vars read in code vs documented/generated); interface currency if the repo exposes an API/CLI/MCP (documented surface vs code); agent instruction files (CLAUDE.md, AGENTS.md) that contradict the code.
OUTPUT JSON to ${OUT}/docs.json: {"summary","grade","metrics":[["README",...],["Docs",...],["Diagrams",...],["Env vars read",...]],"findings":[...]}`,
  uiux: scope.has_ui
    ? `LENS: UI/UX. Design-system discipline (how many styling systems, hardcoded hex count vs tokens, hand-rolled vs system buttons), UX states (loading/empty/error/disabled/double-submit/success), form validation feedback, accessibility (a11y lint present?, img alt, icon-only buttons, div-onClick, focus management in modals, live regions, contrast), responsiveness (fixed px, media queries, embed/iframe assumptions), i18n/locale.
OUTPUT JSON to ${OUT}/uiux.json: {"summary","grade","metrics":[...],"findings":[...]}`
    : null,
  gbu: `LENS: GOOD / BAD / UGLY - the closing verdict. good[]: 3-6 things GENUINELY done well, each pinned to path:line (no other lens records positives). bad[]/ugly[]: defects in files no lens owns (package manifest hygiene, root configs, public/, fixtures with PII, ignore files, hooks) and character observations that are not a discrete finding (N styling systems, copy-pasted helpers, a 1700-line component, months of open PRs). Quote each with path:line; prefix suspected overlaps with "[likely dup] ".
OUTPUT JSON to ${OUT}/gbu.json: {"summary","good":[...],"bad":[...],"ugly":[...]} - no grade.`,
}

const RECON = `You are the onboarding-brief collector of a read-only repo audit of ${scope.slug}. ${tripwire} Use absolute paths only (${ABS}); read-only; gh read-only is allowed.
Collect: churn hotspots (\`git -C ${ABS} log --format= --name-only --since=6.months | sort | uniq -c | sort -rn | head -20\`, fall back to full history if empty); file-type mix; PR mechanics from \`gh pr list --repo ${scope.slug} --state merged --limit 50 --json number,additions,deletions,changedFiles,author,mergedAt,createdAt,headRefName\` (median + p90 LOC, median files, median merge time, branch convention, authors) and \`--limit 40 --json number,reviews\` (top approvers); CODEOWNERS; get-started from README/manifest/CI (prereqs, commands, env, first hour); key dirs with one-line roles; glossary of domain terms you can point to a file for; 3-5 low-risk first PRs anchored to real files. Logins or display names only, never emails.
OUTPUT JSON to ${OUT}/recon.json with EXACTLY: {"get_started":{"prereqs":[],"commands":[[cmd,desc]],"env":[[VAR,note]],"first_hour":[]},"where_to_work":{"hotspots":[[path,count,note]],"key_dirs":[[dir,role]],"ticket_map":[[task,where]]},"pr_process":{"branch_convention","median_loc","p90_loc","median_files","median_merge","approvals_note","review_model","top_reviewers":[[name,count]],"ci_gates":[],"codeowners"},"who_is_who":[[name,role]],"work_nature":{"summary","breakdown":[[kind,pct]]},"glossary":[[term,meaning]],"first_prs":[[title,why,files]]}. Omit fields you cannot populate. Return ONLY a 2-line summary and the JSON path.`

const LENS_SCHEMA = {
  type: 'object',
  properties: { lens: { type: 'string' }, grade: { type: 'string' }, summary: { type: 'string' }, findings: { type: 'number' }, path: { type: 'string' } },
  required: ['lens', 'summary', 'path'],
}

// longest-first: architect/security/quality/features are the heavy readers
const existing = new Set(scope.existing_lens_files || [])
const lensJobs = LENS_KEYS
  .filter(k => LENS[k])
  .filter(k => !ONLY || ONLY.includes(k))
  .filter(k => !existing.has(k))
const reconNeeded = !ONLY && !existing.has('recon')
if (existing.size) log(`skipping ${[...existing].join(', ')} - already present in ${OUT} (delete the file to re-run)`)

phase('Lenses')
const lensResults = await parallel([
  ...lensJobs.map(k => () => agent(
    preamble(k) + LENS[k] + evidenceRule + `\nReturn ONLY: {lens:"${k}", grade, 3-line summary, findings count, path}. No file dumps.`,
    { label: `lens:${k}`, phase: 'Lenses', schema: LENS_SCHEMA, ...STRONG })),
  ...(reconNeeded ? [() => agent(RECON, { label: 'recon', phase: 'Lenses', ...STRONG })] : []),
])
const lensSummary = lensResults.filter(Boolean).filter(r => typeof r === 'object')
  .map(r => `${r.lens}: ${r.grade || '-'} (${r.findings ?? '?'} findings) - ${r.summary}`).join('\n')
log(`${lensSummary.split('\n').filter(Boolean).length} lenses returned`)

// ---------------------------------------------------------------------------- Synthesis
phase('Synthesis')
const synthesis = await agent(
  `You are the synthesis step of a repo audit of ${scope.slug} (${scope.stack_hint.join(', ')}). The lens JSONs are in ${OUT}/ ` +
  `(architect, infra, security, performance, quality, tests, docs, uiux, features, gbu, recon; base.json and scope.json hold the scoping facts). ` +
  `Read them with cat (absolute paths only). Lens summaries:\n${lensSummary}\n\n` +
  `Write ${OUT}/synthesis.json with EXACTLY these keys:\n` +
  `- "top_fixes": 3-5 must-do items ranked across lenses (severity x confidence, cheapest effort wins ties), each {title, lens, severity, file:"path:line", why, fix, effort}. Never pad to 5.\n` +
  `- "bottom_line": one honest sentence.\n` +
  `- "tech_stack": 15-30 rows {name, slug?, icon?, url, category, version} - the WHOLE real stack (languages, frameworks, UI kits, fonts, analytics tags, third-party services, hosting, CI, test/lint tooling) with versions from the lockfile/manifests (read ${ABS}/yarn.lock or package-lock.json, pyproject, versions.tf). Every row needs a logo: a simpleicons slug you verified returns 200 at https://cdn.simpleicons.org/<slug>, else an "icon" URL that returns 200 (Iconify logos:<name>.svg, the vendor favicon). Rows you cannot verify: omit.\n` +
  `- "gbu_drop": {"bad":[indexes],"ugly":[indexes]} - indexes into gbu.json bad[]/ugly[] that restate a finding already present in another lens (same defect, same file). Keep items that share a file but make a different claim.\n` +
  `- "extra_findings": {"<lens>":[finding...]} - only for real gaps you can PROVE by reading the files (e.g. a credential committed in a doc the security lens did not scan, a dependency advisory the lens missed). Same finding shape, evidence with a verbatim \`path:line  snippet\` line, secrets redacted.\n` +
  `- "grade_overrides": {"<lens>":"B"} - only when an extra_finding materially changes a grade; say why in "summary_notes".\n` +
  `- "summary_notes": {"<lens>":"one sentence appended to that lens summary explaining the correction"}.\n` +
  `Judgment stays honest: a real F beats a polite C. Then return ONLY the list of top_fixes titles and the tech_stack row count.`,
  { label: 'synthesis', phase: 'Synthesis', ...STRONG })

// ---------------------------------------------------------------------------- Finish
phase('Finish')
const FINISH_SCHEMA = {
  type: 'object',
  properties: {
    report: { type: 'string' }, grades: { type: 'object' }, findings: { type: 'object' }, gate: { type: 'array', items: { type: 'string' } },
    diagrams: { type: 'object' }, stickies: { type: 'string' }, top_fixes: { type: 'array', items: { type: 'string' } }, error: { type: 'string' },
  },
  required: ['report'],
}
const finish = await agent(
  `Run exactly this command and return its final JSON line as the structured result (if it fails, put the stderr tail in "error" and report="failed"):\n\n` +
  `python3 ${ORCH} finish ${OUT}${A.noPost ? ' --no-post' : ''}\n\n` +
  `Do not edit any file, do not retry with different flags.`,
  { label: 'finish', phase: 'Finish', schema: FINISH_SCHEMA, ...RUNNER })

return { scope: { slug: scope.slug, commit: scope.commit, files: scope.files, loc: scope.loc }, lenses: lensSummary, synthesis, finish, out: OUT }
