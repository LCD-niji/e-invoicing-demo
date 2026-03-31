"""
tag_rules_schematron.py
-----------------------
Ajoute covered_by="schematron" sur les règles f1=True de rules.json
qui sont déjà vérifiées par le XSLT CEN (Contrôle 1 / Schematron EN16931).

Ces règles seront ensuite skippées proprement dans AiValidator avec
skip_reason="xslt", et affichées dans la colonne "Couvertes par XSLT"
de l'interface plutôt que dans "Testées ici".

Pourquoi ces règles sont déjà couvertes par le XSLT :
  - EN16931_CO  : cohérence arithmétique (sommes, totaux) — calculées par Saxon
  - EN16931_DEC : format décimales — vérifié par Saxon sur le document XML
  - EN16931_CL  : codelists (TypeCode, CategoryCode, CountryID...) — Saxon
  - BR-*-8      : formules BT-116 = sum(BT-131) par catégorie TVA
  - BR-*-9      : TVA calculée = 0 pour les catégories exonérées
  - BR-S-9      : BT-117 = BT-116 × BT-119 / 100

Usage :
    python tag_rules_schematron.py
    python tag_rules_schematron.py --dry-run   # aperçu sans modifier le fichier
"""
import json
import argparse
from pathlib import Path

RULES_PATH = Path("rules_engine/rules.json")

# Sections dont TOUTES les règles f1=True sont couvertes par le XSLT CEN
SECTIONS_FULL_XSLT = {
    "EN16931_CO",   # Cohérence arithmétique : BR-CO-9 à BR-CO-26
    "EN16931_DEC",  # Décimales : BR-DEC-01 à BR-DEC-24
    "EN16931_CL",   # Codelists : BR-CL-01 à BR-CL-23
}

# Règles individuelles dans d'autres sections aussi couvertes par le XSLT
# (formules de calcul TVA par catégorie — Saxon les évalue sur le XML)
RULES_INDIVIDUAL_XSLT = {
    "BR-AE-8",  # BT-116 = sum BT-131 pour catégorie AE
    "BR-AE-9",  # BT-117 = 0 pour catégorie AE
    "BR-E-8",   # BT-116 = sum BT-131 pour catégorie E
    "BR-E-9",   # BT-117 = 0 pour catégorie E
    "BR-G-8",   # BT-116 = sum BT-131 pour catégorie G (export)
    "BR-G-9",   # BT-117 = 0 pour catégorie G
    "BR-IC-8",  # BT-116 = sum BT-131 pour catégorie K (intracom.)
    "BR-IC-9",  # BT-117 = 0 pour catégorie K
    "BR-S-8",   # BT-116 = sum BT-131 pour catégorie S (standard)
    "BR-S-9",   # BT-117 = BT-116 × BT-119 / 100
    "BR-Z-8",   # BT-116 = sum BT-131 pour catégorie Z (taux zéro)
    "BR-Z-9",   # BT-117 = 0 pour catégorie Z
}


def tag_rules(data: dict, dry_run: bool = False) -> tuple[int, int]:
    """
    Ajoute covered_by="schematron" sur les règles éligibles.
    Retourne (nb_tagged, nb_already_tagged).
    """
    tagged = 0
    already = 0

    for section, rules in data.items():
        if section == "meta" or not isinstance(rules, list):
            continue
        for rule in rules:
            if not rule.get("f1", False):
                continue  # on ne touche que les règles f1=True

            rule_id = rule.get("id", "")
            should_tag = False

            # Cas 1 : section entière couverte par XSLT
            if section in SECTIONS_FULL_XSLT:
                should_tag = True

            # Cas 2 : règle individuelle listée explicitement
            elif rule_id in RULES_INDIVIDUAL_XSLT:
                should_tag = True

            # Cas 3 : règle avec champ "formula" explicite
            # (calcul arithmétique = Saxon le fait mieux que XPath natif)
            elif "formula" in rule:
                should_tag = True

            if should_tag:
                if rule.get("covered_by") == "schematron":
                    already += 1
                elif not dry_run:
                    rule["covered_by"] = "schematron"
                    tagged += 1
                else:
                    tagged += 1  # dry-run : compte sans modifier

    return tagged, already


def print_summary(data: dict):
    """Affiche un résumé des comptages après tagging."""
    f1_total  = sum(1 for s, v in data.items()
                    if s != "meta" and isinstance(v, list)
                    for r in v if r.get("f1"))
    f1_xslt   = sum(1 for s, v in data.items()
                    if s != "meta" and isinstance(v, list)
                    for r in v if r.get("f1") and r.get("covered_by") == "schematron")
    f1_active = f1_total - f1_xslt

    print(f"\n   Règles f1=True total          : {f1_total}")
    print(f"   → couvertes par XSLT (Ctrl 1) : {f1_xslt}")
    print(f"   → à tester dans Contrôle 2    : {f1_active}")
    print(f"\n   Invariant : {f1_xslt} + {f1_active} = {f1_xslt + f1_active} "
          f"{'✅' if f1_xslt + f1_active == f1_total else '❌'}")
    print()
    print("   Ce que devrait afficher l'UI :")
    print(f"     Règles f1 applicables  : {f1_total}")
    print(f"     Couvertes par XSLT     : {f1_xslt}")
    print(f"     Testées ici (estimé)   : ~{f1_active - 13}  (hors ~13 N/A conditionnels)")
    print(f"     Hors portée locale     : ~47")
    print(f"     N/A condition          : ~13")
    print(f"     Total non évaluées     : ~{f1_xslt + 47 + 13}")
    ok = (f1_xslt + (f1_active - 13) + 47 + 13) == f1_total
    print(f"     Additivité             : {'✅' if ok else '⚠️  (estimations approximatives)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tague les règles XSLT dans rules.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche les changements sans modifier le fichier")
    args = parser.parse_args()

    if not RULES_PATH.exists():
        print(f"❌ {RULES_PATH} introuvable. Lance ce script depuis la racine du repo.")
        raise SystemExit(1)

    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    mode = "DRY-RUN" if args.dry_run else "MISE À JOUR"
    print(f"\n{'─'*50}")
    print(f"  tag_rules_schematron.py — {mode}")
    print(f"{'─'*50}")

    tagged, already = tag_rules(data, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n🔍 {tagged} règles seraient taguées covered_by=schematron")
        print(f"   {already} déjà taguées (pas retouchées)")
    else:
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {tagged} règles taguées covered_by=schematron")
        print(f"   {already} déjà taguées (pas retouchées)")
        print(f"   rules.json mis à jour.")

    print_summary(data)
