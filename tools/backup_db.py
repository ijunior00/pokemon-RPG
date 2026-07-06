"""
Backup completo do banco (todas as mesas) em UM comando — rode ANTES de
mesclar/deployar a migração v2 de stats.

    DATABASE_URL=postgresql://... python3 tools/backup_db.py

Gera backups/backup_YYYYMMDD_HHMMSS.json com o conteúdo integral das
tabelas (tables, users, game_state, npcs). Restauração:

    DATABASE_URL=postgresql://... python3 tools/backup_db.py --restore backups/backup_....json

A restauração sobrescreve as linhas pelo ID (upsert) — não apaga linhas
criadas depois do backup.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print('ERRO: defina DATABASE_URL apontando para o banco da mesa.')
    sys.exit(1)

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backups')

TABLES = {
    'tables': ('id', 'name', 'master_id', 'invite_code'),
    'users': ('id', 'username', 'password_hash', 'role', 'table_id', 'trainer_data'),
    'game_state': ('key', 'value'),
    'npcs': ('id', 'table_id', 'data'),
}
PKS = {'tables': 'id', 'users': 'id', 'game_state': 'key', 'npcs': 'id'}


def backup():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    out = {'created_at': datetime.utcnow().isoformat() + 'Z', 'tables': {}}
    for table, cols in TABLES.items():
        cur.execute(f'SELECT {", ".join(cols)} FROM {table}')
        out['tables'][table] = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f'backup_{datetime.now():%Y%m%d_%H%M%S}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    size = os.path.getsize(path)
    print(f'✅ Backup salvo em {path} ({size/1024:.1f} KB)')
    for table, rows in out['tables'].items():
        print(f'   {table}: {len(rows)} linhas')
    return path


def restore(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    for table, cols in TABLES.items():
        rows = data.get('tables', {}).get(table, [])
        pk = PKS[table]
        for row in rows:
            values = []
            for c in cols:
                v = row.get(c)
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                values.append(v)
            updates = ', '.join(f'{c} = EXCLUDED.{c}' for c in cols if c != pk)
            cur.execute(
                f'INSERT INTO {table} ({", ".join(cols)}) '
                f'VALUES ({", ".join(["%s"] * len(cols))}) '
                f'ON CONFLICT ({pk}) DO UPDATE SET {updates}',
                values)
        print(f'   {table}: {len(rows)} linhas restauradas')
    conn.commit()
    cur.close()
    conn.close()
    print('✅ Restauração concluída.')


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--restore':
        restore(sys.argv[2])
    else:
        backup()
