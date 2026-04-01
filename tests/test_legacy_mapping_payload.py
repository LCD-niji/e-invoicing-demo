import unittest

try:
    from convert_legacy import extract_from_xml, make_sample_legacy_xml
    HAS_LEGACY_DEPS = True
except ModuleNotFoundError:
    HAS_LEGACY_DEPS = False


class TestLegacyMappingPayload(unittest.TestCase):
    @unittest.skipUnless(HAS_LEGACY_DEPS, "convert_legacy dependencies not available in test env")
    def test_extraction_exposes_mapped_and_unmapped(self):
        xml = make_sample_legacy_xml()
        result = extract_from_xml(xml)
        self.assertTrue(len(result.matched_fields) > 0)
        self.assertIsInstance(result.unmatched_tags, set)

    @unittest.skipUnless(HAS_LEGACY_DEPS, "convert_legacy dependencies not available in test env")
    def test_normalized_payload_available(self):
        xml = make_sample_legacy_xml()
        result = extract_from_xml(xml)
        payload = result.normalized_payload
        self.assertIn("BT-1", payload)
        self.assertIn("BT-2", payload)
