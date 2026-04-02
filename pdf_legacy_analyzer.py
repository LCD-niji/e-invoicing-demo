"""
pdf_legacy_analyzer.py
-----------------------
Analyse un PDF classique (non Factur-X) et produit un rapport
de non-conformité orienté métier, pour la réforme 2026.

Logique :
  1. Tente d'extraire le texte via pdfplumber (fallback pypdf)
  2. Détecte si un XML est embarqué → c'est un Factur-X, pas un PDF classique
  3. Applique des heuristiques pour vérifier les champs obligatoires EN16931 + France
  4. Calcule un score de conformité (0-100)
  5. Retourne un rapport structuré avec explications métier et actions correctives
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Extraction texte (pdfplumber en priorité, fallback pypdf) ──────────────
try:
    import pdfplumber  # type: ignore

    _HAS_PDFPLUMBER = True
except ImportError:  # pragma: no cover
    _HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader  # type: ignore

    _HAS_PYPDF = True
except ImportError:  # pragma: no cover
    _HAS_PYPDF = False


# ── Patterns heuristiques ──────────────────────────────────────────────────
_SIRET = re.compile(r"\b\d{14}\b")
_TVA_INTRA = re.compile(r"\bFR\s*[A-Z0-9]{2}[\s\d]{9,}\b", re.IGNORECASE)
_INV_NUMBER = re.compile(
    r"(?:facture|invoice|n[°o]|num[ée]ro)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
    re.IGNORECASE,
)
_DATE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_AMOUNT = re.compile(r"\b\d[\d\s]*[.,]\d{2}\s*€?\b")
_TVA_MENTION = re.compile(r"\bT\.?V\.?A\.?\b", re.IGNORECASE)
_IBAN = re.compile(r"\bFR\d{2}[\s\d]{20,}\b")
_NATURE_OP = re.compile(
    r"\b(prestation|service|fourniture|produit|livraison|bien)\b", re.IGNORECASE
)
_DUE_DATE = re.compile(
    r"(?:éch[eé]ance|due date|paiement)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
    re.IGNORECASE,
)


# ── Modèle de résultat ─────────────────────────────────────────────────────
@dataclass
class PdfIssue:
    category: str  # "bloquant" | "warning" | "info"
    code: str
    label: str  # Message court pour l'UI
    explanation: str  # Explication métier (non-technicien)
    fix: str  # Action corrective concrète


@dataclass
class PdfAnalysisResult:
    is_facturx: bool
    is_plain_pdf: bool
    page_count: int
    text_length: int
    score: int  # 0-100
    issues: list[PdfIssue] = field(default_factory=list)
    detected: dict = field(default_factory=dict)

    @property
    def blocking_count(self) -> int:
        return sum(1 for i in self.issues if i.category == "bloquant")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.category == "warning")

    @property
    def verdict(self) -> str:
        if self.is_facturx:
            return "facturx"
        if self.blocking_count == 0:
            return "ok"
        return "reject"


# ── Extraction texte ───────────────────────────────────────────────────────
def _extract_text_and_meta(pdf_bytes: bytes) -> tuple[str, int, bool]:
    """
    Retourne (texte, nb_pages, has_embedded_xml).
    Utilise pdfplumber si disponible, sinon pypdf.
    """
    text = ""
    pages = 0
    has_xml = False

    # Détection XML embarqué (Factur-X) via pypdf
    if _HAS_PYPDF:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages = len(reader.pages)

            # Chercher pièces jointes XML (structure PDF variable selon générateur)
            root = reader.trailer.get("/Root", {})
            names = root.get("/Names", {})
            if names:
                emb = names.get("/EmbeddedFiles", {})
                if emb:
                    has_xml = True

            # Fallback via /AF (Associated Files - Factur-X standard)
            if not has_xml and root.get("/AF"):
                has_xml = True
        except Exception:
            pass

    # Extraction texte
    if _HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = pages or len(pdf.pages)
                for p in pdf.pages:
                    text += (p.extract_text() or "") + "\n"
        except Exception:
            pass

    if not text and _HAS_PYPDF:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"
        except Exception:
            pass

    return text, pages, has_xml


# ── Analyse principale ─────────────────────────────────────────────────────
def analyze_plain_pdf(pdf_bytes: bytes) -> PdfAnalysisResult:
    """Point d'entrée principal."""

    if not _HAS_PYPDF and not _HAS_PDFPLUMBER:
        return PdfAnalysisResult(
            is_facturx=False,
            is_plain_pdf=True,
            page_count=0,
            text_length=0,
            score=0,
            issues=[
                PdfIssue(
                    "bloquant",
                    "INSTALL",
                    "Librairie PDF manquante",
                    "pdfplumber ou pypdf n'est pas installé.",
                    "pip install pdfplumber pypdf",
                )
            ],
        )

    text, page_count, has_xml = _extract_text_and_meta(pdf_bytes)

    # Cas Factur-X détecté → pas de problème de format
    if has_xml:
        return PdfAnalysisResult(
            is_facturx=True,
            is_plain_pdf=False,
            page_count=page_count,
            text_length=len(text),
            score=100,
            issues=[],
            detected={"format": "Factur-X (XML embarqué détecté)"},
        )

    issues: list[PdfIssue] = []
    detected: dict = {}

    # ── BLOQUANT ABSOLU : format non structuré ──────────────────────────────
    issues.append(
        PdfIssue(
            category="bloquant",
            code="FORMAT-01",
            label="PDF classique non structuré → rejeté après le 1er septembre 2026",
            explanation=(
                "La réforme impose un format électronique structuré (Factur-X, UBL 2.1 ou CII). "
                "Un PDF classique, même s'il contient toutes les informations visuelles, "
                "ne peut pas être traité automatiquement par les Plateformes Agréées (PA). "
                "Il sera rejeté automatiquement avec un code erreur FORMAT_INVALID."
            ),
            fix=(
                "Adopter le format Factur-X : un PDF/A-3b lisible par l'humain "
                "avec un fichier XML CII embarqué. Cet outil permet de le générer directement."
            ),
        )
    )

    # ── SIREN vendeur (BT-30) — détection heuristique via SIRET 14 ch. en PDF ──
    sirets = _SIRET.findall(text)
    if sirets:
        detected["siret_candidats"] = list(dict.fromkeys(sirets))[:4]
        detected["siren_vendeur_candidats"] = [s[:9] for s in detected["siret_candidats"]]
    else:
        issues.append(
            PdfIssue(
                category="bloquant",
                code="FR-01",
                label="SIREN vendeur (BT-30) non détecté — attendu 9 chiffres (Annexe 7)",
                explanation=(
                    "BT-30 porte le SIREN (9 chiffres), pas le SIRET complet. "
                    "Les mentions légales affichent souvent le SIRET (14 chiffres) : les 9 premiers chiffres forment le SIREN."
                ),
                fix="Renseigner le SIREN vendeur (9 chiffres) ou un SIRET (14 chiffres) dont on déduit le SIREN.",
            )
        )

    # ── N° TVA intracommunautaire ───────────────────────────────────────────
    tva_matches = _TVA_INTRA.findall(text)
    if tva_matches:
        detected["tva_candidats"] = tva_matches[:2]
    else:
        issues.append(
            PdfIssue(
                category="bloquant",
                code="BR-31",
                label="Numéro de TVA intracommunautaire non détecté",
                explanation=(
                    "Le numéro de TVA intracommunautaire (BT-31) est obligatoire pour "
                    "toute transaction B2B assujettie à la TVA. "
                    "Format attendu : FR + 2 caractères + 9 chiffres."
                ),
                fix="Ajouter le numéro de TVA au format FRxx xxxxxxxxx dans les mentions vendeur.",
            )
        )

    # ── Numéro de facture ───────────────────────────────────────────────────
    inv_match = _INV_NUMBER.search(text)
    if inv_match:
        detected["invoice_number"] = inv_match.group(1)
    else:
        issues.append(
            PdfIssue(
                category="bloquant",
                code="BR-02",
                label="Numéro de facture non identifiable automatiquement",
                explanation=(
                    "Le numéro unique (BT-1) doit être structuré et lisible par machine. "
                    "Les plateformes vérifient l'unicité du numéro pour détecter les doublons."
                ),
                fix="Utiliser une numérotation séquentielle explicite (ex: FAC-2026-001).",
            )
        )

    # ── Date d'émission ─────────────────────────────────────────────────────
    dates = _DATE.findall(text)
    if dates:
        detected["dates_candidates"] = dates[:3]
    else:
        issues.append(
            PdfIssue(
                category="bloquant",
                code="BR-03",
                label="Date d'émission non détectée",
                explanation=(
                    "La date d'émission (BT-2) est obligatoire. "
                    "Elle doit être au format YYYYMMDD dans le XML structuré."
                ),
                fix="Ajouter une date d'émission explicite et lisible.",
            )
        )

    # ── Mentions TVA ─────────────────────────────────────────────────────────
    if not _TVA_MENTION.search(text):
        issues.append(
            PdfIssue(
                category="bloquant",
                code="TVA-DETAIL",
                label="Aucune ventilation TVA détectée (HT / taux / TVA / TTC)",
                explanation=(
                    "Une facture B2B doit comporter la base HT (BT-106), "
                    "le taux de TVA (BT-119), le montant de TVA (BT-117) "
                    "et le total TTC (BT-112). Sans ces données, "
                    "le rapprochement comptable est impossible."
                ),
                fix="Ajouter les lignes TVA détaillées : base HT, taux (20%/10%/5.5%/0%), montant TVA.",
            )
        )
    else:
        # Vérifier présence de montants
        amounts = _AMOUNT.findall(text)
        if amounts:
            detected["montants_candidats"] = amounts[:5]
        else:
            issues.append(
                PdfIssue(
                    category="bloquant",
                    code="BR-CO-15",
                    label="Montants numériques non détectés",
                    explanation=(
                        "Les montants HT, TVA et TTC doivent être présents et cohérents."
                    ),
                    fix="Vérifier que les montants sont bien en chiffres (pas uniquement en lettres).",
                )
            )

    # ── Nature de l'opération ───────────────────────────────────────────────
    if not _NATURE_OP.search(text):
        issues.append(
            PdfIssue(
                category="warning",
                code="FR-NATURE",
                label="Nature de l'opération (bien ou service) non identifiable",
                explanation=(
                    "La DGFiP exige la qualification de l'opération (BT-19 : vente de biens, "
                    "prestation de services, ou mixte) pour la catégorisation fiscale "
                    "et l'e-reporting."
                ),
                fix="Préciser explicitement 'prestation de services' ou 'vente de biens' dans la désignation.",
            )
        )

    # ── Date d'échéance ─────────────────────────────────────────────────────
    if not _DUE_DATE.search(text):
        issues.append(
            PdfIssue(
                category="warning",
                code="BR-DUE",
                label="Date d'échéance non identifiée",
                explanation=(
                    "La date d'échéance (BT-9) est recommandée pour le suivi des délais de paiement "
                    "et l'automatisation du rapprochement."
                ),
                fix="Ajouter une date d'échéance de paiement explicite.",
            )
        )

    # ── IBAN ─────────────────────────────────────────────────────────────────
    if not _IBAN.search(text):
        issues.append(
            PdfIssue(
                category="warning",
                code="BR-47",
                label="IBAN non détecté",
                explanation=(
                    "L'IBAN (BT-84) est obligatoire si le moyen de paiement est le virement "
                    "(codes UNTDID 30 ou 58). Très recommandé pour automatiser les paiements."
                ),
                fix="Inclure l'IBAN du compte vendeur à créditer.",
            )
        )

    # ── Calcul du score ─────────────────────────────────────────────────────
    n_blocking = sum(1 for i in issues if i.category == "bloquant")
    n_warning = sum(1 for i in issues if i.category == "warning")
    score = max(0, 100 - 40 - (n_blocking - 1) * 10 - n_warning * 5)

    return PdfAnalysisResult(
        is_facturx=False,
        is_plain_pdf=True,
        page_count=page_count,
        text_length=len(text),
        score=score,
        issues=issues,
        detected=detected,
    )

