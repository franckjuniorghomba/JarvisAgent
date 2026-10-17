"""Tests de la fusion encadrée vers dev (logique pure, sans réseau ni tmux)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from jarvis import fusion  # noqa: E402

TETE = "abc123"


def pr(**changes) -> dict:
    base = {
        "number": 12, "title": "Ajout 2FA", "state": "OPEN", "isDraft": False,
        "baseRefName": "dev", "headRefOid": TETE, "mergeable": "MERGEABLE",
        "statusCheckRollup": [{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "reviews": [{"body": "RAS.\n\nVERDICT : PRÊT", "commit": {"oid": TETE}, "submittedAt": "2026-10-13T10:00:00Z"}],
        "commits": [{"committedDate": "2026-10-13T09:00:00Z"}],
    }
    base.update(changes)
    return base


class FusionTest(unittest.TestCase):
    def test_pr_conforme_acceptee(self):
        self.assertEqual(fusion.verifier(pr()), [])

    def test_main_toujours_refusee(self):
        raisons = fusion.verifier(pr(baseRefName="main"))
        self.assertTrue(any("main" in r for r in raisons))

    def test_ci_rouge_en_cours_ou_absente(self):
        rouge = [{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}]
        en_cours = [{"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]
        statut = [{"__typename": "StatusContext", "context": "vercel", "state": "PENDING"}]
        for checks in (rouge, en_cours, statut, []):
            self.assertTrue(fusion.verifier(pr(statusCheckRollup=checks)), checks)

    def test_verdict_absent_ou_negatif(self):
        self.assertTrue(fusion.verifier(pr(reviews=[])))
        mauvais = [{"body": "VERDICT : À CORRIGER\n- tests", "commit": {"oid": TETE}}]
        self.assertTrue(fusion.verifier(pr(reviews=mauvais)))

    def test_verdict_sur_ancien_commit_refuse(self):
        vieux = [{"body": "VERDICT : PRÊT", "commit": {"oid": "ancien"}}]
        self.assertTrue(fusion.verifier(pr(reviews=vieux)))

    def test_verdict_sans_accent_et_sans_oid(self):
        r = [{"body": "**VERDICT : PRET**", "submittedAt": "2026-10-13T10:00:00Z"}]
        self.assertEqual(fusion.verifier(pr(reviews=r)), [])
        r_avant = [{"body": "VERDICT : PRÊT", "submittedAt": "2026-10-13T08:00:00Z"}]
        self.assertTrue(fusion.verifier(pr(reviews=r_avant)))

    def test_brouillon_ferme_conflit(self):
        for changes in ({"isDraft": True}, {"state": "MERGED"}, {"mergeable": "CONFLICTING"}):
            self.assertTrue(fusion.verifier(pr(**changes)), changes)


if __name__ == "__main__":
    unittest.main()
