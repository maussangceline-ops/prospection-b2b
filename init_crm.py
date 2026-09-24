"""Créer les tables CRM démo dans Neon sans modifier les tables existantes."""
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg
ROOT=Path(__file__).resolve().parent

def main():
    load_dotenv(ROOT/'.env',override=False)
    dsn=os.getenv('CRM_DATABASE_URL')
    if not dsn:raise SystemExit('CRM_DATABASE_URL absente du .env local.')
    try:
        with psycopg.connect(dsn,connect_timeout=10) as connection:
            connection.execute((ROOT/'sql/001_crm_demo.sql').read_text(encoding='utf-8'))
    except psycopg.Error:
        raise SystemExit('Initialisation impossible. Vérifiez la connexion Neon et les droits CREATE SCHEMA / CREATE TABLE. Aucun secret affiché.') from None
    print('CRM de démonstration initialisé. Le scoring et les données S3 sont inchangés.')
if __name__=='__main__':main()
