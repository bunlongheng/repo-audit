#!/usr/bin/env python3
"""
verify.py - the evidence gate. Deterministic, zero tokens.

Every finding claims a `path:line` and quotes evidence. A model can invent both and
the result still reads as plausible. This script checks every citation against the
real repo BEFORE anything is rendered:

  PASS   file exists, line in range, and a quoted evidence fragment sits within 20
         lines of the cited line
  NEAR   file exists but the quoted fragment lives elsewhere in the file (a stale
         line number - the claim is real, the pin drifted)
  WARN   file exists but no quoted fragment could be found in it at all
  FAIL   the cited file does not exist, or the line is past the end of the file

Usage:
  python3 verify.py <data.json> [--repo <path>] [--prune] [--strict]

  --repo    repo root; defaults to data["path"]
  --prune   write <data>.verified.json with FAIL findings removed and WARN findings
            downgraded to confidence "Low" (with a note in `evidence`), so the
            renderer never ships an unverifiable claim as fact
  --strict  exit 1 on WARN too (default: exit 1 only on FAIL)
"""
import json, os, re, sys

CITE = re.compile(r'(?P<path>[\w@./+-]+\.[A-Za-z0-9]+):(?P<l1>\d+)(?:-(?P<l2>\d+))?')
WINDOW = 20
MIN_FRAG = 8


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def clean(code):
    # agents wrap snippets in backticks or quotes; the file does not
    return norm(code).strip('`\'" ')


def fragments(evidence):
    """Yield (path, l1, l2, code) for every quoted snippet in the evidence.

    Two shapes are accepted: `path:12  <code>` on one line, and a bare `path:12-19`
    header followed by the snippet on the next line(s) until the next header."""
    cur = None
    for raw in (evidence or '').splitlines():
        line = raw.strip()
        m = CITE.match(line)
        if m:
            cur = (m.group('path'), int(m.group('l1')), int(m.group('l2') or m.group('l1')))
            code = clean(line[m.end():])
            if len(code) >= MIN_FRAG:
                yield (*cur, code)
            continue
        code = clean(line)
        if cur and len(code) >= MIN_FRAG and code != '...':
            yield (*cur, code)


def check(repo, cite, evidence):
    m = CITE.match(cite or '')
    path = m.group('path') if m else (cite or '').split(':')[0]
    if not path:
        return 'WARN', 'no file cited'
    full = os.path.join(repo, path)
    if not os.path.isfile(full):
        return 'FAIL', f'{path} does not exist'
    lines = open(full, encoding='utf-8', errors='replace').read().splitlines()
    l1 = int(m.group('l1')) if m else 0
    if l1 > len(lines):
        return 'FAIL', f'{path} has {len(lines)} lines, cited :{l1}'
    frags = list(fragments(evidence))
    if not frags:
        return 'PASS', 'file + line ok, no quoted fragment to match'
    best = 'WARN'
    for fpath, f1, f2, code in frags:
        ffull = os.path.join(repo, fpath)
        if not os.path.isfile(ffull):
            continue
        flines = open(ffull, encoding='utf-8', errors='replace').read().splitlines()
        lo, hi = max(0, f1 - 1 - WINDOW), min(len(flines), f2 + WINDOW)
        if code in norm(' '.join(flines[lo:hi])):
            return 'PASS', f'fragment found near {fpath}:{f1}'
        if code in norm(' '.join(flines)):
            best = 'NEAR'
    return best, ('fragment found in file but not near the cited line' if best == 'NEAR'
                  else 'no quoted fragment found in the cited file')


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('-'):
        print(__doc__); sys.exit(2)
    src = sys.argv[1]
    data = json.load(open(src))
    repo = sys.argv[sys.argv.index('--repo') + 1] if '--repo' in sys.argv else data.get('path')
    if not repo or not os.path.isdir(repo):
        print(f'verify: repo path not found: {repo!r} (pass --repo)'); sys.exit(2)
    prune, strict = '--prune' in sys.argv, '--strict' in sys.argv

    counts = {'PASS': 0, 'NEAR': 0, 'WARN': 0, 'FAIL': 0}
    rows = []
    for lens, body in (data.get('lenses') or {}).items():
        keep = []
        for f in (body.get('findings') or []) if isinstance(body, dict) else []:
            verdict, why = check(repo, f.get('file'), f.get('evidence'))
            counts[verdict] += 1
            rows.append((verdict, lens, f.get('file') or '-', f.get('title', '')[:60], why))
            if verdict == 'FAIL' and prune:
                continue
            if verdict == 'WARN' and prune:
                f['confidence'] = 'Low'
                f['evidence'] = (f.get('evidence') or '') + '\n[verify: no quoted fragment found in the cited file]'
            keep.append(f)
        if isinstance(body, dict) and 'findings' in body:
            body['findings'] = keep
    for f in data.get('top_fixes') or []:
        if f.get('file'):
            verdict, why = check(repo, f['file'], '')
            if verdict == 'FAIL':
                counts['FAIL'] += 1
                rows.append(('FAIL', 'top_fixes', f['file'], f.get('title', '')[:60], why))

    for r in sorted(rows, key=lambda r: ['FAIL', 'WARN', 'NEAR', 'PASS'].index(r[0])):
        print(f'{r[0]:4}  {r[1]:12} {r[2]:48} {r[3]}\n      {r[4]}' if r[0] != 'PASS'
              else f'{r[0]:4}  {r[1]:12} {r[2]:48} {r[3]}')
    total = sum(counts.values())
    print(f"\nverify: {total} citations - {counts['PASS']} pass, {counts['NEAR']} near, "
          f"{counts['WARN']} warn, {counts['FAIL']} fail  (repo: {repo})")
    if prune:
        out = re.sub(r'\.json$', '', src) + '.verified.json'
        json.dump(data, open(out, 'w'), indent=2)
        print(f'verify: wrote {out} ({counts["FAIL"]} dropped, {counts["WARN"]} downgraded to Low)')
    sys.exit(1 if counts['FAIL'] or (strict and counts['WARN']) else 0)


if __name__ == '__main__':
    main()
