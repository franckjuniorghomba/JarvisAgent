"""Fusion encadrée d'une PR vers `dev` par le chef d'orchestre.

Le chef n'a pas le droit d'appeler `gh pr merge` : il passe par `jarvis fusionner-dev`,
qui vérifie techniquement chaque condition avant de fusionner. Aucune PR qui cible
une autre branche que `dev` (donc jamais `main`) ne peut passer par ici.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

BRANCHE_CIBLE = "dev"
CHAMPS = "number,title,state,isDraft,baseRefName,headRefOid,mergeable,statusCheckRollup,reviews,commits,url"
# Ligne attendue dans la contre-relecture : « VERDICT : PRÊT » (accents et espaces tolérés).
VERDICT_PRET = re.compile(r"^\s*\**\s*VERDICT\s*:\s*PR[ÊE]T\b", re.IGNORECASE | re.MULTILINE)
CHECK_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}


class FusionRefusee(Exception):
    pass


def _gh(args: list[str], cwd: Path) -> str:
    try:
        res = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise FusionRefusee("gh est introuvable") from exc
    except subprocess.TimeoutExpired as exc:
        raise FusionRefusee("gh n'a pas répondu à temps") from exc
    if res.returncode != 0:
        raise FusionRefusee((res.stderr or res.stdout).strip() or f"gh {' '.join(args)} a échoué")
    return res.stdout


def lire_pr(numero: int, cwd: Path) -> dict:
    return json.loads(_gh(["pr", "view", str(numero), "--json", CHAMPS], cwd))


def _etat_check(c: dict) -> tuple[str, str]:
    nom = c.get("name") or c.get("context") or "?"
    if c.get("__typename") == "StatusContext" or "context" in c:
        return nom, (c.get("state") or "").upper()
    if (c.get("status") or "").upper() not in ("COMPLETED", ""):
        return nom, "EN_COURS"
    return nom, (c.get("conclusion") or "").upper()


def _date_dernier_commit(pr: dict) -> str:
    dates = [c.get("committedDate") or "" for c in pr.get("commits") or []]
    return max(dates) if dates else ""


def verdict_pret(pr: dict) -> bool:
    """Une relecture « VERDICT : PRÊT » publiée sur le dernier commit de la PR."""
    tete = pr.get("headRefOid")
    dernier = _date_dernier_commit(pr)
    for r in pr.get("reviews") or []:
        if not VERDICT_PRET.search(r.get("body") or ""):
            continue
        oid = (r.get("commit") or {}).get("oid")
        if oid:
            if oid == tete:
                return True
        elif (r.get("submittedAt") or "") >= dernier:
            return True
    return False


def verifier(pr: dict) -> list[str]:
    """Renvoie la liste des raisons de refuser la fusion (vide = fusion autorisée)."""
    raisons = []
    if pr.get("baseRefName") != BRANCHE_CIBLE:
        raisons.append(f"la PR cible « {pr.get('baseRefName')} », pas « {BRANCHE_CIBLE} » "
                       f"(la fusion vers une autre branche appartient à ton humain)")
    if pr.get("state") != "OPEN":
        raisons.append(f"la PR n'est pas ouverte (état : {pr.get('state')})")
    if pr.get("isDraft"):
        raisons.append("la PR est un brouillon")
    if pr.get("mergeable") == "CONFLICTING":
        raisons.append("la PR a des conflits avec dev")
    checks = [_etat_check(c) for c in pr.get("statusCheckRollup") or []]
    if not checks:
        raisons.append("aucune CI n'a tourné sur cette PR")
    else:
        mauvais = [f"{n} ({e.lower() or 'inconnu'})" for n, e in checks if e not in CHECK_OK]
        if mauvais:
            raisons.append("CI pas verte : " + ", ".join(mauvais))
    if not verdict_pret(pr):
        raisons.append("aucune contre-relecture « VERDICT : PRÊT » sur le dernier commit")
    return raisons


def fusionner(numero: int, cwd: Path) -> dict:
    pr = lire_pr(numero, cwd)
    raisons = verifier(pr)
    if raisons:
        raise FusionRefusee("; ".join(raisons))
    # --match-head-commit : si un commit arrive entre la vérification et la fusion, GitHub refuse.
    _gh(["pr", "merge", str(numero), "--squash", "--match-head-commit", pr["headRefOid"]], cwd)
    return pr
