"""
Remove a entrada de HOJE do assertHistory.
Jogos que terminam hoje so devem aparecer no historico apos o D+1
(quando todos os jogos do dia ja foram concluidos).

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python delete_today_from_history.py
"""
import json, os, sys
from datetime import date as dt_date
sys.stdout.reconfigure(encoding='utf-8')

def main():
    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT nao definida.', flush=True)
        sys.exit(1)

    import firebase_admin
    from firebase_admin import credentials, firestore as fs
    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = fs.client()

    today = dt_date.today().isoformat()
    print(f'Deletando assertHistory/{today}...', flush=True)

    ref = db.collection('assertHistory').document(today)
    if ref.get().exists:
        ref.delete()
        print(f'  OK — entrada removida.', flush=True)
    else:
        print(f'  Entrada nao existe.', flush=True)

if __name__ == '__main__':
    main()
