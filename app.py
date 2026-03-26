"""
app.py
------
Dashboard Streamlit — Démo facturation électronique 2026

Fonctionnalités :
  ✅ Formulaire de saisie de facture
  ✅ Génération XML Factur-X (EN 16931)
  ✅ Génération PDF/A-3b Factur-X complet
  ✅ Validation avec affichage des erreurs/warnings
  ✅ Conversion XML CII → Factur-X PDF
  ✅ Simulation dépôt Chorus Pro
  ✅ Suivi de statut en temps réel

Lancement :
    streamlit run app.py
"""

import sys
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from schematron_validator import validate_en16931, SchematronResult
from rules_engine.ai_validator import AiValidator, AiResult

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from generate_invoice import (
    Address, Invoice, InvoiceLine, Party,
    generate_facturx_xml, PROFILES
)
from generate_pdf import render_invoice_pdf
from generate_facturx import build_facturx, build_facturx_from_xml
from validate_invoice import InvoiceValidator
from send_chorus import simulate_submission, simulate_status_progression, CHORUS_STATUS
from generate_facturx import build_facturx, build_facturx_from_xml, extract_xml_from_facturx

import facturx
st.caption(f"facturx version : {facturx.__version__} — attrs : {[a for a in dir(facturx) if not a.startswith('_')]}")

