"""Pure identifier rules; no accounts are created by these helpers."""

import re
import unittest

from fairmount_api.identity.identifiers import (
    AGENT_ALPHABET,
    canonical_agent_id,
    canonical_player_username,
    generate_agent_id,
)


class IdentifierRuleTests(unittest.TestCase):
    def test_player_canonicalization_and_boundaries(self) -> None:
        self.assertEqual(canonical_player_username("Alice_2"), "alice_2")
        self.assertEqual(canonical_player_username("Ab3"), "ab3")
        self.assertEqual(canonical_player_username("A" + "b" * 31), "a" + "b" * 31)

    def test_player_rejects_invalid_reserved_and_confusable_inputs(self) -> None:
        for value in (
            "ab", "A" + "b" * 32, "2player", "_alice", "a b", "admin", "OWNER",
            "Support", "System", "ROOT", "AGT-hello", "álpha", "Åaa", " aBc", "abc ",
            "abc.def", "bob\n", "straße", None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_player_username(value)

    def test_agent_id_is_generated_and_case_insensitive(self) -> None:
        pattern = re.compile(rf"AGT-[{AGENT_ALPHABET}]{{10}}")
        for _ in range(30):
            value = generate_agent_id()
            self.assertIsNotNone(pattern.fullmatch(value))
            self.assertEqual(canonical_agent_id(value.lower()), value.lower())

    def test_agent_rejects_wrong_size_and_ambiguous_characters(self) -> None:
        for value in (
            "AGT-SHORT", "AGT-AAAAAAAAAAA", "AGT-AAAAAAAAA0", "AGT-AAAAAAAAAI",
            "AGT-AAAAAAAAAO", "AGT-AAAAAAAAA1", "AGT-AAAAAAAAAÅ", "AGT-AAAAAAAAAK",
            "OWNER", "agt_aaaaaaaaaa", None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_agent_id(value)


if __name__ == "__main__":
    unittest.main()
