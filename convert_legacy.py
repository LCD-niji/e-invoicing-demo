"""
convert_legacy.py
-----------------
Convertit un XML facture "legacy" (format propriétaire) vers les champs
nécessaires à la génération d'un CII Factur-X.

Approche : correspondance heuristique sur les noms de balises XML.
Supporte les formats courants : SAP, Sage, Cegid, EBP, noms FR/EN.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

# ─────────────────────────────────────────────
# Patterns heuristiques (lowercase, sans séparateurs)
# ─────────────────────────────────────────────

PATTERNS: dict[str, list[str]] = {
    # Entête facture
    "invoice_number": [
        "numerofacture", "invoicenumber", "nofacture", "nofact", "numfacture",
        "referencefacture", "invoiceid", "documentnumber", "numdoc",
        "numberfacture", "numero", "reference", "id", "pieceref",
        "nopiece", "numpiece", "factureid", "billnumber", "billid",
    ],
    "issue_date": [
        "datefacture", "invoicedate", "dateemission", "datepiece",
        "issuedate", "emissiondate", "datecomptable", "datedu",
        "date", "datedocument", "billdate",
    ],
    "due_date": [
        "dateecheance", "duedate", "datereglement", "echeance",
        "datepaiement", "datedelement", "datepaiement",
    ],
    "currency": [
        "devise", "currency", "codemonnaie", "monnaie", "currencycode",
    ],
    "notes": [
        "commentaire", "notes", "remarques", "observations", "mention",
        "description", "note", "comment",
    ],

    # Vendeur / Fournisseur
    "seller_name": [
        "nomvendeur", "nomsocietevendeur", "raisonsocialevendeur",
        "sellername", "vendeur", "fournisseur", "emetteur", "supplier",
        "nomfournisseur", "raisonsociale", "nomsociete", "societe",
        "companyname", "entreprise",
    ],
    "seller_siret": [
        "siretvendeur", "siretfournisseur", "siretemetteur",
        "siret", "nosiren", "sirenvendeur",
    ],
    "seller_vat": [
        "tvavendeur", "vatvendeur", "numtvavendeur", "numerotvavendeur",
        "tvaemetteur", "identifianttva", "numtva", "numerotva",
        "tvaintracommunautaire", "vatnumber", "vatid",
    ],
    "seller_street": [
        "adressevendeur", "ruevendeur", "adresse1vendeur",
        "adressefournisseur", "streetvendeur", "addressvendeur",
        "ligneadresse1", "adresse",
    ],
    "seller_city": [
        "villevendeur", "villefournisseur", "cityvendeur",
        "communevendeur", "ville",
    ],
    "seller_postal": [
        "codepostalvendeur", "cpvendeur", "postalcodevendeur",
        "codepostal", "cp", "zipcode",
    ],
    "seller_iban": [
        "ibanvendeur", "iban", "ribvendeur", "rib",
        "coordbancaires", "comptebancaire",
    ],
    "seller_bic": [
        "bicvendeur", "bic", "swift", "swiftvendeur",
    ],

    # Acheteur / Client
    "buyer_name": [
        "nomacheteur", "nomclient", "nomsocieteclient",
        "raisonsocialeclient", "buyername", "acheteur",
        "client", "destinataire", "customer", "clientname",
        "nomsocietedestinateur",
    ],
    "buyer_siret": [
        "siretacheteur", "siretclient", "siretdestinataire",
        "siretacheteur",
    ],
    "buyer_vat": [
        "tvaacheteur", "vatclient", "numtvaclient", "numerotvaacheteur",
        "identifiantvaclient",
    ],
    "buyer_street": [
        "adresseacheteur", "adresseclient", "rueclient",
        "streetclient", "adresse1client", "addressclient",
    ],
    "buyer_city": [
        "villeacheteur", "villeclient", "cityclient",
        "communeclient",
    ],
    "buyer_postal": [
        "codepostalacheteur", "codepostalclient", "cpclient",
        "postalcodeclient",
    ],
}

# Patterns pour les lignes de facture (cherchés dans les éléments répétés)
LINE_PATTERNS: dict[str, list[str]] = {
    "description": [
        "designation", "description", "libelle", "label", "desc",
        "produit", "article", "service", "nom", "name", "intitule",
    ],
    "quantity": [
        "quantite", "qty", "quantity", "qte", "nb", "nombre",
        "qtemandataire", "volume",
    ],
    "unit_price": [
        "prixunitaire", "prixunit", "unitprice", "pu", "prix",
        "tarifunitaire", "price", "montantunitaire",
    ],
    "vat_rate": [
        "tauxtva", "tva", "vatrate", "tauxtvа", "pourcentagetva",
        "ratedtva", "taxrate",
    ],
    "line_total": [
        "montantht", "totalht", "montanttotal", "linetotal",
        "montantligne", "total",
    ],
}

# Tags qui signalent souvent une collection de lignes
LINE_CONTAINER_HINTS = [
    "lignes", "lines", "items", "articles", "produits",
    "lignesfacture", "invoicelines", "details", "lignesdetail",
]

LINE_ELEMENT_HINTS = [
    "ligne", "line", "item", "article", "produit",
    "lignedetail", "invoiceline", "detail",
]


# ─────────────────────────────────────────────
# Résultat d'extraction
# ─────────────────────────────────────────────

@dataclass
class ExtractedLine:
    description: str = ""
    quantity: str = "1"
    unit_price: str = "0.00"
    vat_rate: str = "20"


@dataclass
class ExtractionResult:
    # Entête
    invoice_number: str = ""
    issue_date: str = ""
    due_date: str = ""
    currency: str = "EUR"
    notes: str = ""

    # Vendeur
    seller_name: str = ""
    seller_siret: str = ""
    seller_vat: str = ""
    seller_street: str = ""
    seller_city: str = ""
    seller_postal: str = ""
    seller_iban: str = ""
    seller_bic: str = ""

    # Acheteur
    buyer_name: str = ""
    buyer_siret: str = ""
    buyer_vat: str = ""
    buyer_street: str = ""
    buyer_city: str = ""
    buyer_postal: str = ""

    # Lignes
    lines: list[ExtractedLine] = field(default_factory=list)

    # Métadonnées d'extraction
    matched_fields: dict[str, str] = field(default_factory=dict)   # field → xpath matched
    unmatched_tags: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _normalize(tag: str) -> str:
    """Lowercase + supprime séparateurs et namespaces."""
    tag = re.sub(r"\{[^}]+\}", "", tag)   # namespace {uri}
    tag = re.sub(r"[^a-z0-9]", "", tag.lower())
    return tag


def _score(tag_norm: str, patterns: list[str]) -> int:
    """Retourne un score de correspondance (0 = aucun)."""
    if tag_norm in patterns:
        return 100                       # exact match
    for p in patterns:
        if tag_norm.endswith(p) or tag_norm.startswith(p):
            return 80
        if p in tag_norm or tag_norm in p:
            return 50
    return 0


def _flatten(element: ET.Element, prefix: str = "") -> list[tuple[str, str, str]]:
    """Retourne une liste (xpath, tag_norm, text) pour tous les nœuds."""
    results = []
    tag_norm = _normalize(element.tag)
    xpath = f"{prefix}/{element.tag}" if prefix else element.tag
    text = (element.text or "").strip()
    if text:
        results.append((xpath, tag_norm, text))
    # Attributs (parfois les données sont dans des attrs)
    for attr_name, attr_val in element.attrib.items():
        attr_val = attr_val.strip()
        if attr_val:
            results.append((f"{xpath}@{attr_name}", _normalize(attr_name), attr_val))
    for child in element:
        results.extend(_flatten(child, xpath))
    return results


def _parse_date(raw: str) -> str:
    """Essaye de normaliser une date en YYYY-MM-DD."""
    raw = raw.strip()
    # YYYYMMDD
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", raw)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # already YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return raw[:10]
    return raw


def _find_line_elements(root: ET.Element) -> list[ET.Element]:
    """Tente de détecter les éléments répétés correspondant aux lignes."""
    # 1. Chercher un container connu
    for elem in root.iter():
        tag_norm = _normalize(elem.tag)
        if tag_norm in LINE_CONTAINER_HINTS:
            children = list(elem)
            if len(children) >= 1:
                return children

    # 2. Chercher des éléments dont le tag ressemble à une ligne
    candidates: dict[str, list[ET.Element]] = {}
    for elem in root.iter():
        tag_norm = _normalize(elem.tag)
        if tag_norm in LINE_ELEMENT_HINTS:
            candidates.setdefault(elem.tag, []).append(elem)

    if candidates:
        # Prendre le groupe le plus grand
        best = max(candidates.values(), key=len)
        return best

    # 3. Chercher des groupes d'éléments répétés (même tag, plusieurs fois)
    tag_counts: dict[str, list[ET.Element]] = {}
    for elem in root.iter():
        tag_counts.setdefault(elem.tag, []).append(elem)

    repeated = {t: els for t, els in tag_counts.items()
                if len(els) >= 2 and any(
                    _normalize(c.tag) in LINE_PATTERNS["description"] or
                    _normalize(c.tag) in LINE_PATTERNS["unit_price"]
                    for el in els for c in el
                )}
    if repeated:
        best = max(repeated.values(), key=len)
        return best

    return []


def _extract_line(element: ET.Element) -> ExtractedLine:
    """Extrait les champs d'une ligne depuis un élément XML."""
    flat = _flatten(element)
    line = ExtractedLine()
    for _, tag_norm, text in flat:
        for field_key, patterns in LINE_PATTERNS.items():
            if _score(tag_norm, patterns) >= 50:
                if field_key == "description" and not line.description:
                    line.description = text
                elif field_key == "quantity" and not line.quantity:
                    line.quantity = text.replace(",", ".")
                elif field_key == "unit_price" and not line.unit_price:
                    line.unit_price = text.replace(",", ".")
                elif field_key == "vat_rate" and not line.vat_rate:
                    # Normaliser : "20%" → "20", "0.20" → "20"
                    raw = text.replace("%", "").replace(",", ".").strip()
                    try:
                        val = float(raw)
                        if val < 1:
                            val *= 100
                        line.vat_rate = str(int(val))
                    except ValueError:
                        line.vat_rate = raw
    return line


