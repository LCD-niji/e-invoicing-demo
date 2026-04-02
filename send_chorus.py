"""
send_chorus.py
--------------
Connecteur Chorus Pro (API PISTE - sandbox DGFiP).

Ce module implémente :
  - L'authentification OAuth2 via PISTE (portail API DGFiP)
  - Le dépôt d'une facture en mode "Fournisseur → Entité Publique"
  - La consultation du statut de traitement
  - La simulation locale (mode dry-run) sans compte Chorus Pro

Pré-requis sandbox :
  1. Créer un compte sur : https://developer.aife.economie.gouv.fr/
  2. Créer une application → récupérer client_id + client_secret
  3. Activer l'API "Chorus Pro - Espace Fournisseur"
  4. Renseigner les variables d'environnement (voir .env.example)

Documentation officielle :
  https://developer.aife.economie.gouv.fr/index.php?option=com_apiportal&view=apitester

Usage :
    python send_chorus.py facture.xml --dry-run
    python send_chorus.py facture.xml --env sandbox
"""

import argparse
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

class Environment(Enum):
    SANDBOX    = "sandbox"
    PRODUCTION = "production"


# URLs PISTE (portail API DGFiP)
PISTE_URLS = {
    Environment.SANDBOX: {
        "token":  "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
        "chorus": "https://sandbox-api.piste.gouv.fr/cpro/factures/v1",
    },
    Environment.PRODUCTION: {
        "token":  "https://oauth.piste.gouv.fr/api/oauth/token",
        "chorus": "https://api.piste.gouv.fr/cpro/factures/v1",
    },
}

# Codes de statut Chorus Pro
CHORUS_STATUS = {
    "DEPOSEE":                  ("📥", "Facture déposée, en attente de traitement"),
    "EN_COURS_TRAITEMENT":      ("⚙️ ", "Traitement en cours par Chorus Pro"),
    "VALIDEE":                  ("✅", "Facture validée par l'entité publique"),
    "MISE_EN_PAIEMENT":         ("💳", "Mise en paiement"),
    "COMPTABILISEE":            ("📚", "Facture comptabilisée"),
    "REJETEE":                  ("❌", "Facture rejetée (voir motif)"),
    "SUSPENDUE":                ("⏸️ ", "Facture suspendue"),
    "MANDATEE":                 ("📋", "Mandat émis"),
}


