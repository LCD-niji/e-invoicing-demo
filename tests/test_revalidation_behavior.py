import unittest


def summarize_revalidation(previous_blocking, current_blocking):
    if previous_blocking is None:
        return "first-run"
    if current_blocking < previous_blocking:
        return "improved"
    if current_blocking > previous_blocking:
        return "degraded"
    return "stable"


class TestRevalidationBehavior(unittest.TestCase):
    def test_first_run(self):
        self.assertEqual(summarize_revalidation(None, 2), "first-run")

    def test_improved(self):
        self.assertEqual(summarize_revalidation(3, 1), "improved")

    def test_degraded(self):
        self.assertEqual(summarize_revalidation(1, 3), "degraded")

    def test_stable(self):
        self.assertEqual(summarize_revalidation(2, 2), "stable")
