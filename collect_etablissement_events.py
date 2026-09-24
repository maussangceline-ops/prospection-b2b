"""Collecter les établissements des SIREN existants et détecter leurs mouvements.
Étape de qualification : aucun score ni dashboard modifié.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import boto3
import duckdb
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
BASE = 'https://api.insee.fr/api-sirene/3.11'


def date_valide(valeur):
    try:
        return date.fromisoformat(valeur).isoformat()
    except (TypeError, ValueError):
        return None


def identifier(*valeurs):
    return hashlib.sha256('|'.join(str(v or '') for v in valeurs).encode()).hexdigest()


def detecter(etablissements, liens, creations, jour):
    """Un successeur associé à un lien n'est jamais aussi une nouvelle ouverture.
    L'absence de lien ne prouve pas l'absence de transfert : garder un candidat.
    """
    par_siret = {e['siret']: e for e in etablissements}
    par_siren = defaultdict(list)
    for e in etablissements:
        par_siren[e['siret'][:9]].append(e)
    liens_uniques = {}
    for lien in liens:
        cle = (lien['siretEtablissementPredecesseur'], lien['siretEtablissementSuccesseur'], lien.get('dateLienSuccession'))
        if cle in liens_uniques and liens_uniques[cle] != lien:
            raise ValueError('Deux versions contradictoires d’un lien de succession.')
        liens_uniques[cle] = lien
    entrants, sortants = defaultdict(list), defaultdict(list)
    for lien in liens_uniques.values():
        entrants[lien['siretEtablissementSuccesseur']].append(lien)
        sortants[lien['siretEtablissementPredecesseur']].append(lien)
    resultat = []
    def ajouter(siren, type_evt, date_evt, pred, succ, qualification, motif):
        creation = date_valide(creations.get(siren))
        date_evt = date_valide(date_evt)
        if not creation or not date_evt:
            qualification, motif = 'a_verifier', 'Date de création ou événement absente/invalide'
        elif date_evt <= creation:
            qualification, motif = 'hors_perimetre', 'Événement antérieur ou simultané à la création'
        elif date_evt > jour:
            qualification, motif = 'hors_perimetre', 'Événement futur'
        resultat.append((identifier(type_evt, pred, succ, date_evt), siren, type_evt,
                         date_evt, pred, succ, qualification, motif))
    for lien in liens_uniques.values():
        pred, succ = lien['siretEtablissementPredecesseur'], lien['siretEtablissementSuccesseur']
        siren = succ[:9]
        if siren not in creations:
            continue
        if pred[:9] != siren:
            ajouter(siren, 'reprise_activite', lien.get('dateLienSuccession'), pred, succ,
                    'a_verifier', 'Changement d’unité légale, pas un déménagement interne')
        elif len(entrants[succ]) != 1 or len(sortants[pred]) != 1:
            ajouter(siren, 'transfert_complexe', lien.get('dateLienSuccession'), pred, succ,
                    'a_verifier', 'Plusieurs prédécesseurs/successeurs : risque de scission ou fusion')
        elif pred == succ or pred not in par_siret or succ not in par_siret:
            ajouter(siren, 'transfert_complexe', lien.get('dateLienSuccession'), pred, succ,
                    'a_verifier', 'Lien incohérent ou établissement absent')
        else:
            ajouter(siren, 'transfert_etablissement', lien.get('dateLienSuccession'), pred, succ,
                    'confirme_par_lien', 'Lien Sirene entre établissements d’un même SIREN')
    for e in etablissements:
        siret, siren = e['siret'], e['siret'][:9]
        if siret in entrants:
            continue
        d = date_valide(e.get('dateCreationEtablissement'))
        autres = [a for a in par_siren[siren] if a['siret'] != siret]
        precedent = any(date_valide(a.get('dateCreationEtablissement')) and d
                        and a['dateCreationEtablissement'] < d for a in autres)
        if not precedent:
            ajouter(siren, 'etablissement_initial', d, None, siret,
                    'hors_perimetre', 'Aucun établissement antérieur identifié : pas de bonus de création')
        else:
            ajouter(siren, 'ouverture_potentielle', d, None, siret,
                    'a_confirmer', 'Établissement supplémentaire ; aucun lien de succession connu, transfert non exclu')
    return sorted(resultat, key=lambda ligne: (ligne[1], ligne[3] or '', ligne[0]))


def appeler(session, endpoint, params):
    for tentative in range(5):
        time.sleep(2.2)
        try:
            r = session.get(BASE + endpoint, params=params, timeout=60)
        except (requests.Timeout, requests.ConnectionError):
            if tentative == 4:
                raise RuntimeError('API Sirene inaccessible : collecte interrompue.') from None
            time.sleep(2 ** tentative)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if tentative == 4:
                raise RuntimeError(f'API HTTP {r.status_code} : collecte interrompue.')
            time.sleep(30)
            continue
        return r


def paginer(session, endpoint, champ, requete, dossier, prefixe):
    resultats, total, debut = [], None, 0
    while True:
        r = appeler(session, endpoint, {'q': requete, 'nombre': 1000, 'debut': debut})
        (dossier / f'{prefixe}_{debut:06d}.json').write_bytes(r.content)
        try:
            payload = r.json()
        except ValueError:
            raise RuntimeError('Réponse Sirene non JSON.') from None
        header = payload.get('header', {})
        # Seul le 404 métier documenté est une absence de liens ; pas une URL erronée.
        if endpoint.endswith('liensSuccession') and r.status_code == 404 and debut == 0:
            if header.get('statut') == 404 and str(header.get('message', '')).startswith('Aucun lien de succession'):
                return []
        if r.status_code != 200:
            raise RuntimeError(f'API {endpoint} HTTP {r.status_code} : arrêt sans modification du score.')
        n = int(header['total'])
        if total is None:
            total = n
        if n != total or n > 10000:
            raise RuntimeError('Total changeant ou lot trop volumineux : collecte interrompue.')
        page = payload[champ]
        resultats.extend(page)
        debut += len(page)
        if debut == total:
            identifiants = [e.get('siret') if champ == 'etablissements' else
                (e.get('siretEtablissementPredecesseur'), e.get('siretEtablissementSuccesseur'), e.get('dateLienSuccession'))
                for e in resultats]
            if len(identifiants) != len(set(identifiants)):
                raise RuntimeError('Pagination dupliquée.')
            return resultats
        if not page or debut > total:
            raise RuntimeError('Pagination incomplète.')


def lire_lot_archive(source, prefixe):
    fichiers = sorted(source.glob(prefixe + '_*.json'))
    if not fichiers:
        raise RuntimeError('Lot archivé absent : ' + prefixe)
    lignes, total, debut = [], None, 0
    for fichier in fichiers:
        payload = json.loads(fichier.read_text(encoding='utf-8'))
        header = payload.get('header', {})
        if header.get('statut') != 200 or int(fichier.stem.rsplit('_', 1)[1]) != debut:
            raise RuntimeError('Page archivée invalide : ' + fichier.name)
        n = int(header['total'])
        if total is None:
            total = n
        if n != total:
            raise RuntimeError('Total archivé changeant.')
        page = payload['etablissements']
        lignes.extend(page)
        debut += len(page)
    if debut != total:
        raise RuntimeError('Lot archivé incomplet : ' + prefixe)
    return lignes, fichiers


def verifier_absent(session, siret, dossier):
    reponse = appeler(session, '/siret/' + siret, {})
    (dossier / ('verification_' + siret + '.json')).write_bytes(reponse.content)
    try:
        payload = reponse.json()
    except ValueError:
        raise RuntimeError('Vérification individuelle non JSON.') from None
    if reponse.status_code == 200:
        e = payload.get('etablissement', {})
        if not isinstance(e, dict):
            raise RuntimeError('Réponse individuelle sans objet établissement valide.')
        siret_recu = e.get('siret')
        if not isinstance(siret_recu, str) or not re.fullmatch(r'\d{14}', siret_recu):
            raise RuntimeError('Réponse individuelle sans SIRET valide.')
        if siret_recu != siret:
            # Ne jamais fusionner deux identités ni inférer un transfert ici.
            return None, (
                f'Identifiant différent dans la réponse individuelle : demandé {siret}, '
                f'reçu {siret_recu}. Rapprochement non validé ; entreprise à vérifier'
            )
        return e, 'Retrouvé par interrogation individuelle ; couverture du lot à vérifier'
    if reponse.status_code == 404 and payload.get('header', {}).get('statut') == 404:
        return None, 'Non retrouvé par interrogation individuelle (404 Sirene)'
    raise RuntimeError(f'Vérification individuelle HTTP {reponse.status_code} : arrêt.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--reprendre', help='Identifiant de collecte dont les pages établissements sont complètes')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    if not os.getenv('INSEE_API_KEY'):
        raise SystemExit('INSEE_API_KEY absente.')
    bucket = os.getenv('S3_BUCKET_NAME')
    if not args.local_only and not bucket:
        raise SystemExit('S3_BUCKET_NAME absent.')
    base = Path(os.getenv('DUCKDB_PATH', str(ROOT / 'data/warehouse/prospection.duckdb')))
    if not base.is_file():
        raise SystemExit('Base DuckDB introuvable.')
    with duckdb.connect(str(base), read_only=True) as connexion:
        population = connexion.execute('''select substr(siret,1,9),
            json_extract_string(donnees, '$.uniteLegale.dateCreationUniteLegale'), siret
            from raw.sirene_etablissements order by siret''').fetchall()
    creations = {}
    sirets_initiaux = set()
    for siren, creation, siret in population:
        if not re.fullmatch(r'\d{14}', siret or ''):
            raise SystemExit('SIRET historique invalide.')
        if siren in creations and creations[siren] != creation:
            raise SystemExit('Dates de création contradictoires pour un SIREN.')
        creations[siren] = creation
        sirets_initiaux.add(siret)
    if not creations:
        raise SystemExit('Population vide.')
    maintenant = datetime.now(timezone.utc)
    jour, run = maintenant.date().isoformat(), maintenant.strftime('%Y%m%dT%H%M%S%fZ')
    source_reprise = None
    if args.reprendre:
        if not re.fullmatch(r'\d{8}T\d{12}Z', args.reprendre):
            raise SystemExit('Identifiant de collecte invalide.')
        source_reprise = ROOT / 'data/raw/mouvements_etablissements' / args.reprendre
        ancien = json.loads((source_reprise / 'collecte.json').read_text(encoding='utf-8'))
        if ancien.get('nombre_siren') != len(creations):
            raise SystemExit('La population a changé : lancer une nouvelle collecte.')
    dossier = ROOT / 'data/raw/mouvements_etablissements' / run
    dossier.mkdir(parents=True, exist_ok=False)
    manifeste = {'collecte_id': run, 'date_observation': jour, 'statut': 'en_cours',
                 'nombre_siren': len(creations), 'source': BASE, 'version_detection': 'v1_sans_points'}
    if source_reprise:
        manifeste['reprise_de'] = args.reprendre
        manifeste['date_observation_etablissements'] = ancien.get('date_observation')
        print('Reprise des pages établissements :', args.reprendre, flush=True)
    suivi = dossier / 'collecte.json'
    suivi.write_text(json.dumps(manifeste, indent=2), encoding='utf-8')
    etablissements, liens = {}, {}
    with requests.Session() as session:
        session.headers.update({'X-INSEE-Api-Key-Integration': os.environ['INSEE_API_KEY'], 'Accept': 'application/json'})
        sirens = sorted(creations)
        for i in range(0, len(sirens), 50):
            lot = sirens[i:i+50]
            prefixe = f'etablissements_{i//50:04d}'
            if source_reprise:
                donnees, fichiers = lire_lot_archive(source_reprise, prefixe)
                for fichier in fichiers:
                    shutil.copyfile(fichier, dossier / fichier.name)
            else:
                donnees = paginer(session, '/siret', 'etablissements', 'siren:(' + ' OR '.join(lot) + ')', dossier, prefixe)
            for e in donnees:
                siret = e.get('siret', '')
                if not re.fullmatch(r'\d{14}', siret) or siret[:9] not in lot or siret in etablissements:
                    raise RuntimeError('Établissement inattendu ou dupliqué.')
                etablissements[siret] = e
            print(f'Établissements : {min(i+50,len(sirens))}/{len(sirens)} entreprises', flush=True)
        absents = sorted(sirets_initiaux - set(etablissements))
        controles_incomplets = {}
        for siret in absents:
            e, motif = verifier_absent(session, siret, dossier)
            controles_incomplets[siret[:9]] = motif
            if e:
                etablissements[siret] = e
            print('Vérification', siret, ':', motif, flush=True)
        if not etablissements:
            raise RuntimeError('Aucun établissement récupéré : collecte inexploitable.')
        sirets = sorted(etablissements)
        for i in range(0, len(sirets), 50):
            lot = sirets[i:i+50]
            groupe = '(' + ' OR '.join(lot) + ')'
            q = 'siretEtablissementPredecesseur:' + groupe + ' OR siretEtablissementSuccesseur:' + groupe
            donnees = paginer(session, '/siret/liensSuccession', 'liensSuccession', q, dossier, f'liens_{i//50:04d}')
            for lien in donnees:
                pred, succ = lien.get('siretEtablissementPredecesseur',''), lien.get('siretEtablissementSuccesseur','')
                if not re.fullmatch(r'\d{14}',pred) or not re.fullmatch(r'\d{14}',succ) or not {pred,succ}.intersection(lot):
                    raise RuntimeError('Lien sans SIRET attendu.')
                cle = (pred,succ,lien.get('dateLienSuccession'))
                if cle in liens and liens[cle] != lien:
                    raise RuntimeError('Lien modifié pendant la collecte.')
                liens[cle] = lien
            print(f'Liens : {min(i+50,len(sirets))}/{len(sirets)} établissements', flush=True)
    evenements = detecter(list(etablissements.values()), list(liens.values()), creations, jour)
    # Tous les événements des entreprises dont la couverture est incomplète
    # restent à vérifier, même si leur SIRET a été retrouvé individuellement.
    evenements = [(*e[:6], 'a_verifier', 'Couverture incomplète des établissements')
                  if e[1] in controles_incomplets else e for e in evenements]
    controles = [(siren, 'a_verifier' if siren in controles_incomplets else 'population_retrouvee',
                  controles_incomplets.get(siren, 'SIRET historiques retrouvés dans la collecte'), run, jour)
                 for siren in sorted(creations)]
    (dossier/'controles_population.json').write_text(json.dumps(controles, ensure_ascii=False), encoding='utf-8')
    (dossier/'evenements.json').write_text(json.dumps(evenements,ensure_ascii=False), encoding='utf-8')
    manifeste.update(statut='terminee', nombre_etablissements=len(etablissements), nombre_liens=len(liens),
                     nombre_evenements=len(evenements), nombre_siren_a_verifier=len(controles_incomplets), qualifications=dict(Counter(e[6] for e in evenements)))
    suivi.write_text(json.dumps(manifeste,ensure_ascii=False,indent=2), encoding='utf-8')
    if not args.local_only:
        s3=boto3.client('s3')
        for fichier in sorted(p for p in dossier.iterdir() if p != suivi)+[suivi]:
            contenu=fichier.read_bytes(); cle=f'raw/mouvements_etablissements/{run}/{fichier.name}'
            s3.put_object(Bucket=bucket,Key=cle,Body=contenu,ContentType='application/json')
            with s3.get_object(Bucket=bucket,Key=cle)['Body'] as flux:
                if hashlib.sha256(flux.read()).digest()!=hashlib.sha256(contenu).digest():
                    raise RuntimeError('Archive S3 différente.')
    with duckdb.connect(str(base)) as connexion:
        connexion.execute('BEGIN')
        connexion.execute('''create or replace table raw.evenements_etablissements (
            evenement_id varchar primary key, siren varchar, type_evenement varchar,
            date_evenement date, siret_predecesseur varchar, siret_successeur varchar,
            qualification varchar, motif varchar, collecte_id varchar, date_observation date)''')
        if evenements:
            connexion.executemany('insert into raw.evenements_etablissements values (?,?,?,?,?,?,?,?,?,?)',
                                  [(*e,run,jour) for e in evenements])
        connexion.execute('''create or replace table raw.controles_mouvements (
            siren varchar primary key, statut_couverture varchar, motif varchar,
            collecte_id varchar, date_controle date)''')
        connexion.executemany('insert into raw.controles_mouvements values (?,?,?,?,?)', controles)
        connexion.execute('COMMIT')
        print(connexion.execute('''select type_evenement, qualification, count(*) as nombre
            from raw.evenements_etablissements group by all order by 1,2''').fetchall())
    print('Entreprises dont la couverture reste à vérifier :', len(controles_incomplets))
    print('Détection terminée. Aucun score modifié. Archives :', dossier)


if __name__ == '__main__':
    main()
