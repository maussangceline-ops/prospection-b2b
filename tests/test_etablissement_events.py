import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collect_etablissement_events import detecter

A='12345678900001';B='12345678900002';C='12345678900003'
def etab(siret,jour): return {'siret':siret,'dateCreationEtablissement':jour}
def lien(a=A,b=B): return {'siretEtablissementPredecesseur':a,'siretEtablissementSuccesseur':b,'dateLienSuccession':'2026-06-01'}
class Tests(unittest.TestCase):
    def run_detection(self,etabs,liens):return detecter(etabs,liens,{'123456789':'2026-01-01'},'2026-09-23')
    def test_initial(self):
        r=self.run_detection([etab(A,'2026-01-01')],[])
        self.assertEqual(r[0][6],'hors_perimetre')
    def test_premier_etablissement_plus_tard_pas_bonus(self):
        r=self.run_detection([etab(A,'2026-01-15')],[])
        self.assertEqual(r[0][6],'hors_perimetre')
    def test_ouverture_non_prouvee(self):
        r=self.run_detection([etab(A,'2026-01-01'),etab(B,'2026-06-01')],[])
        self.assertEqual(sum(e[2]=='ouverture_potentielle' and e[6]=='a_confirmer' for e in r),1)
    def test_transfert_pas_double_ouverture(self):
        r=self.run_detection([etab(A,'2026-01-01'),etab(B,'2026-06-01')],[lien()])
        self.assertEqual(sum(e[2]=='transfert_etablissement' for e in r),1)
        self.assertFalse(any(e[2]=='ouverture_potentielle' for e in r))
    def test_dedoublonnage(self):
        es=[etab(A,'2026-01-01'),etab(B,'2026-06-01')]
        self.assertEqual(self.run_detection(es,[lien()]),self.run_detection(es,[lien(),lien()]))
    def test_scission(self):
        r=self.run_detection([etab(A,'2026-01-01'),etab(B,'2026-06-01'),etab(C,'2026-06-01')],[lien(),lien(b=C)])
        self.assertEqual(sum(e[2]=='transfert_complexe' for e in r),2)
        self.assertFalse(any(e[6]=='confirme_par_lien' for e in r))
    def test_changement_exploitant(self):
        r=self.run_detection([etab(B,'2026-06-01')],[lien(a='98765432100001')])
        self.assertEqual(r[0][2],'reprise_activite')
    def test_futur(self):
        l=lien();l['dateLienSuccession']='2027-01-01'
        r=self.run_detection([etab(A,'2026-01-01'),etab(B,'2027-01-01')],[l])
        self.assertTrue(all(e[6]=='hors_perimetre' for e in r))
    def test_date_absente(self):
        l=lien();l['dateLienSuccession']=None
        r=self.run_detection([etab(A,'2026-01-01'),etab(B,'2026-06-01')],[l])
        self.assertTrue(any(e[6]=='a_verifier' for e in r))
if __name__=='__main__':unittest.main()
