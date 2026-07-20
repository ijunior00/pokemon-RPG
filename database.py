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

_conn_count = 0   # diagnóstico: quantas conexões o processo abriu (DB_STATS=1)


def get_conn():
    global _conn_count
    _conn_count += 1
    return psycopg2.connect(DATABASE_URL)


if os.environ.get('DB_STATS'):
    import atexit

    @atexit.register
    def _print_db_stats():
        print(f'[db] conexões abertas pelo processo: {_conn_count}')


# ============================================================
# CACHE DE PROCESSO (write-through) — economia de data transfer
# ============================================================
# O deploy roda UM worker gunicorn (-w 1, gevent): este processo é o único
# dono do banco. Então dá para servir TODAS as leituras da memória e ir ao
# Postgres só para escrever — foi o egress de ler users/game_state inteiros
# (JSONB grandes) a cada evento de socket que estourou a cota de data
# transfer do Neon e derrubou a mesa.
#
# Regras:
# - O cache guarda STRINGS JSON e o get faz json.loads: o chamador recebe
#   exatamente o que um roundtrip pelo Postgres devolveria (chaves de dict
#   viram str etc.) — zero mudança de semântica.
# - Write-through: toda função de escrita atualiza o cache APÓS o commit.
# - Só entra no cache o que veio do banco ou acabou de ser gravado
#   (defaults de "linha inexistente" não são cacheados).
# - A tabela `tables` NÃO é cacheada (app.py tem UPDATEs crus nela).
# - Rodando com mais de um worker? Desligue com DB_CACHE=off.
_CACHE_ON = os.environ.get('DB_CACHE', 'on').strip().lower() not in ('off', '0', 'false', 'no')
_users_cache = None    # {uid: {'json': str, 'fp': str}}  (None = ainda não carregado)
_state_cache = {}      # key da tabela game_state -> string JSON do valor
_npcs_cache = {}       # table_id -> {npc_id: string JSON}


def cache_reset():
    """Zera o cache de processo (testes / troca de banco em runtime)."""
    global _users_cache
    _users_cache = None
    _state_cache.clear()
    _npcs_cache.clear()

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
    if _CACHE_ON and _users_cache is not None and user_id in _users_cache:
        u = json.loads(_users_cache[user_id]['json'])
        u['table_id'] = table_id
        _users_cache[user_id] = {'json': json.dumps(u), 'fp': _user_fingerprint(u)}

def get_users_in_table(table_id):
    """Return all users belonging to a specific table."""
    if _CACHE_ON and _users_cache is not None:
        result = {}
        for uid, ent in _users_cache.items():
            u = json.loads(ent['json'])
            if u.get('table_id') == table_id:
                result[uid] = u
        return result
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


def _user_row(u):
    """Forma CANÔNICA de um usuário — só o que o banco persiste (5 colunas).
    O cache guarda isso serializado: chaves extras somem e o trainer_data
    normaliza igualzinho a um roundtrip pelo Postgres."""
    return {'username': u.get('username'), 'password_hash': u.get('password_hash'),
            'role': u.get('role'), 'table_id': u.get('table_id'),
            'trainer_data': u.get('trainer_data', {}) or {}}


class _UsersSnapshot(dict):
    """dict de usuários que lembra o estado ORIGINAL de cada linha (no load).
    Permite ao save_users gravar SÓ quem mudou — sem isso, save_users regravava
    a tabela inteira a partir de um snapshot possivelmente obsoleto, e sob
    concorrência (gevent) um handler revertia a alteração de OUTRO jogador que
    nem estava na requisição (lost update / duplicação de economia)."""
    __slots__ = ('_orig',)


def get_users():
    global _users_cache
    if _CACHE_ON and _users_cache is not None:
        result = _UsersSnapshot()
        result._orig = {}
        for uid, ent in _users_cache.items():
            result[uid] = json.loads(ent['json'])
            result._orig[uid] = ent['fp']
        return result
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM users')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = _UsersSnapshot()
    result._orig = {}
    cache = {}
    for row in rows:
        u = {
            'username': row['username'],
            'password_hash': row['password_hash'],
            'role': row['role'],
            'table_id': row.get('table_id'),
            'trainer_data': row['trainer_data'] or {}
        }
        result[row['id']] = u
        fp = _user_fingerprint(u)
        result._orig[row['id']] = fp
        cache[row['id']] = {'json': json.dumps(u), 'fp': fp}
    if _CACHE_ON:
        _users_cache = cache
    return result

def save_users(users_dict):
    # Grava só os usuários NOVOS ou ALTERADOS desde o load (compara a
    # impressão digital). Um dict comum (ex.: chamado dos testes) grava todos.
    orig = getattr(users_dict, '_orig', None)
    conn = get_conn()
    cur = conn.cursor()
    written = []
    for uid, u in users_dict.items():
        fp = _user_fingerprint(u)
        if orig is not None and orig.get(uid) == fp:
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
        written.append((uid, u, fp))
    conn.commit()
    cur.close()
    conn.close()
    if _CACHE_ON and _users_cache is not None:
        for uid, u, fp in written:
            _users_cache[uid] = {'json': json.dumps(_user_row(u)), 'fp': fp}

