from datetime import date
import unittest

from invoice_payload import build_invoice_from_form, get_preloaded_examples
from generate_invoice import generate_facturx_xml


def _sample_lines():
    return [("Prestation A", 2, 500.0, 20.0)]


class TestInvoicePayload(unittest.TestCase):
    def test_build_invoice_from_form_success(self):
        form_data = get_preloaded_examples()["PME Services FR"].copy()
        invoice, errors = build_invoice_from_form(
            form_data=form_data,
            lines_data=_sample_lines(),
            issue_date=date(2026, 4, 1),
            due_date=date(2026, 5, 1),
            profile="EN16931",
        )

        self.assertEqual(errors, [])
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.number, "FAC-2026-001")
        self.assertEqual(invoice.seller.name, "Acme Conseil SAS")
        self.assertEqual(invoice.buyer.siret, "987654321")
        self.assertEqual(len(invoice.lines), 1)

    def test_build_invoice_from_form_missing_required_fields(self):
        form_data = get_preloaded_examples()["PME Services FR"].copy()
        form_data["seller_name"] = ""
        form_data["invoice_number"] = " "
        invoice, errors = build_invoice_from_form(
            form_data=form_data,
            lines_data=_sample_lines(),
            issue_date=date(2026, 4, 1),
            due_date=date(2026, 5, 1),
            profile="EN16931",
        )

        # On ne bloque plus la création : l'objectif est de permettre la génération
        # de la facture tout en exposant un warning à l'UI.
        self.assertIsNotNone(invoice)
        self.assertTrue(any("Raison sociale vendeur" in err for err in errors))
        self.assertTrue(any("Numero de facture" in err for err in errors))

    def test_payload_is_ready_for_validation_xml_generation(self):
        form_data = get_preloaded_examples()["PME Services FR"].copy()
        invoice, errors = build_invoice_from_form(
            form_data=form_data,
            lines_data=_sample_lines(),
            issue_date=date(2026, 4, 1),
            due_date=date(2026, 5, 1),
            profile="EN16931",
        )

        self.assertEqual(errors, [])
        xml = generate_facturx_xml(invoice)
        self.assertIn("CrossIndustryInvoice", xml)
        self.assertIn("FAC-2026-001", xml)