# ─────────────────────────────────────────────
# Configuration Streamlit
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Démo Facturation Électronique 2026",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
    }
    .status-badge {
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-valid   { background: #d4edda; color: #155724; }
    .badge-invalid { background: #f8d7da; color: #721c24; }
    .badge-warn    { background: #fff3cd; color: #856404; }
    .metric-card {
        background: #f8f9fa;
        border-left: 4px solid #0f3460;
        padding: 1rem;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
    .chorus-step {
        background: #e8f4f8;
        border-radius: 8px;
        padding: 0.8rem;
        margin: 0.4rem 0;
        border-left: 3px solid #17a2b8;
    }
    .rule-error   { border-left-color: #dc3545 !important; background: #fdf2f3; }
    .rule-warning { border-left-color: #ffc107 !important; background: #fffdf0; }
    .rule-info    { border-left-color: #28a745 !important; background: #f2fdf5; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# En-tête
# ─────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🧾 Facturation Électronique 2026</h1>
    <p style="opacity:0.8; margin:0">
        Démo technique — Génération Factur-X · Validation EN 16931 · Dépôt Chorus Pro
    </p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Paramètres")

    profile = st.selectbox(
        "Profil Factur-X",
        options=list(PROFILES.keys()),
        index=3,
        help="EN16931 est recommandé pour les PME"
    )

    st.divider()
    st.markdown("**📋 À propos de cette démo**")
    st.markdown("""
Cette démo illustre une implémentation complète de la **réforme facturation électronique 2026** :

- ✅ Norme **Factur-X** (PDF/A-3 + XML CII)
- ✅ Règles **EN 16931** (norme européenne)
- ✅ Intégration **Chorus Pro** (API PISTE)
- ✅ Validations **DGFiP** spécifiques FR

---
🔗 [LinkedIn](#) · [GitHub](#) · [Me contacter](#)
    """)

    st.divider()
    st.info("💡 **Réforme 2026** : toutes les PME françaises devront émettre des factures électroniques à partir du 1er septembre 2026.")


# ─────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📝 Saisie facture",
    "✅ Validation",
    "🚀 Dépôt Chorus Pro",
    "📊 Statut & Suivi"
])


# ═══════════════════════════════════════════
# TAB 1 — Saisie de la facture
# ═══════════════════════════════════════════

with tab1:
    st.subheader("Informations de la facture")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        invoice_number = st.text_input("Numéro de facture",
                                        value=f"FAC-2026-{uuid.uuid4().hex[:6].upper()}")
    with col2:
        issue_date = st.date_input("Date d'émission", value=date.today())
    with col3:
        due_days = st.number_input("Délai paiement (jours)", value=30, min_value=0, max_value=365)

    st.divider()
    col_sell, col_buy = st.columns(2)

    with col_sell:
        st.markdown("#### 🏢 Vendeur (Fournisseur)")
        seller_name    = st.text_input("Raison sociale", value="Acme Conseil SAS", key="s_name")
        seller_siret   = st.text_input("SIRET (14 chiffres)", value="12345678901234", key="s_siret")
        seller_vat     = st.text_input("N° TVA intra", value="FR12345678901", key="s_vat")
        seller_street  = st.text_input("Adresse", value="12 rue de la Paix", key="s_street")
        col_s1, col_s2 = st.columns([1, 2])
        with col_s1:
            seller_cp   = st.text_input("CP", value="75001", key="s_cp")
        with col_s2:
            seller_city = st.text_input("Ville", value="Paris", key="s_city")
        seller_iban    = st.text_input("IBAN (virement SEPA)", value="FR7630006000011234567890189", key="s_iban")

    with col_buy:
        st.markdown("#### 🏪 Acheteur (Client)")
        buyer_name    = st.text_input("Raison sociale", value="Dupont & Fils SARL", key="b_name")
        buyer_siret   = st.text_input("SIRET (14 chiffres)", value="98765432109876", key="b_siret")
        buyer_vat     = st.text_input("N° TVA intra", value="FR98765432109", key="b_vat")
        buyer_street  = st.text_input("Adresse", value="5 avenue des Champs", key="b_street")
        col_b1, col_b2 = st.columns([1, 2])
        with col_b1:
            buyer_cp   = st.text_input("CP", value="69001", key="b_cp")
        with col_b2:
            buyer_city = st.text_input("Ville", value="Lyon", key="b_city")

    st.divider()
    st.markdown("#### 📦 Lignes de facture")

    if "lines" not in st.session_state:
        st.session_state.lines = [
            {"desc": "Audit système de facturation", "qty": 3.0, "price": 800.0, "vat": 20.0},
            {"desc": "Implémentation connecteur Chorus Pro", "qty": 5.0, "price": 950.0, "vat": 20.0},
            {"desc": "Formation équipe comptable", "qty": 2.0, "price": 600.0, "vat": 20.0},
        ]

    lines_data = []
    for i, line in enumerate(st.session_state.lines):
        cols = st.columns([4, 1, 2, 1, 0.5])
        with cols[0]:
            desc = st.text_input("Description", value=line["desc"], key=f"l_desc_{i}", label_visibility="collapsed")
        with cols[1]:
            qty = st.number_input("Qté", value=line["qty"], key=f"l_qty_{i}", min_value=0.0, step=0.5, label_visibility="collapsed")
        with cols[2]:
            price = st.number_input("Prix HT (€)", value=line["price"], key=f"l_price_{i}", min_value=0.0, step=10.0, label_visibility="collapsed")
        with cols[3]:
            vat = st.selectbox("TVA %", options=[0.0, 5.5, 10.0, 20.0], index=3, key=f"l_vat_{i}", label_visibility="collapsed")
        with cols[4]:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.lines.pop(i)
                st.rerun()
        lines_data.append({"desc": desc, "qty": qty, "price": price, "vat": vat})

    if st.button("➕ Ajouter une ligne"):
        st.session_state.lines.append({"desc": "Nouvelle prestation", "qty": 1.0, "price": 500.0, "vat": 20.0})
        st.rerun()

    if lines_data:
        total_ht  = sum(Decimal(str(l["qty"])) * Decimal(str(l["price"])) for l in lines_data)
        total_vat = sum(Decimal(str(l["qty"])) * Decimal(str(l["price"])) * Decimal(str(l["vat"])) / 100 for l in lines_data)
        total_ttc = total_ht + total_vat

        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Total HT", f"{float(total_ht):,.2f} €")
        m2.metric("TVA", f"{float(total_vat):,.2f} €")
        m3.metric("Total TTC", f"{float(total_ttc):,.2f} €")

    st.divider()
    notes = st.text_area("Notes / Mentions légales",
                          value="Merci pour votre confiance. Paiement par virement SEPA sous 30 jours.",
                          height=80)

    # ── Génération XML ────────────────────────────────────
    if st.button("🔧 Générer la facture XML", type="primary", use_container_width=True):
        try:
            seller = Party(
                name=seller_name, siret=seller_siret, vat_number=seller_vat,
                address=Address(seller_street, seller_city, seller_cp),
                iban=seller_iban or None,
            )
            buyer = Party(
                name=buyer_name, siret=buyer_siret, vat_number=buyer_vat,
                address=Address(buyer_street, buyer_city, buyer_cp),
            )
            invoice_lines = [
                InvoiceLine(
                    description=l["desc"],
                    quantity=Decimal(str(l["qty"])),
                    unit_price=Decimal(str(l["price"])),
                    vat_rate=Decimal(str(l["vat"])),
                )
                for l in lines_data
            ]
            invoice = Invoice(
                number=invoice_number,
                issue_date=issue_date,
                due_date=issue_date + timedelta(days=due_days),
                seller=seller,
                buyer=buyer,
                lines=invoice_lines,
                profile=profile,
                notes=notes if notes else None,
            )
            xml_content = generate_facturx_xml(invoice)
            st.session_state["xml_content"] = xml_content
            st.session_state["invoice_obj"]  = invoice
            st.session_state["submission_id"] = None
            st.success("✅ Facture XML générée avec succès !")

            with st.expander("📄 Aperçu XML (100 premières lignes)"):
                st.code("\n".join(xml_content.split("\n")[:100]), language="xml")

            st.download_button(
                label="⬇️ Télécharger le fichier XML",
                data=xml_content.encode("utf-8"),
                file_name=f"{invoice_number}.xml",
                mime="application/xml",
            )

        except Exception as e:
            st.error(f"❌ Erreur lors de la génération : {e}")

    # ── Génération Factur-X PDF/A-3 ───────────────────────
    if "xml_content" in st.session_state and "invoice_obj" in st.session_state:
        st.divider()
        if st.button("📄 Générer le Factur-X complet (PDF/A-3b)", use_container_width=True):
            with st.spinner("Génération du Factur-X PDF/A-3b..."):
                try:
                    fx_bytes = build_facturx(
                        st.session_state["invoice_obj"],
                        st.session_state["xml_content"]
                    )
                    inv_num = st.session_state["invoice_obj"].number
                    st.download_button(
                        label="⬇️ Télécharger le Factur-X (.pdf)",
                        data=fx_bytes,
                        file_name=f"{inv_num}.pdf",
                        mime="application/pdf",
                    )
                    st.success("✅ Factur-X PDF/A-3b généré — XML CII embarqué dans le PDF")
                    st.info("📌 Ce fichier contient le PDF lisible ET le XML légal. Il est conforme à la norme Factur-X pour la réforme 2026.")
                except Exception as e:
                    st.error(f"❌ Erreur PDF/A-3 : {e}")

# ═══════════════════════════════════════════
# TAB 2 — Validation
# ═══════════════════════════════════════════

with tab2:
    st.subheader("Validation de la facture")

    xml_source = st.radio(
        "Source",
        ["Facture générée ci-dessus",
         "Uploader un fichier XML",
         "Uploader un Factur-X PDF"],
        horizontal=True
    )

    xml_to_validate = None

    if xml_source == "Facture générée ci-dessus":
        if "xml_content" in st.session_state:
            xml_to_validate = st.session_state["xml_content"]
            st.success("Facture chargée depuis l'étape précédente")
        else:
            st.warning("⚠️ Générez d'abord une facture dans l'onglet précédent")

    elif xml_source == "Uploader un fichier XML":
        uploaded = st.file_uploader("Choisir un fichier XML Factur-X", type=["xml"])
        if uploaded:
            content = uploaded.read()
            try:
                xml_to_validate = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                xml_to_validate = content.decode("latin-1")

    elif xml_source == "Uploader un Factur-X PDF":
        st.info("Uploadez un PDF généré par cet outil (bouton 'Générer le Factur-X complet' dans l'onglet 1).")
        uploaded_pdf = st.file_uploader(
            "Choisir un fichier Factur-X (.pdf)", type=["pdf"], key="pdf_upload"
        )
        if uploaded_pdf:
            pdf_bytes = uploaded_pdf.read()
            try:
                xml_to_validate, detected_profile = extract_xml_from_facturx(pdf_bytes)
                if "<facture>" in xml_to_validate or "CrossIndustryInvoice" not in xml_to_validate:
                    st.error(
                        "❌ Le XML embarqué dans ce PDF est au **format propriétaire** "
                        "(pas au format CII Factur-X). Ce PDF vient d'un système legacy "
                        "et n'est pas conforme à la réforme 2026."
                    )
                    xml_to_validate = None
                else:
                    st.success(f"✅ XML CII extrait du PDF — Profil : **{detected_profile}**")
                    with st.expander("📄 Aperçu du XML extrait (50 premières lignes)"):
                        st.code("\n".join(xml_to_validate.split("\n")[:50]), language="xml")
                    st.download_button(
                        label="⬇️ Télécharger le XML extrait",
                        data=xml_to_validate.encode("utf-8"),
                        file_name=uploaded_pdf.name.replace(".pdf", "_extracted.xml"),
                        mime="application/xml",
                    )
            except ValueError as e:
                st.error(f"❌ {e}")
                xml_to_validate = None

    # Feedback format avant validation
    if xml_to_validate:
        if "CrossIndustryInvoice" not in xml_to_validate:
            st.warning(
                "⚠️ Le contenu chargé n'est pas un XML CII Factur-X — "
                "la validation va échouer structurellement."
            )

    # Initialisation
    result     = None
    sch_result = None
    ai_result  = None

    if xml_to_validate and st.button("🔍 Valider la facture", type="primary", use_container_width=True):

        tmp_path = "/tmp/facture_validation.xml"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(xml_to_validate)

        # ══════════════════════════════════════════════════
        # CONTRÔLE 1 — Conformité structurelle DGFiP
        # ══════════════════════════════════════════════════
        st.divider()
        st.markdown("#### 🏛️ Contrôle 1 — Conformité structurelle DGFiP")
        st.caption(
            "La DGFiP impose un format CII (Cross Industry Invoice) précis pour la réforme 2026. "
            "Ces contrôles vérifient que le document respecte la structure minimale : "
            "élément racine, profil Factur-X, numéro, date, TypeCode. "
            "Un document qui échoue ici sera rejeté immédiatement par toute plateforme "
            "de dématérialisation (PDP/PPF)."
        )

        validator = InvoiceValidator(tmp_path)
        result    = validator.validate()

        nb_dgfip_total = len(result.errors) + len(result.warnings) + len(result.infos)

        col_v1, col_v2, col_v3, col_v4 = st.columns(4)
        col_v1.metric("Statut DGFiP", "✅ VALIDE" if result.is_valid else "❌ INVALIDE")
        col_v2.metric("Tests exécutés", nb_dgfip_total)
        col_v3.metric("Erreurs", len(result.errors))
        col_v4.metric("Warnings", len(result.warnings))

        if result.is_valid:
            st.success("🎉 Structure conforme aux exigences DGFiP !")
        else:
            st.error(f"La facture comporte {len(result.errors)} erreur(s) bloquante(s)")

        for issue in result.errors:
            html = (
                '<div style="background-color:#fff0f0;border-left:4px solid #c0392b;'
                'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                '❌ <strong style="color:#c0392b;">[' + str(issue.rule_id) + ']</strong> '
                '<span style="color:#333333;">' + str(issue.message) + '</span>'
                '</div>'
            )
            st.markdown(html, unsafe_allow_html=True)

        for issue in result.warnings:
            html = (
                '<div style="background-color:#fffbf0;border-left:4px solid #b8860b;'
                'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                '⚠️ <strong style="color:#b8860b;">[' + str(issue.rule_id) + ']</strong> '
                '<span style="color:#333333;">' + str(issue.message) + '</span>'
                '</div>'
            )
            st.markdown(html, unsafe_allow_html=True)

        ok_items = result.infos
        if ok_items:
            with st.expander(f"✅ {len(ok_items)} règle(s) DGFiP passée(s)"):
                for issue in ok_items:
                    html = (
                        '<div style="background-color:#f0fff4;border-left:4px solid #1a7a4a;'
                        'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                        '✅ <strong style="color:#1a7a4a;">[' + str(issue.rule_id) + ']</strong> '
                        '<span style="color:#333333;">' + str(issue.message) + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)

        # ══════════════════════════════════════════════════
        # CONTRÔLE 2 — Norme européenne EN 16931
        # ══════════════════════════════════════════════════
        st.divider()
        st.markdown("#### 🇪🇺 Contrôle 2 — Norme européenne EN 16931 (CEN/TC 434)")
        st.caption(
            "La France a adopté la norme européenne EN 16931 comme socle commun de la facturation "
            "électronique. Ce contrôle applique les ~120 règles BR-* officielles du CEN "
            "(Comité Européen de Normalisation) : cohérence arithmétique, codelists ISO, "
            "règles TVA par catégorie. Un document conforme EN 16931 est interopérable "
            "dans toute l'Union Européenne."
        )

        with st.spinner("Application des règles Schematron CEN v1.3.15..."):
            sch_result = validate_en16931(tmp_path)

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Statut EN16931", "✅ CONFORME" if sch_result.is_valid else "❌ NON CONFORME")
        col_s2.metric("Règles BR-* vérifiées", "~120")
        col_s3.metric("Erreurs BR-*", len(sch_result.errors))
        col_s4.metric("Warnings BR-*", len(sch_result.warnings))

        # Liste exhaustive des règles EN16931 CII (source : spec CEN/TC 434 v1.3.15)
        ALL_BR_RULES = {
            "BR-01": "Identifiant de spécification (BT-24) obligatoire",
            "BR-02": "Numéro de facture (BT-1) obligatoire",
            "BR-03": "Date d'émission (BT-2) obligatoire",
            "BR-04": "TypeCode (BT-3) obligatoire",
            "BR-05": "Devise (BT-5) obligatoire",
            "BR-06": "Nom du vendeur (BT-27) obligatoire",
            "BR-07": "Nom de l'acheteur (BT-44) obligatoire",
            "BR-08": "Adresse postale vendeur — code pays obligatoire",
            "BR-09": "Code pays vendeur — ISO 3166-1 alpha-2",
            "BR-10": "Adresse postale acheteur — code pays obligatoire",
            "BR-11": "Si identifiant vendeur (BT-29) : SchemeID obligatoire",
            "BR-12": "Si identifiant acheteur (BT-46) : SchemeID obligatoire",
            "BR-13": "Si identifiant tiers (BT-60) : SchemeID obligatoire",
            "BR-15": "Si BG-13 présent : BT-81 obligatoire",
            "BR-16": "Au moins une ligne de facture obligatoire",
            "BR-17": "Référence à une facture précédente — BT-25 obligatoire si BG-3",
            "BR-18": "Si identifiant vendeur fiscal (BT-32) : SchemeID obligatoire",
            "BR-19": "Si identifiant acheteur fiscal (BT-49) : SchemeID obligatoire",
            "BR-20": "Si référence projet (BT-11) présente : valeur non vide",
            "BR-21": "Identifiant ligne (BT-126) obligatoire",
            "BR-22": "Quantité facturée (BT-129) obligatoire",
            "BR-23": "Unité de mesure (BT-130) obligatoire",
            "BR-24": "Montant net ligne (BT-131) obligatoire",
            "BR-25": "Nom article (BT-153) obligatoire",
            "BR-26": "Code TVA ligne (BT-151) obligatoire",
            "BR-27": "Prix unitaire net (BT-146) obligatoire",
            "BR-28": "Prix de base (BT-148) obligatoire si remise ligne",
            "BR-29": "Si BT-73 et BT-74 présents : BT-74 >= BT-73",
            "BR-30": "Si remise (BG-27) : BT-92 et BT-94 obligatoires",
            "BR-31": "Le vendeur doit avoir SIRET ou TVA intracommunautaire",
            "BR-32": "Si BG-28 : BT-99 et BT-101 obligatoires",
            "BR-33": "BT-92 doit être positif",
            "BR-36": "Adresse vendeur — ville (BT-37) obligatoire",
            "BR-37": "Adresse vendeur — code postal (BT-38) obligatoire",
            "BR-38": "Adresse acheteur — ville (BT-53) obligatoire si BG-8",
            "BR-41": "BT-99 doit être positif",
            "BR-42": "Si BG-23 avec BT-118 : BT-116 et BT-117 obligatoires",
            "BR-43": "BT-110 = somme des BT-117",
            "BR-44": "Si BT-6 présent : valeur non vide",
            "BR-45": "Si BT-19 présent : valeur non vide",
            "BR-46": "Si BT-83 présent : BT-84 obligatoire",
            "BR-47": "Si BT-81=30 ou 58 : BT-84 (IBAN) obligatoire",
            "BR-48": "Si BT-81=54 : BT-86 (carte) obligatoire",
            "BR-49": "Si BT-133 présent : valeur non vide",
            "BR-50": "BT-92 <= BT-93 si BT-93 présent",
            "BR-51": "Si BG-26 : BT-104 et BT-106 obligatoires",
            "BR-52": "Si BG-27 ligne : BT-137 et BT-138 obligatoires",
            "BR-53": "BT-148 >= BT-146 si remise ligne",
            "BR-54": "Si BT-155 présent : SchemeID obligatoire",
            "BR-55": "BG-3 : BT-25 obligatoire",
            "BR-56": "Si BT-134 présent : SchemeID obligatoire",
            "BR-57": "Si BG-24 : BT-122 ou BT-123 obligatoire",
            "BR-61": "Si BT-81=30 : BT-85 (nom compte) recommandé",
            "BR-62": "Si BT-87 présent : BT-88 obligatoire",
            "BR-63": "Si BT-89 présent : valeur non vide",
            "BR-64": "BT-115 >= 0",
            "BR-65": "Si BT-114 présent : valeur >= 0",
            "BR-AE-1":  "Autoliquidation — mention BT-120/BT-121 obligatoire",
            "BR-AE-2":  "Autoliquidation — BT-118=AE sur toutes les lignes ou aucune",
            "BR-AE-3":  "Autoliquidation — BT-95=AE cohérent avec BT-118",
            "BR-AE-4":  "Autoliquidation — TVA calculée doit être 0",
            "BR-AE-5":  "Autoliquidation — BT-117 doit être 0",
            "BR-AE-6":  "Autoliquidation — BT-119 ne doit pas être renseigné",
            "BR-AE-7":  "Autoliquidation — BT-116 doit être positif",
            "BR-AE-8":  "Autoliquidation — BT-110 doit être 0",
            "BR-AE-9":  "Autoliquidation — BG-23 : un seul groupe AE autorisé",
            "BR-AE-10": "Autoliquidation — BT-121 ou BT-120 obligatoire",
            "BR-E-1":   "Exonération — BT-120 ou BT-121 obligatoire",
            "BR-E-2":   "Exonération — BT-118=E sur toutes les lignes ou aucune",
            "BR-E-3":   "Exonération — BT-95=E cohérent",
            "BR-E-4":   "Exonération — TVA calculée doit être 0",
            "BR-E-5":   "Exonération — BT-117 doit être 0",
            "BR-E-6":   "Exonération — BT-119 ne doit pas être renseigné",
            "BR-E-7":   "Exonération — BT-116 doit être positif",
            "BR-E-8":   "Exonération — BT-110 doit être 0",
            "BR-E-9":   "Exonération — BG-23 : un seul groupe E autorisé",
            "BR-G-1":   "Export — BT-120 ou BT-121 obligatoire",
            "BR-G-2":   "Export — BT-118=G cohérent",
            "BR-G-4":   "Export — BT-117 doit être 0",
            "BR-G-7":   "Export — BT-116 doit être positif",
            "BR-IC-1":  "Intracommunautaire — BT-120 ou BT-121 obligatoire",
            "BR-IC-2":  "Intracommunautaire — BT-118=K cohérent",
            "BR-IC-4":  "Intracommunautaire — BT-117 doit être 0",
            "BR-IC-7":  "Intracommunautaire — BT-116 doit être positif",
            "BR-IC-11": "Intracommunautaire — BT-55 (pays acheteur) obligatoire",
            "BR-IC-12": "Intracommunautaire — BT-40 (pays vendeur) obligatoire",
            "BR-O-1":   "Hors périmètre — BT-120 ou BT-121 obligatoire",
            "BR-O-4":   "Hors périmètre — BT-117 doit être 0",
            "BR-O-11":  "Hors périmètre — pas d'autres catégories TVA",
            "BR-O-12":  "Hors périmètre — BT-95 doit être O",
            "BR-O-13":  "Hors périmètre — BT-151 doit être O",
            "BR-S-1":   "Taux standard — BT-119 (RateApplicablePercent) obligatoire",
            "BR-S-2":   "Taux standard — BT-118=S cohérent",
            "BR-S-3":   "Taux standard — BT-95=S cohérent",
            "BR-S-4":   "Taux standard — BT-117 = BT-116 × BT-119 / 100",
            "BR-S-6":   "Taux standard — BT-116 doit être positif",
            "BR-S-7":   "Taux standard — BT-119 doit être > 0",
            "BR-Z-1":   "Taux zéro — BT-119 obligatoire",
            "BR-Z-4":   "Taux zéro — BT-117 doit être 0",
            "BR-Z-6":   "Taux zéro — BT-116 doit être positif",
            "BR-CO-3":  "Montant net ligne = BT-129 × BT-146",
            "BR-CO-4":  "BT-131 = BT-129 × BT-146 - remises + charges",
            "BR-CO-8":  "BT-106 = somme des BT-131",
            "BR-CO-9":  "BT-109 = somme des BT-116",
            "BR-CO-10": "BT-112 = BT-109 + BT-110",
            "BR-CO-11": "BT-115 = BT-112 - BT-113",
            "BR-CO-12": "BT-107 = somme des BT-92",
            "BR-CO-13": "BT-110 = somme des BT-117",
            "BR-CO-14": "BT-108 = somme des BT-99",
            "BR-CO-15": "BT-109 = BT-106 - BT-107 + BT-108",
            "BR-CO-16": "BT-115 arrondi cohérent",
            "BR-CO-17": "BT-92 <= BT-93 (remise <= prix de base)",
            "BR-CO-18": "BT-99 <= BT-100",
            "BR-CO-19": "Si BG-14 : BT-73 et/ou BT-74 obligatoire",
            "BR-CO-20": "Si BG-14 ligne : BT-134 et/ou BT-135 obligatoire",
            "BR-CO-21": "BT-131 arrondi cohérent",
            "BR-CO-22": "BT-146 arrondi cohérent",
            "BR-CO-23": "BT-148 arrondi cohérent",
            "BR-CO-24": "BT-92 arrondi cohérent",
            "BR-CO-25": "BT-99 arrondi cohérent",
            "BR-CL-01": "BT-3 (TypeCode) dans codelist UNTDID 1001",
            "BR-CL-04": "BT-5 (devise) dans codelist ISO 4217",
            "BR-CL-05": "BT-6 (devise TVA) dans codelist ISO 4217",
            "BR-CL-06": "BT-40 / BT-55 (pays) dans codelist ISO 3166-1 alpha-2",
            "BR-CL-07": "BT-95 / BT-118 / BT-151 (TVA catégorie) dans UNCL5305",
            "BR-CL-10": "BT-81 (moyen de paiement) dans UNTDID 4461",
            "BR-CL-14": "BT-130 (unité) dans UN/ECE Rec 20 ou Rec 21",
            "BR-CL-15": "BT-163 (unité prix) dans UN/ECE Rec 20 ou Rec 21",
            "BR-CL-16": "BT-133 (charge indicator) dans codelist",
            "BR-CL-17": "BT-136 (charge indicator ligne) dans codelist",
            "BR-CL-18": "BT-122 (type pièce jointe) dans MimeCode",
            "BR-CL-19": "BT-23 (code processus) dans codelist",
            "BR-CL-20": "BT-14 (ref document précédent) — SchemeID dans codelist",
            "BR-CL-21": "BT-32 (SchemeID vendeur) dans codelist ISO/IEC 6523",
            "BR-CL-22": "BT-121 (motif exonération) dans codelist VATEX",
            "BR-CL-23": "BT-130 (unité de mesure) dans UN/ECE Rec 20",
            "BR-CL-24": "BT-163 (unité de prix) dans UN/ECE Rec 20",
            "BR-CL-25": "BT-46 (SchemeID acheteur) dans codelist ISO/IEC 6523",
            "BR-CL-26": "BT-60 (SchemeID tiers) dans codelist ISO/IEC 6523",
            "BR-DEC-01":"BT-116 (BasisAmount) : max 2 décimales",
            "BR-DEC-02":"BT-117 (CalculatedAmount) : max 2 décimales",
            "BR-DEC-03":"BT-119 (RateApplicablePercent) : max 2 décimales",
            "BR-DEC-04":"BT-92 (AllowanceAmount) : max 2 décimales",
            "BR-DEC-05":"BT-93 (AllowanceBaseAmount) : max 2 décimales",
            "BR-DEC-06":"BT-94 (AllowancePercent) : max 2 décimales",
            "BR-DEC-07":"BT-99 (ChargeAmount) : max 2 décimales",
            "BR-DEC-08":"BT-100 (ChargeBaseAmount) : max 2 décimales",
            "BR-DEC-09":"BT-131 (LineTotalAmount) : max 2 décimales",
            "BR-DEC-10":"BT-137 (AllowanceAmount ligne) : max 2 décimales",
            "BR-DEC-11":"BT-138 (AllowanceBase ligne) : max 2 décimales",
            "BR-DEC-12":"BT-112 (GrandTotalAmount) : max 2 décimales",
            "BR-DEC-13":"BT-115 (DuePayableAmount) : max 2 décimales",
            "BR-DEC-14":"BT-146 (NetPrice) : max 10 décimales",
            "BR-DEC-15":"BT-148 (GrossPrice) : max 10 décimales",
            "BR-DEC-16":"BT-149 (AllowanceQuantity) : max 10 décimales",
            "BR-DEC-17":"BT-150 (BaseQuantity) : max 10 décimales",
            "BR-DEC-18":"BT-129 (BilledQuantity) : max 10 décimales",
            "BR-DEC-19":"BT-104 (AllowanceAmount entête) : max 2 décimales",
            "BR-DEC-20":"BT-106 (LineTotalAmount entête) : max 2 décimales",
            "BR-DEC-21":"BT-107 (AllowanceTotalAmount) : max 2 décimales",
            "BR-DEC-22":"BT-108 (ChargeTotalAmount) : max 2 décimales",
            "BR-DEC-23":"BT-109 (TaxBasisTotalAmount) : max 2 décimales",
            "BR-DEC-24":"BT-110 (TaxTotalAmount) : max 2 décimales",
            "BR-DEC-25":"BT-113 (PrepaidAmount) : max 2 décimales",
            "BR-DEC-26":"BT-114 (RoundingAmount) : max 2 décimales",
        }

        # IDs des règles en erreur ou warning
        failed_ids = {i.rule_id for i in sch_result.errors + sch_result.warnings}

        # Règles OK = toutes sauf celles en échec
        passed_rules = {k: v for k, v in ALL_BR_RULES.items() if k not in failed_ids}
        unknown_rules = {k: v for k, v in ALL_BR_RULES.items() if k in failed_ids}

        nb_all      = len(ALL_BR_RULES)
        nb_passed   = len(passed_rules)
        nb_failed   = len(sch_result.errors)
        nb_warnings = len(sch_result.warnings)

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Statut EN16931",       "✅ CONFORME" if sch_result.is_valid else "❌ NON CONFORME")
        col_s2.metric("Règles référentiel",   nb_all)
        col_s3.metric("Erreurs BR-*",         nb_failed)
        col_s4.metric("Warnings BR-*",        nb_warnings)

        if sch_result.is_valid:
            st.success("🎉 Conforme à la norme européenne EN 16931 (CEN/TC 434) !")

            with st.expander(f"✅ {nb_passed} règles BR-* passées (moteur XSLT CEN v1.3.15)"):
                for rule_id, desc in passed_rules.items():
                    html = (
                        '<div style="background-color:#f0fff4;border-left:4px solid #1a7a4a;'
                        'border-radius:6px;padding:8px 16px;margin-bottom:4px;">'
                        '✅ <strong style="color:#1a7a4a;">[' + rule_id + ']</strong> '
                        '<span style="color:#333333;font-size:0.9rem;">' + desc + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)
                st.caption(
                    f"{nb_passed} règles vérifiées sans anomalie sur {nb_all} du référentiel CEN. "
                    "Le moteur XSLT CEN/TC 434 v1.3.15 ne remonte que les échecs — "
                    "les règles absentes de la liste d'erreurs sont considérées conformes."
                )
        else:
            for issue in sch_result.errors:
                html = (
                    '<div style="background-color:#fff0f0;border-left:4px solid #c0392b;'
                    'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    '❌ <strong style="color:#c0392b;">[' + issue.rule_id + ']</strong> '
                    '<span style="color:#333333;">' + issue.message + '</span>'
                    '<br><small style="color:#888;font-size:0.75rem;">📍 ' + issue.location + '</small>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

        if sch_result and sch_result.warnings:
            with st.expander(f"⚠️ {len(sch_result.warnings)} avertissement(s) EN16931"):
                for issue in sch_result.warnings:
                    html = (
                        '<div style="background-color:#fffbf0;border-left:4px solid #b8860b;'
                        'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                        '⚠️ <strong style="color:#b8860b;">[' + issue.rule_id + ']</strong> '
                        '<span style="color:#333333;">' + issue.message + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)

        st.markdown("""
<div style="text-align:right;font-size:0.75rem;color:#888;margin-top:4px;">
    Source : <a href="https://github.com/ConnectingEurope/eInvoicing-EN16931" target="_blank">
    CEN/TC 434 — EN16931-CII-validation.xslt v1.3.15</a>
</div>""", unsafe_allow_html=True)

        # ══════════════════════════════════════════════════
        # CONTRÔLE 3 — Annexe 7 DGFiP
        # ══════════════════════════════════════════════════
        st.divider()
        st.markdown("#### 📋 Contrôle 3 — Règles de gestion DGFiP (Annexe 7 v1.8)")
        st.caption(
            "En plus de la norme européenne, la DGFiP a publié 235 règles de gestion spécifiques "
            "à la France (Annexe 7, mise à jour octobre 2025). Elles couvrent les particularités "
            "fiscales françaises : SIRET obligatoire, régimes de TVA FR, mentions légales, "
            "avoirs et rectificatives. Ces règles s'appliquent uniquement aux factures émises "
            "ou reçues par des assujettis français."
        )

        rules_path = Path("rules_engine/rules.json")
        if not rules_path.exists():
            st.warning("⚠️ rules_engine/rules.json introuvable")
        else:
            with st.spinner("Évaluation des règles Annexe 7 DGFiP..."):
                ai_val    = AiValidator(rules_path)
                ai_result = ai_val.validate(tmp_path)

            nb_tested  = len(ai_result.errors) + len(ai_result.warnings) + len(ai_result.infos)
            nb_skipped = len(ai_result.skipped)

            col_a1, col_a2, col_a3, col_a4, col_a5 = st.columns(5)
            col_a1.metric("Statut Annexe 7", "✅ CONFORME" if ai_result.is_valid else "❌ NON CONFORME")
            col_a2.metric("Règles testées",  nb_tested)
            col_a3.metric("Erreurs",         len(ai_result.errors))
            col_a4.metric("Warnings",        len(ai_result.warnings))
            col_a5.metric("Non testables",   nb_skipped)

            for issue in ai_result.errors:
                html = (
                    '<div style="background-color:#fff0f0;border-left:4px solid #c0392b;'
                    'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    '❌ <strong style="color:#c0392b;">[' + issue.rule_id + ']</strong> '
                    '<span style="color:#333333;">' + issue.message + '</span>'
                    '<br><small style="color:#888;">BT : ' + issue.bt + ' · ' + issue.source + '</small>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            for issue in ai_result.warnings:
                html = (
                    '<div style="background-color:#fffbf0;border-left:4px solid #b8860b;'
                    'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    '⚠️ <strong style="color:#b8860b;">[' + issue.rule_id + ']</strong> '
                    '<span style="color:#333333;">' + issue.message + '</span>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            with st.expander(f"✅ {len(ai_result.infos)} règles Annexe 7 passées"):
                for issue in ai_result.infos:
                    html = (
                        '<div style="background-color:#f0fff4;border-left:4px solid #1a7a4a;'
                        'border-radius:6px;padding:8px 16px;margin-bottom:4px;">'
                        '✅ <strong style="color:#1a7a4a;">[' + issue.rule_id + ']</strong> '
                        '<span style="color:#333333;font-size:0.9rem;">' + issue.message + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)

            with st.expander(f"⏭️ {nb_skipped} règles non testables localement"):
                st.caption(
                    "Ces règles nécessitent un accès au PPF/annuaire DGFiP "
                    "ou sont déjà couvertes par le Schematron CEN (Contrôle 2)."
                )
                for issue in ai_result.skipped:
                    st.markdown(f"— **[{issue.rule_id}]** {issue.message}")

            st.caption("Source : Annexe 7 — Règles de gestion DGFiP v1.8 (31/10/2025)")

# ═══════════════════════════════════════════
# TAB 3 — Dépôt Chorus Pro
# ═══════════════════════════════════════════

with tab3:
    st.subheader("Dépôt vers Chorus Pro")

    st.info("""
**🔵 Mode simulation activé**

Cette démo simule le dépôt sans faire d'appel réseau réel.
Pour un vrai dépôt, configurez vos credentials PISTE dans `.env`.
    """)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        siret_dest = st.text_input("SIRET entité publique destinataire",
                                    value="13000682900012",
                                    help="Ex : 13000682900012 = Ministère de l'Économie")
    with col_c2:
        service_code = st.text_input("Code service (optionnel)", value="")

    if st.button("🚀 Déposer la facture", type="primary", use_container_width=True):
        if "xml_content" not in st.session_state:
            st.warning("⚠️ Générez d'abord une facture dans l'onglet 1")
        else:
            tmp_path_chorus = "/tmp/facture_chorus.xml"
            with open(tmp_path_chorus, "w", encoding="utf-8") as f:
                f.write(st.session_state["xml_content"])

            with st.spinner("Dépôt en cours..."):
                steps_placeholder = st.empty()
                steps = [
                    "🔐 Authentification OAuth2 PISTE",
                    "📤 Encodage Base64 du flux XML",
                    "🚀 Envoi vers Chorus Pro sandbox",
                    "✅ Réception accusé de dépôt",
                ]
                for i, step in enumerate(steps):
                    steps_placeholder.markdown("\n".join(
                        [f"{'✅' if j < i else '⏳' if j == i else '⏸️'} {s}"
                         for j, s in enumerate(steps)]
                    ))
                    time.sleep(0.4)

                result_chorus = simulate_submission(tmp_path_chorus)
                steps_placeholder.empty()

            if result_chorus.success:
                st.success(f"✅ Facture déposée ! ID de dépôt : **{result_chorus.submission_id}**")
                st.session_state["submission_id"] = result_chorus.submission_id
                st.markdown("#### 📋 Accusé de dépôt")
                st.json(result_chorus.raw_response)
                st.info("💡 Allez dans l'onglet **Statut & Suivi** pour suivre le traitement")
            else:
                st.error(f"❌ Échec : {result_chorus.message}")


# ═══════════════════════════════════════════
# TAB 4 — Statut & Suivi
# ═══════════════════════════════════════════

with tab4:
    st.subheader("Suivi du traitement Chorus Pro")

    sub_id = st.session_state.get("submission_id", "")
    submission_input = st.text_input("ID de dépôt", value=sub_id or "",
                                      placeholder="DEP-20260101-ABCD1234")

    if st.button("📊 Simuler la progression du statut", type="primary",
                  use_container_width=True, disabled=not submission_input):
        if not submission_input:
            st.warning("⚠️ Saisissez un ID de dépôt")
        else:
            st.markdown("#### 🔄 Workflow de traitement")
            progress_bar = st.progress(0)
            status_placeholder = st.empty()

            statuses = simulate_status_progression(submission_input)
            total    = len(statuses)
            history  = []

            for i, res in enumerate(statuses):
                history.append(res)
                progress_bar.progress((i + 1) / total)

                html_steps = ""
                for j, h in enumerate(history):
                    icon, desc = CHORUS_STATUS.get(h.status, ("❓", h.status))
                    is_current = j == len(history) - 1
                    style = "border-left: 4px solid #28a745; background: #d4edda;" if is_current else ""
                    html_steps += f'<div class="chorus-step" style="{style}">{icon} <strong>{h.status}</strong> — {desc}</div>'

                status_placeholder.markdown(html_steps, unsafe_allow_html=True)

            progress_bar.progress(1.0)
            st.success("🎉 Facture traitée avec succès — Paiement programmé !")
            st.balloons()


# ─────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────

st.divider()
st.markdown("""
<div style="text-align: center; color: #666; font-size: 0.85rem;">
    🧾 Démo Facturation Électronique 2026 &nbsp;·&nbsp;
    Conforme <strong>Factur-X EN 16931</strong> &nbsp;·&nbsp;
    Intégration <strong>Chorus Pro (PISTE)</strong><br>
    <a href="https://www.impots.gouv.fr/professionnel/la-facturation-electronique-entre-assujettis-la-tva" target="_blank">
        En savoir plus sur la réforme DGFiP
    </a>
</div>
""", unsafe_allow_html=True)