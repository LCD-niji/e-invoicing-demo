# ═══════════════════════════════════════════
# CONFIGURATION & IMPORTS
# ═══════════════════════════════════════════
import re
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import streamlit as st
import datetime
import json
from pathlib import Path

from generate_invoice    import Invoice, InvoiceLine, Party, Address, PROFILES, generate_facturx_xml
from generate_invoice_ubl import generate_ubl_xml
from generate_pdf        import render_invoice_pdf
from generate_facturx    import build_facturx, extract_xml_from_facturx
from schematron_validator import validate_en16931, detect_syntax
from rules_engine.ai_validator import AiValidator
from convert_legacy      import extract_from_xml, make_sample_legacy_xml, ExtractionResult
from send_chorus         import simulate_submission, simulate_status_progression, CHORUS_STATUS



# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="Facturation Électronique 2026",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Titre ─────────────────────────────────────────────────
st.title("🧾 Démo Facturation Électronique 2026")
st.caption(
    "Outil de démonstration Niji — Génération, validation et conversion "
    "de factures électroniques conformes à la réforme 2026 (EN16931, Factur-X, UBL 2.1)"
)

# ═══════════════════════════════════════════
# CRÉATION DES TABS  ← obligatoire avant tout with tab1/tab2/...
# ═══════════════════════════════════════════

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📝 Générer une facture",
    "✅ Valider",
    "📡 Dépôt Chorus Pro",
    "🔄 Suivi Chorus Pro",
    "🔄 Conversion XML Legacy",
])

# ═══════════════════════════════════════════
# TAB 1 — Génération
# ═══════════════════════════════════════════

