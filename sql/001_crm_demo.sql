-- Initialisation additive uniquement. Aucun accès aux tables de scoring.
create schema if not exists crm_demo;
create table if not exists crm_demo.suivi (
    commercial_id text not null check (commercial_id = 'camille-demo'),
    siren varchar(9) not null check (siren ~ '^[0-9]{9}$'),
    statut text not null default 'À contacter'
        check (statut in ('À contacter','Prise de contact','Rendez-vous','Refus','Négociation','Contrat en cours','Renouvellement')),
    date_dernier_contact date,
    date_relance date,
    date_fin_contrat date,
    contact_nom varchar(120) not null default '',
    contact_prenom varchar(120) not null default '',
    contact_telephone varchar(40) not null default '',
    contact_email varchar(254) not null default '',
    notes text not null default '' check (length(notes)<=5000),
    version integer not null default 1 check (version>=1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(commercial_id,siren),
    check (statut not in ('Contrat en cours','Renouvellement') or date_fin_contrat is not null)
);
