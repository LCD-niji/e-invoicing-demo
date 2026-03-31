"""
patch_app_v3.py
---------------
Corrige app.py depuis son état actuel (après les patches précédents).

Changements :
  1. Métriques : 6 colonnes -> 7 colonnes (nb_condition obtient sa propre colonne)
  2. Caption : format liste -> format equation additive (118 = 0 + 58 + 47 + 13)

Usage depuis la racine du repo :
    python patch_app_v3.py
"""
import sys
from pathlib import Path

APP_PATH = Path("app.py")
if not APP_PATH.exists():
    print("❌ app.py introuvable. Lance ce script depuis la racine du repo.")
    sys.exit(1)

lines = APP_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
original_count = len(lines)

# ─────────────────────────────────────────────────────────
# Utilitaire : trouver un bloc de lignes par marqueur unique
# ─────────────────────────────────────────────────────────

def find_line(lines, marker, start=0):
    """Retourne l'index de la ligne contenant marker, ou -1."""
    for i in range(start, len(lines)):
        if marker in lines[i]:
            return i
    return -1


def replace_block(lines, start_marker, end_marker, new_block_lines):
    """
    Remplace le bloc [start_marker..end_marker] (inclus) par new_block_lines.
    Retourne les nouvelles lignes et le nb de lignes remplacées.
    """
    i_start = find_line(lines, start_marker)
    if i_start == -1:
        return None, f"marqueur de début introuvable : {repr(start_marker[:60])}"
    i_end = find_line(lines, end_marker, i_start + 1)
    if i_end == -1:
        return None, f"marqueur de fin introuvable : {repr(end_marker[:60])}"
    new_lines = lines[:i_start] + new_block_lines + lines[i_end + 1:]
    return new_lines, None


# ─────────────────────────────────────────────────────────
# PATCH 1 — Métriques : 6 colonnes -> 7 colonnes
#
# Marqueur début : "# FIX BUG 4 : 6 colonnes"
# Marqueur fin   : la ligne col_a6.metric( "Hors portée locale" ferme sur ")"
#                  suivi d'une ligne vide — on cherche la dernière col_a6 fermante
# ─────────────────────────────────────────────────────────

# Nouvelles lignes pour les métriques (7 colonnes)
# Indentation : 12 espaces (3 niveaux de 4)
INDENT = "            "

NEW_METRICS = [l + "\n" for l in [
    INDENT + "# 7 colonnes : chaque categorie a sa propre metrique",
    INDENT + "# Invariant visible : total = XSLT + testees + hors_portee + N/A",
    INDENT + "col_a1, col_a2, col_a3, col_a4, col_a5, col_a6, col_a7 = st.columns(7)",
    INDENT + "col_a1.metric(",
    INDENT + '    "Statut Annexe 7",',
    INDENT + '    "✅ CONFORME" if ai_result.is_valid else "❌ NON CONFORME"',
    INDENT + ")",
    INDENT + "col_a2.metric(",
    INDENT + '    "Regles f1",',
    INDENT + "    total_rules,",
    INDENT + '    help=("Regles DGFiP marquees f1=True (Flux F1 — emission B2B). "',
    INDENT + '          "Les regles f1=False sont dans le JSON a titre documentaire "',
    INDENT + '          "et ne sont jamais evaluees.")',
    INDENT + ")",
    INDENT + "col_a3.metric(",
    INDENT + '    "Ctrl 1 (XSLT)",',
    INDENT + "    nb_xslt,",
    INDENT + '    help=("Regles deja verifiees par le Controle 1 (Schematron CEN EN16931 v1.3.15). "',
    INDENT + '          "Elles ne sont pas re-evaluees ici pour eviter les doublons. "',
    INDENT + '          "Lancez tag_rules_schematron.py pour activer ce compteur.")',
    INDENT + ")",
    INDENT + "col_a4.metric(",
    INDENT + '    "Testees ici",',
    INDENT + "    nb_tested,",
    INDENT + '    help=("Regles evaluees sur cette facture : presence des BT, "',
    INDENT + '          "format (SIRET, TVA, dates), codelists (TypeCode, CategoryCode, CountryID).")',
    INDENT + ")",
    INDENT + "col_a5.metric(",
    INDENT + '    "Erreurs",',
    INDENT + "    len(ai_result.errors)",
    INDENT + ")",
    INDENT + "col_a6.metric(",
    INDENT + '    "Hors portee",',
    INDENT + "    nb_hors_scope,",
    INDENT + '    help=("Regles necessitant PPF/annuaire DGFiP ou dont le BT "',
    INDENT + '          "n\'est pas mappable localement (BG-*, BT-8, BT-21, BT-80, BT-111...). "',
    INDENT + '          "Verifiees par la PDP lors du depot reel.")',
    INDENT + ")",
    INDENT + "col_a7.metric(",
    INDENT + '    "N/A facture",',
    INDENT + "    nb_condition,",
    INDENT + '    help=("Regles conditionnelles non applicables a CETTE facture. "',
    INDENT + '          "Ex : BR-55 si TypeCode=380 (pas un avoir), "',
    INDENT + '          "BR-IC-11 si categorie TVA != K (pas intracom.). "',
    INDENT + '          "Elles s\'activent dans les scenarios concernes.")',
    INDENT + ")",
]]

