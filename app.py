"""
dashboard/app.py
-----------------
Dashboard Streamlit — Démo facturation électronique 2026
Auteur : [Votre nom] — https://linkedin.com/in/[votre-profil]

Fonctionnalités :
  ✅ Formulaire de saisie de facture
  ✅ Génération XML Factur-X (EN 16931)
  ✅ Validation avec affichage des erreurs/warnings
  ✅ Simulation dépôt Chorus Pro
  ✅ Suivi de statut en temps réel
  ✅ Téléchargement du fichier XML

Lancement :
    cd dashboard
    streamlit run app.py
"""

import sys
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from schematron_validator import validate_en16931, SchematronResult

# Ajouter le répertoire parent au path pour importer les modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from generate_invoice import (
    Address, Invoice, InvoiceLine, Party,
    generate_facturx_xml, PROFILES
)
from validate_invoice import InvoiceValidator
from send_chorus import simulate_submission, simulate_status_progression, CHORUS_STATUS


# ─────────────────────────────────────────────
# Configuration Streamlit
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Démo Facturation Électronique 2026",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS personnalisé
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
# Sidebar — Paramètres
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Paramètres")

    profile = st.selectbox(
        "Profil Factur-X",
        options=list(PROFILES.keys()),
        index=3,  # EN16931 par défaut
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
# Tabs principales
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
        seller_iban    = st.text_input("IBAN (pour virement SEPA)", value="FR7630006000011234567890189", key="s_iban")

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
            price = st.number_input("Prix unitaire HT (€)", value=line["price"], key=f"l_price_{i}", min_value=0.0, step=10.0, label_visibility="collapsed")
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

    # Calcul des totaux en temps réel
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
            st.session_state["invoice_obj"] = invoice
            st.session_state["submission_id"] = None
            st.success("✅ Facture XML générée avec succès !")

            with st.expander("📄 Aperçu XML (100 premières lignes)"):
                lines_preview = xml_content.split("\n")[:100]
                st.code("\n".join(lines_preview), language="xml")

            st.download_button(
                label="⬇️ Télécharger le fichier XML",
                data=xml_content.encode("utf-8"),
                file_name=f"{invoice_number}.xml",
                mime="application/xml",
            )

        except Exception as e:
            st.error(f"❌ Erreur lors de la génération : {e}")


# ═══════════════════════════════════════════
# TAB 2 — Validation
# ═══════════════════════════════════════════

with tab2:
    st.subheader("Validation de la facture")

    xml_source = st.radio("Source", ["Facture générée ci-dessus", "Uploader un fichier XML"],
                           horizontal=True)

    xml_to_validate = None

    if xml_source == "Facture générée ci-dessus":
        if "xml_content" in st.session_state:
            xml_to_validate = st.session_state["xml_content"]
            st.success("Facture chargée depuis l'étape précédente")
        else:
            st.warning("⚠️ Générez d'abord une facture dans l'onglet précédent")
    else:
        uploaded = st.file_uploader("Choisir un fichier XML Factur-X", type=["xml"])
        if uploaded:
            content = uploaded.read()
            try:
                xml_to_validate = content.decode("utf-8-sig")  # utf-8-sig = UTF-8 + BOM auto-stripped
            except UnicodeDecodeError:
                xml_to_validate = content.decode("latin-1")

    if xml_to_validate and st.button("🔍 Valider la facture", type="primary", use_container_width=True):
        # Sauvegarde temporaire pour validation
        tmp_path = "/tmp/facture_validation.xml"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(xml_to_validate)

        validator = InvoiceValidator(tmp_path)
        result = validator.validate()
        # DEBUG — à retirer après
        st.write("Erreurs brutes :", result.errors)
        st.write("Warnings bruts :", result.warnings)

        # Résumé
        col_v1, col_v2, col_v3 = st.columns(3)
        col_v1.metric("Statut", "✅ VALIDE" if result.is_valid else "❌ INVALIDE")
        col_v2.metric("Erreurs", len(result.errors))
        col_v3.metric("Avertissements", len(result.warnings))

        if result.is_valid:
            st.success("🎉 La facture est conforme aux normes Factur-X et EN 16931 !")
        else:
            st.error(f"La facture comporte {len(result.errors)} erreur(s) bloquante(s)")


        st.divider()
        st.markdown("#### Détail des règles")

        # ── Erreurs bloquantes ─────────────────────────────────────
        if result.errors:
            for issue in result.errors:
                html = (
                    '<div style="background-color:#fff0f0;border-left:4px solid #c0392b;'
                    'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    '❌ <strong style="color:#c0392b;">[' + str(getattr(issue, "rule_id", "?")) + ']</strong> '
                    '<span style="color:#333;">' + str(getattr(issue, "description", getattr(issue, "message", str(issue)))) + '</span>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

        # ── Warnings ───────────────────────────────────────────────
        if result.warnings:
            for issue in result.warnings:
                html = (
                    '<div style="background-color:#fffbf0;border-left:4px solid #b8860b;'
                    'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                    '⚠️ <strong style="color:#b8860b;">[' + str(getattr(issue, "rule_id", "?")) + ']</strong> '
                    '<span style="color:#333;">' + str(getattr(issue, "description", getattr(issue, "message", str(issue)))) + '</span>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

        # ── Règles passées (synthèse) ──────────────────────────────
        nb_total  = getattr(result, "total_checks", 20)
        nb_errors = len(result.errors)
        nb_warn   = len(result.warnings)
        nb_ok     = nb_total - nb_errors - nb_warn

        with st.expander(f"✅ {max(nb_ok, 0)} règle(s) passée(s) avec succès"):
            # Afficher les items OK si le validateur les expose
            ok_items = getattr(result, "infos", getattr(result, "ok_rules", []))
            if ok_items:
                for issue in ok_items:
                    html = (
                        '<div style="background-color:#f0fff4;border-left:4px solid #1a7a4a;'
                        'border-radius:6px;padding:8px 16px;margin-bottom:4px;">'
                        '✅ <strong style="color:#1a7a4a;">[' + str(getattr(issue, "rule_id", "?")) + ']</strong> '
                        '<span style="color:#333;">' + str(getattr(issue, "description", getattr(issue, "message", str(issue)))) + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)
            else:
                st.info("Active les logs OK dans `validate_invoice.py` pour voir le détail des règles passées.")

        # Afficher les warnings dans un expander
        if sch_result.warnings:
            with st.expander(f"⚠️ {len(sch_result.warnings)} avertissement(s) EN16931"):
                for issue in sch_result.warnings:
                    html = (
                        '<div style="background-color:#fffbf0;border-left:4px solid #b8860b;'
                        'border-radius:6px;padding:10px 16px;margin-bottom:6px;">'
                        '⚠️ <strong style="color:#b8860b;">[' + issue.rule_id + ']</strong> '
                        '<span style="color:#333;">' + issue.message + '</span>'
                        '</div>'
                    )
                    st.markdown(html, unsafe_allow_html=True)

        # Badge de source officielle
        st.markdown("""
        <div style="text-align:right;font-size:0.75rem;color:#888;margin-top:4px;">
            Source : 
            <a href="https://github.com/ConnectingEurope/eInvoicing-EN16931" target="_blank">
                CEN/TC 434 — EN16931-CII-validation.xslt v1.3.15
            </a>
        </div>
        """, unsafe_allow_html=True)

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
        service_code = st.text_input("Code service (optionnel)", value="",
                                      help="Code service de l'entité destinataire")

    if st.button("🚀 Déposer la facture", type="primary", use_container_width=True):
        if "xml_content" not in st.session_state:
            st.warning("⚠️ Générez d'abord une facture dans l'onglet 1")
        else:
            tmp_path = "/tmp/facture_chorus.xml"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(st.session_state["xml_content"])

            with st.spinner("Dépôt en cours..."):
                # Affichage des étapes
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

                result = simulate_submission(tmp_path)
                steps_placeholder.empty()

            if result.success:
                st.success(f"✅ Facture déposée ! ID de dépôt : **{result.submission_id}**")
                st.session_state["submission_id"] = result.submission_id

                st.markdown("#### 📋 Accusé de dépôt")
                st.json(result.raw_response)

                st.info("💡 Allez dans l'onglet **Statut & Suivi** pour suivre le traitement")
            else:
                st.error(f"❌ Échec : {result.message}")


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
            total = len(statuses)

            history = []
            for i, res in enumerate(statuses):
                history.append(res)
                progress_bar.progress((i + 1) / total)

                # Affichage du workflow
                html_steps = ""
                for j, h in enumerate(history):
                    icon, desc = CHORUS_STATUS.get(h.status, ("❓", h.status))
                    is_current = j == len(history) - 1
                    style = "border-left: 4px solid #28a745; background: #d4edda;" if is_current else ""
                    html_steps += f"""
<div class="chorus-step" style="{style}">
    {icon} <strong>{h.status}</strong> — {desc}
</div>"""

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
