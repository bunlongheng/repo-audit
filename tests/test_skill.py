"""Contract tests for the deterministic half of the skill: the renderer and the
evidence gate. Standard library only - `python3 -m unittest discover -s tests`."""
import json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LENS_ORDER = ["architect", "infra", "security", "performance", "quality",
              "tests", "docs", "uiux", "features", "gbu"]
ICON = {"architect": "fa-sitemap", "infra": "fa-server", "security": "fa-lock",
        "performance": "fa-gauge-high", "quality": "fa-code", "tests": "fa-flask",
        "docs": "fa-book", "uiux": "fa-palette", "features": "fa-diagram-project",
        "gbu": "fa-scale-balanced"}


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True)


class RenderGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = run("render.py", "golden/sample-data.json", "--no-open")
        m = re.search(r"(reports/\S+\.html)", cls.proc.stdout)
        cls.out = os.path.join(ROOT, m.group(1)) if m else None

    def test_renders_and_reports_one_line(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn("repo-audit: orders-api", self.proc.stdout)
        self.assertTrue(self.out and os.path.isfile(self.out), self.proc.stdout)

    def test_all_ten_lenses_in_report_order_with_gbu_last(self):
        with open(self.out, encoding="utf-8") as fh:
            html = fh.read()
        positions = [html.find(ICON[k]) for k in LENS_ORDER]
        self.assertTrue(all(p > 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions), "lens sections are out of order")

    def test_report_is_self_contained(self):
        with open(self.out, encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("None</", html)
        self.assertNotIn("/Users/", html)  # publish-scan: allow
        self.assertGreater(len(html), 50_000)


class HostileInput(unittest.TestCase):
    """The data JSON is written by an agent that has just read an untrusted repo.
    Nothing from it may reach the report as markup."""

    def test_no_injection_survives_into_the_report(self):
        evil = {
            "repo": "evil", "repo_url": "javascript:alert('HREF')", "path": ROOT,
            "scanned": {"files": 1, "loc": 1},
            "lens_icons": {"security": "fa-lock\" onmouseover=\"alert('ICON')\" x=\""},
            "lens_labels": {"security": "</script><img src=x onerror=alert('LABEL')>"},
            "lenses": {"security": {"grade": "B", "summary": "<script>alert('S')</script>", "findings": [
                {"title": "<img src=x onerror=alert(1)>", "severity": "high", "confidence": "High",
                 "file": "render.py:1", "consequence": "c", "evidence": "e", "fix": "f", "effort": "S"}]}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(evil, fh)
            src = fh.name
        out = os.path.join(tempfile.mkdtemp(), "evil.html")
        proc = run("render.py", src, "--no-open", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("</script><img", html)
        self.assertNotIn("<img src=x onerror", html)
        self.assertNotIn("<script>alert(", html)
        self.assertIsNone(re.search(r'<[^>]+\son(?:mouseover|error|load)=', html),
                          "an event handler reached the rendered page")


class CliContract(unittest.TestCase):
    def test_unknown_flag_is_refused_not_ignored(self):
        proc = run("render.py", "golden/sample-data.json", "--no-opne")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown option", proc.stdout + proc.stderr)

    def test_malformed_json_gets_a_readable_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("not json")
            src = fh.name
        proc = run("render.py", src)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not valid JSON", proc.stdout + proc.stderr)


class EvidenceGate(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.repo, "lib"))
        with open(os.path.join(self.repo, "lib", "db.js"), "w") as fh:
            fh.write("\n".join(f"line {i}" for i in range(1, 30)) + "\n")
            fh.write('const ssl = { rejectUnauthorized: false };\n')

    def gate(self, findings, *flags):
        data = {"repo": "x", "path": self.repo, "lenses": {"security": {"grade": "B", "summary": "", "findings": findings}}}
        src = os.path.join(self.repo, "data.json")
        with open(src, "w") as fh:
            json.dump(data, fh)
        return run("verify.py", src, *flags), src

    def test_pass_near_warn_fail(self):
        f = lambda file, ev: {"title": "t", "severity": "low", "confidence": "High", "file": file,
                              "consequence": "", "evidence": ev, "fix": "", "effort": "S"}
        proc, _ = self.gate([
            f("lib/db.js:30", "lib/db.js:30  `const ssl = { rejectUnauthorized: false };`"),   # PASS
            f("lib/db.js:2", "lib/db.js:2  rejectUnauthorized: false"),                          # NEAR
            f("lib/db.js:5", "lib/db.js:5  this text is not in the file anywhere"),               # WARN
            f("lib/nope.js:1", "lib/nope.js:1  whatever"),                                         # FAIL
        ])
        self.assertIn("1 pass, 1 near, 1 warn, 1 fail", proc.stdout)
        self.assertEqual(proc.returncode, 1, "a FAIL must exit non-zero")

    # The branch nearly every finding takes when an agent writes prose evidence.
    # It used to return PASS with no check at all.
    def test_evidence_that_quotes_nothing_is_unverified_not_passed(self):
        f = {"title": "prose", "severity": "low", "confidence": "High", "file": "lib/db.js:5",
             "consequence": "", "evidence": "I read the file and it looked wrong", "fix": "", "effort": "S"}
        proc, _ = self.gate([f])
        self.assertIn("0 pass, 0 near, 1 warn, 0 fail", proc.stdout)

    # Confinement: without it the gate validates against files outside the target,
    # which both defeats it and leaks whether a string exists on the user's disk.
    def test_paths_outside_the_repo_fail(self):
        f = lambda file: {"title": "escape", "severity": "low", "confidence": "High", "file": file,
                          "consequence": "", "evidence": f"{file}  localhost", "fix": "", "effort": "S"}
        proc, _ = self.gate([f("../../../../../../etc/hosts:1"), f("/etc/hosts:1")])
        self.assertIn("0 pass, 0 near, 0 warn, 2 fail", proc.stdout)
        self.assertEqual(proc.returncode, 1)

    def test_prune_drops_fail_downgrades_warn_and_exits_zero(self):
        f = lambda file, ev: {"title": "t", "severity": "low", "confidence": "High", "file": file,
                              "consequence": "", "evidence": ev, "fix": "", "effort": "S"}
        proc, src = self.gate([f("lib/nope.js:1", "x"), f("lib/db.js:5", "lib/db.js:5  not present")], "--prune")
        self.assertEqual(proc.returncode, 0, "--prune IS the fix, so the pipeline must continue")
        with open(src.replace(".json", ".verified.json")) as fh:
            out = json.load(fh)
        kept = out["lenses"]["security"]["findings"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["confidence"], "Low")
        self.assertIn("[verify:", kept[0]["evidence"])

    def test_a_bad_top_fixes_citation_is_pruned_too(self):
        data = {"repo": "x", "path": self.repo,
                "lenses": {"security": {"grade": "B", "summary": "", "findings": []}},
                "top_fixes": [{"title": "gone", "lens": "security", "severity": "low",
                               "file": "nope/gone.py:9", "why": "w", "fix": "f", "effort": "S"},
                              {"title": "fine", "lens": "security", "severity": "low",
                               "why": "w", "fix": "f", "effort": "S"}]}
        src = os.path.join(self.repo, "tf.json")
        with open(src, "w") as fh:
            json.dump(data, fh)
        run("verify.py", src, "--prune")
        with open(src.replace(".json", ".verified.json")) as fh:
            out = json.load(fh)
        self.assertEqual([f["title"] for f in out["top_fixes"]], ["fine"])


if __name__ == "__main__":
    unittest.main()
