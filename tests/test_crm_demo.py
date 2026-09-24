import sys
from pathlib import Path
from datetime import date
import unittest
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
import crm_store as store
from streamlit.testing.v1 import AppTest

class RulesTests(unittest.TestCase):
    def test_required_end(self):
        for status in ['Contrat en cours','Renouvellement']:
            with self.assertRaises(ValueError):store.validate('123456789',dict(store.empty_record('123456789'),statut=status))
    def test_optional_dates(self):
        self.assertIsNone(store.validate('123456789',store.empty_record('123456789'))['date_fin_contrat'])
    def test_last_contact_future(self):
        with self.assertRaises(ValueError):store.validate('123456789',dict(store.empty_record('123456789'),date_dernier_contact=date(2030,1,1)),date(2026,9,24))
    def test_contacts(self):
        r=store.empty_record('123456789');r.update(contact_email='camille@example.com',contact_telephone='+33 6 00 00 00 00')
        self.assertEqual(store.validate('123456789',r)['contact_telephone'],r['contact_telephone'])
        for field,value in [('contact_email','sans-arobase'),('contact_telephone','abc'),('notes','x'*5001)]:
            with self.assertRaises(ValueError):store.validate('123456789',dict(r,**{field:value}))
    def test_renewal_month_end(self):
        end=date(2027,3,31)
        self.assertEqual(store.renewal_alert('Contrat en cours',end,date(2027,2,27)),'')
        self.assertEqual(store.renewal_alert('Contrat en cours',end,date(2027,2,28)),'Renouvellement à préparer')
        self.assertEqual(store.renewal_alert('Contrat en cours',end,end),'Renouvellement à préparer')
        self.assertEqual(store.renewal_alert('Contrat en cours',end,date(2027,4,1)),'Contrat arrivé à échéance')
    def test_leap_year(self):
        self.assertEqual(store.renewal_alert('Renouvellement',date(2028,3,31),date(2028,2,28)),'')
        self.assertTrue(store.renewal_alert('Renouvellement',date(2028,3,31),date(2028,2,29)))
    def test_non_contract(self):
        self.assertEqual(store.renewal_alert('Refus',date(2020,1,1)), '')
    def test_update_version_and_parameters(self):
        conn=MagicMock();ctx=MagicMock();ctx.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={'version':2}
        data=store.empty_record('123456789');data['notes']="test '; drop table suivi; --"
        with patch.object(store,'connect',return_value=ctx):store.save_record('fake','123456789',data,1)
        sql,params=conn.execute.call_args.args
        self.assertIn('and version=%s',sql);self.assertNotIn(data['notes'],sql)
        self.assertIn(data['notes'],params);self.assertEqual(params[-1],1)
    def test_conflict(self):
        conn=MagicMock();ctx=MagicMock();ctx.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value=None
        with patch.object(store,'connect',return_value=ctx):
            with self.assertRaises(store.ConflictError):store.save_record('fake','123456789',store.empty_record('123456789'),0)
        self.assertEqual(ctx.__exit__.call_args.args[0],store.ConflictError)

class FormTests(unittest.TestCase):
    def test_validation_and_save(self):
        code="""import sys
sys.path.insert(0, DASHBOARD)
import crm_ui
crm_ui.editor('123456789','fake')
""".replace('DASHBOARD',repr(str(Path(__file__).resolve().parents[1]/'dashboard')))
        with patch('crm_ui.read_record',return_value=store.empty_record('123456789')),patch('crm_ui.save_record') as save:
            at=AppTest.from_string(code).run();self.assertFalse(at.exception)
            at.selectbox[0].set_value('Contrat en cours')
            # Use the real validator via mocked persistence: missing end rejected.
            save.side_effect=lambda d,s,v,e: store.validate(s,v)
            at.button[-1].click().run()
            self.assertTrue(at.error);self.assertIn('obligatoire',at.error[0].value)
            at.date_input[2].set_value(date(2027,3,31))
            save.side_effect=lambda d,s,v,e:dict(store.validate(s,v),siren=s,version=1)
            at.button[-1].click().run();self.assertFalse(at.exception)
            self.assertTrue(at.success)
    def test_offline(self):
        code="import sys\nsys.path.insert(0,"+repr(str(Path(__file__).resolve().parents[1]/'dashboard'))+")\nimport crm_ui\ncrm_ui.editor('123456789','fake')"
        with patch('crm_ui.read_record',side_effect=RuntimeError('secret-not-for-ui')):
            at=AppTest.from_string(code).run();self.assertFalse(at.exception)
            self.assertTrue(at.error);self.assertNotIn('secret-not-for-ui',at.error[0].value)
if __name__=='__main__':unittest.main()

class FollowupViewTests(unittest.TestCase):
    def test_records_do_not_reintroduce_excluded_companies(self):
        code="""import sys
sys.path.insert(0, DASHBOARD)
import pandas as pd
import crm_ui
crm_ui.suivi(pd.DataFrame([{'siren':'123456789','siret':'12345678900001','nom_affiche':'Entreprise de démonstration'}]),'fake',lambda row:None)
""".replace('DASHBOARD',repr(str(Path(__file__).resolve().parents[1]/'dashboard')))
        records=[dict(siren=s,statut='À contacter',date_dernier_contact=None,date_relance=None,
                      date_fin_contrat=None,updated_at=None,version=1) for s in ['123456789','999999999']]
        with patch('crm_ui.list_records',return_value=records),patch('crm_ui.editor'):
            at=AppTest.from_string(code).run();self.assertFalse(at.exception)
            self.assertEqual(at.metric[0].value,'1')
