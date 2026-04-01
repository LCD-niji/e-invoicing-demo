import unittest

from xml_import_helpers import decode_uploaded_xml, parse_xml_safely


class TestXmlImportHelpers(unittest.TestCase):
    def test_decode_utf8_sig(self):
        text, encoding = decode_uploaded_xml("\ufeff<root/>".encode("utf-8"))
        self.assertEqual(encoding, "utf-8-sig")
        self.assertIn("<root/>", text)

    def test_decode_latin1_fallback(self):
        raw = "é".encode("latin-1")
        text, encoding = decode_uploaded_xml(raw)
        self.assertEqual(encoding, "latin-1")
        self.assertEqual(text, "é")

    def test_parse_xml_safely_ok(self):
        is_valid, msg = parse_xml_safely("<root><a/></root>")
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")

    def test_parse_xml_safely_malformed(self):
        is_valid, msg = parse_xml_safely("<root><a></root>")
        self.assertFalse(is_valid)
        self.assertIn("mal forme", msg)
