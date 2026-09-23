"""Tableau de bord commercial — lecture seule, sans recalcul du score."""
import io
import os
from pathlib import Path

import boto3
import duckdb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
st.set_page_config(page_title='Prospection B2B', page_icon='🧜‍♀️', layout='wide')

NAF = {
    '58.29C': 'Édition de logiciels',
    '62.02A': 'Conseil informatique',
    '62.01Z': 'Programmation informatique',
}
PRIORITES = {'vert': '🟢 Prioritaire', 'orange': '🟠 Non prioritaire'}


def option(nom, defaut=''):
    valeur = os.getenv(nom)
    if valeur is not None:
        return valeur
    try:
        return str(st.secrets.get(nom, defaut))
    except FileNotFoundError:
        return defaut


@st.cache_data(ttl=300, show_spinner='Chargement des entreprises…')
def charger_donnees(mode, chemin, empreinte, bucket, cle):
    if mode == 'local':
        with duckdb.connect(chemin, read_only=True) as connexion:
            return connexion.sql('select * from analytics.mart_prospects_scores').df()
    parametres = {'region_name': option('AWS_DEFAULT_REGION', 'eu-west-3')}
    access = option('AWS_ACCESS_KEY_ID')
    secret = option('AWS_SECRET_ACCESS_KEY')
    if access and secret:
        parametres.update(aws_access_key_id=access, aws_secret_access_key=secret)
        if option('AWS_SESSION_TOKEN'):
            parametres['aws_session_token'] = option('AWS_SESSION_TOKEN')
    client = boto3.client('s3', **parametres)
    reponse = client.get_object(Bucket=bucket, Key=cle)
    with reponse['Body'] as flux:
        return pd.read_parquet(io.BytesIO(flux.read()))


st.title('🧜‍♀️ Le chant des SIREN')
st.caption('Savoir-faire et faire savoir de la tech')
chemin = Path(option('DUCKDB_PATH', str(ROOT / 'data/warehouse/prospection.duckdb')))
mode = option('DATA_SOURCE', 'local' if chemin.is_file() else 's3')
if mode not in ('local', 's3'):
    st.error('DATA_SOURCE doit valoir local ou s3.')
    st.stop()
if mode == 'local' and not chemin.is_file():
    st.error('Base locale introuvable. Charge les données et exécute dbt avant de démarrer.')
    st.stop()
bucket = option('S3_BUCKET_NAME')
if mode == 's3' and not bucket:
    st.error('Renseigne S3_BUCKET_NAME dans les paramètres de connexion de l’application.')
    st.stop()
if st.sidebar.button('Actualiser les données'):
    charger_donnees.clear()
try:
    donnees = charger_donnees(
        mode, str(chemin), chemin.stat().st_mtime_ns if mode == 'local' else 0,
        bucket, option('S3_SCORES_KEY', 'processed/prospects/current.parquet'),
    )
except Exception:
    st.error('Chargement impossible. Vérifie la connexion, les droits de lecture et la publication des résultats. En local, termine dbt avant de relancer.')
    st.stop()

requis = {
    'siret', 'siren', 'nom_affiche', 'nom_commune', 'nom_departement',
    'code_departement', 'code_postal', 'code_postal_masque', 'naf_etablissement',
    'libelle_age', 'couleur_priorite', 'score_total', 'score_anciennete', 'bonus_naf',
    'date_creation_entreprise', 'date_evaluation', 'date_reference', 'mois_collecte',
    'angle_commercial', 'version_score', 'anciennete_jours',
}
if requis - set(donnees.columns):
    st.error('Les résultats ne contiennent pas toutes les colonnes attendues. Reconstruis les modèles dbt et republie les résultats.')
    st.stop()
if donnees.empty:
    st.info('Aucun établissement disponible.')
    st.stop()
for colonne in ['siret', 'siren', 'code_departement', 'code_postal']:
    donnees[colonne] = donnees[colonne].astype('string')
donnees['activite'] = donnees['naf_etablissement'].map(NAF).fillna('Autre activité')
donnees['priorite'] = donnees['couleur_priorite'].map(PRIORITES).fillna('Hors périmètre V1')
donnees['departement'] = donnees['code_departement'] + ' — ' + donnees['nom_departement']
donnees['code_postal_affiche'] = donnees['code_postal'].fillna('Non renseigné')
donnees.loc[donnees['code_postal_masque'].fillna(False), 'code_postal_affiche'] = 'Non diffusé'
for colonne in ['date_evaluation', 'date_reference', 'date_creation_entreprise']:
    donnees[colonne] = pd.to_datetime(donnees[colonne])
dates = donnees['date_evaluation'].dropna().unique()
if len(dates) != 1:
    st.error('Le fichier doit contenir une seule date d’évaluation.')
    st.stop()
