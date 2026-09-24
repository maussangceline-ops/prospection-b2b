"""Formulaire CRM : profil partagé de démonstration, pas une authentification."""
import pandas as pd
import streamlit as st
from crm_store import (USER_NAME,STATUSES,FIELDS,read_record,list_records,save_record,
                       renewal_alert,today_paris,ConflictError)


def profile(dsn):
    with st.sidebar:
        st.divider()
        st.subheader('Espace commercial')
        st.caption('DÉMONSTRATION · données fictives uniquement')
        if not dsn:
            st.caption('Le suivi commercial n’est pas encore configuré.')
            return False
        return st.toggle('Utiliser le profil Camille',key='crm_demo_active',
            help='Profil fictif partagé entre les visiteurs, sans authentification. Ne pas saisir de coordonnées réelles.')


def editor(siren,dsn):
    st.subheader('Suivi commercial')
    st.caption(USER_NAME+' · profil partagé, non authentifié. Contacts et notes fictifs uniquement.')
    record_key='crm_record_'+siren
    if record_key not in st.session_state:
        try:st.session_state[record_key]=read_record(dsn,siren)
        except Exception as erreur:
            st.error(
                "Le suivi commercial est indisponible. "
                "La fiche entreprise reste consultable."
            )
            st.caption(
                f"Diagnostic : {type(erreur).__name__} — "
                f"code SQL : {getattr(erreur, 'sqlstate', None) or 'non disponible'}"
            )
            return
    record=st.session_state[record_key]
    notice_key='crm_notice_'+siren
    if st.session_state.pop(notice_key,False):st.success('Suivi enregistré dans Neon.')
    epoch=st.session_state.get('crm_epoch_'+siren,0)
    prefix=f'crm_{siren}_{epoch}_'
    if st.button('Recharger le suivi enregistré',key='reload_'+siren,help='Remplace les champs du formulaire par la dernière sauvegarde.'):
        st.session_state.pop(record_key,None)
        st.session_state['crm_epoch_'+siren]=epoch+1
        st.rerun()
    alert=renewal_alert(record['statut'],record.get('date_fin_contrat'))
    if alert:st.warning(alert+' · fin de contrat : '+record['date_fin_contrat'].strftime('%d/%m/%Y'))
    if record.get('date_relance') and record['date_relance']<=today_paris() and record['statut']!='Refus':
        st.info('Relance à effectuer · '+record['date_relance'].strftime('%d/%m/%Y'))
    with st.form(prefix+'form'):
        status=st.selectbox('Statut commercial',STATUSES,index=STATUSES.index(record['statut']),key=prefix+'statut')
        st.caption('Une date de fin est obligatoire pour Contrat en cours et Renouvellement.')
        c1,c2,c3=st.columns(3)
        last=c1.date_input('Dernier contact',value=record.get('date_dernier_contact'),format='DD/MM/YYYY',key=prefix+'last')
        follow=c2.date_input('Prochaine relance',value=record.get('date_relance'),format='DD/MM/YYYY',key=prefix+'follow')
        end=c3.date_input('Fin de contrat',value=record.get('date_fin_contrat'),format='DD/MM/YYYY',key=prefix+'end')
        st.markdown('**Personne de contact — fictive pour cette démonstration**')
        c1,c2=st.columns(2)
        name=c1.text_input('Nom',value=record['contact_nom'],max_chars=120,key=prefix+'name')
        first=c2.text_input('Prénom',value=record['contact_prenom'],max_chars=120,key=prefix+'first')
        c1,c2=st.columns(2)
        phone=c1.text_input('Téléphone',value=record['contact_telephone'],max_chars=40,key=prefix+'phone')
        email=c2.text_input('Email',value=record['contact_email'],max_chars=254,placeholder='camille@example.com',key=prefix+'email')
        notes=st.text_area('Notes commerciales',value=record['notes'],max_chars=5000,height=140,key=prefix+'notes')
        submitted=st.form_submit_button('Enregistrer le suivi',type='primary')
    if submitted:
        data=dict(zip(FIELDS,[status,last,follow,end,name,first,phone,email,notes]))
        try:
            saved=save_record(dsn,siren,data,record['version'])
        except (ValueError,ConflictError) as error:
            st.error(str(error));return
        except Exception:
            st.error('Enregistrement non confirmé. Les champs sont conservés. Rechargez le suivi pour vérifier la dernière sauvegarde avant de réessayer.');return
        st.session_state[record_key]=saved
        st.session_state['crm_epoch_'+siren]=epoch+1
        st.session_state[notice_key]=True
        st.rerun()
    st.caption('Les alertes sont calculées à l’ouverture de l’application, en heure de Paris. Elles ne changent pas le statut et n’envoient pas d’email.')