# ─────────────────────────────────────────────
# Point d'entrée principal
# ─────────────────────────────────────────────

def extract_from_xml(xml_content: str) -> ExtractionResult:
    """
    Parse un XML legacy et extrait les champs de facturation par heuristique.

    Returns:
        ExtractionResult avec tous les champs détectés.
    """
    result = ExtractionResult()

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"XML invalide : {e}")

    flat = _flatten(root)

    # Score chaque nœud contre les patterns
    best: dict[str, tuple[int, str]] = {}   # field_key → (score, value)

    for xpath, tag_norm, text in flat:
        for field_key, patterns in PATTERNS.items():
            s = _score(tag_norm, patterns)
            if s > 0:
                current_score, _ = best.get(field_key, (0, ""))
                if s > current_score:
                    best[field_key] = (s, text)

    # Appliquer les valeurs
    for field_key, (score, value) in best.items():
        matched_tag = next(
            (xpath for xpath, tn, tx in flat
             if tx == value and _score(tn, PATTERNS[field_key]) == score),
            "?"
        )
        result.matched_fields[field_key] = matched_tag

        if field_key == "invoice_number":
            result.invoice_number = value
        elif field_key == "issue_date":
            result.issue_date = _parse_date(value)
        elif field_key == "due_date":
            result.due_date = _parse_date(value)
        elif field_key == "currency":
            result.currency = value.upper()
        elif field_key == "notes":
            result.notes = value
        elif field_key == "seller_name":
            result.seller_name = value
        elif field_key == "seller_siret":
            result.seller_siret = re.sub(r"\D", "", value)
        elif field_key == "seller_vat":
            result.seller_vat = value
        elif field_key == "seller_street":
            result.seller_street = value
        elif field_key == "seller_city":
            result.seller_city = value
        elif field_key == "seller_postal":
            result.seller_postal = value
        elif field_key == "seller_iban":
            result.seller_iban = value.replace(" ", "")
        elif field_key == "seller_bic":
            result.seller_bic = value
        elif field_key == "buyer_name":
            result.buyer_name = value
        elif field_key == "buyer_siret":
            result.buyer_siret = re.sub(r"\D", "", value)
        elif field_key == "buyer_vat":
            result.buyer_vat = value
        elif field_key == "buyer_street":
            result.buyer_street = value
        elif field_key == "buyer_city":
            result.buyer_city = value
        elif field_key == "buyer_postal":
            result.buyer_postal = value

    # Tags non matchés
    matched_tags = set()
    for field_key, (score, value) in best.items():
        for xpath, tn, tx in flat:
            if tx == value and _score(tn, PATTERNS[field_key]) == score:
                matched_tags.add(tn)
                break

    result.unmatched_tags = list({
        tn for _, tn, tx in flat if tn not in matched_tags and tx
    })

    # Extraction des lignes
    line_elements = _find_line_elements(root)
    for elem in line_elements:
        line = _extract_line(elem)
        if line.description or line.unit_price != "0.00":
            result.lines.append(line)

    return result


