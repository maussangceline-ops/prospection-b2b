"""SQL réels, fixtures locales, aucune requête réseau ni donnée de production."""
from datetime import datetime
import json
from pathlib import Path
import unittest
import duckdb
from jinja2 import Environment
ROOT=Path(__file__).resolve().parents[1]

class CapitalScoreTests(unittest.TestCase):
    def setUp(self):
        self.db=duckdb.connect(':memory:')
        self.db.execute('create schema raw')
        self.db.execute('create table raw.capital_variations_a_confirmer(siren varchar,collecte_id varchar,date_collecte date,donnees json)')
        self.db.execute("create table int_etablissements_enrichis as select '1' siren, '100001' siret, date '2026-01-01' date_creation_entreprise, '62.01Z' naf_etablissement")
        self.db.execute('create view stg_capital_variations as '+self.render('models/staging/stg_capital_variations.sql'))
        self.db.execute('create view int_bonus_capital as '+self.render('models/staging/intermediate/int_bonus_capital.sql'))
    def tearDown(self):self.db.close()
    def render(self,path):
        return Environment().from_string((ROOT/'dbt_prospection'/path).read_text()).render(config=lambda **kw:'',ref=lambda n:n,source=lambda a,b:'raw.'+b,var=lambda n,d:'2026-09-24',run_started_at=datetime(2026,9,24))
    def event(self,before=1000,after=2000,day='2026-06-01',previous='2026-01-02',desc='Modification survenue sur le capital.',**kw):
        event=dict(id_annonce_avant='A'+str(before),id_annonce_apres='B'+str(after)+day,date_publication_avant=previous,date_publication_apres=day,capital_avant=str(before),capital_apres=str(after),devise='EUR',variation_observee='hausse' if after>before else 'baisse',descriptif=desc)
        event.update(kw)
        self.db.execute('insert into raw.capital_variations_a_confirmer values (?,?,?,?)',['1','run','2026-09-24',json.dumps(event)])
    def score(self):
        result=self.db.execute('select nombre_hausses_capital_12_mois,nombre_baisses_capital_12_mois,bonus_capital_potentiel from int_bonus_capital').fetchone()
        return result or (0,0,0)
    def test_none(self):self.assertEqual(self.score(),(0,0,0))
    def test_first_raise(self):self.event();self.assertEqual(self.score(),(1,0,50))
    def test_following(self):
        self.event();self.event(2000,3000,'2026-07-01','2026-06-01');self.assertEqual(self.score(),(2,0,75))
    def test_small_decrease(self):self.event(75001,75000);self.assertEqual(self.score(),(0,1,-25))
    def test_mixed(self):self.event(1000,900);self.event(900,1500,'2026-07-01','2026-06-01');self.assertEqual(self.score(),(1,1,25))
    def test_exact_duplicate(self):self.event();self.event();self.assertEqual(self.score(),(1,0,50))
    def test_republished_transition(self):self.event();self.event(day='2026-07-01');self.assertEqual(self.score(),(1,0,50))
    def test_cycle(self):
        self.event();self.event(2000,1000,'2026-07-01','2026-06-01');self.event(1000,2000,'2026-08-01','2026-07-01');self.assertEqual(self.score(),(2,1,50))
    def test_opposite_description(self):self.event(desc='capital (diminution)');self.assertEqual(self.score(),(0,0,0))
    def test_unknown_currency(self):self.event(devise='');self.assertEqual(self.score(),(0,0,0))
    def test_initial_or_missing_baseline(self):self.event(previous='2025-12-31');self.assertEqual(self.score(),(0,0,0))
    def test_future(self):self.event(day='2026-09-25');self.assertEqual(self.score(),(0,0,0))
    def test_window_boundaries(self):
        self.db.execute("update int_etablissements_enrichis set date_creation_entreprise='2024-01-01'")
        self.event(day='2025-09-24',previous='2024-01-02');self.assertEqual(self.score(),(0,0,0))
        self.event(2000,3000,day='2025-09-25',previous='2025-09-24');self.assertEqual(self.score(),(1,0,50))
        self.event(3000,4000,day='2026-09-24',previous='2025-09-25');self.assertEqual(self.score(),(2,0,75))
    def test_mart_exclusions_age_and_total(self):
        self.event()
        self.db.execute("create table int_bonus_transferts as select '1' siren, 1 nombre_transferts_12_mois, date '2026-08-01' date_dernier_transfert,50 bonus_transferts_potentiel")
        self.db.execute("create table stg_activite_actuelle as select '100001' siret, date '2026-09-24' date_verification,'A' statut_etablissement_actuel,'A' statut_entreprise_actuel,'5710' categorie_juridique_actuelle,'SAS' libelle_categorie_juridique,'Actif' etat_activite")
        self.db.execute("create table stg_bodacc_controles as select '1' siren,date '2026-09-24' date_verification_bodacc,'Aucune procédure repérée' statut_bodacc,'' motif_bodacc,0 nombre_annonces_bodacc,null date_jugement_bodacc,null nature_jugement_bodacc,null url_annonce_bodacc")
        sql=self.render('models/marts/mart_prospects_scores.sql')
        self.db.execute('create table mart_prospects_scores as '+sql)
        self.assertEqual(self.db.execute('select score_total,bonus_capital,admissible_prospection from mart_prospects_scores').fetchone(),(160,50,True))
        self.assertEqual(self.db.execute(self.render('tests/test_coherence_scores.sql')).fetchall(),[])
        self.db.execute("update stg_activite_actuelle set etat_activite='Inactif'")
        self.db.execute('create or replace table mart_prospects_scores as '+sql)
        self.assertFalse(self.db.execute('select admissible_prospection from mart_prospects_scores').fetchone()[0])
        self.db.execute("update int_etablissements_enrichis set date_creation_entreprise='2025-09-24'")
        self.db.execute('create or replace table mart_prospects_scores as '+sql)
        self.assertEqual(self.db.execute('select score_total,bonus_capital,couleur_priorite from mart_prospects_scores').fetchone(),(None,None,None))
        self.assertEqual(self.db.execute(self.render('tests/test_coherence_scores.sql')).fetchall(),[])
if __name__=='__main__':unittest.main()