with tab1:
    st.subheader("Génération d'une facture électronique")

    # ── Sélecteur syntaxe + profil ────────────────────────
    col_syntax, col_profile = st.columns(2)
    with col_syntax:
        syntax = st.radio(
            "Syntaxe de sortie",
            ["Factur-X (PDF/A-3b + CII)", "CII pur (.xml)", "UBL 2.1 (.xml)"],
            horizontal=False,
            help=(
                "**Factur-X** : PDF lisible + XML CII embarqué — format privilégié B2B France\n\n"
                "**CII** : XML UN/CEFACT pur — interopérabilité maximale\n\n"
                "**UBL 2.1** : XML OASIS — requis pour les échanges Peppol "
                "et les ERPs internationaux (SAP Ariba, Oracle, Basware)"
            )
        )
    with col_profile:
            if "UBL" in syntax:
                st.info("ℹ️ UBL 2.1 utilise le profil **Peppol BIS Billing 3.0** "
                        "(équivalent EN16931)")
                profile = "EN16931"
            else:
                st.info(
                    "📋 Profil **EN16931** appliqué — seul profil conforme à la réforme 2026.\n\n"
                    "MINIMUM / BASIC_WL / BASIC sont acceptés pour l'**archivage** "
                    "mais insuffisants pour l'émission vers Chorus Pro ou une PA."
                )
                profile = "EN16931"
    st.divider()

    # ── Formulaire vendeur ────────────────────────────────
    st.markdown("#### 🏢 Vendeur")
    col1, col2 = st.columns(2)
    with col1:
        seller_name   = st.text_input("Raison sociale",   "Acme Conseil SAS")
        seller_siret  = st.text_input("SIRET",            "12345678901234")
        seller_vat    = st.text_input("N° TVA",           "FR12345678901")
        seller_iban   = st.text_input("IBAN",             "FR7630006000011234567890189")
        seller_bic    = st.text_input("BIC",              "BNPAFRPP")
    with col2:
        seller_street = st.text_input("Rue",              "12 rue de la Paix")
        seller_city   = st.text_input("Ville",            "Paris")
        seller_zip    = st.text_input("Code postal",      "75001")
        seller_country= st.text_input("Pays (ISO)",       "FR")

    st.divider()

    # ── Formulaire acheteur ───────────────────────────────
    st.markdown("#### 🏭 Acheteur")
    # Formulaire acheteur
    col3, col4 = st.columns(2)
    with col3:
        buyer_name    = st.text_input("Raison sociale",  "Dupont Industries SARL", key="buyer_name")
        buyer_siret   = st.text_input("SIRET",           "98765432109876",          key="buyer_siret")
        buyer_vat     = st.text_input("N° TVA",          "FR98765432109",           key="buyer_vat")  # ← AJOUT
        buyer_street  = st.text_input("Rue",             "5 avenue de la Gare",     key="buyer_street")
    with col4:
        buyer_zip     = st.text_input("Code postal",     "69001",                   key="buyer_zip")
        buyer_city    = st.text_input("Ville",           "Lyon",                    key="buyer_city")
        buyer_country = st.text_input("Pays (ISO)",      "FR",                      key="buyer_country")

    st.divider()

    # ── Entête facture ────────────────────────────────────
    st.markdown("#### 📋 Entête")
    col5, col6, col7 = st.columns(3)
    with col5:
        invoice_number = st.text_input("Numéro", "FAC-2026-001")
        import datetime
        issue_date = st.date_input("Date d'émission", datetime.date.today())
    with col6:
        due_date    = st.date_input("Date d'échéance",
                                    datetime.date.today() + datetime.timedelta(days=30))
        notes       = st.text_input("Note / objet", "")
    with col7:
        contract_ref = st.text_input("Réf. contrat (BT-12)", "")
        purchase_order = st.text_input("Bon de commande (BT-13)", "")

    st.divider()

    # ── Lignes de facture ─────────────────────────────────
    st.markdown("#### 📦 Lignes de facture")
    nb_lines = st.number_input("Nombre de lignes", min_value=1, max_value=20,
                               value=2, step=1)
    lines_data = []
    for i in range(int(nb_lines)):
        with st.expander(f"Ligne {i+1}", expanded=(i == 0)):
            lc1, lc2, lc3, lc4 = st.columns([3, 1, 1, 1])
            with lc1:
                desc = st.text_input("Désignation",
                                     f"Prestation {i+1}", key=f"desc_{i}")
            with lc2:
                qty  = st.number_input("Quantité", min_value=0.01,
                                       value=1.0, key=f"qty_{i}")
            with lc3:
                price = st.number_input("Prix unitaire HT",
                                        min_value=0.0, value=100.0,
                                        key=f"price_{i}")
            with lc4:
                vat  = st.selectbox("TVA (%)", [20.0, 10.0, 5.5, 0.0],
                                    key=f"vat_{i}")
            lines_data.append((desc, qty, price, vat))

    st.divider()

    # ── Bouton génération ─────────────────────────────────
    if st.button("🔧 Générer la facture", type="primary", use_container_width=True):
        try:
            invoice = Invoice(
                number=invoice_number,
                issue_date=issue_date,
                due_date=due_date,
                notes=notes,
                contract_ref=contract_ref,
                purchase_order=purchase_order,
                profile=profile,
                seller=Party(
                    name=seller_name, siret=seller_siret,
                    vat_number=seller_vat, iban=seller_iban, bic=seller_bic,
                    address=Address(
                        street=seller_street,
                        city=seller_city,
                        postal_code=seller_zip,
                        country_code=seller_country,  # ← country → country_code
                    ),
                ),
                buyer=Party(
                    name=buyer_name,
                    siret=buyer_siret,
                    vat_number=buyer_vat,     # ← AJOUT
                    address=Address(
                        street=buyer_street,
                        city=buyer_city,
                        postal_code=buyer_zip,
                        country_code=buyer_country,
                    ),
                ),
                lines=[
                    InvoiceLine(
                        description=d, quantity=Decimal(str(q)),
                        unit_price=Decimal(str(p)), vat_rate=Decimal(str(v))
                    )
                    for d, q, p, v in lines_data
                ],
            )

            # ── UBL 2.1 ───────────────────────────────────
            if "UBL" in syntax:
                xml_content = generate_ubl_xml(invoice)
                st.session_state["xml_content"] = xml_content
                st.session_state["xml_syntax"]  = "UBL"
                st.session_state["invoice_obj"] = invoice
                st.success("✅ Facture UBL 2.1 générée (Peppol BIS Billing 3.0) !")
                st.download_button(
                    label="⬇️ Télécharger UBL 2.1 (.xml)",
                    data=xml_content.encode("utf-8"),
                    file_name=f"{invoice_number}_ubl21.xml",
                    mime="application/xml",
                )
                with st.expander("📄 Aperçu XML UBL 2.1"):
                    st.code(xml_content[:2000], language="xml")

            # ── CII pur ────────────────────────────────────
            elif "CII pur" in syntax:
                xml_content = generate_facturx_xml(invoice)
                st.session_state["xml_content"] = xml_content
                st.session_state["xml_syntax"]  = "CII"
                st.session_state["invoice_obj"] = invoice
                st.success("✅ Facture CII générée !")
                st.download_button(
                    label="⬇️ Télécharger CII (.xml)",
                    data=xml_content.encode("utf-8"),
                    file_name=f"{invoice_number}_cii.xml",
                    mime="application/xml",
                )

            # ── Factur-X (CII + PDF à générer séparément) ─
            else:
                xml_content = generate_facturx_xml(invoice)
                st.session_state["xml_content"] = xml_content
                st.session_state["xml_syntax"]  = "CII"
                st.session_state["invoice_obj"] = invoice
                st.success("✅ XML CII Factur-X généré !")
                st.download_button(
                    label="⬇️ Télécharger XML CII (.xml)",
                    data=xml_content.encode("utf-8"),
                    file_name=f"{invoice_number}.xml",
                    mime="application/xml",
                )

        except Exception as e:
            st.error(f"❌ Erreur génération : {e}")
            import traceback
            st.code(traceback.format_exc())

    # ── Bouton PDF — HORS du bouton génération ────────────
    # (Streamlit interdit les boutons imbriqués)
    if (
        st.session_state.get("xml_syntax") == "CII"
        and "invoice_obj" in st.session_state
        and "Factur-X" in syntax
    ):
        if st.button("📄 Générer le Factur-X complet (PDF/A-3b)",
                     use_container_width=True):
            with st.spinner("Génération PDF/A-3b en cours..."):
                fx_bytes = build_facturx(
                    st.session_state["invoice_obj"],
                    st.session_state["xml_content"]
                )
            st.download_button(
                label="⬇️ Télécharger Factur-X (.pdf)",
                data=fx_bytes,
                file_name=f"{st.session_state['invoice_obj'].number}_facturx.pdf",
                mime="application/pdf",
            )

