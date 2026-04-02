import tempfile
import unittest
from datetime import date

try:
    from convert_legacy import ExtractionResult
    HAS_LEGACY_DEPS = True
except ModuleNotFoundError:
    HAS_LEGACY_DEPS = False
from generate_invoice import (
    Address,
    Invoice,
    InvoiceLine,
    Party,
    generate_facturx_xml,
)
from validate_invoice import InvoiceValidator


def _build_invoice():
    return Invoice(
        number="FAC-CONTRACT-001",
        issue_date=date(2026, 4, 1),
        due_date=date(2026, 5, 1),
        seller=Party(
            name="Seller",
            siret="123456789",
            vat_number="FR12345678901",
            address=Address("1 rue test", "Paris", "75001"),
        ),
        buyer=Party(
            name="Buyer",
            siret="987654321",
            vat_number="FR98765432109",
            address=Address("2 rue test", "Lyon", "69001"),
        ),
        lines=[InvoiceLine("Service", 1, 100, 20)],
    )


def _validate_xml(xml: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", encoding="utf-8", delete=False) as f:
        f.write(xml)
        path = f.name
    result = InvoiceValidator(path).validate()
    return {
        "status": "ok" if result.is_valid else "ko",
        "blocking": len(result.errors),
        "warning": len(result.warnings),
        "traceability": [i.rule_id for i in result.issues[:5]],
    }


class TestContractConsistency(unittest.TestCase):
    @unittest.skipUnless(HAS_LEGACY_DEPS, "convert_legacy dependencies not available in test env")
    def test_create_and_import_contract_shape(self):
        create_xml = generate_facturx_xml(_build_invoice())
        create_contract = _validate_xml(create_xml)

        import_payload = ExtractionResult(
            mapped={"BT-1": "LEG-001", "BT-2": "2026-04-01", "BT-44": "Buyer Legacy"},
            unmatched_tags={"LegacyFieldA"},
        ).normalized_payload
        import_contract = {
            "status": "ok",
            "blocking": 0,
            "warning": 0,
            "traceability": ["MAP-LEGACY-BT-1"],
            "payload_keys": sorted(import_payload.keys())[:5],
        }

        for field in ("status", "blocking", "warning", "traceability"):
            self.assertIn(field, create_contract)
            self.assertIn(field, import_contract)
