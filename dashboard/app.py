"""Le chant des SIREN — interface commerciale, scores dbt en lecture seule."""
import hashlib
import io
import json
import os
from pathlib import Path

import boto3
import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
NAF = {'58.29C': 'Édition de logiciels', '62.02A': 'Conseil informatique', '62.01Z': 'Programmation informatique'}
PRIORITES = {'vert': '🟢 Prioritaire', 'orange': '🟠 Non prioritaire'}
REQUIRED = {'siret','siren','nom_affiche','nom_commune','nom_departement','code_departement',
    'naf_etablissement','libelle_age','couleur_priorite','score_total','date_creation_entreprise',
    'date_evaluation','mois_collecte','angle_commercial','anciennete_jours','admissible_prospection',
    'disponibilite_nom','categorie_juridique_actuelle','codes_postaux_commune'}
DISPLAY = {'nom_affiche':'Entreprise','priorite':'Priorité','angle_commercial':'Angle commercial',
    'score_total':'Score total','libelle_age':'Âge','activite':'Activité','nom_commune':'Commune',
    'codes_postaux_commune':'Code postal','libelle_categorie_juridique':'Catégorie juridique',
    'siret':'SIRET','date_creation_entreprise':'Création'}
COLORS = {'🟢 Prioritaire':'#18806F','🟠 Non prioritaire':'#D68B2D','Non scorée':'#8391A5'}


def option(name, default=''):
    if os.getenv(name) is not None:
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except FileNotFoundError:
        return default


@st.cache_data(ttl=300, show_spinner=False)
def charger_donnees(mode, chemin, empreinte, bucket, cle):
    if mode == 'local':
        with duckdb.connect(chemin, read_only=True) as connexion:
            return connexion.sql('select * from analytics.mart_prospects_scores').df()
    args = {'region_name': option('AWS_DEFAULT_REGION', 'eu-west-3')}
    access, secret = option('AWS_ACCESS_KEY_ID'), option('AWS_SECRET_ACCESS_KEY')
    if access and secret:
        args.update(aws_access_key_id=access, aws_secret_access_key=secret)
        if option('AWS_SESSION_TOKEN'):
            args['aws_session_token'] = option('AWS_SESSION_TOKEN')
    client = boto3.client('s3', **args)
    response = client.get_object(Bucket=bucket, Key=cle)
    with response['Body'] as stream:
        return pd.read_parquet(io.BytesIO(stream.read()))


def preparer_donnees(raw, legal):
    missing = REQUIRED - set(raw.columns)
    if missing:
        raise ValueError('Résultats incomplets : ' + ', '.join(sorted(missing)))
    # Toujours filtrer AVANT toute option, statistique, fiche ou export.
    names = raw['nom_affiche'].astype('string').str.strip()
    valid = (raw['admissible_prospection'].eq(True).fillna(False)
             & raw['disponibilite_nom'].eq('Disponible').fillna(False)
             & names.notna() & names.ne('') & ~names.str.upper().isin(['ND','NR','[ND]']))
    df = raw.loc[valid].copy()
    df['nom_affiche'] = names.loc[valid]
    for col in ['siret','siren','code_departement','mois_collecte']:
        df[col] = df[col].astype('string')
    if df['siret'].isna().any() or df['siret'].duplicated().any():
        raise ValueError('Identifiants absents ou dupliqués dans les résultats commerciaux.')
    for col in ['date_evaluation','date_creation_entreprise']:
        df[col] = pd.to_datetime(df[col], errors='coerce')
    if not df.empty and (df['date_evaluation'].isna().any() or df['date_evaluation'].nunique() != 1):
        raise ValueError('Les résultats doivent contenir une seule date d’évaluation renseignée.')
    for col in ['score_total','anciennete_jours','score_anciennete','bonus_naf','bonus_transferts','bonus_capital',
                'nombre_transferts_12_mois','nombre_hausses_capital_12_mois','nombre_baisses_capital_12_mois']:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    codes = df['categorie_juridique_actuelle'].astype('string').str.strip().str.replace(r'\.0$', '', regex=True).str.zfill(4)
    df['libelle_categorie_juridique'] = codes.map(legal).fillna('Forme juridique non renseignée')
    df['activite'] = df['naf_etablissement'].map(NAF).fillna('Autre activité')
    df['priorite'] = df['couleur_priorite'].map(PRIORITES).fillna('Non scorée')
    df['departement'] = df['code_departement'].fillna('') + ' — ' + df['nom_departement'].fillna('Non renseigné')
    df['nom_commune'] = df['nom_commune'].astype('string').str.replace(r'^Paris\s+(\d{1,2}(?:er|e))\s+Arrondissement$', r'Paris \1', regex=True, flags=2)
    return df


