"""Garde de publication unique : septembre 2026, le 1er octobre 2026 UTC."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone, date
from botocore.exceptions import ClientError
from dashboard.storage_client import storage_client

TARGET_DATE = date(2026,10,1)
PUBLICATION_ID = 'final-2026-10-01'
MARKER = 'control/updates/2026-10-01.success.json'
CURRENT = 'processed/prospects/current.parquet'

def allowed_day(day):
    return day == TARGET_DATE

def get_optional(client,bucket,key):
    try:
        response=client.get_object(Bucket=bucket,Key=key)
    except ClientError as error:
        if error.response['Error']['Code'] in ('404','NoSuchKey','NotFound'):
            return None,None
        raise
    with response['Body'] as stream:
        data=stream.read()
    return response,data

def completed(client,bucket):
    _,body=get_optional(client,bucket,MARKER)
    if body is None:return False
    record=json.loads(body)
    if record.get('publication_id') != PUBLICATION_ID or record.get('status') != 'success':
        raise RuntimeError('Marqueur de publication invalide : contrôle manuel requis.')
    return True

def write_success(client,bucket,response,data):
    metadata=response.get('Metadata',{})
    digest=hashlib.sha256(data).hexdigest()
    if metadata.get('publication-id') != PUBLICATION_ID or metadata.get('sha256') != digest:
        raise RuntimeError('Publication finale absente ou empreinte invalide : aucun marqueur écrit.')
    record={'publication_id':PUBLICATION_ID,'status':'success','month':'2026-09',
            'sha256':digest,'completed_at':datetime.now(timezone.utc).isoformat()}
    client.put_object(Bucket=bucket,Key=MARKER,Body=json.dumps(record).encode(),
                      ContentType='application/json',IfNoneMatch='*')

def should_run(client,bucket,day):
    if not allowed_day(day):return False
    if completed(client,bucket):return False
    # Recover if current.parquet was published but the runner stopped before its marker.
    response,data=get_optional(client,bucket,CURRENT)
    if response and response.get('Metadata',{}).get('publication-id') == PUBLICATION_ID:
        write_success(client,bucket,response,data)
        return False
    return True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','complete'])
    args=parser.parse_args()
    day=datetime.now(timezone.utc).date()
    if not allowed_day(day):
        raise SystemExit('Actualisation autorisée uniquement le 2026-10-01 UTC.')
    client=storage_client();bucket=os.environ['R2_BUCKET_NAME']
    if args.action=='check':
        run=should_run(client,bucket,day)
        print('Actualisation autorisée.' if run else 'Déjà publiée : collecte ignorée.')
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write(f"run={'true' if run else 'false'}\n")
    else:
        if not completed(client,bucket):
            response,data=get_optional(client,bucket,CURRENT)
            if response is None:raise RuntimeError('Parquet final absent.')
            write_success(client,bucket,response,data)
        print('Publication unique confirmée.')

if __name__=='__main__':main()
