"""
patch_app.py
------------
Applique les corrections BUG 1 (faux total) et BUG 4 (catégories SKIPPED)
sur app.py. À lancer depuis la racine du repo :
    python patch_app.py
"""
from pathlib import Path
import sys

APP_PATH = Path("app.py")
if not APP_PATH.exists():
    print(f"❌ {APP_PATH} introuvable. Lance ce script depuis la racine du repo.")
    sys.exit(1)

src = APP_PATH.read_text(encoding="utf-8")
original_len = len(src)

# ─────────────────────────────────────────────────────────
# ZONE 2 — Calcul des métriques + colonnes affichées
# BUG 1 : total_rules comptait f1=True + f1=False + sans f1
# BUG 4 : 5 colonnes sans distinction des types de SKIPPED
# ─────────────────────────────────────────────────────────
AVANT_ZONE2 = """\
            nb_tested  = len(ai_result.errors) + len(ai_result.warnings) + len(ai_result.infos)
            nb_skipped = len(ai_result.skipped)

            # Total règles depuis rules.json
            try:
                import json
                with open(rules_path, encoding="utf-8") as f:
                    rules_data = json.load(f)
                total_rules = sum(
                    len(v) for k, v in rules_data.items()
                    if k != "meta" and isinstance(v, list)
                )
            except Exception:
                total_rules = 235

            col_a1, col_a2, col_a3, col_a4, col_a5 = st.columns(5)
            col_a1.metric("Statut Annexe 7",
                          "✅ CONFORME" if ai_result.is_valid else "❌ NON CONFORME")
            col_a2.metric("Règles totales",   total_rules)
            col_a3.metric("Testées",          nb_tested)
            col_a4.metric("Erreurs",          len(ai_result.errors))
            col_a5.metric("Non testables",    nb_skipped)"""

APRES_ZONE2 = """\
            # FIX BUG 1 : on utilise total_f1_rules exposé par AiValidator
            # (compte uniquement les règles f1=True — les f1=False sont
            #  dans le JSON pour documentation mais jamais traitées)
            nb_tested     = len(ai_result.errors) + len(ai_result.warnings) + len(ai_result.infos)
            nb_xslt       = len(ai_result.skipped_xslt)
            nb_condition  = len(ai_result.skipped_condition)
            nb_hors_scope = len(ai_result.skipped_out_of_scope)
            total_rules   = ai_val.total_f1_rules

            # FIX BUG 4 : 7 colonnes — chaque catégorie visible, additivité immédiate
            # Invariant : total = nb_xslt + nb_tested + nb_hors_scope + nb_condition
            col_a1, col_a2, col_a3, col_a4, col_a5, col_a6, col_a7 = st.columns(7)
            col_a1.metric(
                "Statut Annexe 7",
                "✅ CONFORME" if ai_result.is_valid else "❌ NON CONFORME"
            )
            col_a2.metric(
                "Règles f1",
                total_rules,
                help="Règles DGFiP marquées f1=True (Flux F1 — émission B2B). "
                     "Les règles f1=False sont dans le JSON à titre documentaire "
                     "et ne sont jamais évaluées."
            )
            col_a3.metric(
                "Ctrl 1 (XSLT)",
                nb_xslt,
                help="Règles déjà vérifiées par le Contrôle 1 (Schematron CEN EN16931 v1.3.15). "
                     "Elles ne sont pas re-évaluées ici pour éviter les doublons. "
                     "Lancez tag_rules_schematron.py pour activer ce compteur."
            )
            col_a4.metric(
                "Testées ici",
                nb_tested,
                help="Règles évaluées sur cette facture : présence des BT, format "
                     "(SIRET, TVA, dates), codelists (TypeCode, CategoryCode, CountryID)."
            )
            col_a5.metric("Erreurs", len(ai_result.errors))
            col_a6.metric(
                "Hors portée",
                nb_hors_scope,
                help="Règles nécessitant PPF/annuaire DGFiP ou dont le BT n'est pas "
                     "mappable localement (BG-*, BT-8, BT-21, BT-80, BT-111…). "
                     "Vérifiées par la PDP lors du dépôt réel."
            )
            col_a7.metric(
                "N/A facture",
                nb_condition,
                help="Règles conditionnelles non applicables à CETTE facture. "
                     "Ex : BR-55 (avoir sans référence) si TypeCode=380, "
                     "BR-IC-11 si catégorie TVA != K, etc. "
                     "Elles s'activent dans les scénarios concernés."
            )"""

# ─────────────────────────────────────────────────────────
# ZONE 3 — Expander des règles SKIPPED
# BUG 4 : séparation par "Contrôle" in message (fragile)
#         → remplacé par sous-type explicite skip_reason
# ─────────────────────────────────────────────────────────
AVANT_ZONE3 = """\
            with st.expander(f"⏭️ {nb_skipped} règles non testées localement"):
                skip_schema = [i for i in ai_result.skipped if "Contrôle" in i.message]
                skip_ppf    = [i for i in ai_result.skipped if "Contrôle" not in i.message]

                if skip_schema:
                    st.markdown(
                        f"**✅ {len(skip_schema)} règles déjà couvertes par "
                        "le Contrôle 1 (EN16931 XSLT)**"
                    )
                    for issue in skip_schema:
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")

                if skip_ppf:
                    st.markdown(
                        f"**⏭️ {len(skip_ppf)} règles nécessitant PPF/annuaire DGFiP**"
                    )
                    st.caption(
                        "Non testables en standalone — "
                        "requièrent un accès à la plateforme de dématérialisation."
                    )
                    for issue in skip_ppf:
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")"""