def filtrer(df, choix, recherche='', priorite='Toutes', signal='Tous'):
    mask = pd.Series(True,index=df.index)
    for column, values in choix.items():
        if values:
            mask &= df[column].isin(values)
    if priorite != 'Toutes':
        mask &= df['priorite'].eq(priorite)
    signals = {'Transfert confirmé':'nombre_transferts_12_mois',
               'Hausse de capital publiée':'nombre_hausses_capital_12_mois',
               'Baisse de capital publiée':'nombre_baisses_capital_12_mois'}
    if signal in signals:
        column = signals[signal]
        mask &= df[column].gt(0) if column in df else False
    if recherche.strip():
        found = pd.Series(False,index=df.index)
        for column in ['nom_affiche','siret','siren','nom_commune']:
            found |= df[column].astype('string').str.contains(recherche.strip(), case=False, regex=False, na=False)
        mask &= found
    return df.loc[mask].copy()


def exporter_csv(df):
    exported = df[list(DISPLAY)].rename(columns=DISPLAY).copy()
    exported['Création'] = pd.to_datetime(exported['Création']).dt.strftime('%Y-%m-%d')
    # Neutralisation de formules Excel dans toutes les cellules texte, y compris dtype mixte.
    for col in exported.columns:
        exported[col] = exported[col].map(lambda value: "'" + value if isinstance(value,str)
            and (value.startswith(('\t','\r','\n')) or value.lstrip().startswith(('=','+','-','@'))) else value)
    return exported.to_csv(index=False,sep=';').encode('utf-8-sig')


def nombre(value):
    return '—' if pd.isna(value) else f'{value:,.0f}'.replace(',', ' ')


def reset_filters():
    for key in list(st.session_state):
        if key.startswith('filtre_'):
            del st.session_state[key]


def fiche(row):
    with st.container(border=True):
        st.caption('FICHE ENTREPRISE')
        st.subheader(str(row['nom_affiche']))
        st.write(f"{row['priorite']} · {row['libelle_age']} · {row['activite']}")
        c1,c2,c3 = st.columns(3)
        c1.metric('Score publié',nombre(row['score_total']))
        c2.write('**Commune**'); c2.write(str(row['nom_commune']))
        c3.write('**Code postal**'); c3.write(str(row['codes_postaux_commune']) if pd.notna(row['codes_postaux_commune']) else 'Non renseigné')
        st.write('**Angle commercial**')
        st.write(str(row['angle_commercial']) if pd.notna(row['angle_commercial']) else 'Pas d’angle proposé pour ce profil.')
        labels = {'score_anciennete':'Ancienneté','bonus_naf':'Activité NAF',
                  'bonus_transferts':'Transferts confirmés','bonus_capital':'Capital publié'}
        if pd.isna(row['score_total']):
            st.info('Hors du scoring V1 : aucune priorité calculée. Les profils d’un an ou plus restent consultables.')
        else:
            cols = st.columns(4)
            for block,(key,label) in zip(cols,labels.items()):
                block.metric(label,nombre(row.get(key)))
            if not all(key in row.index for key in labels):
                st.caption('Le détail de certaines composantes n’est pas disponible dans cet export.')
        date_publication = pd.to_datetime(row.get('date_derniere_publication_capital'),errors='coerce')
        if pd.notna(date_publication):
            st.caption('Variation de capital publiée le ' + date_publication.strftime('%d/%m/%Y') + ' · référence : publication BODACC, pas date d’effet.')
        with st.expander('Identité et localisation'):
            st.write('**Forme juridique :** '+str(row['libelle_categorie_juridique']))
            st.write('**Département :** '+str(row['departement']))
            st.write('**SIREN :** '+str(row['siren'])+' · **SIRET :** '+str(row['siret']))
            st.write('**Création :** '+(row['date_creation_entreprise'].strftime('%d/%m/%Y') if pd.notna(row['date_creation_entreprise']) else 'Non renseignée'))
            st.caption('Les codes postaux sont ceux de la commune ; ils ne confirment pas l’adresse de cet établissement.')


