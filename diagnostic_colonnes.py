"""Diagnostic en lecture seule : aucune collecte, écriture S3 ou modification DuckDB."""
import ast
import io
import os
from pathlib import Path

import boto3
import duckdb
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
application = ROOT / 'dashboard/app.py'
arbre = ast.parse(application.read_text(encoding='utf-8'))
requis = None
for noeud in ast.walk(arbre):
    if isinstance(noeud, ast.Assign) and any(isinstance(cible, ast.Name) and cible.id == 'requis' for cible in noeud.targets):
        requis = set(ast.literal_eval(noeud.value))
        break
if not requis:
    raise SystemExit('Liste requis introuvable dans dashboard/app.py : transmettre ce fichier.')
print('Colonnes attendues par le dashboard local :', ', '.join(sorted(requis)))


def bilan(label, colonnes):
    manquantes = sorted(requis - set(colonnes))
    print(f'\n{label}')
    print('Colonnes manquantes :', ', '.join(manquantes) if manquantes else 'AUCUNE')
    print('Nombre de colonnes :', len(colonnes))


base_export = ROOT / 'data/warehouse/prospection.duckdb'
base_dashboard = Path(os.getenv('DUCKDB_PATH', str(base_export))).expanduser()
for base in dict.fromkeys([base_export, base_dashboard]):
    print('\nBase DuckDB :', base.resolve())
    if not base.is_file():
        print('Fichier absent')
        continue
    try:
        with duckdb.connect(str(base), read_only=True) as connexion:
            colonnes = [ligne[0] for ligne in connexion.execute('describe analytics.mart_prospects_scores').fetchall()]
            bilan('Table mart_prospects_scores', colonnes)
    except Exception as erreur:
        print('Lecture DuckDB impossible :', type(erreur).__name__)

local = ROOT / 'data/processed/prospects.parquet'
if local.is_file():
    bilan('Parquet exporté localement', pd.read_parquet(local).columns)
else:
    print('\nParquet local absent')

bucket = os.getenv('S3_BUCKET_NAME')
cle_defaut = 'processed/prospects/current.parquet'
cles = list(dict.fromkeys([cle_defaut, os.getenv('S3_SCORES_KEY', cle_defaut)]))
if not bucket:
    raise SystemExit('S3_BUCKET_NAME absent du .env ou de l’environnement.')
s3 = boto3.client('s3', region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-west-3'))
for cle in cles:
    print(f'\nObjet S3 : s3://{bucket}/{cle}')
    try:
        reponse = s3.get_object(Bucket=bucket, Key=cle)
        with reponse['Body'] as flux:
            contenu = flux.read()
        bilan('Parquet effectivement présent dans S3', pd.read_parquet(io.BytesIO(contenu)).columns)
        print('Dernière modification S3 :', reponse['LastModified'].isoformat())
    except Exception as erreur:
        print('Lecture S3 impossible :', type(erreur).__name__)
print('\nDiagnostic terminé. Aucune donnée modifiée ; aucune clé secrète affichée.')