def make_sample_legacy_xml() -> str:
    """Génère un XML legacy d'exemple pour les tests."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<Facture>
  <Entete>
    <NumeroFacture>FAC-2026-0042</NumeroFacture>
    <DateFacture>15/03/2026</DateFacture>
    <DateEcheance>15/04/2026</DateEcheance>
    <Devise>EUR</Devise>
  </Entete>

  <Fournisseur>
    <RaisonSociale>ACME Solutions SAS</RaisonSociale>
    <SIRET>35609901000036</SIRET>
    <NumTVA>FR72356099010</NumTVA>
    <Adresse>12 rue de la Paix</Adresse>
    <CodePostal>75001</CodePostal>
    <Ville>Paris</Ville>
    <IBAN>FR7630006000011234567890189</IBAN>
    <BIC>BNPAFRPPXXX</BIC>
  </Fournisseur>

  <Client>
    <RaisonSociale>Mairie de Lyon</RaisonSociale>
    <SIRET>21690123400015</SIRET>
    <NumTVA>FR83216901234</NumTVA>
    <Adresse>Place de la Comédie</Adresse>
    <CodePostal>69001</CodePostal>
    <Ville>Lyon</Ville>
  </Client>

  <Lignes>
    <Ligne>
      <Designation>Audit système de facturation</Designation>
      <Quantite>3</Quantite>
      <PrixUnitaire>800.00</PrixUnitaire>
      <TauxTVA>20</TauxTVA>
    </Ligne>
    <Ligne>
      <Designation>Implémentation connecteur</Designation>
      <Quantite>5</Quantite>
      <PrixUnitaire>950.00</PrixUnitaire>
      <TauxTVA>20</TauxTVA>
    </Ligne>
    <Ligne>
      <Designation>Formation équipe comptable</Designation>
      <Quantite>2</Quantite>
      <PrixUnitaire>600.00</PrixUnitaire>
      <TauxTVA>20</TauxTVA>
    </Ligne>
  </Lignes>

  <Commentaire>Facture relative au projet de dématérialisation 2026</Commentaire>
</Facture>
"""