def chart(df,column,title):
    counts=df.groupby([column,'priorite'],dropna=False).size().reset_index(name='Établissements')
    order=df.groupby(column).size().sort_values().index.tolist()
    fig=px.bar(counts,x='Établissements',y=column,color='priorite',orientation='h',
               color_discrete_map=COLORS,labels={column:'','priorite':'Priorité'},
               category_orders={'priorite':list(COLORS)},title=title)
    fig.update_layout(height=max(310,45*len(order)+100),margin=dict(l=0,r=10,t=45,b=15),
                      paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
                      legend=dict(orientation='h',y=-0.25),yaxis=dict(categoryorder='array',categoryarray=order))
    fig.update_traces(hovertemplate='%{y}<br>%{x} établissements<extra>%{fullData.name}</extra>')
    st.plotly_chart(fig,width='stretch',config={'displayModeBar':False})


def methode():
    st.subheader('Un score explicable, une priorité commerciale')
    st.write('Le score exprime des hypothèses métier. Il ne mesure pas une probabilité de vente et ne garantit ni budget ni coordonnées de contact.')
    st.table(pd.DataFrame([
        ['Babies · moins de 3 mois','100'],['Newbies · de 3 à moins de 9 mois','50'],
        ['Premiers pas · de 9 à moins de 12 mois','100'],['Édition / conseil / programmation','+30 / +20 / +10'],
        ['Transferts confirmés · 12 derniers mois','+50 pour le premier, +25 par suivant'],
        ['Hausses de capital publiées · 12 derniers mois','+50 pour la première, +25 par suivante'],
        ['Baisses de capital publiées · 12 derniers mois','−25 chacune'],
        ['À partir de 12 mois d’âge','Non scorée']],columns=['Critère','Points']))
    st.write('**Priorité :** vert à partir de 81 points ; orange jusqu’à 80 inclus. Le score peut dépasser 100 ou devenir négatif.')
    st.write('**Dates :** mois calendaires pour l’âge. Fenêtre glissante de 12 mois pour les événements ; pour le capital, la date retenue est celle de publication BODACC.')
    st.write('Les événements initiaux ne donnent pas de bonus. Les ouvertures potentielles restent sans points. Les chiffres d’affaires fictifs prévus pour les tests ne sont pas utilisés ici.')
    st.caption('La catégorie juridique et la localisation servent à filtrer ; elles ne donnent pas de points. Seuls les établissements admissibles et disposant d’un nom exploitable sont affichés.')


