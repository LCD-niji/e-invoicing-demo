# 🧾 Facturation Électronique 2026 — Démo Technique

> **Implémentation complète Factur-X + Chorus Pro pour la réforme obligatoire 2026**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Factur-X](https://img.shields.io/badge/Factur--X-EN%2016931-green.svg)](https://fnfe-mpe.org/factur-x/)
[![Chorus Pro](https://img.shields.io/badge/Chorus%20Pro-API%20PISTE-orange.svg)](https://developer.aife.economie.gouv.fr/)
[![Streamlit](https://img.shields.io/badge/Démo-Streamlit-red.svg)](https://streamlit.io)

---

## 🚨 Pourquoi ce projet existe

**À partir du 1er septembre 2026**, toutes les PME françaises devront :

1. **Émettre** des factures électroniques structurées (Factur-X / UBL / CII)
2. **Recevoir** des factures via une Plateforme de Dématérialisation Partenaire (PDP)
3. **Transmettre** les données de transaction à la DGFiP en temps réel

👉 **85% des PME ne sont pas encore prêtes.** Ce repo montre ce que ça implique concrètement.

---

## ✅ Ce que cette démo couvre

| Module | Description | Standard |
|--------|-------------|----------|
| `generate_invoice.py` | Génération XML CII conforme | Factur-X EN 16931 |
| `validate_invoice.py` | Validation règles métier BR-* | DGFiP / CEN |
| `send_chorus.py` | Dépôt via API PISTE | Chorus Pro sandbox |
| `dashboard/app.py` | Interface démo interactive | Streamlit |

---

## 🚀 Lancement rapide

```bash
# 1. Cloner le repo
git clone https://github.com/[votre-username]/e-invoicing-demo
cd e-invoicing-demo

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Générer une facture de démo
python generate_invoice.py --output demo.xml

# 4. La valider
python validate_invoice.py demo.xml

# 5. Simuler l'envoi Chorus Pro
python send_chorus.py demo.xml --dry-run

# 6. Lancer le dashboard interactif
cd dashboard && streamlit run app.py
```

---

## 📦 Structure du projet

```
e-invoicing-demo/
├── generate_invoice.py    # Générateur XML Factur-X (CII)
├── validate_invoice.py    # Validateur règles EN 16931 + FR
├── send_chorus.py         # Connecteur API Chorus Pro (PISTE)
├── dashboard/
│   └── app.py             # Interface Streamlit
├── tests/
│   └── test_invoice.py    # Tests unitaires (pytest)
├── sample_data/           # Exemples de fichiers XML
├── requirements.txt
└── .env.example           # Template credentials PISTE
```

---

## 🔬 Détail technique

### Format Factur-X

Factur-X est le standard hybride franco-allemand retenu par la DGFiP :
- **Couche humaine** : PDF/A-3 lisible par un humain
- **Couche machine** : XML CII (Cross Industry Invoice) embarqué dans le PDF
- **5 profils** : MINIMUM → BASIC WL → BASIC → EN 16931 → EXTENDED

Ce repo implémente le profil **EN 16931** (recommandé pour les PME).

### Règles de validation implémentées

```
BR-01   Namespace et profil Factur-X
BR-03   Numéro de facture (unicité, longueur)
BR-04   Type de document (380/381/384...)
BR-05   Format de date (YYYYMMDD)
BR-06   Nom et adresse du vendeur
BR-07   Nom et adresse de l'acheteur
BR-08   Adresse postale vendeur
BR-09   Code pays ISO 3166-1
BR-16   Présence de lignes de facture
BR-25   Description produit par ligne
BR-26   Quantité facturée
BR-27   Prix unitaire net
BR-CO-15 Cohérence arithmétique HT + TVA = TTC
BR-CO-16 DuePayableAmount = GrandTotalAmount
FR-01   SIRET vendeur (14 chiffres)
FR-02   SIRET acheteur
FR-TVA  Format numéro TVA intracommunautaire
```

### API Chorus Pro (PISTE)

- **Authentification** : OAuth2 Password Grant via portail PISTE
- **Endpoint dépôt** : `POST /cpro/factures/v1/deposer/flux`
- **Format** : `IN_DP_E1_CII_FACTURX`
- **Statuts** : DEPOSEE → EN_COURS_TRAITEMENT → VALIDEE → MISE_EN_PAIEMENT

Pour utiliser le mode live (sandbox réel) :
```bash
cp .env.example .env
# Renseigner vos credentials PISTE
python send_chorus.py demo.xml --live --env sandbox
```

---

## 🧪 Tests

```bash
# Lancer tous les tests
pytest tests/ -v

# Avec couverture
pytest tests/ -v --tb=short

# Test rapide smoke
python generate_invoice.py && python validate_invoice.py facture_demo.xml
```

---

## 🗺️ Roadmap

- [ ] Export PDF/A-3 avec XML embarqué (Factur-X complet)
- [ ] Support UBL 2.1 (Peppol)
- [ ] Intégration webhook statut Chorus Pro
- [ ] Détection d'anomalies ML (doublons, fraudes)
- [ ] Connecteurs ERP (Sage, Cegid, Odoo)

---

## 📞 Vous êtes une PME concernée par la réforme 2026 ?

Ce repo est la partie visible de l'iceberg. J'accompagne les PME françaises de bout en bout :

- **Audit** de votre système de facturation actuel
- **Choix** de la solution adaptée (PDP, OD, PPF)
- **Intégration** dans votre ERP / outil comptable
- **Formation** de vos équipes

👉 **[Me contacter sur LinkedIn](#)** pour un diagnostic gratuit de 30 minutes.

---

## 📚 Ressources officielles

- [DGFiP — La facturation électronique](https://www.impots.gouv.fr/professionnel/la-facturation-electronique-entre-assujettis-la-tva)
- [Portail API PISTE (Chorus Pro)](https://developer.aife.economie.gouv.fr/)
- [Spécification Factur-X](https://fnfe-mpe.org/factur-x/)
- [Norme EN 16931](https://www.en16931.eu/)

---

*Made with ❤️ pour les PMEs françaises — Réforme 2026*
