import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import duckdb
import pandas as pd
from streamlit.testing.v1 import AppTest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dashboard_pro',ROOT/'dashboard/app.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)

def fixtures():
    rows=[]
    for i in range(8):
        rows.append(dict(siren=f'{i+1:09}',siret=f'{i+1:09}00001',nom_affiche=f'Entreprise {i}',
            nom_commune='Paris 14e Arrondissement',nom_departement='Paris',code_departement='75',
            naf_etablissement='62.01Z',libelle_age='Newbies',couleur_priorite='vert' if i%2==0 else 'orange',
            score_total=110 if i%2==0 else 60,date_creation_entreprise='2026-02-01',date_evaluation='2026-09-24',
            mois_collecte='2026-02',angle_commercial='Clarifier votre offre.',anciennete_jours=235,
            admissible_prospection=True,disponibilite_nom='Disponible',categorie_juridique_actuelle='5710',
            codes_postaux_commune='75014',score_anciennete=50,bonus_naf=10,bonus_transferts=50 if i%2==0 else 0,
            bonus_capital=0,nombre_transferts_12_mois=1 if i%2==0 else 0,
            nombre_hausses_capital_12_mois=0,nombre_baisses_capital_12_mois=0))
    rows[4]['nom_affiche']='ND';rows[5]['nom_affiche']='NR';rows[6]['admissible_prospection']=False
    rows[7]['score_total']=None;rows[7]['couleur_priorite']=None;rows[7]['libelle_age']='1 an'
    return pd.DataFrame(rows)

class DataTests(unittest.TestCase):
    def test_exclusions_and_labels(self):
        df=app.preparer_donnees(fixtures(),{'5710':'Société par actions simplifiée'})
        self.assertEqual(len(df),5);self.assertEqual(df['nom_commune'].unique().tolist(),['Paris 14e'])
        self.assertNotIn('ND',df['nom_affiche'].tolist())
    def test_search_priority(self):
        df=app.preparer_donnees(fixtures(),{})
        self.assertEqual(len(app.filtrer(df,{},priorite='🟢 Prioritaire')),2)
        self.assertEqual(len(app.filtrer(df,{},recherche='000000001')),1)
        self.assertEqual(len(app.filtrer(df,{},recherche='[')),0)
    def test_events(self):
        df=app.preparer_donnees(fixtures(),{})
        self.assertEqual(len(app.filtrer(df,{},signal='Transfert confirmé')),2)
    def test_csv_formula(self):
        df=app.preparer_donnees(fixtures(),{})
        df.loc[df.index[0],'nom_affiche']='=HYPERLINK("x")'
        text=app.exporter_csv(df).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK",text)
        self.assertNotIn('admissible_prospection',text)
        self.assertEqual(list(app.DISPLAY.values())[1:3],['Priorité','Angle commercial'])
    def test_missing_column(self):
        with self.assertRaises(ValueError):app.preparer_donnees(fixtures().drop(columns='siret'),{})
    def test_duplicate(self):
        df=fixtures();df.loc[1,'siret']=df.loc[0,'siret']
        with self.assertRaises(ValueError):app.preparer_donnees(df,{})

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'dashboard').mkdir()
        for name in ['app.py','crm_ui.py','crm_store.py']:
            shutil.copy(ROOT/'dashboard'/name,self.root/'dashboard'/name)
        (self.root/'dashboard/categories_juridiques.json').write_text(json.dumps({'libelles':{'5710':'Société par actions simplifiée'}}))
        db=self.root/'test.duckdb'
        with duckdb.connect(str(db)) as c:
            fixture=fixtures();c.register('fixture',fixture);c.execute('create schema analytics');c.execute('create table analytics.mart_prospects_scores as select * from fixture')
        self.env=patch.dict(os.environ,{'DATA_SOURCE':'local','DUCKDB_PATH':str(db)});self.env.start()
        self.at=AppTest.from_file(str(self.root/'dashboard/app.py'),default_timeout=30)
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_navigation_filters_and_reset(self):
        at=self.at.run();self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value,'5')
        at.radio(key='filtre_priorite').set_value('🟢 Prioritaire').run()
        self.assertEqual(at.metric[0].value,'2')
        at.text_input(key='filtre_recherche').set_value('introuvable').run()
        self.assertEqual(at.metric[0].value,'0');self.assertFalse(at.exception)
        at.button[0].click().run();self.assertEqual(at.metric[0].value,'5')
        at.radio(key='navigation').set_value('Vue d’ensemble').run();self.assertFalse(at.exception)
        at.radio(key='navigation').set_value('Méthode').run();self.assertFalse(at.exception)
    def test_details(self):
        at=self.at.run()
        # Test de rendu de fiche indépendamment du clic navigateur.
        code="import importlib.util\nspec=importlib.util.spec_from_file_location('d',"+repr(str(ROOT/'dashboard/app.py'))+")\nd=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)\nimport pandas as pd\nrow=pd.Series("+repr(fixtures().iloc[0].to_dict())+")\nrow['activite']='Programmation informatique'; row['priorite']='🟢 Prioritaire';row['departement']='75 — Paris';row['libelle_categorie_juridique']='SAS';row['date_creation_entreprise']=pd.Timestamp('2026-02-01')\nd.fiche(row)"
        detail=AppTest.from_string(code).run();self.assertFalse(detail.exception)
        self.assertEqual(detail.metric[0].value,'110')
if __name__=='__main__':unittest.main()