START_METRICS = "# FIX BUG 4 : 6 colonnes avec séparation explicite des catégories"
# La fin du bloc métriques : la ligne qui ferme col_a6.metric(...)
# C'est la ligne "            )" qui suit le help= de col_a6
# On cherche la ligne contenant "+ {nb_condition} règles non applicables"
END_METRICS = "f\"+ {nb_condition} règles non applicables à cette facture.\""

# ─────────────────────────────────────────────────────────
# PATCH 2 — Caption : format liste -> format equation
# ─────────────────────────────────────────────────────────

# Nouvelles lignes pour le caption
NEW_CAPTION = [l + "\n" for l in [
    INDENT + "# Caption = equation : verifiable de tete (ex: 118 = 0 + 58 + 47 + 13)",
    INDENT + "st.caption(",
    INDENT + '    f"{total_rules} regles f1=True"',
    INDENT + '    f" = {nb_xslt} Ctrl1 (XSLT)"',
    INDENT + '    f" + {nb_tested} testees ici ({len(ai_result.errors)} erreur(s))"',
    INDENT + '    f" + {nb_hors_scope} hors portee"',
    INDENT + '    f" + {nb_condition} N/A."',
    INDENT + '    f" Syntaxe : {syntax_detect}"',
    INDENT + "    f\" {'(UBL -> BT)' if syntax_detect == 'UBL' else '(XPath CII)'}. \"",
    INDENT + '    "Source : Annexe 7 DGFiP v1.8 (31/10/2025)."',
    INDENT + ")",
]]

START_CAPTION = "# FIX BUG 1 : caption avec les vrais chiffres désormais cohérents"
END_CAPTION   = "\"Source : Annexe 7 DGFiP v1.8 (31/10/2025).\""

# ─────────────────────────────────────────────────────────
# Application des patches
# ─────────────────────────────────────────────────────────

patches = [
    ("Métriques (6→7 colonnes)", START_METRICS, END_METRICS,  NEW_METRICS),
    ("Caption (liste→équation)",  START_CAPTION, END_CAPTION, NEW_CAPTION),
]

ok = True
for label, start, end, new_block in patches:
    result, error = replace_block(lines, start, end, new_block)
    if error:
        print(f"❌ {label} : {error}")
        ok = False
    else:
        replaced = len(lines) - len(result) + len(new_block)
        lines = result
        print(f"✅ {label} : appliqué ({replaced} lignes → {len(new_block)} lignes)")

if not ok:
    print("\n❌ Patch interrompu — app.py non modifié.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────
# Vérifications post-patch
# ─────────────────────────────────────────────────────────
result_text = "".join(lines)

checks = [
    ("col_a7" in result_text,                              "col_a7 (7ème colonne) présent"),
    ("N/A facture" in result_text,                         "métrique 'N/A facture' présente"),
    ("st.columns(7)" in result_text,                       "st.columns(7) présent"),
    ("st.columns(6)" not in result_text,                   "st.columns(6) absent"),
    ("nb_xslt} Ctrl1" in result_text,        "format équation dans caption"),
    ("nb_condition} N/A" in result_text,                    "nb_condition dans caption"),
    ("ai_val.total_f1_rules" in result_text,                "total_f1_rules présent"),
    (".skip_reason" not in result_text,                     ".skip_reason absent (accès direct)"),
]

print()
all_ok = True
for condition, label in checks:
    icon = "✅" if condition else "❌"
    print(f"  {icon} {label}")
    if not condition:
        all_ok = False

if not all_ok:
    print("\n❌ Vérifications échouées — app.py non modifié.")
    sys.exit(1)

APP_PATH.write_text(result_text, encoding="utf-8")
print(f"\n✅ app.py mis à jour ({original_count} → {len(lines)} lignes)")
print()
print("Résultat attendu dans l'UI (avec les données actuelles) :")
print("  Règles f1 | Ctrl1 | Testées | Erreurs | Hors portée | N/A facture")
print("  118       |  0*   |   58    |    0    |     47      |     13")
print("  * 0 jusqu'à l'exécution de tag_rules_schematron.py")
print()
print("  Caption : '118 règles f1=True = 0 Ctrl1 + 58 testées (0 erreur) + 47 hors portée + 13 N/A'")
print("  Vérification : 0 + 58 + 47 + 13 = 118 ✓")
