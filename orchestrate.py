#!/usr/bin/env python3
"""
orchestrate.py - the deterministic glue of /repo-audit (owner rule 2026-09-30).

Everything in an audit that is NOT judgment lives here so it runs the same way every
time and never through a chat transcript again:

  scope   <owner/repo | url | path> --out DIR   clone/refresh into ~/code/<name>, measure
                                                 files/LOC/vitality/churn/GitHub health/
                                                 dependency advisories, write DIR/scope.json
                                                 and DIR/base.json (report skeleton)
  finish  DIR [--no-post] [--no-diagrams] [--reports-dir D]
                                                 merge DIR/<lens>.json + DIR/synthesis.json,
                                                 normalise, de-dup GBU, run the evidence gate
                                                 (verify.py --prune), build the 3 app diagrams
                                                 (Flows / Sequences / Mindmaps), render, archive,
                                                 post to Stickies, print a JSON summary

The lens JSONs and synthesis.json are written by the strong-model agents that the saved
workflow fans out (workflow/repo-audit.js). This file never calls a model.

Secrets: Flows / Sequences / Mindmaps creates run locally when FLOWS_API_SECRET /
SEQUENCES_API_SECRET / MINDMAPS_API_SECRET are in the environment, otherwise the payload is
shipped to the M4 over `ssh M4 'bash -s'` and the secret is read there from the app's .env.
Python 3.9 compatible on purpose (the work Mac ships 3.9).
"""
import base64
import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
CODE = HOME / "code"
TODAY = datetime.date.today().isoformat()
LENSES = ["architect", "infra", "security", "performance", "quality", "tests", "docs", "uiux", "features", "gbu"]
GRADED = ["architect", "infra", "security", "performance", "quality", "tests", "docs", "uiux", "features"]
SEV = {"crit": "critical", "high": "high", "med": "medium", "medi": "medium", "low": "low"}
CONF = {"h": "High", "m": "Med", "l": "Low"}
M4_SECRET_FILES = {
    "FLOWS_API_SECRET": "~/Sites/flows/.env",
    "SEQUENCES_API_SECRET": "~/Sites/sequences/.env.local",
    "MINDMAPS_API_SECRET": "~/Sites/mindmaps/.env.local",
}
MINDMAPS_USER = "731ace87-64e5-44db-bf2a-82265f06f4d9"


