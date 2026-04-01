from decimal import Decimal

from generate_invoice import Address, Invoice, InvoiceLine, Party


def get_preloaded_examples() -> dict:
    return {
        "PME Services FR": {
            "seller_name": "Acme Conseil SAS",
            "seller_siret": "12345678901234",
            "seller_vat": "FR12345678901",
            "seller_iban": "FR7630006000011234567890189",
            "seller_bic": "BNPAFRPP",
            "seller_street": "12 rue de la Paix",
            "seller_city": "Paris",
            "seller_zip": "75001",
            "seller_country": "FR",
            "buyer_name": "Dupont Industries SARL",
            "buyer_siret": "98765432109876",
            "buyer_vat": "FR98765432109",
            "buyer_street": "5 avenue de la Gare",
            "buyer_zip": "69001",
            "buyer_city": "Lyon",
            "buyer_country": "FR",
            "invoice_number": "FAC-2026-001",
            "notes": "",
            "contract_ref": "",
            "purchase_order": "",
        }
    }


def build_invoice_from_form(form_data: dict, lines_data: list, issue_date, due_date, profile: str):
    required_fields = {
        "seller_name": "Raison sociale vendeur",
        "seller_siret": "SIRET vendeur",
        "buyer_name": "Raison sociale acheteur",
        "buyer_siret": "SIRET acheteur",
        "invoice_number": "Numero de facture",
    }

    missing = []
    for key, label in required_fields.items():
        if not str(form_data.get(key, "")).strip():
            missing.append(f"Champ obligatoire manquant: {label}")

    if not lines_data:
        missing.append("Au moins une ligne de facture est requise")

    if missing:
        return None, missing

    invoice = Invoice(
        number=str(form_data["invoice_number"]).strip(),
        issue_date=issue_date,
        due_date=due_date,
        notes=str(form_data.get("notes", "")).strip() or None,
        contract_ref=str(form_data.get("contract_ref", "")).strip() or None,
        purchase_order=str(form_data.get("purchase_order", "")).strip() or None,
        profile=profile,
        seller=Party(
            name=str(form_data["seller_name"]).strip(),
            siret=str(form_data["seller_siret"]).strip(),
            vat_number=str(form_data.get("seller_vat", "")).strip(),
            iban=str(form_data.get("seller_iban", "")).strip() or None,
            bic=str(form_data.get("seller_bic", "")).strip() or None,
            address=Address(
                street=str(form_data.get("seller_street", "")).strip(),
                city=str(form_data.get("seller_city", "")).strip(),
                postal_code=str(form_data.get("seller_zip", "")).strip(),
                country_code=str(form_data.get("seller_country", "FR")).strip() or "FR",
            ),
        ),
        buyer=Party(
            name=str(form_data["buyer_name"]).strip(),
            siret=str(form_data["buyer_siret"]).strip(),
            vat_number=str(form_data.get("buyer_vat", "")).strip(),
            address=Address(
                street=str(form_data.get("buyer_street", "")).strip(),
                city=str(form_data.get("buyer_city", "")).strip(),
                postal_code=str(form_data.get("buyer_zip", "")).strip(),
                country_code=str(form_data.get("buyer_country", "FR")).strip() or "FR",
            ),
        ),
        lines=[
            InvoiceLine(
                description=str(d).strip(),
                quantity=Decimal(str(q)),
                unit_price=Decimal(str(p)),
                vat_rate=Decimal(str(v)),
            )
            for d, q, p, v in lines_data
        ],
    )
    return invoice, []
