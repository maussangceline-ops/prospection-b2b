"""Exécute les vrais SQL dbt sur DuckDB en mémoire, sans API ni S3."""
from pathlib import Path
from datetime import datetime
import unittest
import duckdb
from jinja2 import Environment
ROOT = Path(__file__).resolve().parents[1]

class BonusTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(':memory:')
        self.db.execute('create schema raw')
        self.db.execute("create table int_etablissements_enrichis(siren varchar, siret varchar, date_creation_entreprise date, naf_etablissement varchar)")
        self.db.execute("insert into int_etablissements_enrichis values ('1','100001','2026-02-01','62.01Z')")
        self.db.execute('create table stg_evenements_etablissements(siren varchar,siret_predecesseur varchar,siret_successeur varchar,date_evenement date,type_evenement varchar,qualification varchar,collecte_id varchar)')
        self.db.execute('create table raw.controles_mouvements(siren varchar,statut_couverture varchar,collecte_id varchar)')
        self.db.execute("insert into raw.controles_mouvements values ('1','population_retrouvee','run')")
    def tearDown(self): self.db.close()
    def render(self,path):
        return Environment().from_string((ROOT/path).read_text()).render(
            config=lambda **kw:'',ref=lambda name:name,source=lambda a,b:'raw.'+b,
            var=lambda name,default:'2026-09-23',run_started_at=datetime(2026,9,23))
    def event(self,date='2026-08-01',pred='a',succ='b',kind='transfert_etablissement',qualification='confirme_par_lien'):
        self.db.execute('insert into stg_evenements_etablissements values (?,?,?,?,?,?,?)', ['1',pred,succ,date,kind,qualification,'run'])
    def bonus(self):
        rows=self.db.execute(self.render('dbt_prospection/models/staging/intermediate/int_bonus_transferts.sql')).fetchall()
        return rows[0][3] if rows else 0
    def test_no_event(self): self.assertEqual(self.bonus(),0)
    def test_first(self): self.event(); self.assertEqual(self.bonus(),50)
    def test_following(self):
        for i in range(3): self.event(pred=str(i),succ=str(i+1))
        self.assertEqual(self.bonus(),100)
    def test_duplicate(self): self.event();self.event();self.assertEqual(self.bonus(),50)
    def test_uncertain(self): self.event(qualification='a_verifier');self.assertEqual(self.bonus(),0)
    def test_opening(self): self.event(kind='ouverture_potentielle');self.assertEqual(self.bonus(),0)
    def test_creation_and_future(self):
        self.event(date='2026-02-01');self.event(date='2026-09-24');self.assertEqual(self.bonus(),0)
    def test_window(self):
        self.db.execute("update int_etablissements_enrichis set date_creation_entreprise='2024-01-01'")
        self.event(date='2025-09-23');self.assertEqual(self.bonus(),0)
        self.event(date='2025-09-24');self.assertEqual(self.bonus(),50)
        self.event(date='2026-09-23',pred='b',succ='c');self.assertEqual(self.bonus(),75)
    def test_incomplete(self):
        self.event();self.db.execute("update raw.controles_mouvements set statut_couverture='a_verifier'");self.assertEqual(self.bonus(),0)
    def test_other_collection(self):
        self.event();self.db.execute("update raw.controles_mouvements set collecte_id='old'");self.assertEqual(self.bonus(),0)
    def test_mart_and_anniversary(self):
        self.event()
        self.db.execute('create view int_bonus_transferts as '+self.render('dbt_prospection/models/staging/intermediate/int_bonus_transferts.sql'))
        self.db.execute("create table stg_activite_actuelle as select '100001' siret, date '2026-09-23' date_verification, 'A' statut_etablissement_actuel, 'A' statut_entreprise_actuel, '5710' categorie_juridique_actuelle, 'SAS' libelle_categorie_juridique, 'Actif' etat_activite")
        self.db.execute("create table stg_bodacc_controles as select '1' siren, date '2026-09-23' date_verification_bodacc, 'Aucune procédure repérée' statut_bodacc, '' motif_bodacc, 0 nombre_annonces_bodacc, null date_jugement_bodacc, null nature_jugement_bodacc, null url_annonce_bodacc")
        sql=self.render('dbt_prospection/models/marts/mart_prospects_scores.sql')
        self.db.execute('create table mart_prospects_scores as '+sql)
        self.assertEqual(self.db.execute('select score_total,bonus_transferts,couleur_priorite from mart_prospects_scores').fetchone(),(110,50,'vert'))
        self.assertEqual(self.db.execute(self.render('dbt_prospection/tests/test_coherence_scores.sql')).fetchall(),[])
        self.db.execute("update int_etablissements_enrichis set date_creation_entreprise='2025-09-23'")
        self.db.execute('create or replace table mart_prospects_scores as '+sql)
        self.assertEqual(self.db.execute('select score_total,bonus_transferts,couleur_priorite from mart_prospects_scores').fetchone(),(None,None,None))
        self.assertEqual(self.db.execute(self.render('dbt_prospection/tests/test_coherence_scores.sql')).fetchall(),[])
if __name__ == '__main__': unittest.main()
