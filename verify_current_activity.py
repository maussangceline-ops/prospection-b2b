"""Vérifier les SIRET historiques à la date du jour, sans modifier leur historique."""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
import duckdb
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
URL = 'https://api.insee.fr/api-sirene/3.11/siret'


def normaliser(etablissement, date_reference):
    unite = etablissement.get('uniteLegale') or {}
    periodes = [p for p in etablissement.get('periodesEtablissement', [])
                if p.get('dateDebut') and p['dateDebut'] <= date_reference
                and (not p.get('dateFin') or p['dateFin'] >= date_reference)]
    statut_etablissement = periodes[0].get('etatAdministratifEtablissement') if len(periodes) == 1 else None
    statut_entreprise = unite.get('etatAdministratifUniteLegale')
    if statut_etablissement == 'F' or statut_entreprise == 'C':
        etat = 'Inactif'
    elif statut_etablissement == 'A' and statut_entreprise == 'A':
        etat = 'Actif'
    else:
        etat = 'À vérifier'
    categorie = unite.get('categorieJuridiqueUniteLegale')
    if not categorie or categorie == '[ND]':
        categorie = None
    return statut_etablissement, statut_entreprise, categorie, etat


def demander(session, parametres):
    for tentative in range(5):
        time.sleep(2.2)  # Quota Sirene : 30 appels / minute.
        try:
            reponse = session.get(URL, params=parametres, timeout=60)
        except (requests.Timeout, requests.ConnectionError):
            if tentative == 4:
                raise RuntimeError('Sirene indisponible : publication interrompue.') from None
            time.sleep(min(2 ** (tentative + 1), 30))
            continue
        if reponse.status_code == 429 or reponse.status_code >= 500:
            if tentative == 4:
                raise RuntimeError(f'Sirene HTTP {reponse.status_code} : publication interrompue.')
            try:
                attente = float(reponse.headers.get('Retry-After', 10))
            except ValueError:
                attente = 10
            time.sleep(min(max(attente, 2 ** tentative), 60))
            continue
        if reponse.status_code != 200:
            raise RuntimeError(f'Sirene HTTP {reponse.status_code} : aucune nouvelle vérification publiée.')
        return reponse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true', help='Ne pas archiver dans S3 (test local).')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    cle = os.getenv('INSEE_API_KEY')
    if not cle:
        raise SystemExit('INSEE_API_KEY absente.')
    bucket = os.getenv('S3_BUCKET_NAME')
    if not args.local_only and not bucket:
        raise SystemExit('S3_BUCKET_NAME absent.')
    chemin_base = Path(os.getenv('DUCKDB_PATH', str(ROOT / 'data/warehouse/prospection.duckdb')))
    if not chemin_base.is_file():
        raise SystemExit('Charger DuckDB avant de vérifier les activités.')
    with duckdb.connect(str(chemin_base), read_only=True) as connexion:
        sirets = [r[0] for r in connexion.execute('select siret from raw.sirene_etablissements order by siret').fetchall()]
    if not sirets or len(sirets) != len(set(sirets)) or any(not re.fullmatch(r'\d{14}', s or '') for s in sirets):
        raise SystemExit('Population SIRET vide ou invalide.')
    debut = datetime.now(timezone.utc)
    jour = debut.date().isoformat()
    identifiant = debut.strftime('%Y%m%dT%H%M%S%fZ')
    dossier = ROOT / 'data/raw/verifications_activite' / identifiant
    dossier.mkdir(parents=True, exist_ok=False)
    manifeste = {'verification_id': identifiant, 'date_verification': jour,
                 'debut_utc': debut.isoformat(), 'source': URL, 'statut': 'en_cours',
                 'nombre_attendu': len(sirets), 'taille_lot': 100}
    suivi = dossier / 'verification.json'
    suivi.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2), encoding='utf-8')
    lignes = []
    with requests.Session() as session:
        session.headers.update({'X-INSEE-Api-Key-Integration': cle, 'Accept': 'application/json'})
        for debut_lot in range(0, len(sirets), 100):
            lot = sirets[debut_lot:debut_lot + 100]
            parametres = {'q': 'siret:(' + ' OR '.join(lot) + ')', 'date': jour, 'nombre': 100, 'curseur': '*'}
            reponse = demander(session, parametres)
            nom = f'lot_{debut_lot // 100 + 1:04d}.json'
            (dossier / nom).write_bytes(reponse.content)
            payload = reponse.json()
            etablissements = payload.get('etablissements', [])
            if int(payload['header']['total']) != len(etablissements):
                raise RuntimeError('Réponse tronquée : aucune publication.')
            par_siret = {e['siret']: e for e in etablissements}
            if len(par_siret) != len(etablissements) or not set(par_siret).issubset(lot):
                raise RuntimeError('SIRET inattendu ou dupliqué : aucune publication.')
            for siret in lot:
                e = par_siret.get(siret)
                valeurs = normaliser(e, jour) if e else (None, None, None, 'À vérifier')
                lignes.append((siret, jour, identifiant, *valeurs,
                               'Réponse Sirene' if e else 'Absent de la réponse Sirene', nom))
            print(f'Activité : {min(debut_lot + 100, len(sirets))}/{len(sirets)} SIRET vérifiés', flush=True)
    if all(ligne[6] == 'À vérifier' for ligne in lignes):
        raise RuntimeError('Aucun statut exploitable : vérifier la réponse API avant publication.')
    synthese = dossier / 'resultats.json'
    synthese.write_text(json.dumps(lignes, ensure_ascii=False), encoding='utf-8')
    manifeste.update(statut='terminee', fin_utc=datetime.now(timezone.utc).isoformat(),
                     nombres={etat: sum(l[6] == etat for l in lignes) for etat in ['Actif', 'Inactif', 'À vérifier']})
    suivi.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.local_only:
        s3 = boto3.client('s3')
        # Manifeste envoyé en dernier, seulement après toutes les réponses et la synthèse.
        fichiers = sorted(p for p in dossier.iterdir() if p != suivi) + [suivi]
        for fichier in fichiers:
            contenu = fichier.read_bytes()
            key = f'raw/verifications_activite/{identifiant}/{fichier.name}'
            s3.put_object(Bucket=bucket, Key=key, Body=contenu, ContentType='application/json')
            with s3.get_object(Bucket=bucket, Key=key)['Body'] as flux:
                if hashlib.sha256(flux.read()).digest() != hashlib.sha256(contenu).digest():
                    raise RuntimeError(f'Archive S3 différente : {key}')
    with duckdb.connect(str(chemin_base)) as connexion:
        connexion.execute('BEGIN')
        connexion.execute('''create or replace table raw.verifications_activite (
            siret varchar primary key, date_verification date, verification_id varchar,
            statut_etablissement_actuel varchar, statut_entreprise_actuel varchar,
            categorie_juridique_actuelle varchar, etat_activite varchar,
            motif_verification varchar, fichier_verification varchar)''')
        connexion.executemany('insert into raw.verifications_activite values (?, ?, ?, ?, ?, ?, ?, ?, ?)', lignes)
        connexion.execute('COMMIT')
    print('Vérification terminée :', manifeste['nombres'])


if __name__ == '__main__':
    main()
