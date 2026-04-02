# ═══════════════════════════════════════════
# CONFIGURATION & IMPORTS
# ═══════════════════════════════════════════
import hashlib
import html
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
from convert_legacy      import (
    extract_from_xml,
    get_active_bt_list,
    make_sample_legacy_xml,
    ExtractionResult,
    _parse_date as _legacy_parse_date,
)
from send_chorus         import simulate_submission, simulate_status_progression, CHORUS_STATUS
from invoice_payload     import build_invoice_from_form, get_preloaded_examples, get_demo_scenarios
from validation_explainability import explain_issue_plain_language, remediation_guidance
from xml_import_helpers import decode_uploaded_xml, parse_xml_safely
from pdf_legacy_analyzer import analyze_plain_pdf


def _normalize_siren_bt(raw: str) -> str:
    """SIREN BT-30/BT-47 (9 chiffres). Un SIRET (14 chiffres) saisi est ramené aux 9 premiers chiffres."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 14:
        return d[:9]
    return d


LEGACY_BT_BUCKETS = [
    ("📋 Facture & références", {"BT-1", "BT-2", "BT-3", "BT-5", "BT-9", "BT-10", "BT-12", "BT-13", "BT-22"}),
    ("🏢 Vendeur", {"BT-27", "BT-30", "BT-31", "BT-35", "BT-37", "BT-38", "BT-40", "BT-84", "BT-86"}),
    ("🏭 Acheteur", {"BT-44", "BT-47", "BT-48", "BT-50", "BT-53", "BT-54", "BT-55"}),
    ("📦 Lignes & TVA", {"BT-126", "BT-129", "BT-146", "BT-151", "BT-153"}),
]


def _legacy_xml_fingerprint(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def _legacy_reset_overrides_if_new_xml(fp: str) -> None:
    if st.session_state.get("legacy_xml_fingerprint") != fp:
        st.session_state.legacy_xml_fingerprint = fp
        st.session_state.legacy_bt_overrides = {}
        st.session_state.legacy_tile_dismissed = []
        st.session_state.legacy_tile_used = []


def _legacy_form_value(bt: str, extracted: ExtractionResult, property_fallback: str = "") -> str:
    """Overrides session > mapped[bt] > propriété métier (ex. invoice_number)."""
    ov = st.session_state.get("legacy_bt_overrides", {}).get(bt)
    if ov is not None and str(ov).strip() != "":
        return str(ov)
    mapped = extracted.mapped.get(bt, "")
    if mapped:
        return mapped
    return property_fallback


def _legacy_unmatched_fields(extracted: ExtractionResult) -> dict[str, str]:
    """Balises non mappées avec valeur (tuiles). Compat si ancien convert_legacy sans cet attribut."""
    uf = getattr(extracted, "unmatched_fields", None)
    if isinstance(uf, dict):
        return uf
    return {}


def _group_legacy_bt_entries(bt_entries: list[dict]) -> list[tuple[str, list[dict]]]:
    by_code = {x["bt"]: x for x in bt_entries}
    out: list[tuple[str, list[dict]]] = []
    seen: set[str] = set()
    for title, bset in LEGACY_BT_BUCKETS:
        chunk = [by_code[bt] for bt in sorted(bset) if bt in by_code]
        if chunk:
            out.append((title, chunk))
            seen |= {x["bt"] for x in chunk}
    rest = [by_code[bt] for bt in sorted(by_code.keys()) if bt not in seen]
    if rest:
        out.append(("Autres champs actifs", rest))
    return out


def _legacy_visible_tag_pool(uf: dict[str, str]) -> list[str]:
    """Balises encore affichées dans la zone principale (pas masquées ni déjà affectées à un BT)."""
    dismissed = set(st.session_state.get("legacy_tile_dismissed") or [])
    used = set(st.session_state.get("legacy_tile_used") or [])
    return sorted(t for t in uf if t not in dismissed and t not in used)


def _legacy_sanitize_map_selects(visible: list[str]) -> None:
    """Évite une valeur de selectbox hors options quand une tuile disparaît."""
    allowed = {"—", *visible}
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("legacy_map_tgt_"):
            if st.session_state.get(k) not in allowed:
                st.session_state[k] = "—"


def _apply_legacy_tile_mapping(unmatched_fields: dict[str, str], bt_entries: list[dict]) -> None:
    """Lit les selectbox de cibles et met à jour legacy_bt_overrides + balises « utilisées »."""
    base = dict(st.session_state.get("legacy_bt_overrides", {}))
    newly_used: list[str] = []
    for bt_ent in bt_entries:
        bt = bt_ent["bt"]
        sel = st.session_state.get(f"legacy_map_tgt_{bt}", "—")
        if not sel or sel == "—":
            base.pop(bt, None)
            continue
        raw = unmatched_fields.get(sel, "").strip()
        if not raw:
            continue
        if bt in ("BT-2", "BT-9"):
            raw = _legacy_parse_date(raw)
        if bt in ("BT-30", "BT-47"):
            raw = _normalize_siren_bt(raw)
        base[bt] = raw
        newly_used.append(sel)
    st.session_state.legacy_bt_overrides = base
    prev = list(st.session_state.get("legacy_tile_used") or [])
    st.session_state.legacy_tile_used = sorted(set(prev) | set(newly_used))


# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="Facturation Électronique 2026",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* ═══════════════════════════════════════
       RESET & BASE
    ═══════════════════════════════════════ */
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }

    /* ═══════════════════════════════════════
       HEADER PRINCIPAL (masque le header Streamlit par défaut)
    ═══════════════════════════════════════ */
    [data-testid="stHeader"] {
        background: linear-gradient(90deg, #005FAD 0%, #0077CC 100%);
        height: 3px;
    }

    /* ═══════════════════════════════════════
       HERO BANNER
    ═══════════════════════════════════════ */
    .hero-banner {
        background: linear-gradient(135deg, #003D73 0%, #005FAD 60%, #0095D9 100%);
        border-radius: 14px;
        padding: 2.2rem 2.5rem;
        margin-bottom: 1.8rem;
        color: white;
        box-shadow: 0 4px 24px rgba(0, 95, 173, 0.18);
    }
    .hero-banner h1 {
        font-size: 1.9rem;
        font-weight: 700;
        margin: 0 0 0.4rem 0;
        color: white !important;
        letter-spacing: -0.02em;
    }
    .hero-banner p {
        font-size: 1.0rem;
        opacity: 0.88;
        margin: 0;
        line-height: 1.6;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(255,255,255,0.18);
        border: 1px solid rgba(255,255,255,0.35);
        border-radius: 20px;
        padding: 0.2rem 0.8rem;
        font-size: 0.78rem;
        font-weight: 600;
        margin-top: 0.9rem;
        letter-spacing: 0.04em;
    }

    /* ═══════════════════════════════════════
       SECTION HEADER (bandeau parcours par tab)
    ═══════════════════════════════════════ */
    .section-header {
        background: #F0F4FA;
        border-left: 4px solid #005FAD;
        border-radius: 0 10px 10px 0;
        padding: 0.85rem 1.2rem;
        margin: 0.5rem 0 1.4rem 0;
    }
    .section-header .step-label {
        font-size: 0.73rem;
        font-weight: 700;
        color: #005FAD;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.15rem;
    }
    .section-header .step-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #1A1A2E;
        margin: 0 0 0.15rem 0;
    }
    .section-header .step-desc {
        font-size: 0.85rem;
        color: #555;
        margin: 0;
    }

    /* ═══════════════════════════════════════
       TABS
    ═══════════════════════════════════════ */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 2px solid #E2E8F0;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.55rem 1.1rem;
        font-weight: 600;
        font-size: 0.88rem;
        color: #555;
        background: transparent;
        transition: background 0.15s, color 0.15s;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        color: #005FAD !important;
        border-bottom: 2px solid #005FAD !important;
        background: #EBF3FB !important;
    }

    /* ═══════════════════════════════════════
       BOUTONS PRIMAIRES
    ═══════════════════════════════════════ */
    [data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #005FAD, #0077CC) !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.01em !important;
        box-shadow: 0 2px 8px rgba(0, 95, 173, 0.22) !important;
        transition: box-shadow 0.2s, transform 0.1s !important;
    }
    [data-testid="baseButton-primary"]:hover {
        box-shadow: 0 4px 16px rgba(0, 95, 173, 0.35) !important;
        transform: translateY(-1px) !important;
    }

    /* ═══════════════════════════════════════
       BOUTONS SECONDAIRES
    ═══════════════════════════════════════ */
    [data-testid="baseButton-secondary"] {
        border: 1.5px solid #005FAD !important;
        color: #005FAD !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }

    /* ═══════════════════════════════════════
       MÉTRIQUES (st.metric)
    ═══════════════════════════════════════ */
    [data-testid="metric-container"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 0.9rem 1rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }
    [data-testid="metric-container"] [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        color: #6B7280 !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        color: #1A1A2E !important;
    }

    /* ═══════════════════════════════════════
       ALERTS : SUCCESS / WARNING / ERROR / INFO
    ═══════════════════════════════════════ */
    [data-testid="stSuccess"] {
        background: #ECFDF5;
        border-left: 4px solid #10B981;
        border-radius: 0 8px 8px 0;
        color: #065F46;
    }
    [data-testid="stWarning"] {
        background: #FFFBEB;
        border-left: 4px solid #F59E0B;
        border-radius: 0 8px 8px 0;
        color: #78350F;
    }
    [data-testid="stError"] {
        background: #FEF2F2;
        border-left: 4px solid #EF4444;
        border-radius: 0 8px 8px 0;
        color: #7F1D1D;
    }
    [data-testid="stInfo"] {
        background: #EFF6FF;
        border-left: 4px solid #3B82F6;
        border-radius: 0 8px 8px 0;
        color: #1E3A8A;
    }

    /* ═══════════════════════════════════════
       CARTES DE RÈGLES (validation)
    ═══════════════════════════════════════ */
    .rule-card-ok {
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        border-radius: 8px;
        padding: 0.5rem 0.9rem;
        margin: 0.25rem 0;
        font-size: 0.87rem;
        color: #064E3B;
    }
    .rule-card-error {
        background: #FEF2F2;
        border: 1px solid #FECACA;
        border-radius: 8px;
        padding: 0.5rem 0.9rem;
        margin: 0.25rem 0;
        font-size: 0.87rem;
        color: #7F1D1D;
    }
    .rule-card-warning {
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        border-radius: 8px;
        padding: 0.5rem 0.9rem;
        margin: 0.25rem 0;
        font-size: 0.87rem;
        color: #78350F;
    }

    /* ═══════════════════════════════════════
       TIMELINE STATUT CHORUS PRO
    ═══════════════════════════════════════ */
    .chorus-step {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        padding: 0.7rem 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
        font-weight: 500;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        transition: background 0.2s;
    }
    .chorus-step.active {
        background: #EBF3FB;
        border-color: #005FAD;
        border-left: 4px solid #005FAD;
        color: #003D73;
        font-weight: 700;
    }
    .chorus-step.done {
        background: #ECFDF5;
        border-color: #A7F3D0;
        color: #065F46;
    }

    /* ═══════════════════════════════════════
       EXPANDERS
    ═══════════════════════════════════════ */
    [data-testid="stExpander"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        font-weight: 600;
        color: #1A1A2E;
        padding: 0.6rem 0.8rem;
    }

    /* ═══════════════════════════════════════
       INPUTS & SELECTBOX
    ═══════════════════════════════════════ */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-baseweb="select"] {
        border-radius: 7px !important;
        border-color: #CBD5E1 !important;
        font-size: 0.9rem !important;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stNumberInput"] input:focus {
        border-color: #005FAD !important;
        box-shadow: 0 0 0 2px rgba(0,95,173,0.15) !important;
    }

    /* ═══════════════════════════════════════
       LEGACY XML — tuiles sources / cibles
       ═══════════════════════════════════════ */
    .legacy-tile-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 0.5rem 0 1.2rem 0;
    }
    .legacy-tile-source {
        flex: 1 1 160px;
        max-width: 240px;
        border: 1px solid #D7E3F0;
        border-radius: 10px;
        padding: 10px 12px;
        background: linear-gradient(160deg, #F8FAFC 0%, #FFFFFF 100%);
        box-shadow: 0 1px 3px rgba(0,60,120,0.06);
    }
    .legacy-tile-tag {
        font-family: ui-monospace, Consolas, monospace;
        font-size: 0.78rem;
        font-weight: 700;
        color: #005FAD;
        word-break: break-all;
    }
    .legacy-tile-val {
        font-size: 0.8rem;
        color: #475569;
        margin-top: 6px;
        display: block;
        line-height: 1.35;
    }
    .legacy-tile-target-h {
        font-size: 0.72rem;
        font-weight: 600;
        color: #1B4332;
        margin-bottom: 4px;
    }

    /* ═══════════════════════════════════════
       FOOTER
       ═══════════════════════════════════════ */
    .app-footer {
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
        font-size: 0.78rem;
        color: #9CA3AF;
        border-top: 1px solid #E2E8F0;
        margin-top: 3rem;
    }
    .app-footer strong {
        color: #005FAD;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-banner">
        <h1>🧾 Facturation Électronique 2026</h1>
        <p>Outil de démonstration Niji — Générez, validez et convertissez des factures conformes<br>
        à la réforme 2026 : <strong>EN 16931 · Factur-X · UBL 2.1 · Chorus Pro</strong></p>
        <span class="hero-badge">🔵 DÉMO NIJI — Réforme obligatoire · 1er sept. 2026</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════
# CRÉATION DES TABS  ← obligatoire avant tout with tab1/tab2/...
# ═══════════════════════════════════════════
# Masque les onglets Dépôt / Suivi Chorus Pro (le code des onglets reste ci-dessous, non exécuté si False).
SHOW_CHORUS_UI = False
# Numéro d’étape affiché pour l’import legacy (cohérent avec la présence des onglets Chorus).
LEGACY_STEP_LABEL = "Parcours 5" if SHOW_CHORUS_UI else "Parcours 3"

if SHOW_CHORUS_UI:
    tab_audit, tab1, tab2, tab3, tab4, tab_legacy = st.tabs([
        "🔍 Audit PDF",
        "📝 Générer une facture",
        "✅ Valider",
        "📡 Dépôt Chorus Pro",
        "🔄 Suivi Chorus Pro",
        "🔄 Conversion XML Legacy",
    ])
else:
    tab_audit, tab1, tab2, tab_legacy = st.tabs([
        "🔍 Audit PDF",
        "📝 Générer une facture",
        "✅ Valider",
        "🔄 Conversion XML Legacy",
    ])

# ═══════════════════════════════════════════
# TAB 1 — Génération
# ═══════════════════════════════════════════

with tab1:
    st.markdown(
        """
        <div class="section-header">
          <div class="step-label">Étape 1</div>
          <div class="step-title">Génération guidée</div>
          <p class="step-desc">Saisissez vos données métier et produisez un document prêt à validation.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Génération d'une facture électronique")
    st.caption(
        "Objectif : produire une facture structurée conforme (Factur-X, CII ou UBL) "
        "à partir de vos données métier."
    )
    st.info(
        "Conseil d'utilisation : renseignez d'abord les identifiants légaux (SIREN BT-30/BT-47, TVA), "
        "puis les lignes de facturation. En cas d'information manquante, l'outil génère quand même "
        "le document et signale les points à compléter."
    )
    _scenario_override = st.session_state.get("scenario_form_data")
    preloaded_example = (
        _scenario_override
        if _scenario_override
        else get_preloaded_examples()["PME Services FR"]
    )

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
        seller_name   = st.text_input("Raison sociale",   preloaded_example["seller_name"])
        seller_siret  = st.text_input("SIREN vendeur (9 chiffres, BT-30)", preloaded_example["seller_siret"])
        seller_vat    = st.text_input("N° TVA",           preloaded_example["seller_vat"])
        seller_iban   = st.text_input("IBAN",             preloaded_example["seller_iban"])
        seller_bic    = st.text_input("BIC",              preloaded_example["seller_bic"])
    with col2:
        seller_street = st.text_input("Rue",              preloaded_example["seller_street"])
        seller_city   = st.text_input("Ville",            preloaded_example["seller_city"])
        seller_zip    = st.text_input("Code postal",      preloaded_example["seller_zip"])
        seller_country= st.text_input("Pays (ISO)",       preloaded_example["seller_country"])

    st.divider()

    # ── Formulaire acheteur ───────────────────────────────
    st.markdown("#### 🏭 Acheteur")
    # Formulaire acheteur
    col3, col4 = st.columns(2)
    with col3:
        buyer_name    = st.text_input("Raison sociale",  preloaded_example["buyer_name"], key="buyer_name")
        buyer_siret   = st.text_input("SIREN acheteur (9 chiffres, BT-47)", preloaded_example["buyer_siret"], key="buyer_siret")
        buyer_vat     = st.text_input("N° TVA",          preloaded_example["buyer_vat"], key="buyer_vat")
        buyer_street  = st.text_input("Rue",             preloaded_example["buyer_street"], key="buyer_street")
    with col4:
        buyer_zip     = st.text_input("Code postal",     preloaded_example["buyer_zip"], key="buyer_zip")
        buyer_city    = st.text_input("Ville",           preloaded_example["buyer_city"], key="buyer_city")
        buyer_country = st.text_input("Pays (ISO)",      preloaded_example["buyer_country"], key="buyer_country")

    st.divider()

    # ── Entête facture ────────────────────────────────────
    st.markdown("#### 📋 Entête")
    col5, col6, col7 = st.columns(3)
    with col5:
        invoice_number = st.text_input("Numéro", preloaded_example["invoice_number"])
        import datetime
        issue_date = st.date_input("Date d'émission", datetime.date.today())
    with col6:
        due_date    = st.date_input("Date d'échéance",
                                    datetime.date.today() + datetime.timedelta(days=30))
        notes       = st.text_input("Note / objet", preloaded_example["notes"])
    with col7:
        contract_ref = st.text_input("Réf. contrat (BT-12)", preloaded_example["contract_ref"])
        purchase_order = st.text_input("Bon de commande (BT-13)", preloaded_example["purchase_order"])

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
            form_data = {
                "seller_name": seller_name,
                "seller_siret": seller_siret,
                "seller_vat": seller_vat,
                "seller_iban": seller_iban,
                "seller_bic": seller_bic,
                "seller_street": seller_street,
                "seller_city": seller_city,
                "seller_zip": seller_zip,
                "seller_country": seller_country,
                "buyer_name": buyer_name,
                "buyer_siret": buyer_siret,
                "buyer_vat": buyer_vat,
                "buyer_street": buyer_street,
                "buyer_zip": buyer_zip,
                "buyer_city": buyer_city,
                "buyer_country": buyer_country,
                "invoice_number": invoice_number,
                "notes": notes,
                "contract_ref": contract_ref,
                "purchase_order": purchase_order,
            }
            invoice, missing_messages = build_invoice_from_form(
                form_data=form_data,
                lines_data=lines_data,
                issue_date=issue_date,
                due_date=due_date,
                profile=profile,
            )
            if missing_messages:
                for msg in missing_messages:
                    st.warning(f"⚠️ {msg}")

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
    st.markdown(
        """
        <div class="section-header">
          <div class="step-label">Étape 2</div>
          <div class="step-title">Validation unifiée</div>
          <p class="step-desc">Obtenez un statut global, des explications lisibles et des actions de correction.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Validation de la facture électronique")
    st.caption(
        "Cette étape contrôle la conformité sur 2 niveaux : "
        "norme européenne EN16931 puis règles DGFiP (Annexe 7)."
    )
    st.info(
        "Bonnes pratiques : validez d'abord sur un document généré dans l'onglet précédent, "
        "puis utilisez l'upload XML/PDF pour tester vos flux réels."
    )

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
    import_mapping_issue_count = 0

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
            xml_to_validate, _ = decode_uploaded_xml(content)

            xml_is_valid, parse_error_message = parse_xml_safely(xml_to_validate)
            if not xml_is_valid:
                st.error(f"❌ Erreur de parsing XML : {parse_error_message}")
                xml_to_validate = None

            if xml_to_validate:
                # Auto-détection syntaxe
                syntax_detect = detect_syntax(xml_to_validate)
                badge = "UBL 2.1" if syntax_detect == "UBL" else "CII"
                st.info(f"📄 Format détecté : **{badge}**")
                import_mapping_issue_count = int(st.session_state.get("legacy_unmapped_count", 0))

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
        st.session_state["last_validation_summary"] = None
        st.session_state["last_validation_blocking_count"] = None
        st.session_state["last_validation_trigger"] = time.time()
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
            "BR-31":"Vendeur : identifiant légal (SIREN) ou TVA intracommunautaire obligatoire",
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
            "SIREN (BT-30/BT-47) obligatoire, régimes de TVA FR, mentions légales, avoirs et rectificatives. "
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
                      "format (SIREN BT-30/BT-47, TVA, dates), codelists (TypeCode, CategoryCode, CountryID).")
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

        # ══════════════════════════════════════════════════
        # SYNTHÈSE UNIFIÉE (create/import même sémantique)
        # ══════════════════════════════════════════════════
        unified_blocking = []
        unified_warning = []
        unified_info = []

        for issue in (sch_result.errors if sch_result else []):
            unified_blocking.append(("EN16931", issue.rule_id, issue.message))
        for issue in (sch_result.warnings if sch_result else []):
            unified_warning.append(("EN16931", issue.rule_id, issue.message))

        if ai_result:
            for issue in ai_result.errors:
                unified_blocking.append(("Annexe 7", issue.rule_id, issue.message))
            for issue in ai_result.warnings:
                unified_warning.append(("Annexe 7", issue.rule_id, issue.message))
            for issue in ai_result.infos:
                unified_info.append(("Annexe 7", issue.rule_id, issue.message))

        st.divider()
        st.markdown("#### 🧭 Statut global")
        global_status = "✅ VALIDE" if len(unified_blocking) == 0 else "❌ CORRECTIONS REQUISES"
        st.metric("Statut global", global_status)
        st.caption(
            "Un clic sur 'Valider la facture' lance une exécution complète "
            "(EN16931 + Annexe 7) et met à jour le résumé global."
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Blocking", len(unified_blocking), help="Erreurs bloquantes à corriger")
        c2.metric("Warning", len(unified_warning), help="Anomalies non bloquantes à surveiller")
        c3.metric("Info", len(unified_info), help="Informations ou conformités détectées")

        previous_blocking = st.session_state.get("last_validation_blocking_count")
        if previous_blocking is not None:
            if len(unified_blocking) < previous_blocking:
                st.success(
                    f"Amelioration detectee: blocking {previous_blocking} -> {len(unified_blocking)}."
                )
            elif len(unified_blocking) > previous_blocking:
                st.warning(
                    f"Nouvelle execution: blocking {previous_blocking} -> {len(unified_blocking)} (degradation)."
                )
            else:
                st.info(
                    f"Nouvelle execution: blocking inchange ({len(unified_blocking)})."
                )

        if unified_blocking:
            with st.expander(f"❌ {len(unified_blocking)} blocking"):
                for source, rule_id, message in unified_blocking:
                    st.markdown(f"- **[{source}] [{rule_id}]** {message}")
                    st.caption(f"Explication: {explain_issue_plain_language(rule_id, message, 'blocking')}")
                    st.info(f"Action recommandee: {remediation_guidance(rule_id, message)}")
        if unified_warning:
            with st.expander(f"⚠️ {len(unified_warning)} warning"):
                for source, rule_id, message in unified_warning:
                    st.markdown(f"- **[{source}] [{rule_id}]** {message}")
                    st.caption(f"Explication: {explain_issue_plain_language(rule_id, message, 'warning')}")
        if unified_info:
            with st.expander(f"ℹ️ {len(unified_info)} info"):
                for source, rule_id, message in unified_info:
                    st.markdown(f"- **[{source}] [{rule_id}]** {message}")
                    st.caption(f"Explication: {explain_issue_plain_language(rule_id, message, 'info')}")

        if not unified_blocking:
            st.success("Aucun point bloquant détecté. Vous pouvez poursuivre le flux sans correction obligatoire.")
        else:
            st.warning("Des points bloquants sont présents. Corrigez-les puis relancez la validation.")

        if xml_source == "Uploader un fichier XML (CII ou UBL)":
            st.markdown("#### 🔀 Séparation des catégories d'issues")
            st.info(
                f"Issues de mapping (import): {import_mapping_issue_count} | "
                f"Issues de validation (EN16931 + Annexe 7): {len(unified_blocking) + len(unified_warning)}"
            )

        st.session_state["last_validation_blocking_count"] = len(unified_blocking)
        st.session_state["last_validation_summary"] = {
            "blocking": len(unified_blocking),
            "warning": len(unified_warning),
            "info": len(unified_info),
            "timestamp": st.session_state["last_validation_trigger"],
        }


# ═══════════════════════════════════════════
# TAB AUDIT PDF — Analyse PDF classique
# ═══════════════════════════════════════════
with tab_audit:
    st.markdown(
        """
        <div class="section-header">
            <div class="step-label">Étape 0 — Analyse</div>
            <div class="step-title">Audit de votre facture PDF</div>
            <p class="step-desc">
                Déposez un PDF reçu aujourd’hui (par email, portail, etc.). L’outil
                identifie rapidement les points susceptibles d’empêcher une conformité
                à la réforme 2026 et propose des actions de correction.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.info(
        "Cette analyse est **heuristique** (lecture du texte du PDF). "
        "Elle n’est pas une validation réglementaire officielle, mais un guide pour corriger en priorité "
        "avant de générer un format structuré (Factur-X, UBL 2.1 ou CII)."
    )

    uploaded_pdf_audit = st.file_uploader(
        "Déposez votre facture PDF ici",
        type=["pdf"],
        key="audit_pdf_upload",
        help="PDF classique (visuel), ou Factur-X (PDF/A-3 avec XML CII embarqué).",
    )

    if uploaded_pdf_audit:
        pdf_bytes_audit = uploaded_pdf_audit.read()

        with st.spinner("Analyse de la facture en cours..."):
            result = analyze_plain_pdf(pdf_bytes_audit)

        # ── Cas Factur-X détecté ──────────────────────────────────────────
        if result.is_facturx:
            st.success(
                "Le document est détecté comme un **Factur-X** (XML CII embarqué présent). "
                "Le format attendu par la réforme est donc déjà couvert. "
                "Passez à l’onglet **Valider** pour contrôler les règles métier."
            )

        # ── PDF classique ─────────────────────────────────────────────────
        else:
            # Score visuel
            score = result.score
            score_color = (
                "#10B981" if score >= 70 else "#F59E0B" if score >= 40 else "#EF4444"
            )
            score_label = (
                "Peu risquée" if score >= 70 else "Risquée" if score >= 40 else "Non conforme 2026"
            )

            col_score, col_meta = st.columns([1, 2])

            with col_score:
                st.markdown(
                    f"""
                    <div style="
                        background: #FEF2F2;
                        border: 2px solid {score_color};
                        border-radius: 14px;
                        padding: 1.5rem;
                        text-align: center;
                    ">
                        <div style="font-size: 0.8rem; font-weight: 700; color: #6B7280;
                                    text-transform: uppercase; letter-spacing: 0.06em;">
                            Score de conformité
                        </div>
                        <div style="font-size: 3.2rem; font-weight: 800; color: {score_color};
                                    line-height: 1.1; margin: 0.4rem 0;">
                            {score}/100
                        </div>
                        <div style="font-size: 0.9rem; font-weight: 600; color: {score_color};">
                            {score_label}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with col_meta:
                st.metric("Type de document", "PDF classique (non structuré)")
                st.metric("Pages", result.page_count)
                col_b, col_w = st.columns(2)
                col_b.metric("🔴 Erreurs bloquantes", result.blocking_count)
                col_w.metric("🟡 Avertissements", result.warning_count)

            st.error(
                "Ce PDF classique risque d’être rejeté à partir du 1er septembre 2026. "
                f"Il présente **{result.blocking_count} point(s) bloquant(s)** à corriger avant conversion."
            )

            st.divider()

            # ── Rapport détaillé ──────────────────────────────────────────
            st.markdown("#### Rapport de non-conformité (heuristique)")

            blocking_issues = [i for i in result.issues if i.category == "bloquant"]
            warning_issues = [i for i in result.issues if i.category == "warning"]

            if blocking_issues:
                st.markdown(
                    "**Points bloquants — à corriger en priorité avant le 1er sept. 2026**"
                )
                for issue in blocking_issues:
                    with st.expander(f"[{issue.code}] {issue.label}", expanded=True):
                        st.markdown(f"**Pourquoi c’est bloquant :**  \n{issue.explanation}")
                        st.info(f"Action corrective : {issue.fix}")

            if warning_issues:
                st.markdown("**Points à surveiller — non bloquants mais risqués**")
                for issue in warning_issues:
                    with st.expander(f"[{issue.code}] {issue.label}"):
                        st.markdown(f"**Pourquoi c’est risqué :**  \n{issue.explanation}")
                        st.info(f"Recommandation : {issue.fix}")

            # ── Champs détectés ───────────────────────────────────────────
            if result.detected:
                with st.expander("🔍 Données détectées dans votre PDF", expanded=False):
                    st.caption(
                        "Chiffres et libellés détectés dans le texte. "
                        "La présence visuelle ne suffit pas à garantir la conformité : "
                        "le contrôle réglementaire requiert un format structuré."
                    )
                    for k, v in result.detected.items():
                        label = {
                            "siret_candidats": "SIRET(s) détecté(s)",
                            "tva_candidats": "N° TVA détecté(s)",
                            "invoice_number": "Numéro de facture",
                            "dates_candidates": "Date(s) détectée(s)",
                            "montants_candidats": "Montant(s) détecté(s)",
                        }.get(k, k)
                        st.markdown(f"- **{label}** : `{v}`")

            st.divider()

            # ── CTA ───────────────────────────────────────────────────────
            st.markdown(
                """
                <div style="
                    background: linear-gradient(135deg, #003D73 0%, #005FAD 100%);
                    border-radius: 12px;
                    padding: 1.5rem 2rem;
                    color: white;
                    text-align: center;
                ">
                    <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem;">
                        Prochaine étape : générer un format structuré conforme 2026
                    </div>
                    <div style="font-size: 0.9rem; opacity: 0.88;">
                        Utilisez l’onglet <strong>Générer une facture</strong> pour créer un Factur-X, ou "
                        "l’onglet <strong>Conversion XML Legacy</strong> si vous partez d’un XML existant.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── Scénarios d'erreur préchargés ─────────────────────────────────────
    st.divider()
    st.markdown("#### Scénarios de démonstration (optionnel)")
    st.caption("Pas de PDF sous la main ? Choisissez un scénario pour tester le parcours utilisateur.")

    scenarios = get_demo_scenarios()
    selected_scenario = st.selectbox(
        "Choisir un scénario",
        options=list(scenarios.keys()),
        key="demo_scenario_select",
    )

    if selected_scenario:
        scenario = scenarios[selected_scenario]
        tag = scenario.get("_demo_tag", "")
        desc = scenario.get("_demo_description", "")
        lines = scenario.get("_demo_lines", [("Prestation", 1.0, 100.0, 20.0)])

        if tag == "ok":
            st.success(f"Scénario nominal — {desc}")
        else:
            st.error(f"Scénario d'erreur — {desc}")

        if st.button(
            "Charger ce scénario dans l’onglet Générer",
            type="primary",
            key="load_scenario",
        ):
            # Stocker dans session_state pour pré-remplir Tab 1
            st.session_state["scenario_form_data"] = {
                k: v for k, v in scenario.items() if not k.startswith("_")
            }
            st.session_state["scenario_lines"] = lines
            st.info(
                "Scénario chargé. Allez dans **Générer une facture**, cliquez **Générer**, puis **Valider**."
            )


# ═══════════════════════════════════════════
# TAB 3 — Dépôt Chorus Pro
# ═══════════════════════════════════════════

if SHOW_CHORUS_UI:
    with tab3:
        st.markdown(
            """
            <div class="section-header">
              <div class="step-label">Parcours 3</div>
              <div class="step-title">Dépôt (simulation)</div>
              <p class="step-desc">Illustrez le flux cible vers Chorus Pro sans appel réseau réel.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
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
        st.markdown(
            """
            <div class="section-header">
              <div class="step-label">Parcours 4</div>
              <div class="step-title">Suivi de traitement</div>
              <p class="step-desc">Visualisez la progression des statuts pour faciliter la narration en démo.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
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

with tab_legacy:
    st.markdown(
        f"""
        <div class="section-header">
          <div class="step-label">Étape Annexe</div>
          <div class="step-title">Import XML legacy</div>
          <p class="step-desc">Mappez, normalisez et corrigez vos données externes en toute transparence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Conversion XML Legacy → Factur-X CII")
    st.caption(
        "Objectif : convertir un XML métier existant vers un format structuré "
        "conforme à la réforme 2026."
    )
    st.info(
        "Parcours recommandé : importer le XML, vérifier les correspondances détectées, "
        "corriger les champs clés si nécessaire, puis générer et valider le résultat."
    )
    st.caption(
        "Formats d'entrée typiques : SAP, Sage, Cegid, EBP, ou tout XML interne. "
        "Le mapping est heuristique : vérifiez systématiquement les données détectées."
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
        legacy_xml_valid, legacy_parse_message = parse_xml_safely(legacy_xml_content)
        if not legacy_xml_valid:
            st.error(f"❌ Erreur de parsing XML legacy : {legacy_parse_message}")
            st.stop()
        try:
            extracted = extract_from_xml(legacy_xml_content)
        except ValueError as e:
            st.error(f"❌ {e}")
            extracted = None

        if extracted:
            _legacy_reset_overrides_if_new_xml(_legacy_xml_fingerprint(legacy_xml_content))
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

            uf = _legacy_unmatched_fields(extracted)
            if uf:
                visible = _legacy_visible_tag_pool(uf)
                _legacy_sanitize_map_selects(visible)

                st.markdown("#### 🧩 Cartographie manuelle — balises non reconnues")
                st.caption(
                    "**Tuiles** : chaque carte est une balise du XML. Utilisez **Masquer** pour la retirer "
                    "de la zone (ignore, ou traité ailleurs) — la liste se clarifie. "
                    "Associez une balise à un **champ BT** ci-dessous puis **Appliquer** : la balise utilisée "
                    "sort aussi de la zone. Les retraits sont réversibles dans **Balises retirées**."
                )
                _fp_short = (st.session_state.get("legacy_xml_fingerprint") or "x")[:10]
                st.caption(
                    f"**{len(visible)}** tuile(s) dans la zone principale · **{len(uf)}** balise(s) au total"
                )

                if visible:
                    st.markdown("**📥 Zone « À traiter »**")
                    for row_start in range(0, len(visible), 3):
                        row_tags = visible[row_start : row_start + 3]
                        cols = st.columns(3)
                        for ci, tag in enumerate(row_tags):
                            val = uf[tag]
                            preview = val[:90] + ("…" if len(val) > 90 else "")
                            with cols[ci]:
                                with st.container(border=True):
                                    st.markdown(f"**`{tag}`**")
                                    st.caption(preview)
                                    _hid = hashlib.md5(tag.encode("utf-8")).hexdigest()[:12]

                                    def _hide_tag(t=tag):
                                        lst = list(st.session_state.get("legacy_tile_dismissed") or [])
                                        if t not in lst:
                                            lst.append(t)
                                        st.session_state.legacy_tile_dismissed = lst

                                    st.button(
                                        "✕ Masquer de la zone",
                                        key=f"lg_hide_{_fp_short}_{_hid}",
                                        help="Retire la tuile pour y voir plus clair (réversible ci-dessous).",
                                        on_click=_hide_tag,
                                        use_container_width=True,
                                    )
                else:
                    st.info(
                        "Aucune tuile dans la zone principale : tout est masqué ou déjà affecté à un champ BT. "
                        "Réaffichez des balises depuis la section ci-dessous si besoin."
                    )

                pool_off = set(st.session_state.get("legacy_tile_dismissed") or []) | set(
                    st.session_state.get("legacy_tile_used") or []
                )
                if pool_off:
                    with st.expander(
                        f"📦 Balises retirées de la zone ({len(pool_off)}) — réafficher",
                        expanded=False,
                    ):
                        st.caption(
                            "Cochez **Réafficher** pour remettre une balise dans « À traiter » "
                            "(elle redevient disponible dans les listes cibles)."
                        )
                        for tag in sorted(pool_off):
                            if tag not in uf:
                                continue
                            v = uf[tag]
                            pv = v[:60] + ("…" if len(v) > 60 else "")
                            c_a, c_b = st.columns([4, 1])
                            with c_a:
                                st.markdown(f"`{tag}` · {pv}")
                            with c_b:

                                def _restore_tag(t=tag):
                                    st.session_state.legacy_tile_dismissed = [
                                        x
                                        for x in (st.session_state.get("legacy_tile_dismissed") or [])
                                        if x != t
                                    ]
                                    st.session_state.legacy_tile_used = [
                                        x
                                        for x in (st.session_state.get("legacy_tile_used") or [])
                                        if x != t
                                    ]

                                _rid = hashlib.md5(tag.encode("utf-8")).hexdigest()[:12]
                                st.button(
                                    "↩ Réafficher",
                                    key=f"lg_rst_{_fp_short}_{_rid}",
                                    on_click=_restore_tag,
                                    use_container_width=True,
                                )

                bt_entries = get_active_bt_list()

                def _label_unmapped_option(x: str) -> str:
                    if x == "—":
                        return "— (aucune)"
                    v = uf[x]
                    return f"{x} — {v[:40]}…" if len(v) > 40 else f"{x} — {v}"

                with st.form("legacy_tile_mapping_form"):
                    st.markdown("**⬇️ Champs cibles — associer une balise source**")
                    _opts_pool = ["—"] + visible
                    for title, chunk in _group_legacy_bt_entries(bt_entries):
                        st.markdown(f"**{title}**")
                        for i in range(0, len(chunk), 3):
                            row = chunk[i : i + 3]
                            cols = st.columns(3)
                            for j, bt_ent in enumerate(row):
                                bt = bt_ent["bt"]
                                lbl = bt_ent["label"]
                                with cols[j]:
                                    st.markdown(
                                        f'<div class="legacy-tile-target-h">{html.escape(bt)} · {html.escape(lbl)}</div>',
                                        unsafe_allow_html=True,
                                    )
                                    st.selectbox(
                                        f"source_{bt}",
                                        _opts_pool,
                                        format_func=_label_unmapped_option,
                                        key=f"legacy_map_tgt_{bt}",
                                        label_visibility="collapsed",
                                    )
                    submitted_map = st.form_submit_button(
                        "Appliquer vers les champs BT",
                        use_container_width=True,
                    )
                if submitted_map:
                    _apply_legacy_tile_mapping(uf, bt_entries)
                    st.success("Associations appliquées — le formulaire ci-dessous reprend ces valeurs.")

            if extracted.unmatched_tags:
                with st.expander(f"⚠️ {len(extracted.unmatched_tags)} tags non reconnus (liste)", expanded=False):
                    st.caption("Balises non mappées automatiquement — utilisez la cartographie ci-dessus si disponible.")
                    st.write(", ".join(f"`{t}`" for t in sorted(extracted.unmatched_tags)))
            elif not uf:
                st.success("✅ Tous les tags détectés ont été mappés automatiquement.")
            st.session_state["legacy_unmapped_count"] = len(extracted.unmatched_tags)

            normalized_payload = extracted.normalized_payload
            with st.expander("🧩 Payload normalisé (canonique)", expanded=False):
                st.caption(
                    "Vue normalisée utilisée par le pipeline interne (mapping -> normalisation -> validation)."
                )
                st.json(normalized_payload)
                st.download_button(
                    label="⬇️ Télécharger le payload normalisé (.json)",
                    data=json.dumps(normalized_payload, ensure_ascii=False, indent=2),
                    file_name="normalized_payload.json",
                    mime="application/json",
                    key="download_normalized_payload",
                )

            st.divider()
            st.markdown("#### ✏️ Vérifiez et complétez les données extraites")
            st.caption("Les champs pré-remplis proviennent du XML source. Corrigez si nécessaire avant de générer le Factur-X.")

            with st.form("legacy_conversion_form"):
                st.markdown("**Entête de facture**")
                fc1, fc2, fc3 = st.columns(3)
                conv_number   = fc1.text_input(
                    "Numéro de facture *",
                    value=_legacy_form_value("BT-1", extracted, extracted.invoice_number),
                )
                conv_date_str = fc2.text_input(
                    "Date d'émission * (YYYY-MM-DD)",
                    value=_legacy_form_value("BT-2", extracted, extracted.issue_date),
                )
                conv_due_str  = fc3.text_input(
                    "Date d'échéance * (YYYY-MM-DD)",
                    value=_legacy_form_value("BT-9", extracted, extracted.due_date),
                )

                st.markdown("**Vendeur (émetteur)**")
                fv1, fv2, fv3 = st.columns(3)
                conv_seller_name   = fv1.text_input(
                    "Raison sociale *",
                    value=_legacy_form_value("BT-27", extracted, extracted.seller_name),
                    key="cs_name",
                )
                conv_seller_siret  = fv2.text_input(
                    "SIREN vendeur — BT-30 (9 chiffres) *",
                    value=_legacy_form_value("BT-30", extracted, extracted.seller_siret),
                    key="cs_siret",
                )
                conv_seller_vat    = fv3.text_input(
                    "N° TVA intracommunautaire *",
                    value=_legacy_form_value("BT-31", extracted, extracted.seller_vat),
                    key="cs_vat",
                )
                fv4, fv5, fv6 = st.columns(3)
                conv_seller_street = fv4.text_input(
                    "Adresse",
                    value=_legacy_form_value("BT-35", extracted, extracted.seller_street),
                    key="cs_street",
                )
                conv_seller_postal = fv5.text_input(
                    "Code postal",
                    value=_legacy_form_value("BT-38", extracted, extracted.seller_postal),
                    key="cs_postal",
                )
                conv_seller_city   = fv6.text_input(
                    "Ville",
                    value=_legacy_form_value("BT-37", extracted, extracted.seller_city),
                    key="cs_city",
                )
                fi1, fi2 = st.columns(2)
                conv_seller_iban   = fi1.text_input(
                    "IBAN",
                    value=_legacy_form_value("BT-84", extracted, extracted.seller_iban),
                    key="cs_iban",
                )
                conv_seller_bic    = fi2.text_input(
                    "BIC",
                    value=_legacy_form_value("BT-86", extracted, extracted.seller_bic),
                    key="cs_bic",
                )

                st.markdown("**Acheteur (destinataire)**")
                fa1, fa2, fa3 = st.columns(3)
                conv_buyer_name    = fa1.text_input(
                    "Raison sociale *",
                    value=_legacy_form_value("BT-44", extracted, extracted.buyer_name),
                    key="cb_name",
                )
                conv_buyer_siret   = fa2.text_input(
                    "SIREN acheteur — BT-47 (9 chiffres) *",
                    value=_legacy_form_value("BT-47", extracted, extracted.buyer_siret),
                    key="cb_siret",
                )
                conv_buyer_vat     = fa3.text_input(
                    "N° TVA intracommunautaire",
                    value=_legacy_form_value("BT-48", extracted, extracted.buyer_vat),
                    key="cb_vat",
                )
                fa4, fa5, fa6 = st.columns(3)
                conv_buyer_street  = fa4.text_input(
                    "Adresse",
                    value=_legacy_form_value("BT-50", extracted, extracted.buyer_street),
                    key="cb_street",
                )
                conv_buyer_postal  = fa5.text_input(
                    "Code postal",
                    value=_legacy_form_value("BT-54", extracted, extracted.buyer_postal),
                    key="cb_postal",
                )
                conv_buyer_city    = fa6.text_input(
                    "Ville",
                    value=_legacy_form_value("BT-53", extracted, extracted.buyer_city),
                    key="cb_city",
                )

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
                if len(_normalize_siren_bt(conv_seller_siret)) != 9:
                    errors_conv.append("SIREN vendeur (BT-30) invalide — 9 chiffres (ou SIRET 14 ch., SIREN = 9 premiers chiffres)")
                if len(_normalize_siren_bt(conv_buyer_siret)) != 9:
                    errors_conv.append("SIREN acheteur (BT-47) invalide — 9 chiffres (ou SIRET 14 ch., SIREN = 9 premiers chiffres)")

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
                            siret=_normalize_siren_bt(conv_seller_siret),
                            vat_number=conv_seller_vat or f"FR00{_normalize_siren_bt(conv_seller_siret)}",
                            address=_make_addr(conv_seller_street, conv_seller_postal, conv_seller_city),
                            iban=conv_seller_iban or None,
                            bic=conv_seller_bic or None,
                        )
                        buyer_conv = Party(
                            name=conv_buyer_name,
                            siret=_normalize_siren_bt(conv_buyer_siret),
                            vat_number=conv_buyer_vat or f"FR00{_normalize_siren_bt(conv_buyer_siret)}",
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
st.markdown(
    """
    <div class="app-footer">
        <strong>Niji</strong> · Démo Facturation Électronique 2026 · 
        EN 16931 · Factur-X · UBL 2.1 · Chorus Pro<br>
        Outil interne — non contractuel
    </div>
    """,
    unsafe_allow_html=True,
)
