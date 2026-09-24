"""Persistance du CRM de démonstration, séparée du scoring et des collectes."""
import calendar
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

USER_ID = 'camille-demo'
USER_NAME = 'Camille — Commercial (démo)'
STATUSES = ['À contacter','Prise de contact','Rendez-vous','Refus','Négociation','Contrat en cours','Renouvellement']
FIELDS = ['statut','date_dernier_contact','date_relance','date_fin_contrat',
          'contact_nom','contact_prenom','contact_telephone','contact_email','notes']

class ConflictError(Exception): pass


def today_paris():
    return datetime.now(ZoneInfo('Europe/Paris')).date()


def renewal_alert(status, end, today=None):
    if status not in ('Contrat en cours','Renouvellement') or not end:
        return ''
    today = today or today_paris()
    if end < today: return 'Contrat arrivé à échéance'
    year, month = (end.year-1,12) if end.month==1 else (end.year,end.month-1)
    threshold = date(year,month,min(end.day,calendar.monthrange(year,month)[1]))
    if today >= threshold: return 'Renouvellement à préparer'
    return ''


def empty_record(siren):
    return dict(siren=siren,version=0,statut='À contacter',date_dernier_contact=None,
                date_relance=None,date_fin_contrat=None,contact_nom='',contact_prenom='',
                contact_telephone='',contact_email='',notes='')


def validate(siren, values, today=None):
    today = today or today_paris()
    if not re.fullmatch(r'\d{9}',str(siren)): raise ValueError('SIREN invalide.')
    cleaned = {k:values.get(k) for k in FIELDS}
    if cleaned['statut'] not in STATUSES: raise ValueError('Statut commercial invalide.')
    for field in ['date_dernier_contact','date_relance','date_fin_contrat']:
        value=cleaned[field]
        if value is not None and (not isinstance(value,date) or isinstance(value,datetime)):
            raise ValueError('Date invalide.')
    if cleaned['statut'] in ('Contrat en cours','Renouvellement') and cleaned['date_fin_contrat'] is None:
        raise ValueError('La date de fin de contrat est obligatoire pour ce statut.')
    if cleaned['date_dernier_contact'] and cleaned['date_dernier_contact'] > today:
        raise ValueError('La date du dernier contact ne peut pas être future. Utilisez la prochaine relance.')
    limits={'contact_nom':120,'contact_prenom':120,'contact_telephone':40,'contact_email':254,'notes':5000}
    for field,limit in limits.items():
        cleaned[field]=str(cleaned[field] or '').strip()
        if len(cleaned[field])>limit:raise ValueError(f'Champ trop long : {field} (maximum {limit} caractères).')
    email=cleaned['contact_email']
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Format de l’email invalide.')
    phone=cleaned['contact_telephone']
    if phone and (not re.fullmatch(r'\+?[0-9 ().\-]+',phone) or not 7<=len(re.sub(r'\D','',phone))<=15):
        raise ValueError('Téléphone invalide : utilisez des chiffres, espaces et éventuellement un préfixe +.')
    return cleaned


def connect(dsn):
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        dsn,
        connect_timeout=30,
        row_factory=dict_row,
        application_name="siren-crm-demo",
    )

def read_record(dsn,siren):
    with connect(dsn) as connection:
        row=connection.execute('select * from crm_demo.suivi where commercial_id=%s and siren=%s',(USER_ID,siren)).fetchone()
    return row or empty_record(siren)


def list_records(dsn):
    with connect(dsn) as connection:
        return connection.execute('''select siren,statut,date_dernier_contact,date_relance,date_fin_contrat,
            updated_at,version from crm_demo.suivi where commercial_id=%s order by updated_at desc''',(USER_ID,)).fetchall()


def save_record(dsn,siren,values,expected_version):
    cleaned=validate(siren,values)
    if not isinstance(expected_version,int) or expected_version<0:raise ValueError('Version invalide.')
    params=[cleaned[k] for k in FIELDS]
    with connect(dsn) as connection:
        if expected_version==0:
            row=connection.execute('''insert into crm_demo.suivi
                (commercial_id,siren,statut,date_dernier_contact,date_relance,date_fin_contrat,
                 contact_nom,contact_prenom,contact_telephone,contact_email,notes)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (commercial_id,siren) do nothing returning *''',[USER_ID,siren]+params).fetchone()
        else:
            row=connection.execute('''update crm_demo.suivi set statut=%s,date_dernier_contact=%s,
                date_relance=%s,date_fin_contrat=%s,contact_nom=%s,contact_prenom=%s,
                contact_telephone=%s,contact_email=%s,notes=%s,version=version+1,updated_at=now()
                where commercial_id=%s and siren=%s and version=%s returning *''',params+[USER_ID,siren,expected_version]).fetchone()
        if not row:raise ConflictError('Le dossier a été modifié dans une autre session. Rechargez-le avant de réessayer.')
    return row
