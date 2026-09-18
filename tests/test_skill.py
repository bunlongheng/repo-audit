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

    def test_prune_drops_fail_and_downgrades_warn(self):
        f = lambda file, ev: {"title": "t", "severity": "low", "confidence": "High", "file": file,
                              "consequence": "", "evidence": ev, "fix": "", "effort": "S"}
        proc, src = self.gate([f("lib/nope.js:1", "x"), f("lib/db.js:5", "lib/db.js:5  not present")], "--prune")
        with open(src.replace(".json", ".verified.json")) as fh:
            out = json.load(fh)
        kept = out["lenses"]["security"]["findings"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["confidence"], "Low")
        self.assertIn("[verify:", kept[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
