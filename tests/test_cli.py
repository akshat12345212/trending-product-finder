import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trendfinder.cli import export_report


class ExportTests(unittest.TestCase):
    def test_empty_evidence_cannot_become_qualified_and_html_is_escaped(self):
        dataset = {"candidates": [{"id": "x", "name": "<script>alert(1)</script>"}], "videos": [],
                   "collection": {"mode": "public", "events": [{"status": "blocked", "reason": "no access"}]}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = export_report(dataset, output)
            self.assertEqual(result["international"], [])
            self.assertEqual(result["india"], [])
            self.assertEqual(json.loads((output / "dataset.json").read_text()), dataset)
            rendered = (output / "report.html").read_text()
            self.assertNotIn("<script>alert(1)</script>", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn("no access", rendered)
            self.assertTrue((output / "video-evidence.csv").read_text().startswith("product_id,"))


if __name__ == "__main__":
    unittest.main()
