"""Tests fictifs : aucune requête réseau ni écriture S3."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_bodacc as bodacc


def annonce(identifiant='a1', nature="Jugement d'ouverture d'une procédure de sauvegarde",
            jugement='2026-08-01', publication='2026-08-03', siren='123456789', avis='annonce'):
    return {'id': identifiant, 'dateparution': publication, 'typeavis': avis,
            'registre': [siren, f'{siren[:3]} {siren[3:6]} {siren[6:]}'],
            'tribunal': 'Tribunal de test', 'jugement': json.dumps({
                'nature': nature, 'date': jugement, 'type': 'initial'})}


class Reponse:
    def __init__(self, results, total=None):
        self.content = json.dumps({'total_count': len(results) if total is None else total,
                                   'results': results}).encode()
    def json(self):
        return json.loads(self.content)


class TestQualification(unittest.TestCase):
    def qualifier(self, annonces):
        return bodacc.qualifier(annonces, '2026-09-23')[0]

    def test_aucune_annonce(self):
        self.assertEqual(self.qualifier([]), 'Aucune procédure repérée')

    def test_sauvegarde(self):
        self.assertEqual(self.qualifier([annonce()]), 'Exclusion — sauvegarde')

    def test_redressement(self):
        self.assertEqual(self.qualifier([annonce(nature="Jugement d'ouverture d'une procédure de redressement judiciaire")]), 'Exclusion — redressement')

    def test_suivi_ne_change_pas_ouverture(self):
        self.assertEqual(self.qualifier([annonce(), annonce('a2', "Dépôt de l'état des créances", '2026-09-01')]), 'Exclusion — sauvegarde')

    def test_plan_cloture_liquidation_ne_sont_pas_ouverture(self):
        for nature in ['Jugement arrêtant le plan de sauvegarde', 'Jugement de clôture pour extinction du passif', 'Jugement de conversion en liquidation judiciaire']:
            with self.subTest(nature=nature):
                self.assertEqual(self.qualifier([annonce(), annonce('a2', nature, '2026-09-01')]), 'À vérifier')

    def test_date_jugement_prime_sur_publication(self):
        self.assertEqual(self.qualifier([annonce(jugement='2026-09-01', publication='2026-09-02'),
            annonce('a2', "Dépôt de l'état des créances", '2026-08-01', '2026-09-20')]), 'Exclusion — sauvegarde')

    def test_rectificatif_date_inconnue_future(self):
        for item in [annonce(avis='rectificatif'), annonce(jugement=None), annonce(jugement='2027-01-01')]:
            self.assertEqual(self.qualifier([item]), 'À vérifier')

    def test_dates_francaises(self):
        self.assertEqual(bodacc.date_jugement('1er février 2026'), '2026-02-01')
        self.assertIsNone(bodacc.date_jugement('31 février 2026'))

    def test_siren_exact(self):
        self.assertEqual(bodacc.sirens_annonce(annonce()), {'123456789'})

    def test_jugements_contradictoires(self):
        self.assertEqual(self.qualifier([annonce(), annonce('a2', "Jugement d'ouverture d'une procédure de redressement judiciaire")]), 'À vérifier')

    def test_plusieurs_tribunaux(self):
        autre=annonce('a2'); autre['tribunal']='Autre tribunal'
        self.assertEqual(self.qualifier([annonce(),autre]), 'À vérifier')

    def test_pagination_incomplete(self):
        with tempfile.TemporaryDirectory() as dossier, patch.object(bodacc,'demander',side_effect=[Reponse([annonce()],2),Reponse([],2)]):
            with self.assertRaises(RuntimeError):
                bodacc.recuperer_lot(None,['123456789'],'2026-09-23',Path(dossier),1)

    def test_pagination_dupliquee(self):
        with tempfile.TemporaryDirectory() as dossier, patch.object(bodacc,'demander',side_effect=[Reponse([annonce()],2),Reponse([annonce()],2)]):
            with self.assertRaises(RuntimeError):
                bodacc.recuperer_lot(None,['123456789'],'2026-09-23',Path(dossier),1)

    def test_collecte_complete_et_echec_preserve_table(self):
        with tempfile.TemporaryDirectory() as dossier:
            racine=Path(dossier); db=racine/'test.duckdb'
            with duckdb.connect(str(db)) as conn:
                conn.execute('create schema raw')
                conn.execute("create table raw.sirene_etablissements as select * from (values ('12345678900001'),('98765432100001')) t(siret)")
            with patch.object(bodacc,'ROOT',racine), patch.dict(os.environ,{'DUCKDB_PATH':str(db)}), patch.object(sys,'argv',['collect_bodacc.py','--local-only']), patch.object(bodacc,'demander',return_value=Reponse([annonce()])):
                bodacc.main()
            with duckdb.connect(str(db)) as conn:
                avant=conn.execute('select * from raw.bodacc_controles order by siren').fetchall()
                self.assertEqual(len(avant),2)
                self.assertEqual(avant[0][3],'Exclusion — sauvegarde')
                self.assertEqual(avant[1][3],'Aucune procédure repérée')
            with patch.object(bodacc,'ROOT',racine), patch.dict(os.environ,{'DUCKDB_PATH':str(db)}), patch.object(sys,'argv',['collect_bodacc.py','--local-only']), patch.object(bodacc,'demander',side_effect=RuntimeError('Panne simulée')):
                with self.assertRaises(RuntimeError):bodacc.main()
            with duckdb.connect(str(db)) as conn:
                self.assertEqual(avant,conn.execute('select * from raw.bodacc_controles order by siren').fetchall())


if __name__ == '__main__':
    unittest.main()