def main():
    load_dotenv(ROOT/'.env',override=False)
    st.set_page_config(page_title='Le chant des SIREN · Prospection',page_icon='🧜‍♀️',layout='wide')
    st.markdown('''<style>
    .block-container {padding-top:2rem; padding-bottom:2rem; max-width:1600px;}
    [data-testid="stMetric"] {border:1px solid rgba(128,145,163,.28);border-radius:12px;padding:16px;}
    [data-testid="stMetricLabel"] {font-size:.88rem;}
    h1 {letter-spacing:-.035em;}
    </style>''',unsafe_allow_html=True)
    head,image = st.columns([2,1],vertical_alignment='center')
    with head:
        st.caption('PROSPECTION B2B · ÎLE-DE-FRANCE')
        st.title('Le chant des SIREN')
        st.write('Savoir-faire et faire savoir de la tech')
    banner=Path(__file__).parent/'bandeau_sirene.png'
    if banner.is_file():image.image(str(banner),width='stretch')
    with st.sidebar:
        st.header('Affiner la sélection')
        st.button('Réinitialiser les filtres',on_click=reset_filters,width='stretch')
        refresh=st.button('Actualiser les données',width='stretch',help='Recharge la dernière publication. Ne relance pas la collecte.')
    if refresh:charger_donnees.clear()
    path=Path(option('DUCKDB_PATH',str(ROOT/'data/warehouse/prospection.duckdb')))
    mode=option('DATA_SOURCE','local' if path.is_file() else 's3')
    if mode not in ('local','s3') or (mode=='local' and not path.is_file()):
        st.error('Source de données indisponible. Contactez le responsable de l’application.');st.stop()
    bucket=option('S3_BUCKET_NAME')
    if mode=='s3' and not bucket:
        st.error('La connexion aux résultats publiés n’est pas configurée.');st.stop()
    try:
        legal=json.loads((Path(__file__).parent/'categories_juridiques.json').read_text(encoding='utf-8'))['libelles']
        with st.spinner('Préparation de votre espace de prospection…'):
            raw=charger_donnees(mode,str(path),path.stat().st_mtime_ns if mode=='local' else 0,bucket,option('S3_SCORES_KEY','processed/prospects/current.parquet'))
            df=preparer_donnees(raw,legal)
    except (OSError,ValueError,KeyError) as error:
        st.error('Les résultats ou le référentiel ne sont pas exploitables. Contactez le responsable de l’application.')
        # Aucun contenu de configuration, secret ou exception AWS affiché.
        if isinstance(error,ValueError) and str(error).startswith('Résultats incomplets'):
            st.caption('Une publication plus récente du modèle de données est nécessaire.')
        st.stop()
    except Exception:
        st.error('Chargement momentanément impossible. Réessayez ou contactez le responsable de l’application.');st.stop()
    if df.empty:
        st.info('Aucun établissement disponible pour la prospection actuellement.');st.stop()
    evaluated=df['date_evaluation'].iloc[0]
    st.caption(f"Évaluation au {evaluated:%d/%m/%Y} · {nombre(len(df))} établissements disponibles · créations collectées de {df['mois_collecte'].min()} à {df['mois_collecte'].max()}")
    choices={}
    with st.sidebar:
        for column,label in [('activite','Activité'),('departement','Département'),('libelle_age','Âge')]:
            options=sorted(df[column].dropna().unique().tolist())
            if column=='libelle_age':options=df.sort_values('anciennete_jours')[column].dropna().drop_duplicates().tolist()
            key='filtre_'+column
            if key in st.session_state:st.session_state[key]=[v for v in st.session_state[key] if v in options]
            choices[column]=st.multiselect(label,options,key=key,help='Sans sélection : toutes les valeurs.')
        with st.expander('Autres critères'):
            for column,label in [('libelle_categorie_juridique','Forme juridique'),('mois_collecte','Mois de création collecté')]:
                options=sorted(df[column].dropna().unique().tolist());key='filtre_'+column
                if key in st.session_state:st.session_state[key]=[v for v in st.session_state[key] if v in options]
                choices[column]=st.multiselect(label,options,key=key)
            signals={'Transfert confirmé':'nombre_transferts_12_mois','Hausse de capital publiée':'nombre_hausses_capital_12_mois','Baisse de capital publiée':'nombre_baisses_capital_12_mois'}
            options=['Tous']+[k for k,v in signals.items() if v in df]
            if st.session_state.get('filtre_signal','Tous') not in options:st.session_state['filtre_signal']='Tous'
            signal=st.selectbox('Événement sur les 12 derniers mois',options,key='filtre_signal')
    search=st.text_input('Rechercher une entreprise',placeholder='Nom, SIREN, SIRET ou commune…',key='filtre_recherche')
    priority=st.radio('Priorité',['Toutes']+list(PRIORITES.values())+['Non scorée'],horizontal=True,key='filtre_priorite')
    filtered=filtrer(df,choices,search,priority,signal)
    metrics=st.columns(4)
    for col,title,value in zip(metrics,['Dans votre sélection','Prioritaires','Non prioritaires','Non scorées'],
                              [len(filtered),filtered['couleur_priorite'].eq('vert').sum(),filtered['couleur_priorite'].eq('orange').sum(),filtered['score_total'].isna().sum()]):
        col.metric(title,nombre(value))
    st.caption('Tous les indicateurs et exports suivent votre sélection. Aucun critère sélectionné dans un menu multiple signifie « tous ».')
    view=st.radio('Navigation',['Prospects','Vue d’ensemble','Méthode'],horizontal=True,label_visibility='collapsed',key='navigation')
    if view=='Méthode':methode();return
    if filtered.empty:
        st.info('Aucun résultat. Élargissez vos critères ou réinitialisez les filtres.');return
    if view=='Vue d’ensemble':
        left,right=st.columns(2)
        with left:chart(filtered,'activite','Répartition par activité')
        with right:chart(filtered,'departement','Répartition par département')
        st.caption('Les graphiques décrivent la sélection actuelle ; les couleurs reprennent les priorités publiées.')
        return
    st.subheader('Votre liste de prospection')
    toolbar=st.columns([2,1,1])
    sort=toolbar[0].selectbox('Trier par',['Score décroissant','Création la plus récente','Nom de l’entreprise'])
    page_size=toolbar[1].selectbox('Lignes par page',[25,50,100],index=1)
    if sort=='Score décroissant':filtered=filtered.sort_values(['score_total','date_creation_entreprise','siret'],ascending=[False,False,True],na_position='last')
    elif sort=='Création la plus récente':filtered=filtered.sort_values(['date_creation_entreprise','siret'],ascending=[False,True],na_position='last')
    else:filtered=filtered.sort_values(['nom_affiche','siret'])
    # Réinitialiser pagination et sélection lorsque le résultat ou les données changent.
    signature=hashlib.sha256(pd.util.hash_pandas_object(filtered[list(DISPLAY)].astype('string'),index=False).values.tobytes()+str(page_size).encode()).hexdigest()[:16]
    if st.session_state.get('_result_signature')!=signature:
        st.session_state['_result_signature']=signature
        st.session_state['page_prospects']=1
    total_pages=max(1,(len(filtered)+page_size-1)//page_size)
    page=int(toolbar[2].number_input('Page',min_value=1,max_value=total_pages,step=1,key='page_prospects'))
    start=(page-1)*page_size
    visible=filtered.iloc[start:start+page_size].reset_index(drop=True)
    st.caption(f'{start+1}–{min(start+page_size,len(filtered))} sur {nombre(len(filtered))} · cochez une ligne pour ouvrir sa fiche')
    event=st.dataframe(visible[list(DISPLAY)].rename(columns=DISPLAY),hide_index=True,width='stretch',
        height=450,on_select='rerun',selection_mode='single-row',key=f'liste_{signature}_{page}',
        column_config={'Entreprise':st.column_config.TextColumn(width='medium'),
            'Angle commercial':st.column_config.TextColumn(width='large'),
            'Score total':st.column_config.NumberColumn(format='%d'),
            'Création':st.column_config.DateColumn(format='DD/MM/YYYY')})
    st.download_button(f'Télécharger les {nombre(len(filtered))} résultats (CSV)',data=exporter_csv(filtered),
        file_name=f'prospects_{evaluated:%Y%m%d}.csv',mime='text/csv',width='content')
    st.caption('L’export contient toute la sélection filtrée, pas seulement la page affichée. Codes postaux : codes possibles de la commune.')
    selected=event.selection.rows
    if selected and 0<=selected[0]<len(visible):fiche(visible.iloc[selected[0]])
    else:st.info('Sélectionnez un établissement dans le tableau pour lire son angle commercial et le détail de son score.')


if __name__=='__main__':
    main()
