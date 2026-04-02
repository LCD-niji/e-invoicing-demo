"""
tests/test_invoice.py
----------------------
Tests unitaires pour le pipeline de facturation électronique.

Lancement :
    pytest tests/ -v
    pytest tests/ -v --tb=short
"""

import sys
import tempfile
import unittest
from decimal import Decimal
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_invoice import (
    Address, Invoice, InvoiceLine, Party,
    generate_facturx_xml, make_demo_invoice, PROFILES
)
from validate_invoice import InvoiceValidator


# ─────────────────────────────────────────────
# Fixtures communes
# ─────────────────────────────────────────────

def make_seller():
    return Party(
        name="Acme SAS",
        siret="123456789",
        vat_number="FR12345678901",
        address=Address("1 rue Test", "Paris", "75001"),
        iban="FR7630006000011234567890189",
    )

def make_buyer():
    return Party(
        name="Client SARL",
        siret="987654321",
        vat_number="FR98765432109",
        address=Address("2 av Test", "Lyon", "69001"),
    )

def make_lines():
    return [
        InvoiceLine("Prestation A", Decimal("2"), Decimal("500.00"), Decimal("20")),
        InvoiceLine("Prestation B", Decimal("1"), Decimal("300.00"), Decimal("20")),
    ]

def make_invoice(**kwargs):
    defaults = dict(
        number="FAC-TEST-001",
        issue_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        seller=make_seller(),
        buyer=make_buyer(),
        lines=make_lines(),
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


# ─────────────────────────────────────────────
# Tests de génération
# ─────────────────────────────────────────────

class TestInvoiceCalculations(unittest.TestCase):

    def test_line_total_ht(self):
        line = InvoiceLine("Test", Decimal("3"), Decimal("100.00"), Decimal("20"))
        self.assertEqual(line.line_total_ht, Decimal("300.00"))

    def test_line_vat_amount(self):
        line = InvoiceLine("Test", Decimal("1"), Decimal("1000.00"), Decimal("20"))
        self.assertEqual(line.vat_amount, Decimal("200.00"))

    def test_line_total_ttc(self):
        line = InvoiceLine("Test", Decimal("1"), Decimal("1000.00"), Decimal("20"))
        self.assertEqual(line.line_total_ttc, Decimal("1200.00"))

    def test_invoice_totals(self):
        # 2 * 500 + 1 * 300 = 1300 HT
        # 1300 * 20% = 260 TVA
        # 1560 TTC
        invoice = make_invoice()
        self.assertEqual(invoice.total_ht, Decimal("1300.00"))
        self.assertEqual(invoice.total_vat, Decimal("260.00"))
        self.assertEqual(invoice.total_ttc, Decimal("1560.00"))

    def test_vat_breakdown_single_rate(self):
        invoice = make_invoice()
        breakdown = invoice.vat_breakdown()
        self.assertIn("20", breakdown)
        self.assertEqual(breakdown["20"]["base"], Decimal("1300.00"))
        self.assertEqual(breakdown["20"]["vat"], Decimal("260.00"))

    def test_vat_breakdown_multiple_rates(self):
        lines = [
            InvoiceLine("A", Decimal("1"), Decimal("100"), Decimal("20")),
            InvoiceLine("B", Decimal("1"), Decimal("200"), Decimal("10")),
        ]
        invoice = make_invoice(lines=lines)
        breakdown = invoice.vat_breakdown()
        self.assertIn("20", breakdown)
        self.assertIn("10", breakdown)
        self.assertEqual(breakdown["20"]["base"], Decimal("100.00"))
        self.assertEqual(breakdown["10"]["base"], Decimal("200.00"))

    def test_decimal_rounding(self):
        """Vérifie que les arrondis ne causent pas de dérive."""
        line = InvoiceLine("Test", Decimal("3"), Decimal("33.33"), Decimal("20"))
        # 3 * 33.33 = 99.99
        self.assertEqual(line.line_total_ht, Decimal("99.99"))
        # 99.99 * 20% = 19.998 → arrondi à 20.00
        self.assertEqual(line.vat_amount, Decimal("20.00"))


# ─────────────────────────────────────────────
# Tests de génération XML
# ─────────────────────────────────────────────

class TestXMLGeneration(unittest.TestCase):

    def test_generates_valid_xml_string(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIsInstance(xml, str)
        self.assertIn("CrossIndustryInvoice", xml)

    def test_contains_invoice_number(self):
        invoice = make_invoice(number="FAC-2026-XYZ")
        xml = generate_facturx_xml(invoice)
        self.assertIn("FAC-2026-XYZ", xml)

    def test_contains_seller_name(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("Acme SAS", xml)

    def test_contains_buyer_name(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("Client SARL", xml)

    def test_contains_siren_bt30(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("123456789", xml)

    def test_contains_vat_number(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("FR12345678901", xml)

    def test_contains_total_ht(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("1300.00", xml)

    def test_all_profiles_generate(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                invoice = make_invoice(profile=profile)
                xml = generate_facturx_xml(invoice)
                self.assertIn("CrossIndustryInvoice", xml)

    def test_demo_invoice_generates(self):
        """La facture de démo doit générer sans erreur."""
        invoice = make_demo_invoice()
        xml = generate_facturx_xml(invoice)
        self.assertIn("CrossIndustryInvoice", xml)


# ─────────────────────────────────────────────
# Tests de validation
# ─────────────────────────────────────────────

class TestValidation(unittest.TestCase):

    def _validate(self, xml: str):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml",
                                         encoding="utf-8", delete=False) as f:
            f.write(xml)
            tmp_path = f.name
        validator = InvoiceValidator(tmp_path)
        return validator.validate()

    def test_valid_invoice_passes(self):
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        result = self._validate(xml)
        self.assertTrue(result.is_valid, f"Erreurs : {[str(e) for e in result.errors]}")

    def test_demo_invoice_passes(self):
        invoice = make_demo_invoice()
        xml = generate_facturx_xml(invoice)
        result = self._validate(xml)
        self.assertTrue(result.is_valid, f"Erreurs : {[str(e) for e in result.errors]}")

    def test_invalid_xml_fails(self):
        result = self._validate("<invalid>xml")
        self.assertFalse(result.is_valid)
        self.assertTrue(any(i.rule_id == "PARSE-ERR" for i in result.errors))

    def test_invalid_siren_creates_error(self):
        seller = make_seller()
        seller.siret = "INVALID"
        invoice = make_invoice(seller=seller)
        xml = generate_facturx_xml(invoice)
        result = self._validate(xml)
        siren_errors = [i for i in result.issues if i.rule_id == "FR-01"]
        self.assertTrue(len(siren_errors) > 0)

    def test_file_not_found(self):
        validator = InvoiceValidator("/tmp/nonexistent_file_xyz.xml")
        result = validator.validate()
        self.assertFalse(result.is_valid)
        self.assertTrue(any(i.rule_id == "FILE-NOT-FOUND" for i in result.errors))

    def test_arithmetic_coherence(self):
        """Une facture correctement générée ne doit pas avoir d'erreur BR-CO-15."""
        invoice = make_invoice()
        xml = generate_facturx_xml(invoice)
        result = self._validate(xml)
        co15_errors = [i for i in result.errors if i.rule_id == "BR-CO-15"]
        self.assertEqual(len(co15_errors), 0)

    def test_profile_detected(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                invoice = make_invoice(profile=profile)
                xml = generate_facturx_xml(invoice)
                result = self._validate(xml)
                br02_info = [i for i in result.issues
                              if i.rule_id == "BR-02" and i.severity == "INFO"]
                self.assertTrue(len(br02_info) > 0)


# ─────────────────────────────────────────────
# Tests de simulation Chorus Pro
# ─────────────────────────────────────────────

class TestChorusSimulation(unittest.TestCase):

    def test_simulate_valid_file(self):
        from send_chorus import simulate_submission
        invoice = make_demo_invoice()
        xml = generate_facturx_xml(invoice)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml",
                                          encoding="utf-8", delete=False) as f:
            f.write(xml)
            tmp_path = f.name

        result = simulate_submission(tmp_path)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.submission_id)
        self.assertEqual(result.status, "DEPOSEE")
        self.assertTrue(result.simulated)

    def test_simulate_missing_file(self):
        from send_chorus import simulate_submission
        result = simulate_submission("/tmp/nonexistent.xml")
        self.assertFalse(result.success)

    def test_status_progression(self):
        from send_chorus import simulate_status_progression
        statuses = simulate_status_progression("DEP-TEST-001")
        self.assertTrue(len(statuses) > 0)
        self.assertTrue(all(r.simulated for r in statuses))
        # Vérifie que le statut final est "en paiement"
        final_status = statuses[-1].status
        self.assertIn(final_status, ["MISE_EN_PAIEMENT", "COMPTABILISEE", "MANDATEE"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
