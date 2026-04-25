import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "ev" / "percentile calc v1.py"

try:
    from shared.models import EVDistribution
except ModuleNotFoundError:
    EVDistribution = None


def load_percentile_module():
    spec = importlib.util.spec_from_file_location("ev_percentile_calc_v1", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_row():
    return {
        "live_listing": {
            "id": "live-1",
            "name": "788Z Back Zip Boots",
            "designer": "Guidi",
            "size": "43",
            "condition_raw": "Gently Used",
            "price": {
                "listing_price_usd": 850,
                "shipping_price_usd": 20,
            },
        },
        "sold_comparables": [
            {
                "designer": "Guidi",
                "size": "43",
                "condition_raw": "Used",
                "sold_at_unix": 1711500000,
                "price": {
                    "sold_price_usd": 720,
                    "shipping_price_usd": 45,
                },
                "seller": {
                    "reviews_count": 89,
                    "transactions_count": 94,
                    "badges": {
                        "verified": True,
                        "trusted_seller": False,
                    },
                },
            },
            {
                "designer": "Guidi",
                "size": "44",
                "condition_raw": "Gently Used",
                "sold_at_unix": 1712000000,
                "price": {
                    "sold_price_usd": 810,
                    "shipping_price_usd": 35,
                },
                "seller": {
                    "reviews_count": 50,
                    "transactions_count": 60,
                    "badges": {
                        "verified": False,
                        "trusted_seller": True,
                    },
                },
            },
        ],
    }


class EVPercentileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_percentile_module()

    def test_value_listing_uses_shared_distribution_keys(self):
        result = self.module.value_listing(make_row(), scraped_at=1713995645)

        self.assertEqual(set(result["dist"].keys()), {"q10", "q50", "q90"})

    def test_value_listing_does_not_emit_legacy_distribution_keys(self):
        result = self.module.value_listing(make_row(), scraped_at=1713995645)

        self.assertNotIn("p10_floor", result["dist"])
        self.assertNotIn("p50_fair", result["dist"])
        self.assertNotIn("p90_max", result["dist"])

    @unittest.skipIf(EVDistribution is None, "pydantic is not installed in the local test environment")
    def test_distribution_validates_against_shared_model_without_translation(self):
        result = self.module.value_listing(make_row(), scraped_at=1713995645)

        dist = EVDistribution(**result["dist"])

        self.assertEqual(dist.q10, result["dist"]["q10"])
        self.assertEqual(dist.q50, result["dist"]["q50"])
        self.assertEqual(dist.q90, result["dist"]["q90"])

    def test_percentile_values_are_unchanged_by_contract_rename(self):
        row = make_row()
        scraped_at = 1713995645
        expected_q10 = round(
            self.module.weighted_percentile(
                [765, 845],
                [
                    self.module.get_condition_weight("Gently Used", "Used")
                    * self.module.get_size_weight("43", "43")
                    * self.module.get_recency_weight(1711500000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 89,
                            "transactions_count": 94,
                            "badges": {
                                "verified": True,
                                "trusted_seller": False,
                            },
                        }
                    ),
                    self.module.get_condition_weight("Gently Used", "Gently Used")
                    * self.module.get_size_weight("43", "44")
                    * self.module.get_recency_weight(1712000000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 50,
                            "transactions_count": 60,
                            "badges": {
                                "verified": False,
                                "trusted_seller": True,
                            },
                        }
                    ),
                ],
                10,
            ),
            2,
        )
        expected_q50 = round(
            self.module.weighted_percentile(
                [765, 845],
                [
                    self.module.get_condition_weight("Gently Used", "Used")
                    * self.module.get_size_weight("43", "43")
                    * self.module.get_recency_weight(1711500000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 89,
                            "transactions_count": 94,
                            "badges": {
                                "verified": True,
                                "trusted_seller": False,
                            },
                        }
                    ),
                    self.module.get_condition_weight("Gently Used", "Gently Used")
                    * self.module.get_size_weight("43", "44")
                    * self.module.get_recency_weight(1712000000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 50,
                            "transactions_count": 60,
                            "badges": {
                                "verified": False,
                                "trusted_seller": True,
                            },
                        }
                    ),
                ],
                50,
            ),
            2,
        )
        expected_q90 = round(
            self.module.weighted_percentile(
                [765, 845],
                [
                    self.module.get_condition_weight("Gently Used", "Used")
                    * self.module.get_size_weight("43", "43")
                    * self.module.get_recency_weight(1711500000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 89,
                            "transactions_count": 94,
                            "badges": {
                                "verified": True,
                                "trusted_seller": False,
                            },
                        }
                    ),
                    self.module.get_condition_weight("Gently Used", "Gently Used")
                    * self.module.get_size_weight("43", "44")
                    * self.module.get_recency_weight(1712000000, scraped_at)
                    * self.module.get_seller_score(
                        {
                            "reviews_count": 50,
                            "transactions_count": 60,
                            "badges": {
                                "verified": False,
                                "trusted_seller": True,
                            },
                        }
                    ),
                ],
                90,
            ),
            2,
        )

        result = self.module.value_listing(row, scraped_at=scraped_at)

        self.assertEqual(result["dist"]["q10"], expected_q10)
        self.assertEqual(result["dist"]["q50"], expected_q50)
        self.assertEqual(result["dist"]["q90"], expected_q90)


if __name__ == "__main__":
    unittest.main()
