"""Collecter l'historique BODACC des SIREN locaux et produire un filtre commercial prudent.
Pas de clé BODACC. Aucun point attribué. Les réponses originales restent archivées.
"""
import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import boto3
import duckdb
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
URL = 'https://www.bodacc.fr/api/explore/v2.1/catalog/datasets/annonces-commerciales/records'
VERSION = 'bodacc_v1_prudent'


def texte(valeur):
    valeur = unicodedata.normalize('NFKD', str(valeur or '').lower().replace('’', "'"))
    return ' '.join(''.join(c for c in valeur if not unicodedata.combining(c)).split())


def date_jugement(valeur):
    valeur = texte(valeur)
    try:
        return date.fromisoformat(valeur).isoformat()
    except ValueError:
        mois = ['janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin', 'juillet',
                'aout', 'septembre', 'octobre', 'novembre', 'decembre']
        morceaux = valeur.split()
        if len(morceaux) == 3 and morceaux[1] in mois:
            try:
                return date(int(morceaux[2]), mois.index(morceaux[1])+1,
                            int(morceaux[0].replace('er', ''))).isoformat()
            except ValueError:
                pass
    return None


def objet_json(valeur):
    if isinstance(valeur, dict):
        return valeur
    try:
        resultat = json.loads(valeur or '{}')
        return resultat if isinstance(resultat, dict) else {}
    except (ValueError, TypeError):
        return {}


def sirens_annonce(annonce):
    valeurs = annonce.get('registre') or []
    if isinstance(valeurs, str):
        valeurs = valeurs.split(',')
    return {v for valeur in valeurs
            if re.fullmatch(r'\d{9}', v := re.sub(r'\s', '', str(valeur)))}


def normaliser(annonce):
    jugement = objet_json(annonce.get('jugement'))
    nature = jugement.get('nature') or ''
    n = texte(nature)
    ouvertures = {
        "jugement d'ouverture d'une procedure de sauvegarde": 'sauvegarde',
        "jugement d'ouverture d'une procedure de sauvegarde acceleree": 'sauvegarde',
        "jugement d'ouverture d'une procedure de redressement judiciaire": 'redressement',
        "jugement de conversion en redressement judiciaire de la procedure de sauvegarde": 'redressement',
    }
    neutres = {"depot de l'etat des creances"}
    type_evenement = ouvertures.get(n, 'suivi_neutre' if n in neutres else 'a_verifier')
    return {
        'id_annonce': annonce['id'], 'date_publication': annonce.get('dateparution'),
        'date_jugement': date_jugement(jugement.get('date')), 'nature_jugement': nature,
        'type_evenement': type_evenement, 'type_avis': annonce.get('typeavis'),
        'type_jugement': jugement.get('type'), 'tribunal': annonce.get('tribunal'),
        'url_annonce': 'https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:' + annonce['id'],
    }


def qualifier(annonces, jour):
    """Déduction commerciale sur les annonces disponibles, pas un certificat juridique.
    Une évolution non interprétable suspend la décision automatique.
    """
    if not annonces:
        return 'Aucune procédure repérée', 'Aucune annonce collective retrouvée pour ce SIREN', None
    evenements = [normaliser(a) for a in annonces]
    derniere_publication = max(evenements, key=lambda e: (e['date_publication'] or '', e['id_annonce']))
    if any(e['type_avis'] != 'annonce' or e['type_jugement'] not in (None, 'initial')
           or not e['date_jugement'] or e['date_jugement'] > jour for e in evenements):
        return 'À vérifier', 'Rectificatif, date absente/invalide ou jugement futur', derniere_publication
    tribunaux = {texte(e['tribunal']) for e in evenements if e['tribunal']}
    if len(tribunaux) > 1:
        return 'À vérifier', 'Plusieurs tribunaux : rapprochement des procédures nécessaire', derniere_publication
    decisifs = [e for e in evenements if e['type_evenement'] != 'suivi_neutre']
    if not decisifs:
        return 'À vérifier', 'Annonces de suivi sans jugement décisif interprétable', derniere_publication
    dernier_jour = max(e['date_jugement'] for e in decisifs)
    derniers = [e for e in decisifs if e['date_jugement'] == dernier_jour]
    dernier = max(derniers, key=lambda e: (e['date_publication'] or '', e['id_annonce']))
    if len({e['type_evenement'] for e in derniers}) != 1 or dernier['type_evenement'] == 'a_verifier':
        return 'À vérifier', 'Plan, clôture, liquidation ou autre évolution à interpréter', dernier
    libelle = 'Exclusion — ' + dernier['type_evenement']
    return libelle, 'Dernier jugement décisif identifié : ouverture/conversion, sans fin interprétable ultérieure', dernier


