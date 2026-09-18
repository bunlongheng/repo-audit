#!/usr/bin/env python3
"""
verify.py - the evidence gate. Deterministic, zero tokens.

Every finding claims a `path:line` and quotes evidence. A model can invent both and
the result still reads as plausible, so nothing is trusted: each citation is checked
against the real repo BEFORE anything is rendered.

  PASS   the file exists inside the repo, the line is in range, and a quoted evidence
         fragment was found within 20 lines of the cited line
  NEAR   the fragment is in the file but not near the cited line (the claim is real,
         the line number drifted)
  WARN   nothing could be confirmed - either the fragment is not in the file at all,
         or the evidence quotes no code, so there is nothing to check. WARN is not a
         pass: it means UNVERIFIED, and --prune downgrades it to Low confidence.
  FAIL   the cited file does not exist, is outside the repo, or the line is past EOF

For a fragment to be checkable, an evidence line must start with `path:line` and be
followed by the real snippet:

    lib/db.js:14  const ssl = { rejectUnauthorized: false }

Prose evidence with no such line can never be verified mechanically, which is why it
lands in WARN rather than passing silently.

Usage:
  python3 verify.py <data.json> [--repo <path>] [--prune] [--strict] [--quiet]

  --repo    repo root; defaults to data["path"]
  --prune   write <data>.verified.json: FAIL findings removed, WARN/NEAR findings
            downgraded to confidence "Low" with a note appended to their evidence,
            and any top_fixes entry whose citation FAILs dropped. Exits 0 on success,
            so it can sit between the audit and the renderer in a script.
  --strict  without --prune, exit 1 on WARN as well as FAIL
  --quiet   only print the summary line
"""
import json, os, re, sys

CITE = re.compile(r'(?P<path>[\w@.+-][\w@./+-]*\.[A-Za-z0-9]+):(?P<l1>\d+)(?:-(?P<l2>\d+))?')
WINDOW = 20      # lines either side of the cited line a fragment may sit in
MIN_FRAG = 8     # shorter snippets match by accident
ORDER = ['FAIL', 'WARN', 'NEAR', 'PASS']


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def clean(code):
    # agents wrap snippets in backticks or quotes; the file does not
    return norm(code).strip('`\'" ')


class Repo:
    """Reads files from one repo root, and never from outside it.

    os.path.join silently discards the root when the second argument is absolute,
    and nothing stops `../../`, so a citation could otherwise be 'verified' against
    any file on the machine - which both defeats the gate and turns its PASS/WARN
    output into a content oracle over the user's filesystem.
    """

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self._cache = {}

    def resolve(self, path):
        if not path or os.path.isabs(path) or path.startswith('~'):
            return None
        full = os.path.realpath(os.path.join(self.root, path))
        if full != self.root and not full.startswith(self.root + os.sep):
            return None
        return full if os.path.isfile(full) else None

    def read(self, path):
        """-> (lines, one normalised string) for a path inside the repo, else None."""
        if path in self._cache:
            return self._cache[path]
        full = self.resolve(path)
        if not full:
            self._cache[path] = None
            return None
        with open(full, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
        self._cache[path] = (lines, norm(' '.join(lines)))
        return self._cache[path]


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
    if os.path.isabs(path) or '..' in path.split('/'):
        return 'FAIL', f'{path} points outside the repo'
    got = repo.read(path)
    if not got:
        return 'FAIL', f'{path} does not exist in the repo'
    lines, _ = got
    l1 = int(m.group('l1')) if m else 0
    if l1 > len(lines):
        return 'FAIL', f'{path} has {len(lines)} lines, cited :{l1}'

    frags = list(fragments(evidence))
    if not frags:
        return 'WARN', 'evidence quotes no code, so nothing could be checked'
    best, seen_any = 'WARN', False
    for fpath, f1, f2, code in frags:
        fgot = repo.read(fpath)
        if not fgot:
            continue
        flines, whole = fgot
        seen_any = True
        lo, hi = max(0, f1 - 1 - WINDOW), min(len(flines), f2 + WINDOW)
        if code in norm(' '.join(flines[lo:hi])):
            return 'PASS', f'fragment found near {fpath}:{f1}'
        if code in whole:
            best = 'NEAR'
    if not seen_any:
        return 'FAIL', 'every quoted fragment cites a file outside the repo'
    return best, ('fragment found in the file but not near the cited line' if best == 'NEAR'
                  else 'quoted fragment is not in the cited file')


NOTE = {
    'WARN': '[verify: UNVERIFIED - no quoted fragment could be confirmed in the cited file]',
    'NEAR': '[verify: the quoted fragment is in the file but not at the cited line]',
}


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith('-'):
        print(__doc__)
        sys.exit(2)
    src = args[0]
    flags = set(a for a in args if a.startswith('--'))
    prune, strict, quiet = '--prune' in flags, '--strict' in flags, '--quiet' in flags
    try:
        with open(src, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print(f'verify: cannot read {src}: {e}', file=sys.stderr)
        sys.exit(2)

    root = args[args.index('--repo') + 1] if '--repo' in args else data.get('path')
    if not root or not os.path.isdir(root):
        print(f'verify: repo path not found: {root!r} (pass --repo)', file=sys.stderr)
        sys.exit(2)
    repo = Repo(root)

    counts = {k: 0 for k in ORDER}
    rows = []
    for lens, body in (data.get('lenses') or {}).items():
        if not isinstance(body, dict) or 'findings' not in body:
            continue
        keep = []
        for f in body.get('findings') or []:
            verdict, why = check(repo, f.get('file'), f.get('evidence'))
            counts[verdict] += 1
            rows.append((verdict, lens, f.get('file') or '-', str(f.get('title', ''))[:60], why))
            if prune and verdict == 'FAIL':
                continue
            if prune and verdict in NOTE:
                f['confidence'] = 'Low'
                f['evidence'] = f'{f.get("evidence") or ""}\n{NOTE[verdict]}'.strip()
            keep.append(f)
        body['findings'] = keep

    fixes = []
    for f in data.get('top_fixes') or []:
        if not f.get('file'):
            fixes.append(f)
            continue
        verdict, why = check(repo, f['file'], f.get('evidence') or '')
        if verdict == 'FAIL':
            counts['FAIL'] += 1
            rows.append(('FAIL', 'top_fixes', f['file'], str(f.get('title', ''))[:60], why))
            if prune:
                continue
        fixes.append(f)
    if prune and 'top_fixes' in data:
        data['top_fixes'] = fixes

    if not quiet:
        for verdict, lens, cite, title, why in sorted(rows, key=lambda r: ORDER.index(r[0])):
            print(f'{verdict:4}  {lens:12} {cite:48} {title}')
            if verdict != 'PASS':
                print(f'      {why}')
    total = sum(counts.values())
    print(f"\nverify: {total} citations - {counts['PASS']} pass, {counts['NEAR']} near, "
          f"{counts['WARN']} warn, {counts['FAIL']} fail  (repo: {repo.root})")

    if prune:
        out = re.sub(r'\.json$', '', src) + '.verified.json'
        with open(out, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        print(f"verify: wrote {out} ({counts['FAIL']} dropped, "
              f"{counts['NEAR'] + counts['WARN']} downgraded to Low)")
        sys.exit(0)  # pruning IS the fix - the pipeline continues
    sys.exit(1 if counts['FAIL'] or (strict and counts['WARN']) else 0)


if __name__ == '__main__':
    main()