date_score = pd.Timestamp(dates[0]).strftime('%d/%m/%Y')
st.caption(f"Évaluation au {date_score} · Créations collectées de {donnees['mois_collecte'].min()} à {donnees['mois_collecte'].max()}")
st.caption('Statuts administratifs correspondant à la date de collecte')

st.sidebar.header('Votre sélection')
priorites = st.sidebar.multiselect('Priorité', list(PRIORITES.values()) + ['Hors périmètre V1'], default=list(PRIORITES.values()) + ['Hors périmètre V1'])
ages = st.sidebar.multiselect('Âge', donnees.sort_values('anciennete_jours')['libelle_age'].drop_duplicates().tolist())
activites = st.sidebar.multiselect('Activité', list(NAF.values()))
departements = st.sidebar.multiselect('Département', sorted(donnees['departement'].dropna().unique()))
mois = st.sidebar.multiselect('Mois de création collecté', sorted(donnees['mois_collecte'].unique()))
recherche = st.sidebar.text_input('Nom, SIRET ou commune').strip()
filtre = donnees[donnees['priorite'].isin(priorites)].copy()
for colonne, choix in [('libelle_age', ages), ('activite', activites), ('departement', departements), ('mois_collecte', mois)]:
    if choix:
        filtre = filtre[filtre[colonne].isin(choix)]
if recherche:
    masque = pd.Series(False, index=filtre.index)
    for colonne in ['nom_affiche', 'siret', 'nom_commune']:
        masque |= filtre[colonne].astype('string').str.contains(recherche, case=False, regex=False, na=False)
    filtre = filtre[masque]

indicateurs = st.columns(4)
for bloc, titre, valeur in zip(indicateurs,
    ['Établissements sélectionnés', '🟢 Prioritaires', '🟠 Non prioritaires', 'Hors périmètre V1'],
    [len(filtre), filtre['couleur_priorite'].eq('vert').sum(), filtre['couleur_priorite'].eq('orange').sum(), filtre['score_total'].isna().sum()]):
    bloc.metric(titre, f'{valeur:,}'.replace(',', ' '))
st.caption(f"Base complète : {len(donnees):,} établissements. Les indicateurs et graphiques suivent les filtres.".replace(',', ' '))

if filtre.empty:
    st.info('Aucun établissement ne correspond à ces filtres.')
else:
    gauche, droite = st.columns(2)
    with gauche:
        st.subheader('Activités')
        st.bar_chart(filtre.groupby('activite').size().rename('Établissements'), horizontal=True)
    with droite:
        st.subheader('Départements')
        st.bar_chart(filtre.groupby('departement').size().rename('Établissements'), horizontal=True)
    st.subheader('Établissements')
    filtre = filtre.sort_values(['score_total', 'date_creation_entreprise', 'siret'], ascending=[False, False, True], na_position='last')
    colonnes = {
        'nom_affiche': 'Entreprise', 'siret': 'SIRET', 'nom_commune': 'Commune',
        'code_postal_affiche': 'Code postal', 'departement': 'Département',
        'activite': 'Activité', 'libelle_age': 'Âge', 'priorite': 'Priorité',
        'angle_commercial': 'Angle commercial', 'score_total': 'Score total',
        'score_anciennete': 'Points ancienneté', 'bonus_naf': 'Bonus NAF', 
        'date_creation_entreprise': 'Création',
        'date_reference': 'Référence Sirene', 'date_evaluation': 'Évaluation',
    }
    affichage = filtre[list(colonnes)].rename(columns=colonnes)
    st.dataframe(affichage, hide_index=True, width='stretch')
    # Neutraliser les cellules texte pouvant être interprétées comme des formules.
    export = affichage.copy()
    for colonne in export.select_dtypes(include=['object', 'string']).columns:
        export[colonne] = export[colonne].map(lambda valeur: "'" + valeur if isinstance(valeur, str) and valeur.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else valeur)
    st.download_button('Télécharger la sélection CSV', export.to_csv(index=False, sep=';').encode('utf-8-sig'), file_name=f'prospects_{pd.Timestamp(dates[0]):%Y%m%d}.csv', mime='text/csv')

with st.expander('Comprendre le classement'):
    st.markdown('''**Ancienneté :** Babies (moins de 3 mois) et Premiers pas (9 à moins de 12 mois) : 100 points. Newbies (3 à moins de 9 mois) : 50 points.

**Activité :** édition +30 ; conseil +20 ; programmation +10.

**Priorité :** vert à partir de 81 points ; orange jusqu’à 80.
À partir du premier anniversaire : hors périmètre V1, sans score ni couleur.

Le score exprime une priorité métier, pas une probabilité de vente.
Les codes postaux masqués et les statuts de diffusion ne modifient pas le score.
Les résultats ne sont pas une liste de contacts vérifiés.''')
