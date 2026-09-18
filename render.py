#!/usr/bin/env python3
"""
repo-audit renderer - the ONE canonical HTML output for /repo-audit.

This is the DETERMINISTIC half of the skill. It does NO judgment: it does not
clone, scan, find issues, grade, or rank anything. The agent does all of that
(see SKILL.md) and hands this script a single JSON file describing the run. This
script turns that JSON into the one "Repo Audit" HTML view - a Reverse Engineer
report with 10 lenses (Architect, Good/Bad/Ugly, Infra, Security, Performance,
Code Quality, Tests, Docs, UI/UX, Features mindmap), writes it to disk, optionally
POSTs it to a note-taking/report board (see AUDIT_POST_URL below, off by default),
and prints a one-line summary. Never hand-roll this HTML; always run THIS script so
the UI is identical every run.

Usage:
  python3 render.py <data.json> [--no-open] [--out <file.html>]

  --out       write here instead of ./reports/<prefix>-<repo>-<date>.html
  --no-open   accepted and ignored: this renderer never opens a browser. Kept so
              existing scripts and the docs' examples keep working.

Input contract (the JSON the agent builds at <data.json>):
  {
    "repo": "my-app",                             # display name (or owner/name)
    "repo_url": "https://github.com/acme/my-app", # optional, makes name clickable
    "path": "/path/to/my-app",                    # optional local path scanned
    "branch": "main",                             # optional
    "commit": "abc1234",                          # optional short SHA
    "stack": ["Next.js 16", "Tailwind", "Supabase"],  # optional plain-tag stack
                                                  #   (shown only if tech_stack is absent)
    "tech_stack": [                               # optional rich stack table (above Architect)
      { "name":"Next.js", "slug":"nextdotjs",     #   slug = Simple Icons slug for the brand icon
        "icon":"https://...logo.svg",             #   icon = explicit direct logo URL (wins over slug)
        "url":"https://nextjs.org",               #   url = official site the icon/name links to
        "category":"Framework", "version":"16" }  #   logo priority: icon -> slug -> favicon(url) -> monogram
    ],
    "scanned": { "files": 320, "loc": 24000 },    # REQUIRED scan-scope summary - every
                                                  #   report shows Files + LOC. Omit it ONLY
                                                  #   when "path" points at a git repo the
                                                  #   renderer can count for itself; with
                                                  #   neither, it exits with a clear error.
    "vitality": {                                  # optional repo-life signals (one-line meta strip in overview)
      "last_commit": "2d ago",                     #   relative age of HEAD commit
      "commits_90d": 142,                          #   commit count in the last 90 days
      "contributors": 5,                           #   distinct authors (git shortlog -sn)
      "bus_factor": "68% 1 author",                #   share of commits by the top author
      "stale_branches": 7                          #   branches with no commit in 90d
    },
    "model": "your-model",                         # optional - which model ran the audit
                                                    #   (shown as a small badge next to the
                                                    #   chip so re-audits by a different
                                                    #   model are visually distinguishable)
    "stamp": "2026-06-30 14:00",                   # optional run timestamp
    "lenses": {
      "architect":   { "grade":"B", "summary":"...", "points":["..."],
                       "table":[["Layer","Role"],["app/","routes"]] },   # table optional
      "gbu":         { "good":["..."], "bad":["..."], "ugly":["..."] },  # report-only, never graded
      "infra":       { "grade":"C", "summary":"...", "findings":[ FIND ] },
      "security":    { "grade":"B", "summary":"...", "findings":[ FIND ] },
      "performance": { "grade":"B", "summary":"...", "findings":[ FIND ] },
      "quality":     { "grade":"C", "summary":"...",
                       "metrics":[["Types","strict"],["Lint","eslint"]], # optional
                       "findings":[ FIND ] },
      "tests":       { "grade":"D", "summary":"...",          # what tests EXIST + what SHOULD exist
                       "metrics":[["Test files","42"],["E2E","none"]],   # optional
                       "findings":[ FIND ] },                 # zero tests = F, never N/A
      "docs":        { "grade":"C", "summary":"...",          # README/docs/diagrams
                       "metrics":[["README","320 ln"],["Docs","4"]],     # optional
                       "findings":[ FIND ] },                 # + MCP/CLI/REST staleness
      "uiux":        { "grade":"B", "summary":"...",          # only if the repo HAS a UI;
                       "findings":[ FIND ] },                 #   BE-only repo -> "grade":"N/A" = the
                                                              #   lens is OMITTED from report + scoring
      "features":    { "grade":"A-", "summary":"...",   # grade = feature coherence/completeness
                       "tree":[ {"name":"Auth","note":"Supabase",
                                 "children":[ {"name":"Login"} ]} ] }
    },
    "top_fixes": [                                 # optional cross-lens "fix these first" (max 5, ranked)
      { "title":"...", "lens":"security",          #   lens key the finding came from
        "severity":"high", "file":"path/foo.ts:42",#   file optional
        "why":"...", "fix":"...", "effort":"S" }
    ],
    "delta": {                                     # optional re-audit diff card (agent computes it
      "prev_date": "2026-06-01",                   #   from the archived previous run JSON)
      "fixed": ["title (file)"],                   #   findings gone since last run
      "new": ["title (file)"],                     #   findings that appeared since last run
      "still": 6,                                  #   count still open
      "grade_moves": [["Security","C","B"]]        #   [lens label, old grade, new grade]
    },
    "bottom_line": "one-sentence verdict",         # optional
    # NOTE: no score fields needed - this renderer maps grades to 0-100 itself
    # (GRADE_SCORE), averages them into an overall %, and draws the animated
    # Chart.js donuts (overall in the overview's right side + one mini per lens).
    # Branding overrides (used by sibling skills - same look,
    # different names; all optional, defaults = repo-audit branding):
    "chip": "/another-audit",                      # header chip + <title>
    "out_prefix": "another-audit",                 # reports/<prefix>-<repo>-<date>.html
    "lens_labels": { "architect": "Memory System" },   # per-key display label
    "lens_icons":  { "architect": "fa-brain" },        # per-key Font Awesome icon
    "post": { "title": "..." }                    # optional; overrides the default post title
  }

  FIND = { "title": "...", "severity":"critical|high|medium|low",
           "confidence":"High|Med|Low", "file":"path/foo.ts:42",  # file optional
           "consequence":"...", "evidence":"...", "fix":"...", "effort":"S|M|L" }
  All judgment text comes from the agent. This script only renders it.
"""
import json, os, sys, html, datetime, re, base64

# Verified-dead simpleicons slugs -> working alternatives (tested 2026-08-17)
SLUG_FIX = {
    "java": "openjdk", "micronaut": "openjdk", "maven": "apachemaven",
    "amazonaws": "serverless", "amazons3": "serverless", "awslambda": "serverless",
    "amazonecs": "docker", "amazonrds": "postgresql", "amazondynamodb": "mongodb",
    "recurly": "stripe", "sendgrid": "mailchimp", "twilio": "vonage",
    "openapi": "openapiinitiative", "launchdarkly": "nodedotjs",
    "yext": "yelp", "tray": "zapier", "traydotio": "zapier", "pendo": "datadog",
    # Node.js ecosystem - no simpleicons entry (2026-08-17)
    "knex": "nodedotjs", "helmet": "express", "winston": "nodedotjs",
    "expressjs": "express", "koa": "nodedotjs", "fastify": "fastify",
    # Mobile / cross-platform
    "reactnative": "react", "expo": "expo",
    # Cloud / infra
    "awsecs": "docker", "awsfargate": "docker", "awscodebuilder": "amazonaws",
    "awsecr": "docker", "awssecrets": "amazonaws",
    # Charting libs with no simpleicons entry -> the Chart.js mark (verified live 2026-08-18)
    "recharts": "chartdotjs", "victory": "chartdotjs", "nivo": "chartdotjs",
    "visx": "chartdotjs", "apexcharts": "chartdotjs", "reactchartjs2": "chartdotjs",
    # Misc
    "knexjs": "nodedotjs", "prismaorm": "prisma", "typeorm": "nodedotjs",
}


# 10 lenses in fixed display order. (key, label, fa-icon, accent)
# Good/Bad/Ugly renders LAST, deliberately (owner 2026-09-17). The report already
# opens with the overall grade, the vitality strip and Top Fixes First; a third
# summary at position 2 pushed the evidence down and repeated what the reader had
# just seen. As the closing section it answers "what is this codebase like to live
# with?" AFTER the proof - and it is the part that gets lifted into a portfolio
# blurb or a handoff doc.
LENS_ORDER = [
    ("architect",   "Architect Audit",       "fa-sitemap",            "#cf222e"),
    ("infra",       "Infra Audit",            "fa-server",             "#9a6700"),
    ("security",    "Security Audit",         "fa-lock",      "#1a7f37"),
    ("performance", "Performance Audit",      "fa-gauge-high",         "#0969da"),
    ("quality",     "Code",                   "fa-code",               "#8250df"),
    ("tests",       "Tests Audit",            "fa-flask",              "#24292f"),
    ("docs",        "Docs",                   "fa-book",               "#0891b2"),
    ("uiux",        "UI/UX Audit",            "fa-palette",            "#bf3989"),
    ("features",    "Features Supported",     "fa-diagram-project",    "#cf222e"),
    ("gbu",         "Good, Bad, Ugly",        "fa-scale-balanced",     "#bc4c00"),
]

# Graduated shades per letter so +/base/- read differently: minus = lighter,
# base = medium, plus = darkest. (owner request 2026-07-15 - heat gradient good->bad:
# A=green, B=yellow, C=orange, D=red, E/F=red; +/- just shift the shade)
GRADE_BADGE = {
    "A+": "#0f5323", "A": "#1a7f37", "A-": "#2da44e",   # green:  darkest -> lightest
    "B+": "#b8860b", "B": "#eab308", "B-": "#facc15",   # yellow: darkest -> lightest
    "C+": "#7c2d12", "C": "#c2410c", "C-": "#f97316",   # orange: darkest -> lightest
    "D+": "#7f1d1d", "D": "#b91c1c", "D-": "#ef4444",   # red:    darkest -> lightest
    "E+": "#6d0f0f", "E": "#991b1b", "E-": "#c53030",   # deep red: darkest -> lightest
    "F": "#cf222e",                                      # red
}
# Grade -> 0-100 score for the donut scorecard. Overall = mean of graded lenses.
GRADE_SCORE = {
    "A+": 100, "A": 95, "A-": 92,
    "B+": 88, "B": 85, "B-": 82,
    "C+": 78, "C": 75, "C-": 72,
    "D+": 68, "D": 65, "D-": 62,
    "E+": 58, "E": 55, "E-": 52,
    "F": 50,
}


def score_color(s):
    """Band color for the overall donut, heat gradient good->bad:
    90+ green, 80+ yellow, 70+ orange, 60+ red, 52+ deep red, else red."""
    return ("#1a7f37" if s >= 90 else "#eab308" if s >= 80 else
            "#c2410c" if s >= 70 else "#b91c1c" if s >= 60 else
            "#991b1b" if s >= 52 else "#cf222e")