# ═══════════════════════════════════════════
# TAB 2 — Validation
# ═══════════════════════════════════════════

with tab2:
    st.subheader("Validation de la facture électronique")

    # ── Sélecteur source ──────────────────────────────────
    xml_source = st.radio(
        "Source",
        ["Facture générée ci-dessus",
         "Uploader un fichier XML (CII ou UBL)",
         "Uploader un Factur-X PDF"],
        horizontal=True
    )

    xml_to_validate = None
    syntax_detect   = st.session_state.get("xml_syntax", "CII")

    # ── Source 1 : session ────────────────────────────────
    if xml_source == "Facture générée ci-dessus":
        if "xml_content" in st.session_state:
            xml_to_validate = st.session_state["xml_content"]
            syntax_detect   = st.session_state.get("xml_syntax", "CII")
            badge = "UBL 2.1" if syntax_detect == "UBL" else "CII Factur-X"
            st.success(f"✅ Facture chargée depuis Tab 1 — Format : **{badge}**")
        else:
            st.warning("⚠️ Générez d'abord une facture dans l'onglet 1")

    # ── Source 2 : upload XML ──────────────────────────────
    elif xml_source == "Uploader un fichier XML (CII ou UBL)":
        uploaded = st.file_uploader(
            "Choisir un fichier XML (.xml)",
            type=["xml"],
            help="Formats acceptés : CII Factur-X (CrossIndustryInvoice) et UBL 2.1 (Invoice)"
        )
        if uploaded:
            content = uploaded.read()
            try:
                xml_to_validate = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                xml_to_validate = content.decode("latin-1")

            # Auto-détection syntaxe
            syntax_detect = detect_syntax(xml_to_validate)
            badge = "UBL 2.1" if syntax_detect == "UBL" else "CII"
            st.info(f"📄 Format détecté : **{badge}**")

            if "CrossIndustryInvoice" not in xml_to_validate and \
               "oasis" not in xml_to_validate and \
               "Invoice-2" not in xml_to_validate:
                st.error(
                    "❌ Format non reconnu (ni CII ni UBL). "
                    "Utilisez le Tab 🔄 Conversion pour convertir un XML legacy."
                )
                xml_to_validate = None

    # ── Source 3 : upload PDF Factur-X ────────────────────
    elif xml_source == "Uploader un Factur-X PDF":
        st.info("Uploadez un PDF **Factur-X** contenant un XML CII embarqué.")
        uploaded_pdf = st.file_uploader(
            "Choisir un fichier Factur-X (.pdf)",
            type=["pdf"],
            key="pdf_upload"
        )
        if uploaded_pdf:
            pdf_bytes = uploaded_pdf.read()
            try:
                xml_to_validate, detected_profile = extract_xml_from_facturx(pdf_bytes)
                if "<facture>" in xml_to_validate or \
                   ("CrossIndustryInvoice" not in xml_to_validate and \
                    "oasis" not in xml_to_validate):
                    st.error(
                        "❌ Le XML embarqué est au **format propriétaire** — "
                        "pas conforme à la réforme 2026."
                    )
                    xml_to_validate = None
                else:
                    syntax_detect = detect_syntax(xml_to_validate)
                    st.success(
                        f"✅ XML extrait du PDF — "
                        f"Profil : **{detected_profile}** — "
                        f"Syntaxe : **{syntax_detect}**"
                    )
                    with st.expander("📄 Aperçu XML extrait"):
                        st.code(xml_to_validate[:1000], language="xml")
                    st.download_button(
                        label="⬇️ Télécharger le XML extrait",
                        data=xml_to_validate.encode("utf-8"),
                        file_name=uploaded_pdf.name.replace(".pdf", "_extracted.xml"),
                        mime="application/xml",
                    )
            except ValueError as e:
                st.error(f"❌ {e}")
                xml_to_validate = None

    # ── Feedback format ───────────────────────────────────
    if xml_to_validate:
        if syntax_detect == "UBL":
            st.info("📋 Validation UBL 2.1 : "
                    "Schematron CEN EN16931-UBL + règles sémantiques Annexe 7 (via mapper BT)")
        else:
            st.info("📋 Validation CII : "
                    "Schematron CEN EN16931-CII + règles DGFiP Annexe 7")

    # ─────────────────────────────────────────────────────
    # BOUTON VALIDER
    # ─────────────────────────────────────────────────────
    result     = None
    sch_result = None
    ai_result  = None

    if xml_to_validate and st.button(
        "🔍 Valider la facture", type="primary", use_container_width=True
    ):
        tmp_path = "/tmp/facture_validation.xml"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(xml_to_validate)

        # ══════════════════════════════════════════════════
        # CONTRÔLE 1 — Norme européenne EN16931
        # ══════════════════════════════════════════════════
        st.divider()
        label_c1 = (
            "#### 🇪🇺 Contrôle 1 — Norme européenne EN 16931 · UBL 2.1 (Peppol BIS Billing 3.0)"
            if syntax_detect == "UBL"
            else "#### 🇪🇺 Contrôle 1 — Norme européenne EN 16931 (CEN/TC 434 · CII)"
        )
        st.markdown(label_c1)

        if syntax_detect == "UBL":
            st.caption(
                "La France a adopté la norme européenne EN 16931 comme socle commun. "
                "Pour UBL 2.1, le moteur applique les règles BR-* du XSLT officiel CEN "
                "adapté à la syntaxe OASIS — c'est le format natif du réseau **Peppol**, "
                "protocole d'interopérabilité inter-plateformes reconnu par la réforme 2026."
            )
        else:
            st.caption(
                "La France a adopté la norme européenne EN 16931 comme socle commun. "
                "Ce contrôle applique les ~120 règles BR-* officielles du CEN "
                "(Comité Européen de Normalisation) : cohérence arithmétique, "
                "codelists ISO, règles TVA. Un document conforme EN 16931 est "
                "interopérable dans toute l'Union Européenne."
            )

        with st.spinner(f"Application des règles Schematron CEN ({syntax_detect})..."):
            sch_result = validate_en16931(tmp_path, syntax=syntax_detect)

        # ── Référentiel BR-* complet (dynamique) ──────────
        ALL_BR_RULES = {
            "BR-01":"Identifiant de spécification (BT-24) obligatoire",
            "BR-02":"Numéro de facture (BT-1) obligatoire",
            "BR-03":"Date d'émission (BT-2) obligatoire",
            "BR-04":"TypeCode (BT-3) obligatoire",
            "BR-05":"Devise (BT-5) obligatoire",
            "BR-06":"Nom du vendeur (BT-27) obligatoire",
            "BR-07":"Nom de l'acheteur (BT-44) obligatoire",
            "BR-08":"Adresse vendeur — code pays obligatoire",
            "BR-09":"Code pays vendeur — ISO 3166-1 alpha-2",
            "BR-10":"Adresse acheteur — code pays obligatoire",
            "BR-16":"Au moins une ligne de facture obligatoire",
            "BR-21":"Identifiant ligne (BT-126) obligatoire",
            "BR-22":"Quantité facturée (BT-129) obligatoire",
            "BR-23":"Unité de mesure (BT-130) obligatoire",
            "BR-24":"Montant net ligne (BT-131) obligatoire",
            "BR-25":"Nom article (BT-153) obligatoire",
            "BR-26":"Code TVA ligne (BT-151) obligatoire",
            "BR-27":"Prix unitaire net (BT-146) obligatoire",
            "BR-31":"Vendeur : SIRET ou TVA intracommunautaire obligatoire",
            "BR-36":"Adresse vendeur — ville (BT-37) obligatoire",
            "BR-37":"Adresse vendeur — code postal (BT-38) obligatoire",
            "BR-43":"BT-110 = somme des BT-117",
            "BR-47":"Si BT-81=30 ou 58 : BT-84 (IBAN) obligatoire",
            "BR-CO-3":"Montant net ligne = quantité × prix unitaire",
            "BR-CO-9":"BT-109 = somme des BT-116",
            "BR-CO-10":"BT-112 = BT-109 + BT-110",
            "BR-CO-11":"BT-115 = BT-112 − BT-113",
            "BR-CO-13":"BT-110 = somme des BT-117",
            "BR-CO-15":"Cohérence arithmétique HT + TVA = TTC",
            "BR-CO-16":"DuePayableAmount cohérent",
            "BR-AE-1":"Autoliquidation — mention BT-120/121 obligatoire",
            "BR-AE-4":"Autoliquidation — TVA calculée = 0",
            "BR-E-1":"Exonération — BT-120 ou BT-121 obligatoire",
            "BR-E-4":"Exonération — TVA calculée = 0",
            "BR-G-1":"Export — BT-120 ou BT-121 obligatoire",
            "BR-IC-1":"Intracommunautaire — BT-120 ou BT-121 obligatoire",
            "BR-IC-11":"Intracommunautaire — BT-55 (pays acheteur) obligatoire",
            "BR-IC-12":"Intracommunautaire — BT-40 (pays vendeur) obligatoire",
            "BR-O-1":"Hors périmètre — BT-120 ou BT-121 obligatoire",
            "BR-S-1":"Taux standard — BT-119 (RateApplicablePercent) obligatoire",
            "BR-S-4":"Taux standard — BT-117 = BT-116 × BT-119 / 100",
            "BR-Z-1":"Taux zéro — BT-119 obligatoire",
            "BR-CL-01":"TypeCode dans codelist UNTDID 1001",
            "BR-CL-04":"Devise — ISO 4217",
            "BR-CL-06":"Code pays — ISO 3166-1 alpha-2",
            "BR-CL-07":"Catégorie TVA — UNCL5305",
            "BR-CL-10":"Moyen de paiement — UNTDID 4461",
            "BR-CL-14":"Unité de mesure — UN/ECE Rec 20 ou Rec 21",
            "BR-DEC-01":"BT-116 (BasisAmount) — max 2 décimales",
            "BR-DEC-02":"BT-117 (CalculatedAmount) — max 2 décimales",
            "BR-DEC-09":"BT-131 (LineTotalAmount) — max 2 décimales",
            "BR-DEC-12":"BT-112 (GrandTotalAmount) — max 2 décimales",
            "BR-DEC-13":"BT-115 (DuePayableAmount) — max 2 décimales",
        }

        failed_ids   = {i.rule_id for i in sch_result.errors + sch_result.warnings}
        passed_rules = {k: v for k, v in ALL_BR_RULES.items() if k not in failed_ids}
        nb_all       = len(ALL_BR_RULES)

        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Statut EN16931",
                      "✅ CONFORME" if sch_result.is_valid else "❌ NON CONFORME")
        col_s2.metric("Référentiel BR-*",   nb_all)
        col_s3.metric("Erreurs",            len(sch_result.errors))
        col_s4.metric("Warnings",           len(sch_result.warnings))

        if sch_result.is_valid:
            st.success("🎉 Conforme à la norme européenne EN 16931 !")
            with st.expander(
                f"✅ {len(passed_rules)} règles BR-* conformes "
                f"(moteur XSLT CEN {syntax_detect} v1.3.15)"
            ):
                for rule_id, desc in passed_rules.items():
                    st.markdown(
                        f'<div style="background:#f0fff4;border-left:4px solid #1a7a4a;'
                        f'border-radius:6px;padding:8px 16px;margin-bottom:4px;">'
                        f'✅ <strong style="color:#1a7a4a;">[{rule_id}]</strong> '
                        f'<span style="color:#333;font-size:.9rem;">{desc}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                st.caption(
                    f"{len(passed_rules)} règles sans anomalie sur {nb_all} du référentiel. "
                    f"Syntaxe validée : {syntax_detect}. "
                    "Source : CEN/TC 434 v1.3.15"
                )
        else:
            for issue in sch_result.errors:
                st.markdown(
                    f'<div style="background:#fff0f0;border-left:4px solid #c0392b;'
                    f'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    f'❌ <strong style="color:#c0392b;">[{issue.rule_id}]</strong> '
                    f'<span style="color:#333;">{issue.message}</span>'
                    f'<br><small style="color:#888;font-size:.75rem;">📍 {issue.location}</small>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        if sch_result.warnings:
            with st.expander(f"⚠️ {len(sch_result.warnings)} avertissement(s) EN16931"):
                for issue in sch_result.warnings:
                    st.markdown(
                        f'<div style="background:#fffbf0;border-left:4px solid #b8860b;'
                        f'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                        f'⚠️ <strong style="color:#b8860b;">[{issue.rule_id}]</strong> '
                        f'<span style="color:#333;">{issue.message}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

        # ══════════════════════════════════════════════════
        # CONTRÔLE 2 — Annexe 7 DGFiP
        # ══════════════════════════════════════════════════
        st.divider()
        st.markdown("#### 📋 Contrôle 2 — Règles de gestion DGFiP (Annexe 7 v1.8)")
        st.caption(
            "La DGFiP a publié 235 règles de gestion spécifiques à la France "
            "(Annexe 7, octobre 2025). Elles couvrent les particularités fiscales françaises : "
            "SIRET obligatoire, régimes de TVA FR, mentions légales, avoirs et rectificatives. "
            "Le moteur est **syntaxe-agnostique** : les valeurs BT sont extraites du XML "
            f"{'via le mapper UBL → BT' if syntax_detect == 'UBL' else 'via XPath CII'} "
            "puis évaluées sur le modèle sémantique EN16931."
        )

        rules_path = Path("rules_engine/rules.json")
        if not rules_path.exists():
            st.warning("⚠️ rules_engine/rules.json introuvable")
        else:
            with st.spinner("Évaluation des règles Annexe 7 DGFiP..."):
                ai_val    = AiValidator(rules_path)

                # ── Mapper UBL → BT si nécessaire ─────────
                if syntax_detect == "UBL":
                    from rules_engine.ubl_mapper import extract_bt_values
                    bt_values = extract_bt_values(tmp_path)
                    ai_result = ai_val.validate(
                        tmp_path,
                        schematron_ran=(sch_result is not None),
                        bt_override=bt_values
                    )
                else:
                    ai_result = ai_val.validate(
                        tmp_path,
                        schematron_ran=(sch_result is not None)
                    )

            # FIX BUG 1 : on utilise total_f1_rules exposé par AiValidator
            # (compte uniquement les règles f1=True — les f1=False sont
            #  dans le JSON pour documentation mais jamais traitées)
            nb_tested     = len(ai_result.errors) + len(ai_result.warnings) + len(ai_result.infos)
            nb_xslt       = len(ai_result.skipped_xslt)
            nb_condition  = len(ai_result.skipped_condition)
            nb_hors_scope = len(ai_result.skipped_out_of_scope)
            total_rules   = ai_val.total_f1_rules

            # 7 colonnes : chaque categorie a sa propre metrique
            # Invariant visible : total = XSLT + testees + hors_portee + N/A
            col_a1, col_a2, col_a3, col_a4, col_a5, col_a6, col_a7 = st.columns(7)
            col_a1.metric(
                "Statut Annexe 7",
                "✅ CONFORME" if ai_result.is_valid else "❌ NON CONFORME"
            )
            col_a2.metric(
                "Regles f1",
                total_rules,
                help=("Regles DGFiP marquees f1=True (Flux F1 — emission B2B). "
                      "Les regles f1=False sont dans le JSON a titre documentaire "
                      "et ne sont jamais evaluees.")
            )
            col_a3.metric(
                "Ctrl 1 (XSLT)",
                nb_xslt,
                help=("Regles deja verifiees par le Controle 1 (Schematron CEN EN16931 v1.3.15). "
                      "Elles ne sont pas re-evaluees ici pour eviter les doublons. "
                      "Lancez tag_rules_schematron.py pour activer ce compteur.")
            )
            col_a4.metric(
                "Testees ici",
                nb_tested,
                help=("Regles evaluees sur cette facture : presence des BT, "
                      "format (SIRET, TVA, dates), codelists (TypeCode, CategoryCode, CountryID).")
            )
            col_a5.metric(
                "Erreurs",
                len(ai_result.errors)
            )
            col_a6.metric(
                "Hors portee",
                nb_hors_scope,
                help=("Regles necessitant PPF/annuaire DGFiP ou dont le BT "
                      "n'est pas mappable localement (BG-*, BT-8, BT-21, BT-80, BT-111...). "
                      "Verifiees par la PDP lors du depot reel.")
            )
            col_a7.metric(
                "N/A facture",
                nb_condition,
                help=("Regles conditionnelles non applicables a CETTE facture. "
                      "Ex : BR-55 si TypeCode=380 (pas un avoir), "
                      "BR-IC-11 si categorie TVA != K (pas intracom.). "
                      "Elles s'activent dans les scenarios concernes.")
            )
            

            for issue in ai_result.errors:
                st.markdown(
                    f'<div style="background:#fff0f0;border-left:4px solid #c0392b;'
                    f'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    f'❌ <strong style="color:#c0392b;">[{issue.rule_id}]</strong> '
                    f'<span style="color:#333;">{issue.message}</span>'
                    f'<br><small style="color:#888;">BT : {issue.bt} · {issue.source}</small>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            for issue in ai_result.warnings:
                st.markdown(
                    f'<div style="background:#fffbf0;border-left:4px solid #b8860b;'
                    f'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    f'⚠️ <strong style="color:#b8860b;">[{issue.rule_id}]</strong> '
                    f'<span style="color:#333;">{issue.message}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            if ai_result.infos:
                with st.expander(f"✅ {len(ai_result.infos)} règles Annexe 7 conformes"):
                    for issue in ai_result.infos:
                        st.markdown(
                            f'<div style="background:#f0fff4;border-left:4px solid #1a7a4a;'
                            f'border-radius:6px;padding:8px 16px;margin-bottom:4px;">'
                            f'✅ <strong style="color:#1a7a4a;">[{issue.rule_id}]</strong> '
                            f'<span style="color:#333;font-size:.9rem;">{issue.message}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

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
                        st.markdown(f"— **[{issue.rule_id}]** {issue.message}")

            # Caption = equation : verifiable de tete (ex: 118 = 0 + 58 + 47 + 13)
            st.caption(
                f"{total_rules} regles f1=True"
                f" = {nb_xslt} Ctrl1 (XSLT)"
                f" + {nb_tested} testees ici ({len(ai_result.errors)} erreur(s))"
                f" + {nb_hors_scope} hors portee"
                f" + {nb_condition} N/A."
                f" Syntaxe : {syntax_detect}"
                f" {'(UBL -> BT)' if syntax_detect == 'UBL' else '(XPath CII)'}. "
                "Source : Annexe 7 DGFiP v1.8 (31/10/2025)."
            )
            

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


# ═══════════════════════════════════════════
# TAB 5 — Conversion XML Legacy → Factur-X
# ═══════════════════════════════════════════

with tab5:
    st.subheader("Conversion XML Legacy → Factur-X CII")
    st.caption(
        "Vous avez une facture dans un format XML propriétaire (SAP, Sage, Cegid, EBP…) ? "
        "Uploadez-la ici : le système détecte automatiquement les champs par heuristique, "
        "vous permet de corriger les données, puis génère un XML Factur-X CII conforme à la réforme 2026."
    )

    col_upload, col_sample = st.columns([3, 1])
    with col_upload:
        legacy_file = st.file_uploader(
            "Charger un XML legacy",
            type=["xml"],
            key="legacy_xml_upload",
            help="Format propriétaire : SAP, Sage, Cegid, EBP, ou tout XML de facturation interne"
        )
    with col_sample:
        st.markdown("&nbsp;")
        if st.button("📄 Charger un exemple", use_container_width=True, key="load_sample_legacy"):
            st.session_state["legacy_xml_content"] = make_sample_legacy_xml()

    # Source XML : upload ou exemple
    legacy_xml_content = None
    if legacy_file:
        raw = legacy_file.read()
        try:
            legacy_xml_content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            legacy_xml_content = raw.decode("latin-1")
        st.session_state["legacy_xml_content"] = legacy_xml_content
    elif "legacy_xml_content" in st.session_state:
        legacy_xml_content = st.session_state["legacy_xml_content"]

    if legacy_xml_content:
        with st.expander("📄 XML source (aperçu)", expanded=False):
            st.code("\n".join(legacy_xml_content.split("\n")[:60]), language="xml")

        # Extraction heuristique
        try:
            extracted = extract_from_xml(legacy_xml_content)
        except ValueError as e:
            st.error(f"❌ {e}")
            extracted = None

        if extracted:
            # Rapport d'extraction
            nb_matched = sum(1 for v in [
                extracted.invoice_number, extracted.issue_date,
                extracted.seller_name, extracted.seller_siret,
                extracted.buyer_name,
            ] if v)
            nb_lines   = len(extracted.lines)

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric("Champs détectés", len(extracted.matched_fields))
            col_r2.metric("Lignes détectées", nb_lines)
            col_r3.metric("Champs non mappés", len(extracted.unmatched_tags))

            if extracted.matched_fields:
                with st.expander("🔍 Correspondances détectées", expanded=False):
                    for field_key, xpath in extracted.matched_fields.items():
                        st.markdown(f"- `{field_key}` ← `{xpath}`")
            if extracted.unmatched_tags:
                with st.expander(f"⚠️ {len(extracted.unmatched_tags)} tags non reconnus", expanded=False):
                    st.caption("Ces balises n'ont pas pu être mappées automatiquement.")
                    st.write(", ".join(f"`{t}`" for t in sorted(extracted.unmatched_tags)))

            st.divider()
            st.markdown("#### ✏️ Vérifiez et complétez les données extraites")
            st.caption("Les champs pré-remplis proviennent du XML source. Corrigez si nécessaire avant de générer le Factur-X.")

            with st.form("legacy_conversion_form"):
                st.markdown("**Entête de facture**")
                fc1, fc2, fc3 = st.columns(3)
                conv_number   = fc1.text_input("Numéro de facture *", value=extracted.invoice_number)
                conv_date_str = fc2.text_input("Date d'émission * (YYYY-MM-DD)", value=extracted.issue_date)
                conv_due_str  = fc3.text_input("Date d'échéance * (YYYY-MM-DD)", value=extracted.due_date)

                st.markdown("**Vendeur (émetteur)**")
                fv1, fv2, fv3 = st.columns(3)
                conv_seller_name   = fv1.text_input("Raison sociale *", value=extracted.seller_name, key="cs_name")
                conv_seller_siret  = fv2.text_input("SIRET (14 chiffres) *", value=extracted.seller_siret, key="cs_siret")
                conv_seller_vat    = fv3.text_input("N° TVA intracommunautaire *", value=extracted.seller_vat, key="cs_vat")
                fv4, fv5, fv6 = st.columns(3)
                conv_seller_street = fv4.text_input("Adresse", value=extracted.seller_street, key="cs_street")
                conv_seller_postal = fv5.text_input("Code postal", value=extracted.seller_postal, key="cs_postal")
                conv_seller_city   = fv6.text_input("Ville", value=extracted.seller_city, key="cs_city")
                fi1, fi2 = st.columns(2)
                conv_seller_iban   = fi1.text_input("IBAN", value=extracted.seller_iban, key="cs_iban")
                conv_seller_bic    = fi2.text_input("BIC", value=extracted.seller_bic, key="cs_bic")

                st.markdown("**Acheteur (destinataire)**")
                fa1, fa2, fa3 = st.columns(3)
                conv_buyer_name    = fa1.text_input("Raison sociale *", value=extracted.buyer_name, key="cb_name")
                conv_buyer_siret   = fa2.text_input("SIRET (14 chiffres) *", value=extracted.buyer_siret, key="cb_siret")
                conv_buyer_vat     = fa3.text_input("N° TVA intracommunautaire", value=extracted.buyer_vat, key="cb_vat")
                fa4, fa5, fa6 = st.columns(3)
                conv_buyer_street  = fa4.text_input("Adresse", value=extracted.buyer_street, key="cb_street")
                conv_buyer_postal  = fa5.text_input("Code postal", value=extracted.buyer_postal, key="cb_postal")
                conv_buyer_city    = fa6.text_input("Ville", value=extracted.buyer_city, key="cb_city")

                st.markdown("**Lignes de facture**")
                if not extracted.lines:
                    st.warning("⚠️ Aucune ligne détectée — ajoutez au moins une ligne manuellement.")
                    extracted.lines = [type("L", (), {"description":"", "quantity":"1", "unit_price":"0.00", "vat_rate":"20"})()]

                conv_lines = []
                for i, ln in enumerate(extracted.lines):
                    ll1, ll2, ll3, ll4 = st.columns([4, 1, 2, 1])
                    desc  = ll1.text_input(f"Description #{i+1}", value=ln.description, key=f"cl_desc_{i}")
                    qty   = ll2.text_input(f"Qté #{i+1}",         value=ln.quantity,    key=f"cl_qty_{i}")
                    price = ll3.text_input(f"Prix HT #{i+1}",     value=ln.unit_price,  key=f"cl_price_{i}")
                    vat   = ll4.text_input(f"TVA% #{i+1}",        value=ln.vat_rate,    key=f"cl_vat_{i}")
                    conv_lines.append((desc, qty, price, vat))

                submitted_conv = st.form_submit_button(
                    "⚙️ Générer le XML Factur-X CII", type="primary", use_container_width=True
                )

            if submitted_conv:
                errors_conv = []
                if not conv_number:
                    errors_conv.append("Numéro de facture manquant")
                if not conv_seller_siret or len(re.sub(r"\D", "", conv_seller_siret)) != 14:
                    errors_conv.append("SIRET vendeur invalide (14 chiffres requis)")
                if not conv_buyer_siret or len(re.sub(r"\D", "", conv_buyer_siret)) != 14:
                    errors_conv.append("SIRET acheteur invalide (14 chiffres requis)")

                try:
                    conv_issue_date = date.fromisoformat(conv_date_str)
                except ValueError:
                    errors_conv.append(f"Date d'émission invalide : '{conv_date_str}' (format attendu YYYY-MM-DD)")
                    conv_issue_date = date.today()
                try:
                    conv_due_date = date.fromisoformat(conv_due_str) if conv_due_str else conv_issue_date + timedelta(days=30)
                except ValueError:
                    conv_due_date = conv_issue_date + timedelta(days=30)

                if errors_conv:
                    for err in errors_conv:
                        st.error(f"❌ {err}")
                else:
                    try:
                        from generate_invoice import Address, Invoice, InvoiceLine, Party

                        def _make_addr(street, postal, city):
                            return Address(
                                street=street or "—",
                                city=city or "—",
                                postal_code=postal or "00000",
                                country_code="FR",
                            )

                        seller_conv = Party(
                            name=conv_seller_name,
                            siret=re.sub(r"\D", "", conv_seller_siret),
                            vat_number=conv_seller_vat or f"FR00{re.sub(r'D','',conv_seller_siret)[:9]}",
                            address=_make_addr(conv_seller_street, conv_seller_postal, conv_seller_city),
                            iban=conv_seller_iban or None,
                            bic=conv_seller_bic or None,
                        )
                        buyer_conv = Party(
                            name=conv_buyer_name,
                            siret=re.sub(r"\D", "", conv_buyer_siret),
                            vat_number=conv_buyer_vat or f"FR00{re.sub(r'D','',conv_buyer_siret)[:9]}",
                            address=_make_addr(conv_buyer_street, conv_buyer_postal, conv_buyer_city),
                        )

                        invoice_lines_conv = []
                        for desc, qty, price, vat in conv_lines:
                            if not desc and not price:
                                continue
                            try:
                                invoice_lines_conv.append(InvoiceLine(
                                    description=desc or "—",
                                    quantity=Decimal(qty.replace(",", ".") or "1"),
                                    unit_price=Decimal(price.replace(",", ".") or "0"),
                                    vat_rate=Decimal(vat.replace(",", ".") or "20"),
                                ))
                            except InvalidOperation:
                                st.warning(f"⚠️ Ligne ignorée (valeurs numériques invalides) : {desc}")

                        if not invoice_lines_conv:
                            st.error("❌ Aucune ligne valide — ajoutez au moins une ligne.")
                        else:
                            invoice_conv = Invoice(
                                number=conv_number,
                                issue_date=conv_issue_date,
                                due_date=conv_due_date,
                                seller=seller_conv,
                                buyer=buyer_conv,
                                lines=invoice_lines_conv,
                                currency="EUR",
                                profile="EN16931",
                            )
                            xml_conv = generate_facturx_xml(invoice_conv)
                            st.success("✅ XML Factur-X CII généré avec succès !")

                            with st.expander("📄 Aperçu XML généré", expanded=True):
                                st.code("\n".join(xml_conv.split("\n")[:60]), language="xml")

                            st.download_button(
                                label="⬇️ Télécharger le XML Factur-X",
                                data=xml_conv.encode("utf-8"),
                                file_name=f"{conv_number}_facturx.xml",
                                mime="application/xml",
                            )

                            # Proposer de valider directement
                            if st.button("✅ Valider ce XML (aller à l'onglet Validation)", key="conv_to_validate"):
                                st.session_state["xml_content"] = xml_conv
                                st.info("XML chargé en session — allez dans l'onglet **Validation** et choisissez 'Facture générée ci-dessus'.")

                    except Exception as e:
                        st.error(f"❌ Erreur lors de la génération : {e}")


# ─────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────
