"""
validation_explainability.py
-----------------------------
Charge rules_engine/explanations.json (généré offline, zéro token runtime)
et expose les deux fonctions attendues par app.py :
  - explain_issue_plain_language(rule_id, message, severity)
  - remediation_guidance(rule_id, message)
"""
import json
from pathlib import Path

# Chargement unique au démarrage (cache module-level)
_DB: dict = {}
_DB_PATH = Path(__file__).parent / "rules_engine" / "explanations.json"


def _load() -> dict:
    global _DB
    if not _DB and _DB_PATH.exists():
        with open(_DB_PATH, encoding="utf-8") as f:
            _DB = json.load(f)
    return _DB


def explain_issue_plain_language(rule_id: str, message: str, severity: str) -> str:
    """Retourne l'explication métier d'une règle, en français clair."""
    entry = _load().get((rule_id or "").upper())
    if entry:
        return entry.get("explanation", message)

    # Fallback : même logique qu'avant pour les règles non couvertes
    rid = (rule_id or "").upper()
    if rid.startswith("BR-CO"):
        return "Le calcul total de la facture semble incohérent. Vérifiez montants HT, TVA et TTC."
    if rid.startswith("BR-CL"):
        return "Un code utilisé n'est pas reconnu par la norme. Vérifiez devise, pays ou code de catégorie."
    if rid in {"BR-01", "BR-02", "BR-03", "BR-04", "BR-05", "BR-06", "BR-07"}:
        return "Une information obligatoire manque dans la facture. Complétez les champs requis puis revalidez."
    msg_u = (message or "").upper()
    if "SIREN" in msg_u or ("BT-30" in msg_u or "BT-47" in msg_u):
        return "Le SIREN semble invalide ou absent. Renseignez un SIREN à 9 chiffres (Annexe 7)."
    if "SIRET" in msg_u:
        return "Le SIRET semble invalide ou absent. Renseignez un SIRET à 14 chiffres."
    if severity == "blocking":
        return "Cette anomalie bloque la conformité de la facture et doit être corrigée."
    if severity == "warning":
        return "Ce point n'est pas bloquant immédiatement mais peut poser problème ensuite."
    return "Information de contrôle fournie pour faciliter l'analyse de la facture."


def remediation_guidance(rule_id: str, message: str) -> str:
    """Retourne l'action corrective concrète pour une règle."""
    entry = _load().get((rule_id or "").upper())
    if entry:
        return entry.get("fix", "Corriger selon la norme EN16931.")

    # Fallback
    rid = (rule_id or "").upper()
    if rid.startswith("BR-CO"):
        return "Recalculez les lignes (quantité × prix), puis vérifiez total HT, TVA et total TTC."
    if rid.startswith("BR-CL"):
        return "Utilisez une valeur de code conforme (ISO 4217, ISO 3166-1 alpha-2, UNCL selon le champ)."
    if rid in {"BR-01", "BR-02", "BR-03", "BR-04", "BR-05", "BR-06", "BR-07"}:
        return "Renseignez le champ obligatoire manquant dans l'onglet de génération puis relancez la validation."
    msg_u = (message or "").upper()
    if "SIREN" in msg_u or ("BT-30" in msg_u or "BT-47" in msg_u):
        return "Corrigez le SIREN en 9 chiffres sans espaces ni caractères spéciaux."
    if "SIRET" in msg_u:
        return "Corrigez le SIRET en 14 chiffres sans espaces ni caractères spéciaux."
    return "Corrigez la donnée signalée par la règle, puis relancez la validation pour confirmer."
