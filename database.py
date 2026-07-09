"""
PostgreSQL database layer for Pokemon 5e RPG.
Replaces JSON file storage for users, game_state, and npcs.
Static data (pokemon, moves, routes, mega_stones) stays in JSON files.
"""
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable not set. "
        "Set it to your PostgreSQL connection string before starting the server."
    )

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tables (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            master_id TEXT NOT NULL,
            invite_code TEXT UNIQUE NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            table_id TEXT DEFAULT NULL,
            trainer_data JSONB DEFAULT '{}'
        )
    ''')
    # Add table_id column to existing users table if missing
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS table_id TEXT DEFAULT NULL
    """)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS game_state (
            key TEXT PRIMARY KEY,
            value JSONB DEFAULT '{}'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS npcs (
            id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL DEFAULT 'default',
            data JSONB DEFAULT '{}'
        )
    ''')
    cur.execute("ALTER TABLE npcs ADD COLUMN IF NOT EXISTS table_id TEXT NOT NULL DEFAULT 'default'")
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# TABLES (mesas de RPG)
# ============================================================
def create_table(table_id, name, master_id, invite_code):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO tables (id, name, master_id, invite_code)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    ''', (table_id, name, master_id, invite_code))
    conn.commit()
    cur.close()
    conn.close()

def get_table_by_invite(invite_code):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM tables WHERE invite_code = %s', (invite_code,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_table(table_id):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM tables WHERE id = %s', (table_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_tables_for_master(master_id):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM tables WHERE master_id = %s', (master_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def set_user_table(user_id, table_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE users SET table_id = %s WHERE id = %s', (table_id, user_id))
    conn.commit()
    cur.close()
    conn.close()

def get_users_in_table(table_id):
    """Return all users belonging to a specific table."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM users WHERE table_id = %s', (table_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for row in rows:
        result[row['id']] = {
            'username': row['username'],
            'password_hash': row['password_hash'],
            'role': row['role'],
            'table_id': row['table_id'],
            'trainer_data': row['trainer_data'] or {}
        }
    return result

# ============================================================
# USERS
# ============================================================
def _user_fingerprint(u):
    """Serialização estável de um usuário para detectar mudança no save."""
    return json.dumps([
        u.get('username'), u.get('password_hash'), u.get('role'),
        u.get('table_id'), u.get('trainer_data', {})
    ], sort_keys=True, default=str)


class _UsersSnapshot(dict):
    """dict de usuários que lembra o estado ORIGINAL de cada linha (no load).
    Permite ao save_users gravar SÓ quem mudou — sem isso, save_users regravava
    a tabela inteira a partir de um snapshot possivelmente obsoleto, e sob
    concorrência (gevent) um handler revertia a alteração de OUTRO jogador que
    nem estava na requisição (lost update / duplicação de economia)."""
    __slots__ = ('_orig',)


def get_users():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM users')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = _UsersSnapshot()
    result._orig = {}
    for row in rows:
        u = {
            'username': row['username'],
            'password_hash': row['password_hash'],
            'role': row['role'],
            'table_id': row.get('table_id'),
            'trainer_data': row['trainer_data'] or {}
        }
        result[row['id']] = u
        result._orig[row['id']] = _user_fingerprint(u)
    return result

def save_users(users_dict):
    # Grava só os usuários NOVOS ou ALTERADOS desde o load (compara a
    # impressão digital). Um dict comum (ex.: chamado dos testes) grava todos.
    orig = getattr(users_dict, '_orig', None)
    conn = get_conn()
    cur = conn.cursor()
    for uid, u in users_dict.items():
        if orig is not None and orig.get(uid) == _user_fingerprint(u):
            continue   # inalterado → não regrava (evita clobber cross-player)
        cur.execute('''
            INSERT INTO users (id, username, password_hash, role, table_id, trainer_data)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                password_hash = EXCLUDED.password_hash,
                role = EXCLUDED.role,
                table_id = EXCLUDED.table_id,
                trainer_data = EXCLUDED.trainer_data
        ''', (uid, u['username'], u['password_hash'], u['role'],
              u.get('table_id'), json.dumps(u.get('trainer_data', {}))))
    conn.commit()
    cur.close()
    conn.close()

def delete_user(uid):
    """Remove a user permanently (usado ao rejeitar cadastro de mestre)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE id = %s', (uid,))
    conn.commit()
    cur.close()
    conn.close()

def save_user(uid, user_data):
    """Save a single user efficiently."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (id, username, password_hash, role, table_id, trainer_data)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            username = EXCLUDED.username,
            password_hash = EXCLUDED.password_hash,
            role = EXCLUDED.role,
            table_id = EXCLUDED.table_id,
            trainer_data = EXCLUDED.trainer_data
    ''', (uid, user_data['username'], user_data['password_hash'], user_data['role'],
          user_data.get('table_id'), json.dumps(user_data.get('trainer_data', {}))))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# GAME STATE
# ============================================================
def get_game_state(table_id='default'):
    key = f'main_{table_id}'
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM game_state WHERE key = %s", (key,))
    row = cur.fetchone()
    # Fallback: legacy 'main' key for old data migration
    if not row:
        cur.execute("SELECT * FROM game_state WHERE key = 'main'")
        row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row['value']
    return {'active_encounters': {}, 'quests': [], 'player_xp': {},
            'calendar': {'day': 1, 'month': 1, 'year': 1},
            'calendar_events': [], 'hunts': {}}

def save_game_state(state, table_id='default'):
    key = f'main_{table_id}'
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, json.dumps(state)))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# NPCs
# ============================================================
def get_npcs(table_id='default'):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM npcs WHERE table_id = %s', (table_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [row['data'] for row in rows]

def save_npc(npc, table_id='default'):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO npcs (id, table_id, data) VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, table_id = EXCLUDED.table_id
    ''', (npc['id'], table_id, json.dumps(npc)))
    conn.commit()
    cur.close()
    conn.close()

def delete_npc(npc_id, table_id='default'):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM npcs WHERE id = %s AND table_id = %s', (npc_id, table_id))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# SITE SETTINGS (theme, background, etc.)
# ============================================================
DEFAULT_SITE_SETTINGS = {
    'theme': 'gba',
    'background': 'gba-grass',
    'custom_banner': '',
    'mesa_name': 'Pokémon 5e RPG'
}

def get_site_settings(table_id='default'):
    key = f'site_settings_{table_id}'
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM game_state WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT * FROM game_state WHERE key = 'site_settings'")
        row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row['value']:
        merged = dict(DEFAULT_SITE_SETTINGS)
        merged.update(row['value'])
        return merged
    return dict(DEFAULT_SITE_SETTINGS)

def save_site_settings(settings, table_id='default'):
    key = f'site_settings_{table_id}'
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, json.dumps(settings)))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# GYMS — per table
# ============================================================
def get_gyms(table_id='default'):
    key = f'gyms_{table_id}'
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT value FROM game_state WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT value FROM game_state WHERE key = 'gyms'")
        row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row['value']:
        return row['value'] if isinstance(row['value'], list) else []
    return []

def save_gyms(gyms_list, table_id='default'):
    key = f'gyms_{table_id}'
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, json.dumps(gyms_list)))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# LEAGUE — per table
# ============================================================
def get_league(table_id='default'):
    key = f'league_{table_id}'
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT value FROM game_state WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT value FROM game_state WHERE key = 'league'")
        row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row['value']:
        return row['value']
    return {'slots': [], 'active_runs': {}}

def save_league(league, table_id='default'):
    key = f'league_{table_id}'
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, json.dumps(league)))
    conn.commit()
    cur.close()
    conn.close()