# ----------------------------------------------------------------------------- helpers
def sh(cmd, cwd=None, timeout=120, check=False, env=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True, text=True,
                       timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise RuntimeError("%s\n%s" % (cmd, r.stderr[-800:]))
    return r.stdout.strip()


def jload(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default


def jdump(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as fh:
        json.dump(obj, fh, indent=1)


def log(msg):
    print("orchestrate: " + msg, file=sys.stderr)


# ----------------------------------------------------------------------------- scope
def resolve_target(target):
    """Return (abs_path, name, slug, repo_url). Clones owner/repo or a GitHub URL into ~/code."""
    t = target.strip().rstrip("/")
    m = re.match(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?$", t)
    if Path(t).expanduser().exists():
        p = Path(t).expanduser().resolve()
        url = sh("git config --get remote.origin.url", cwd=p)
        slug = None
        mm = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url or "")
        if mm:
            slug = mm.group(1)
        return p, p.name, slug or p.name, ("https://github.com/" + slug) if slug else None
    if not m:
        sys.exit("scope: cannot resolve target %r (path, owner/repo or GitHub URL)" % target)
    owner, name = m.group(1), m.group(2)
    p = CODE / name
    CODE.mkdir(exist_ok=True)
    if (p / ".git").exists():
        sh("git fetch -q --depth=200 origin && git reset -q --hard @{u}", cwd=p, timeout=300)
    else:
        sh(["gh", "repo", "clone", owner + "/" + name, str(p), "--", "--depth=200", "--no-tags", "-q"],
           timeout=600, check=True)
    return p, name, owner + "/" + name, "https://github.com/%s/%s" % (owner, name)


def count_loc(repo):
    files = sh("git ls-files", cwd=repo).splitlines()
    skip = re.compile(r"(lock|\.(png|jpe?g|gif|svg|ico|woff2?|ttf|mp4|pdf|webp|zip|jar)$|node_modules/|vendor/|dist/|build/|\.next/)")
    total = 0
    for f in files:
        if skip.search(f):
            continue
        try:
            with open(repo / f, "rb") as fh:
                total += fh.read().count(b"\n")
        except Exception:
            pass
    return len(files), total, files


def detect_stack(repo, files):
    hints, manifests = [], {}
    pj = repo / "package.json"
    if pj.exists():
        p = jload(pj, {})
        deps = dict(p.get("dependencies", {}))
        deps.update(p.get("devDependencies", {}))
        manifests["package.json"] = {"name": p.get("name"), "scripts": p.get("scripts", {}),
                                     "dependencies": p.get("dependencies", {}),
                                     "devDependencies": p.get("devDependencies", {}),
                                     "engines": p.get("engines")}
        for k, label in [("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("@angular/core", "Angular"),
                         ("vite", "Vite"), ("typescript", "TypeScript"), ("express", "Express"),
                         ("@nestjs/core", "NestJS"), ("jest", "Jest"), ("vitest", "Vitest"),
                         ("playwright", "Playwright"), ("cypress", "Cypress"), ("storybook", "Storybook")]:
            if k in deps:
                hints.append(label)
        if (repo / "yarn.lock").exists():
            hints.append("Yarn")
        elif (repo / "pnpm-lock.yaml").exists():
            hints.append("pnpm")
        elif (repo / "package-lock.json").exists():
            hints.append("npm")
    if (repo / "pyproject.toml").exists() or (repo / "requirements.txt").exists():
        hints.append("Python")
        for f in ("pyproject.toml", "requirements.txt"):
            if (repo / f).exists():
                manifests[f] = open(repo / f).read()[:4000]
    if (repo / "go.mod").exists():
        hints.append("Go")
    if any(f.endswith(".tf") for f in files):
        hints.append("Terraform")
    if (repo / "Dockerfile").exists():
        hints.append("Docker")
    if (repo / ".github" / "workflows").exists():
        hints.append("GitHub Actions")
    has_ui = any(f.endswith((".tsx", ".jsx", ".vue", ".svelte", ".html", ".css")) and "node_modules" not in f
                 for f in files)
    return hints, manifests, has_ui


def vitality(repo):
    last = sh("git log -1 --format=%cr", cwd=repo)
    c90 = sh("git rev-list --count --since=90.days HEAD", cwd=repo)
    short = sh("git shortlog -sn --no-merges HEAD", cwd=repo).splitlines()
    total = sum(int(l.split()[0]) for l in short if l.strip()) or 1
    top = int(short[0].split()[0]) if short else 0
    return {
        "last_commit": re.sub(r"^(\d+) (\w)\w* ago$", r"\1\2 ago", last) if last else "n/a",
        "commits_90d": int(c90 or 0),
        "contributors": len(short),
        "bus_factor": "%d%% 1 author" % round(100.0 * top / total),
        "stale_branches": "n/a (shallow clone)",
        "total_commits": total,
        "top_authors": [l.strip() for l in short[:6]],
    }


def churn(repo):
    out = sh("git log --format= --name-only --since=6.months | grep -vE 'lock|\\.snap' | sort | uniq -c | sort -rn | head -20",
             cwd=repo)
    if not out.strip():
        out = sh("git log --format= --name-only | grep -vE 'lock|\\.snap' | sort | uniq -c | sort -rn | head -20", cwd=repo)
    rows = []
    for l in out.splitlines():
        parts = l.strip().split(None, 1)
        if len(parts) == 2:
            rows.append([parts[1], int(parts[0])])
    return rows


def gh_health(slug, default_branch):
    if not slug or not shutil.which("gh"):
        return {}
    h = {}
    prs = jload_str(sh(["gh", "pr", "list", "--repo", slug, "--state", "open", "--json", "number,updatedAt,title"], timeout=60))
    if isinstance(prs, list):
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()
        h["open_prs"] = len(prs)
        h["stale_prs"] = sum(1 for p in prs if p.get("updatedAt", "") < cutoff)
    runs = jload_str(sh(["gh", "run", "list", "--repo", slug, "--limit", "10", "--json", "conclusion,name"], timeout=60))
    if isinstance(runs, list):
        h["recent_runs"] = ["%s %s" % (r.get("conclusion"), r.get("name")) for r in runs]
    rules = jload_str(sh(["gh", "api", "repos/%s/rules/branches/%s" % (slug, default_branch)], timeout=60))
    h["rulesets"] = [r.get("type") for r in rules] if isinstance(rules, list) else "unavailable"
    prot = sh(["gh", "api", "repos/%s/branches/%s/protection" % (slug, default_branch), "--jq",
               ".required_pull_request_reviews.required_approving_review_count"], timeout=60)
    h["classic_protection_reviews"] = prot if prot and not prot.startswith("{") else "none (404)"
    return h


def jload_str(s):
    try:
        return json.loads(s)
    except Exception:
        return None


def dep_audit(repo):
    """Warn-only dependency advisory scan. Reads the lockfile, never installs the repo's code."""
    res = {"tool": None, "summary": None, "high_critical_modules": []}
    try:
        if (repo / "yarn.lock").exists():
            res["tool"] = "yarn audit (npx yarn@1.22.22, lockfile only)"
            out = sh("npx --yes yarn@1.22.22 audit --json 2>/dev/null", cwd=repo, timeout=420)
            sev, mods = {}, set()
            for line in out.splitlines():
                d = jload_str(line)
                if not d:
                    continue
                if d.get("type") == "auditAdvisory":
                    a = d["data"]["advisory"]
                    sev[a["severity"]] = sev.get(a["severity"], 0) + 1
                    if a["severity"] in ("high", "critical"):
                        mods.add("%s (%s)" % (a["module_name"], a["severity"]))
            res["summary"] = sev
            res["high_critical_modules"] = sorted(mods)
        elif (repo / "package-lock.json").exists():
            res["tool"] = "npm audit --json"
            d = jload_str(sh("npm audit --json 2>/dev/null", cwd=repo, timeout=300)) or {}
            res["summary"] = (d.get("metadata") or {}).get("vulnerabilities")
            res["high_critical_modules"] = sorted("%s (%s)" % (k, v.get("severity")) for k, v in (d.get("vulnerabilities") or {}).items()
                                                  if v.get("severity") in ("high", "critical"))
        elif (repo / "uv.lock").exists() or (repo / "requirements.txt").exists():
            if shutil.which("pip-audit"):
                res["tool"] = "pip-audit"
                res["summary"] = sh("pip-audit -r requirements.txt 2>&1 | tail -5", cwd=repo, timeout=300)
            else:
                res["tool"] = "skipped: pip-audit not installed"
        else:
            res["tool"] = "skipped: no supported lockfile"
    except Exception as e:  # warn-only by contract
        res["tool"] = "failed: %s" % str(e)[:120]
    return res


def env_vars(repo):
    out = sh("grep -rhoE 'import\\.meta\\.env\\.[A-Z0-9_]+|process\\.env\\.[A-Z0-9_]+|os\\.environ\\[\"[A-Z0-9_]+\"\\]|os\\.getenv\\(\"[A-Z0-9_]+\"' "
             "src app lib config 2>/dev/null | sort | uniq -c | sort -rn | head -40", cwd=repo)
    return [l.strip() for l in out.splitlines()]


def cmd_scope(target, out):
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    repo, name, slug, url = resolve_target(target)
    branch = sh("git rev-parse --abbrev-ref HEAD", cwd=repo)
    commit = sh("git rev-parse --short HEAD", cwd=repo)
    nfiles, loc, files = count_loc(repo)
    hints, manifests, has_ui = detect_stack(repo, files)
    ext = {}
    for f in files:
        e = f.rsplit(".", 1)[-1] if "." in f.rsplit("/", 1)[-1] else "(none)"
        ext[e] = ext.get(e, 0) + 1
    scope = {
        "target": target, "abs": str(repo), "name": name, "slug": slug, "repo_url": url,
        "branch": branch, "commit": commit, "files": nfiles, "loc": loc,
        "filetypes": sorted(ext.items(), key=lambda kv: -kv[1])[:12],
        "top_level": sorted(os.listdir(repo)),
        "src_dirs": sorted(os.listdir(repo / "src")) if (repo / "src").is_dir() else [],
        "stack_hint": hints, "has_ui": has_ui, "manifests": manifests,
        "vitality": vitality(repo), "churn": churn(repo), "gh": gh_health(slug, branch),
        "dep_audit": dep_audit(repo), "env_vars": env_vars(repo),
        "tools": {t: bool(shutil.which(t)) for t in ("semgrep", "gitleaks", "cloc", "trivy", "tflint", "tfsec")},
        "scale_guard": loc > 150000 or nfiles > 3000,
    }
    jdump(out / "scope.json", scope)
    v = dict(scope["vitality"])
    v.pop("total_commits", None)
    v.pop("top_authors", None)
    base = {
        "repo": slug, "repo_url": url, "path": str(repo), "branch": branch, "commit": commit,
        "args": target, "model": "Fable 5.1", "stamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stack": hints[:8], "tech_stack": [], "scanned": {"files": nfiles, "loc": loc}, "vitality": v,
        "lenses": {} if has_ui else {"uiux": {"grade": "N/A", "summary": "No user-facing surface in this repo."}},
    }
    jdump(out / "base.json", base)
    # what the workflow needs to fill its prompt templates - small on purpose
    brief = {k: scope[k] for k in ("abs", "name", "slug", "repo_url", "branch", "commit", "files", "loc",
                                   "stack_hint", "has_ui", "top_level", "src_dirs", "scale_guard")}
    brief["manifest_summary"] = {
        "scripts": list((manifests.get("package.json") or {}).get("scripts", {}).keys())[:20],
        "runtime_deps": list((manifests.get("package.json") or {}).get("dependencies", {}).keys())[:60],
    } if "package.json" in manifests else {}
    brief["dep_audit"] = scope["dep_audit"]
    brief["gh"] = scope["gh"]
    brief["vitality"] = v
    brief["churn_top"] = scope["churn"][:10]
    brief["existing_lens_files"] = sorted(p.stem for p in out.glob("*.json") if p.stem in LENSES + ["recon", "synthesis"])
    print(json.dumps(brief))


# ----------------------------------------------------------------------------- finish helpers
def norm_findings(lenses, strip):
    for l in lenses.values():
        for f in l.get("findings", []):
            f["severity"] = SEV.get(str(f.get("severity", "low")).lower()[:4], str(f.get("severity", "low")).lower())
            f["confidence"] = CONF.get(str(f.get("confidence", "Med")).lower()[:1], "Med")
            for k in ("file", "evidence", "title", "consequence", "fix"):
                if isinstance(f.get(k), str):
                    f[k] = f[k].replace(strip, "")


def dedup_gbu(g, drop_idx):
    for k in ("bad", "ugly"):
        items = g.get(k, [])
        keep = []
        for i, x in enumerate(items):
            if i in drop_idx.get(k, []) or x.startswith("[likely dup]"):
                continue
            keep.append(x)
        g[k] = keep
    g["summary"] = (g.get("summary") or "") + " (De-duplicated at synthesis: items already reported by other lenses were removed.)"


CITE_RE = re.compile(r"^(?P<path>[\w./@+-]+):(?P<l1>\d+)")


def repair_evidence_paths(lenses, repo):
    """Lens agents sometimes quote a bare basename (`runTests.yml:24`) instead of the repo-relative
    path; verify.py then cannot resolve the fragment and FAILs a true finding. Rewrite such fragments
    to `<dir of the cited file>/<basename>` when that file exists. Deterministic, no judgment."""
    fixed = 0
    for l in lenses.values():
        for f in l.get("findings", []):
            cite_dir = os.path.dirname(str(f.get("file") or "").split(":")[0])
            out_lines = []
            for line in (f.get("evidence") or "").splitlines():
                m = CITE_RE.match(line.strip())
                if m and not (repo / m.group("path")).exists():
                    cand = os.path.join(cite_dir, os.path.basename(m.group("path"))) if cite_dir else None
                    if cand and (repo / cand).is_file():
                        line = line.replace(m.group("path") + ":", cand + ":", 1)
                        fixed += 1
                out_lines.append(line)
            f["evidence"] = "\n".join(out_lines)
    if fixed:
        log("repaired %d evidence fragment paths to repo-relative form" % fixed)


def hold_nonfile(lenses, repo):
    held = {}
    for k, l in lenses.items():
        keep = []
        for f in l.get("findings", []):
            fl = str(f.get("file") or "")
            path = fl.split(":")[0]
            nonfile = (fl.startswith("GitHub") or "(deleted" in fl or path == "" or
                       not (repo / path).exists() or (repo / path).is_file() and (repo / path).stat().st_size == 0)
            if nonfile and path and (repo / path).exists() and (repo / path).stat().st_size > 0:
                nonfile = False
            if nonfile:
                f["evidence"] = (f.get("evidence") or "") + "\n(Not a verifiable file:line in this repo - GitHub state, another repo, a deleted or empty file. Held out of the file gate by design and re-added at synthesis.)"
                held.setdefault(k, []).append(f)
            else:
                keep.append(f)
        l["findings"] = keep
    return held


def auto_top_fixes(lenses):
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    conf = {"High": 3, "Med": 2, "Low": 1}
    eff = {"S": 3, "M": 2, "L": 1}
    cands = []
    for k in GRADED:
        for f in (lenses.get(k) or {}).get("findings", []):
            score = rank.get(f["severity"], 1) * 10 + conf.get(f.get("confidence"), 2) * 2 + eff.get(f.get("effort"), 2)
            cands.append((score, k, f))
    cands.sort(key=lambda x: -x[0])
    return [{"title": f["title"], "lens": k, "severity": f["severity"], "file": f.get("file"),
             "why": f.get("consequence", ""), "fix": f.get("fix", ""), "effort": f.get("effort", "M")}
            for _, k, f in cands[:5]]


# ----------------------------------------------------------------------------- diagram plumbing
def have_local(secret):
    return bool(os.environ.get(secret))


def run_with_secret(secret, script_body):
    """script_body uses $SECRET. Runs locally if the env var exists, else on the M4 via ssh."""
    if have_local(secret):
        return sh("SECRET=\"$%s\"\n%s" % (secret, script_body), timeout=300)
    grep_key = "(SEQUENCES|DIAGRAMS)_API_SECRET" if secret == "SEQUENCES_API_SECRET" else secret
    remote = ("SECRET=$(grep -E '^%s=' %s | head -1 | cut -d= -f2- | tr -d '\"' | tr -d \"'\")\n%s"
              % (grep_key, M4_SECRET_FILES[secret], script_body))
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "M4", "bash -s"], input=remote, capture_output=True,
                       text=True, timeout=400)
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError("M4 run failed: " + r.stderr[-400:])
    return r.stdout.strip()


def fetch_bytes(url):
    r = subprocess.run(["curl", "-sL", "--max-time", "15", "-w", "\n%{content_type}", url], capture_output=True)
    body, ct = r.stdout.rsplit(b"\n", 1)
    return body, ct.decode().split(";")[0].strip()


def _png_ok(body, min_px):
    w, h = struct.unpack(">II", body[16:24])
    return min(w, h) >= min_px and len(body) <= 24000


def icon_data_uri(url, min_px=96):
    """Inline a logo as a data URI. Flows refuses redirecting hosts and anything under 96px, so a
    favicon-shaped URL falls back to Google's 256px favicon service for the same domain before giving up."""
    body, ct = fetch_bytes(url)
    if body.lstrip()[:4] == b"<svg" or ct.startswith("image/svg"):
        return "data:image/svg+xml;base64," + base64.b64encode(body).decode()
    if body[:8] == b"\x89PNG\r\n\x1a\n" and _png_ok(body, min_px):
        return "data:image/png;base64," + base64.b64encode(body).decode()
    m = re.search(r"url=(https?://[^&\s]+)|https?://([^/\s]+)", url)
    domain = (m.group(1) or ("https://" + m.group(2))) if m else None
    if domain:
        alt = ("https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=%s&size=256" % domain)
        body2, ct2 = fetch_bytes(alt)
        if body2[:8] == b"\x89PNG\r\n\x1a\n" and _png_ok(body2, min_px):
            return "data:image/png;base64," + base64.b64encode(body2).decode()
    raise ValueError("no logo >= %dpx for %s (%s)" % (min_px, url[:60], ct))


GENERIC_ICON = "https://cdn.simpleicons.org/react/61dafb"


def build_flow_payload(arch, title, description):
    g = arch.get("arch_graph") or {}
    nodes, notes = [], []
    for n in g.get("nodes", []):
        try:
            icon = icon_data_uri(n["icon"])
        except Exception as e:
            notes.append("%s: %s" % (n["id"], str(e)[:50]))
            icon = icon_data_uri(GENERIC_ICON)
        nodes.append({"id": n["id"], "label": n["name"][:40], "sub": (n.get("role") or "")[:60],
                      "icon": icon, "note": ("src: " + n.get("src", ""))[:400]})
    edges = [{"source": e["from"], "target": e["to"], "label": (e.get("label") or "")[:60]} for e in g.get("edges", [])]
    if notes:
        log("flow icon fallbacks: " + "; ".join(notes))
    return {"title": title, "is_public": True, "nodes": nodes, "edges": edges,
            "pattern": (arch.get("summary") or "")[:200], "description": description[:600]}


W, H, NOTE = 158, 94, 60


def layout_score(pos, edges):
    import itertools
    B = {k: [x, y, x + W, y + H + NOTE] for k, (x, y) in pos.items()}

    def c(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def hit(p, q, b, pad=2):
        x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
        (ax, ay), (bx, by) = p, q
        if ax == bx:
            return x0 <= ax <= x1 and max(y0, min(ay, by)) <= min(y1, max(ay, by))
        if ay == by:
            return y0 <= ay <= y1 and max(x0, min(ax, bx)) <= min(x1, max(ax, bx))
        return False

    ov = sum(1 for a, b in itertools.combinations(B, 2)
             if B[a][0] < B[b][2] and B[b][0] < B[a][2] and B[a][1] < B[b][3] and B[b][1] < B[a][3])
    hits = []
    for s, t in edges:
        if s not in B or t not in B:
            continue
        sb, tb = B[s], B[t]
        sc, tc = c(sb), c(tb)
        dx, dy = tc[0] - sc[0], tc[1] - sc[1]
        if abs(dx) >= abs(dy):
            p0 = (sb[2] if dx > 0 else sb[0], sc[1])
            p3 = (tb[0] if dx > 0 else tb[2], tc[1])
            mx = (p0[0] + p3[0]) / 2
            pts = [p0, (mx, p0[1]), (mx, p3[1]), p3]
        else:
            p0 = (sc[0], sb[3] if dy > 0 else sb[1])
            p3 = (tc[0], tb[1] if dy > 0 else tb[3])
            my = (p0[1] + p3[1]) / 2
            pts = [p0, (p0[0], my), (p3[0], my), p3]
        for nid, b in B.items():
            if nid not in (s, t) and any(hit(pts[k], pts[k + 1], b) for k in range(3)):
                hits.append((s, t, nid))
    return ov, hits


def unoverlap(pos, edges, rounds=14):
    for _ in range(rounds):
        ov, hits = layout_score(pos, edges)
        if not hits and not ov:
            break
        best = None
        for cand in {hits[0][2], hits[0][0], hits[0][1]} if hits else set(pos):
            for dy in range(-720, 721, 120):
                for dx in range(-600, 601, 200):
                    if dx == 0 and dy == 0:
                        continue
                    trial = {k: list(v) for k, v in pos.items()}
                    trial[cand][0] += dx
                    trial[cand][1] += dy
                    o, h = layout_score(trial, edges)
                    key = (o, len(h), abs(dx) + abs(dy))
                    if best is None or key < best[0]:
                        best = (key, cand, dx, dy)
        if best is None:
            break
        _, cand, dx, dy = best
        pos[cand][0] += dx
        pos[cand][1] += dy
    return pos


def create_flow(payload):
    body = json.dumps(payload)
    script = ("cat > /tmp/ra-flow.json <<'EOF'\n%s\nEOF\n"
              "curl -s -X POST 'https://flows-bheng.vercel.app/api/ai/flows?format=svg' -H \"Authorization: Bearer $SECRET\" "
              "-H 'Content-Type: application/json' --data @/tmp/ra-flow.json\n") % body
    resp = jload_str(run_with_secret("FLOWS_API_SECRET", script)) or {}
    if "url" not in resp:
        raise RuntimeError("flows create failed: %s" % json.dumps(resp)[:300])
    return resp


def flows_diagram(arch, title, description):
    payload = build_flow_payload(arch, title, description)
    if not payload["nodes"]:
        return None
    first = create_flow(payload)
    live = jload_str(sh(["curl", "-s", "--max-time", "20", "https://flows-bheng.vercel.app/api/flows/" + first["id"]])) or {}
    pos = {n["id"]: [n["position"]["x"], n["position"]["y"]] for n in live.get("nodes", [])}
    edges = [(e["source"], e["target"]) for e in live.get("edges", [])]
    ov, hits = layout_score(pos, edges)
    log("flows auto-layout: %d overlaps, %d edges through cards" % (ov, len(hits)))
    if not hits and not ov:
        return {"url": first["url"], "svg_url": first["svg_url"], "svg": first.get("svg", "")}
    pos = unoverlap(pos, edges)
    ov, hits = layout_score(pos, edges)
    log("flows after search: %d overlaps, %d hits -> re-creating with explicit positions (created flows are edit-locked)" % (ov, len(hits)))
    minx = min(v[0] for v in pos.values())
    miny = min(v[1] for v in pos.values())
    for n in payload["nodes"]:
        x, y = pos[n["id"]][0] - minx, pos[n["id"]][1] - miny
        n["position"] = {"x": x, "y": y}
        n["x"], n["y"] = x, y
    second = create_flow(payload)
    return {"url": second["url"], "svg_url": second["svg_url"], "svg": second.get("svg", ""),
            "superseded": first["url"]}


def lane_for(layer, iac):
    l = layer.lower()
    if iac:
        if re.search(r"\b(ci|workflows?|github|pipeline)\b", l):
            return "CI"
        if re.search(r"\b(external|common|shared|remote)\b", l):
            return "Shared"
        if "module" in l:
            return "Modules"
        return "Roots"
    if re.search(r"\b(bootstrap|entry|auth|authentication|gating|root)\b", l):
        return "Entry"
    if re.search(r"\b(views?|components?|styles?|ui|screens?|pages?|assets?|catalog|routing)\b", l):
        return "UI"
    if re.search(r"\b(tests?|stories|quality|ci|workflows?|build|deploy|config|tooling)\b", l):
        return "Tooling"
    return "Data"


def short_label(t, prefixes, n):
    t = re.sub(r"\s+", " ", str(t).strip())
    for p in prefixes:
        t = t.replace(p, "")
    if len(t) <= n:
        return t
    cut = t[:n - 3]
    sep = max(cut.rfind(","), cut.rfind(" "), cut.rfind("/"))
    if sep > n // 2:
        cut = cut[:sep]
    return cut.rstrip(" ,/{") + "..."


def layers_sequence(table, name, iac):
    """Owner rule 2026-09-30: tall not wide - 3-5 lanes, forward-only staircase, notes for same-lane rows."""
    rows = table[1:] if table and table[0] and str(table[0][0]).lower() == "layer" else table
    if not rows:
        return None
    dirs = [str(r[1]) for r in rows]
    prefix = os.path.commonprefix(dirs)
    prefix = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
    prefixes = ([prefix] if prefix else []) + (["terraform/apps/", "terraform/modules/", "environments/",
                                                 "git::https://github.com/"] if iac else [])
    order = ["Roots", "Modules", "Shared", "CI"] if iac else ["Entry", "UI", "Data", "Tooling"]
    rows = sorted(rows, key=lambda r: order.index(lane_for(str(r[0]), iac)))
    lanes = [x for x in order if any(lane_for(str(r[0]), iac) == x for r in rows)]
    lines = ["---", "title: %s - File Layers" % name, "---", "sequenceDiagram", "  autonumber"] + \
            ["  participant %s" % ln for ln in lanes]
    prev = None
    for r in rows:
        ln = lane_for(str(r[0]), iac)
        layer = str(r[0]).replace(":", " -")
        layer = layer if len(layer) <= 26 else layer[:25] + "."
        if prev and ln != prev:
            lines.append("  %s->>%s: %s: %s" % (prev, ln, layer, short_label(r[1], prefixes, 48 - len(layer) - 2)))
        else:
            lines.append("  note over %s: %s: %s" % (ln, layer, short_label(r[1], prefixes, 60 - len(layer) - 2)))
        prev = ln
    code = "\n".join(lines).replace(";", ",") + "\n"
    seq = {"title": "%s - File Layers" % name, "diagramType": "sequence", "code": code, "return": "svg"}
    script = ("cat > /tmp/ra-seq.json <<'EOF'\n%s\nEOF\n"
              "curl -s -X POST https://sequences-bheng.vercel.app/api/ai/sequences -H \"Authorization: Bearer $SECRET\" "
              "-H 'Content-Type: application/json' --data @/tmp/ra-seq.json\n") % json.dumps(seq)
    resp = jload_str(run_with_secret("SEQUENCES_API_SECRET", script)) or {}
    if "url" not in resp:
        raise RuntimeError("sequences create failed: %s" % json.dumps(resp)[:300])
    return {"url": resp["url"], "svg_url": resp["svg_url"], "svg": resp.get("svg", "")}


def features_mindmap(tree, slug):
    if not tree:
        return None

    def conv(n):
        nm = n["name"] + (" - " + n["note"][:70] if n.get("note") else "")
        kids = n.get("children") or []
        return {nm: [conv(k) for k in kids]} if kids else nm

    outline = {"%s - Features" % slug: [conv(n) for n in tree]}
    mm = {"title": "%s Features (repo-audit)" % slug.split("/")[-1], "type": "logic-chart", "userId": MINDMAPS_USER,
          "sharing": True, "outline": json.dumps(outline)}
    script = ("cat > /tmp/ra-mm.json <<'EOF'\n%s\nEOF\n"
              "curl -s -X POST https://mindmaps-bheng.vercel.app/api/ai/mindmaps -H \"Authorization: Bearer $SECRET\" "
              "-H 'Content-Type: application/json' --data @/tmp/ra-mm.json\n") % json.dumps(mm)
    resp = jload_str(run_with_secret("MINDMAPS_API_SECRET", script)) or {}
    if "url" not in resp:
        raise RuntimeError("mindmaps create failed: %s" % json.dumps(resp)[:300])
    svg = sh(["curl", "-s", "--max-time", "30", resp["svg_url"]], timeout=60)
    return {"url": resp["url"], "svg_url": resp["svg_url"], "svg": svg}


def verify_tech_stack(ts):
    """Owner rule: every tech-stack row needs a real logo AND a version, else it is dropped."""
    keep, dropped = [], []
    for t in ts:
        url = t.get("icon") or ("https://cdn.simpleicons.org/%s" % t["slug"] if t.get("slug") else None)
        ok = False
        if url:
            code = sh(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8", url])
            ok = code == "200"
        if ok and t.get("version") and t["version"] != "-":
            keep.append(t)
        else:
            dropped.append(t.get("name"))
    if dropped:
        log("tech_stack rows dropped (no logo or version): " + ", ".join(map(str, dropped)))
    return keep


# ----------------------------------------------------------------------------- finish
def cmd_finish(out, no_post=False, no_diagrams=False, reports_dir=None):
    out = Path(out).expanduser()
    base = jload(out / "base.json")
    scope = jload(out / "scope.json", {})
    if not base:
        sys.exit("finish: %s/base.json missing - run scope first" % out)
    repo = Path(base["path"])
    strip = str(repo) + "/"
    synth = jload(out / "synthesis.json", {}) or {}
    lenses = dict(base.get("lenses", {}))
    for k in LENSES:
        d = jload(out / ("%s.json" % k))
        if d:
            lenses[k] = d
    missing = [k for k in LENSES if k not in lenses]
    if missing:
        log("lenses missing (rendered as absent): " + ", ".join(missing))
    if "gbu" in lenses:
        dedup_gbu(lenses["gbu"], synth.get("gbu_drop", {}))
        for k in ("good", "bad", "ugly", "summary"):
            v = lenses["gbu"].get(k)
            lenses["gbu"][k] = [x.replace(strip, "") for x in v] if isinstance(v, list) else (v or "").replace(strip, "")
    norm_findings(lenses, strip)
    # synthesis corrections: extra findings / grade moves written by the strong model
    for k, extra in (synth.get("extra_findings") or {}).items():
        if k in lenses:
            lenses[k].setdefault("findings", [])
            lenses[k]["findings"] = list(extra) + lenses[k]["findings"]
    for k, g in (synth.get("grade_overrides") or {}).items():
        if k in lenses:
            lenses[k]["grade"] = g
    for k, note in (synth.get("summary_notes") or {}).items():
        if k in lenses:
            lenses[k]["summary"] = (lenses[k].get("summary") or "").rstrip() + " " + note
    norm_findings(lenses, strip)
    # dependency advisories are a fact of the scope, not an opinion - make sure security carries them
    da = scope.get("dep_audit") or {}
    summ = da.get("summary") if isinstance(da.get("summary"), dict) else None
    if summ and (summ.get("high") or summ.get("critical")) and "security" in lenses:
        sec = lenses["security"]
        if not any(re.search(r"advisor|yarn audit|npm audit|CVE|dependency debt", f.get("title", ""), re.I) for f in sec.get("findings", [])):
            sec.setdefault("findings", []).insert(0, {
                "title": "Dependency advisories: %s high, %s critical (%s)" % (summ.get("high", 0), summ.get("critical", 0), da.get("tool")),
                "severity": "high" if summ.get("critical") or summ.get("high", 0) > 10 else "medium", "confidence": "High",
                "file": "package.json:1",
                "consequence": "Advisories in high/critical modules: " + ", ".join((da.get("high_critical_modules") or [])[:12]),
                "evidence": "package.json:1  {\n%s summary: %s" % (da.get("tool"), json.dumps(summ)),
                "fix": "Upgrade the runtime packages first, then gate CI on the audit at level high.", "effort": "M"})
        sec["metrics"] = [m for m in sec.get("metrics", []) if not str(m[0]).lower().startswith("deps")] + \
                         [["Deps high/critical", "%s / %s" % (summ.get("high", 0), summ.get("critical", 0))]]
    arch = lenses.get("architect", {})
    arch.pop("arch_canvas", None)
    arch.pop("stack_flow", None)
    data = dict(base)
    data["lenses"] = lenses
    if synth.get("tech_stack"):
        data["tech_stack"] = verify_tech_stack(synth["tech_stack"])
    data["top_fixes"] = synth.get("top_fixes") or auto_top_fixes(lenses)
    for t in data["top_fixes"]:
        t["severity"] = SEV.get(str(t.get("severity", "high")).lower()[:4], "high")
    data["bottom_line"] = synth.get("bottom_line") or ""
    recon = jload(out / "recon.json")
    if recon:
        data["recon"] = json.loads(json.dumps(recon).replace(strip, ""))
    # evidence gate: repair basename-only fragments, hold non-file findings, prune, re-add
    repair_evidence_paths(lenses, repo)
    held = hold_nonfile(lenses, repo)
    jdump(out / "data.json", data)
    gate = sh(["python3", str(HERE / "verify.py"), str(out / "data.json"), "--repo", str(repo), "--prune"], timeout=300)
    gate_line = [l for l in gate.splitlines() if l.startswith("verify:")]
    log(" | ".join(gate_line) or gate[-300:])
    v = jload(out / "data.verified.json") or data
    for k, fs in held.items():
        v["lenses"][k]["findings"] = fs + v["lenses"][k].get("findings", [])
    # diagrams from the 3 apps - never renderer-drawn
    diag = {}
    if not no_diagrams:
        name = base["repo"].split("/")[-1]
        iac = "Terraform" in (scope.get("stack_hint") or [])
        try:
            fl = flows_diagram(arch, "%s - Architecture (repo-audit)" % base["repo"],
                               "Auto-generated by /repo-audit on %s from %s @ %s. Every node and edge is pinned to a path:line in its note."
                               % (TODAY, base["branch"], base["commit"]))
            if fl:
                v["system_design"] = fl
                diag["flows"] = fl["url"]
        except Exception as e:
            log("flows failed: %s" % str(e)[:200])
        try:
            sq = layers_sequence(arch.get("table") or [], name, iac)
            if sq:
                v["file_layers_sequence"] = sq
                diag["sequences"] = sq["url"]
        except Exception as e:
            log("sequences failed: %s" % str(e)[:200])
        try:
            mm = features_mindmap((lenses.get("features") or {}).get("tree"), base["repo"])
            if mm:
                v["features_mindmap"] = mm
                diag["mindmaps"] = mm["url"]
        except Exception as e:
            log("mindmaps failed: %s" % str(e)[:200])
        v.pop("sequence", None)  # critical-path diagram retired 2026-09-30
    jdump(out / "data.verified.json", v)
    # render + archive + post
    rdir = Path(reports_dir or (CODE / "reports")).expanduser()
    rdir.mkdir(parents=True, exist_ok=True)
    slug_file = re.sub(r"\W+", "-", base["repo"]).strip("-").lower()
    report = rdir / ("repo-audit-%s-%s.html" % (slug_file, TODAY))
    rend = sh(["python3", str(HERE / "render.py"), str(out / "data.verified.json"), "--no-open", "--out", str(report)],
              cwd=str(rdir.parent), timeout=300)
    log(rend.splitlines()[-1] if rend else "render produced no output")
    logs = HOME / ".claude" / "logs" / "repo-audit"
    logs.mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "data.verified.json", logs / ("%s-%s.json" % (base["repo"].split("/")[-1], TODAY)))
    posted = "skipped"
    helper = HOME / ".claude" / "lib" / "stickies.py"
    if not no_post and helper.exists():
        posted = sh("zsh -lc 'python3 %s %s --title %s --folder Audits'" % (helper, report, json.dumps("Repo Audit - " + base["repo"])),
                    timeout=120).splitlines()[-1:] or ["no output"]
        posted = posted[0]
    tot = {}
    for k in GRADED:
        for f in (v["lenses"].get(k) or {}).get("findings", []):
            tot[f["severity"]] = tot.get(f["severity"], 0) + 1
    summary = {"report": str(report), "grades": {k: (v["lenses"].get(k) or {}).get("grade") for k in GRADED if v["lenses"].get(k)},
               "findings": tot, "gate": gate_line, "diagrams": diag, "stickies": posted, "top_fixes": [t["title"] for t in v.get("top_fixes", [])]}
    print(json.dumps(summary))


# ----------------------------------------------------------------------------- main
def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]

    def opt(flag, default=None):
        return rest[rest.index(flag) + 1] if flag in rest else default

    if cmd == "scope":
        cmd_scope(rest[0], opt("--out", "/tmp/repo-audit-run"))
    elif cmd == "finish":
        cmd_finish(rest[0], no_post="--no-post" in rest, no_diagrams="--no-diagrams" in rest, reports_dir=opt("--reports-dir"))
    else:
        sys.exit("unknown command %r (scope | finish)" % cmd)


if __name__ == "__main__":
    main(sys.argv[1:])
