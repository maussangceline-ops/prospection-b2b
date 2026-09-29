"""Unique configuration R2; no implicit AWS credentials or fallback."""
import os
from urllib.parse import urlsplit
import boto3
from botocore.config import Config

REQUIRED = ('R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME')

def storage_client(getter=None):
    getter = getter or os.getenv
    values = {key: getter(key) for key in REQUIRED}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError('Configuration R2 manquante : ' + ', '.join(missing))
    url = urlsplit(values['R2_ENDPOINT_URL'])
    if (url.scheme != 'https' or not url.hostname
            or not url.hostname.endswith('.r2.cloudflarestorage.com')
            or url.username or url.password or url.query or url.fragment
            or url.path not in ('', '/') or url.port not in (None, 443)):
        raise ValueError('R2_ENDPOINT_URL doit être l’endpoint HTTPS S3 Cloudflare, sans bucket ni paramètres.')
    return boto3.client(
        's3', endpoint_url=values['R2_ENDPOINT_URL'].rstrip('/'), region_name='auto',
        aws_access_key_id=values['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=values['R2_SECRET_ACCESS_KEY'],
        config=Config(signature_version='s3v4', connect_timeout=15, read_timeout=120,
                      retries={'max_attempts': 4, 'mode': 'standard'},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))
