"""
PostgreSQL database layer for Pokemon 5e RPG.
Replaces JSON file storage for users, game_state, and npcs.
Static data (pokemon, moves, routes, mega_stones) stays in JSON files.
"""
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_SNzbFnCQ8v1L@ep-sweet-hall-afeg85fw.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require')

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            trainer_data JSONB DEFAULT '{}'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS game_state (
            key TEXT PRIMARY KEY,
            value JSONB DEFAULT '{}'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS npcs (
            id TEXT PRIMARY KEY,
            data JSONB DEFAULT '{}'
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# USERS
# ============================================================
def get_users():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM users')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for row in rows:
        result[row['id']] = {
            'username': row['username'],
            'password_hash': row['password_hash'],
            'role': row['role'],
            'trainer_data': row['trainer_data'] or {}
        }
    return result

def save_users(users_dict):
    conn = get_conn()
    cur = conn.cursor()
    for uid, u in users_dict.items():
        cur.execute('''
            INSERT INTO users (id, username, password_hash, role, trainer_data)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                password_hash = EXCLUDED.password_hash,
                role = EXCLUDED.role,
                trainer_data = EXCLUDED.trainer_data
        ''', (uid, u['username'], u['password_hash'], u['role'], json.dumps(u.get('trainer_data', {}))))
    conn.commit()
    cur.close()
    conn.close()

def save_user(uid, user_data):
    """Save a single user efficiently."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (id, username, password_hash, role, trainer_data)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            username = EXCLUDED.username,
            password_hash = EXCLUDED.password_hash,
            role = EXCLUDED.role,
            trainer_data = EXCLUDED.trainer_data
    ''', (uid, user_data['username'], user_data['password_hash'], user_data['role'], json.dumps(user_data.get('trainer_data', {}))))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# GAME STATE
# ============================================================
def get_game_state():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM game_state WHERE key = 'main'")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row['value']
    return {'active_encounters': {}, 'quests': [], 'player_xp': {}}

def save_game_state(state):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO game_state (key, value) VALUES ('main', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    ''', (json.dumps(state),))
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# NPCs
# ============================================================
def get_npcs():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM npcs')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [row['data'] for row in rows]

def save_npc(npc):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO npcs (id, data) VALUES (%s, %s)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
    ''', (npc['id'], json.dumps(npc)))
    conn.commit()
    cur.close()
    conn.close()

def delete_npc(npc_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM npcs WHERE id = %s', (npc_id,))
    conn.commit()
    cur.close()
    conn.close()
