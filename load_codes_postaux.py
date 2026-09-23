"""Importer La Poste après load_raw_duckdb.py, avant dbt build.
La correspondance communale ne reconstitue pas l'adresse de l'établissement.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import unicodedata
import urllib.request

import duckdb
from dotenv import load_dotenv

URL = 'https://data.laposte.fr/data-fair/api/v1/datasets/laposte-hexasmal/raw'
ROOT = Path(__file__).resolve().parent


def analyser(contenu):
    try:
        texte = contenu.decode('utf-8-sig')
    except UnicodeDecodeError:
        texte = contenu.decode('cp1252')
    lecteur = csv.DictReader(io.StringIO(texte), dialect=csv.Sniffer().sniff(texte[:8192], delimiters=';,\t'))
    def normaliser(nom):
        return re.sub('[^a-z0-9]', '', unicodedata.normalize('NFKD', nom or '').encode('ascii', 'ignore').decode().lower())
    champs = {normaliser(nom): nom for nom in (lecteur.fieldnames or [])}
    if not {'codecommuneinsee', 'codepostal'} <= champs.keys():
        raise ValueError('Colonnes attendues absentes du CSV La Poste.')
    couples = set()
    for numero, ligne in enumerate(lecteur, 2):
        commune = (ligne.get(champs['codecommuneinsee']) or '').strip().upper()
        postal = (ligne.get(champs['codepostal']) or '').strip()
        if not re.fullmatch(r'[0-9AB]{5}', commune) or not re.fullmatch(r'\d{5}', postal):
            raise ValueError(f'Code invalide dans le référentiel, ligne {numero}.')
        couples.add((commune, postal))
    if not couples:
        raise ValueError('Référentiel postal vide.')
    return sorted(couples)


def main():
    load_dotenv(ROOT / '.env', override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true', help='Importer dans DuckDB sans publier le référentiel dans S3.')
    parser.add_argument('--fichier', type=Path, help='CSV La Poste local ; sinon téléchargement officiel.')
    args = parser.parse_args()
    base = Path(os.getenv('DUCKDB_PATH', str(ROOT / 'data/warehouse/prospection.duckdb')))
    if not base.is_file():
        raise SystemExit('Charge d’abord DuckDB avec load_raw_duckdb.py.')
    if not args.local_only and not os.getenv('S3_BUCKET_NAME'):
        raise SystemExit('S3_BUCKET_NAME absent.')
    if args.fichier:
        contenu = args.fichier.read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=90) as reponse:
            contenu = reponse.read()
    couples = analyser(contenu)
    date = datetime.now(timezone.utc)
    identifiant = date.strftime('%Y%m%dT%H%M%S%fZ')
    dossier = ROOT / 'data/raw/referentiels/postaux' / identifiant
    dossier.mkdir(parents=True, exist_ok=False)
    (dossier / 'codes_postaux.csv').write_bytes(contenu)
    manifeste = {'source_url': URL, 'date_recuperation': date.isoformat(),
                 'fichier_local_source': str(args.fichier) if args.fichier else None,
                 'sha256': hashlib.sha256(contenu).hexdigest(), 'nombre_couples': len(couples)}
    suivi = json.dumps(manifeste, ensure_ascii=False, indent=2).encode('utf-8')
    (dossier / 'referentiel.json').write_bytes(suivi)
    if not args.local_only:
        import boto3
        client = boto3.client('s3')
        for nom, donnees in [('codes_postaux.csv', contenu), ('referentiel.json', suivi)]:
            cle = f'raw/referentiels/postaux/{identifiant}/{nom}'
            client.put_object(Bucket=os.environ['S3_BUCKET_NAME'], Key=cle, Body=donnees)
            with client.get_object(Bucket=os.environ['S3_BUCKET_NAME'], Key=cle)['Body'] as flux:
                if hashlib.sha256(flux.read()).digest() != hashlib.sha256(donnees).digest():
                    raise RuntimeError('Vérification S3 échouée : ' + cle)
    with duckdb.connect(str(base)) as connexion:
        connexion.execute('BEGIN')
        try:
            connexion.execute('CREATE SCHEMA IF NOT EXISTS raw')
            connexion.execute('''CREATE OR REPLACE TABLE raw.codes_postaux (
                code_commune VARCHAR NOT NULL, code_postal VARCHAR NOT NULL,
                date_recuperation TIMESTAMPTZ NOT NULL, source_url VARCHAR NOT NULL,
                PRIMARY KEY (code_commune, code_postal))''')
            connexion.executemany('INSERT INTO raw.codes_postaux VALUES (?, ?, ?, ?)',
                                 [(commune, postal, date, URL) for commune, postal in couples])
            connexion.execute('COMMIT')
        except Exception:
            connexion.execute('ROLLBACK')
            raise
    print(f'La Poste : {len(couples)} couples commune/code postal validés et chargés.')


if __name__ == '__main__':
    main()
