"""Guard local plan references and the safety-critical recovery cross-references."""

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "project-plan"
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class ProjectPlanDocsTests(unittest.TestCase):
    def test_local_markdown_links_have_targets(self) -> None:
        checked = 0
        missing = []
        for document in sorted(PLAN.rglob("*.md")):
            for target in LOCAL_LINK.findall(document.read_text(encoding="utf-8")):
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                # Anchors are not checked here; this tests file existence only.
                path = (document.parent / unquote(url.path)).resolve()
                checked += 1
                if not path.is_file() or not path.is_relative_to(ROOT):
                    missing.append(f"{document.relative_to(ROOT)} -> {target}")
        self.assertGreater(checked, 300)
        self.assertEqual(missing, [])

    def test_recovery_spec_references_owner_supersession(self) -> None:
        for name in (
            "MASTER_PLAN.md",
            "LOCKED_REQUIREMENTS.md",
            "roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md",
            "roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md",
            "roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md",
            "database/CONCEPTUAL_SCHEMA_AND_TRANSACTIONS.md",
            "tasks/P00-T02.md",
        ):
            with self.subTest(name=name):
                text = (PLAN / name).read_text(encoding="utf-8")
                self.assertIn("D-06a", text)
                self.assertIn("settle", text.lower())
        matrix = (PLAN / "roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md").read_text()
        self.assertIn("there is no separate exact-split cap", matrix)


if __name__ == "__main__":
    unittest.main()