def demander(session, parametres):
    for tentative in range(5):
        time.sleep(1.0)
        try:
            reponse = session.get(URL, params=parametres, timeout=60)
        except (requests.Timeout, requests.ConnectionError):
            if tentative == 4:
                raise RuntimeError('BODACC inaccessible : publication interrompue.') from None
            time.sleep(2 ** tentative)
            continue
        if reponse.status_code == 429 or reponse.status_code >= 500:
            if tentative == 4:
                raise RuntimeError(f'BODACC HTTP {reponse.status_code} : publication interrompue.')
            try:
                attente = float(reponse.headers.get('Retry-After', 10))
            except ValueError:
                attente = 10
            time.sleep(min(max(attente, 2 ** tentative), 60))
            continue
        if reponse.status_code != 200:
            raise RuntimeError(f'BODACC HTTP {reponse.status_code} : aucune conclusion d’absence.')
        return reponse


def recuperer_lot(session, sirens, jour, dossier, numero):
    # Requête exacte sur le champ multivalué : formes compacte ET espacée.
    identifiants = sorted(set(sirens) | {' '.join((s[:3], s[3:6], s[6:])) for s in sirens})
    where = ('familleavis="collective" AND dateparution <= "' + jour + '" AND registre IN ('
             + ','.join('"' + s + '"' for s in identifiants) + ')')
    total_attendu = None
    annonces = {}
    offset = 0
    while True:
        reponse = demander(session, {'where': where, 'limit': 100, 'offset': offset,
                                      'order_by': 'dateparution ASC, id ASC'})
        chemin = dossier / f'lot_{numero:04d}_page_{offset // 100 + 1:04d}.json'
        chemin.write_bytes(reponse.content)
        payload = reponse.json()
        total = int(payload['total_count'])
        if total_attendu is None:
            total_attendu = total
        if total != total_attendu or total > 10000:
            raise RuntimeError('Volume BODACC changeant ou trop élevé : arrêt sans publication.')
        resultats = payload['results']
        for annonce in resultats:
            if not isinstance(annonce.get('id'), str) or not sirens_annonce(annonce).intersection(sirens):
                raise RuntimeError('Annonce sans identifiant ou sans SIREN attendu.')
            if annonce['id'] in annonces:
                raise RuntimeError('Pagination BODACC dupliquée : relancer la collecte.')
            annonces[annonce['id']] = annonce
        offset += len(resultats)
        if offset == total_attendu:
            break
        if not resultats or offset > total_attendu:
            raise RuntimeError('Pagination BODACC incomplète.')
    return list(annonces.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true', help='Pas de publication S3 ; table locale actualisée.')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    chemin = Path(os.getenv('DUCKDB_PATH', str(ROOT / 'data/warehouse/prospection.duckdb')))
    if not chemin.is_file():
        raise SystemExit('Charge DuckDB avant la collecte BODACC.')
    bucket = os.getenv('S3_BUCKET_NAME')
    if not args.local_only and not bucket:
        raise SystemExit('S3_BUCKET_NAME absent.')
    with duckdb.connect(str(chemin), read_only=True) as connexion:
        sirens = [ligne[0] for ligne in connexion.execute(
            'select distinct substr(siret, 1, 9) from raw.sirene_etablissements order by 1').fetchall()]
    if not sirens or any(not re.fullmatch(r'\d{9}', s or '') for s in sirens):
        raise SystemExit('Population SIREN vide ou invalide.')
    debut = datetime.now(timezone.utc)
    jour = debut.date().isoformat()
    collecte_id = debut.strftime('%Y%m%dT%H%M%S%fZ')
    dossier = ROOT / 'data/raw/bodacc' / collecte_id
    dossier.mkdir(parents=True, exist_ok=False)
    suivi = dossier / 'collecte.json'
    manifeste = {'collecte_id': collecte_id, 'date_verification_bodacc': jour,
                 'statut': 'en_cours', 'source': URL, 'nombre_sirens': len(sirens),
                 'version_regles': VERSION, 'historique': 'Tout l’historique disponible à la date de contrôle',
                 'debut_utc': debut.isoformat()}
    suivi.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2), encoding='utf-8')
    par_siren = {s: {} for s in sirens}
    with requests.Session() as session:
        session.headers.update({'Accept': 'application/json', 'User-Agent': 'prospection-b2b/1.0'})
        for i in range(0, len(sirens), 25):
            lot = sirens[i:i + 25]
            annonces = recuperer_lot(session, lot, jour, dossier, i // 25 + 1)
            for annonce in annonces:
                for siren in sirens_annonce(annonce).intersection(lot):
                    par_siren[siren][annonce['id']] = annonce
            print(f'BODACC : {min(i + 25, len(sirens))}/{len(sirens)} entreprises contrôlées', flush=True)
    lignes = []
    evenements = []
    for siren, annonces in par_siren.items():
        etat, motif, derniere = qualifier(list(annonces.values()), jour)
        dernier = derniere or {}
        lignes.append((siren, jour, collecte_id, etat, motif, len(annonces),
                       dernier.get('id_annonce'), dernier.get('date_jugement'),
                       dernier.get('nature_jugement'), dernier.get('url_annonce'), VERSION))
        for annonce in annonces.values():
            evenements.append((siren, annonce['id'], collecte_id, json.dumps(annonce, ensure_ascii=False)))
    (dossier / 'resultats.json').write_text(json.dumps(lignes, ensure_ascii=False), encoding='utf-8')
    manifeste.update(statut='terminee', fin_utc=datetime.now(timezone.utc).isoformat(),
                     nombre_annonces_siren=len(evenements),
                     repartition={etat: sum(l[3] == etat for l in lignes) for etat in sorted({l[3] for l in lignes})})
    suivi.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.local_only:
        s3 = boto3.client('s3')
        for fichier in sorted(p for p in dossier.iterdir() if p != suivi) + [suivi]:
            contenu = fichier.read_bytes()
            cle = f'raw/bodacc/{collecte_id}/{fichier.name}'
            s3.put_object(Bucket=bucket, Key=cle, Body=contenu, ContentType='application/json')
            with s3.get_object(Bucket=bucket, Key=cle)['Body'] as flux:
                if hashlib.sha256(contenu).digest() != hashlib.sha256(flux.read()).digest():
                    raise RuntimeError(f'Archive S3 différente : {cle}')
    with duckdb.connect(str(chemin)) as connexion:
        connexion.execute('BEGIN')
        connexion.execute('''create or replace table raw.bodacc_controles (
            siren varchar primary key, date_verification_bodacc date, collecte_bodacc_id varchar,
            statut_bodacc varchar, motif_bodacc varchar, nombre_annonces_bodacc integer,
            id_annonce_bodacc varchar, date_jugement_bodacc date, nature_jugement_bodacc varchar,
            url_annonce_bodacc varchar, version_regles_bodacc varchar)''')
        connexion.executemany('insert into raw.bodacc_controles values (?,?,?,?,?,?,?,?,?,?,?)', lignes)
        connexion.execute('''create or replace table raw.bodacc_annonces (
            siren varchar, id_annonce varchar, collecte_id varchar, donnees json,
            primary key(siren,id_annonce))''')
        if evenements:
            connexion.executemany('insert into raw.bodacc_annonces values (?,?,?,?)', evenements)
        connexion.execute('COMMIT')
    print('Collecte BODACC terminée :', manifeste['repartition'])


if __name__ == '__main__':
    main()