def overall_grade(pct):
    """Map the overall % back to a letter grade for the donut center (owner request
    2026-08-18: show the grade, e.g. B+, not just 89%). Standard +/- bands - 89 -> B+,
    90 -> A-."""
    if pct is None:
        return "-"
    for cut, g in ((97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
                   (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-")):
        if pct >= cut:
            return g
    return "F"


SEV_BADGE = {
    "critical": ("badge-red", "Critical"), "high": ("badge-red", "High"),
    "medium": ("badge-yellow", "Medium"), "low": ("badge-blue", "Low"),
}
CONF_BADGE = {
    "High": ("badge-green", "High"), "Med": ("badge-yellow", "Med"),
    "Medium": ("badge-yellow", "Med"), "Low": ("badge-grey", "Low"),
}
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
CONF_RANK = {"High": 0, "Med": 1, "Medium": 1, "Low": 2}


def esc(s):
    return html.escape(str(s if s is not None else ""))

# A Font Awesome class name and nothing else - no quote, no space, no handler.
ICON_OK = re.compile(r'^fa-[a-z0-9-]+(?: fa-[a-z0-9-]+)*$')
# Only a real web URL may become a clickable href (javascript:, data:, file: out).
SAFE_URL = re.compile(r'^https?://', re.I)


def script_json(obj):
    """json.dumps for an inline <script>. The HTML parser ends the script at the
    first literal `</`, so a string containing `</script>` would break out of the
    block and start executing markup - escape the sequence, not the JSON."""
    return json.dumps(obj).replace('</', '<\\/')



# Set once per render (see below) so md_inline can LINK auto-detected file:line refs.
_REPO_URL = ""
_BRANCH = "main"


def md_inline(s):
    """Escape prose, then give it visual texture so lens summaries/points do not read
    as a wall of black. Honors author markup (`code`, **bold**) AND auto-styles code-like
    tokens the auditor wrote as plain text: file:line refs (linked to the repo), file
    paths, func() calls, and SCREAMING_SNAKE constants/env vars all become inline <code>.
    Each generated span is stashed as a placeholder the moment it is made, so later
    passes can never re-match inside an already-built tag (robust vs regex-on-HTML)."""
    s = html.escape(s or "")
    stash = []

    def keep(frag):
        stash.append(frag)
        return f"\x00{len(stash) - 1}\x00"

    # 1. author-written `code`
    s = re.sub(r'`([^`]+)`', lambda m: keep(f'<code>{m.group(1)}</code>'), s)

    # 2. file:line (path.ext:NN or NN-MM) -> linked code (most specific, first)
    def _fileline(m):
        ref = m.group(0)
        mm = re.match(r'^(.*?):(\d+)', ref)
        if _REPO_URL and mm:
            url = f"{_REPO_URL.rstrip('/')}/blob/{_BRANCH}/{mm.group(1)}#L{mm.group(2)}"
            return keep(f'<a href="{esc(url)}"><code>{ref}</code></a>')
        return keep(f'<code>{ref}</code>')
    s = re.sub(r'[\w./*-]+\.[A-Za-z]{1,6}:\d+(?:-\d+)?', _fileline, s)

    # 3. bare file path (dir/....ext) -> code
    s = re.sub(r'[\w.*-]+/[\w./*-]+\.[A-Za-z]{1,6}', lambda m: keep(f'<code>{m.group(0)}</code>'), s)
    # 4. func() call -> code
    s = re.sub(r'[A-Za-z_]\w+\(\)', lambda m: keep(f'<code>{m.group(0)}</code>'), s)
    # 5. SCREAMING_SNAKE const / env var (2+ segments) -> code
    s = re.sub(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+', lambda m: keep(f'<code>{m.group(0)}</code>'), s)
    # 6. **bold** (after code is stashed, so ** inside code is untouched)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)

    # restore all protected spans
    return re.sub('\x00(\\d+)\x00', lambda m: stash[int(m.group(1))], s)


def md_point(s):
    """md_inline + auto-bold a short lead-in label ('Pure core: ...') so lens
    bullet lists carry visual hierarchy without the author hand-marking each one
    (owner request 2026-07-21). Only fires on a label-shaped prefix: <= 42 chars
    before the first colon, no sentence period inside, and not already bolded."""
    txt = s or ""
    m = re.match(r'^([^:.]{2,42}):\s+(.+)$', txt, re.S)
    if m and "**" not in m.group(1):
        return f'<strong>{md_inline(m.group(1))}:</strong> {md_inline(m.group(2))}'
    return md_inline(txt)


def file_ref(repo_url, branch, fileref):
    """'path/foo.ts:42' -> linked code if repo_url given, else bare code."""
    if not fileref:
        return ""
    if repo_url and SAFE_URL.match(repo_url):
        m = re.match(r'^(.*?):(\d+)(?:-(\d+))?$', fileref)
        base = repo_url.rstrip("/")
        if m:
            url = f"{base}/blob/{branch}/{m.group(1)}#L{m.group(2)}"
        else:
            url = f"{base}/blob/{branch}/{fileref}"
        return f'<a href="{esc(url)}"><code>{esc(fileref)}</code></a>'
    return f'<code>{esc(fileref)}</code>'


def find_sort(f):
    return (SEV_RANK.get((f.get("severity") or "low").lower(), 9),
            CONF_RANK.get(f.get("confidence") or "Low", 9),
            (f.get("title") or ""))


# The report's MAIN icon when it is posted through the optional hook: a plain
# magnifying-glass glyph, not the skill's own app-icon PNG.
_REPORT_ICON = "__repoaudit"


ICON_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp",
             ".gif": "image/gif"}


def _is_image_bytes(b, mime):
    """Do these bytes actually START like the image type the extension claims?

    Load-bearing, not cosmetic: this function base64-embeds a local file into a
    report that gets shared. Trusting the extension alone meant any readable file
    under the size cap - .env, id_rsa, a credentials file - was embedded and
    labelled image/png, so naming it in the data JSON exfiltrated it into a
    document the user then sent to their team."""
    if mime == "image/svg+xml":
        head = b[:512].lstrip().lower()
        return head.startswith(b"<?xml") or head.startswith(b"<svg") or head.startswith(b"<!doctype svg")
    return (
        (mime == "image/png" and b.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/jpeg" and b.startswith(b"\xff\xd8\xff"))
        or (mime == "image/gif" and b[:6] in (b"GIF87a", b"GIF89a"))
        or (mime == "image/webp" and b[:4] == b"RIFF" and b[8:12] == b"WEBP")
        or (mime == "image/x-icon" and b[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"))
    )


def _icon_datauri(fp):
    """Embed a local IMAGE as a self-contained data-URI (reports stay offline-safe).
    Refuses anything whose extension is not a known image type, anything whose bytes
    do not match that type, and anything over 1.5MB."""
    mime = ICON_MIME.get(os.path.splitext(fp)[1].lower())
    if not mime:
        return ""
    try:
        with open(fp, "rb") as fh:
            b = fh.read(1536 * 1024 + 1)
        if len(b) > 1536 * 1024 or not _is_image_bytes(b, mime):
            return ""
        return f"data:{mime};base64,{base64.b64encode(b).decode()}"
    except Exception:
        return ""


def _img_max_dim(fp):
    """Largest pixel dimension of a local image, WITHOUT Pillow (render.py stays
    dependency-free). Used to prefer HD assets over tiny favicons. SVG is scalable
    so it wins; unknown rasters get a middling score so a real PNG still beats them."""
    ext = os.path.splitext(fp)[1].lower()
    if ext == ".svg":
        return 100000
    try:
        with open(fp, "rb") as fh:
            head = fh.read(64)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            w = int.from_bytes(head[16:20], "big"); h = int.from_bytes(head[20:24], "big")
            return max(w, h)
        if head[:4] == b"\x00\x00\x01\x00":  # ICO: dir entries carry per-image size
            n = int.from_bytes(head[4:6], "little"); best = 0
            with open(fp, "rb") as fh:
                fh.seek(6); dirs = fh.read(16 * n)
            for i in range(n):
                w = dirs[i * 16] or 256; h = dirs[i * 16 + 1] or 256
                best = max(best, w, h)
            return best
    except Exception:
        pass
    return 200  # jpg/webp/gif of unknown size - decent but below a real PNG


def resolve_app_icon(explicit, repo_path, repo_short):
    """The icon of the app that was audited, for the report's top-right badge.
    MUST always resolve to something visible (owner requirement) - callers render a
    monogram fallback when this returns "". Priority:
      1. explicit `app_icon` from the JSON (http/https/data URL, or a filesystem path)
      2. the audited repo's own icon assets (public/app/root: icon/logo/favicon)
      3. the optional local icon registry (REPO_AUDIT_ICON_REGISTRY) keyed by the repo's short name
    Returns a data-URI (local files, so the report stays self-contained) or a URL."""
    # Optional local app-icon registry: a directory of <repo-short>.png|svg|jpg files.
    # Point REPO_AUDIT_ICON_REGISTRY at it to resolve a shared icon when the repo has
    # none of its own. Unset by default - the registry lookups below then simply no-op
    # and the renderer falls back to the repo's own assets, then a monogram.
    reg = os.path.expanduser(os.environ.get("REPO_AUDIT_ICON_REGISTRY", ""))
    # 1. explicit override
    if explicit:
        e = explicit.strip()
        if e.startswith(("http://", "https://", "data:")):
            return e
        ep = os.path.realpath(os.path.expanduser(e))
        # Only from inside the audited repo or a registry the USER configured. The
        # value can come from an agent that just read an untrusted repo, so an
        # arbitrary absolute path must not be readable through it.
        roots = [os.path.realpath(r) for r in (repo_path, reg,
                 os.path.expanduser(os.environ.get("REPO_AUDIT_FAVICON_REGISTRY", ""))) if r]
        inside = any(ep == r or ep.startswith(r + os.sep) for r in roots)
        if inside and os.path.isfile(ep):
            u = _icon_datauri(ep)
            if u:
                return u
        # bare token -> treat as a registry key (e.g. app_icon="local-apps")
        for ext in (reg and (".png", ".svg", ".jpg") or ()):
            fp = os.path.join(reg, os.path.basename(e) + ext)
            if os.path.exists(fp):
                u = _icon_datauri(fp)
                if u:
                    return u
    # 1.5. Optional: prefer a curated favicon from a second registry when present (set
    # REPO_AUDIT_FAVICON_REGISTRY to a dir of <repo-short>.png files). Skip a tiny
    # favicon (< 128px) that would render blurry, and fall through to ranking. Unset by
    # default - this block then no-ops.
    favreg = os.environ.get("REPO_AUDIT_FAVICON_REGISTRY", "")
    lafav = os.path.join(os.path.expanduser(favreg), f"{repo_short}.png") if favreg else ""
    if lafav and os.path.isfile(lafav) and _img_max_dim(lafav) >= 128:
        u = _icon_datauri(lafav)
        if u:
            return u
    # 2 + 3. Auto-resolve: collect EVERY candidate that exists (the audited repo's own
    # assets + the optional icon registry), then embed the HIGHEST-resolution one
    # rather than the first match. Without this, a repo whose first hit is a 32px
    # favicon.ico renders a blurry header badge even when a 512px icon.png sits right
    # next to it. Owner requirement: all app icons render HD.
    cands = []
    if repo_path:
        rp = os.path.expanduser(repo_path)
        for c in (
            f"public/app-icons/{repo_short}.png",
            "public/logo512.png", "public/logo256.png", "public/logo192.png",
            "public/icon.png", "public/logo.png", "public/favicon.png",
            "public/apple-touch-icon.png", "public/favicon.ico",
            "app/icon.png", "app/apple-icon.png", "app/apple-touch-icon.png", "app/favicon.ico",
            "src/app/icon.png", "src/app/favicon.ico",
            "icon.png", "logo.png", "assets/logo.png", "assets/icon.png",
            "public/logo.svg", "public/icon.svg", "logo.svg", "icon.svg",
        ):
            fp = os.path.join(rp, c)
            if os.path.isfile(fp):
                cands.append(fp)
    for ext in (reg and (".png", ".svg", ".jpg") or ()):
        fp = os.path.join(reg, f"{repo_short}{ext}")
        if os.path.isfile(fp):
            cands.append(fp)
    # Rank by resolution, but cap the "useful" dimension at 512: the header badge is
    # 64px, so anything >=512 is already crisp and a 1024px asset just bloats the
    # embedded report. Among equally-crisp candidates, prefer the smaller file (an SVG
    # or a tidy 512 PNG over a heavy 1024). Then embed the first that fits under the cap.
    def _rank(fp):
        return (min(_img_max_dim(fp), 512), -os.path.getsize(fp))
    for fp in sorted(cands, key=_rank, reverse=True):
        u = _icon_datauri(fp)
        if u:
            return u
    return ""


def text_on(hexcol):
    """Readable text color for a solid badge: dark ink on light fills (yellow),
    white on dark fills (green/red). Keeps the yellow B grade legible."""
    h = hexcol.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#1f2328" if lum > 0.6 else "#fff"


# Small badge next to the header chip showing which model label produced this run's
# judgment, so re-audits by a different model are visually distinguishable when
# comparing reports over time. Any label works; the color comes from the label.
def _model_color(label):
    palette = ["#7c3aed", "#4338ca", "#0969da", "#0891b2", "#1a7f37", "#bc4c00"]
    return palette[sum(ord(c) for c in label) % len(palette)]


def model_badge(model):
    if not model:
        return ""
    key = str(model).lower()
    color, icon = _model_color(key), "fa-microchip"
    return (f'<span class="model-badge" style="color:{color};border-color:{color}66;background:{color}14">'
            f'<i class="fa-solid {icon}"></i>{esc(model)}</span>')


def grade_pill(grade):
    if not grade:
        return ""
    col = GRADE_BADGE.get(grade.strip(), "#57606a")
    # Grade is a circle (owner request): equal width/height + border-radius:50%.
    return (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'background:{col};color:{text_on(col)};font-weight:800;font-size:19px;'
            f'width:52px;height:52px;flex:0 0 52px;border-radius:50%;letter-spacing:.02em;'
            f'box-shadow:0 2px 5px {col}55">{esc(grade)}</span>')


def render_findings(P, findings, repo_url, branch):
    A = P.append
    for f in sorted(findings, key=find_sort):
        sb, sl = SEV_BADGE.get((f.get("severity") or "low").lower(),
                               ("badge-grey", f.get("severity", "?")))
        cb, cl = CONF_BADGE.get(f.get("confidence") or "Low",
                                ("badge-grey", f.get("confidence", "?")))
        A('<div class="finding"><div class="head">')
        A(f'<span class="title">{esc(f.get("title",""))}</span>')
        A('<span class="badges">')
        A(f'<span class="badge {sb}"><i class="fa-solid fa-bug"></i>{esc(sl)}</span>')
        A(f'<span class="badge {cb}"><i class="fa-solid fa-bullseye"></i>{esc(cl)}</span>')
        if f.get("effort"):
            A(f'<span class="badge badge-grey"><i class="fa-solid fa-hourglass-half"></i>{esc(f["effort"])}</span>')
        A('</span>')
        A('</div>')
        if f.get("file"):
            A(f'<div class="kv"><b>Where:</b> {file_ref(repo_url, branch, f["file"])}</div>')
        if f.get("consequence"):
            A(f'<div class="kv"><b>Impact:</b> {md_inline(f["consequence"])}</div>')
        if f.get("evidence"):
            A(f'<div class="kv"><b>Evidence:</b> {md_inline(f["evidence"])}</div>')
        if f.get("fix"):
            A(f'<div class="kv"><b>Fix:</b> {md_inline(f["fix"])}</div>')
        A('</div>')


def render_flow(flow):
    """Simple left-to-right communication flow: one row (lane) per runtime path,
    node chips joined by arrows. Nodes named in `seam` are tinted to show the
    shared path the lanes converge on. Light theme, responsive (wraps narrow)."""
    if not flow or not flow.get("lanes"):
        return ""
    seam = set(flow.get("seam", []))
    out = ['<div class="flow">']
    for lane in flow["lanes"]:
        col = lane.get("color", "#0969da")
        out.append('<div class="flane">')
        if lane.get("label"):
            out.append(f'<span class="flane-lbl" style="background:{esc(col)}1a;'
                       f'color:{esc(col)};border:1px solid {esc(col)}40">{esc(lane["label"])}</span>')
        nodes = lane.get("nodes", [])
        for i, n in enumerate(nodes):
            hot = n in seam
            bg = "#ddf4ff" if hot else "#f6f8fa"
            bd = "#54aeff" if hot else "#d0d7de"
            out.append(f'<span class="fnode" style="background:{bg};border-color:{bd}">{esc(n)}</span>')
            if i < len(nodes) - 1:
                out.append('<span class="farr">&rarr;</span>')
        out.append('</div>')
    if flow.get("note"):
        out.append(f'<div class="flow-note">{md_inline(flow["note"])}</div>')
    out.append('</div>')
    return "".join(out)


def render_layers(layers):
    """Vertical layer stack with a single dependency direction (top -> down).
    For layered / hexagonal architectures. Light theme, responsive."""
    if not layers or not layers.get("stack"):
        return ""
    out = ['<div class="lyr">']
    if layers.get("direction"):
        out.append(f'<div class="lyr-dir">{esc(layers["direction"])}</div>')
    stack = layers["stack"]
    for i, lv in enumerate(stack):
        note = f'<span class="lyr-note">{esc(lv.get("note",""))}</span>' if lv.get("note") else ""
        out.append(f'<div class="lyr-box"><span class="lyr-name">{esc(lv.get("name",""))}</span>{note}</div>')
        if i < len(stack) - 1:
            out.append('<div class="lyr-arr">&darr;</div>')
    if layers.get("note"):
        out.append(f'<div class="flow-note">{md_inline(layers["note"])}</div>')
    out.append('</div>')
    return "".join(out)


def render_arch_diagram(table):
    """Layered architecture diagram built from the architect [[Layer,Role],...]
    table. FULLY INLINE-STYLED (no CSS classes) so it renders both in-browser and
    when posted to a note-taking app that strips <style>/classes. Top card = entry/edge
    layer, arrows flow down to the data/infra layer - the wall of text becomes a
    scannable stack of colour-coded layer cards, each with its role beneath."""
    if not table or len(table) < 2:
        return ""
    rows = [r for r in table[1:] if r and str(r[0]).strip()]
    if not rows:
        return ""
    pal = ["#0969da", "#1f883d", "#9a6700", "#8250df", "#cf222e",
           "#0550ae", "#116329", "#953800", "#6639ba", "#a40e26"]
    out = ['<div style="display:flex;flex-direction:column;align-items:stretch;'
           'gap:0;margin:12px 0 18px;max-width:780px">']
    for i, r in enumerate(rows):
        layer = esc(str(r[0]))
        role = md_inline(str(r[1])) if len(r) > 1 else ""
        ac = pal[i % len(pal)]
        out.append(
            f'<div style="border:2px solid {ac};'
            'border-radius:10px;padding:11px 15px;background:#ffffff;'
            'box-shadow:0 1px 2px rgba(27,31,36,0.06)">'
            '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
            f'font-weight:700;font-size:13px;color:#1f2328;letter-spacing:-0.2px">{layer}</div>'
            + (f'<div style="font-size:12px;color:#57606a;margin-top:4px;'
               f'line-height:1.45">{role}</div>' if role else "")
            + '</div>')
        if i < len(rows) - 1:
            out.append('<div style="text-align:center;color:#afb8c1;font-size:15px;'
                       'line-height:1;padding:4px 0">&darr;</div>')
    out.append('</div>')
    return "".join(out)


def _tech_logo_img(node, size=20):
    """Inline <img> logo for a diagram node, resolved like the tech-stack table:
    explicit icon URL -> Simple Icons slug -> favicon of the node's url -> monogram.
    Fully inline-styled so it survives note-taking apps that strip CSS classes."""
    import re as _re
    name = str(node.get("name", ""))
    slug = SLUG_FIX.get((node.get("slug") or "").strip().lower(), (node.get("slug") or "").strip())
    icon = (node.get("icon") or "").strip()
    url = node.get("url", "") or ""
    m = _re.search(r"https?://([^/]+)", url)
    dom = m.group(1).lstrip("www.") if m else ""
    fav = f"https://icons.duckduckgo.com/ip3/{dom}.ico" if dom else ""
    mono = (f"<span style=\"display:inline-flex;align-items:center;justify-content:center;"
            f"width:{size}px;height:{size}px;border-radius:5px;background:#eaeef2;"
            f"font-size:{max(9,size//2)}px;font-weight:800;color:#57606a\">{esc(name[:1])}</span>")
    if icon:
        src = icon
    elif slug:
        src = f"https://cdn.simpleicons.org/{esc(slug)}"
    elif fav:
        src = fav
    else:
        return mono
    oe = (f"this.onerror=null;this.src=&#39;{esc(fav)}&#39;" if (fav and src != fav)
          else f"this.outerHTML=&#39;{esc(mono)}&#39;")
    return (f'<img src="{esc(src)}" alt="{esc(name)}" width="{size}" height="{size}" '
            f'style="display:block;width:{size}px;height:{size}px;object-fit:contain" '
            f'loading="lazy" onerror="{oe}">')


def render_arch_flow(flow):
    """High-level 'how it is built / how things talk' diagram: horizontal tiers of
    tech-logo chips, connected top-to-bottom by labelled protocol arrows (e.g. the
    request path Client -> Edge -> Server -> Data). FULLY INLINE-STYLED so it renders
    in-browser AND when posted to a note-taking app. `flow` = {tiers:[{label, nodes:[{name,slug|icon|url}]}],
    links:["HTTPS","SQL / WebSocket", ...]} where links[i] labels the arrow under tier i."""
    if not flow or not flow.get("tiers"):
        return ""
    tiers = flow["tiers"]
    links = flow.get("links", [])
    # distinct accent per tier for at-a-glance hierarchy on a phone (reads top-to-bottom)
    PAL = ["#2563eb", "#7c3aed", "#16a34a", "#d97706", "#0891b2", "#db2777"]
    out = ['<div style="margin:14px auto 20px;max-width:780px">']
    for i, tier in enumerate(tiers):
        c = PAL[i % len(PAL)]
        out.append(f'<div style="border:2px solid {c};border-radius:13px;'
                   f'padding:13px 15px;background:#fff;box-shadow:0 2px 8px rgba(20,30,50,.07)">')
        if tier.get("label"):
            out.append('<div style="display:flex;align-items:center;gap:9px;margin-bottom:11px">'
                       f'<span style="flex-shrink:0;display:inline-flex;align-items:center;justify-content:center;'
                       f'width:22px;height:22px;border-radius:7px;background:{c};color:#fff;font-size:12px;font-weight:800">{i+1}</span>'
                       f'<span style="font-size:12.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:{c}">{esc(tier["label"])}</span></div>')
        out.append('<div style="display:flex;flex-direction:column;gap:9px">')
        for n in tier.get("nodes", []):
            logo = _tech_logo_img(n, 24)
            sub = (f'<span style="font-size:12px;color:#8c959f;display:block;line-height:1.25">{esc(n["role"])}</span>'
                   if n.get("role") else "")
            # archify evidence pin: the file:line where this node is actually wired up
            if n.get("src"):
                sub += (f'<span style="font-size:12px;color:#6b7684;display:block;line-height:1.3;margin-top:1px;'
                        f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all" title="verified source">'
                        f'&#9679; {esc(n["src"])}</span>')
            # trust-boundary marker
            BC = {"auth": "#b45309", "trust": "#b91c1c", "network": "#1d4ed8"}
            btag = ""
            if n.get("boundary") in BC:
                bc = BC[n["boundary"]]
                btag = (f'<span style="font-size:12px;font-weight:800;letter-spacing:.08em;color:{bc};'
                        f'background:{bc}18;border:1px solid {bc}44;border-radius:5px;padding:1px 5px;'
                        f'text-transform:uppercase;margin-left:6px;vertical-align:middle">{esc(n["boundary"])}</span>')
            out.append('<div style="display:flex;align-items:flex-start;gap:9px;background:#f6f8fa;'
                       f'border:1px solid #e1e6eb;border-radius:11px;padding:8px 13px;width:100%;box-sizing:border-box">{logo}'
                       f'<span style="flex:1;min-width:0"><span style="font-size:13px;font-weight:700;color:#1f2328;line-height:1.25">{esc(n.get("name",""))}</span>{btag}{sub}</span></div>')
        out.append('</div></div>')
        if i < len(tiers) - 1:
            lbl = esc(str(links[i])) if i < len(links) and links[i] else ""
            out.append('<div style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:7px 0">'
                       '<svg width="20" height="22" viewBox="0 0 24 24" fill="none" stroke="#aab2bd" stroke-width="2.6" '
                       'stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="3" x2="12" y2="18"/><polyline points="6 12 12 18 18 12"/></svg>'
                       + (f'<span style="font-size:12px;font-weight:600;color:#57606a;background:#eef1f4;border:1px solid #e1e6eb;'
                          f'border-radius:999px;padding:3px 12px;text-align:center;max-width:280px">{esc(lbl)}</span>' if lbl else "")
                       + '</div>')
    out.append('</div>')
    return "".join(out)


def render_arch_canvas(canvas):
    """Free-form node-graph architecture diagram with real service icons, arrows, and labels.
    canvas = {width, height, nodes:[{id,x,y,name,role,icon,color}], edges:[{from,to,label,dashed?}]}
    Renders as a self-contained inline SVG - no external deps, survives any viewer."""
    if not canvas or not canvas.get("nodes"):
        return ""
    W = canvas.get("width", 900)
    H = canvas.get("height", 480)
    NW, NH = 120, 78  # node box width / height
    IR = 30           # icon size
    nodes = {n["id"]: n for n in canvas["nodes"]}
    edges = canvas.get("edges", [])

    def cx(n): return n["x"] + NW // 2
    def cy(n): return n["y"] + NH // 2

    parts = []
    parts.append(f'<div style="margin:18px auto 24px;max-width:{W}px;overflow-x:auto">')
    parts.append(f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                 f'style="width:100%;max-width:{W}px;height:auto;display:block;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif">')

    # defs: arrow marker + drop shadow filter
    parts.append('<defs>')
    parts.append('<marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
                 '<path d="M0,0 L0,6 L8,3 z" fill="#94a3b8"/></marker>')
    parts.append('<marker id="arr-d" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
                 '<path d="M0,0 L0,6 L8,3 z" fill="#c4b5fd"/></marker>')
    parts.append('<filter id="nshadow" x="-20%" y="-20%" width="140%" height="140%">'
                 '<feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#1e293b" flood-opacity="0.10"/></filter>')
    parts.append('</defs>')

    # edges (draw behind nodes)
    for e in edges:
        src = nodes.get(e.get("from"))
        dst = nodes.get(e.get("to"))
        if not src or not dst:
            continue
        x1, y1 = cx(src), cy(src)
        x2, y2 = cx(dst), cy(dst)
        # shorten line to node edge
        import math
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1
        ox, oy = dx / dist, dy / dist
        px1, py1 = x1 + ox * (NW // 2 + 2), y1 + oy * (NH // 2 + 2)
        px2, py2 = x2 - ox * (NW // 2 + 10), y2 - oy * (NH // 2 + 10)
        # smooth bezier
        mx = (px1 + px2) / 2
        my = (py1 + py2) / 2
        dashed = e.get("dashed", False)
        stroke = "#c4b5fd" if dashed else "#94a3b8"
        marker = "arr-d" if dashed else "arr"
        dash_attr = 'stroke-dasharray="6,4"' if dashed else ''
        parts.append(f'<path d="M{px1:.1f},{py1:.1f} Q{mx:.1f},{py1:.1f} {px2:.1f},{py2:.1f}" '
                     f'fill="none" stroke="{stroke}" stroke-width="1.8" {dash_attr} '
                     f'marker-end="url(#{marker})"/>')
        # edge label at midpoint
        if e.get("label"):
            lx, ly = (px1 + px2) / 2, (py1 + py2) / 2 - 7
            parts.append(f'<rect x="{lx - 36:.0f}" y="{ly - 9:.0f}" width="72" height="14" rx="7" '
                         f'fill="white" opacity="0.9"/>')
            parts.append(f'<text x="{lx:.1f}" y="{ly + 2:.1f}" text-anchor="middle" '
                         f'font-size="8" fill="#64748b" font-weight="600">{esc(e["label"])}</text>')

    # nodes
    for n in canvas["nodes"]:
        x, y = n["x"], n["y"]
        color = n.get("color", "#3b82f6")
        name = esc(n.get("name", ""))
        role = esc(n.get("role", ""))
        icon_uri = n.get("icon", "")

        # box
        parts.append(f'<g filter="url(#nshadow)">')
        parts.append(f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="12" ry="12" '
                     f'fill="white" stroke="{color}30" stroke-width="1.5"/>')
        # colored top bar
        parts.append(f'<rect x="{x}" y="{y}" width="{NW}" height="4" rx="2" fill="{color}" opacity="0.85"/>')
        parts.append('</g>')

        # icon
        icon_x = x + (NW - IR) // 2
        icon_y = y + 12
        if icon_uri and icon_uri.startswith(("data:", "http:", "https:")):
            # data: URIs and remote CDN logos (cdn.simpleicons.org / iconify / favicons) both
            # render - matches how the tech-stack table sources its brand icons. Only a missing
            # or non-URL icon falls back to the monogram, so the LOGO RULE is no longer defeated.
            parts.append(f'<image href="{esc(icon_uri)}" x="{icon_x}" y="{icon_y}" '
                         f'width="{IR}" height="{IR}" preserveAspectRatio="xMidYMid meet"/>')
        else:
            # color circle monogram fallback
            parts.append(f'<circle cx="{icon_x + IR//2}" cy="{icon_y + IR//2}" r="{IR//2}" fill="{color}22"/>')
            parts.append(f'<text x="{icon_x + IR//2}" y="{icon_y + IR//2 + 5}" text-anchor="middle" '
                         f'font-size="14" font-weight="800" fill="{color}">{name[:1]}</text>')

        # name
        name_y = icon_y + IR + 10
        parts.append(f'<text x="{x + NW//2}" y="{name_y}" text-anchor="middle" '
                     f'font-size="10" font-weight="700" fill="#1e293b">{name}</text>')
        # role
        if role:
            parts.append(f'<text x="{x + NW//2}" y="{name_y + 13}" text-anchor="middle" '
                         f'font-size="8.5" fill="{color}" font-weight="600">{role}</text>')

    parts.append('</svg></div>')
    return "".join(parts)


def render_critical_path(cp):
    """archify request-trace: the app's single most important operation traced end to
    end as a numbered sequence, each hop pinned to a real path:line. Renders as a
    vertical evidence ladder below the tier diagram. `cp` =
    {title, steps:[{n, label, src, note?}]}. Fully inline-styled to survive any viewer."""
    if not cp or not cp.get("steps"):
        return ""
    out = ['<div style="margin:6px auto 20px;max-width:640px;border:1px solid #e6e9ee;border-radius:13px;'
           'background:#fff;padding:15px 18px;box-shadow:0 2px 8px rgba(20,30,50,.07)">']
    title = esc(cp.get("title", "Critical request path"))
    out.append('<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">'
               '<span style="font-size:12px">&#128269;</span>'
               f'<span style="font-size:12.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:#334155">{title}</span>'
               '<span style="font-size:12px;color:#94a3b8;font-weight:600">verified request trace</span></div>')
    steps = cp["steps"]
    for i, s in enumerate(steps):
        num = s.get("n", i + 1)
        is_last = i == len(steps) - 1
        # Outer row: stretch so left column fills full row height (needed for connector)
        out.append('<div style="display:flex;gap:11px;align-items:stretch;padding:2px 0">')
        # Left column: circle + continuous connector line that fills remaining height
        out.append('<div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0">'
                   f'<span style="width:21px;height:21px;border-radius:50%;background:#334155;color:#fff;'
                   f'font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0">{esc(str(num))}</span>'
                   + ('' if is_last else '<span style="flex:1;width:2px;background:#dfe3e8;min-height:10px;margin:2px 0"></span>')
                   + '</div>')
        note = (f'<span style="font-size:12px;color:#8c959f;display:block;line-height:1.3">{esc(s["note"])}</span>'
                if s.get("note") else "")
        src = (f'<span style="font-size:12px;color:#6b7684;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
               f'display:block;line-height:1.35">&#9679; {esc(s["src"])}</span>' if s.get("src") else "")
        # Content card: full surrounding border
        pb = "8px" if is_last else "10px"
        out.append(f'<div style="flex:1;padding:7px 10px;margin-bottom:{pb};border:1px solid #e6e9ee;border-radius:8px;background:#f8fafc">'
                   f'<span style="font-size:13px;font-weight:650;color:#1f2328;line-height:1.3">{esc(s.get("label",""))}</span>'
                   f'{src}{note}</div>')
        out.append('</div>')
    out.append('</div>')
    return "".join(out)


def render_mindmap(mm):
    """Root node on the left, branches fanning right - a simple 2-level mindmap."""
    if not mm or not mm.get("branches"):
        return ""
    out = ['<div class="mm">']
    out.append(f'<div class="mm-root">{esc(mm.get("root",""))}</div>')
    out.append('<div class="mm-branches">')
    for b in mm["branches"]:
        det = f'<span class="mm-det">{md_inline(b.get("detail",""))}</span>' if b.get("detail") else ""
        out.append(f'<div class="mm-b"><span class="mm-name">{esc(b.get("name",""))}</span>{det}</div>')
    out.append('</div></div>')
    return "".join(out)


def render_depgraph(g):
    """Boxes + arrows module dependency graph as inline SVG. Node positions are
    given as (col,row) grid coords; edges must point left-to-right (lower->higher col)."""
    if not g or not g.get("nodes"):
        return ""
    nodes = {n["id"]: n for n in g["nodes"]}
    NW, NH, CX, CY, PAD = 128, 36, 168, 66, 16
    def cx(n): return PAD + n["col"] * CX
    def cy(n): return PAD + n["row"] * CY
    maxc = max(n["col"] for n in nodes.values())
    maxr = max(n["row"] for n in nodes.values())
    W = PAD + maxc * CX + NW + PAD
    H = PAD + maxr * CY + NH + PAD
    s = [f'<svg class="dg" viewBox="0 0 {int(W)} {int(H)}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;max-width:{int(W)}px;height:auto">']
    s.append('<defs><marker id="dgar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" '
             'markerUnits="strokeWidth"><path d="M0,0 L7,3 L0,6 Z" fill="#9aa4af"/></marker></defs>')
    for a, b in g.get("edges", []):
        na, nb = nodes.get(a), nodes.get(b)
        if not na or not nb:
            continue
        x1, y1 = cx(na) + NW, cy(na) + NH / 2
        x2, y2 = cx(nb) - 2, cy(nb) + NH / 2
        mx = (x1 + x2) / 2
        s.append(f'<path d="M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
                 f'fill="none" stroke="#c0c6cd" stroke-width="1.5" marker-end="url(#dgar)"/>')
    for n in nodes.values():
        x, y = cx(n), cy(n)
        s.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" rx="8" '
                 f'fill="#f6f8fa" stroke="#d0d7de" stroke-width="1"/>')
        s.append(f'<text x="{x+NW/2:.0f}" y="{y+NH/2+4:.0f}" text-anchor="middle" '
                 f'font-family="SF Mono,ui-monospace,monospace" font-size="12.5" font-weight="600" '
                 f'fill="#1f2328">{esc(n["id"])}</text>')
    s.append('</svg>')
    wrap = ['<div class="dgwrap">', "".join(s)]
    if g.get("note"):
        wrap.append(f'<div class="flow-note">{md_inline(g["note"])}</div>')
    wrap.append('</div>')
    return "".join(wrap)


def _tree_name(nd):
    # lens agents sometimes use branch/node/title/label instead of name - accept them all
    return nd.get("name") or nd.get("branch") or nd.get("node") or nd.get("title") or nd.get("label") or ""

def _tree_kids(nd):
    return nd.get("children") or nd.get("nodes") or nd.get("items") or []

def render_tree(nodes):
    if not nodes:
        return ""
    out = ['<ul class="tree">']
    for nd in nodes:
        if isinstance(nd, str):  # tolerate bare-string tree children from lens agents
            nd = {"name": nd}
        note = f' <span class="muted">- {md_inline(nd["note"])}</span>' if nd.get("note") else ""
        out.append(f'<li><span class="node">{esc(_tree_name(nd))}</span>{note}')
        kids = _tree_kids(nd)
        if kids:
            out.append(render_tree(kids))
        out.append('</li>')
    out.append('</ul>')
    return "".join(out)


# Per-branch color families (one per top-level feature). Each entry gives a
# strong shade for the branch head (level 1) and a light shade for its leaves,
# so every top-level branch and all its descendants read as one color family.
#   (l1_fill, l1_text, l1_border, leaf_fill, leaf_text, leaf_border, edge)
BRANCH_PAL = [
    ("#ddf4ff", "#0a3069", "#4493f8", "#f2f9ff", "#28517a", "#b6e3ff", "#4493f8"),  # blue
    ("#dafbe1", "#0f5323", "#2da44e", "#f0fdf4", "#245c37", "#aceebb", "#2da44e"),  # green
    ("#f3ebff", "#512a97", "#8250df", "#faf6ff", "#492f7c", "#e0c9ff", "#8250df"),  # purple
    ("#fff1e5", "#7a3c00", "#e16f24", "#fff8f2", "#6b3f14", "#ffd8b5", "#e16f24"),  # orange
    ("#d9fbf4", "#0a4f47", "#12b3a0", "#f0fdfa", "#255f57", "#9ee9dd", "#12b3a0"),  # teal
    ("#ffeef0", "#82071e", "#e5484d", "#fff5f6", "#6b2b30", "#ffcdd2", "#e5484d"),  # red/pink
    ("#fff7cc", "#5c4200", "#d4a900", "#fffceb", "#54460d", "#f2df8f", "#d4a900"),  # amber
    ("#e8eaff", "#2d2b8a", "#6366f1", "#f4f5ff", "#33357a", "#c7ccff", "#6366f1"),  # indigo
]
ROOT_COLORS = ("#1a1a2e", "#ffffff", "#1a1a2e", "#cbd5e1")  # fill, text, border, note


def render_features_mindmap(root_label, tree):
    """Turn the features tree into a horizontal node-link mindmap as inline SVG
    (root on the left, branches fanning right). Self-contained, no JS, scrolls
    horizontally on narrow screens. Coloring is per top-level branch: each
    branch and all its descendants share one color family (see BRANCH_PAL)."""
    if not tree:
        return ""
    ROWH, COLW, PADX, PADY = 52, 250, 16, 16
    NW, NH = 210, 26
    nodes, edges, leaf = [], [], [0]

    def wrap(s, n):
        s = (s or "").strip()
        return s if len(s) <= n else s[:n - 1] + "…"

    def walk(node, depth, parent, branch):
        if isinstance(node, str):  # tolerate bare-string tree children from lens agents
            node = {"name": node}
        idx = len(nodes)
        nodes.append({"name": _tree_name(node), "note": node.get("note", ""),
                      "depth": depth, "branch": branch, "y": 0.0})
        if parent is not None:
            edges.append((parent, idx))
        kids = _tree_kids(node)
        if not kids:
            nodes[idx]["y"] = leaf[0] * ROWH
            leaf[0] += 1
        else:
            ys = []
            for i, k in enumerate(kids):
                # root's direct children each seed a new color family; deeper
                # nodes inherit their ancestor branch.
                b = i if depth == 0 else branch
                ci = walk(k, depth + 1, idx, b)
                ys.append(nodes[ci]["y"])
            nodes[idx]["y"] = sum(ys) / len(ys)
        return idx

    walk({"name": root_label, "children": tree}, 0, None, None)
    maxd = max(n["depth"] for n in nodes)
    W = PADX * 2 + maxd * COLW + 220
    H = PADY * 2 + max(1, leaf[0]) * ROWH

    def fam(n): return BRANCH_PAL[n["branch"] % len(BRANCH_PAL)]

    def colors(n):
        if n["depth"] == 0:
            return ROOT_COLORS
        p = fam(n)
        return (p[0], p[1], p[2], p[1]) if n["depth"] == 1 else (p[3], p[4], p[5], p[4])

    def nx(n): return PADX + n["depth"] * COLW
    def ny(n): return PADY + n["y"] + (ROWH - NH) / 2

    s = [f'<div class="fmm"><svg viewBox="0 0 {int(W)} {int(H)}" '
         f'xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:{int(W)}px;height:auto">']
    # edges: tinted to the target node's branch color family so connectors read
    # as part of the same colored branch.
    for a, b in edges:
        na, nb = nodes[a], nodes[b]
        stroke = fam(nb)[6] if nb["branch"] is not None else "#c0c6cd"
        x1, y1 = nx(na) + NW, ny(na) + NH / 2
        x2, y2 = nx(nb) - 2, ny(nb) + NH / 2
        mx = (x1 + x2) / 2
        s.append(f'<path d="M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
                 f'fill="none" stroke="{stroke}" stroke-width="1.8" stroke-opacity="0.55"/>')
    for n in nodes:
        fill, txt, bd, nc = colors(n)
        x, y = nx(n), ny(n)
        label = wrap(n["name"], 30)
        note = wrap(n["note"], 34) if n["note"] else ""
        bh = NH if not note else NH + 12
        sw = "1.5" if n["depth"] <= 1 else "1"
        s.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{bh}" rx="7" '
                 f'fill="{fill}" stroke="{bd}" stroke-width="{sw}"/>')
        ty = y + (16 if not note else 14)
        fw = "700" if n["depth"] <= 1 else "600"
        s.append(f'<text x="{x+10:.0f}" y="{ty:.0f}" font-family="-apple-system,Segoe UI,sans-serif" '
                 f'font-size="12.5" font-weight="{fw}" fill="{txt}">{esc(label)}</text>')
        if note:
            s.append(f'<text x="{x+10:.0f}" y="{y+bh-6:.0f}" font-family="-apple-system,Segoe UI,sans-serif" '
                     f'font-size="10.5" fill="{nc}" fill-opacity="0.85">{esc(note)}</text>')
    s.append('</svg></div>')
    return "".join(s)


def _render_recon(data, A):
    """Render the onboarding brief section from data["recon"] (merged from repo-recon)."""
    rec = data.get("recon")
    if not rec:
        return
    sec = '<div class="card" style="margin-top:20px;page-break-inside:avoid">'
    sec += ('<h2 style="font-size:17px;font-weight:800;color:#1f2328;margin-bottom:14px;'
            'border-bottom:1px solid #e1e4e8;padding-bottom:10px">'
            '<i class="fa-solid fa-person-chalkboard" style="margin-right:8px;color:#0969da"></i>'
            'Onboarding Brief</h2>')
    A(sec)

    def sub(title, icon):
        A(f'<h3 style="font-size:12.5px;font-weight:700;color:#57606a;text-transform:uppercase;letter-spacing:.06em;margin:16px 0 8px">'
          f'<i class="fa-solid {icon}" style="margin-right:5px"></i>{esc(title)}</h3>')
    def tbl2(rows, hdr=None):
        th = "".join(f'<th style="padding:5px 10px;background:#f6f8fa;border:1px solid #d0d7de;font-size:12px">{esc(h)}</th>' for h in (hdr or []))
        trs = "".join('<tr>' + "".join(f'<td style="padding:5px 10px;border:1px solid #e1e4e8;font-size:12px;vertical-align:top">{c}</td>' for c in r) + '</tr>' for r in rows)
        return f'<div style="overflow-x:auto;margin-bottom:8px"><table style="border-collapse:collapse;width:100%"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'
    def ul(items):
        return '<ul style="margin:0 0 8px 18px;font-size:12.5px">' + "".join(f'<li style="margin:2px 0">{esc(str(x))}</li>' for x in items) + '</ul>'

    gs = rec.get("get_started", {})
    if gs:
        sub("Get Started", "fa-play-circle")
        if gs.get("prereqs"): A(ul(gs["prereqs"]))
        if gs.get("commands"): A(tbl2([[f'<code style="font-size:12px">{esc(c[0])}</code>', esc(c[1]) if len(c) > 1 else ""] for c in gs["commands"]], ["Command", "What it does"]))
        if gs.get("env"): A(tbl2([[f'<code style="font-size:12px">{esc(e[0])}</code>', esc(e[1]) if len(e) > 1 else ""] for e in gs["env"]], ["Env var", "Note"]))
        if gs.get("first_hour"): A(ul(gs["first_hour"]))

    ww = rec.get("where_to_work", {})
    if ww:
        sub("Where to Work", "fa-code-fork")
        if ww.get("hotspots"): A(tbl2([[esc(str(h[0])), esc(str(h[1])), esc(h[2]) if len(h) > 2 else ""] for h in ww["hotspots"]], ["File", "Changes (6mo)", "Note"]))
        if ww.get("key_dirs"): A(tbl2([[f'<code style="font-size:12px">{esc(str(d[0]))}</code>', esc(d[1]) if len(d) > 1 else ""] for d in ww["key_dirs"]], ["Dir", "What it is"]))
        if ww.get("ticket_map"): A(tbl2([[esc(str(t[0])), esc(t[1]) if len(t) > 1 else ""] for t in ww["ticket_map"]], ["Ticket type", "Files you touch"]))

    pr = rec.get("pr_process", {})
    if pr:
        sub("PR Process", "fa-code-pull-request")
        pills = []
        if pr.get("median_loc") is not None: pills.append(f'Median {pr["median_loc"]} LOC')
        if pr.get("p90_loc") is not None: pills.append(f'p90 {pr["p90_loc"]} LOC')
        if pr.get("median_files") is not None: pills.append(f'{pr["median_files"]} files/PR')
        if pr.get("median_merge"): pills.append(f'Merges {pr["median_merge"]}')
        if pills:
            A('<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">' +
              "".join(f'<span style="background:#ddf4ff;border:1px solid #54aeff;border-radius:12px;padding:2px 10px;font-size:12px;font-weight:600">{esc(p)}</span>' for p in pills) +
              '</div>')
        if pr.get("branch_convention"): A(f'<p style="font-size:12.5px;margin:4px 0"><strong>Branch:</strong> <code>{esc(pr["branch_convention"])}</code></p>')
        if pr.get("approvals_note"): A(f'<p style="font-size:12.5px;margin:4px 0"><strong>Approvals:</strong> {esc(pr["approvals_note"])}</p>')
        if pr.get("review_model"): A(f'<p style="font-size:12.5px;margin:4px 0 8px"><strong>Review model:</strong> {esc(pr["review_model"])}</p>')
        if pr.get("top_reviewers"): A(tbl2([[esc(str(r[0])), esc(str(r[1]))] for r in pr["top_reviewers"]], ["Reviewer", "Approvals"]))
        if pr.get("ci_gates"): A(ul(pr["ci_gates"]))
        if pr.get("codeowners"): A(f'<p style="font-size:12px;color:#57606a;margin:4px 0"><strong>CODEOWNERS:</strong> {esc(pr["codeowners"])}</p>')

    who = rec.get("who_is_who", [])
    if who:
        sub("Who's Who", "fa-users")
        A(tbl2([[esc(str(w[0])), esc(w[1]) if len(w) > 1 else ""] for w in who], ["Name", "Owns / area"]))

    wn = rec.get("work_nature", {})
    if wn:
        sub("Work Nature", "fa-chart-pie")
        if wn.get("summary"): A(f'<p style="font-size:12.5px;margin:0 0 8px">{esc(wn["summary"])}</p>')
        if wn.get("breakdown"): A(tbl2([[esc(str(b[0])), esc(str(b[1]))] for b in wn["breakdown"]], ["Kind", "Share"]))

    gl = rec.get("glossary", [])
    if gl:
        sub("Glossary", "fa-book")
        A(tbl2([[f'<strong style="font-size:12px">{esc(str(g[0]))}</strong>', esc(g[1]) if len(g) > 1 else ""] for g in gl], ["Term", "Meaning"]))

    fp = rec.get("first_prs", [])
    if fp:
        sub("Your First PRs", "fa-star")
        A(tbl2([[f'<strong style="font-size:12px">{esc(str(p[0]))}</strong>', esc(p[1]) if len(p) > 1 else "", f'<code style="font-size:12px">{esc(p[2]) if len(p) > 2 else ""}</code>'] for p in fp], ["PR idea", "Why", "Files"]))

    A('</div>')


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        print(__doc__.split("Input contract")[0].strip()); sys.exit(1)
    # Parse the flags by name and REFUSE anything unknown: a typo'd --no-opne used
    # to be ignored silently, so the browser opened on a CI box and nobody noticed.
    src, out_override, known = argv[0], None, {"--no-open", "--out"}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            i += 1
            if i >= len(argv):
                sys.exit("render: --out needs a file path")
            out_override = argv[i]
        elif a not in known:
            sys.exit(f"render: unknown option {a!r} (known: {', '.join(sorted(known))})")
        i += 1
    try:
        with open(src, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        sys.exit(f"render: cannot read {src}: {e}")
    except ValueError as e:
        sys.exit(f"render: {src} is not valid JSON: {e}")
    if not isinstance(data, dict):
        sys.exit(f"render: {src} must contain a JSON object, got {type(data).__name__}")
    repo = data.get("repo", "repo")
    repo_url = data.get("repo_url", "")
    # Post title = owner/repo slug ONLY (no "Repo Audit -" prefix, no date). Derive
    # owner/repo from the GitHub URL when present, else fall back to the bare repo
    # display name.
    repo_slug = repo
    if repo_url:
        _m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", repo_url)
        if _m:
            repo_slug = _m.group(1)
    # Scoped runs (--only=<lens>) append the lens list to the title so the run
    # scope is visible at a glance, e.g. "acme/orders-api (infra)".
    _args = data.get("args", "")
    _only = re.search(r"--only=([\w,\-]+)", _args)
    if _only:
        repo_slug += f" ({_only.group(1).replace(',', ', ')})"
    path = data.get("path", "")
    branch = data.get("branch", "main")
    # Expose to md_inline so auto-detected file:line refs in prose link to the repo.
    # A repo_url that is not a real web URL never becomes an href anywhere in the
    # report - javascript:, data: and file: are dropped to plain text instead.
    if repo_url and not SAFE_URL.match(repo_url):
        repo_url = ""
    global _REPO_URL, _BRANCH
    _REPO_URL, _BRANCH = repo_url, branch
    commit = data.get("commit", "")
    stack = data.get("stack", [])
    tech_stack = data.get("tech_stack", [])
    scanned = dict(data.get("scanned") or {})
    # Files + LOC are MANDATORY in every report (owner rule 2026-08-23: a report
    # without scan scope is useless). Self-heal from the repo when the collector
    # forgot, and refuse to render if they still can't be determined.
    if not (scanned.get("files") and scanned.get("loc")):
        if path and os.path.isdir(path):
            import subprocess
            try:
                ls = subprocess.run(["git", "-C", path, "ls-files"],
                                    capture_output=True, text=True, timeout=60)
                skip = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.next|\.git|coverage)(/|$)"
                                  r"|(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|composer\.lock)$"
                                  r"|\.min\.(js|css)$")
                names = [f for f in ls.stdout.splitlines() if f and not skip.search(f)]
                if names and not scanned.get("files"):
                    scanned["files"] = len(names)
                if names and not scanned.get("loc"):
                    total = 0
                    for f in names:
                        try:
                            with open(os.path.join(path, f), "rb") as fh:
                                head = fh.read(1024)
                                if b"\0" in head:
                                    continue  # binary
                                total += head.count(b"\n")
                                for chunk in iter(lambda: fh.read(1 << 20), b""):
                                    total += chunk.count(b"\n")
                        except OSError:
                            continue
                    scanned["loc"] = total
            except Exception:
                pass
        if not (scanned.get("files") and scanned.get("loc")):
            sys.exit("FATAL: scanned.files + scanned.loc are required in data.json "
                     "(owner rule: every report must show Files + LOC). Pass a valid "
                     "\"path\" so the renderer can compute them, or fill \"scanned\" yourself.")
    lenses = data.get("lenses", {})
    bottom = data.get("bottom_line", "")
    stamp = data.get("stamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.date.today().isoformat()

    # Optional branding overrides so sibling skills reuse this
    # exact renderer with their own lens names. Look and feel never changes.
    # Branding overrides are the only data that reaches the page as MARKUP rather
    # than as text: the icon lands inside a class attribute and the label is
    # serialized into an inline <script>. Both are sanitised here, at the single
    # point they enter the render, rather than at each of their sinks - the data
    # JSON is written by an agent that has just read an untrusted repo, so a
    # prompt-injected payload must not be able to reach either.
    lens_labels = {k: str(v) for k, v in (data.get("lens_labels") or {}).items()}
    lens_icons = {k: v for k, v in (data.get("lens_icons") or {}).items()
                  if isinstance(v, str) and ICON_OK.match(v)}
    LENSES = [(k, lens_labels.get(k, lbl), lens_icons.get(k, ic), col)
              for k, lbl, ic, col in LENS_ORDER]
    chip = data.get("chip", "/repo-audit")
    out_prefix = data.get("out_prefix", "repo-audit")
    post_cfg = data.get("post", {})

    all_finds = []
    for k in ("infra", "security", "performance", "quality", "tests", "docs", "uiux"):
        all_finds += (lenses.get(k) or {}).get("findings", [])
    n = len(all_finds)
    by_sev = {k: sum(1 for f in all_finds if (f.get("severity") or "").lower() == k)
              for k in ("critical", "high", "medium", "low")}

    P = []
    A = P.append
    A('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    A(f'<title>{esc(chip.lstrip("/"))}</title>')
    A('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">')
    A('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>')
    A('''<style>
* { box-sizing:border-box; margin:0; padding:0; }
html { overflow-x:hidden; }
/* Owner-locked: whole report renders at 67% scale (reads like browser zoom 67%) - denser, fits cleanly. Never remove. */
body { zoom:0.67; background:#f6f8fa; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; min-height:100vh; padding:28px 44px; overflow-x:hidden; width:100%; }
.page { max-width:1680px; width:100%; margin:0 auto; position:relative; }
.chip { display:inline-block; font-family:'SF Mono','Fira Code',monospace; font-size:12px; background:#eef2ff; color:#5b6ab0; border:1px solid #c7d2fe; border-radius:6px; padding:2px 8px; margin-bottom:14px; }
.model-badge { display:inline-block; font-family:'SF Mono','Fira Code',monospace; font-size:12px; font-weight:700; border:1px solid; border-radius:6px; padding:2px 8px; margin:0 0 14px 6px; }
.model-badge i { margin-right:5px; }
/* Audited-app icon, always present, pinned top-right of the report (owner: MUST show
   the icon of the app that was audited). Auto-resolved from the repo's own assets or
   the optional REPO_AUDIT_ICON_REGISTRY; monogram fallback guarantees it never renders empty. */
.app-badge { position:absolute; top:14px; right:22px; width:64px; height:64px; display:flex; align-items:center; justify-content:center; }
.app-badge img { width:100%; height:100%; object-fit:contain; border-radius:14px; }
.app-badge .mono { width:64px; height:64px; border-radius:14px; background:#1f2d3d; color:#fff; font-weight:800; font-size:28px; display:flex; align-items:center; justify-content:center; font-family:-apple-system,BlinkMacSystemFont,sans-serif; box-shadow:0 2px 8px rgba(20,30,50,.18); letter-spacing:-.01em; }
h1 { font-size:20px; font-weight:700; color:#1f2328; margin-bottom:4px; display:flex; align-items:center; gap:8px; }
h1 i { color:#0969da; font-size:18px; }
.subtitle { font-size:12px; color:#444c56; font-family:'SF Mono','Fira Code',monospace; margin-bottom:16px; }
.card { background:#fff; border:1px solid #d0d7de; border-radius:10px; padding:16px 20px; margin-bottom:14px; }
.section-label { text-transform:uppercase; font-size:12px; font-weight:700; letter-spacing:.08em; color:#57606a; margin-bottom:8px; }
h2 { font-size:15px; font-weight:700; color:#1f2328; margin-bottom:12px; display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
h2 .g { margin-left:auto; }
a { color:#0969da; text-decoration:none; }
a:hover { text-decoration:underline; }
code { font-family:'SF Mono','Fira Code',monospace; font-size:12px; background:#f6f8fa; border:1px solid #d0d7de; border-radius:4px; padding:1px 5px; }
.badge { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:12px; font-size:12px; font-weight:600; border:1px solid; white-space:nowrap; }
.badge i { font-size:12px; opacity:.85; }
.badge-green { background:#dafbe1; color:#1a7f37; border-color:#a7e5b6; }
.badge-red { background:#ffebe9; color:#cf222e; border-color:#ffc1bc; }
.badge-yellow { background:#fff8c5; color:#9a6700; border-color:#ecd77e; }
.badge-blue { background:#ddf4ff; color:#0550ae; border-color:#addcff; }
.badge-black { background:#1f2328; color:#fff; border-color:#1f2328; }
.badge-grey { background:#f6f8fa; color:#57606a; border-color:#d0d7de; }
.tag { display:inline-block; background:#eef2ff; color:#5b6ab0; border:1px solid #c7d2fe; border-radius:6px; font-size:12px; padding:2px 8px; margin:0 6px 6px 0; font-family:'SF Mono',monospace; }
.muted { color:#57606a; font-size:12px; }
.summary { font-size:13.5px; line-height:1.65; color:#1f2328; margin-bottom:12px; }
.pills { display:flex; flex-wrap:wrap; gap:12px; }
.pill { background:#f6f8fa; border:1px solid #d0d7de; border-radius:8px; padding:10px 16px; min-width:88px; }
.pill .n { font-size:22px; font-weight:700; color:#424a53; }
.pill .l { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:#57606a; }
.pill.red { background:#ffebe9; border-color:#ffc1bc; }
.pill.red .n { color:#cf222e; } .pill.red .l { color:#a0202b; }
.pill.yellow { background:#fff8c5; border-color:#ecd77e; }
.pill.yellow .n { color:#9a6700; } .pill.yellow .l { color:#7a5200; }
.pill.blue { background:#ddf4ff; border-color:#addcff; }
.pill.blue .n { color:#0550ae; } .pill.blue .l { color:#0a4a8a; }
.pill.green { background:#dafbe1; border-color:#7ee2a8; }
.pill.green .n { color:#1a7f37; } .pill.green .l { color:#116329; }
.vit-line { margin-top:10px; font-size:12px; color:#57606a; line-height:1.6; }
.vit-line b { color:#1f2328; font-weight:700; }
.vit-line i { color:#8b949e; margin-right:3px; font-size:12px; }
.ov-flex { display:flex; gap:22px; align-items:center; flex-wrap:wrap; }
.ov-left { flex:1; min-width:260px; }
.ov-right { flex:0 0 auto; text-align:center; }
.ov-lbl { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:#57606a; margin-top:4px; }
.scorecard { display:flex; gap:4px; margin-top:14px; padding-top:12px; border-top:1px solid #eaecef; }
.sc-item { text-align:center; flex:1 1 0; min-width:0; }
.sc-lbl { font-size:12px; font-weight:700; color:#1f2328; margin-top:5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sc-lbl i { font-size:12px; margin-right:1px; }
ul.pts { margin:6px 0 0 18px; }
ul.pts li { font-size:13px; line-height:1.6; color:#1f2328; margin-bottom:4px; }
.finding { border:1px solid #e3e8ee; border-radius:8px; padding:14px 16px; margin-bottom:12px; }
.finding:last-child { margin-bottom:0; }
.finding .head { display:flex; flex-wrap:nowrap; align-items:flex-start; gap:10px; margin-bottom:8px; }
.finding .title { font-size:14px; font-weight:600; color:#1f2328; flex:1 1 auto; min-width:0; }
.finding .badges { margin-left:auto; display:flex; align-items:center; gap:6px; flex:0 0 auto; flex-wrap:wrap; justify-content:flex-end; }
.kv { font-size:12px; line-height:1.6; color:#1f2328; margin-top:4px; }
.kv b { color:#57606a; font-weight:600; }
.gbu { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
.gbu .col { border:1px solid #d0d7de; border-radius:8px; padding:14px; }
.gbu .col h3 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; margin-bottom:8px; display:flex; align-items:center; gap:6px; }
.gbu .good { background:#f2fcf5; border-color:#b6e6c2; } .gbu .good h3 { color:#1a7f37; }
.gbu .bad { background:#fffaf0; border-color:#f0d8a8; } .gbu .bad h3 { color:#9a6700; }
.gbu .ugly { background:#fff5f5; border-color:#f3c0bd; } .gbu .ugly h3 { color:#cf222e; }
.gbu ul { margin-left:16px; } .gbu li { font-size:12.5px; line-height:1.55; margin-bottom:5px; color:#1f2328; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; width:100%; border:1px solid #d0d7de; border-radius:8px; }
table { width:100%; border-collapse:collapse; font-size:12px; min-width:420px; }
th { text-align:left; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#57606a; padding:6px 10px; border-bottom:1px solid #d0d7de; white-space:nowrap; background:#f6f8fa; }
td { padding:6px 10px; border-bottom:1px solid #eaecef; color:#1f2328; vertical-align:top; }
tr:last-child td { border-bottom:none; }
.fmm { overflow-x:hidden; border:1px solid #d0d7de; border-radius:10px; background:#fff; padding:10px; margin-bottom:12px; }
.fmm-list { margin-top:6px; }
.fmm-list summary { cursor:pointer; color:#57606a; font-size:12px; font-weight:600; padding:4px 0; }
ul.tree, ul.tree ul { list-style:none; margin:0; padding-left:18px; }
ul.tree { padding-left:2px; }
ul.tree li { position:relative; padding:3px 0 3px 14px; font-size:13px; line-height:1.5; }
ul.tree li:before { content:""; position:absolute; left:0; top:14px; width:9px; height:1px; background:#c0c6cd; }
ul.tree ul li:before { background:#d8dce1; }
.node { font-weight:600; color:#1f2328; }
.tech-name { display:flex; align-items:center; gap:9px; font-weight:600; }
.tech-badge { width:22px; height:22px; flex:0 0 22px; border-radius:6px; background:#fff; border:1px solid #e0e4ea; display:inline-flex; align-items:center; justify-content:center; box-shadow:0 1px 2px rgba(0,0,0,.06); }
.tech-ico { width:14px; height:14px; object-fit:contain; display:block; }
.tech-mono { width:22px; height:22px; flex:0 0 22px; border-radius:6px; background:#eef2ff; color:#5b6ab0; border:1px solid #c7d2fe; display:inline-flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; font-family:'SF Mono',monospace; }
/* Icons sit on a permanently-white .tech-badge chip (this report is a fixed light theme, its
   background never darkens). Do NOT invert Simple Icons in dark mode - that turned black brand
   marks (Rust, Next.js) WHITE on the white chip, i.e. invisible. Brand colors render as-is. */
a.tech-link { display:inline-flex; align-items:center; }
.flow { margin:4px 0 16px; padding:14px 16px; background:#fbfcfe; border:1px solid #e4e8ed; border-radius:10px; }
.flane { display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin:6px 0; }
.flane-lbl { font-size:12px; font-weight:700; letter-spacing:.03em; text-transform:uppercase; padding:3px 9px; border-radius:999px; margin-right:4px; white-space:nowrap; }
.fnode { font-size:12px; font-weight:600; color:#1f2328; background:#f6f8fa; border:1px solid #d0d7de; border-radius:7px; padding:5px 10px; white-space:nowrap; }
.farr { color:#9aa4af; font-size:13px; font-weight:700; }
.flow-note { margin-top:10px; padding-top:9px; border-top:1px dashed #e4e8ed; font-size:12px; color:#57606a; line-height:1.55; }
.lyr { margin:4px 0 16px; padding:14px 16px; background:#fbfcfe; border:1px solid #e4e8ed; border-radius:10px; }
.lyr-dir { font-size:12px; font-weight:700; letter-spacing:.03em; text-transform:uppercase; color:#57606a; margin-bottom:8px; }
.lyr-box { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; padding:9px 13px; background:#fff; border:1px solid #d0d7de; border-radius:8px; }
.lyr-name { font-size:13px; font-weight:700; color:#0969da; font-family:'SF Mono',ui-monospace,monospace; }
.lyr-note { font-size:12px; color:#57606a; }
.lyr-arr { text-align:center; color:#9aa4af; font-size:15px; line-height:1.1; margin:2px 0; }
.mm { margin:4px 0 16px; padding:14px 16px; background:#fbfcfe; border:1px solid #e4e8ed; border-radius:10px; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.mm-root { flex:0 0 auto; padding:12px 16px; background:#0969da; color:#fff; font-weight:700; font-size:13px; border-radius:9px; font-family:'SF Mono',ui-monospace,monospace; }
.mm-branches { display:flex; flex-direction:column; gap:7px; border-left:2px solid #d0d7de; padding-left:14px; }
.mm-b { display:flex; align-items:baseline; gap:9px; flex-wrap:wrap; }
.mm-name { font-size:12px; font-weight:700; color:#1f2328; min-width:96px; }
.mm-det { font-size:12px; color:#57606a; }
.dgwrap { margin:4px 0 16px; padding:14px 16px; background:#fbfcfe; border:1px solid #e4e8ed; border-radius:10px; }
.dg { display:block; }
.bottomline { background:#dafbe1; border:1px solid #b6e6c2; border-radius:10px; padding:18px 22px; color:#1a4d2b; font-size:13px; }
.fixno { flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:#1f2328; color:#fff; font-size:12px; font-weight:700; }
.empty { color:#57606a; font-size:13px; font-style:italic; }
@media (max-width:600px){
  body{padding:12px;} .card{padding:12px 14px;} td,th{padding:5px 7px;font-size:12px;}
  h1{font-size:16px;} h2{font-size:13px;} .gbu{grid-template-columns:1fr;}
  .app-badge{width:48px;height:48px;} .app-badge .mono{width:48px;height:48px;font-size:22px;border-radius:10px;}
  /* tighter, tinier text on phones - no horizontal scroll anywhere */
  .subtitle{font-size:12px;} .summary{font-size:12px;line-height:1.55;}
  .pill{padding:8px 12px;min-width:74px;} .pill .n{font-size:18px;}
  ul.pts li{font-size:12px;} .gbu li{font-size:12px;} ul.tree li{font-size:12px;}
  .finding .title{font-size:12px;} .kv{font-size:12px;}
  .ov-flex{gap:14px;justify-content:center;} .ov-right canvas{width:96px !important;height:96px !important;}
  .scorecard{gap:2px;} .sc-item{flex:1 1 0;} .sc-lbl{font-size:12px;letter-spacing:-.02em;}
}
</style></head><body><div class="page">''')

    # owner/repo display (from the GitHub url when present, else the bare name)
    repo_disp = repo
    if repo_url:
        _m = re.search(r'github\.com[:/]+([^/]+/[^/.]+)', repo_url)
        if _m:
            repo_disp = _m.group(1)
    A(f'<span class="chip">{esc(chip)}</span>')
    if data.get("args"):
        A(f'<span class="model-badge" style="color:#57606a;border-color:#57606a66;background:#57606a14">'
          f'<i class="fa-solid fa-filter"></i>{esc(data["args"])}</span>')
    A(model_badge(data.get("model", "")))
    # Title = SHORT repo name (owner request 2026-07-17), blue + bold, linked when
    # a repo_url exists. The subtitle right below carries the full owner/repo path,
    # so the title never repeats the owner.
    repo_short = repo_disp.split("/")[-1].strip() or repo_disp
    # Audited-app icon badge, top-right, ALWAYS present (owner: must show the icon of
    # the app it audited). Auto-resolved from the repo/registry; monogram fallback.
    _app_icon = resolve_app_icon(data.get("app_icon", ""), path, repo_short)
    if _app_icon:
        _badge = f'<img src="{_app_icon}" alt="{esc(repo_short)}">'
    else:
        _badge = f'<span class="mono">{esc((repo_short[:1] or "?").upper())}</span>'
    A(f'<div class="app-badge">{_badge}</div>')
    if repo_url:
        h1_inner = f'<a href="{esc(repo_url)}" style="color:#0969da;text-decoration:none">{esc(repo_short)}</a>'
    else:
        h1_inner = esc(repo_short)
    # Brand mark: the repo-audit logo (magnifier-over-code with a score ring)
    # replaces the flat FA magnifier. Embedded as a data-URI so the report stays
    # self-contained (posted notes, PNG captures, offline files); falls back to
    # the FA glyph if logo-96.png is ever missing.
    _logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo-96.png")
    if os.path.exists(_logo):
        _b64 = base64.b64encode(open(_logo, "rb").read()).decode()
        brand = f'<img src="data:image/png;base64,{_b64}" alt="" style="height:30px;width:30px;vertical-align:-7px;margin-right:10px;border-radius:7px">'
    else:
        brand = '<i class="fa-solid fa-magnifying-glass" style="color:#0969da;font-size:0.78em;margin-right:10px"></i>'
    A(f'<h1 style="color:#0969da;font-weight:800">{brand}{h1_inner}</h1>')
    # Subtitle: owner/repo @ branch (commit) . date ET - the FULL path leads,
    # anchored to the GitHub repo; the timestamp moves to the END (owner request
    # 2026-07-17).
    sub_repo = (f'<a href="{esc(repo_url)}" style="color:#0969da;text-decoration:none">{esc(repo_disp)}</a>'
                if repo_url else esc(repo_disp))
    sub = f'{sub_repo} @ {esc(branch)}'
    if commit:
        sub += f' ({esc(commit)})'
    sub += f' . {esc(stamp)} ET'
    A(f'<div class="subtitle">{sub}</div>')

    # ---- scores: grade -> 0-100 per lens, overall = mean (drives the donuts) ----
    # "N/A" (e.g. uiux on a BE-only repo) = the lens is OMITTED entirely - no
    # donut, no lens card, and excluded from the overall mean (owner request).
    lens_scores = []
    for k, lbl, ic, accent in LENSES:
        g = ((lenses.get(k) or {}).get("grade") or "").strip()
        if g and g.upper() != "N/A" and g not in GRADE_SCORE:
            print(f"render: warning - lens {k!r} has grade {g!r}, which is not one of "
                  f"{', '.join(GRADE_SCORE)}; it is shown but excluded from the overall score",
                  file=sys.stderr)
        if g in GRADE_SCORE:
            lens_scores.append({"label": lbl.replace(" Audit", "").replace(" Supported", ""),
                                "grade": g, "score": GRADE_SCORE[g],
                                "color": GRADE_BADGE.get(g, "#57606a"),
                                "icon": ic, "accent": accent})
    overall = round(sum(s["score"] for s in lens_scores) / len(lens_scores)) if lens_scores else None

    # overview card - the repo name IS the H1 (owner request 2026-07-17), so the
    # card opens straight with the stats: no REPOSITORY eyebrow, no duplicate
    # name row, no local path chip.
    A('<div class="card"><div class="ov-flex"><div class="ov-left">')
    if stack and not tech_stack:
        A('<div style="margin-bottom:12px">' + "".join(f'<span class="tag">{esc(s)}</span>' for s in stack) + '</div>')
    # Row 1: the severity pills. Row 2: scan-scope (Files, LOC) on its own line
    # so the counts read in a clean, logical order.
    A('<div class="pills">')
    A(f'<div class="pill"><div class="n">{n}</div><div class="l">Findings</div></div>')
    A(f'<div class="pill red"><div class="n">{by_sev["critical"]+by_sev["high"]}</div><div class="l">Crit/High</div></div>')
    A(f'<div class="pill yellow"><div class="n">{by_sev["medium"]}</div><div class="l">Medium</div></div>')
    A(f'<div class="pill blue"><div class="n">{by_sev["low"]}</div><div class="l">Low</div></div>')
    A('</div>')
    if scanned.get("files") or scanned.get("loc"):
        A('<div class="pills" style="margin-top:8px">')
        if scanned.get("files"):
            A(f'<div class="pill"><div class="n">{scanned["files"]:,}</div><div class="l">Files</div></div>')
        if scanned.get("loc"):
            A(f'<div class="pill"><div class="n">{scanned["loc"]:,}</div><div class="l">LOC</div></div>')
        A('</div>')
    # vitality strip (repo-life signals) - ONE quiet meta line, never a 2nd pill row
    # (owner request 2026-07-02: pills wrapped to multiple rows and looked heavy)
    vit = data.get("vitality") or {}
    if vit:
        parts = []
        if vit.get("last_commit"):
            parts.append(f'last commit <b>{esc(str(vit["last_commit"]))}</b>')
        if vit.get("commits_90d") is not None:
            parts.append(f'<b>{vit["commits_90d"]:,}</b> commits/90d')
        if vit.get("contributors") is not None:
            parts.append(f'<b>{vit["contributors"]}</b> authors')
        if vit.get("bus_factor"):
            parts.append(f'bus factor <b style="color:#9a6700">{esc(str(vit["bus_factor"]))}</b>')
        if vit.get("stale_branches") is not None:
            parts.append(f'<b>{vit["stale_branches"]}</b> stale branches')
        if parts:
            A('<div class="vit-line"><i class="fa-solid fa-heart-pulse"></i> ' + ' &middot; '.join(parts) + '</div>')
    A('</div>')  # /ov-left
    # overall score donut (animated Chart.js, % centered) fills the top-right whitespace
    if overall is not None:
        A('<div class="ov-right"><canvas id="ovDonut" width="300" height="300" style="width:112px;height:112px;max-width:100%"></canvas></div>')
    A('</div>')  # /ov-flex
    # scorecard - one mini donut per graded lens (grade letter centered, % under it)
    if lens_scores:
        # per-lens = SOLID grade-colored circle (owner request: the circle fill is
        # the GRADE color so quality reads at a glance; the tiny lens icon under it
        # carries the lens color). The overall % keeps the donut.
        A('<div class="scorecard">')
        for s in lens_scores:
            col = s["color"]
            A(f'<div class="sc-item">'
              f'<div style="display:inline-flex;align-items:center;justify-content:center;'
              f'width:46px;height:46px;border-radius:50%;background:{col};color:{text_on(col)};'
              f'font-weight:800;font-size:16px;letter-spacing:.02em;box-shadow:0 2px 5px {col}55">{esc(s["grade"])}</div>'
              f'<div class="sc-lbl"><i class="fa-solid {s["icon"]}" style="color:{s["accent"]}"></i> {esc(s["label"])}</div></div>')
        A('</div>')
    A('</div>')

    # delta card (re-audit only - "since last audit" memory)
    delta = data.get("delta") or {}
    if delta:
        prev = f' <span class="muted" style="font-size:12px;font-weight:400">vs {esc(str(delta.get("prev_date","previous run")))}</span>'
        A('<div class="card">')
        A(f'<h2><i class="fa-solid fa-code-compare" style="color:#8250df"></i> Since Last Audit{prev}</h2>')
        A('<div class="pills">')
        A(f'<div class="pill green"><div class="n">{len(delta.get("fixed") or [])}</div><div class="l">Fixed</div></div>')
        A(f'<div class="pill red"><div class="n">{len(delta.get("new") or [])}</div><div class="l">New</div></div>')
        # "still" may be a count (int) or a list of descriptions - the pill shows
        # the count, the descriptions render below as a small line (never a raw list).
        still = delta.get("still")
        still_items = still if isinstance(still, list) else []
        still_count = len(still_items) if isinstance(still, list) else still
        if still_count is not None:
            A(f'<div class="pill"><div class="n">{esc(str(still_count))}</div><div class="l">Still Open</div></div>')
        A('</div>')
        if delta.get("grade_moves"):
            A('<div style="margin-top:10px">')
            for mv in delta["grade_moves"]:
                if len(mv) == 3:
                    A(f'<span class="tag" style="margin-right:6px">{esc(str(mv[0]))}: {esc(str(mv[1]))} -&gt; <b>{esc(str(mv[2]))}</b></span>')
            A('</div>')
        for label, key, color in (("Fixed", "fixed", "#1a7f37"), ("New", "new", "#cf222e"), ("Still open", "still", "#57606a")):
            items = still_items if key == "still" else (delta.get(key) or [])
            if items:
                A(f'<div class="kv" style="margin-top:8px"><b style="color:{color}">{label}:</b> '
                  + "; ".join(esc(str(i)) for i in items[:8])
                  + (f" (+{len(items)-8} more)" if len(items) > 8 else "") + '</div>')
        A('</div>')

    # top fixes card (right under the overview - the cross-lens action list)
    top_fixes = data.get("top_fixes", [])
    if top_fixes:
        lens_meta = {k: (lbl.replace(" Audit", ""), ic, acc) for k, lbl, ic, acc in LENSES}
        A('<div class="card">')
        A('<h2><i class="fa-solid fa-list-ol" style="color:#cf222e"></i> Top Fixes First</h2>')
        for i, f in enumerate(top_fixes[:5], 1):
            sb, sl = SEV_BADGE.get((f.get("severity") or "low").lower(),
                                   ("badge-grey", f.get("severity", "?")))
            A('<div class="finding"><div class="head">')
            A(f'<span class="fixno">{i}</span>')
            A(f'<span class="title">{esc(f.get("title",""))}</span>')
            A('<span class="badges">')
            if f.get("lens") in lens_meta:
                llbl, lic, lacc = lens_meta[f["lens"]]
                A(f'<span class="badge" style="background:{lacc};color:{text_on(lacc)};border-color:{lacc}"><i class="fa-solid {lic}"></i>{esc(llbl)}</span>')
            A(f'<span class="badge {sb}"><i class="fa-solid fa-bug"></i>{esc(sl)}</span>')
            if f.get("effort"):
                A(f'<span class="badge badge-grey"><i class="fa-solid fa-hourglass-half"></i>{esc(f["effort"])}</span>')
            A('</span></div>')
            if f.get("file"):
                A(f'<div class="kv"><b>Where:</b> {file_ref(repo_url, branch, f["file"])}</div>')
            if f.get("why"):
                A(f'<div class="kv"><b>Why first:</b> {md_inline(f["why"])}</div>')
            if f.get("fix"):
                A(f'<div class="kv"><b>Fix:</b> {md_inline(f["fix"])}</div>')
            A('</div>')
        A('</div>')

    # tech stack card (above architect lens)
    if tech_stack:
        A('<div class="card">')
        A('<h2><i class="fa-solid fa-layer-group" style="color:#0969da"></i> Tech Stack</h2>')
        A('<div class="table-wrap"><table style="min-width:560px"><thead><tr>'
          '<th style="width:40%">Tech</th><th style="width:22%">Category</th><th style="width:38%">Version</th></tr></thead><tbody>')
        import re as _re
        def _domain(u):
            m = _re.search(r"https?://([^/]+)", u or "")
            return m.group(1).lstrip("www.") if m else ""
        for t in tech_stack:
            name = esc(t.get("name", ""))
            slug = SLUG_FIX.get((t.get("slug") or "").strip().lower(), (t.get("slug") or "").strip())
            icon = (t.get("icon") or "").strip()          # explicit direct logo URL (wins)
            url = t.get("url", "")
            cat = esc(t.get("category", ""))
            ver = esc(str(t.get("version", "")) if t.get("version") not in (None, "") else "-")
            # Build the logo source priority: explicit icon URL -> Simple Icons slug ->
            # DuckDuckGo favicon of the official domain. Each falls back to the next on
            # error, and only a truly url-less, slug-less entry ends as a monogram.
            dom = _domain(url)
            fav = f"https://icons.duckduckgo.com/ip3/{dom}.ico" if dom else ""
            # Terminal fallback: a clean letter badge, NEVER a broken/blank image. &quot;
            # delimits the JS string so the single-quoted class survives inside the attr.
            setmono = f"this.onerror=null;this.outerHTML=&quot;<span class='tech-mono'>{esc(name[:1])}</span>&quot;"
            # An icon/slug that 404s tries the favicon next, and if THAT 404s too it
            # degrades to the letter badge - so a dead source can never leave a grey stub.
            via_fav = f"this.onerror=function(){{{setmono}}};this.src=&#39;{esc(fav)}&#39;" if fav else setmono
            if icon:
                src, oe = icon, via_fav
            elif slug:
                src, oe = f"https://cdn.simpleicons.org/{esc(slug)}", via_fav
            elif fav:
                src, oe = fav, setmono
            else:
                src = None
            if src:
                is_si = "simpleicons.org" in src
                cls = "tech-ico si-ico" if is_si else "tech-ico"
                img = f'<img class="{cls}" src="{esc(src)}" alt="{name}" loading="lazy" onerror="{oe}">'
                ico = f'<span class="tech-badge">{img}</span>'
            else:
                ico = f'<span class="tech-mono">{name[:1]}</span>'
            ico_link = f'<a class="tech-link" href="{esc(url)}" target="_blank" rel="noopener">{ico}</a>' if url else ico
            label = f'<a href="{esc(url)}" target="_blank" rel="noopener">{name}</a>' if url else name
            A(f'<tr><td><div class="tech-name">{ico_link}<span>{label}</span></div></td>'
              f'<td style="white-space:nowrap">{cat or "-"}</td><td style="white-space:nowrap"><code>{ver}</code></td></tr>')
        A('</tbody></table></div></div>')

    # per-lens cards
    for key, lbl, icon, color in LENSES:
        L = lenses.get(key)
        if not L:
            continue
        if ((L.get("grade") or "").strip().upper() in ("N/A", "NA")):
            continue  # N/A lens (e.g. uiux on a BE-only repo) is omitted from the report entirely
        A('<div class="card">')
        head = f'<h2><i class="fa-solid {icon}" style="color:{color}"></i> {esc(lbl)}'
        if L.get("grade"):
            head += f'<span class="g">{grade_pill(L["grade"])}</span>'
        head += '</h2>'
        A(head)
        if L.get("summary") and key != "architect":
            A(f'<div class="summary">{md_inline(L["summary"])}</div>')
        if L.get("flow"):
            A(render_flow(L["flow"]))
        if L.get("layers"):
            A(render_layers(L["layers"]))
        if L.get("mindmap"):
            A(render_mindmap(L["mindmap"]))
        if L.get("depgraph"):
            A(render_depgraph(L["depgraph"]))

        if key == "gbu":
            A('<div class="gbu">')
            for col, ttl, ico in (("good", "Good", "fa-circle-check"),
                                  ("bad", "Bad", "fa-triangle-exclamation"),
                                  ("ugly", "Ugly", "fa-skull")):
                items = L.get(col, [])
                A(f'<div class="col {col}"><h3><i class="fa-solid {ico}"></i> {ttl}</h3>')
                if items:
                    A('<ul>' + "".join(f'<li>{md_inline(x)}</li>' for x in items) + '</ul>')
                else:
                    A('<p class="empty">nothing noted</p>')
                A('</div>')
            A('</div>')

        elif key == "features":
            tree = L.get("tree", [])
            if tree:
                A(render_features_mindmap(repo, tree))
                A('<details class="fmm-list"><summary>Feature list</summary>')
                A(render_tree(tree))
                A('</details>')
            else:
                A('<p class="empty">no feature map provided</p>')

        elif key == "architect":
            # Lead with the high-level "how it's built / how it talks" flow (tech-logo
            # tiers + protocol arrows), then the file-layer diagram (auto-built from the
            # table). The verbose prose summary and the raw table go into collapsibles -
            # diagrams + bullet points carry the section.
            if L.get("arch_canvas"):
                A(render_arch_canvas(L["arch_canvas"]))
            elif L.get("stack_flow"):
                A(render_arch_flow(L["stack_flow"]))
            if L.get("critical_path"):
                A(render_critical_path(L["critical_path"]))
            if L.get("table"):
                A('<details open style="margin:6px 0 4px"><summary style="cursor:pointer;color:#57606a;font-size:12px;font-weight:600">File layers</summary>')
                A(render_arch_diagram(L["table"]))
                A('</details>')
            if L.get("summary"):
                A('<details style="margin:2px 0 10px"><summary style="cursor:pointer;color:#57606a;font-size:13px">Full summary</summary>')
                A(f'<div class="summary" style="margin-top:8px">{md_inline(L["summary"])}</div></details>')
            if L.get("points"):
                A('<ul class="pts">' + "".join(f'<li>{md_point(x)}</li>' for x in L["points"]) + '</ul>')
            if L.get("table"):
                rows = L["table"]
                A('<details style="margin-top:12px"><summary style="cursor:pointer;color:#57606a;font-size:13px">Layer table</summary>')
                A('<div class="table-wrap" style="margin-top:8px"><table><thead><tr>')
                A("".join(f'<th>{esc(c)}</th>' for c in rows[0]) + '</tr></thead><tbody>')
                for r in rows[1:]:
                    A('<tr>' + "".join(f'<td>{md_inline(str(c))}</td>' for c in r) + '</tr>')
                A('</tbody></table></div></details>')
            finds = L.get("findings", [])
            if finds:
                A('<div style="margin-top:14px">')
                render_findings(P, finds, repo_url, branch)
                A('</div>')

        else:
            if L.get("points"):
                A('<ul class="pts">' + "".join(f'<li>{md_point(x)}</li>' for x in L["points"]) + '</ul>')
            if L.get("table"):
                rows = L["table"]
                A('<div class="table-wrap" style="margin-top:12px"><table><thead><tr>')
                A("".join(f'<th>{esc(c)}</th>' for c in rows[0]) + '</tr></thead><tbody>')
                for r in rows[1:]:
                    A('<tr>' + "".join(f'<td>{md_inline(str(c))}</td>' for c in r) + '</tr>')
                A('</tbody></table></div>')
            if L.get("metrics"):
                A('<div class="pills" style="margin-top:12px">')
                for m in L["metrics"]:
                    A(f'<div class="pill"><div class="n" style="font-size:16px">{esc(m[1])}</div><div class="l">{esc(m[0])}</div></div>')
                A('</div>')
            finds = L.get("findings", [])
            if finds:
                A('<div style="margin-top:14px">')
                render_findings(P, finds, repo_url, branch)
                A('</div>')
            elif not L.get("points") and not L.get("summary"):
                A('<p class="empty">no findings</p>')
        A('</div>')

    if bottom:
        A(f'<div class="bottomline"><strong>Bottom line:</strong> {md_inline(bottom)}</div>')

    # Onboarding brief (merged from repo-recon, 2026-08-17)
    _render_recon(data, A)

    # donut init: overall (% centered) + one mini per lens (grade centered, % under)
    if lens_scores:
        chart_data = {"overall": {"score": overall, "grade": overall_grade(overall), "color": score_color(overall)},
                      "lenses": lens_scores}
        A('<script>')
        A(f'const SCORES = {script_json(chart_data)};')
        A('''
(function(){
  if (typeof Chart === "undefined") return;
  const center = { id:"center", afterDraw(ch){
    const o = ch.config.options.centerTxt || {}; const m = ch.getDatasetMeta(0).data[0]; if (!m) return;
    const ctx = ch.ctx; ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "800 " + o.big + "px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif";
    ctx.fillStyle = o.color; ctx.fillText(o.main, m.x, o.sub ? m.y - o.off : m.y);
    if (o.sub) { ctx.font = "700 " + o.small + "px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif";
      ctx.fillStyle = "#57606a"; ctx.fillText(o.sub, m.x, m.y + o.off + 2); }
    ctx.restore(); } };
  function donut(id, score, color, txt){
    const el = document.getElementById(id); if (!el) return;
    new Chart(el, { type: "doughnut",
      data: { datasets: [{ data: [score, 100 - score],
        backgroundColor: [color, "#eef1f4"], borderWidth: 0, borderRadius: 6 }] },
      options: { cutout: "89%", responsive: false, devicePixelRatio: 2, events: [],
        animation: { animateRotate: true, duration: 1100, easing: "easeOutQuart" },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        centerTxt: txt },
      plugins: [center] });
  }
  // the donut CHART is the overall score only; per-lens are solid grade circles (no chart)
  // Center shows the LETTER GRADE big (e.g. B+) with the % under it (owner request 2026-08-18).
  donut("ovDonut", SCORES.overall.score, SCORES.overall.color,
        { main: SCORES.overall.grade, big: 58, small: 19, off: 19, sub: SCORES.overall.score + "%", color: SCORES.overall.color });
})();''')
        A('</script>')
    # Token-cost footer removed (owner request 2026-08-18): repo-audit reports no
    # longer append the "Token cost / /repo-audit" section on any run.

    A('</div></body></html>')

    os.makedirs("reports", exist_ok=True)
    out = out_override or f"reports/{out_prefix}-{re.sub(chr(92)+'W+','-',repo).strip('-').lower()}-{today}.html"
    try:
        with open(out, "w") as fh:
            fh.write("\n".join(P))
    except IsADirectoryError:
        sys.exit(f"render: --out {out!r} is a directory, not a file")
    except OSError as e:
        sys.exit(f"render: cannot write {out!r}: {e}")

    # The report is always written to disk; opening it in a browser is left to the
    # caller. Posting it somewhere is an OPTIONAL, generic hook - off by default.

    posted = "skipped"
    # OPTIONAL post hook. To enable, set BOTH AUDIT_POST_URL (the endpoint to POST to)
    # and AUDIT_POST_TOKEN (a bearer token) in your OWN environment - never read from
    # the audited repo, since that repo is untrusted input and must not be able to
    # redirect the post elsewhere. When either is unset the post is simply skipped -
    # never an error. Payload is exactly {title, content, type: "html"}; point
    # AUDIT_POST_URL at any endpoint that accepts that shape.
    base = os.environ.get("AUDIT_POST_URL")
    tok = os.environ.get("AUDIT_POST_TOKEN")
    if base and tok:
        try:
            import urllib.request
            payload = json.dumps({
                "title": post_cfg.get("title", repo_slug),
                "content": open(out).read(),
                "type": "html",
            }).encode()
            req = urllib.request.Request(base, data=payload,
                                         headers={"Authorization": f"Bearer {tok}",
                                                  "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            posted = "posted"
        except Exception as e:
            posted = f"warn: {e}"

    print(f"repo-audit: {repo} | {n} findings | "
          f"{by_sev['critical']}C/{by_sev['high']}H/{by_sev['medium']}M/{by_sev['low']}L | "
          f"{out} | post: {posted}")


if __name__ == "__main__":
    main()
