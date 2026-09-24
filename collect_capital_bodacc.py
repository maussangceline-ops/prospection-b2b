"""Collecte réelle des observations de capital BODACC. Aucun score modifié.
Dépend du collect_bodacc.py existant (client HTTP et contrôles de pagination).
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
ROOT = Path(__file__).resolve().parent


def objet(value):
    if isinstance(value, dict): return value
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError): return {}


def montant(value):
    if value is None or isinstance(value, bool): return None
    text = str(value).replace('\u00a0', '').replace('\u202f', '').replace(' ', '')
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?', text): return None
    try:
        number = Decimal(text.replace(',', '.'))
        return format(number, '.2f') if number.is_finite() else None
    except InvalidOperation: return None


def texte(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))


def personnes(value):
    value = objet(value)
    result = value.get('personne', [])
    return result if isinstance(result, list) else [result] if isinstance(result, dict) else []


def observation(annonce, siren):
    matches = [p for p in personnes(annonce.get('listepersonnes'))
               if re.sub(r'\s', '', str(objet(p.get('numeroImmatriculation')).get('numeroIdentification', ''))) == siren]
    description = str(objet(annonce.get('modificationsgenerales')).get('descriptif') or '')
    capital = objet(matches[0].get('capital')) if len(matches) == 1 else {}
    value = montant(capital.get('montantCapital'))
    currency = str(capital.get('devise') or '').upper().strip()
    reason = ''
    if len(matches) != 1: reason = 'personne_absente_ou_ambigue'
    elif annonce.get('typeavis') != 'annonce': reason = 'avis_non_initial'
    elif value is None: reason = 'montant_absent_ou_invalide'
    elif not currency: reason = 'devise_absente'
    # Un capital variable n'est pas comparable à un capital fixe sans interprétation.
    elif any('variab' in texte(key) for key in capital) or 'capital variable' in texte(description): reason = 'capital_variable'
    elif not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(annonce.get('dateparution') or '')): reason = 'date_publication_invalide'
    return dict(siren=siren, id_annonce=annonce['id'], date_publication=annonce.get('dateparution'),
                famille=annonce.get('familleavis'), type_avis=annonce.get('typeavis'),
                montant_capital=value, devise=currency, descriptif=description,
                mention_capital=bool(re.search(r'\bcapital\b', texte(description))),
                statut_observation=reason or 'montant_lisible',
                capital_source=capital,
                url_annonce='https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:' + annonce['id'])


def comparer(observations):
    """Écarts d'observation, jamais événements confirmés ni dates d'effet inventées."""
    groups=defaultdict(list)
    for obs in observations: groups[obs['siren']].append(obs)
    results=[]
    for siren, rows in groups.items():
        by_id={row['id_annonce']:row for row in rows}
        rows=sorted(by_id.values(),key=lambda row:(row['date_publication'] or '',row['id_annonce']))
        # Une correction peut invalider un montant déjà publié : tout le dossier à revoir.
        if any(row['type_avis'] != 'annonce' for row in rows): continue
        per_day=Counter(row['date_publication'] for row in rows if row['montant_capital'] is not None)
        previous=None
        for row in rows:
            if row['statut_observation'] != 'montant_lisible':
                if row['mention_capital'] or row['montant_capital'] is not None: previous=None
                continue
            if per_day[row['date_publication']] > 1:
                previous=None
                continue
            if previous and previous['devise'] == row['devise']:
                difference=Decimal(row['montant_capital'])-Decimal(previous['montant_capital'])
                if difference:
                    results.append(dict(siren=siren,id_annonce_avant=previous['id_annonce'],
                        id_annonce_apres=row['id_annonce'],date_publication_avant=previous['date_publication'],
                        date_publication_apres=row['date_publication'],date_effet=None,
                        capital_avant=previous['montant_capital'],capital_apres=row['montant_capital'],
                        devise=row['devise'],variation_observee='hausse' if difference>0 else 'baisse',
                        qualification='a_confirmer',motif='Écart entre deux publications ; date d’effet et opération à confirmer',
                        mention_capital=row['mention_capital'],descriptif=row['descriptif'],
                        url_annonce_avant=previous['url_annonce'],url_annonce_apres=row['url_annonce']))
            previous=row
    return results


def recuperer_lot(session, sirens, jour, dossier, numero):
    from collect_bodacc import demander, sirens_annonce
    ids=sorted(set(sirens)|{' '.join((s[:3],s[3:6],s[6:])) for s in sirens})
    # Tout l'historique publié : un état antérieur peut précéder les 12 mois.
    where=f'dateparution <= "{jour}" AND registre IN ('+','.join('"'+s+'"' for s in ids)+')'
    total_attendu=None; annonces={}; offset=0
    while True:
        response=demander(session,dict(where=where,limit=100,offset=offset,order_by='dateparution ASC, id ASC'))
        (dossier/f'lot_{numero:04d}_page_{offset//100+1:04d}.json').write_bytes(response.content)
        payload=response.json(); total=int(payload['total_count'])
        if total_attendu is None: total_attendu=total
        if total != total_attendu or total>10000: raise RuntimeError('Volume instable ou limite de pagination dépassée ; aucune table remplacée.')
        rows=payload['results']
        for row in rows:
            if not isinstance(row.get('id'),str) or not sirens_annonce(row).intersection(sirens): raise RuntimeError('Annonce sans identité attendue.')
            if row['id'] in annonces: raise RuntimeError('Pagination dupliquée.')
            annonces[row['id']]=row
        offset+=len(rows)
        if offset==total_attendu: return list(annonces.values())
        if not rows or offset>total_attendu: raise RuntimeError('Pagination incomplète.')


def main():
    import boto3
    import duckdb
    import requests
    from dotenv import load_dotenv
    from collect_bodacc import sirens_annonce, URL
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only',action='store_true',help='Ne pas archiver dans S3.')
    args=parser.parse_args()
    load_dotenv(ROOT/'.env',override=False)
    db=Path(os.getenv('DUCKDB_PATH',str(ROOT/'data/warehouse/prospection.duckdb')))
    if not db.is_file(): raise SystemExit('Base DuckDB absente.')
    bucket=os.getenv('S3_BUCKET_NAME')
    if not args.local_only and not bucket: raise SystemExit('S3_BUCKET_NAME absent.')
    with duckdb.connect(str(db),read_only=True) as con:
        sirens=[r[0] for r in con.execute('select distinct substr(siret,1,9) from raw.sirene_etablissements order by 1').fetchall()]
    if not sirens or any(not re.fullmatch(r'\d{9}',s or '') for s in sirens): raise SystemExit('Population SIREN invalide.')
    now=datetime.now(timezone.utc); jour=now.date().isoformat(); run=now.strftime('%Y%m%dT%H%M%S%fZ')
    folder=ROOT/'data/raw/capital_bodacc'/run;folder.mkdir(parents=True)
    meta=dict(collecte_id=run,date_collecte=jour,source=URL,statut='en_cours',nombre_sirens=len(sirens),score_modifie=False)
    def save(name,value): (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    save('collecte.json',meta)
    obs=[]; records={}; covered=set()
    with requests.Session() as session:
        session.headers.update({'Accept':'application/json','User-Agent':'prospection-b2b/1.0'})
        for i in range(0,len(sirens),25):
            lot=sirens[i:i+25]
            for row in recuperer_lot(session,lot,jour,folder,i//25+1):
                for siren in sirens_annonce(row).intersection(lot):
                    records[(siren,row['id'])]=row;covered.add(siren)
                    # Les actes sans capital restent archivés, pas dans la série de montants.
                    parsed=observation(row,siren)
                    if parsed['capital_source'] or parsed['mention_capital'] or row.get('typeavis')!='annonce': obs.append(parsed)
            print(f'Capital BODACC : {min(i+25,len(sirens))}/{len(sirens)} entreprises',flush=True)
    candidates=comparer(obs)
    report=dict(entreprises_interrogees=len(sirens),entreprises_sans_annonce=len(set(sirens)-covered),
        observations=len(obs),montants_lisibles=sum(o['statut_observation']=='montant_lisible' for o in obs),
        repartition_observations=dict(Counter(o['statut_observation'] for o in obs)),
        variations_a_confirmer=dict(Counter(c['variation_observee'] for c in candidates)),
        entreprises_avec_variation=len({c['siren'] for c in candidates}),aucun_score_modifie=True)
    save('observations.json',obs);save('variations_a_confirmer.json',candidates);save('diagnostic.json',report)
    meta.update(statut='terminee',nombre_annonces_siren=len(records));save('collecte.json',meta)
    if not args.local_only:
        s3=boto3.client('s3'); files=sorted(p for p in folder.iterdir() if p.name!='collecte.json')+[folder/'collecte.json']
        for i,file in enumerate(files,1):
            body=file.read_bytes();key=f'raw/capital_bodacc/{run}/{file.name}'
            s3.put_object(Bucket=bucket,Key=key,Body=body,ContentType='application/json')
            with s3.get_object(Bucket=bucket,Key=key)['Body'] as stream:
                if hashlib.sha256(stream.read()).digest()!=hashlib.sha256(body).digest(): raise RuntimeError('Archive S3 différente : '+key)
            if i%50==0 or i==len(files): print(f'Archives S3 : {i}/{len(files)}',flush=True)
    with duckdb.connect(str(db)) as con:
        con.execute('begin')
        for table, rows in [('capital_observations',obs),('capital_variations_a_confirmer',candidates)]:
            con.execute(f'create or replace table raw.{table}(siren varchar,collecte_id varchar,date_collecte date,donnees json)')
            if rows: con.executemany(f'insert into raw.{table} values (?,?,?,?)',[(r['siren'],run,jour,json.dumps(r,ensure_ascii=False)) for r in rows])
        con.execute('create or replace table raw.capital_annonces(siren varchar,id_annonce varchar,collecte_id varchar,donnees json, primary key(siren,id_annonce))')
        if records: con.executemany('insert into raw.capital_annonces values (?,?,?,?)',[(s,i,run,json.dumps(r,ensure_ascii=False)) for (s,i),r in records.items()])
        con.execute('commit')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Collecte terminée. Aucun score modifié. Archives :',folder)

if __name__=='__main__': main()
