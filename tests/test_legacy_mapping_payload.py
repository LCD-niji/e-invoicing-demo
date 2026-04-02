import json
import re
import unittest

try:
    from convert_legacy import extract_from_xml, get_active_bt_list, make_sample_legacy_xml
    from legacy_mapping_dnd import build_legacy_dnd_html, group_legacy_bt_entries
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

    @unittest.skipUnless(HAS_LEGACY_DEPS, "convert_legacy dependencies not available in test env")
    def test_dnd_html_json_embed_parses_with_special_chars(self):
        """html.escape sur le JSON cassait JSON.parse (&quot;) — tuiles vides dans l'iframe."""
        uf = {
            "tag&amp": 'valeur avec "guillemets" & <br/>',
            "simple": "ok",
        }
        html = build_legacy_dnd_html(uf, group_legacy_bt_entries(get_active_bt_list()))
        self.assertNotIn("&quot;", html)
        m = re.search(
            r'<script type="application/json" id="legacy-dnd-sources">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        sources = json.loads(m.group(1))
        self.assertEqual(len(sources), 2)
        by_tag = {s["tag"]: s["value"] for s in sources}
        self.assertEqual(by_tag["simple"], "ok")
        self.assertIn("&", by_tag["tag&amp"])
