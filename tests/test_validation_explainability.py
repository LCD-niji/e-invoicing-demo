import unittest

from validation_explainability import explain_issue_plain_language, remediation_guidance


class TestValidationExplainability(unittest.TestCase):
    def test_plain_language_for_mandatory_field_rule(self):
        text = explain_issue_plain_language("BR-02", "Numero de facture manquant", "blocking")
        self.assertIn("obligatoire", text.lower())

    def test_plain_language_for_warning(self):
        text = explain_issue_plain_language("X-TEST", "Avertissement", "warning")
        self.assertIn("pas bloquant", text.lower())

    def test_remediation_for_siren_fr01(self):
        text = remediation_guidance("FR-01", "SIREN vendeur invalide")
        self.assertIn("9 chiffres", text)

    def test_remediation_for_calculation_rule(self):
        text = remediation_guidance("BR-CO-15", "Incoherence arithmetique")
        self.assertIn("Recalculez", text)
