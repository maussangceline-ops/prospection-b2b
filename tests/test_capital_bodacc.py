import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collect_capital_bodacc import montant, observation, comparer, recuperer_lot
import tempfile

SIREN='123456789'
def annonce(value='1000',day='2026-01-01',ident='a',**kwargs):
    row=dict(id=ident,dateparution=day,typeavis='annonce',familleavis='modification',
      listepersonnes=json.dumps({'personne':{'numeroImmatriculation':{'numeroIdentification':'123 456 789'},'capital':{'montantCapital':value,'devise':'EUR'}}}),
      modificationsgenerales=json.dumps({'descriptif':'Modification survenue sur le capital.'}))
    row.update(kwargs);return row
class CapitalTests(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(montant('10\u202f000,50'),'10000.50')
        for value in ('1.000,50','NaN','-2',None,True,'100 EUR'):self.assertIsNone(montant(value))
    def test_exact_siren(self): self.assertEqual(observation(annonce(),'999999999')['statut_observation'],'personne_absente_ou_ambigue')
    def test_initial_only(self): self.assertEqual(comparer([observation(annonce(),SIREN)]),[])
    def test_increase_decrease(self):
        rows=[observation(annonce(v,d,i),SIREN) for v,d,i in [('1000','2026-01-01','a'),('2000','2026-03-01','b'),('1500','2026-04-01','c')]]
        results=comparer(rows)
        self.assertEqual([r['variation_observee'] for r in results],['hausse','baisse'])
        self.assertTrue(all(r['date_effet'] is None and r['qualification']=='a_confirmer' for r in results))
    def test_identical(self):
        self.assertEqual(comparer([observation(annonce(day=d,ident=d),SIREN) for d in ['2026-01-01','2026-03-01']]),[])
    def test_dedup(self):
        a=observation(annonce(),SIREN);b=observation(annonce('2000','2026-03-01','b'),SIREN)
        self.assertEqual(len(comparer([a,b,b])),1)
    def test_rectification(self):
        a=observation(annonce(),SIREN);b=observation(annonce('2000','2026-03-01','b',typeavis='rectificatif'),SIREN)
        self.assertEqual(comparer([a,b]),[])
    def test_same_day(self):
        self.assertEqual(comparer([observation(annonce(),SIREN),observation(annonce('2000',ident='b'),SIREN)]),[])
    def test_currency(self):
        a=observation(annonce(),SIREN);b=observation(annonce('2000','2026-03-01','b'),SIREN);b['devise']='USD'
        self.assertEqual(comparer([a,b]),[])
    def test_unreadable_breaks_chain(self):
        rows=[observation(annonce(v,d,d),SIREN) for v,d in [('1000','2026-01-01'),('inconnu','2026-02-01'),('2000','2026-03-01')]]
        self.assertEqual(comparer(rows),[])
    def test_pagination_incomplete(self):
        response=SimpleNamespace(content=b'{}',json=lambda:dict(total_count=2,results=[]))
        fake=SimpleNamespace(demander=lambda *a:response,sirens_annonce=lambda a:{SIREN})
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'collect_bodacc':fake}):
            with self.assertRaisesRegex(RuntimeError,'incomplète'):recuperer_lot(None,[SIREN],'2026-09-24',Path(folder),1)
if __name__=='__main__':unittest.main()