@dataclass
class ChorusConfig:
    client_id: str
    client_secret: str
    login: str          # Identifiant Chorus Pro (souvent l'email)
    password: str       # Mot de passe Chorus Pro
    env: Environment = Environment.SANDBOX

    @classmethod
    def from_env(cls, env: Environment = Environment.SANDBOX) -> "ChorusConfig":
        """Charge la configuration depuis les variables d'environnement."""
        required = ["CHORUS_CLIENT_ID", "CHORUS_CLIENT_SECRET",
                    "CHORUS_LOGIN", "CHORUS_PASSWORD"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise EnvironmentError(
                f"Variables d'environnement manquantes : {', '.join(missing)}\n"
                f"Copiez .env.example en .env et renseignez vos credentials."
            )
        return cls(
            client_id=os.getenv("CHORUS_CLIENT_ID"),
            client_secret=os.getenv("CHORUS_CLIENT_SECRET"),
            login=os.getenv("CHORUS_LOGIN"),
            password=os.getenv("CHORUS_PASSWORD"),
            env=env,
        )


@dataclass
class SubmissionResult:
    success: bool
    submission_id: Optional[str] = None
    status: Optional[str] = None
    message: str = ""
    raw_response: Optional[dict] = None
    simulated: bool = False

    def __str__(self):
        mode = " [SIMULATION]" if self.simulated else ""
        icon = "✅" if self.success else "❌"
        lines = [
            f"{icon} Résultat{mode} :",
            f"   Message    : {self.message}",
        ]
        if self.submission_id:
            lines.append(f"   ID dépôt   : {self.submission_id}")
        if self.status:
            icon_s, desc = CHORUS_STATUS.get(self.status, ("❓", self.status))
            lines.append(f"   Statut     : {icon_s} {self.status} — {desc}")
        return "\n".join(lines)


# ─────────────────────────────────────────────
# Client Chorus Pro
# ─────────────────────────────────────────────

class ChorusClient:
    def __init__(self, config: ChorusConfig):
        self.config = config
        self._token: Optional[str] = None
        self._token_expiry: float = 0
        self.urls = PISTE_URLS[config.env]

    # ── Auth OAuth2 ──────────────────────────────
    def _get_token(self) -> str:
        """Récupère ou renouvelle le token OAuth2 PISTE."""
        if not HAS_REQUESTS:
            raise ImportError("pip install requests")

        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        creds = base64.b64encode(
            f"{self.config.client_id}:{self.config.client_secret}".encode()
        ).decode()

        resp = requests.post(
            self.urls["token"],
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "password",
                "username": self.config.login,
                "password": self.config.password,
                "scope": "openid",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "cpro-account": self.config.login,
        }

    # ── Dépôt de facture ─────────────────────────
    def submit_invoice(self, xml_path: str,
                       siret_destinataire: str,
                       service_code: Optional[str] = None) -> SubmissionResult:
        """
        Dépose une facture XML auprès de Chorus Pro.

        Args:
            xml_path           : chemin vers le fichier XML Factur-X
            siret_destinataire : SIRET de l'entité publique destinataire
            service_code       : code service de l'entité (optionnel)
        """
        if not HAS_REQUESTS:
            raise ImportError("pip install requests")

        xml_content = Path(xml_path).read_text(encoding="utf-8")
        xml_b64 = base64.b64encode(xml_content.encode("utf-8")).decode()

        payload = {
            "idUtilisateurCourant": self.config.login,
            "fichierFacture": [
                {
                    "nomFichier": Path(xml_path).name,
                    "typeIdentifiantFournisseur": "SIRET",
                    "syntaxeFlux": "IN_DP_E1_CII_FACTURX",
                    "fluxFacture": xml_b64,
                }
            ],
            "siretDestinataire": siret_destinataire,
        }
        if service_code:
            payload["codeServiceExecutant"] = service_code

        try:
            resp = requests.post(
                f"{self.urls['chorus']}/deposer/flux",
                headers=self._headers(),
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return SubmissionResult(
                success=True,
                submission_id=str(data.get("numeroFluxDepot", "")),
                status="DEPOSEE",
                message="Facture déposée avec succès",
                raw_response=data,
            )
        except requests.HTTPError as e:
            err_msg = str(e)
            try:
                err_data = e.response.json()
                err_msg = err_data.get("message", err_msg)
            except Exception:
                pass
            return SubmissionResult(success=False, message=f"Erreur HTTP : {err_msg}")
        except requests.ConnectionError:
            return SubmissionResult(
                success=False,
                message="Impossible de joindre l'API PISTE (vérifiez votre connexion / VPN)"
            )

    # ── Consultation de statut ───────────────────
    def get_status(self, submission_id: str) -> SubmissionResult:
        """Consulte le statut d'un dépôt Chorus Pro."""
        if not HAS_REQUESTS:
            raise ImportError("pip install requests")

        try:
            resp = requests.post(
                f"{self.urls['chorus']}/consulter/flux",
                headers=self._headers(),
                json={
                    "idUtilisateurCourant": self.config.login,
                    "numeroFluxDepot": submission_id,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("listeFactures", [{}])[0].get("statutCourantFlux", "INCONNU")
            return SubmissionResult(
                success=True,
                submission_id=submission_id,
                status=status,
                message=f"Statut récupéré",
                raw_response=data,
            )
        except Exception as e:
            return SubmissionResult(success=False, message=str(e))


# ─────────────────────────────────────────────
# Mode simulation (démo sans credentials)
# ─────────────────────────────────────────────

def simulate_submission(xml_path: str) -> SubmissionResult:
    """
    Simule un dépôt Chorus Pro pour la démo.
    Reproduit le comportement de l'API sans appel réseau.
    """
    # NOTE: stdout sous Windows est parfois en cp1252 ; certains emojis
    # provoquaient un UnicodeEncodeError dans les tests.
    print("\n[Mode SIMULATION] (aucun appel reseau)")
    print("   - Pour un vrai depot, configurez .env avec vos credentials PISTE\n")

    # Vérification basique du fichier
    try:
        content = Path(xml_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return SubmissionResult(
            success=False,
            message=f"Fichier introuvable : {xml_path}",
            simulated=True
        )

    # Simulation des étapes
    steps = [
        ("Authentification OAuth2 PISTE",        0.3),
        ("Encodage Base64 du flux XML",         0.2),
        ("Envoi vers Chorus Pro sandbox",      0.8),
        ("Reception accuse de depot",          0.4),
    ]
    for step, delay in steps:
        print(f"   {step}...")
        time.sleep(delay)

    fake_id = f"DEP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    return SubmissionResult(
        success=True,
        submission_id=fake_id,
        status="DEPOSEE",
        message="Facture déposée avec succès (simulation)",
        raw_response={
            "numeroFluxDepot": fake_id,
            "dateDepot": datetime.now().isoformat(),
            "syntaxeFlux": "IN_DP_E1_CII_FACTURX",
            "taille": len(content),
            "environnement": "SANDBOX_SIMULATION",
        },
        simulated=True,
    )


def simulate_status_progression(submission_id: str) -> list[SubmissionResult]:
    """Simule la progression du statut dans le temps (pour la démo)."""
    workflow = [
        ("DEPOSEE", "Reçue par Chorus Pro", 1),
        ("EN_COURS_TRAITEMENT", "Vérifications en cours", 2),
        ("VALIDEE", "Validée par l'entité publique", 1),
        ("COMPTABILISEE", "Enregistrée en comptabilité", 1),
        ("MISE_EN_PAIEMENT", "Paiement programmé", 0),
    ]
    results = []
    for status, msg, delay in workflow:
        time.sleep(delay * 0.3)  # accéléré pour la démo
        results.append(SubmissionResult(
            success=True,
            submission_id=submission_id,
            status=status,
            message=msg,
            simulated=True,
        ))
    return results


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Envoie une facture vers Chorus Pro")
    parser.add_argument("xml_file", help="Fichier XML Factur-X à envoyer")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Simulation sans appel réseau (défaut)")
    parser.add_argument("--live", action="store_true",
                        help="Vrai appel vers l'API sandbox (nécessite .env)")
    parser.add_argument("--env", choices=["sandbox", "production"], default="sandbox")
    parser.add_argument("--siret-dest", default="13000682900012",
                        help="SIRET entité publique destinataire")
    parser.add_argument("--status", metavar="ID",
                        help="Consulte le statut d'un dépôt existant")
    args = parser.parse_args()

    print("=" * 60)
    print("  CHORUS PRO — Dépôt facture électronique")
    print("=" * 60)

    if args.status:
        # Simulation progression statut
        print(f"\n📊 Suivi du dépôt : {args.status}\n")
        for result in simulate_status_progression(args.status):
            print(result)
        exit(0)

    if args.live:
        # Vrai appel API
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        env = Environment(args.env)
        config = ChorusConfig.from_env(env)
        client = ChorusClient(config)
        result = client.submit_invoice(args.xml_file, args.siret_dest)
    else:
        # Simulation
        result = simulate_submission(args.xml_file)

    print(result)

    if result.success and result.raw_response:
        print("\n📋 Réponse complète :")
        print(json.dumps(result.raw_response, ensure_ascii=False, indent=2))