def calendar_date(value):
    return None if pd.isna(value) else pd.Timestamp(value).date()


def suivi(df,dsn,render_fiche):
    st.subheader('Mes dossiers commerciaux')
    st.caption('Profil partagé Camille · seuls les établissements actuellement admissibles et correspondant aux filtres sont présentés.')
    try:records=list_records(dsn)
    except Exception:
        st.error('Impossible de charger le suivi commercial. Réessayez après avoir vérifié la connexion Neon.');return
    if not records:
        st.info('Aucun dossier enregistré. Ouvrez une fiche dans Prospects et enregistrez votre premier suivi.');return
    records=pd.DataFrame(records)
    # Le rapprochement est par SIREN, sans réintroduire les entreprises exclues.
    companies=df.sort_values('siret').drop_duplicates('siren')
    merged=companies.merge(records,on='siren',how='inner',validate='one_to_one')
    if merged.empty:
        st.info('Aucun dossier enregistré ne correspond à votre sélection actuelle.');return
    merged['alerte_contrat']=merged.apply(lambda r:renewal_alert(r['statut'],calendar_date(r['date_fin_contrat'])),axis=1)
    merged['relance_due']=merged.apply(lambda r:bool(calendar_date(r['date_relance']) and calendar_date(r['date_relance'])<=today_paris() and r['statut']!='Refus'),axis=1)
    a,b,c=st.columns(3)
    a.metric('Dossiers dans la sélection',len(merged))
    b.metric('Renouvellements à préparer',int(merged['alerte_contrat'].eq('Renouvellement à préparer').sum()))
    c.metric('Relances à effectuer',int(merged['relance_due'].sum()))
    statuses=st.multiselect('Statuts commerciaux',STATUSES,key='crm_status_filter')
    alert=st.selectbox('Échéances',['Toutes','Relances à effectuer','Renouvellements à préparer','Contrats arrivés à échéance'],key='crm_alert_filter')
    if statuses:merged=merged[merged['statut'].isin(statuses)]
    if alert=='Relances à effectuer':merged=merged[merged['relance_due']]
    elif alert=='Renouvellements à préparer':merged=merged[merged['alerte_contrat'].eq('Renouvellement à préparer')]
    elif alert=='Contrats arrivés à échéance':merged=merged[merged['alerte_contrat'].eq('Contrat arrivé à échéance')]
    if merged.empty:st.info('Aucun dossier pour ces critères de suivi.');return
    st.dataframe(merged[['nom_affiche','statut','date_dernier_contact','date_relance','date_fin_contrat','alerte_contrat']].rename(columns={
        'nom_affiche':'Entreprise','statut':'Statut commercial','date_dernier_contact':'Dernier contact',
        'date_relance':'Relance','date_fin_contrat':'Fin du contrat','alerte_contrat':'Alerte'}),hide_index=True,width='stretch')
    options=merged['siren'].tolist()
    if st.session_state.get('crm_open_siren') not in options:st.session_state['crm_open_siren']=options[0]
    labels=dict(zip(merged['siren'],merged['nom_affiche']))
    selected=st.selectbox('Ouvrir un dossier',options,format_func=lambda s:f'{labels[s]} · {s}',key='crm_open_siren')
    render_fiche(merged.loc[merged['siren'].eq(selected)].iloc[0])
    editor(selected,dsn)