def delete_user(uid):
    """Remove a user permanently (usado ao rejeitar cadastro de mestre)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE id = %s', (uid,))
    conn.commit()
    cur.close()
    conn.close()
    if _CACHE_ON and _users_cache is not None:
        _users_cache.pop(uid, None)

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
    if _CACHE_ON and _users_cache is not None:
        _users_cache[uid] = {'json': json.dumps(_user_row(user_data)),
                             'fp': _user_fingerprint(user_data)}

# ============================================================
# GAME STATE
# ============================================================
def _state_row_get(key, legacy_key=None):
    """Lê uma linha de game_state com cache (fallback opcional p/ chave
    legada). Devolve o valor parseado ou None se não existir."""
    if _CACHE_ON and key in _state_cache:
        return json.loads(_state_cache[key])
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM game_state WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row and legacy_key:
        cur.execute("SELECT * FROM game_state WHERE key = %s", (legacy_key,))
        row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        if _CACHE_ON:
            _state_cache[key] = json.dumps(row['value'])
        return row['value']
    return None


def _state_row_save(key, value):
    """Grava uma linha de game_state e atualiza o cache (write-through)."""
    payload = json.dumps(value)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, payload))
    conn.commit()
    cur.close()
    conn.close()
    if _CACHE_ON:
        _state_cache[key] = payload


def get_game_state(table_id='default'):
    value = _state_row_get(f'main_{table_id}', legacy_key='main')
    if value is not None:
        return value
    return {'active_encounters': {}, 'quests': [], 'player_xp': {},
            'calendar': {'day': 1, 'month': 1, 'year': 1},
            'calendar_events': [], 'hunts': {}}

def save_game_state(state, table_id='default'):
    _state_row_save(f'main_{table_id}', state)

# ============================================================
# NPCs
# ============================================================
def get_npcs(table_id='default'):
    if _CACHE_ON and table_id in _npcs_cache:
        return [json.loads(s) for s in _npcs_cache[table_id].values()]
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM npcs WHERE table_id = %s', (table_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if _CACHE_ON:
        _npcs_cache[table_id] = {row['id']: json.dumps(row['data']) for row in rows}
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
    if _CACHE_ON:
        # o upsert pode MOVER o NPC de mesa (table_id atualiza) — tira das outras
        for t, d in _npcs_cache.items():
            if t != table_id:
                d.pop(npc['id'], None)
        if table_id in _npcs_cache:
            _npcs_cache[table_id][npc['id']] = json.dumps(npc)

def delete_npc(npc_id, table_id='default'):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM npcs WHERE id = %s AND table_id = %s', (npc_id, table_id))
    conn.commit()
    cur.close()
    conn.close()
    if _CACHE_ON and table_id in _npcs_cache:
        _npcs_cache[table_id].pop(npc_id, None)

# ============================================================
# SITE SETTINGS (theme, background, etc.)
# ============================================================
DEFAULT_SITE_SETTINGS = {
    # "valorant" = tema Arena (moldura cinematográfica moderna + sprites pixel).
    # Mesas que já salvaram um tema na aba Visual mantêm a escolha delas.
    'theme': 'valorant',
    'background': 'none',
    'custom_banner': '',
    'mesa_name': 'Pokémon 5e RPG'
}

def get_site_settings(table_id='default'):
    value = _state_row_get(f'site_settings_{table_id}', legacy_key='site_settings')
    if value:
        merged = dict(DEFAULT_SITE_SETTINGS)
        merged.update(value)
        # Compat (code-review C13): mesa que salvou o tema GBA mas nunca
        # salvou fundo mantém a Grama GBA (o default novo de fundo é 'none',
        # pensado para o tema Arena — não pode roubar a grama do GBA).
        if merged.get('theme') == 'gba' and not value.get('background'):
            merged['background'] = 'gba-grass'
        return merged
    return dict(DEFAULT_SITE_SETTINGS)

def save_site_settings(settings, table_id='default'):
    _state_row_save(f'site_settings_{table_id}', settings)

# ============================================================
# GYMS — per table
# ============================================================
def get_gyms(table_id='default'):
    value = _state_row_get(f'gyms_{table_id}', legacy_key='gyms')
    if value:
        return value if isinstance(value, list) else []
    return []

def save_gyms(gyms_list, table_id='default'):
    _state_row_save(f'gyms_{table_id}', gyms_list)

# ============================================================
# LEAGUE — per table
# ============================================================
def get_league(table_id='default'):
    value = _state_row_get(f'league_{table_id}', legacy_key='league')
    if value:
        return value
    return {'slots': [], 'active_runs': {}}

def save_league(league, table_id='default'):
    _state_row_save(f'league_{table_id}', league)
