import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError
from dashboard.storage_client import storage_client
from migrate_s3_to_r2 import copy_one
import one_off_update as guard


def missing():
    return ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')

def response(data=b'abc', metadata=None):
    return {'Body': io.BytesIO(data), 'Metadata': metadata or {}}

class StorageTests(unittest.TestCase):
    def test_explicit_r2_credentials(self):
        values={'R2_ENDPOINT_URL':'https://example.r2.cloudflarestorage.com','R2_ACCESS_KEY_ID':'r2-id','R2_SECRET_ACCESS_KEY':'r2-secret','R2_BUCKET_NAME':'bucket'}
        with patch('dashboard.storage_client.boto3.client') as factory:
            storage_client(values.get)
            self.assertEqual(factory.call_args.kwargs['region_name'],'auto')
            self.assertEqual(factory.call_args.kwargs['aws_access_key_id'],'r2-id')
    def test_no_aws_fallback(self):
        with self.assertRaises(ValueError): storage_client({}.get)
    def test_reject_other_endpoint(self):
        values={k:'x' for k in ['R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET_NAME']}
        values['R2_ENDPOINT_URL']='https://s3.amazonaws.com'
        with self.assertRaises(ValueError): storage_client(values.get)

class CopyTests(unittest.TestCase):
    def copy(self, remote):
        source=Mock();source.get_object.return_value=response()
        target=Mock();target.get_object.side_effect=remote
        with tempfile.TemporaryDirectory() as folder:
            result=copy_one(source,target,'aws','r2','raw/a.json',{'etag':'etag','size':3},Path(folder))
            self.assertEqual((Path(folder)/result['backup_file']).read_bytes(),b'abc')
        return target
    def test_new_object_verified(self):
        target=self.copy([missing(),response()])
        self.assertEqual(target.put_object.call_args.kwargs['IfNoneMatch'],'*')
        self.assertEqual(target.put_object.call_args.kwargs['Key'],'raw/a.json')
    def test_identical_resume_no_write(self):
        self.copy([response()]).put_object.assert_not_called()
    def test_different_object_refused(self):
        with self.assertRaises(RuntimeError): self.copy([response(b'bad')])
    def test_corrupt_upload_refused(self):
        with self.assertRaises(RuntimeError): self.copy([missing(),response(b'bad')])

class GuardTests(unittest.TestCase):
    def test_other_dates_never_access_storage(self):
        client=Mock()
        for day in [date(2026,9,30),date(2026,10,2),date(2027,10,1)]:
            self.assertFalse(guard.should_run(client,'bucket',day))
        client.get_object.assert_not_called()
    def test_first_run_allowed(self):
        client=Mock();client.get_object.side_effect=[missing(),response()]
        self.assertTrue(guard.should_run(client,'bucket',guard.TARGET_DATE))
    def test_success_blocks_repeat(self):
        client=Mock();client.get_object.return_value=response(json.dumps({'publication_id':guard.PUBLICATION_ID,'status':'success'}).encode())
        self.assertFalse(guard.should_run(client,'bucket',guard.TARGET_DATE))
        self.assertEqual(client.get_object.call_count,1)
    def test_recovery_after_publication(self):
        client=Mock();client.get_object.side_effect=[missing(),response(metadata={'publication-id':guard.PUBLICATION_ID,'sha256':hashlib.sha256(b'abc').hexdigest()})]
        self.assertFalse(guard.should_run(client,'bucket',guard.TARGET_DATE))
        self.assertEqual(client.put_object.call_args.kwargs['Key'],guard.MARKER)
    def test_invalid_hash_blocks_marker(self):
        client=Mock()
        with self.assertRaises(RuntimeError): guard.write_success(client,'bucket',{'Metadata':{'publication-id':guard.PUBLICATION_ID,'sha256':'bad'}},b'abc')
        client.put_object.assert_not_called()
    def test_access_denied_not_treated_as_missing(self):
        client=Mock();client.get_object.side_effect=ClientError({'Error':{'Code':'AccessDenied'}},'GetObject')
        with self.assertRaises(ClientError): guard.should_run(client,'bucket',guard.TARGET_DATE)
    def test_invalid_marker_blocks_run(self):
        client=Mock();client.get_object.return_value=response(b'{}')
        with self.assertRaises(RuntimeError): guard.should_run(client,'bucket',guard.TARGET_DATE)

if __name__=='__main__':unittest.main()
