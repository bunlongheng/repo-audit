"""1 Flows diagram per repo per run (owner rule 2026-09-30). The old path created a flow, read
the app's auto-layout back, and on any overlap created a second flow, so every audit left a
pair behind and repeated audits piled up. Standard library only."""
import importlib.util, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("orchestrate", os.path.join(ROOT, "orchestrate.py"))
orch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orch)


class SeedPositions(unittest.TestCase):
    def test_layered_left_to_right_without_overlap(self):
        ids = ["ui", "api", "db", "cache", "ci"]
        edges = [("ui", "api"), ("api", "db"), ("api", "cache"), ("ci", "ui")]
        pos = orch.seed_positions(ids, edges)
        self.assertEqual(set(pos), set(ids))
        self.assertLess(pos["ci"][0], pos["ui"][0])
        self.assertLess(pos["ui"][0], pos["api"][0])
        self.assertLess(pos["api"][0], pos["db"][0])
        self.assertEqual(pos["db"][0], pos["cache"][0])
        self.assertNotEqual(pos["db"][1], pos["cache"][1])
        ov, hits = orch.layout_score(pos, edges)
        self.assertEqual((ov, len(hits)), (0, 0))

    def test_cycles_and_unknown_endpoints_do_not_crash(self):
        pos = orch.seed_positions(["a", "b"], [("a", "b"), ("b", "a"), ("a", "ghost")])
        self.assertEqual(set(pos), {"a", "b"})


class OneCreatePerRun(unittest.TestCase):
    def test_flows_diagram_creates_exactly_once_and_retires_older_copies(self):
        calls = {"create": [], "retire": []}
        orch.build_flow_payload = lambda arch, title, description: {
            "title": title, "is_public": True,
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}

        def fake_create(payload):
            calls["create"].append(payload)
            return {"id": "new-id", "url": "u", "svg_url": "s", "svg": "<svg/>"}

        orch.create_flow = fake_create
        orch.retire_previous_flows = lambda title, keep: calls["retire"].append((title, keep)) or 2
        orch.log = lambda m: None
        out = orch.flows_diagram({}, "repo - Architecture (repo-audit)", "desc")
        self.assertEqual(len(calls["create"]), 1)
        self.assertEqual(calls["retire"], [("repo - Architecture (repo-audit)", "new-id")])
        self.assertNotIn("superseded", out)
        for n in calls["create"][0]["nodes"]:
            self.assertIn("position", n)
            self.assertEqual((n["x"], n["y"]), (n["position"]["x"], n["position"]["y"]))


if __name__ == "__main__":
    unittest.main()