APRES_ZONE3 = """\
            # FIX BUG 4 : 3 sous-catégories via skip_reason (plus fragile que "Contrôle" in msg)
            nb_skipped_total = len(ai_result.skipped)
            with st.expander(
                f"⏭️ {nb_skipped_total} règles non évaluées "
                f"({nb_xslt} XSLT · {nb_hors_scope} hors portée · {nb_condition} N/A)"
            ):
                if ai_result.skipped_xslt:
                    st.markdown(
                        f"**✅ {nb_xslt} règles couvertes par le Contrôle 1 (Schematron EN16931)**"
                    )
                    st.caption(
                        "Ces règles sont testées par le moteur XSLT CEN v1.3.15 "
                        "au Contrôle 1. Les re-tester ici serait un doublon."
                    )
                    for issue in ai_result.skipped_xslt:
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")

                if ai_result.skipped_out_of_scope:
                    st.markdown(
                        f"**⏭️ {nb_hors_scope} règles hors portée locale**"
                    )
                    st.caption(
                        "Ces règles nécessitent un accès au PPF, à l'annuaire DGFiP "
                        "ou à l'historique des factures (unicité, atteignabilité adresse…). "
                        "Elles seront vérifiées par la PDP lors du dépôt réel."
                    )
                    for issue in ai_result.skipped_out_of_scope:
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")

                if ai_result.skipped_condition:
                    st.markdown(
                        f"**ℹ️ {nb_condition} règles non applicables à cette facture**"
                    )
                    st.caption(
                        "Ces règles sont conditionnelles (TypeCode, catégorie TVA, "
                        "présence d'un champ déclencheur). "
                        "Elles s'activent uniquement dans les scénarios concernés "
                        "(avoir, export, autoliquidation, etc.)."
                    )
                    for issue in ai_result.skipped_condition:
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")"""

# ─────────────────────────────────────────────────────────
# ZONE 4 — Caption final
# BUG 1 : les chiffres dans le caption ne correspondaient plus
# ─────────────────────────────────────────────────────────
AVANT_ZONE4 = """\
            st.caption(
                f"Sur {total_rules} règles DGFiP v1.8 : "
                f"{nb_tested} testables localement, "
                f"{nb_skipped} nécessitent PPF/annuaire/historique. "
                f"Syntaxe : {syntax_detect} "
                f"{'(via mapper UBL → BT)' if syntax_detect == 'UBL' else '(XPath CII natif)'}. "
                "Source : Annexe 7 DGFiP v1.8 (31/10/2025)"
            )"""

APRES_ZONE4 = """\
            # FIX BUG 1 : caption = équation visible pour vérifier l'additivité
            st.caption(
                f"{total_rules} règles f1=True "
                f"= {nb_xslt} Contrôle 1 (XSLT) "
                f"+ {nb_tested} testées ici ({len(ai_result.errors)} erreur(s)) "
                f"+ {nb_hors_scope} hors portée "
                f"+ {nb_condition} N/A. "
                f"Syntaxe : {syntax_detect} "
                f"{'(via mapper UBL → BT)' if syntax_detect == 'UBL' else '(XPath CII natif)'}. "
                "Source : Annexe 7 DGFiP v1.8 (31/10/2025)."
            )"""

# ─────────────────────────────────────────────────────────
# Application des patches
# ─────────────────────────────────────────────────────────

patches = [
    ("ZONE 2 — métriques", AVANT_ZONE2, APRES_ZONE2),
    ("ZONE 3 — expander SKIPPED", AVANT_ZONE3, APRES_ZONE3),
    ("ZONE 4 — caption", AVANT_ZONE4, APRES_ZONE4),
]

for label, avant, apres in patches:
    count = src.count(avant)
    if count == 0:
        print(f"❌ {label} : chaîne AVANT introuvable dans app.py")
        sys.exit(1)
    if count > 1:
        print(f"⚠️  {label} : chaîne AVANT trouvée {count} fois (ambiguïté)")
        sys.exit(1)
    src = src.replace(avant, apres)
    print(f"✅ {label} : appliqué ({avant.count(chr(10))+1} → {apres.count(chr(10))+1} lignes)")

# Vérification finale
assert src.count("nb_tested  = len") == 0,    "Ancienne ligne nb_tested encore présente"
assert src.count('total_rules = 235') == 0,    "Ancienne ligne fallback 235 encore présente"
assert src.count("col_a1, col_a2, col_a3, col_a4, col_a5, col_a6, col_a7") == 1, "7 colonnes attendues"
assert src.count("skipped_xslt") >= 2,         "skipped_xslt manquant"
assert src.count("skipped_out_of_scope") >= 2, "skipped_out_of_scope manquant"
assert src.count("skipped_condition") >= 2,    "skipped_condition manquant"
assert ".skip_reason" not in src,              "app.py ne doit pas acceder a .skip_reason directement"
assert "nb_hors_scope" in src,                 "nb_hors_scope manquant"
assert "nb_xslt" in src,                       "nb_xslt manquant"
assert "ai_val.total_f1_rules" in src,         "fix BUG 1 manquant (ai_val.total_f1_rules)"
assert 'f"Sur {total_rules}' not in src,       "Ancien caption encore present"

APP_PATH.write_text(src, encoding="utf-8")
print(f"\n✅ app.py patché ({original_len} → {len(src)} caractères)")
print(f"   {len(src) - original_len:+d} caractères")
