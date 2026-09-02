import unittest

from construction_company_profiles import profile_for, validate_profile


class ConstructionProfileTests(unittest.TestCase):
    def test_attached_profiles_validate(self):
        for ticker in ("AVLL3", "CALI3", "CURY3"):
            profile = profile_for(ticker)
            validate_profile(profile)
            self.assertEqual(profile["ticker"], ticker)

    def test_unknown_company_has_safe_empty_profile(self):
        profile = profile_for("NEW3")
        self.assertEqual(profile["metrics"], {})


if __name__ == "__main__":
    unittest.main()
