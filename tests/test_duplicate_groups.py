"""Regression checks for mixed purpose and calculated duplicate groups."""

import unittest

from bpfw.core.catalog.duplicate_profile import (
    CodeUnitKey, DuplicateProfile, DuplicateProfileKeys, InterfaceProfile,
    OutcomeProfile, StructureProfile, enrich_duplicate_profile_groups,
)


class DuplicateGroupTests(unittest.TestCase):
    def make_case(self, strength="strong"):
        blocks = [
            {"status": "active", "purpose": purpose,
             "code": {"path": "sample.py", "symbol": symbol, "kind": "function"}}
            for symbol, purpose in (
                ("first", "Shared purpose"), ("second", "Shared purpose"),
                ("third", "Different purpose"), ("fourth", "Another purpose"),
            )
        ]
        profiles = {
            CodeUnitKey(**block["code"]): DuplicateProfile(
                version=2, confidence="high", structure=StructureProfile(),
                outcome=OutcomeProfile(), interface=InterfaceProfile(),
                keys=DuplicateProfileKeys(
                    duplicate_key="shared", duplicate_hash="shared-hash", hash_strength=strength,
                ),
            ) for block in blocks
        }
        return blocks, profiles

    def test_mixed_groups_preserve_strong_and_weak_statuses(self):
        for strength, expected in (("strong", "yes"), ("weak", "check")):
            with self.subTest(strength=strength):
                blocks, profiles = self.make_case(strength)
                original_profiles = dict(profiles)
                enriched = enrich_duplicate_profile_groups(blocks, profiles)
                self.assertEqual(profiles, original_profiles)
                for block in blocks[:2]:
                    keys = enriched[CodeUnitKey(**block["code"])].keys
                    self.assertEqual((keys.duplicated, keys.group_size), ("yes", 2))
                for block in blocks[2:]:
                    keys = enriched[CodeUnitKey(**block["code"])].keys
                    self.assertEqual((keys.duplicated, keys.group_size), (expected, 4))

    def test_explicit_hash_allowance_still_applies(self):
        blocks, profiles = self.make_case()
        blocks[2]["duplicate_policy"] = {"allowed_duplicate_hashes": [
            {"duplicate_hash": "shared-hash", "reason": "Intentional shared implementation"},
        ]}
        enriched = enrich_duplicate_profile_groups(blocks, profiles)
        for block in blocks[2:]:
            keys = enriched[CodeUnitKey(**block["code"])].keys
            self.assertEqual((keys.duplicated, keys.reason), ("no", "allowed duplicate profile"))

    def test_empty_input_preserves_profiles(self):
        _, profiles = self.make_case()
        self.assertEqual(enrich_duplicate_profile_groups([], profiles), profiles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
