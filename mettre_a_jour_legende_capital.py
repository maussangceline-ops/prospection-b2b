"""Ajoute la règle capital à la légende existante, en préservant le reste de l'app."""
from pathlib import Path
p=Path(__file__).resolve().parent/'dashboard/app.py'
s=p.read_text(encoding='utf-8')
marker='**Capital social — publications BODACC :**'
if marker in s:
    print('Légende capital déjà présente.')
else:
    anchor='**Priorité :**'
    if s.count(anchor)!=1:
        raise SystemExit('Repère de légende absent ou ambigu : aucun fichier modifié. Ajouter manuellement le texte indiqué dans le guide.')
    backup=p.with_name('app.py.avant_capital.bak')
    if backup.exists():raise SystemExit('Sauvegarde déjà présente : aucun fichier modifié.')
    text=marker+' sur les 12 derniers mois, +50 pour la première hausse, +25 par hausse suivante, −25 par baisse. La date retenue est celle de publication, pas la date juridique de l’opération.\n\n'
    backup.write_text(s,encoding='utf-8')
    p.write_text(s.replace(anchor,text+anchor),encoding='utf-8')
    print('Légende mise à jour. Sauvegarde locale :',backup.name)
