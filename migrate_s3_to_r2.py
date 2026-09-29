"""Inventaire, sauvegarde locale et copie S3 -> R2. Aucune suppression."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from dashboard.storage_client import storage_client

ROOT = Path(__file__).resolve().parent

def inventory(client, bucket):
    result = {}
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
        for obj in page.get('Contents', []):
            result[obj['Key']] = {'size': obj['Size'], 'etag': obj['ETag'],
                                  'modified': obj['LastModified'].isoformat()}
    return result

def read(client, bucket, key, **kwargs):
    response = client.get_object(Bucket=bucket, Key=key, **kwargs)
    with response['Body'] as stream:
        content = stream.read()
    return response, content

def sha(content):
    return hashlib.sha256(content).hexdigest()

def copy_one(source, target, source_bucket, target_bucket, key, item, backup):
    # Hashed filenames avoid unsafe keys, case collisions and file/directory conflicts.
    path = backup / 'objects' / hashlib.sha256(key.encode()).hexdigest()
    response, content = read(source, source_bucket, key, IfMatch=item['etag'])
    if len(content) != item['size']:
        raise RuntimeError('La source a changé pendant la copie : ' + key)
    digest = sha(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)
    try:
        _, remote = read(target, target_bucket, key)
    except ClientError as error:
        if error.response['Error']['Code'] not in ('404', 'NoSuchKey', 'NotFound'):
            raise
        metadata = dict(response.get('Metadata', {}))
        metadata['sha256'] = digest
        args = {k: response[k] for k in ('ContentType','CacheControl','ContentDisposition','ContentEncoding','ContentLanguage') if k in response}
        target.put_object(Bucket=target_bucket, Key=key, Body=content,
                          Metadata=metadata, IfNoneMatch='*', **args)
        _, remote = read(target, target_bucket, key)
    if sha(remote) != digest:
        raise RuntimeError('Objet R2 différent : arrêt sans écrasement. Clé : ' + key)
    return {'key': key, 'bytes': len(content), 'sha256': digest,
            'backup_file': str(path.relative_to(backup))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy', action='store_true', help='Copier après inventaire (sinon lecture seule).')
    parser.add_argument('--backup-dir', default=str(ROOT/'data/backup_s3_r2'))
    args = parser.parse_args()
    load_dotenv(ROOT/'.env', override=False)
    keys = ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','S3_BUCKET_NAME')
    if any(not os.getenv(k) for k in keys):
        raise SystemExit('Conserver les identifiants AWS et S3_BUCKET_NAME pour la migration.')
    source_bucket = os.environ['S3_BUCKET_NAME']
    source = boto3.client('s3', endpoint_url='https://s3.'+os.getenv('AWS_DEFAULT_REGION','eu-west-3')+'.amazonaws.com',
                          region_name=os.getenv('AWS_DEFAULT_REGION','eu-west-3'),
                          aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                          aws_session_token=os.getenv('AWS_SESSION_TOKEN'))
    objects = inventory(source, source_bucket)
    print(f"Source : {len(objects)} objets actuels, {sum(x['size'] for x in objects.values())/1e6:.2f} Mo")
    if not objects:
        raise SystemExit('Source vide : migration interrompue.')
    # Inventory earlier versions too, but do not silently discard them during account closure.
    version_status = 'inconnu'
    old_versions = old_bytes = delete_markers = 0
    try:
        version_status = source.get_bucket_versioning(Bucket=source_bucket).get('Status','jamais_active')
        if version_status in ('Enabled','Suspended'):
            for page in source.get_paginator('list_object_versions').paginate(Bucket=source_bucket):
                for obj in page.get('Versions', []):
                    if not obj['IsLatest']:
                        old_versions += 1; old_bytes += obj['Size']
                delete_markers += len(page.get('DeleteMarkers', []))
        print(f'Versioning : {version_status}; anciennes versions : {old_versions}; marqueurs de suppression : {delete_markers}')
    except ClientError:
        print('Versioning non vérifiable avec ces droits : contrôle AWS requis avant fermeture.')
    if not args.copy:
        print('Inventaire terminé. Pour sauvegarder et copier : python migrate_s3_to_r2.py --copy')
        return
    target = storage_client(); target_bucket = os.environ['R2_BUCKET_NAME']
    backup = Path(args.backup_dir).resolve(); backup.mkdir(parents=True,exist_ok=True)
    report = {'status':'en_cours','source_bucket':source_bucket,'target_bucket':target_bucket,
              'started_at':datetime.now(timezone.utc).isoformat(),'versioning':version_status,
              'old_versions_not_copied':old_versions,'old_version_bytes':old_bytes,
              'delete_markers_not_copied':delete_markers,'objects':[]}
    manifest = backup/'manifest.json'
    def checkpoint():
        temp = manifest.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(manifest)
    checkpoint()
    for number, (key,item) in enumerate(sorted(objects.items()),1):
        report['objects'].append(copy_one(source,target,source_bucket,target_bucket,key,item,backup))
        if number % 50 == 0 or number == len(objects):
            checkpoint(); print(f'{number}/{len(objects)} sauvegardés et vérifiés')
    if inventory(source,source_bucket) != objects:
        raise RuntimeError('Inventaire source modifié pendant la migration : relancer le contrôle.')
    target_objects = inventory(target,target_bucket)
    if any(key not in target_objects or target_objects[key]['size'] != item['size'] for key,item in objects.items()):
        raise RuntimeError('Inventaire final R2 incomplet.')
    report.update(status='terminee',finished_at=datetime.now(timezone.utc).isoformat())
    checkpoint()
    print(f'Migration des objets actuels vérifiée par SHA-256. Sauvegarde : {backup}')
    print('Aucune suppression AWS. Les anciennes versions et autres ressources AWS restent à examiner.')

if __name__ == '__main__':
    main()
