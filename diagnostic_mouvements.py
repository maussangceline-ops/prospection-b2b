"""Examiner la collecte interrompue, sans appel API ni modification de données."""
import argparse
import json
import os
from collections import Counter
from pathlib import Path
import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--collecte', help='Identifiant du dossier à examiner ; sinon dernière collecte.')
args = parser.parse_args()
parent = ROOT / 'data/raw/mouvements_etablissements'
dossiers = sorted(p for p in parent.iterdir() if p.is_dir() and (p/'collecte.json').is_file()) if parent.is_dir() else []
if not dossiers:
    raise SystemExit('Aucune collecte locale de mouvements trouvée.')
dossier = parent / args.collecte if args.collecte else dossiers[-1]
print('Collecte examinée :', dossier.name)
base = Path(os.getenv('DUCKDB_PATH', str(ROOT/'data/warehouse/prospection.duckdb')))
if not base.is_file():
    raise SystemExit('Base DuckDB absente.')
with duckdb.connect(str(base), read_only=True) as connexion:
    historiques = {r[0] for r in connexion.execute('select siret from raw.sirene_etablissements').fetchall()}
recus = set()
par_siren = Counter()
nombre_lignes = 0
anomalies = []
lots = {}
for fichier in sorted(dossier.glob('etablissements_*.json')):
    payload = json.loads(fichier.read_text(encoding='utf-8'))
    header = payload.get('header', {})
    items = payload.get('etablissements', [])
    lot = fichier.stem.rsplit('_',1)[0]
    suivi = lots.setdefault(lot, {'totaux':set(), 'recu':0})
    suivi['totaux'].add(header.get('total'))
    suivi['recu'] += len(items)
    if header.get('statut') != 200:
        anomalies.append(fichier.name + ': statut ' + str(header.get('statut')))
    for item in items:
        siret = item.get('siret')
        if not siret:
            anomalies.append(fichier.name + ': SIRET absent')
            continue
        nombre_lignes += 1
        recus.add(siret)
for siret in recus:
    par_siren[siret[:9]] += 1
for lot,suivi in lots.items():
    if suivi['totaux'] != {suivi['recu']}:
        anomalies.append(lot + ': pagination incomplète ou total changeant')
absents = sorted(historiques-recus)
sirens_historiques = {s[:9] for s in historiques}
sirens_absents = sirens_historiques-set(par_siren)
print('Lots enregistrés :', len(lots))
print('Anomalies de pages :', len(anomalies))
for a in anomalies[:10]: print('  ',a)
print('SIRET historiques :', len(historiques))
print('Établissements distincts récupérés (sièges et secondaires) :', len(recus))
print('Doublons dans les pages :', nombre_lignes-len(recus))
print('SIRET historiques absents :', len(absents))
print('SIREN historiques sans aucun établissement reçu :', len(sirens_absents))
print('SIRET absents mais même SIREN présent :', sum(s[:9] in par_siren for s in absents))
print('\nExemples limités à 20 (aucun nom ni adresse) :')
for siret in absents[:20]:
    print(siret, '| établissements reçus pour ce SIREN :', par_siren[siret[:9]])
print('\nLecture seule terminée. Aucun appel API ; aucun fichier modifié.')
