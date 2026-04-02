"""
convert_legacy.py
-----------------
Convertit un XML legacy (format propriétaire) vers CII Factur-X EN16931.

Exports attendus par app.py :
  - ExtractionResult
  - extract_from_xml(xml_content: str) -> ExtractionResult
  - make_sample_legacy_xml() -> str
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

# ── Chemins par défaut ─────────────────────────────────────
RULES_PATH    = Path("rules_engine/rules.json")
SYNONYMS_PATH = Path("mappings/bt_synonyms.json")
@dataclass
class ExtractionResult:
    # Champs mappés (BT-1, BT-2, ...)
    mapped: dict[str, str] = field(default_factory=dict)
    lines: list[LineResult] = field(default_factory=list)
    # Les tests + l'UI attendent une collection de tags non mappés,
    # sans forcément conserver (tag XML original, valeur).
    unmatched_tags: set[str] = field(default_factory=set)
    total_tags:   int = 0
    matched_tags: int = 0

    @property
    def match_rate(self) -> float:
        if self.total_tags == 0:
            return 0.0
        return round(self.matched_tags / self.total_tags * 100, 1)

    # ── Propriétés de compatibilité app.py ────────────────
    @property
    def invoice_number(self) -> str:
        return self.mapped.get("BT-1", "")

    @property
    def issue_date(self) -> str:
        return self.mapped.get("BT-2", "")

    @property
    def due_date(self) -> str:
        return self.mapped.get("BT-9", "")

    @property
    def type_code(self) -> str:
        return self.mapped.get("BT-3", "380")

    @property
    def currency(self) -> str:
        return self.mapped.get("BT-5", "EUR")

    @property
    def buyer_ref(self) -> str:
        return self.mapped.get("BT-10", "")

    @property
    def contract_ref(self) -> str:
        return self.mapped.get("BT-12", "")

    @property
    def purchase_order(self) -> str:
        return self.mapped.get("BT-13", "")

    @property
    def notes(self) -> str:
        return self.mapped.get("BT-22", "")

    @property
    def seller_name(self) -> str:
        return self.mapped.get("BT-27", "")

    @property
    def seller_siret(self) -> str:
        return self.mapped.get("BT-30", "")

    @property
    def seller_vat(self) -> str:
        return self.mapped.get("BT-31", "")

    @property
    def seller_street(self) -> str:
        return self.mapped.get("BT-35", "")

    @property
    def seller_city(self) -> str:
        return self.mapped.get("BT-37", "")

    @property
    def seller_postal_code(self) -> str:
        return self.mapped.get("BT-38", "")

    @property
    def seller_postal(self) -> str:
        return self.mapped.get("BT-38", "")

    @property
    def seller_country(self) -> str:
        return self.mapped.get("BT-40", "FR")

    @property
    def seller_iban(self) -> str:
        return self.mapped.get("BT-84", "")

    @property
    def seller_bic(self) -> str:
        return self.mapped.get("BT-86", "")

    @property
    def buyer_name(self) -> str:
        return self.mapped.get("BT-44", "")

    @property
    def buyer_siret(self) -> str:
        return self.mapped.get("BT-47", "")

    @property
    def buyer_vat(self) -> str:
        return self.mapped.get("BT-48", "")

    @property
    def buyer_street(self) -> str:
        return self.mapped.get("BT-50", "")

    @property
    def buyer_city(self) -> str:
        return self.mapped.get("BT-53", "")

    @property
    def buyer_postal(self) -> str:
        return self.mapped.get("BT-53", "")

    @property
    def buyer_country(self) -> str:
        return self.mapped.get("BT-55", "FR")

    @property
    def matched_fields(self) -> dict[str, str]:
        return self.mapped

    @property
    def normalized_payload(self) -> dict[str, Any]:
        payload = {
            "invoice_number": self.invoice_number,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "type_code": self.type_code,
            "currency": self.currency,
            "buyer_ref": self.buyer_ref,
            "contract_ref": self.contract_ref,
            "purchase_order": self.purchase_order,
            "notes": self.notes,
            "seller": {
                "name": self.seller_name,
                "siret": self.seller_siret,
                "vat": self.seller_vat,
                "street": self.seller_street,
                "city": self.seller_city,
                "postal_code": self.seller_postal,
                "country": self.seller_country,
                "iban": self.seller_iban,
                "bic": self.seller_bic,
            },
            "buyer": {
                "name": self.buyer_name,
                "siret": self.buyer_siret,
                "vat": self.buyer_vat,
                "street": self.buyer_street,
                "city": self.buyer_city,
                "postal_code": self.buyer_postal,
                "country": self.buyer_country,
            },
            "lines": [
                {
                    "line_id": ln.line_id,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "unit_price": ln.unit_price,
                    "vat_rate": ln.vat_rate,
                    "unit": ln.unit,
                }
                for ln in self.lines
            ],
            # Sécuriser la sérialisation JSON (sets ne sont pas sérialisables nativement).
            "unmatched_tags": sorted(self.unmatched_tags),
            "stats": {
                "total_tags": self.total_tags,
                "matched_tags": self.matched_tags,
                "match_rate": self.match_rate,
            },
        }
        # Compat tests: exposer les BT canoniques attendus par les scénarios legacy.
        payload["BT-1"] = self.mapped.get("BT-1", "")
        payload["BT-2"] = self.mapped.get("BT-2", "")
        payload["BT-3"] = self.mapped.get("BT-3", self.type_code)
        payload["BT-5"] = self.mapped.get("BT-5", self.currency)
        return payload

# ─────────────────────────────────────────────────────────────
# Normalisation
# ─────────────────────────────────────────────────────────────

def _normalize(tag: str) -> str:
    """Minuscules, sans séparateurs ni namespace."""
    tag = re.sub(r"\{[^}]+\}", "", tag)   # retire namespace XML
    return re.sub(r"[^a-z0-9]", "", tag.lower())


# ─────────────────────────────────────────────────────────────
# Chargement du mapping depuis les règles actives
# ─────────────────────────────────────────────────────────────

def _load_active_bts() -> set[str]:
    """Retourne les BT codes actifs (f1:true) depuis rules.json."""
    if not RULES_PATH.exists():
        return set()
    with open(RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    active: set[str] = set()
    for key, rules in data.items():
        if key == "meta" or not isinstance(rules, list):
            continue
        for rule in rules:
            if rule.get("f1") is True:
                for bt in rule.get("bt", "").split(","):
                    active.add(bt.strip())
    return active


def build_field_map() -> dict[str, dict]:
    """
    Génère le mapping normalisé_pattern → {bt, label}
    à partir des synonymes ET des règles actives.
    Seuls les BT présents dans rules.json (f1:true) sont inclus.
    """
    if not SYNONYMS_PATH.exists():
        return _fallback_field_map()

    with open(SYNONYMS_PATH, encoding="utf-8") as f:
        synonyms = json.load(f)

    active_bts = _load_active_bts()

    result: dict[str, dict] = {}
    for bt_code, meta in synonyms.items():
        if bt_code.startswith("_"):
            continue
        if active_bts and bt_code not in active_bts:
            continue
        label = meta.get("label", bt_code)
        for pattern in meta.get("patterns", []):
            key = _normalize(pattern)
            if key not in result:
                result[key] = {"bt": bt_code, "label": label}
    return result


def get_active_bt_list() -> list[dict]:
    """Liste des BT actifs avec labels, pour le selectbox de mapping manuel."""
    if not SYNONYMS_PATH.exists():
        return [{"bt": k, "label": v} for k, v in _BT_LABELS.items()]

    with open(SYNONYMS_PATH, encoding="utf-8") as f:
        synonyms = json.load(f)
    active_bts = _load_active_bts()

    return sorted(
        [{"bt": bt, "label": meta.get("label", bt)}
         for bt, meta in synonyms.items()
         if not bt.startswith("_") and (not active_bts or bt in active_bts)],
        key=lambda x: x["bt"]
    )


# ─────────────────────────────────────────────────────────────
# Fallback si bt_synonyms.json absent (patterns hardcodés)
# ─────────────────────────────────────────────────────────────

_BT_LABELS = {
    "BT-1": "Numéro de facture", "BT-2": "Date d'émission",
    "BT-3": "TypeCode",          "BT-5": "Devise",
    "BT-9": "Date d'échéance",   "BT-10": "Référence acheteur",
    "BT-12": "Référence contrat","BT-13": "Bon de commande",
    "BT-22": "Note",             "BT-27": "Nom vendeur",
    "BT-30": "SIRET vendeur",    "BT-31": "TVA vendeur",
    "BT-35": "Rue vendeur",      "BT-37": "Ville vendeur",
    "BT-38": "CP vendeur",       "BT-40": "Pays vendeur",
    "BT-44": "Nom acheteur",     "BT-47": "SIRET acheteur",
    "BT-53": "Ville acheteur",   "BT-55": "Pays acheteur",
    "BT-84": "IBAN",             "BT-126": "N° ligne",
    "BT-129": "Quantité",        "BT-146": "Prix unitaire",
    "BT-151": "Code TVA ligne",  "BT-153": "Désignation",
}

def _fallback_field_map() -> dict[str, dict]:
    return {
        # Entête
        "facturenum":    {"bt": "BT-1",  "label": "Numéro de facture"},
        "numfact":       {"bt": "BT-1",  "label": "Numéro de facture"},
        "nofact":        {"bt": "BT-1",  "label": "Numéro de facture"},
        "factureid":     {"bt": "BT-1",  "label": "Numéro de facture"},
        "invoicenumber": {"bt": "BT-1",  "label": "Numéro de facture"},
        "numerofacture": {"bt": "BT-1",  "label": "Numéro de facture"},
        "facturedate":   {"bt": "BT-2",  "label": "Date d'émission"},
        "datefact":      {"bt": "BT-2",  "label": "Date d'émission"},
        "dateemission":  {"bt": "BT-2",  "label": "Date d'émission"},
        "invoicedate":   {"bt": "BT-2",  "label": "Date d'émission"},
        "facturetype":   {"bt": "BT-3",  "label": "TypeCode"},
        "typefact":      {"bt": "BT-3",  "label": "TypeCode"},
        "invoicetype":   {"bt": "BT-3",  "label": "TypeCode"},
        "devise":        {"bt": "BT-5",  "label": "Devise"},
        "currency":      {"bt": "BT-5",  "label": "Devise"},
        "devisecomptable":{"bt": "BT-5", "label": "Devise"},
        "dtech":         {"bt": "BT-9",  "label": "Date d'échéance"},
        "dtecheance":    {"bt": "BT-9",  "label": "Date d'échéance"},
        "echeance":      {"bt": "BT-9",  "label": "Date d'échéance"},
        "dateecheance":  {"bt": "BT-9",  "label": "Date d'échéance"},
        "duedate":       {"bt": "BT-9",  "label": "Date d'échéance"},
        "adrcptcli":     {"bt": "BT-10", "label": "Référence acheteur"},
        "refclient":     {"bt": "BT-10", "label": "Référence acheteur"},
        "codeacheteur":  {"bt": "BT-10", "label": "Référence acheteur"},
        "contratnum":    {"bt": "BT-12", "label": "Référence contrat"},
        "nocontrat":     {"bt": "BT-12", "label": "Référence contrat"},
        "refcontrat":    {"bt": "BT-12", "label": "Référence contrat"},
        "boncde":        {"bt": "BT-13", "label": "Bon de commande"},
        "boncommande":   {"bt": "BT-13", "label": "Bon de commande"},
        "noboncommande": {"bt": "BT-13", "label": "Bon de commande"},
        "comment":       {"bt": "BT-22", "label": "Note"},
        "comment1":      {"bt": "BT-22", "label": "Note"},
        "loyer":         {"bt": "BT-22", "label": "Note"},
        # Vendeur
        "nomfournisseur":{"bt": "BT-27", "label": "Nom vendeur"},
        "sellername":    {"bt": "BT-27", "label": "Nom vendeur"},
        "siretfournisseur":{"bt":"BT-30","label": "SIRET vendeur"},
        "siretvendeur":  {"bt": "BT-30", "label": "SIRET vendeur"},
        "tvafournisseur":{"bt": "BT-31", "label": "TVA vendeur"},
        "numtvafournisseur":{"bt":"BT-31","label":"TVA vendeur"},
        "adrfournisseur":{"bt": "BT-35", "label": "Rue vendeur"},
        "ruefournisseur":{"bt": "BT-35", "label": "Rue vendeur"},
        "villefournisseur":{"bt":"BT-37","label": "Ville vendeur"},
        "cpfournisseur": {"bt": "BT-38", "label": "CP vendeur"},
        "paysfournisseur":{"bt":"BT-40", "label": "Pays vendeur"},
        "iban":          {"bt": "BT-84", "label": "IBAN"},
        "ibanfournisseur":{"bt":"BT-84", "label": "IBAN"},
        "bic":           {"bt": "BT-86", "label": "BIC"},
        # Acheteur
        "nomclient":     {"bt": "BT-44", "label": "Nom acheteur"},
        "raisonsocialeclient":{"bt":"BT-44","label":"Nom acheteur"},
        "buyername":     {"bt": "BT-44", "label": "Nom acheteur"},
        "siretclient":   {"bt": "BT-47", "label": "SIRET acheteur"},
        "siretacheteur": {"bt": "BT-47", "label": "SIRET acheteur"},
        "villeclient":   {"bt": "BT-53", "label": "Ville acheteur"},
        "paysclient":    {"bt": "BT-55", "label": "Pays acheteur"},
        # Lignes
        "designation":   {"bt": "BT-153","label": "Désignation"},
        "description":   {"bt": "BT-153","label": "Désignation"},
        "libelle":       {"bt": "BT-153","label": "Désignation"},
        "quantite":      {"bt": "BT-129","label": "Quantité"},
        "quantity":      {"bt": "BT-129","label": "Quantité"},
        "qte":           {"bt": "BT-129","label": "Quantité"},
        "prixunitaire":  {"bt": "BT-146","label": "Prix unitaire"},
        "unitprice":     {"bt": "BT-146","label": "Prix unitaire"},
        "prixht":        {"bt": "BT-146","label": "Prix unitaire"},
        "tvaligne":      {"bt": "BT-151","label": "Code TVA ligne"},
        "vatrateligne":  {"bt": "BT-151","label": "Code TVA ligne"},
    }


# ─────────────────────────────────────────────────────────────
# Structures de résultat
# ─────────────────────────────────────────────────────────────

@dataclass
class LineResult:
    line_id:     str = ""
    description: str = ""
    quantity:    float = 1.0
    unit_price:  float = 0.0
    vat_rate:    float = 20.0
    unit:        str = "C62"
    raw_fields:  dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# Utilitaires date
# ─────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> str:
    """Normalise vers AAAA-MM-JJ."""
    raw = raw.strip()
    # DD/MM/YYYY
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # YYYYMMDD
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # YYYY-MM-DD déjà bon
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return raw


def _parse_amount(raw: str) -> float:
    try:
        return float(raw.replace(",", ".").replace(" ", "").replace("\xa0", ""))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
# Détection des lignes répétées
# ─────────────────────────────────────────────────────────────

def _find_line_elements(root: etree._Element) -> list[etree._Element]:
    """3 stratégies pour détecter les lignes de facture répétées."""
    LINE_HINTS = ["ligne", "line", "detail", "article", "item",
                  "prestation", "service", "produit", "product"]

    # Stratégie 1 : balise répétée > 1 fois avec un hint
    tag_counts: dict[str, list] = {}
    for el in root.iter():
        t = _normalize(el.tag)
        tag_counts.setdefault(t, []).append(el)
    for hint in LINE_HINTS:
        for tag, elements in tag_counts.items():
            if hint in tag and len(elements) > 1:
                return elements

    # Stratégie 2 : parent contenant des éléments répétés avec hint
    for el in root.iter():
        children_tags = [_normalize(c.tag) for c in el]
        if len(children_tags) > 1 and len(set(children_tags)) == 1:
            if any(h in children_tags[0] for h in LINE_HINTS):
                return list(el)

    # Stratégie 3 : groupe d'éléments contenant montant + quantité
    for el in root.iter():
        children = list(el)
        if len(children) >= 2:
            has_qty    = any("quantit" in _normalize(c.tag) or
                             _normalize(c.tag) in ("qte","qty") for c in children)
            has_amount = any("prix" in _normalize(c.tag) or
                             "price" in _normalize(c.tag) or
                             "montant" in _normalize(c.tag) for c in children)
            if has_qty and has_amount:
                return [el]

    return []


# ─────────────────────────────────────────────────────────────
# Extraction principale
# ─────────────────────────────────────────────────────────────

def extract_from_xml(xml_content: str) -> ExtractionResult:
    """
    Extrait les champs CII depuis un XML legacy quelconque.
    Utilise le mapping dérivé de rules.json + bt_synonyms.json.
    """
    result     = ExtractionResult()
    field_map  = build_field_map()

    # Parser le XML (tolérant aux encodages)
    try:
        content_bytes = xml_content.encode("utf-8", errors="replace")
        root = etree.fromstring(content_bytes)
    except Exception:
        try:
            root = etree.fromstring(xml_content.encode("latin-1", errors="replace"))
        except Exception as e:
            # On conserve au moins le fait qu'il y ait eu une erreur de parsing.
            result.unmatched_tags.add("_parse_error")
            return result

    # Détecter les lignes d'abord pour les exclure du mapping entête
    line_elements = _find_line_elements(root)
    line_el_ids   = {id(el) for el in line_elements}
    line_ancestor_ids: set[int] = set()
    for line_el in line_elements:
        parent = line_el.getparent()
        if parent is not None:
            line_ancestor_ids.add(id(parent))

    # ── Mapping des champs entête ──────────────────────────
    for el in root.iter():
        if id(el) in line_el_ids:
            continue
        if id(el) in line_ancestor_ids:
            continue
        if el.text is None or not el.text.strip():
            continue

        tag_norm = _normalize(el.tag)
        value    = el.text.strip()
        result.total_tags += 1

        if tag_norm in field_map:
            bt    = field_map[tag_norm]["bt"]
            label = field_map[tag_norm]["label"]
            # Ne pas écraser si déjà mappé avec une valeur non vide
            if bt not in result.mapped or not result.mapped[bt]:
                result.mapped[bt] = value
                result.matched_tags += 1
        else:
            result.unmatched_tags.add(tag_norm)

    # ── Post-traitement dates ──────────────────────────────
    for bt in ("BT-2", "BT-9"):
        if bt in result.mapped:
            result.mapped[bt] = _parse_date(result.mapped[bt])

    # ── Mapping des lignes ─────────────────────────────────
    for i, line_el in enumerate(line_elements, start=1):
        line = LineResult(line_id=str(i))
        line_field_map = {
            k: v for k, v in field_map.items()
            if v["bt"] in ("BT-126","BT-129","BT-130","BT-131",
                           "BT-146","BT-151","BT-153","BT-154")
        }
        for child in line_el.iter():
            if child.text is None or not child.text.strip():
                continue
            tag_norm = _normalize(child.tag)
            value    = child.text.strip()
            if tag_norm in line_field_map:
                bt = line_field_map[tag_norm]["bt"]
                line.raw_fields[bt] = value
                if bt == "BT-153":
                    line.description = value
                elif bt == "BT-129":
                    line.quantity = _parse_amount(value)
                elif bt == "BT-146":
                    line.unit_price = _parse_amount(value)
                elif bt == "BT-151":
                    raw_vat = value.replace("%","").strip()
                    try:
                        line.vat_rate = float(raw_vat)
                    except Exception:
                        line.vat_rate = 20.0
                elif bt == "BT-126":
                    line.line_id = value

        if line.description or line.unit_price:
            result.lines.append(line)

    return result


# ─────────────────────────────────────────────────────────────
# XML d'exemple générique (pour la démo)
# ─────────────────────────────────────────────────────────────

def make_sample_legacy_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Facture>
  <Entete>
    <FactureNum>FAC-2026-001</FactureNum>
    <FactureDate>15/03/2026</FactureDate>
    <FactureType>380</FactureType>
    <ContratNum>CTR-2026-042</ContratNum>
    <BonCde>BC-98765</BonCde>
    <DtEch>14/04/2026</DtEch>
    <Devise>EUR</Devise>
    <AdrCptCli>C100042</AdrCptCli>
    <Comment>Prestation de conseil en transformation numérique — Mars 2026</Comment>
  </Entete>
  <Fournisseur>
    <NomFournisseur>Acme Conseil SAS</NomFournisseur>
    <SIRETFournisseur>12345678901234</SIRETFournisseur>
    <TVAFournisseur>FR12345678901</TVAFournisseur>
    <AdrFournisseur>12 rue de la Paix</AdrFournisseur>
    <CPFournisseur>75001</CPFournisseur>
    <VilleFournisseur>Paris</VilleFournisseur>
    <PaysFournisseur>FR</PaysFournisseur>
    <IBAN>FR7630006000011234567890189</IBAN>
    <BIC>BNPAFRPP</BIC>
  </Fournisseur>
  <Client>
    <NomClient>Dupont Industries SARL</NomClient>
    <SIRETClient>98765432109876</SIRETClient>
    <VilleClient>Lyon</VilleClient>
    <PaysClient>FR</PaysClient>
  </Client>
  <Lignes>
    <Ligne>
      <Designation>Audit système de facturation électronique</Designation>
      <Quantite>3</Quantite>
      <PrixUnitaire>800.00</PrixUnitaire>
      <TVALigne>20</TVALigne>
    </Ligne>
    <Ligne>
      <Designation>Implémentation connecteur Chorus Pro</Designation>
      <Quantite>5</Quantite>
      <PrixUnitaire>950.00</PrixUnitaire>
      <TVALigne>20</TVALigne>
    </Ligne>
    <Ligne>
      <Designation>Formation équipe comptable (2 jours)</Designation>
      <Quantite>2</Quantite>
      <PrixUnitaire>600.00</PrixUnitaire>
      <TVALigne>20</TVALigne>
    </Ligne>
  </Lignes>
</Facture>"""