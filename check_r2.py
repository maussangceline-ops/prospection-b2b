"""Contrôle en lecture seule de R2 : référentiels et Parquet publié."""
import hashlib
import io
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from dashboard.storage_client import storage_client

if __name__ == '__main__':
    load_dotenv(Path(__file__).resolve().parent/'.env',override=False)
    client=storage_client();bucket=os.environ['R2_BUCKET_NAME']
    for name in ['v_commune_2026.csv','v_departement_2026.csv','v_region_2026.csv']:
        client.head_object(Bucket=bucket,Key=f'raw/referentiels/cog/2026/{name}')
    obj=client.get_object(Bucket=bucket,Key='processed/prospects/current.parquet')
    with obj['Body'] as stream: data=stream.read()
    digest=hashlib.sha256(data).hexdigest()
    if obj.get('Metadata',{}).get('sha256') != digest:
        raise SystemExit('Empreinte absente ou incorrecte : vérifier la migration.')
    df=pd.read_parquet(io.BytesIO(data))
    required=set('admissible_prospection anciennete_jours angle_commercial categorie_juridique_actuelle code_departement codes_postaux_commune couleur_priorite date_creation_entreprise date_evaluation disponibilite_nom libelle_age mois_collecte naf_etablissement nom_affiche nom_commune nom_departement score_total siren siret'.split())
    missing=required-set(df.columns)
    if missing:raise SystemExit('Colonnes manquantes : '+', '.join(sorted(missing)))
    print(f'R2 vérifié : {len(df)} établissements, {len(df.columns)} colonnes ; 3 référentiels COG présents.')
    print('Aucun fichier modifié, aucune collecte déclenchée.')
