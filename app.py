"""
Pokemon 5e RPG - Aplicação Web Principal
Sistema de gerenciamento de mesa para Pokemon 5e com tempo real.
"""
import os
import json
import random
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import pvp_battle as pvp
import status_effects as effects
import pokemon_scaling as scaling
import abilities as ab

# ============================================================
# APP SETUP
# ============================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pokemon5e-rpg-secret-key-2024-galar')
app.config['REMEMBER_COOKIE_DURATION'] = 2592000  # 30 dias
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize database
db.init_db()

# ============================================================
# DATA LOADING (static data from JSON files)
# ============================================================
DATA_DIR = os.path.join(os.path.dirname(__file__), 'server', 'data')
POKEMON_FILE = os.path.join(DATA_DIR, 'pokemon.json')
ROUTES_FILE = os.path.join(DATA_DIR, 'routes.json')

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Load Pokemon database
POKEMON_DB = load_json(POKEMON_FILE)
POKEMON_BY_NUMBER = {p['number']: p for p in POKEMON_DB}
POKEMON_BY_NAME = {p['name'].lower(): p for p in POKEMON_DB}
POKEMON_BY_TYPE = {}
for p in POKEMON_DB:
    for t in p.get('types', []):
        POKEMON_BY_TYPE.setdefault(t.lower(), []).append(p)

# Load routes
ROUTES_DATA = load_json(ROUTES_FILE)

# Load moves database
MOVES_FILE = os.path.join(DATA_DIR, 'moves.json')
MOVES_DB = load_json(MOVES_FILE)
MOVES_BY_NAME = {k.lower(): v for k, v in MOVES_DB.items()}

# Load mega stones database
MEGA_FILE = os.path.join(DATA_DIR, 'mega_stones.json')
MEGA_DB = load_json(MEGA_FILE)
MEGA_BY_POKEMON = {}
for stone_name, stone_data in MEGA_DB.items():
    pokemon_name = stone_data.get('pokemon', '')
    MEGA_BY_POKEMON.setdefault(pokemon_name.lower(), []).append(stone_data)

# ============================================================
# USER MODEL
# ============================================================
class User(UserMixin):
    def __init__(self, id, username, password_hash, role='player', trainer_data=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role  # 'master' or 'player'
        self.trainer_data = trainer_data or {}

# Users/game state now handled by database.py module
import database as _db_raw

def _tid():
    """Return table_id for current user (request context required)."""
    try:
        if current_user.is_authenticated:
            users = _db_raw.get_users()
            u = users.get(current_user.id, {})
            return u.get('table_id') or 'default'
    except Exception:
        pass
    return 'default'

class _TableScopedDB:
    """Proxy that injects current table_id into every db call."""
    def get_game_state(self): return _db_raw.get_game_state(_tid())
    def save_game_state(self, s): return _db_raw.save_game_state(s, _tid())
    def get_site_settings(self): return _db_raw.get_site_settings(_tid())
    def save_site_settings(self, s): return _db_raw.save_site_settings(s, _tid())
    def get_gyms(self): return _db_raw.get_gyms(_tid())
    def save_gyms(self, g): return _db_raw.save_gyms(g, _tid())
    def get_league(self): return _db_raw.get_league(_tid())
    def save_league(self, l): return _db_raw.save_league(l, _tid())
    def get_npcs(self): return _db_raw.get_npcs(_tid())
    def save_npc(self, n): return _db_raw.save_npc(n, _tid())
    def delete_npc(self, nid): return _db_raw.delete_npc(nid, _tid())
    def get_users(self): return _db_raw.get_users()
    def save_users(self, u): return _db_raw.save_users(u)
    def save_user(self, uid, u): return _db_raw.save_user(uid, u)
    def get_users_in_table(self): return _db_raw.get_users_in_table(_tid())
    def __getattr__(self, name): return getattr(_db_raw, name)

db = _TableScopedDB()
get_users = _db_raw.get_users
save_users = _db_raw.save_users

def get_game_state():
    return _db_raw.get_game_state(_tid())

def save_game_state(state):
    _db_raw.save_game_state(state, _tid())

@login_manager.user_loader
def load_user(user_id):
    users = get_users()
    if user_id in users:
        u = users[user_id]
        return User(user_id, u['username'], u['password_hash'], u['role'], u.get('trainer_data'))
    return None

# ============================================================
# CONTEXT PROCESSOR - inject site settings into all templates
# ============================================================
@app.context_processor
def inject_site_settings():
    return {'site_settings': db.get_site_settings()}

# ============================================================
# ROUTES (AUTH)
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'master':
            return redirect(url_for('master_dashboard'))
        return redirect(url_for('player_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        users = get_users()
        for uid, u in users.items():
            if u['username'].lower() == username.lower():
                if check_password_hash(u['password_hash'], password):
                    user = User(uid, u['username'], u['password_hash'], u['role'], u.get('trainer_data'))
                    remember = request.form.get('remember') == '1'
                    login_user(user, remember=remember)
                    return redirect(url_for('index'))
        flash('Usuário ou senha incorretos', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'player')
        
        if not username or not password:
            flash('Preencha todos os campos', 'error')
            return render_template('register.html')
        
        users = get_users()
        # Check if username exists
        for u in users.values():
            if u['username'].lower() == username.lower():
                flash('Usuário já existe', 'error')
                return render_template('register.html')
        
        # Players need an invite code to join a table
        invite_code = request.form.get('invite_code', '').strip()
        table_id = None

        if role == 'player':
            if not invite_code:
                flash('Jogadores precisam de um código de convite para entrar em uma mesa.', 'error')
                return render_template('register.html')
            table = _db_raw.get_table_by_invite(invite_code.upper())
            if not table:
                flash('Código de convite inválido.', 'error')
                return render_template('register.html')
            table_id = table['id']

        uid = secrets.token_hex(8)
        users[uid] = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
            'table_id': table_id,
            'trainer_data': {
                'name': username,
                'level': 1,
                'xp': 0,
                'xp_to_next': 100,
                'team': [],
                'bag': [],
                'badges': [],
                'visited_routes': [],
                'notes': ''
            }
        }
        save_users(users)

        # Masters auto-create their table
        if role == 'master':
            new_table_id = secrets.token_hex(6)
            invite = secrets.token_hex(3).upper()
            _db_raw.create_table(new_table_id, f"Mesa de {username}", uid, invite)
            # Assign master to their own table
            users[uid]['table_id'] = new_table_id
            save_users(users)
            flash(f'Conta criada! Sua mesa foi criada. Código de convite para jogadores: {invite}', 'success')
        else:
            flash('Conta criada com sucesso!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ============================================================
# MASTER ROUTES
# ============================================================
@app.route('/master')
@login_required
def master_dashboard():
    if current_user.role != 'master':
        return redirect(url_for('player_dashboard'))
    tid = _tid()
    users = _db_raw.get_users()
    # Only show players from this master's table
    players = {uid: u for uid, u in users.items() if u['role'] == 'player' and u.get('table_id') == tid}
    game_state = get_game_state()
    table = _db_raw.get_table(tid)
    return render_template('master.html',
                         players=players,
                         game_state=game_state,
                         routes=ROUTES_DATA,
                         current_table=table)


@app.route('/master/table', methods=['GET'])
@login_required
def master_table_info():
    """Returns current table info (name, invite code) for the master."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    table = _db_raw.get_table(_tid())
    if not table:
        return jsonify({'error': 'Mesa não encontrada'}), 404
    return jsonify(table)


@app.route('/master/table/rename', methods=['POST'])
@login_required
def master_rename_table():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome inválido'}), 400
    conn = _db_raw.get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE tables SET name = %s WHERE id = %s', (name, _tid()))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True, 'name': name})


@app.route('/master/table/new-invite', methods=['POST'])
@login_required
def master_new_invite():
    """Generate a new invite code for the current table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    new_code = secrets.token_hex(3).upper()
    conn = _db_raw.get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE tables SET invite_code = %s WHERE id = %s', (new_code, _tid()))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True, 'invite_code': new_code})


@app.route('/master/table/players', methods=['GET'])
@login_required
def master_table_players():
    """List players in this table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = _db_raw.get_users()
    tid = _tid()
    players = [{'id': uid, 'username': u['username']}
               for uid, u in users.items() if u['role'] == 'player' and u.get('table_id') == tid]
    return jsonify(players)


@app.route('/master/table/kick/<player_id>', methods=['POST'])
@login_required
def master_kick_player(player_id):
    """Remove a player from this table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = _db_raw.get_users()
    tid = _tid()
    u = users.get(player_id)
    if not u or u.get('table_id') != tid:
        return jsonify({'error': 'Jogador não encontrado nesta mesa'}), 404
    _db_raw.set_user_table(player_id, None)
    return jsonify({'ok': True})

# ── Player transfer system ──────────────────────────────────
# Flow:
# 1. Player requests transfer: POST /player/request-transfer {invite_code}
# 2. Destination master sees pending request in their mesa tab
# 3. Master approves: POST /master/table/approve-transfer {request_id, keep_progress}
#    keep_progress=true → keep trainer_data as-is
#    keep_progress=false → reset trainer_data to fresh player

PENDING_TRANSFERS = {}  # {request_id: {player_id, from_table, to_table, username, trainer_data}}

@app.route('/player/request-transfer', methods=['POST'])
@login_required
def player_request_transfer():
    """Player requests to move to another table via invite code."""
    data = request.json or {}
    invite_code = (data.get('invite_code') or '').strip().upper()
    if not invite_code:
        return jsonify({'error': 'Código inválido'}), 400
    target_table = _db_raw.get_table_by_invite(invite_code)
    if not target_table:
        return jsonify({'error': 'Código de convite não encontrado'}), 404
    current_tid = _tid()
    if target_table['id'] == current_tid:
        return jsonify({'error': 'Você já está nesta mesa'}), 400

    users = _db_raw.get_users()
    user = users.get(current_user.id, {})
    req_id = secrets.token_hex(6)
    PENDING_TRANSFERS[req_id] = {
        'request_id': req_id,
        'player_id': current_user.id,
        'username': current_user.username,
        'from_table': current_tid,
        'to_table': target_table['id'],
        'trainer_data': user.get('trainer_data', {})
    }
    # Notify destination master
    socketio.emit('transfer_request', PENDING_TRANSFERS[req_id],
                  room=f'master_{target_table["id"]}')
    return jsonify({'ok': True, 'message': f'Solicitação enviada ao mestre da mesa "{target_table["name"]}"'})


@app.route('/master/table/approve-transfer', methods=['POST'])
@login_required
def master_approve_transfer():
    """Master approves or rejects a player transfer."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    req_id = data.get('request_id')
    keep_progress = bool(data.get('keep_progress', True))
    approved = bool(data.get('approved', True))
    req = PENDING_TRANSFERS.pop(req_id, None)
    if not req:
        return jsonify({'error': 'Solicitação não encontrada ou expirada'}), 404
    if req['to_table'] != _tid():
        return jsonify({'error': 'Solicitação não pertence a esta mesa'}), 403

    if not approved:
        socketio.emit('transfer_result', {'approved': False,
            'message': 'Sua solicitação de transferência foi recusada pelo mestre.'},
            room=req['player_id'])
        return jsonify({'ok': True, 'approved': False})

    users = _db_raw.get_users()
    user = users.get(req['player_id'])
    if not user:
        return jsonify({'error': 'Jogador não encontrado'}), 404

    if not keep_progress:
        # Reset to fresh trainer
        user['trainer_data'] = {
            'name': user['username'],
            'level': 1, 'xp': 0, 'xp_to_next': 100,
            'team': [], 'bag': [], 'badges': [], 'visited_routes': [], 'notes': ''
        }
    user['table_id'] = req['to_table']
    _db_raw.save_user(req['player_id'], user)

    socketio.emit('transfer_result', {
        'approved': True,
        'keep_progress': keep_progress,
        'message': 'Transferência aprovada! Faça logout e login novamente para entrar na nova mesa.'
    }, room=req['player_id'])
    return jsonify({'ok': True, 'approved': True, 'keep_progress': keep_progress})


@app.route('/master/table/pending-transfers', methods=['GET'])
@login_required
def master_pending_transfers():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tid = _tid()
    pending = [r for r in PENDING_TRANSFERS.values() if r['to_table'] == tid]
    return jsonify(pending)


# ── Map system ───────────────────────────────────────────────
import os as _os

MAPS_STATIC_DIR = _os.path.join(_os.path.dirname(__file__), 'static', 'maps')

BUNDLED_MAPS = [
    {'id': 'galar', 'name': 'Galar', 'file': 'galar_map.png'},
    {'id': 'galarian', 'name': 'Galar (detalhe)', 'file': 'galarian_map.png'},
    {'id': 'kalos', 'name': 'Kalos', 'file': 'kalos_map.png'},
    {'id': 'alola', 'name': 'Alola (geral)', 'file': 'alola_map_geral.jpg'},
    {'id': 'alola_mele', 'name': 'Alola – Melemele', 'file': 'alola_map_melemele_island.png'},
    {'id': 'alola_akala', 'name': 'Alola – Akala', 'file': 'alola_map_akala_island.png'},
    {'id': 'alola_ula', 'name': "Alola – Ula'Ula", 'file': 'alola_map_ula_ula_island.png'},
    {'id': 'alola_poni', 'name': 'Alola – Poni', 'file': 'alola_map_poni_island.png'},
    {'id': 'paldea', 'name': 'Paldea', 'file': 'pokemon_paldea_map.jpg'},
    {'id': 'geral', 'name': 'Mapa Geral', 'file': 'mapa_geral.png'},
    {'id': 'geral_nomes', 'name': 'Mapa Geral (nomes)', 'file': 'mapa_atualizado_com_nomes.jpg'},
]

# Add exterior maps dynamically
_ext_dir = _os.path.join(MAPS_STATIC_DIR, 'exteriores')
if _os.path.isdir(_ext_dir):
    for _f in sorted(_os.listdir(_ext_dir)):
        if _f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            _name = _f.rsplit('.', 1)[0].replace('_', ' ').title()
            BUNDLED_MAPS.append({'id': f'ext_{_f}', 'name': f'Exterior – {_name}', 'file': f'exteriores/{_f}'})


@app.route('/api/maps', methods=['GET'])
@login_required
def api_maps():
    """List available bundled maps."""
    return jsonify(BUNDLED_MAPS)


@app.route('/master/table/set-map', methods=['POST'])
@login_required
def master_set_map():
    """Set the active map for this table. Broadcasts to all players."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    map_id = data.get('map_id')
    map_file = data.get('map_file')
    map_name = data.get('map_name', '')

    settings = db.get_site_settings()
    settings['active_map'] = {'id': map_id, 'file': map_file, 'name': map_name}
    db.save_site_settings(settings)

    socketio.emit('map_changed', {'map_file': map_file, 'map_name': map_name},
                  room=f'players_{_tid()}')
    return jsonify({'ok': True})


@app.route('/master/quests', methods=['POST'])
@login_required
def add_quest():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    game_state = get_game_state()
    # Parse objectives — accept either list of strings or list of {text, done}
    raw_objectives = data.get('objectives', [])
    objectives = []
    for obj in raw_objectives:
        if isinstance(obj, str):
            objectives.append({'text': obj, 'done': False})
        elif isinstance(obj, dict):
            objectives.append({'text': obj.get('text', ''), 'done': bool(obj.get('done', False))})

    quest = {
        'id': secrets.token_hex(4),
        'title': data.get('title', ''),
        'city': data.get('city', ''),
        'description': data.get('description', ''),
        'category': data.get('category', 'main'),   # 'main' | 'side' | 'urgent'
        'assigned_to': data.get('assigned_to', []),
        'xp_reward': int(data.get('xp_reward', 0)),
        'money_reward': int(data.get('money_reward', 0)),
        'item_rewards': data.get('item_rewards', []),  # [{name, qty, file}]
        'repeatable_per_player': bool(data.get('repeatable_per_player', False)),
        'objectives': objectives,
        'completed': False,
        'completions': {},   # {player_id: True} for repeatable_per_player quests
        'player_notes': {}   # {player_id: note_text}
    }
    game_state['quests'].append(quest)
    save_game_state(game_state)
    socketio.emit('new_quest', quest, room=f'players_{_tid()}')
    return jsonify(quest)

@app.route('/master/quests/<quest_id>/complete', methods=['POST'])
@login_required
def complete_quest(quest_id):
    """Mark a quest as complete and award XP/money/items to assigned players.

    Body (optional): { "player_id": "..." }  — for repeatable_per_player quests,
    completes only for that specific player. If omitted, completes globally.
    """
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    target_player = data.get('player_id')   # optional: complete for one player only
    game_state = get_game_state()
    users = get_users()
    XP_TABLE = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500,
                5500, 6600, 7800, 9100, 10500, 12000, 13600, 15300, 17100, 19000]

    for quest in game_state['quests']:
        if quest['id'] != quest_id:
            continue

        per_player = quest.get('repeatable_per_player', False)

        # Determine which players to reward
        if target_player:
            players_to_reward = [target_player]
        else:
            assigned = quest.get('assigned_to', [])
            players_to_reward = assigned if assigned else [uid for uid, u in users.items() if u['role'] == 'player']

        # Check already completed (global quest)
        if not per_player and quest.get('completed'):
            return jsonify({'error': 'Quest já completada'}), 400

        # For per-player, filter out those who already completed
        if per_player:
            completions = quest.setdefault('completions', {})
            players_to_reward = [p for p in players_to_reward if not completions.get(p)]
            if not players_to_reward:
                return jsonify({'error': 'Todos os jogadores já completaram esta quest'}), 400

        xp_reward    = quest.get('xp_reward', 0)
        money_reward = quest.get('money_reward', 0)
        item_rewards = quest.get('item_rewards', [])

        rewarded = []
        for player_id in players_to_reward:
            if player_id not in users:
                continue
            trainer = users[player_id].get('trainer_data', {})

            # XP
            if xp_reward > 0:
                trainer['xp'] = trainer.get('xp', 0) + xp_reward
                new_level = 1
                for i, threshold in enumerate(XP_TABLE):
                    if trainer['xp'] >= threshold:
                        new_level = i + 1
                old_level = trainer.get('level', 1)
                trainer['level'] = new_level
                trainer['xp_to_next'] = XP_TABLE[min(new_level, len(XP_TABLE)-1)] if new_level < len(XP_TABLE) else 99999
                socketio.emit('xp_update', {
                    'player_id': player_id, 'xp': trainer['xp'],
                    'level': trainer['level'], 'xp_to_next': trainer['xp_to_next'],
                    'leveled_up': new_level > old_level
                }, room=player_id)

            # Money
            if money_reward > 0:
                trainer['money'] = trainer.get('money', 0) + money_reward

            # Items
            for reward_item in item_rewards:
                if not reward_item.get('name'):
                    continue
                bag = trainer.setdefault('bag', [])
                existing = next((i for i in bag if i.get('name') == reward_item['name']), None)
                if existing:
                    existing['qty'] = existing.get('qty', 1) + int(reward_item.get('qty', 1))
                else:
                    bag.append({'name': reward_item['name'],
                                'qty': int(reward_item.get('qty', 1)),
                                'file': reward_item.get('file', '')})

            users[player_id]['trainer_data'] = trainer

            # Notify player
            socketio.emit('quest_completed', {
                'quest_id': quest_id,
                'xp_reward': xp_reward,
                'money_reward': money_reward,
                'item_rewards': item_rewards
            }, room=player_id)

            if per_player:
                quest['completions'][player_id] = True

            rewarded.append(player_id)

        # Mark global completion if not per-player
        if not per_player:
            quest['completed'] = True

        save_users(users)
        save_game_state(game_state)

        # Notify master panel
        socketio.emit('quest_updated', quest, room=f'master_{_tid()}')
        return jsonify({'success': True, 'rewarded': rewarded})

    return jsonify({'error': 'Quest not found'}), 404


@app.route('/master/quests/<quest_id>', methods=['PUT'])
@login_required
def update_quest(quest_id):
    """Update quest details (title, description, objectives, etc.)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] == quest_id:
            if 'title'       in data: quest['title']       = data['title']
            if 'city'        in data: quest['city']        = data['city']
            if 'description' in data: quest['description'] = data['description']
            if 'category'    in data: quest['category']    = data['category']
            if 'xp_reward'   in data: quest['xp_reward']   = int(data['xp_reward'])
            if 'money_reward' in data: quest['money_reward'] = int(data['money_reward'])
            if 'item_rewards' in data: quest['item_rewards'] = data['item_rewards']
            if 'repeatable_per_player' in data: quest['repeatable_per_player'] = bool(data['repeatable_per_player'])
            if 'objectives'  in data:
                raw = data['objectives']
                quest['objectives'] = [
                    {'text': o if isinstance(o, str) else o.get('text', ''),
                     'done': False if isinstance(o, str) else bool(o.get('done', False))}
                    for o in raw
                ]
            save_game_state(game_state)
            socketio.emit('quest_updated', quest, room=f'players_{_tid()}')
            return jsonify(quest)
    return jsonify({'error': 'Quest not found'}), 404


@app.route('/master/quests/<quest_id>', methods=['DELETE'])
@login_required
def delete_quest(quest_id):
    """Delete a quest entirely."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    game_state = get_game_state()
    before = len(game_state['quests'])
    game_state['quests'] = [q for q in game_state['quests'] if q['id'] != quest_id]
    if len(game_state['quests']) == before:
        return jsonify({'error': 'Quest not found'}), 404
    save_game_state(game_state)
    socketio.emit('quest_deleted', {'quest_id': quest_id}, room=f'players_{_tid()}')
    socketio.emit('quest_deleted', {'quest_id': quest_id}, room=f'master_{_tid()}')
    return jsonify({'success': True})


@app.route('/api/game-state', methods=['GET'])
@login_required
def api_game_state():
    """Return current game state (quests, etc.) for master UI refresh."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(get_game_state())


@app.route('/quests/<quest_id>/objectives/<int:obj_idx>/toggle', methods=['POST'])
@login_required
def toggle_objective(quest_id, obj_idx):
    """Toggle an objective's done state. Auto-completes quest if all done."""
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] != quest_id:
            continue
        objectives = quest.get('objectives', [])
        if obj_idx < 0 or obj_idx >= len(objectives):
            return jsonify({'error': 'Invalid objective index'}), 400
        objectives[obj_idx]['done'] = not objectives[obj_idx]['done']
        quest['objectives'] = objectives

        # Auto-complete if all objectives done
        auto_completed = False
        if objectives and all(o['done'] for o in objectives) and not quest['completed']:
            quest['completed'] = True
            auto_completed = True

        save_game_state(game_state)
        socketio.emit('quest_updated', quest, room=f'players_{_tid()}')
        socketio.emit('quest_updated', quest, room=f'master_{_tid()}')
        return jsonify({'quest': quest, 'auto_completed': auto_completed})
    return jsonify({'error': 'Quest not found'}), 404


@app.route('/quests/<quest_id>/notes', methods=['POST'])
@login_required
def save_quest_notes(quest_id):
    """Save player notes on a quest."""
    data = request.json or {}
    note = data.get('note', '')
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] == quest_id:
            if 'player_notes' not in quest:
                quest['player_notes'] = {}
            quest['player_notes'][current_user.id] = note
            save_game_state(game_state)
            return jsonify({'success': True})
    return jsonify({'error': 'Quest not found'}), 404


@app.route('/master/players/<player_id>')
@login_required
def master_view_player(player_id):
    """Master full view of a player's data."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id in users:
        return jsonify(users[player_id])
    return jsonify({'error': 'Player not found'}), 404

@app.route('/master/players/<player_id>/edit', methods=['POST'])
@login_required
def master_edit_player(player_id):
    """Master can edit ANY field of any player's trainer data. No restrictions."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player not found'}), 404
    
    data = request.json
    trainer = users[player_id].get('trainer_data', {})
    
    # Master can edit everything - no field restrictions
    for key, value in data.items():
        trainer[key] = value
    
    users[player_id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'success': True, 'trainer_data': trainer})

@app.route('/master/players/<player_id>/team', methods=['POST'])
@login_required
def master_edit_team(player_id):
    """Master can edit a player's Pokemon team directly."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player not found'}), 404
    
    data = request.json
    users[player_id]['trainer_data']['team'] = data.get('team', [])
    save_users(users)
    return jsonify({'success': True})

# ============================================================
# NPC MANAGEMENT
# ============================================================

@app.route('/master/npcs', methods=['GET'])
@login_required
def list_npcs():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(db.get_npcs())

@app.route('/master/npcs', methods=['POST'])
@login_required
def create_npc():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    npc = {
        'id': secrets.token_hex(4),
        'name': data.get('name', ''),
        'npc_class': data.get('npc_class', ''),
        'level': data.get('level', 10),
        'team': data.get('team', []),
        'notes': data.get('notes', '')
    }
    db.save_npc(npc)
    return jsonify(npc)

@app.route('/master/npcs/<npc_id>', methods=['PUT'])
@login_required
def update_npc(npc_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    npcs = db.get_npcs()
    npc  = next((n for n in npcs if n['id'] == npc_id), None)
    if not npc:
        return jsonify({'error': 'NPC not found'}), 404
    for field in ['name', 'npc_class', 'level', 'role', 'specialty', 'money', 'team', 'notes']:
        if field in data:
            npc[field] = data[field]
    db.save_npc(npc)
    socketio.emit('npcs_update', {'npcs': db.get_npcs()}, room=f'master_{_tid()}')
    return jsonify(npc)


@app.route('/master/npcs/<npc_id>', methods=['DELETE'])
@login_required
def delete_npc(npc_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    db.delete_npc(npc_id)
    return jsonify({'success': True})

@app.route('/master/npcs/generate', methods=['POST'])
@login_required
def generate_npc():
    """Auto-generate an NPC with themed team based on class/type."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    npc_class = data.get('npc_class', 'Trainer')
    level = int(data.get('level', 10))
    team_size = int(data.get('team_size', 3))
    preferred_types = data.get('types', [])  # e.g. ['fire', 'fighting']
    
    # NPC name generation
    first_names = [
        'Akira', 'Brock', 'Cynthia', 'Drake', 'Elesa', 'Flint', 'Gardenia', 
        'Hau', 'Iris', 'Jasmine', 'Koga', 'Lance', 'Misty', 'Norman',
        'Olivia', 'Phoebe', 'Quinn', 'Raihan', 'Sabrina', 'Tate',
        'Uri', 'Volkner', 'Wallace', 'Xerxes', 'Yuki', 'Zinnia',
        'Bruno', 'Clair', 'Diantha', 'Erika', 'Fantina', 'Guzma',
        'Hex', 'Ilima', 'Jupiter', 'Karen', 'Lorelei', 'Marlon',
        'Nessa', 'Opal', 'Piers', 'Roxie', 'Skyla', 'Thorton',
        'Wulfric', 'Allister', 'Bea', 'Gordie', 'Melony', 'Leon'
    ]
    
    titles = {
        'Gym Leader': 'Líder ',
        'Elite Four': 'Elite ',
        'Champion': 'Campeão(ã) ',
        'Trainer': '',
        'Ranger': 'Ranger ',
        'Rocket': 'Rocket ',
        'Ace': 'Ás ',
        'Breeder': 'Criador(a) ',
        'Youngster': 'Jovem ',
        'Hiker': 'Montanhista ',
        'Swimmer': 'Nadador(a) ',
        'Psychic': 'Médium ',
        'Bug Catcher': 'Caça-insetos ',
        'Fisherman': 'Pescador ',
        'Beauty': '',
        'Scientist': 'Cientista ',
        'Blackbelt': 'Faixa Preta '
    }
    
    name_prefix = titles.get(npc_class, '')
    name = name_prefix + random.choice(first_names)
    
    # Determine types for team
    class_type_map = {
        'Gym Leader': preferred_types,
        'Elite Four': preferred_types,
        'Champion': [],  # mixed
        'Trainer': [],
        'Ranger': ['grass', 'bug', 'normal'],
        'Rocket': ['poison', 'dark', 'ghost'],
        'Ace': [],
        'Breeder': ['normal', 'fairy'],
        'Youngster': ['normal', 'bug'],
        'Hiker': ['rock', 'ground', 'fighting'],
        'Swimmer': ['water'],
        'Psychic': ['psychic', 'ghost'],
        'Bug Catcher': ['bug'],
        'Fisherman': ['water'],
        'Scientist': ['electric', 'steel', 'psychic'],
        'Blackbelt': ['fighting']
    }
    
    types_to_use = preferred_types if preferred_types else class_type_map.get(npc_class, [])
    
    # Build team
    team = []
    candidates = []
    
    if types_to_use:
        for t in types_to_use:
            candidates.extend(POKEMON_BY_TYPE.get(t.lower(), []))
        # Remove duplicates
        seen = set()
        unique = []
        for c in candidates:
            if c['number'] not in seen:
                seen.add(c['number'])
                unique.append(c)
        candidates = unique
    else:
        candidates = POKEMON_DB[:]

    # Restrict to Gen 1-3 (≤386)
    candidates = [p for p in candidates if p.get('number', 999) <= 386]

    # Filter by level appropriateness
    level_filtered = [p for p in candidates if p.get('minLevel', 1) <= level]
    if not level_filtered:
        level_filtered = candidates[:50]
    
    # Prefer evolved pokemon for higher levels
    if level >= 15:
        evolved = [p for p in level_filtered if '/' in p.get('evolutionStage', '1/1') and int(p['evolutionStage'].split('/')[0]) >= 2]
        if len(evolved) >= team_size:
            level_filtered = evolved
    
    # Pick random team
    pick_count = min(team_size, len(level_filtered))
    chosen_pokemon = random.sample(level_filtered, pick_count) if pick_count > 0 else []
    
    for poke in chosen_pokemon:
        # Calculate pokemon level (around NPC level ±2)
        poke_level = max(poke.get('minLevel', 1), level + random.randint(-2, 1))
        
        # Build moveset
        move_pool = list(poke.get('startingMoves', []))
        if poke.get('levelMoves'):
            for lv, moves in poke['levelMoves'].items():
                if int(lv) <= poke_level:
                    move_pool.extend(moves)
        move_pool = [m for m in move_pool if len(m) > 2 and not m.startswith('©') and '©' not in m and 'unofficial' not in m.lower() and 'wizards' not in m.lower() and 'nintendo' not in m.lower() and 'portions' not in m.lower() and len(m) < 30]
        move_pool = list(dict.fromkeys(move_pool))
        moves = move_pool[-4:] if len(move_pool) > 4 else (move_pool if move_pool else ['Tackle'])
        
        team.append({
            'name': poke['name'],
            'number': poke['number'],
            'level': poke_level,
            'types': poke.get('types', []),
            'hp': poke.get('hp', 20),
            'maxHp': poke.get('hp', 20),
            'currentHp': poke.get('hp', 20),
            'ac': poke.get('ac', 13),
            'stats': poke.get('stats', {}),
            'moves': moves,
            'speed': poke.get('speed', '30ft'),
            'ability': poke.get('ability', {}).get('name', '') if poke.get('ability') else '',
            'vulnerabilities': poke.get('vulnerabilities', []),
            'resistances': poke.get('resistances', [])
        })
    
    # Create NPC
    npc = {
        'id': secrets.token_hex(4),
        'name': name,
        'npc_class': npc_class + (' - ' + '/'.join(t.title() for t in types_to_use) if types_to_use else ''),
        'level': level,
        'team': team,
        'notes': f'Gerado automaticamente. {team_size} Pokémon.',
        'generated': True
    }
    db.save_npc(npc)
    return jsonify(npc)

def check_and_evolve_pokemon(pokemon):
    """Check if a Pokemon should evolve based on its current level.
    Returns (evolved_pokemon_data, evolved_name) or (None, None) if no evolution."""
    import re
    info = pokemon.get('evolutionInfo', '') or ''
    if not info:
        return None, None

    # Parse: "X can evolve into Y at level N and above."
    match = re.search(r'evolve into ([A-Za-z\-\s]+?) at (?:trainer )?level (\d+)', info, re.IGNORECASE)
    if not match:
        match = re.search(r'evolve into ([A-Za-z\-\s]+?) at level (\d+)', info, re.IGNORECASE)
    if not match:
        return None, None

    evolved_name = match.group(1).strip()
    evo_trainer_level = int(match.group(2))
    evo_pokemon_level = evo_trainer_level * 5  # trainer level scale to pokemon level scale

    current_level = pokemon.get('level', 1)
    if current_level < evo_pokemon_level:
        return None, None

    evolved_base = POKEMON_BY_NAME.get(evolved_name.lower())
    if not evolved_base:
        return None, None

    # Build evolved pokemon, preserving player-specific data
    scaled = scaling.calculate_pokemon_stats(evolved_base, current_level, pokemon.get('nature'))
    evolved = {
        'name': evolved_base['name'],
        'number': evolved_base['number'],
        'types': evolved_base.get('types', pokemon.get('types', [])),
        'level': current_level,
        'hp': scaled['hp'],
        'maxHp': scaled['maxHp'],
        'currentHp': min(pokemon.get('currentHp', scaled['hp']), scaled['hp']),
        'ac': scaled['ac'],
        'stats': scaled['stats'],
        'proficiency': scaled['proficiency'],
        'stab': scaled['stab'],
        'speed': evolved_base.get('speed', pokemon.get('speed', '30ft')),
        'ability': evolved_base.get('ability', {}).get('name', '') if evolved_base.get('ability') else pokemon.get('ability', ''),
        'vulnerabilities': evolved_base.get('vulnerabilities', []),
        'resistances': evolved_base.get('resistances', []),
        'evolutionInfo': evolved_base.get('evolutionInfo', ''),
        'evolutionStage': evolved_base.get('evolutionStage', ''),
        # Preserve player-specific fields
        'nickname': pokemon.get('nickname', ''),
        'nature': pokemon.get('nature', ''),
        'moves': pokemon.get('moves', []),
        'heldItem': pokemon.get('heldItem', ''),
        'notes': pokemon.get('notes', ''),
    }
    return evolved, evolved_base['name']


@app.route('/master/xp', methods=['POST'])
@login_required
def give_xp():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    player_id = data.get('player_id')
    xp_amount = int(data.get('xp', 0))
    
    users = get_users()
    if player_id in users:
        trainer = users[player_id].get('trainer_data', {})
        trainer['xp'] = trainer.get('xp', 0) + xp_amount
        # Level up check - XP table based on Pokemon 5e
        xp_table = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500,
                    5500, 6600, 7800, 9100, 10500, 12000, 13600, 15300, 17100, 19000]
        current_xp = trainer['xp']
        new_level = 1
        for i, threshold in enumerate(xp_table):
            if current_xp >= threshold:
                new_level = i + 1
        
        old_level = trainer.get('level', 1)
        trainer['level'] = new_level
        trainer['xp_to_next'] = xp_table[min(new_level, len(xp_table)-1)] if new_level < len(xp_table) else 99999
        
        # Auto-level Pokemon (trainer level - 2, min 1) and check evolution
        evolutions = []
        for i, pokemon in enumerate(trainer.get('team', [])):
            if pokemon.get('level', 1) < new_level - 2:
                pokemon['level'] = max(1, new_level - 2)
            evolved, evolved_name = check_and_evolve_pokemon(pokemon)
            if evolved:
                old_name = pokemon.get('name', '')
                old_number = pokemon.get('number', 0)
                evolved_base_data = POKEMON_BY_NAME.get(evolved_name.lower(), {})
                new_moves = [m for m in (evolved_base_data.get('startingMoves') or [])
                             if m not in (pokemon.get('moves') or [])]
                trainer['team'][i] = evolved
                evolutions.append({
                    'from': old_name, 'to': evolved_name, 'slot': i,
                    'old_number': old_number, 'new_number': evolved.get('number', 0),
                    'new_moves': new_moves
                })

        users[player_id]['trainer_data'] = trainer
        save_users(users)

        # Emit XP update to specific player
        socketio.emit('xp_update', {
            'player_id': player_id,
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level,
            'evolutions': evolutions
        }, room=player_id)
        
        # Also notify master
        socketio.emit('xp_update', {
            'player_id': player_id,
            'username': users[player_id]['username'],
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level
        }, room=f'master_{_tid()}')
        
        return jsonify({'success': True, 'level': new_level, 'xp': trainer['xp']})
    return jsonify({'error': 'Player not found'}), 404

# ============================================================
# SITE SETTINGS API
# ============================================================
@app.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    """Get current site settings (available to all users)."""
    return jsonify(db.get_site_settings())

@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    """Update site settings (master only). Broadcasts to all connected users."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    settings = db.get_site_settings()
    allowed_fields = ['theme', 'background', 'custom_banner', 'mesa_name']
    for field in allowed_fields:
        if field in data:
            settings[field] = data[field]
    db.save_site_settings(settings)
    # Broadcast theme change to ALL connected users in real-time
    socketio.emit('theme_changed', settings)
    return jsonify(settings)

# ============================================================
# POKEMON API
# ============================================================
@app.route('/api/pokemon')
@login_required
def api_pokemon_list():
    """List all pokemon with optional filters."""
    type_filter = request.args.get('type', '').lower()
    level_min = int(request.args.get('level_min', 0))
    level_max = int(request.args.get('level_max', 100))
    search = request.args.get('search', '').lower()
    
    results = POKEMON_DB
    if type_filter:
        results = [p for p in results if type_filter in [t.lower() for t in p.get('types', [])]]
    if level_min > 0:
        results = [p for p in results if p.get('minLevel', 0) >= level_min]
    if level_max < 100:
        results = [p for p in results if p.get('minLevel', 0) <= level_max]
    if search:
        results = [p for p in results if search in p['name'].lower() or search == str(p['number'])]
    
    limit = int(request.args.get('limit', 50))
    return jsonify(results[:limit])

@app.route('/api/pokemon/all')
@login_required
def api_pokemon_all():
    """Return slim list of ALL pokemon for the Pokedex (number, name, types only)."""
    return jsonify([{'number': p['number'], 'name': p['name'], 'types': p.get('types', [])} for p in POKEMON_DB])

@app.route('/api/pokemon/<int:number>')
@login_required
def api_pokemon_detail(number):
    """Get a specific Pokemon by number."""
    pokemon = POKEMON_BY_NUMBER.get(number)
    if pokemon:
        return jsonify(pokemon)
    return jsonify({'error': 'Pokemon not found'}), 404

@app.route('/api/moves')
@login_required
def api_moves():
    """Get move data. Query by name."""
    name = request.args.get('name', '').strip()
    if name:
        move = MOVES_BY_NAME.get(name.lower()) or MOVES_DB.get(name)
        if move:
            return jsonify(move)
        # Fuzzy search
        results = [v for k, v in MOVES_DB.items() if name.lower() in k.lower()]
        if results:
            return jsonify(results[:10])
    return jsonify({}), 404

@app.route('/api/moves/batch', methods=['POST'])
@login_required
def api_moves_batch():
    """Get multiple moves at once."""
    data = request.json
    move_names = data.get('moves', [])
    results = {}
    for name in move_names:
        move = MOVES_BY_NAME.get(name.lower()) or MOVES_DB.get(name)
        if move:
            results[name] = move
    return jsonify(results)

@app.route('/api/mega/<pokemon_name>')
@login_required
def api_mega(pokemon_name):
    """Get mega evolution data for a pokemon."""
    megas = MEGA_BY_POKEMON.get(pokemon_name.lower(), [])
    if megas:
        return jsonify(megas)
    return jsonify([]), 404

@app.route('/api/mega')
@login_required
def api_mega_all():
    """Get all mega stones."""
    return jsonify(MEGA_DB)

@app.route('/api/encounter', methods=['POST'])
@login_required
def api_encounter():
    """Generate a random encounter based on route, hunt mode, rarity.
    
    Level scale: Pokemon 1-100.
    player_level = highest Pokemon level in player's team.
    
    Modes:
    - Normal: ±5 levels of player. Common Pokemon. Shiny 1%.
    - Dungeon: ±15 levels, skews harder. Rare/evolved Pokemon. Shiny 3%.
    - Night: +10 to +30 above player. Extremely dangerous. Shiny 5%.
    """
    data = request.json
    route_id = data.get('route_id')
    hunt_mode = data.get('hunt_mode', 'normal')
    if data.get('is_dungeon') and hunt_mode == 'normal':
        hunt_mode = 'dungeon'
    # player_level = highest Pokemon level in team (1-100 scale)
    player_level = int(data.get('player_level', 5))
    
    route = ROUTES_DATA.get(route_id, {})
    route_types = route.get('types', ['Normal'])
    # Scale route level range to 1-100 (original was 1-20 based)
    raw_range = route.get('level_range', [1, 20])
    route_level_range = [raw_range[0] * 5, min(100, raw_range[1] * 5)]
    
    # Dungeon/night use dungeon types (stronger/rarer)
    if hunt_mode in ('dungeon', 'night'):
        route_types = route.get('dungeon_types', route_types)

    # Gen 1-3 filter (up to #386)
    GEN3_MAX = 386

    # If route has an explicit pokemon list, use it (route-specific encounters)
    route_pokemon_names = route.get('pokemon', [])
    if route_pokemon_names:
        # Resolve names to data entries (try exact match, then case-insensitive)
        candidates = []
        for pname in route_pokemon_names:
            entry = POKEMON_BY_NAME.get(pname.lower())
            if entry and entry['number'] <= GEN3_MAX:
                candidates.append(entry)
        # Fallback to type pool if nothing matched
        if not candidates:
            route_pokemon_names = []

    if not route_pokemon_names:
        # Type-based pool, filtered to Gen 1-3
        candidates = []
        for ptype in route_types:
            for p in POKEMON_BY_TYPE.get(ptype.lower(), []):
                if p['number'] <= GEN3_MAX:
                    candidates.append(p)

    # Remove duplicates
    seen_nums = set()
    unique_candidates = []
    for c in candidates:
        if c['number'] not in seen_nums:
            seen_nums.add(c['number'])
            unique_candidates.append(c)
    candidates = unique_candidates

    if not candidates:
        # Last resort: all Gen 1-3 Normal-type
        candidates = [p for p in POKEMON_BY_TYPE.get('normal', []) if p['number'] <= GEN3_MAX]
    
    # Level filtering based on mode
    if hunt_mode == 'night':
        # Night: dangerous, -10 to +20 (mixes weak and strong)
        min_lv = max(1, player_level - 10)
        max_lv = min(100, player_level + 20)
    elif hunt_mode == 'dungeon':
        # Dungeon: varied, -10 to +10 (mix of strong and weak)
        min_lv = max(1, player_level - 10)
        max_lv = min(100, player_level + 10)
    else:
        # Normal: -50% of player level to +5 levels
        min_lv = max(1, player_level // 2)
        max_lv = min(100, player_level + 5)
    
    # Filter candidates by minLevel appropriateness
    # minLevel in JSON is trainer-level scale (1-20), convert: minLevel * 5
    filtered = [p for p in candidates if (p.get('minLevel', 1) * 5) <= max_lv]
    
    if not filtered:
        filtered = sorted(candidates, key=lambda p: abs((p.get('minLevel', 1) * 5) - player_level))[:10]
    
    if not filtered:
        return jsonify({'error': 'No pokemon available for this route'}), 404
    
    # Rarity weights - dungeon/night favors evolved/rare
    weights = []
    for p in filtered:
        stage = p.get('evolutionStage', '1/1')
        stage_num = int(stage.split('/')[0]) if '/' in stage else 1
        sr_str = p.get('sr', '1/2')
        if '/' in str(sr_str):
            sr_val = int(str(sr_str).split('/')[0]) / int(str(sr_str).split('/')[1])
        else:
            sr_val = float(sr_str)
        
        if hunt_mode == 'night':
            # Night: heavily favors evolved/high-SR
            weight = max(1, sr_val * 4 + stage_num * 3)
        elif hunt_mode == 'dungeon':
            # Dungeon: favors evolved
            weight = max(1, sr_val * 2 + stage_num * 2)
        else:
            # Normal: common first-stage pokemon more likely
            weight = 10 if stage_num == 1 else (3 if stage_num == 2 else 1)
            if sr_val <= 0.5: weight *= 3
            elif sr_val <= 2: weight *= 2
        
        weights.append(max(1, weight))
    
    chosen = random.choices(filtered, weights=weights, k=1)[0]
    
    # Determine encounter level
    if hunt_mode == 'night':
        # Night: -10 to +20 (varied, skews dangerous)
        encounter_level = random.randint(max(1, player_level - 10), min(100, player_level + 20))
    elif hunt_mode == 'dungeon':
        # Dungeon: -10 to +10 (varied mix)
        encounter_level = random.randint(max(1, player_level - 10), min(100, player_level + 10))
    else:
        # Normal: -50% of player level to +5
        low = max(1, player_level // 2)
        high = min(100, player_level + 5)
        encounter_level = random.randint(low, high)
    
    # Ensure minimum level based on pokemon's min (scaled)
    pokemon_min_lv = max(1, chosen.get('minLevel', 1) * 5)
    encounter_level = max(pokemon_min_lv, encounter_level)
    encounter_level = min(100, encounter_level)
    
    # Shiny chance by mode
    shiny_chances = {'normal': 0.01, 'dungeon': 0.03, 'night': 0.05}
    is_shiny = random.random() < shiny_chances.get(hunt_mode, 0.01)
    
    # Generate moveset (picks last 4 available moves for the level)
    move_pool = list(chosen.get('startingMoves', []))
    if chosen.get('levelMoves'):
        for lv, moves in chosen['levelMoves'].items():
            # levelMoves keys are trainer-level scale, multiply by 5
            if int(lv) * 5 <= encounter_level:
                move_pool.extend(moves)
    if chosen.get('eggMoves'):
        move_pool.extend(chosen['eggMoves'])
    
    move_pool = [m for m in move_pool if len(m) > 2 and not m.startswith('©') and not m.isdigit() and 'unofficial' not in m.lower() and 'wizards' not in m.lower() and 'nintendo' not in m.lower() and 'portions' not in m.lower() and '©' not in m and len(m) < 30]
    move_pool = list(dict.fromkeys(move_pool))
    
    # Validate moves against database - only keep moves that actually exist
    move_pool = [m for m in move_pool if m.lower() in MOVES_BY_NAME or m in MOVES_DB]
    
    # Pick last 4 moves (highest level moves)
    wild_moves = move_pool[-4:] if len(move_pool) > 4 else (move_pool if move_pool else ['Tackle'])
    
    # Calculate scaled stats for the wild pokemon
    scaled = scaling.calculate_pokemon_stats(chosen, encounter_level)
    
    # Build pokemon data with scaled stats
    pokemon_data = dict(chosen)
    pokemon_data['hp'] = scaled['hp']
    pokemon_data['maxHp'] = scaled['maxHp']
    pokemon_data['ac'] = scaled['ac']
    pokemon_data['stats'] = scaled['stats']
    pokemon_data['proficiency'] = scaled['proficiency']
    pokemon_data['stab'] = scaled['stab']
    
    # Shiny boost: +20% em todos os stats, +20% HP, +2 AC
    if is_shiny:
        pokemon_data['hp'] = int(pokemon_data['hp'] * 1.2)
        pokemon_data['maxHp'] = pokemon_data['hp']
        pokemon_data['ac'] += 2
        for stat in pokemon_data['stats']:
            pokemon_data['stats'][stat] = int(pokemon_data['stats'][stat] * 1.2)
        pokemon_data['is_shiny'] = True
    
    encounter = {
        'pokemon': pokemon_data,
        'level': encounter_level,
        'wild_moves': wild_moves,
        'is_shiny': is_shiny,
        'hunt_mode': hunt_mode,
        'route_id': route_id
    }
    
    return jsonify(encounter)

# ============================================================
# PLAYER ROUTES
# ============================================================
@app.route('/player')
@login_required
def player_dashboard():
    if current_user.role == 'master':
        return redirect(url_for('master_dashboard'))
    users = get_users()
    trainer_data = users.get(current_user.id, {}).get('trainer_data', {})
    game_state = get_game_state()
    # Filter quests for this player
    my_quests = [q for q in game_state.get('quests', []) 
                 if current_user.id in q.get('assigned_to', []) or not q.get('assigned_to')]
    return render_template('player.html',
                         trainer=trainer_data,
                         quests=my_quests,
                         routes=ROUTES_DATA,
                         current_user_id=current_user.id)

@app.route('/player/pc', methods=['GET'])
@login_required
def get_pc():
    """Get player's PC box."""
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    return jsonify(trainer.get('pc', []))


@app.route('/player/pc/deposit', methods=['POST'])
@login_required
def pc_deposit():
    """Move a Pokémon from team to PC."""
    data = request.json or {}
    idx  = data.get('team_idx')

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])

    if idx is None or idx < 0 or idx >= len(team):
        return jsonify({'error': 'Índice inválido'}), 400
    if len(team) <= 1:
        return jsonify({'error': 'Você não pode depositar seu último Pokémon!'}), 400

    poke = team.pop(idx)
    pc   = trainer.get('pc', [])
    pc.append(poke)
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/pc/withdraw', methods=['POST'])
@login_required
def pc_withdraw():
    """Move a Pokémon from PC to team."""
    data = request.json or {}
    idx  = data.get('pc_idx')

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    pc      = trainer.get('pc', [])

    if idx is None or idx < 0 or idx >= len(pc):
        return jsonify({'error': 'Índice inválido'}), 400
    if len(team) >= 6:
        return jsonify({'error': 'Time cheio! Deposite um Pokémon primeiro.'}), 400

    poke = pc.pop(idx)
    team.append(poke)
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/pc/swap', methods=['POST'])
@login_required
def pc_swap():
    """Swap a team Pokémon directly with a PC Pokémon."""
    data     = request.json or {}
    team_idx = data.get('team_idx')
    pc_idx   = data.get('pc_idx')

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    pc      = trainer.get('pc', [])

    if team_idx is None or pc_idx is None:
        return jsonify({'error': 'Parâmetros inválidos'}), 400
    if team_idx < 0 or team_idx >= len(team) or pc_idx < 0 or pc_idx >= len(pc):
        return jsonify({'error': 'Índice fora dos limites'}), 400

    team[team_idx], pc[pc_idx] = pc[pc_idx], team[team_idx]
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/use-stone', methods=['POST'])
@login_required
def use_evolution_stone():
    """Player uses an evolution stone/item on a team Pokémon."""
    data = request.json or {}
    pokemon_idx = data.get('pokemon_idx')
    item_name   = data.get('item_name', '').strip()

    if pokemon_idx is None or not item_name:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    bag     = trainer.get('bag', [])

    if pokemon_idx < 0 or pokemon_idx >= len(team):
        return jsonify({'error': 'Pokémon inválido'}), 400

    pokemon = team[pokemon_idx]

    # Check item is in bag
    bag_item = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if not bag_item or (bag_item.get('qty') or 0) < 1:
        return jsonify({'error': f'Você não tem {item_name} na bolsa!'}), 400

    # Check evolution
    evolved_name, ok = scaling.get_special_evolution(
        pokemon['name'],
        stone_used=item_name,
        battle_wins=pokemon.get('battle_wins', 0),
        moves=pokemon.get('moves', [])
    )
    if not ok or not evolved_name:
        return jsonify({'error': f'{pokemon["name"]} não evolui com {item_name}.'}), 400

    evolved_base = POKEMON_BY_NAME.get(evolved_name.lower())
    if not evolved_base:
        return jsonify({'error': f'Pokémon evoluído "{evolved_name}" não encontrado no banco.'}), 404

    # Build evolved Pokémon
    current_level = pokemon.get('level', 1)
    scaled = scaling.calculate_pokemon_stats(evolved_base, current_level, pokemon.get('nature'))
    evolved = {
        'name': evolved_base['name'],
        'number': evolved_base['number'],
        'types': evolved_base.get('types', pokemon.get('types', [])),
        'level': current_level,
        'hp': scaled['hp'], 'maxHp': scaled['maxHp'],
        'currentHp': min(pokemon.get('currentHp', scaled['hp']), scaled['hp']),
        'ac': scaled['ac'], 'stats': scaled['stats'],
        'proficiency': scaled['proficiency'], 'stab': scaled['stab'],
        'speed': evolved_base.get('speed', pokemon.get('speed', '30ft')),
        'ability': evolved_base.get('ability', {}).get('name', '') if evolved_base.get('ability') else pokemon.get('ability', ''),
        'vulnerabilities': evolved_base.get('vulnerabilities', []),
        'resistances': evolved_base.get('resistances', []),
        'evolutionInfo': evolved_base.get('evolutionInfo', ''),
        'evolutionStage': evolved_base.get('evolutionStage', ''),
        'nickname': pokemon.get('nickname', ''),
        'nature': pokemon.get('nature', ''),
        'moves': pokemon.get('moves', []),
        'heldItem': pokemon.get('heldItem', ''),
        'notes': pokemon.get('notes', ''),
        'battle_wins': pokemon.get('battle_wins', 0),
    }
    team[pokemon_idx] = evolved

    # Consume item from bag
    bag_item['qty'] = (bag_item.get('qty') or 1) - 1
    if bag_item['qty'] <= 0:
        bag.remove(bag_item)
    trainer['team'] = team
    trainer['bag']  = bag
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    # Notify
    display_name = evolved['nickname'] or evolved['name']
    socketio.emit('pokemon_evolved', {
        'player_id':    current_user.id,
        'old_name':     pokemon['name'],
        'new_name':     evolved['name'],
        'display_name': display_name,
        'method':       f'usou {item_name}'
    }, room=f'players_{_tid()}')
    socketio.emit('pokemon_evolved', {
        'player_id': current_user.id,
        'old_name':  pokemon['name'],
        'new_name':  evolved['name'],
        'method':    f'usou {item_name}'
    }, room=f'master_{_tid()}')

    stone_evolved_base = POKEMON_BY_NAME.get(evolved['name'].lower(), {})
    stone_new_moves = [m for m in (stone_evolved_base.get('startingMoves') or [])
                       if m not in (pokemon.get('moves') or [])]
    return jsonify({
        'ok': True, 'evolved_into': evolved['name'], 'pokemon': evolved,
        'old_number': pokemon.get('number', 0), 'new_number': evolved.get('number', 0),
        'new_moves': stone_new_moves
    })


@app.route('/player/friendship-evolve', methods=['POST'])
@login_required
def friendship_evolve():
    """Evolve a Pokémon by friendship (≥10 battle wins)."""
    data = request.json or {}
    pokemon_idx = data.get('pokemon_idx')

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])

    if pokemon_idx is None or pokemon_idx < 0 or pokemon_idx >= len(team):
        return jsonify({'error': 'Pokémon inválido'}), 400

    pokemon = team[pokemon_idx]
    wins    = pokemon.get('battle_wins', 0)

    evolved_name, ok = scaling.get_special_evolution(
        pokemon['name'], battle_wins=wins
    )
    if not ok or not evolved_name:
        return jsonify({'error': f'{pokemon["name"]} não está pronto para evoluir por amizade (precisa de 10 batalhas vencidas, tem {wins}).'}), 400

    evolved_base = POKEMON_BY_NAME.get(evolved_name.lower())
    if not evolved_base:
        return jsonify({'error': f'"{evolved_name}" não encontrado.'}), 404

    current_level = pokemon.get('level', 1)
    scaled = scaling.calculate_pokemon_stats(evolved_base, current_level, pokemon.get('nature'))
    evolved = {
        'name': evolved_base['name'], 'number': evolved_base['number'],
        'types': evolved_base.get('types', pokemon.get('types', [])),
        'level': current_level,
        'hp': scaled['hp'], 'maxHp': scaled['maxHp'],
        'currentHp': min(pokemon.get('currentHp', scaled['hp']), scaled['hp']),
        'ac': scaled['ac'], 'stats': scaled['stats'],
        'proficiency': scaled['proficiency'], 'stab': scaled['stab'],
        'speed': evolved_base.get('speed', pokemon.get('speed', '30ft')),
        'ability': evolved_base.get('ability', {}).get('name', '') if evolved_base.get('ability') else pokemon.get('ability', ''),
        'vulnerabilities': evolved_base.get('vulnerabilities', []),
        'resistances': evolved_base.get('resistances', []),
        'evolutionInfo': evolved_base.get('evolutionInfo', ''),
        'evolutionStage': evolved_base.get('evolutionStage', ''),
        'nickname': pokemon.get('nickname', ''),
        'nature': pokemon.get('nature', ''),
        'moves': pokemon.get('moves', []),
        'heldItem': pokemon.get('heldItem', ''),
        'notes': pokemon.get('notes', ''),
        'battle_wins': wins,
    }
    team[pokemon_idx] = evolved
    trainer['team'] = team
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    display_name = evolved['nickname'] or evolved['name']
    socketio.emit('pokemon_evolved', {
        'player_id': current_user.id, 'old_name': pokemon['name'],
        'new_name': evolved['name'], 'display_name': display_name, 'method': 'amizade'
    }, room=f'players_{_tid()}')
    socketio.emit('pokemon_evolved', {
        'player_id': current_user.id, 'old_name': pokemon['name'],
        'new_name': evolved['name'], 'method': 'amizade'
    }, room=f'master_{_tid()}')

    friendship_evolved_base = POKEMON_BY_NAME.get(evolved['name'].lower(), {})
    friendship_new_moves = [m for m in (friendship_evolved_base.get('startingMoves') or [])
                            if m not in (pokemon.get('moves') or [])]
    return jsonify({
        'ok': True, 'evolved_into': evolved['name'], 'pokemon': evolved,
        'old_number': pokemon.get('number', 0), 'new_number': evolved.get('number', 0),
        'new_moves': friendship_new_moves
    })


@app.route('/player/pokemon-center', methods=['POST'])
@login_required
def pokemon_center():
    """Heal all Pokémon to full HP and clear all status conditions."""
    users = get_users()
    trainer = users[current_user.id].get('trainer_data', {})
    team = trainer.get('team', [])

    for poke in team:
        poke['currentHp'] = poke.get('maxHp', poke.get('hp', 20))
        poke.pop('status', None)

    trainer['team'] = team
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    socketio.emit('team_update', {
        'player_id': current_user.id,
        'team': team
    }, room=f'master_{_tid()}')

    return jsonify({'ok': True, 'team': team})


@app.route('/player/level-evolve', methods=['POST'])
@login_required
def level_evolve():
    """Manually trigger a level-based evolution check for a team slot."""
    data = request.json or {}
    slot = data.get('slot')

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])

    if slot is None or slot < 0 or slot >= len(team):
        return jsonify({'error': 'Slot inválido'}), 400

    pokemon = team[slot]
    old_name = pokemon.get('name', '')
    evolved, evolved_name = check_and_evolve_pokemon(pokemon)

    if not evolved:
        return jsonify({'evolved': False, 'message': f'{old_name} não atingiu o nível necessário para evoluir ainda.'})

    evolved_base_data = POKEMON_BY_NAME.get(evolved_name.lower(), {})
    new_moves = [m for m in (evolved_base_data.get('startingMoves') or [])
                 if m not in (pokemon.get('moves') or [])]

    team[slot] = evolved
    trainer['team'] = team
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    socketio.emit('pokemon_evolved', {
        'player_id': current_user.id, 'old_name': old_name,
        'new_name': evolved['name'], 'method': 'level'
    }, room=f'master_{_tid()}')

    return jsonify({
        'evolved': True, 'old_name': old_name, 'pokemon': evolved,
        'old_number': pokemon.get('number', 0),
        'new_number': evolved.get('number', 0),
        'new_moves': new_moves
    })


@app.route('/player/team-data')
@login_required
def get_team_data():
    """Return the current player's team (for live refresh after evolution)."""
    users = get_users()
    team = users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
    return jsonify(team)

@app.route('/player/team', methods=['POST'])
@login_required
def update_team():
    """Update player's Pokemon team."""
    data = request.json
    users = get_users()
    if current_user.id in users:
        users[current_user.id]['trainer_data']['team'] = data.get('team', [])
        save_users(users)
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/player/trainer', methods=['POST'])
@login_required
def update_trainer():
    """Update trainer data."""
    data = request.json
    users = get_users()
    if current_user.id in users:
        trainer = users[current_user.id]['trainer_data']
        # Update allowed fields
        allowed_fields = ['name', 'bag', 'badges', 'visited_routes', 'notes',
                         'race', 'background', 'path', 'specializations',
                         'str', 'dex', 'con', 'int', 'wis', 'cha',
                         'hp_max', 'hp_current', 'proficiencies',
                         'money', 'pokeslots', 'max_sr', 'pokedex_seen',
                         'avatar', 'trainerStatPointsUsed']
        for field in allowed_fields:
            if field in data:
                trainer[field] = data[field]
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/player/avatar', methods=['POST'])
@login_required
def upload_avatar():
    """Upload player avatar image."""
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    # Validate file type
    allowed_ext = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        return jsonify({'error': 'Invalid file type'}), 400
    # Save with user-specific name
    filename = f"{current_user.id}{ext}"
    filepath = os.path.join('static', 'uploads', 'avatars', filename)
    file.save(filepath)
    # Update trainer data with avatar path
    users = get_users()
    if current_user.id in users:
        users[current_user.id]['trainer_data']['avatar'] = f"/static/uploads/avatars/{filename}"
        save_users(users)
    return jsonify({'success': True, 'avatar_url': f"/static/uploads/avatars/{filename}"})

# ============================================================
# SHOP / POKÉMART
# ============================================================
SHOP_CATALOG = [
    # Pokébolas
    {'id': 'poke-ball',   'name': 'Pokébola',    'category': 'pokeball', 'price': 200,   'description': 'Pokébola padrão. DC captura base.'},
    {'id': 'great-ball',  'name': 'Super Bola',  'category': 'pokeball', 'price': 600,   'description': '+2 no teste de captura.'},
    {'id': 'ultra-ball',  'name': 'Ultra Bola',  'category': 'pokeball', 'price': 1200,  'description': '+4 no teste de captura.'},
    {'id': 'master-ball', 'name': 'Master Ball', 'category': 'pokeball', 'price': 99999, 'description': 'Captura garantida. Muito raro.'},
    {'id': 'heal-ball',   'name': 'Cura Bola',   'category': 'pokeball', 'price': 300,   'description': 'Cura o Pokémon capturado.'},
    {'id': 'net-ball',    'name': 'Net Bola',     'category': 'pokeball', 'price': 1000,  'description': '+3 em Bug e Water.'},
    # Poções
    {'id': 'potion',        'name': 'Poção',         'category': 'medicine', 'price': 300,  'description': 'Restaura 2d4+2 HP de um Pokémon.'},
    {'id': 'super-potion',  'name': 'Super Poção',   'category': 'medicine', 'price': 700,  'description': 'Restaura 4d4+4 HP de um Pokémon.'},
    {'id': 'hyper-potion',  'name': 'Hiper Poção',   'category': 'medicine', 'price': 1500, 'description': 'Restaura 6d4+12 HP de um Pokémon.'},
    {'id': 'max-potion',    'name': 'Poção Máxima',  'category': 'medicine', 'price': 2500, 'description': 'Restaura todos os HP de um Pokémon.'},
    {'id': 'full-restore',  'name': 'Restauração',   'category': 'medicine', 'price': 3000, 'description': 'Restaura HP e cura condição de status.'},
    {'id': 'antidote',      'name': 'Antídoto',      'category': 'medicine', 'price': 100,  'description': 'Cura envenenamento.'},
    {'id': 'burn-heal',     'name': 'Cura Queimadura','category':'medicine', 'price': 250,  'description': 'Cura queimadura.'},
    {'id': 'ice-heal',      'name': 'Cura Gelo',     'category': 'medicine', 'price': 250,  'description': 'Cura congelamento.'},
    {'id': 'awakening',     'name': 'Despertar',     'category': 'medicine', 'price': 250,  'description': 'Acorda um Pokémon dormindo.'},
    {'id': 'paralyze-heal', 'name': 'Cura Paralisia','category': 'medicine', 'price': 200,  'description': 'Cura paralisia.'},
    {'id': 'full-heal',     'name': 'Cura Total',    'category': 'medicine', 'price': 600,  'description': 'Cura qualquer condição de status.'},
    {'id': 'revive',        'name': 'Reviver',       'category': 'medicine', 'price': 1500, 'description': 'Revive Pokémon desmaiado com metade do HP.'},
    {'id': 'max-revive',    'name': 'Reviver Máx',   'category': 'medicine', 'price': 4000, 'description': 'Revive Pokémon com HP máximo.'},
    {'id': 'ether',         'name': 'Éter',          'category': 'medicine', 'price': 1200, 'description': 'Restaura PP de um golpe (+1 uso).'},
    # Batalha
    {'id': 'x-attack',   'name': 'X Ataque',    'category': 'battle', 'price': 500,  'description': '+2 ATK por 1 batalha.'},
    {'id': 'x-defense',  'name': 'X Defesa',    'category': 'battle', 'price': 550,  'description': '+2 AC por 1 batalha.'},
    {'id': 'x-speed',    'name': 'X Velocidade','category': 'battle', 'price': 350,  'description': '+2 SPE por 1 batalha.'},
    {'id': 'x-sp-atk',   'name': 'X At. Esp.',  'category': 'battle', 'price': 500,  'description': '+2 SPA por 1 batalha.'},
    {'id': 'dire-hit',   'name': 'Acerto Certo','category': 'battle', 'price': 650,  'description': 'Aumenta críticos por 1 batalha.'},
    # Itens de evolução
    {'id': 'fire-stone',    'name': 'Pedra Fogo',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'water-stone',   'name': 'Pedra Água',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'thunder-stone', 'name': 'Pedra Trovão',  'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'leaf-stone',    'name': 'Pedra Folha',   'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'moon-stone',    'name': 'Pedra Lua',     'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'sun-stone',     'name': 'Pedra Solar',   'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'shiny-stone',   'name': 'Pedra Brilhante','category':'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'dusk-stone',    'name': 'Pedra Crepúsculo','category':'evo_stone','price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'dawn-stone',    'name': 'Pedra Aurora',  'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'ice-stone',     'name': 'Pedra Gelo',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    # Itens segurados
    {'id': 'leftovers',   'name': 'Restos',       'category': 'held', 'price': 4000, 'description': 'Cura 1d4 HP no início de cada turno.'},
    {'id': 'choice-band', 'name': 'Faixa Seleção','category': 'held', 'price': 5000, 'description': '+1d6 ATK, mas só pode usar 1 golpe.'},
    {'id': 'life-orb',    'name': 'Orbe Vida',    'category': 'held', 'price': 5000, 'description': '+30% dano, -10% HP por uso.'},
    {'id': 'rocky-helmet','name': 'Capacete Pedra','category':'held', 'price': 3000, 'description': 'Quem ataca corpo a corpo perde 1d6 HP.'},
    # Raros/Especiais
    {'id': 'rare-candy',  'name': 'Bala Rara',    'category': 'special', 'price': 2000, 'description': 'Aumenta 1 nível do Pokémon.'},
    {'id': 'repel',       'name': 'Repelente',    'category': 'special', 'price': 350,  'description': 'Evita encontros por 1 hora.'},
    {'id': 'super-repel', 'name': 'Super Repelente','category':'special','price': 500,  'description': 'Evita encontros por 2 horas.'},
]

@app.route('/api/shop')
@login_required
def api_shop():
    """Return the shop catalog. Master can hide items via game_state."""
    game_state = get_game_state()
    hidden_items = set(game_state.get('shop_hidden_items', []))
    catalog = [item for item in SHOP_CATALOG if item['id'] not in hidden_items]
    return jsonify(catalog)

@app.route('/api/shop/buy', methods=['POST'])
@login_required
def api_shop_buy():
    """Buy an item. Deducts money and adds to player bag."""
    if current_user.role == 'master':
        return jsonify({'error': 'Mestre não pode comprar itens'}), 403
    data = request.json or {}
    item_id = data.get('item_id')
    qty = max(1, int(data.get('qty', 1)))

    item = next((i for i in SHOP_CATALOG if i['id'] == item_id), None)
    if not item:
        return jsonify({'error': 'Item não encontrado'}), 404

    total_cost = item['price'] * qty
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    money = trainer.get('money', 0)
    if money < total_cost:
        return jsonify({'error': f'Sem dinheiro suficiente! Precisa de ₽{total_cost}, tem ₽{money}'}), 400

    trainer['money'] = money - total_cost
    bag = trainer.get('bag', [])
    existing = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item['name'].lower()), None)
    if existing:
        existing['qty'] = existing.get('qty', 1) + qty
    else:
        bag.append({'name': item['name'], 'qty': qty, 'description': item['description']})
    trainer['bag'] = bag
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'success': True, 'money_left': trainer['money'], 'item': item, 'qty': qty})

@app.route('/player/pc/items', methods=['GET'])
@login_required
def get_pc_items():
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    return jsonify(trainer.get('pc_items', []))

@app.route('/player/pc/items/deposit', methods=['POST'])
@login_required
def pc_deposit_item():
    """Move item(s) from bag to PC item storage."""
    data = request.json or {}
    item_name = data.get('item_name', '').strip()
    qty = max(1, int(data.get('qty', 1)))
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])
    pc_items = trainer.get('pc_items', [])

    bag_item = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if not bag_item or bag_item.get('qty', 0) < qty:
        return jsonify({'error': f'Não tem {qty}x {item_name} na bolsa'}), 400

    if sum(i.get('qty', 1) for i in pc_items) + qty > 10000:
        return jsonify({'error': 'PC de itens cheio! (limite 10.000)'}), 400

    bag_item['qty'] = bag_item.get('qty', qty) - qty
    if bag_item['qty'] <= 0:
        bag.remove(bag_item)

    pc_existing = next((b for b in pc_items if b.get('name', '').lower() == item_name.lower()), None)
    if pc_existing:
        pc_existing['qty'] = pc_existing.get('qty', 1) + qty
    else:
        pc_items.append({'name': bag_item.get('name', item_name), 'qty': qty, 'description': bag_item.get('description', '')})

    trainer['bag'] = bag
    trainer['pc_items'] = pc_items
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'bag': bag, 'pc_items': pc_items})

@app.route('/player/pc/items/withdraw', methods=['POST'])
@login_required
def pc_withdraw_item():
    """Move item(s) from PC storage to bag."""
    data = request.json or {}
    item_name = data.get('item_name', '').strip()
    qty = max(1, int(data.get('qty', 1)))
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])
    pc_items = trainer.get('pc_items', [])

    pc_item = next((b for b in pc_items if b.get('name', '').lower() == item_name.lower()), None)
    if not pc_item or pc_item.get('qty', 0) < qty:
        return jsonify({'error': f'Não tem {qty}x {item_name} no PC'}), 400

    pc_item['qty'] = pc_item.get('qty', qty) - qty
    if pc_item['qty'] <= 0:
        pc_items.remove(pc_item)

    bag_existing = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if bag_existing:
        bag_existing['qty'] = bag_existing.get('qty', 1) + qty
    else:
        bag.append({'name': pc_item.get('name', item_name), 'qty': qty, 'description': pc_item.get('description', '')})

    trainer['bag'] = bag
    trainer['pc_items'] = pc_items
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'bag': bag, 'pc_items': pc_items})

@app.route('/api/items')
@login_required
def api_items_list():
    """List available item sprites for the bag system."""
    items_dir = os.path.join('static', 'img', 'items')
    if not os.path.exists(items_dir):
        return jsonify([])
    items = []
    for f in os.listdir(items_dir):
        if f.endswith('.png') and not f.startswith('Bag_'):
            name = f.replace('.png', '').replace('-', ' ').title()
            items.append({'name': name, 'file': f})
    items.sort(key=lambda x: x['name'])
    return jsonify(items)

@app.route('/api/status-effects')
@login_required
def api_status_effects():
    """Get status effects data for the battle system."""
    return jsonify({
        'conditions': {k: {'name': v['name'], 'icon': v['icon'], 'color': v['color'], 'description': v['description']} 
                       for k, v in effects.STATUS_CONDITIONS.items()},
        'move_effects': {k: {'status': v['status'], 'chance': v['chance'], 'on': v['on']} 
                         for k, v in effects.MOVE_STATUS_EFFECTS.items()}
    })

@app.route('/api/pokemon/stats', methods=['POST'])
@login_required
def api_pokemon_scaled_stats():
    """Calculate Pokemon stats at a specific level."""
    data = request.json
    pokemon_number = data.get('number')
    level = int(data.get('level', 1))
    
    nature = data.get('nature', '')
    name   = data.get('name', '')

    base_pokemon = POKEMON_BY_NUMBER.get(pokemon_number)
    if not base_pokemon and name:
        base_pokemon = POKEMON_BY_NAME.get(name.lower())
    if not base_pokemon:
        return jsonify({'error': 'Pokemon not found'}), 404

    stats = scaling.calculate_pokemon_stats(base_pokemon, level, nature or None)
    stats['growth_rate'] = scaling.get_growth_rate(base_pokemon)
    stats['xp_to_next'] = scaling.xp_to_next_level(level, stats['growth_rate'])
    # Include which stat was boosted/lowered for UI display
    nature_mods = scaling.NATURE_MODIFIERS.get(nature, {})
    stats['nature_boost']  = next((s for s, m in nature_mods.items() if m > 1), None)
    stats['nature_lower']  = next((s for s, m in nature_mods.items() if m < 1), None)
    return jsonify(stats)

@app.route('/api/pokemon/battle-xp', methods=['POST'])
@login_required
def api_battle_xp():
    """Calculate XP reward for a battle result.
    Formula: loser_level x multiplier (2=wild, 3=official, 4=street, 5=gym)"""
    data = request.json
    winner_level = int(data.get('winner_level', 1))
    loser_level = int(data.get('loser_level', 1))
    battle_type = data.get('battle_type', 'wild')  # wild, official, street, gym_leader
    
    xp = scaling.battle_xp_reward(winner_level, loser_level, battle_type)
    xp_to_next = scaling.xp_to_next_level(winner_level)
    return jsonify({'xp_gained': xp, 'xp_to_next': xp_to_next})

@app.route('/api/pokemon/level-check', methods=['POST'])
@login_required  
def api_level_check():
    """Check if trainer can control a Pokemon at given level."""
    data = request.json
    trainer_level = int(data.get('trainer_level', 1))
    pokemon_level = int(data.get('pokemon_level', 1))
    
    can_control = scaling.can_control_pokemon(trainer_level, pokemon_level)
    max_level = scaling.max_pokemon_level(trainer_level)
    return jsonify({
        'can_control': can_control,
        'max_pokemon_level': max_level,
        'trainer_level': trainer_level
    })

@app.route('/api/pokemon/damage-dice', methods=['POST'])
@login_required
def api_damage_dice():
    """Get scaled damage dice for a move at a Pokemon level."""
    data = request.json
    base_damage = data.get('base_damage', '1d6')
    level = int(data.get('level', 1))
    higher_levels = data.get('higher_levels', '')
    
    scaled = scaling.get_scaled_damage_dice(base_damage, level, higher_levels)
    return jsonify({'scaled_dice': scaled, 'base_dice': base_damage, 'level': level})

@app.route('/api/check-status', methods=['POST'])
@login_required
def api_check_status():
    """Check if a move inflicts status and process turn-start effects.
    Used by the battle frontend for real-time status processing."""
    data = request.json
    action = data.get('action')  # 'check_hit' or 'turn_start'
    
    if action == 'check_hit':
        move_name = data.get('move_name', '')
        attack_roll = int(data.get('attack_roll', 10))
        damage_dealt = int(data.get('damage', 0))
        status_key, inflicted = effects.check_status_on_hit(move_name, attack_roll, damage_dealt)
        if inflicted:
            condition = effects.STATUS_CONDITIONS.get(status_key, {})
            return jsonify({
                'inflicted': True,
                'status': status_key,
                'name': condition.get('name', ''),
                'icon': condition.get('icon', ''),
                'description': condition.get('description', '')
            })
        return jsonify({'inflicted': False})
    
    elif action == 'turn_start':
        pokemon_status = data.get('pokemon_status')  # {condition: 'badly_poisoned', turns_active: 2}
        max_hp = int(data.get('max_hp', 20))
        ability = (data.get('ability', '') or '').strip().lower()

        can_act, damage, messages, removed = effects.process_turn_start(pokemon_status, max_hp)

        # Passive ability overrides
        passive = ab.get_passive(ability) if ability else None
        ability_msgs = []

        if passive == 'no_indirect' and damage > 0:
            damage = 0
            ability_msgs.append(f'✨ Magia Guarda: dano de status bloqueado!')

        elif passive == 'heal_poison' and pokemon_status and pokemon_status.get('condition') == 'badly_poisoned':
            # Instead of taking damage, heal that amount
            heal = damage
            damage = -heal  # negative = heal signal
            ability_msgs.append(f'💚 Cura Venenosa: recuperou {heal} HP do veneno!')

        elif passive == 'speed_up_turn':
            ability_msgs.append('⚡ Impulso: SPE aumentou!')

        elif passive == 'cure_on_switch':
            # Handled client-side on switch
            pass

        elif passive == 'heal_on_switch':
            pass  # Handled client-side on switch

        if pokemon_status and not removed:
            # Shed Skin: 33% chance to cure status
            if passive == 'shed_skin_passive' or ability == 'shed skin':
                import random as _r
                if _r.random() < 0.33:
                    removed = True
                    ability_msgs.append('🐍 Muda de Pele: status curado!')

        if ability_msgs:
            messages = messages + ability_msgs

        return jsonify({
            'can_act': can_act,
            'damage': damage,
            'messages': messages,
            'status_removed': removed,
            'turns_active': pokemon_status.get('turns_active', 1) if pokemon_status else 1,
            'ability_messages': ability_msgs,
        })
    
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/process-status-move', methods=['POST'])
@login_required
def api_process_status_move():
    """Process a status move - auto-detects effect from move description.
    Handles ALL status moves by parsing their descriptions."""
    data = request.json
    move_name = data.get('move_name', '')
    attacker_stats = data.get('attacker_stats', {})
    target_stats = data.get('target_stats', {})
    
    # Get move data from database
    move_data = MOVES_DB.get(move_name) or MOVES_BY_NAME.get(move_name.lower())
    if not move_data:
        return jsonify({'success': False, 'message': f'Move {move_name} não encontrado'})
    
    result = effects.process_status_move(move_data, attacker_stats, target_stats)
    return jsonify(result)

@app.route('/player/pokedex/register', methods=['POST'])
@login_required
def register_pokedex():
    """Register a Pokemon in the player's Pokedex and award XP."""
    data = request.json
    pokemon_number = data.get('pokemon_number')
    
    users = get_users()
    if current_user.id in users:
        trainer = users[current_user.id]['trainer_data']
        pokedex_seen = trainer.get('pokedex_seen', [])
        
        if pokemon_number not in pokedex_seen:
            pokedex_seen.append(pokemon_number)
            trainer['pokedex_seen'] = pokedex_seen
            
            # Award 10 XP per new Pokemon registered
            xp_reward = 10
            trainer['xp'] = trainer.get('xp', 0) + xp_reward
            
            # Level up check
            xp_table = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500,
                        5500, 6600, 7800, 9100, 10500, 12000, 13600, 15300, 17100, 19000]
            new_level = 1
            for i, threshold in enumerate(xp_table):
                if trainer['xp'] >= threshold:
                    new_level = i + 1
            old_level = trainer.get('level', 1)
            trainer['level'] = new_level
            trainer['xp_to_next'] = xp_table[min(new_level, len(xp_table)-1)] if new_level < len(xp_table) else 99999
            
            users[current_user.id]['trainer_data'] = trainer
            save_users(users)
            
            socketio.emit('xp_update', {
                'player_id': current_user.id,
                'xp': trainer['xp'],
                'level': trainer['level'],
                'xp_to_next': trainer['xp_to_next'],
                'leveled_up': new_level > old_level
            }, room=current_user.id)
            
            return jsonify({'success': True, 'xp_gained': xp_reward, 'total_seen': len(pokedex_seen)})
        
        return jsonify({'success': True, 'already_registered': True, 'total_seen': len(pokedex_seen)})
    return jsonify({'error': 'User not found'}), 404

# ============================================================
# SOCKET.IO EVENTS
# ============================================================
# Global auto-mode flag (master controls)
WILD_AUTO_MODE = True

@socketio.on('set_auto_mode')
def handle_set_auto_mode(data):
    global WILD_AUTO_MODE
    if current_user.is_authenticated and current_user.role == 'master':
        WILD_AUTO_MODE = data.get('enabled', True)
        print(f"[AUTO MODE] {'ON' if WILD_AUTO_MODE else 'OFF'}")

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        tid = _tid()
        join_room(current_user.id)
        if current_user.role == 'master':
            join_room(f'master_{tid}')
        else:
            join_room(f'players_{tid}')
        print(f"[CONNECTED] {current_user.username} ({current_user.role}) table={tid}")

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        leave_room(current_user.id)
        print(f"[DISCONNECTED] {current_user.username}")

@socketio.on('start_encounter')
def handle_encounter(data):
    """Player starts a wild encounter - notify master with full battle data."""
    if current_user.is_authenticated:
        users = get_users()
        trainer = users.get(current_user.id, {}).get('trainer_data', {})
        team = trainer.get('team', [])
        
        # Find the player's active pokemon
        player_pokemon_idx = data.get('player_pokemon_idx', 0)
        player_pokemon = team[player_pokemon_idx] if player_pokemon_idx < len(team) else None
        
        encounter_data = {
            'player_id': current_user.id,
            'player_name': current_user.username,
            'pokemon': data.get('pokemon'),
            'level': data.get('level'),
            'is_shiny': data.get('is_shiny', False),
            'route_id': data.get('route_id'),
            'wild_moves': data.get('wild_moves', []),
            'player_pokemon': player_pokemon,
            'player_pokemon_name': data.get('player_pokemon'),
            'battle_state': {
                'turn': None,  # 'player' or 'wild'
                'round': 0,
                'wild_hp_current': data.get('pokemon', {}).get('hp', 20),
                'wild_hp_max': data.get('pokemon', {}).get('hp', 20),
                'player_hp_current': player_pokemon.get('currentHp', 20) if player_pokemon else 20,
                'player_hp_max': player_pokemon.get('maxHp', 20) if player_pokemon else 20,
                'wild_status': None,
                'player_status': None,
                'initiative_rolled': False
            }
        }
        # Save to game state — use str key so JSON roundtrip doesn't change it
        pid = str(current_user.id)
        encounter_data['player_id'] = pid
        game_state = get_game_state()
        game_state['active_encounters'][pid] = encounter_data
        save_game_state(game_state)

        # Notify master
        emit('encounter_started', encounter_data, room=f'master_{_tid()}')

        # Auto-roll initiative if AUTO mode is ON
        if WILD_AUTO_MODE:
            _auto_roll_initiative(pid, game_state)

@socketio.on('roll_initiative')
def handle_initiative(data):
    """Roll initiative for battle - determines who goes first.
    Can be triggered by master OR player (auto mode)."""
    if not current_user.is_authenticated:
        return
    
    # Determine player_id: if master triggers, use data; if player triggers, use own id
    if current_user.role == 'master':
        player_id = str(data.get('player_id', ''))
    else:
        player_id = str(current_user.id)

    if not player_id:
        player_id = str(current_user.id)

    game_state = get_game_state()
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter:
        return
    
    # Don't re-roll if already rolled
    if encounter.get('battle_state', {}).get('initiative_rolled'):
        return
    
    wild_pokemon = encounter['pokemon']
    player_pokemon = encounter.get('player_pokemon') or {}
    
    # Initiative = d20 + Speed/DEX modifier (support both stat formats)
    wild_stats = wild_pokemon.get('stats', {})
    wild_dex = wild_stats.get('DEX', wild_stats.get('SPE', 10))
    wild_mod = (wild_dex - 10) // 2
    
    player_stats = player_pokemon.get('stats', {}) if player_pokemon else {}
    player_dex = player_stats.get('DEX', player_stats.get('SPE', 10))
    player_mod = (player_dex - 10) // 2
    
    wild_init = random.randint(1, 20) + wild_mod
    player_init = random.randint(1, 20) + player_mod
    
    first_turn = 'player' if player_init >= wild_init else 'wild'
    
    encounter['battle_state']['initiative_rolled'] = True
    encounter['battle_state']['turn'] = first_turn
    encounter['battle_state']['round'] = 1
    encounter['battle_state']['wild_initiative'] = wild_init
    encounter['battle_state']['player_initiative'] = player_init
    
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    
    # Check on-enter abilities for both combatants
    on_enter_msgs = []
    wild_ability = wild_pokemon.get('ability', '') or ''
    player_ability = player_pokemon.get('ability', '') or ''
    wild_name = wild_pokemon.get('name', 'Selvagem')
    player_name = player_pokemon.get('nickname') or player_pokemon.get('name', 'Pokémon')

    for ability_str, poke_name in [(wild_ability, wild_name), (player_ability, player_name)]:
        entry = ab.check_on_enter(ability_str, poke_name)
        if entry:
            on_enter_msgs.append(entry['message'])
            # Apply Intimidate: lower opponent ATK (stored in battle_state for client)
            if entry.get('stat') == 'ATK' and entry.get('mod', 0) < 0:
                if poke_name == wild_name:
                    encounter['battle_state']['player_atk_mod'] = encounter['battle_state'].get('player_atk_mod', 0) + entry['mod']
                else:
                    encounter['battle_state']['wild_atk_mod'] = encounter['battle_state'].get('wild_atk_mod', 0) + entry['mod']
            # Weather abilities set the field
            if entry.get('weather'):
                encounter['battle_state']['weather'] = entry['weather']

    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)

    result = {
        'player_id': player_id,
        'wild_initiative': wild_init,
        'wild_mod': wild_mod,
        'player_initiative': player_init,
        'player_mod': player_mod,
        'first_turn': first_turn,
        'on_enter_abilities': on_enter_msgs,
        'weather': encounter['battle_state'].get('weather'),
    }

    emit('initiative_result', result, room=f'master_{_tid()}')
    emit('initiative_result', result, room=player_id)

@socketio.on('battle_action')
def handle_battle_action(data):
    """Handle a battle action (attack, status move, etc.)."""
    if current_user.is_authenticated:
        player_id = str(data.get('player_id', current_user.id))
        action_by = data.get('action_by')  # 'player' or 'master' (for wild pokemon)
        action_type = data.get('action_type')  # 'attack', 'status', 'item'
        move_name = data.get('move_name', '')
        move_type = data.get('move_type', '')   # e.g. 'fire', 'ground'
        damage = data.get('damage', 0)
        heal = data.get('heal', 0)
        status_effect = data.get('status_effect', None)
        message = data.get('message', '')
        # Pre-turn status damage (applied before this action, doesn't switch turn)
        wild_status_damage = data.get('wild_status_damage', 0)
        player_status_damage = data.get('player_status_damage', 0)
        
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        battle_state = encounter['battle_state']
        
        # Apply pre-turn status damage first (doesn't count as an action)
        PERMADEATH_FLOOR = -30
        if wild_status_damage > 0:
            battle_state['wild_hp_current'] = max(PERMADEATH_FLOOR, battle_state['wild_hp_current'] - wild_status_damage)
        if player_status_damage > 0:
            battle_state['player_hp_current'] = max(PERMADEATH_FLOOR, battle_state['player_hp_current'] - player_status_damage)
        
        # Check defender ability before applying damage
        ability_result = None
        if damage > 0 and move_type and action_type == 'attack':
            if action_by == 'player':
                # Player attacks wild — check wild's ability
                wild_ability = encounter.get('pokemon', {}).get('ability', '') or ''
                if wild_ability:
                    ability_result = ab.check_defender_ability(
                        wild_ability, move_type, damage,
                        battle_state['wild_hp_current'], battle_state['wild_hp_max']
                    )
                    if ability_result['triggered']:
                        damage = ability_result['modified_damage']
                        if ability_result['heal']:
                            battle_state['wild_hp_current'] = min(battle_state['wild_hp_max'], battle_state['wild_hp_current'] + ability_result['heal'])
            elif action_by == 'master':
                # Wild/NPC attacks player — check player pokemon's ability
                users = get_users()
                trainer = users.get(player_id, {}).get('trainer_data', {})
                team = trainer.get('team', [])
                player_poke = team[0] if team else {}
                player_ability = player_poke.get('ability', '') or ''
                if player_ability:
                    ability_result = ab.check_defender_ability(
                        player_ability, move_type, damage,
                        battle_state['player_hp_current'], battle_state['player_hp_max']
                    )
                    if ability_result['triggered']:
                        damage = ability_result['modified_damage']
                        if ability_result['heal']:
                            battle_state['player_hp_current'] = min(battle_state['player_hp_max'], battle_state['player_hp_current'] + ability_result['heal'])

        # Handle switch: reset player HP to new pokemon's HP
        if action_type == 'switch' and action_by == 'player':
            new_hp     = int(data.get('new_pokemon_hp', 0))
            new_max_hp = int(data.get('new_pokemon_max_hp', new_hp or 20))
            if new_hp > 0:
                battle_state['player_hp_current'] = new_hp
                battle_state['player_hp_max'] = new_max_hp

        # Apply damage — allow negative down to -30 for permadeath detection
        PERMADEATH_FLOOR = -30
        if action_by == 'player' and damage > 0:
            battle_state['wild_hp_current'] = max(PERMADEATH_FLOOR, battle_state['wild_hp_current'] - damage)
        elif action_by == 'master' and damage > 0:
            battle_state['player_hp_current'] = max(PERMADEATH_FLOOR, battle_state['player_hp_current'] - damage)
        
        # Apply healing
        if action_by == 'player' and heal > 0:
            battle_state['player_hp_current'] = min(battle_state['player_hp_max'], battle_state['player_hp_current'] + heal)
        elif action_by == 'master' and heal > 0:
            battle_state['wild_hp_current'] = min(battle_state['wild_hp_max'], battle_state['wild_hp_current'] + heal)
        
        # Apply status (store as dict so process_turn_start can read .get('condition'))
        if status_effect:
            status_dict = status_effect if isinstance(status_effect, dict) else {'condition': status_effect, 'turns_active': 0}
            if action_by == 'player':
                if not battle_state.get('wild_status'):
                    battle_state['wild_status'] = status_dict
            else:
                if not battle_state.get('player_status'):
                    battle_state['player_status'] = status_dict
        
        # Switch turn
        battle_state['turn'] = 'wild' if battle_state['turn'] == 'player' else 'player'
        if battle_state['turn'] == 'player':
            battle_state['round'] += 1
        
        encounter['battle_state'] = battle_state
        game_state['active_encounters'][player_id] = encounter
        save_game_state(game_state)
        
        # Build action result
        action_result = {
            'player_id': player_id,
            'action_by': action_by,
            'action_type': action_type,
            'move_name': move_name,
            'damage': damage,
            'heal': heal,
            'status_effect': status_effect,
            'message': message,
            'battle_state': battle_state,
            'ability_trigger': ability_result if (ability_result and ability_result.get('triggered')) else None,
        }
        
        # Notify both sides
        emit('battle_update', action_result, room=f'master_{_tid()}')
        emit('battle_update', action_result, room=player_id)
        
        # Wild auto-attack is handled client-side (player.js wildPokemonAutoAttack) to support
        # status damage, move variety, and status moves. Server-side auto-attack removed to
        # prevent race condition: server used stale encounter state and overwrote correct HP.

def _auto_roll_initiative(player_id, game_state):
    """Auto-roll initiative when AUTO mode is ON."""
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter or encounter.get('battle_state', {}).get('initiative_rolled'):
        return
    
    wild_pokemon = encounter['pokemon']
    player_pokemon = encounter.get('player_pokemon') or {}
    
    wild_stats = wild_pokemon.get('stats', {})
    wild_dex = wild_stats.get('DEX', wild_stats.get('SPE', 10))
    wild_mod = (wild_dex - 10) // 2
    
    player_stats = player_pokemon.get('stats', {}) if player_pokemon else {}
    player_dex = player_stats.get('DEX', player_stats.get('SPE', 10))
    player_mod = (player_dex - 10) // 2
    
    wild_init = random.randint(1, 20) + wild_mod
    player_init = random.randint(1, 20) + player_mod
    first_turn = 'player' if player_init >= wild_init else 'wild'
    
    encounter['battle_state']['initiative_rolled'] = True
    encounter['battle_state']['turn'] = first_turn
    encounter['battle_state']['round'] = 1
    encounter['battle_state']['wild_initiative'] = wild_init
    encounter['battle_state']['player_initiative'] = player_init
    
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    
    result = {
        'player_id': player_id,
        'wild_initiative': wild_init,
        'wild_mod': wild_mod,
        'player_initiative': player_init,
        'player_mod': player_mod,
        'first_turn': first_turn,
        'on_enter_abilities': [],
        'weather': None,
    }
    
    socketio.emit('initiative_result', result, room=f'master_{_tid()}')
    socketio.emit('initiative_result', result, room=player_id)
    
    # Wild auto-attack when wild goes first is handled client-side via initiative_result handler.

def _wild_auto_attack(player_id, encounter, game_state):
    """Wild pokemon automatically attacks the player's pokemon."""
    wild_pokemon = encounter['pokemon']
    battle_state = encounter['battle_state']
    wild_moves = encounter.get('wild_moves', wild_pokemon.get('startingMoves', ['Tackle'])[:4])
    
    if not wild_moves:
        wild_moves = ['Tackle']
    
    # Choose random move
    move_name = random.choice(wild_moves)
    move_data = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name) or {}
    
    # Calculate attack
    wild_stats = wild_pokemon.get('stats', {})
    wild_level = encounter.get('level', 5)
    
    # Determine MOVE modifier
    power = (move_data.get('power', 'FOR') or 'FOR').upper()
    move_mod = 0
    stat_map = {'FOR': 'STR', 'DES': 'DEX', 'INT': 'INT', 'SAB': 'WIS', 'CAR': 'CHA', 'CON': 'CON'}
    for abbr, stat_key in stat_map.items():
        if abbr in power:
            val = wild_stats.get(stat_key, 10)
            move_mod = max(move_mod, (val - 10) // 2)
    
    # Proficiency
    prof = 2 if wild_level < 5 else (3 if wild_level < 9 else (4 if wild_level < 13 else (5 if wild_level < 17 else 6)))
    
    # Roll d20
    attack_roll = random.randint(1, 20)
    total_attack = attack_roll + move_mod + prof
    is_crit = attack_roll == 20
    is_miss = attack_roll == 1
    
    # Target AC
    player_pokemon = encounter.get('player_pokemon', {})
    target_ac = player_pokemon.get('ac', 13) if player_pokemon else 13
    
    damage = 0
    message = ''
    
    if is_miss:
        message = f'Nat 1 - Falha!'
    elif total_attack >= target_ac or is_crit:
        # Roll damage
        base_damage = move_data.get('baseDamage', '1d6')
        if base_damage:
            match = __import__('re').match(r'(\d+)d(\d+)', base_damage)
            if match:
                count, sides = int(match.group(1)), int(match.group(2))
                for _ in range(count):
                    damage += random.randint(1, sides)
                if is_crit:
                    for _ in range(count):
                        damage += random.randint(1, sides)
        damage += move_mod
        
        # STAB
        wild_types = [t.lower() for t in wild_pokemon.get('types', [])]
        move_type = (move_data.get('type', '') or '').lower()
        stab_table = [0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5]
        stab = stab_table[min(wild_level, 20)] if move_type in wild_types else 0
        damage += stab
        
        # Type effectiveness
        player_vulns = [v.lower() for v in (player_pokemon.get('vulnerabilities') or [])]
        player_resists = [r.lower() for r in (player_pokemon.get('resistances') or [])]
        player_immunes = [i.lower() for i in (player_pokemon.get('immunities') or [])]
        
        effectiveness = 1
        if move_type in player_immunes:
            effectiveness = 0
        else:
            if move_type in player_vulns: effectiveness *= 2
            if move_type in player_resists: effectiveness *= 0.5
        
        damage = int(damage * effectiveness)
        if damage < 1 and effectiveness > 0: damage = 1
        
        eff_label = ''
        if effectiveness == 0: eff_label = ' ⛔ IMUNE'
        elif effectiveness > 1: eff_label = f' ⚡ Super Efetivo (x{effectiveness})'
        elif effectiveness < 1: eff_label = f' 🛡️ Não Efetivo (x{effectiveness})'
        
        message = f'd20({attack_roll})+MOD({move_mod})+Prof({prof})={total_attack} vs AC {target_ac} → {damage} dano{eff_label}{"💥 CRIT" if is_crit else ""}'
    else:
        message = f'Errou ({total_attack} vs AC {target_ac})'
    
    # Apply damage
    battle_state['player_hp_current'] = max(0, battle_state['player_hp_current'] - damage)
    
    # Switch turn back to player
    battle_state['turn'] = 'player'
    battle_state['round'] += 1
    
    encounter['battle_state'] = battle_state
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    
    action_result = {
        'player_id': player_id,
        'action_by': 'wild',
        'action_type': 'attack',
        'move_name': move_name,
        'damage': damage,
        'message': message,
        'battle_state': battle_state
    }
    
    socketio.emit('battle_update', action_result, room=f'master_{_tid()}')
    socketio.emit('battle_update', action_result, room=player_id)

@socketio.on('apply_wild_status')
def handle_apply_wild_status(data):
    """Apply status to wild pokemon without switching turn (follow-up after on-hit status)."""
    if not current_user.is_authenticated:
        return
    player_id = str(current_user.id)
    status = data.get('status')
    if not status:
        return
    game_state = get_game_state()
    encounter = game_state['active_encounters'].get(player_id)
    if not encounter:
        return
    battle_state = encounter['battle_state']
    if not battle_state.get('wild_status'):
        status_dict = status if isinstance(status, dict) else {'condition': status, 'turns_active': 0}
        battle_state['wild_status'] = status_dict
        encounter['battle_state'] = battle_state
        game_state['active_encounters'][player_id] = encounter
        save_game_state(game_state)
        emit('wild_status_applied', {'status': status, 'player_id': player_id}, room=f'master_{_tid()}')

@socketio.on('end_encounter')
def handle_end_encounter(data):
    """End an encounter."""
    if current_user.is_authenticated:
        game_state = get_game_state()
        player_id = str(data.get('player_id', current_user.id))
        result = data.get('result', '')

        # Track battle_wins on active Pokémon when player wins
        if result == 'defeated':
            users = get_users()
            trainer = users.get(player_id, {}).get('trainer_data', {})
            active_poke_name = data.get('active_pokemon_name')
            if active_poke_name:
                for poke in trainer.get('team', []):
                    if poke.get('name') == active_poke_name or poke.get('nickname') == active_poke_name:
                        poke['battle_wins'] = poke.get('battle_wins', 0) + 1
                        break
                users[player_id]['trainer_data'] = trainer
                save_users(users)

        if player_id in game_state['active_encounters']:
            del game_state['active_encounters'][player_id]
            save_game_state(game_state)
        emit('encounter_ended', {'player_id': player_id, 'result': result}, room=f'master_{_tid()}')
        emit('encounter_ended', {'player_id': player_id, 'result': result}, room=player_id)

@socketio.on('master_action')
def handle_master_action(data):
    """Master sends an action to a player (e.g., battle command, mega wild)."""
    if current_user.is_authenticated and current_user.role == 'master':
        target_player = data.get('player_id')
        emit('master_action', data, room=target_player)

@socketio.on('mega_evolve')
def handle_mega_evolve(data):
    """Handle mega evolution in battle."""
    if current_user.is_authenticated:
        player_id = str(data.get('player_id', current_user.id))
        side = data.get('side', 'player')  # 'player' or 'wild'
        stone_name = data.get('stone_name', '')
        
        stone_data = MEGA_DB.get(stone_name, {})
        if not stone_data:
            return
        
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        bonuses = stone_data.get('bonuses', {})
        
        result = {
            'player_id': player_id,
            'side': side,
            'stone_name': stone_name,
            'mega_name': stone_data.get('megaName', ''),
            'ability': stone_data.get('ability', ''),
            'new_types': stone_data.get('newTypes'),
            'bonuses': bonuses
        }
        
        # Apply AC bonus to battle state
        if side == 'wild' and 'ac' in bonuses:
            # Boost wild pokemon AC in encounter
            pass  # Frontend handles display
        
        emit('mega_evolved', result, room=f'master_{_tid()}')
        emit('mega_evolved', result, room=player_id)

# ============================================================
# PVP ARENA
# ============================================================
# In-memory PVP battles (active battles stored here for speed)
ACTIVE_PVP = {}  # battle_id -> battle state
ACTIVE_TOURNAMENTS = {}  # tournament_id -> tournament state

@socketio.on('pvp_join_arena')
def handle_pvp_join(data):
    """Player enters the PVP arena."""
    if current_user.is_authenticated:
        join_room('pvp_arena')
        users = get_users()
        players_list = []
        for uid, u in users.items():
            if u['role'] == 'player':
                trainer = u.get('trainer_data', {})
                players_list.append({
                    'id': uid,
                    'name': trainer.get('name', u['username']),
                    'level': trainer.get('level', 1),
                    'team_size': len(trainer.get('team', []))
                })
        emit('pvp_arena_players', players_list)
        emit('pvp_player_joined', {
            'id': current_user.id,
            'name': current_user.username
        }, room='pvp_arena', include_self=False)

@socketio.on('master_pvp_challenge')
@login_required
def handle_master_pvp_challenge(data):
    """Master sends an NPC to challenge a player (or battle another NPC)."""
    if current_user.role != 'master':
        return
    npc_id    = data.get('npc_id')
    target_id = data.get('target_id')
    mode      = data.get('mode', 'official')

    npcs  = db.get_npcs()
    npc   = next((n for n in npcs if n['id'] == npc_id), None)
    if not npc:
        emit('master_error', {'msg': 'NPC não encontrado'})
        return

    users = get_users()
    target_is_npc = target_id not in users
    if target_is_npc:
        target_npc = next((n for n in npcs if n['id'] == target_id), None)
        if not target_npc:
            emit('master_error', {'msg': 'Alvo não encontrado'})
            return
        target_team = target_npc.get('team', [])
        target_name = target_npc.get('name', target_id)
    else:
        target_trainer = users[target_id].get('trainer_data', {})
        target_team    = target_trainer.get('team', [])
        target_name    = target_trainer.get('name', users[target_id]['username'])

    battle = pvp.create_pvp_battle(mode, npc_id, target_id)
    battle['extra'] = {'initiated_by_master': True}
    pvp.set_team(battle, 'player1', npc.get('team', []))
    pvp.set_team(battle, 'player2', target_team)
    battle['player1']['is_npc'] = True
    if npc.get('team'):
        pvp.select_pokemon(battle, 'player1', 0)
    if target_is_npc:
        battle['player2']['is_npc'] = True
        if target_team:
            pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle
    _emit_pvp_to_master(battle, 'created')

    if not target_is_npc:
        socketio.emit('pvp_battle_created', {
            'battle_id':     battle['id'],
            'opponent_name': npc.get('name', 'NPC'),
            'mode':          mode,
            'your_team':     target_team,
            'you_are':       'player2',
            'phase':         'selection'
        }, room=target_id)

    emit('master_pvp_created', {'battle_id': battle['id'], 'npc': npc.get('name'), 'target': target_name})


@socketio.on('pvp_challenge')
def handle_pvp_challenge(data):
    """Send a PVP challenge with mode and optional bet."""
    if current_user.is_authenticated:
        target_id = data.get('target_id')
        mode = data.get('mode', 'street')  # official, street
        bet_money = int(data.get('bet_money', 0))
        bet_items = data.get('bet_items', [])
        
        emit('pvp_challenge_received', {
            'challenger_id': current_user.id,
            'challenger_name': current_user.username,
            'challenger_level': current_user.trainer_data.get('level', 1) if current_user.trainer_data else 1,
            'mode': mode,
            'bet_money': bet_money,
            'bet_items': bet_items
        }, room=target_id)
        emit('pvp_challenge_sent', {
            'challenger': current_user.username,
            'target_id': target_id,
            'mode': mode
        }, room=f'master_{_tid()}')

@socketio.on('pvp_accept')
def handle_pvp_accept(data):
    """Accept a PVP challenge - create battle."""
    if current_user.is_authenticated:
        challenger_id = data.get('challenger_id')
        mode = data.get('mode', 'street')
        bet_money = int(data.get('bet_money', 0))
        bet_items = data.get('bet_items', [])
        
        # Create battle
        bets = {
            'player1': {'money': bet_money, 'items': bet_items},
            'player2': {'money': bet_money, 'items': bet_items}
        }
        battle = pvp.create_pvp_battle(mode, challenger_id, current_user.id, bets)
        
        # Set teams from trainer data
        users = get_users()
        p1_team = users.get(challenger_id, {}).get('trainer_data', {}).get('team', [])
        p2_team = users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
        pvp.set_team(battle, 'player1', p1_team)
        pvp.set_team(battle, 'player2', p2_team)
        
        ACTIVE_PVP[battle['id']] = battle
        
        # Notify both - send to selection phase
        emit('pvp_battle_created', {
            'battle_id': battle['id'],
            'mode': mode,
            'opponent_name': current_user.username,
            'your_team': p1_team,
            'you_are': 'player1',
            'phase': 'selection'
        }, room=challenger_id)
        emit('pvp_battle_created', {
            'battle_id': battle['id'],
            'mode': mode,
            'opponent_name': data.get('challenger_name', '???'),
            'your_team': p2_team,
            'you_are': 'player2',
            'phase': 'selection'
        }, room=current_user.id)
        emit('pvp_battle_started', {
            'battle_id': battle['id'],
            'player1': data.get('challenger_name', '???'),
            'player2': current_user.username,
            'mode': mode
        }, room=f'master_{_tid()}')

@socketio.on('pvp_decline')
def handle_pvp_decline(data):
    if current_user.is_authenticated:
        emit('pvp_challenge_declined', {
            'decliner_name': current_user.username
        }, room=data.get('challenger_id'))

@socketio.on('pvp_select_pokemon')
def handle_pvp_select(data):
    """Player selects starting pokemon (blind selection)."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        pokemon_idx = int(data.get('pokemon_idx', 0))
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        
        # Determine which player this is
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        
        success, result = pvp.select_pokemon(battle, player_key, pokemon_idx)

        # If the opponent is an NPC and hasn't selected yet, auto-select for them
        opponent_key = 'player2' if player_key == 'player1' else 'player1'
        if result == 'waiting_opponent' and battle[opponent_key].get('is_npc'):
            opp = battle[opponent_key]
            opp_team = opp.get('team') or []
            if not opp_team:
                # NPC has no team — create a minimal fallback so battle can proceed
                opp_team = [{'name': 'Rattata', 'number': 19, 'level': 5,
                              'currentHp': 20, 'maxHp': 20, 'ac': 11,
                              'types': ['Normal'], 'moves': ['Tackle'], 'stats': {}}]
                opp['team'] = opp_team
            # Force mark NPC ready directly if select_pokemon fails (e.g. index out of range)
            if not opp.get('ready'):
                s2, result = pvp.select_pokemon(battle, opponent_key, 0)
                if not s2:
                    # Manually mark ready as last resort
                    opp['active_idx'] = 0
                    opp['ready'] = True
                    opp['used_pokemon'] = [0]
                    if battle['player1']['ready'] and battle['player2']['ready']:
                        import random as _r
                        battle['phase'] = 'battle'
                        battle['round'] = 1
                        i1 = _r.randint(1, 20)
                        i2 = _r.randint(1, 20)
                        battle['turn'] = 'player1' if i1 >= i2 else 'player2'
                        result = 'battle_start'

        if result == 'battle_start':
            # Send state to human player(s) only; skip NPC rooms
            p1_is_npc = battle['player1'].get('is_npc', False)
            p2_is_npc = battle['player2'].get('is_npc', False)
            p1_state = pvp.get_battle_state_for_player(battle, 'player1')
            p2_state = pvp.get_battle_state_for_player(battle, 'player2')
            if not p1_is_npc:
                emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
            if not p2_is_npc:
                emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
            _emit_pvp_to_master(battle, 'battle_started')
            # If it's the NPC's turn first, trigger their turn immediately
            first_turn_key = battle.get('turn')
            if first_turn_key and battle[first_turn_key].get('is_npc'):
                handle_npc_turn(battle, first_turn_key)
        elif result == 'waiting_opponent':
            emit('pvp_waiting', {'message': 'Aguardando oponente escolher Pokémon...'})

@socketio.on('pvp_attack')
def handle_pvp_attack(data):
    """Player attacks in PVP battle."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        move_name = data.get('move_name', '')
        damage = int(data.get('damage', 0))
        move_type = (data.get('move_type', '') or '').lower()
        status_effect = data.get('status_effect')
        message = data.get('message', '')

        battle = ACTIVE_PVP.get(battle_id)
        if not battle or battle['phase'] != 'battle':
            return

        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        defender_key = 'player2' if player_key == 'player1' else 'player1'

        # Validate it's this player's turn
        if battle['turn'] != player_key:
            emit('pvp_error', {'message': 'Não é seu turno!'})
            return

        # Process attacker's own status damage before acting
        status_dmg, status_info = pvp.process_turn_status(battle, player_key)
        ability_trigger = None

        # Check defender ability
        if damage > 0 and move_type:
            defender = battle[defender_key]
            def_active = defender['team'][defender['active_idx']]
            def_ability = (def_active.get('ability') or '').lower()
            if def_ability:
                ar = ab.check_defender_ability(
                    def_ability, move_type, damage,
                    max(0, def_active.get('currentHp', 0)), def_active.get('maxHp', 20)
                )
                if ar['triggered']:
                    damage = ar['modified_damage']
                    if ar['heal']:
                        def_active['currentHp'] = min(def_active.get('maxHp', 20),
                                                      def_active.get('currentHp', 0) + ar['heal'])
                    ability_trigger = ar

        # Apply damage
        result = pvp.apply_damage(battle, player_key, damage, move_name, message)

        # Apply status effect to defender if move has one
        status_applied = False
        if status_effect and result not in ('battle_end',):
            status_applied = pvp.apply_status(battle, defender_key, status_effect)
        
        # Auto-check move status effects if client didn't send one
        if not status_applied and damage > 0 and move_name and result not in ('battle_end',):
            move_effect = effects.MOVE_STATUS_EFFECTS.get(move_name)
            if move_effect and move_effect.get('on') == 'hit':
                import random as rng
                if rng.random() < move_effect.get('chance', 0):
                    auto_status = {'condition': move_effect['status']}
                    status_applied = pvp.apply_status(battle, defender_key, auto_status)
                    if status_applied:
                        status_effect = auto_status

        # Handle permanent death before sending state
        _handle_pvp_permadeath(battle)

        # Attach extra info to battle log for client display
        if ability_trigger:
            battle['log'].append({'type': 'ability', 'message': ability_trigger.get('message', '')})
        if status_applied:
            battle['log'].append({'type': 'status_applied', 'player': defender_key,
                                  'status': status_effect})
        if status_dmg > 0:
            battle['log'].append({'type': 'status_damage', 'player': player_key,
                                  'damage': status_dmg, 'status': status_info})

        # Send updated state to both players
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'attack')

        if result == 'battle_end':
            handle_pvp_victory(battle)
        elif result == 'must_switch':
            # Notify defender they must switch
            defender_key = 'player2' if player_key == 'player1' else 'player1'
            defender_id = battle[defender_key]['id']
            emit('pvp_must_switch', {
                'battle_id': battle_id,
                'message': 'Seu Pokémon desmaiou! Escolha o próximo.'
            }, room=defender_id)
            # If defender is NPC, auto-switch
            if battle[defender_key].get('is_npc'):
                npc_next = pvp.npc_choose_pokemon(battle, defender_key)
                if npc_next is not None:
                    pvp.switch_pokemon(battle, defender_key, npc_next)
                    # Send updated state
                    p1_state = pvp.get_battle_state_for_player(battle, 'player1')
                    p2_state = pvp.get_battle_state_for_player(battle, 'player2')
                    emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
                    emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        
        # If next turn is NPC, auto-attack
        next_player_key = battle['turn']
        if battle['phase'] == 'battle' and battle[next_player_key].get('is_npc'):
            handle_npc_turn(battle, next_player_key)

@socketio.on('pvp_switch')
def handle_pvp_switch(data):
    """Player switches pokemon in PVP."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        new_idx = int(data.get('pokemon_idx', 0))
        
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        success, msg = pvp.switch_pokemon(battle, player_key, new_idx)
        
        if not success:
            emit('pvp_error', {'message': msg})
            return
        
        # Send updated state
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'switch')

        # If next turn is NPC
        if battle['phase'] == 'battle' and battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])

@socketio.on('pvp_pass_turn')
def handle_pvp_pass(data):
    """Player passes turn."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        if battle['turn'] != player_key:
            return
        pvp.advance_turn(battle)
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'pass')

        if battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])

@socketio.on('tournament_start_match')
def handle_tournament_start_match(data):
    """Master initiates a tournament match — creates an official PVP battle between participants."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    tourney_id = data.get('tournament_id')
    match_id   = data.get('match_id')
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return

    match = next((m for m in tournament['bracket'] if m['id'] == match_id), None)
    if not match or match['winner'] or not match['player1'] or not match['player2']:
        return

    p1 = match['player1']
    p2 = match['player2']

    users = get_users()
    battle = pvp.create_pvp_battle('tournament', p1['id'], p2['id'])
    battle['tournament_id']   = tourney_id
    battle['tournament_match_id'] = match_id

    # Load teams (NPC participants store team directly on participant dict)
    p1_team = p1.get('team') or users.get(p1['id'], {}).get('trainer_data', {}).get('team', [])
    p2_team = p2.get('team') or users.get(p2['id'], {}).get('trainer_data', {}).get('team', [])
    pvp.set_team(battle, 'player1', p1_team)
    pvp.set_team(battle, 'player2', p2_team)

    # Mark NPC players
    if p1.get('is_npc'):
        battle['player1']['is_npc'] = True
    if p2.get('is_npc'):
        battle['player2']['is_npc'] = True

    ACTIVE_PVP[battle['id']] = battle
    match['battle_id'] = battle['id']

    # Notify human players
    for side, participant in [('player1', p1), ('player2', p2)]:
        if not participant.get('is_npc'):
            opponent = p2 if side == 'player1' else p1
            my_team  = p1_team if side == 'player1' else p2_team
            socketio.emit('pvp_battle_created', {
                'battle_id': battle['id'],
                'mode': 'tournament',
                'opponent_name': opponent['name'],
                'your_team': my_team,
                'you_are': side,
                'phase': 'selection',
                'tournament_name': tournament['name']
            }, room=participant['id'])

    # If both are NPCs, auto-resolve immediately
    if p1.get('is_npc') and p2.get('is_npc'):
        winner_key = random.choice(['player1', 'player2'])
        battle['winner'] = winner_key
        battle['phase']  = 'finished'
        handle_pvp_victory(battle)
    elif p1.get('is_npc'):
        # Auto-select for NPC player1 then wait for human p2
        if p1_team:
            pvp.select_pokemon(battle, 'player1', 0)
            battle['player1']['is_npc'] = True
    elif p2.get('is_npc'):
        if p2_team:
            pvp.select_pokemon(battle, 'player2', 0)
            battle['player2']['is_npc'] = True

    socketio.emit('tournament_match_started', {
        'match_id': match_id,
        'battle_id': battle['id'],
        'p1_name': p1['name'],
        'p2_name': p2['name']
    }, room=f'master_{_tid()}')


@socketio.on('pvp_forfeit')
def handle_pvp_forfeit(data):
    """Player forfeits the battle."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        winner_key = 'player2' if player_key == 'player1' else 'player1'
        battle['phase'] = 'finished'
        battle['winner'] = winner_key
        handle_pvp_victory(battle)


def _handle_pvp_permadeath(battle):
    """Check for and process permanent Pokémon death in PVP (HP <= -10)."""
    pd = battle.pop('last_permadeath', None)
    if not pd:
        return
    dead_player_id = pd['player_id']
    dead_poke_name = pd['pokemon_name']
    users = get_users()
    user = users.get(dead_player_id)
    if user:
        team = user.get('trainer_data', {}).get('team', [])
        original_len = len(team)
        team = [p for p in team if (p.get('nickname') or p.get('name')) != dead_poke_name]
        if len(team) < original_len:
            user['trainer_data']['team'] = team
            save_users(users)
    socketio.emit('pvp_pokemon_death', {
        'pokemon_name': dead_poke_name,
        'message': f'💀 {dead_poke_name} atingiu -30 HP e morreu permanentemente!'
    }, room=dead_player_id)
    socketio.emit('pvp_master_permadeath', {
        'player_id': dead_player_id,
        'pokemon': dead_poke_name
    }, room=f'master_{_tid()}')


@socketio.on('master_force_npc_select')
def handle_master_force_npc_select(data):
    """Master forces an NPC to select their starting pokemon."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    battle_id = data.get('battle_id')
    player_key = data.get('player_key')
    battle = ACTIVE_PVP.get(battle_id)
    if not battle or battle['phase'] != 'selection':
        emit('master_error', {'msg': 'Batalha não está em fase de seleção.'})
        return
    team = battle[player_key].get('team', [])
    if not team:
        emit('master_error', {'msg': 'NPC não tem equipe.'})
        return
    success, result = pvp.select_pokemon(battle, player_key, 0)
    if result == 'battle_start':
        opponent_key = 'player2' if player_key == 'player1' else 'player1'
        opp_is_npc = battle[opponent_key].get('is_npc', False)
        if not opp_is_npc:
            state = pvp.get_battle_state_for_player(battle, opponent_key)
            socketio.emit('pvp_battle_state', state, room=battle[opponent_key]['id'])
        _emit_pvp_to_master(battle, 'battle_started')
        if battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])
    else:
        _emit_pvp_to_master(battle, 'update')
    emit('master_force_npc_result', {'message': f'✅ NPC selecionou Pokémon!'})


@socketio.on('master_force_npc_action')
def handle_master_force_npc(data):
    """Master forces an NPC (or frozen player) to take an action."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    battle_id = data.get('battle_id')
    player_key = data.get('player_key')
    battle = ACTIVE_PVP.get(battle_id)
    if not battle or battle['phase'] != 'battle':
        emit('master_error', {'msg': 'Batalha inativa ou não encontrada.'})
        return
    if player_key not in ('player1', 'player2'):
        return
    handle_npc_turn(battle, player_key)
    emit('master_force_npc_result', {'message': f'⚡ Ação forçada para {player_key}!'})


def _emit_pvp_to_master(battle, event='update'):
    """Broadcast current PVP battle state to master room."""
    p1 = battle.get('player1', {})
    p2 = battle.get('player2', {})
    p1_active = (p1.get('team') or [{}])[p1.get('active_idx') or 0] if p1.get('team') else {}
    p2_active = (p2.get('team') or [{}])[p2.get('active_idx') or 0] if p2.get('team') else {}
    users = get_users()
    npcs = db.get_npcs()
    npc_map = {n['id']: n['name'] for n in npcs}
    p1_name = users.get(p1.get('id'), {}).get('username') or npc_map.get(p1.get('id'), p1.get('id', '?'))
    p2_name = users.get(p2.get('id'), {}).get('username') or npc_map.get(p2.get('id'), p2.get('id', '?'))
    socketio.emit('pvp_master_update', {
        'event':       event,
        'battle_id':   battle.get('id'),
        'mode':        battle.get('mode', 'official'),
        'phase':       battle.get('phase', 'selection'),
        'round':       battle.get('round', 0),
        'turn':        battle.get('turn'),
        'winner':      battle.get('winner'),
        'extra':       battle.get('extra', {}),
        'p1_id':       p1.get('id'), 'p1_name': p1_name,
        'p1_is_npc':   p1.get('is_npc', False),
        'p1_hp':       max(0, p1_active.get('currentHp', 0)) if isinstance(p1_active.get('currentHp'), (int, float)) else '?',
        'p1_maxhp':    p1_active.get('maxHp', '?'),
        'p1_pokemon':  p1_active.get('nickname') or p1_active.get('name', '?'),
        'p2_id':       p2.get('id'), 'p2_name': p2_name,
        'p2_is_npc':   p2.get('is_npc', False),
        'p2_hp':       max(0, p2_active.get('currentHp', 0)) if isinstance(p2_active.get('currentHp'), (int, float)) else '?',
        'p2_maxhp':    p2_active.get('maxHp', '?'),
        'p2_pokemon':  p2_active.get('nickname') or p2_active.get('name', '?'),
    }, room=f'master_{_tid()}')


def handle_npc_turn(battle, npc_key):
    """Handle NPC's automatic turn."""
    move = pvp.npc_choose_action(battle, npc_key)
    damage = random.randint(3, 12)

    # Check defender (human player) ability against NPC move type
    defender_key = 'player2' if npc_key == 'player1' else 'player1'
    if not battle[defender_key].get('is_npc'):
        move_data = MOVES_BY_NAME.get(move.lower(), {})
        move_type = move_data.get('type', '').lower()
        defender_team = battle[defender_key].get('team', [])
        defender_active_idx = battle[defender_key].get('active_idx')
        defender_active = defender_team[defender_active_idx] if (defender_active_idx is not None and defender_team) else None
        if defender_active and move_type:
            def_ability = defender_active.get('ability', '') or ''
            if def_ability:
                ab_result = ab.check_defender_ability(
                    def_ability, move_type, damage,
                    defender_active.get('currentHp', 999), defender_active.get('maxHp', 999)
                )
                if ab_result['triggered']:
                    damage = ab_result['modified_damage']
                    if ab_result['heal']:
                        defender_active['currentHp'] = min(
                            defender_active.get('maxHp', 999),
                            defender_active.get('currentHp', 0) + ab_result['heal']
                        )
                    # Emit ability trigger to the defender's room
                    defender_id = battle[defender_key]['id']
                    socketio.emit('ability_triggered', {
                        'message': ab_result['message'],
                        'blocked': ab_result['blocked'],
                        'heal': ab_result['heal'],
                        'boost': ab_result['boost'],
                    }, room=defender_id)

    result = pvp.apply_damage(battle, npc_key, damage, move, 'NPC auto-attack')

    p1_state = pvp.get_battle_state_for_player(battle, 'player1')
    p2_state = pvp.get_battle_state_for_player(battle, 'player2')
    socketio.emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
    socketio.emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
    _emit_pvp_to_master(battle, 'npc_attack')

    if result == 'battle_end':
        handle_pvp_victory(battle)
    elif result == 'must_switch':
        defender_key = 'player2' if npc_key == 'player1' else 'player1'
        if battle[defender_key].get('is_npc'):
            npc_next = pvp.npc_choose_pokemon(battle, defender_key)
            if npc_next is not None:
                pvp.switch_pokemon(battle, defender_key, npc_next)


def handle_pvp_victory(battle):
    """Handle battle end - distribute rewards."""
    winner_key = battle['winner']
    loser_key = 'player2' if winner_key == 'player1' else 'player1'
    winner_id = battle[winner_key]['id']
    loser_id = battle[loser_key]['id']
    mode = battle['mode']
    
    users = get_users()
    winner_trainer = users.get(winner_id, {}).get('trainer_data', {})
    loser_trainer = users.get(loser_id, {}).get('trainer_data', {})
    
    rewards = {'money': 0, 'items': []}
    
    if mode == 'official' or mode == 'tournament':
        # Winner gets both bets
        p1_bet = battle['bets'].get('player1', {})
        p2_bet = battle['bets'].get('player2', {})
        total_money = p1_bet.get('money', 0) + p2_bet.get('money', 0)
        total_items = p1_bet.get('items', []) + p2_bet.get('items', [])
        
        winner_trainer['money'] = winner_trainer.get('money', 0) + total_money
        for item in total_items:
            bag = winner_trainer.get('bag', [])
            added = False
            for bi in bag:
                if isinstance(bi, dict) and bi.get('name', '').lower() == item.get('name', '').lower():
                    bi['qty'] = bi.get('qty', 1) + item.get('qty', 1)
                    added = True
                    break
            if not added:
                bag.append(item)
            winner_trainer['bag'] = bag
        
        rewards = {'money': total_money, 'items': total_items}
    
    elif mode == 'street':
        # Winner steals 25% money + 2 random items
        stolen_money, stolen_items = pvp.calculate_street_loot(loser_trainer)
        
        loser_trainer['money'] = max(0, loser_trainer.get('money', 0) - stolen_money)
        winner_trainer['money'] = winner_trainer.get('money', 0) + stolen_money
        
        # Remove stolen items from loser
        loser_bag = loser_trainer.get('bag', [])
        for si in stolen_items:
            for i, bi in enumerate(loser_bag):
                if isinstance(bi, dict) and bi.get('name', '').lower() == si['name'].lower():
                    bi['qty'] = bi.get('qty', 1) - 1
                    if bi['qty'] <= 0:
                        loser_bag.pop(i)
                    break
        loser_trainer['bag'] = loser_bag
        
        # Add to winner
        winner_bag = winner_trainer.get('bag', [])
        for si in stolen_items:
            added = False
            for bi in winner_bag:
                if isinstance(bi, dict) and bi.get('name', '').lower() == si['name'].lower():
                    bi['qty'] = bi.get('qty', 1) + 1
                    added = True
                    break
            if not added:
                winner_bag.append(si)
        winner_trainer['bag'] = winner_bag
        
        rewards = {'money': stolen_money, 'items': stolen_items}
    
    # Increment battle_wins on winner's active Pokémon
    winner_team = winner_trainer.get('team', [])
    winner_active_idx = battle.get(winner_key, {}).get('active_idx')
    if winner_active_idx is not None and winner_active_idx < len(winner_team):
        winner_team[winner_active_idx]['battle_wins'] = winner_team[winner_active_idx].get('battle_wins', 0) + 1
    winner_trainer['team'] = winner_team

    # Save
    if winner_id in users:
        users[winner_id]['trainer_data'] = winner_trainer
    if loser_id in users:
        users[loser_id]['trainer_data'] = loser_trainer
    save_users(users)
    
    # Notify players
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner': winner_key,
        'winner_name': users.get(winner_id, {}).get('username', '???'),
        'loser_name': users.get(loser_id, {}).get('username', '???'),
        'mode': mode,
        'rewards': rewards
    }, room=winner_id)
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner': winner_key,
        'winner_name': users.get(winner_id, {}).get('username', '???'),
        'loser_name': users.get(loser_id, {}).get('username', '???'),
        'mode': mode,
        'lost': rewards
    }, room=loser_id)
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner_name': users.get(winner_id, {}).get('username', '???'),
        'mode': mode
    }, room=f'master_{_tid()}')
    
    _emit_pvp_to_master(battle, 'battle_ended')

    # Auto-report tournament result
    tourney_id  = battle.get('tournament_id')
    match_id_bt = battle.get('tournament_match_id')
    if tourney_id and match_id_bt:
        tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
        if tournament:
            winner_participant_id = battle[winner_key]['id']
            _apply_tournament_match_result(tournament, tourney_id, match_id_bt, winner_participant_id)

    # Cleanup
    if battle['id'] in ACTIVE_PVP:
        del ACTIVE_PVP[battle['id']]

# ============================================================
# PLAYER-TO-PLAYER TRANSFERS (Money & Items)
# ============================================================
@app.route('/player/transfer', methods=['POST'])
@login_required
def transfer_assets():
    """Transfer money and/or items from current player to another player."""
    data = request.json
    target_id = data.get('target_id')
    money_amount = int(data.get('money', 0))
    items_to_send = data.get('items', [])  # list of {name, qty, file}
    
    if not target_id:
        return jsonify({'error': 'No target specified'}), 400
    
    users = get_users()
    sender = users.get(current_user.id)
    receiver = users.get(target_id)
    
    if not sender or not receiver:
        return jsonify({'error': 'Player not found'}), 404
    
    sender_trainer = sender.get('trainer_data', {})
    receiver_trainer = receiver.get('trainer_data', {})
    
    # Validate money
    if money_amount > 0:
        sender_money = sender_trainer.get('money', 0)
        if sender_money < money_amount:
            return jsonify({'error': f'Dinheiro insuficiente. Você tem ₽{sender_money}'}), 400
        sender_trainer['money'] = sender_money - money_amount
        receiver_trainer['money'] = receiver_trainer.get('money', 0) + money_amount
    
    # Validate and transfer items
    sender_bag = sender_trainer.get('bag', [])
    receiver_bag = receiver_trainer.get('bag', [])
    
    for item in items_to_send:
        item_name = item.get('name', '')
        item_qty = int(item.get('qty', 1))
        item_file = item.get('file', '')
        
        # Find item in sender's bag
        found = False
        for i, bag_item in enumerate(sender_bag):
            bag_name = bag_item.get('name', '') if isinstance(bag_item, dict) else bag_item
            if bag_name.lower() == item_name.lower():
                bag_qty = bag_item.get('qty', 1) if isinstance(bag_item, dict) else 1
                if bag_qty < item_qty:
                    return jsonify({'error': f'Quantidade insuficiente de {item_name}'}), 400
                # Remove from sender
                if bag_qty == item_qty:
                    sender_bag.pop(i)
                else:
                    sender_bag[i]['qty'] = bag_qty - item_qty
                found = True
                break
        
        if not found:
            return jsonify({'error': f'Item {item_name} não encontrado na sua bolsa'}), 400
        
        # Add to receiver
        added = False
        for bag_item in receiver_bag:
            if isinstance(bag_item, dict) and bag_item.get('name', '').lower() == item_name.lower():
                bag_item['qty'] = bag_item.get('qty', 1) + item_qty
                added = True
                break
        if not added:
            receiver_bag.append({'name': item_name, 'qty': item_qty, 'file': item_file})
    
    sender_trainer['bag'] = sender_bag
    receiver_trainer['bag'] = receiver_bag
    users[current_user.id]['trainer_data'] = sender_trainer
    users[target_id]['trainer_data'] = receiver_trainer
    save_users(users)
    
    # Notify both players in real-time
    transfer_msg = []
    if money_amount > 0:
        transfer_msg.append(f'₽{money_amount}')
    if items_to_send:
        transfer_msg.append(', '.join([f"{i['qty']}x {i['name']}" for i in items_to_send]))
    
    socketio.emit('transfer_received', {
        'from': current_user.username,
        'message': ' + '.join(transfer_msg),
        'money': money_amount,
        'items': items_to_send
    }, room=target_id)
    
    return jsonify({
        'success': True,
        'new_money': sender_trainer['money'],
        'message': f'Transferido {" + ".join(transfer_msg)} para {receiver["username"]}'
    })

@app.route('/api/players')
@login_required
def api_players_list():
    """List all players (for transfers/PVP)."""
    users = get_users()
    players = []
    for uid, u in users.items():
        if u['role'] == 'player' and uid != current_user.id:
            trainer = u.get('trainer_data', {})
            players.append({
                'id': uid,
                'name': trainer.get('name', u['username']),
                'username': u['username'],
                'level': trainer.get('level', 1)
            })
    return jsonify(players)

# ============================================================
# TOURNAMENT MANAGEMENT
# ============================================================
@app.route('/master/tournament', methods=['POST'])
@login_required
def create_tournament_route():
    """Create a new tournament."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    name = data.get('name', 'Campeonato')
    max_participants = int(data.get('max_participants', 16))
    prizes = {
        'first': {'money': int(data.get('prize_1_money', 0)), 'extra': data.get('prize_extra', '')},
        'second': {'money': int(data.get('prize_2_money', 0))},
        'third': {'money': int(data.get('prize_3_money', 0))},
        'places': int(data.get('prize_places', 3))
    }
    tournament = pvp.create_tournament(name, prizes, max_participants)
    ACTIVE_TOURNAMENTS[tournament['id']] = tournament
    return jsonify(tournament)

@app.route('/master/tournament/<tourney_id>/participants', methods=['POST'])
@login_required
def add_tournament_participant(tourney_id):
    """Add a participant (player or NPC) to tournament."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404
    if tournament['status'] != 'registration':
        return jsonify({'error': 'Tournament already started'}), 400
    
    data = request.json
    participant_type = data.get('type', 'player')  # 'player' or 'npc'
    
    if participant_type == 'player':
        player_id = data.get('player_id')
        users = get_users()
        if player_id not in users:
            return jsonify({'error': 'Player not found'}), 404
        user = users[player_id]
        trainer = user.get('trainer_data', {})
        participant = {
            'id': player_id,
            'name': trainer.get('name', user['username']),
            'is_npc': False,
            'team': trainer.get('team', [])
        }
    else:
        npc_id = data.get('npc_id')
        npcs = db.get_npcs()
        npc = next((n for n in npcs if n.get('id') == npc_id), None)
        if not npc:
            return jsonify({'error': 'NPC not found'}), 404
        participant = {
            'id': f"npc_{npc['id']}",
            'name': npc['name'],
            'is_npc': True,
            'team': npc.get('team', [])
        }
    
    # Check if already registered
    if any(p['id'] == participant['id'] for p in tournament['participants']):
        return jsonify({'error': 'Já registrado'}), 400
    
    if len(tournament['participants']) >= tournament['max_participants']:
        return jsonify({'error': 'Campeonato lotado'}), 400
    
    tournament['participants'].append(participant)
    return jsonify({'success': True, 'participants': tournament['participants']})

@app.route('/master/tournament/<tourney_id>/start', methods=['POST'])
@login_required
def start_tournament_route(tourney_id):
    """Start the tournament - generate bracket."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404
    if len(tournament['participants']) < 2:
        return jsonify({'error': 'Mínimo 2 participantes'}), 400
    
    bracket = pvp.generate_bracket(tournament)

    payload = {
        'tournament_id': tourney_id,
        'name': tournament['name'],
        'bracket': bracket,
        'status': tournament['status'],
        'current_round': tournament['current_round'],
        'participants_count': len(tournament['participants'])
    }
    socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
    socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')

    return jsonify({'success': True, 'bracket': bracket})

@app.route('/master/tournament/<tourney_id>/bracket')
@login_required
def get_tournament_bracket(tourney_id):
    """Get current bracket state."""
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(tournament)

@app.route('/api/natures')
@login_required
def api_natures():
    """List all natures with their stat modifiers."""
    return jsonify(scaling.NATURE_MODIFIERS)

@app.route('/api/tournament/active')
@login_required
def get_active_tournament():
    """Get the current active tournament (for players to poll on load)."""
    for t in ACTIVE_TOURNAMENTS.values():
        if t['status'] in ('in_progress', 'registration'):
            return jsonify(t)
    return jsonify(None)

def _apply_tournament_match_result(tournament, tourney_id, match_id, winner_id):
    """Core logic: record match winner, advance bracket, emit updates. Returns status string."""
    for match in tournament['bracket']:
        if match['id'] == match_id:
            if match['winner']:
                return 'already_decided'
            match['winner'] = winner_id
            break

    current_round = tournament['current_round']
    round_matches = [m for m in tournament['bracket'] if m['round'] == current_round]
    all_decided = all(m['winner'] is not None for m in round_matches)

    if not all_decided:
        socketio.emit('tournament_bracket_update', {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': current_round
        }, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': current_round
        }, room=f'master_{_tid()}')
        return 'round_in_progress'

    # Round complete — compute winners list
    winners = []
    for m in round_matches:
        wp = m['player1'] if m['player1'] and m['player1']['id'] == m['winner'] else m['player2']
        if wp:
            winners.append(wp)

    if len(winners) <= 1:
        tournament['status'] = 'finished'
        tournament['results'] = {
            'first': winners[0] if winners else None,
            'second': None,
            'third': None
        }
        final_match = round_matches[0] if round_matches else None
        if final_match:
            loser = final_match['player1'] if final_match['player1'] and final_match['player1']['id'] != final_match['winner'] else final_match['player2']
            tournament['results']['second'] = loser
        award_tournament_prizes(tournament)

        payload = {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': 'finished',
            'current_round': tournament['current_round'],
            'results': tournament['results']
        }
        socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')
        return 'finished'
    else:
        next_round = current_round + 1
        for i in range(0, len(winners), 2):
            new_match = {
                'id': f"match_{secrets.token_hex(3)}",
                'round': next_round,
                'player1': winners[i],
                'player2': winners[i + 1] if i + 1 < len(winners) else None,
                'winner': None,
                'battle_id': None
            }
            if new_match['player2'] is None:
                new_match['winner'] = new_match['player1']['id']
            tournament['bracket'].append(new_match)
        tournament['current_round'] = next_round

        payload = {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': next_round
        }
        socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')
        return 'next_round'


@app.route('/master/tournament/<tourney_id>/match/<match_id>/result', methods=['POST'])
@login_required
def set_match_result(tourney_id, match_id):
    """Set the winner of a tournament match (manual override by master)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404

    data = request.json
    winner_id = data.get('winner_id')
    status = _apply_tournament_match_result(tournament, tourney_id, match_id, winner_id)

    if status == 'finished':
        return jsonify({'success': True, 'status': 'finished', 'results': tournament['results']})
    return jsonify({'success': True, 'bracket': tournament['bracket']})


def award_tournament_prizes(tournament):
    """Award prizes to tournament winners."""
    prizes = tournament.get('prizes', {})
    results = tournament.get('results', {})
    users = get_users()
    
    placements = [('first', results.get('first')), ('second', results.get('second')), ('third', results.get('third'))]
    max_places = prizes.get('places', 3)
    
    for i, (place, participant) in enumerate(placements):
        if i >= max_places or not participant or participant.get('is_npc'):
            continue
        player_id = participant['id']
        if player_id in users:
            trainer = users[player_id].get('trainer_data', {})
            prize_money = prizes.get(place, {}).get('money', 0)
            if prize_money > 0:
                trainer['money'] = trainer.get('money', 0) + prize_money
            users[player_id]['trainer_data'] = trainer
            
            socketio.emit('tournament_prize', {
                'tournament': tournament['name'],
                'place': place,
                'money': prize_money,
                'extra': prizes.get('first', {}).get('extra', '') if place == 'first' else ''
            }, room=player_id)
    
    save_users(users)

# ============================================================
# GYMS
# ============================================================

@app.route('/api/gyms')
@login_required
def api_get_gyms():
    gyms = db.get_gyms()
    # Attach conquered status per player
    if current_user.role == 'player':
        trainer = get_users().get(current_user.id, {}).get('trainer_data', {})
        badges = trainer.get('badges', [])
        for g in gyms:
            g['conquered'] = g['badge_name'] in badges
    return jsonify(gyms)


@app.route('/api/gyms', methods=['POST'])
@login_required
def api_create_gym():
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    data = request.json or {}
    required = ['name', 'badge_name', 'type', 'leader_name']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'Campo obrigatório: {f}'}), 400

    gyms = db.get_gyms()
    gym_id = f"gym_{secrets.token_hex(4)}"
    gym = {
        'id': gym_id,
        'name': data['name'],
        'badge_name': data['badge_name'],
        'badge_icon': data.get('badge_icon', '🏅'),
        'type': data['type'],
        'leader_name': data['leader_name'],
        'leader_npc_id': data.get('leader_npc_id'),
        'leader_player_id': data.get('leader_player_id'),
        'required_badges': data.get('required_badges', []),
        'level_cap': int(data.get('level_cap', 5)),
        'order': len(gyms) + 1,
        'description': data.get('description', ''),
        'active_battles': {}
    }
    gyms.append(gym)
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify(gym), 201


@app.route('/api/gyms/<gym_id>', methods=['PUT'])
@login_required
def api_update_gym(gym_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return jsonify({'error': 'Ginásio não encontrado'}), 404
    data = request.json or {}
    for field in ['name', 'badge_name', 'badge_icon', 'type', 'leader_name',
                  'leader_npc_id', 'leader_player_id', 'required_badges',
                  'level_cap', 'order', 'description']:
        if field in data:
            gym[field] = data[field]
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify(gym)


@app.route('/api/gyms/<gym_id>', methods=['DELETE'])
@login_required
def api_delete_gym(gym_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    gyms = db.get_gyms()
    gyms = [g for g in gyms if g['id'] != gym_id]
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify({'ok': True})


@socketio.on('gym_challenge')
@login_required
def handle_gym_challenge(data):
    """Player challenges a gym. Creates an official PVP battle vs leader."""
    gym_id = data.get('gym_id')
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        emit('gym_error', {'msg': 'Ginásio não encontrado'})
        return

    # Check badge requirements
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    badges = trainer.get('badges', [])
    for req in gym.get('required_badges', []):
        if req not in badges:
            emit('gym_error', {'msg': f'Você precisa da insígnia "{req}" antes de desafiar este ginásio.'})
            return

    # Check if already conquered
    if gym['badge_name'] in badges:
        emit('gym_error', {'msg': 'Você já conquistou esta insígnia!'})
        return

    # Determine leader
    leader_npc_id   = gym.get('leader_npc_id')
    leader_player_id = gym.get('leader_player_id')

    if leader_player_id and leader_player_id in users:
        # Human leader — send challenge invite
        battle_id = f"gym_{gym_id}_{secrets.token_hex(4)}"
        pending = {
            'battle_id': battle_id,
            'gym_id': gym_id,
            'gym_name': gym['name'],
            'challenger_id': current_user.id,
            'challenger_name': trainer.get('name', current_user.username)
        }
        socketio.emit('gym_challenge_incoming', pending, room=leader_player_id)
        emit('gym_challenge_sent', {'msg': f'Desafio enviado para {gym["leader_name"]}!'})
        return

    # NPC leader
    npcs = db.get_npcs()
    npc = next((n for n in npcs if n['id'] == leader_npc_id), None) if leader_npc_id else None

    if not npc:
        npc = {'id': f'npc_leader_{gym_id}', 'name': gym['leader_name'], 'team': [], 'is_npc': True}

    battle = pvp.create_pvp_battle('official', current_user.id, npc['id'])
    battle['gym_id']    = gym_id
    battle['gym_badge'] = gym['badge_name']
    battle['gym_icon']  = gym.get('badge_icon', '🏅')
    battle['extra']     = {'gym_id': gym_id, 'gym_badge': gym['badge_name'], 'gym_icon': gym.get('badge_icon', '🏅')}
    pvp.set_team(battle, 'player1', trainer.get('team', []))
    pvp.set_team(battle, 'player2', npc.get('team', []))
    battle['player2']['is_npc'] = True
    if npc.get('team'):
        pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle

    emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': gym['leader_name'],
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    })


@socketio.on('gym_challenge_accept')
@login_required
def handle_gym_challenge_accept(data):
    """Human leader accepts a gym challenge."""
    gym_id       = data.get('gym_id')
    challenger_id = data.get('challenger_id')
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return

    users = get_users()
    challenger_trainer = users.get(challenger_id, {}).get('trainer_data', {})
    leader_trainer     = users.get(current_user.id, {}).get('trainer_data', {})

    battle = pvp.create_pvp_battle('official', challenger_id, current_user.id)
    battle['extra'] = {'gym_id': gym_id, 'gym_badge': gym['badge_name'], 'gym_icon': gym.get('badge_icon', '🏅')}
    pvp.set_team(battle, 'player1', challenger_trainer.get('team', []))
    pvp.set_team(battle, 'player2', leader_trainer.get('team', []))
    ACTIVE_PVP[battle['id']] = battle

    challenger_name = challenger_trainer.get('name', users[challenger_id]['username'])
    leader_name_str = leader_trainer.get('name', current_user.username)
    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': gym['leader_name'],
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     challenger_trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    }, room=challenger_id)
    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': challenger_name,
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     leader_trainer.get('team', []),
        'you_are':       'player2',
        'phase':         'selection'
    }, room=current_user.id)


def _award_gym_badge(winner_id, gym_id):
    """Called after gym battle is won. Awards badge and XP multiplier."""
    gyms = db.get_gyms()
    gym  = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return

    users = get_users()
    if winner_id not in users:
        return

    trainer = users[winner_id].get('trainer_data', {})
    badges  = trainer.get('badges', [])
    badge   = gym['badge_name']

    if badge not in badges:
        badges.append(badge)
        trainer['badges'] = badges
        users[winner_id]['trainer_data'] = trainer
        save_users(users)

        socketio.emit('badge_awarded', {
            'gym_id':    gym_id,
            'gym_name':  gym['name'],
            'badge':     badge,
            'icon':      gym.get('badge_icon', '🏅'),
            'badges_total': len(badges)
        }, room=winner_id)

        socketio.emit('master_action', {
            'type': 'badge_awarded',
            'player': trainer.get('name', users[winner_id]['username']),
            'badge': badge,
            'gym': gym['name']
        }, room=f'master_{_tid()}')


# ============================================================
# LEAGUE
# ============================================================

@app.route('/api/league')
@login_required
def api_get_league():
    league = db.get_league()
    if current_user.role == 'player':
        run = league.get('active_runs', {}).get(current_user.id)
        return jsonify({'slots': league.get('slots', []), 'my_run': run})
    return jsonify(league)


@app.route('/api/league/slots', methods=['POST'])
@login_required
def api_save_league_slots():
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    data = request.json or {}
    league = db.get_league()
    league['slots'] = data.get('slots', [])
    db.save_league(league)
    socketio.emit('league_updated', {'slots': league['slots']}, room=f'players_{_tid()}')
    socketio.emit('league_updated', {'slots': league['slots']}, room=f'master_{_tid()}')
    return jsonify({'ok': True})


@socketio.on('league_challenge_start')
@login_required
def handle_league_start(data):
    """Player starts a League run. Must have all required badges."""
    league = db.get_league()
    slots  = league.get('slots', [])
    if not slots:
        emit('league_error', {'msg': 'A Liga ainda não foi configurada pelo Mestre.'})
        return

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    badges  = trainer.get('badges', [])

    # Check all gym badges that have "required_for_league" or just all gym badges
    gyms = db.get_gyms()
    gym_badges = [g['badge_name'] for g in gyms]
    missing = [b for b in gym_badges if b not in badges]
    if missing:
        emit('league_error', {'msg': f'Você ainda precisa das insígnias: {", ".join(missing)}'})
        return

    # Check if already has an active run
    active_runs = league.get('active_runs', {})
    if current_user.id in active_runs and active_runs[current_user.id].get('status') == 'in_progress':
        emit('league_error', {'msg': 'Você já tem uma tentativa em andamento!'})
        return

    run = {
        'player_id':   current_user.id,
        'player_name': trainer.get('name', current_user.username),
        'current_slot': 0,
        'status':       'in_progress',
        'battle_id':    None
    }
    active_runs[current_user.id] = run
    league['active_runs'] = active_runs
    db.save_league(league)
    emit('league_run_started', {'run': run, 'slots': slots})
    _start_league_battle(current_user.id, 0)


def _start_league_battle(player_id, slot_index):
    """Creates a battle between the player and the current league slot opponent."""
    league = db.get_league()
    slots  = league.get('slots', [])
    if slot_index >= len(slots):
        return

    slot = slots[slot_index]
    users = get_users()
    trainer = users.get(player_id, {}).get('trainer_data', {})

    leader_player_id = slot.get('leader_player_id')
    leader_npc_id    = slot.get('leader_npc_id')

    if leader_player_id and leader_player_id in users:
        leader_trainer = users[leader_player_id].get('trainer_data', {})
        leader_team    = leader_trainer.get('team', [])
        leader_name    = leader_trainer.get('name', users[leader_player_id]['username'])
        is_npc_battle  = False
        opponent_id    = leader_player_id
    else:
        npcs = db.get_npcs()
        npc  = next((n for n in npcs if n['id'] == leader_npc_id), None) if leader_npc_id else None
        if not npc:
            npc = {'id': f'npc_league_{slot_index}', 'name': slot.get('leader_name', f'Elite {slot_index+1}'), 'team': [], 'is_npc': True}
        leader_team   = npc.get('team', [])
        leader_name   = npc.get('name', slot.get('leader_name', f'Membro da Liga {slot_index+1}'))
        is_npc_battle = True
        opponent_id   = npc['id']

    battle = pvp.create_pvp_battle('official', player_id, opponent_id)
    battle['extra'] = {
        'league_slot':  slot_index,
        'league_total': len(slots),
        'slot_title':   slot.get('title', f'Membro {slot_index+1}'),
        'is_champion':  slot.get('is_champion', False)
    }
    pvp.set_team(battle, 'player1', trainer.get('team', []))
    pvp.set_team(battle, 'player2', leader_team)
    if is_npc_battle:
        battle['player2']['is_npc'] = True
        if leader_team:
            pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle

    # Store battle_id in run
    league['active_runs'][player_id]['battle_id'] = battle['id']
    db.save_league(league)

    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': leader_name,
        'mode':          'official',
        'league_slot':   slot_index,
        'slot_title':    slot.get('title', f'Membro {slot_index+1}'),
        'is_champion':   slot.get('is_champion', False),
        'your_team':     trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    }, room=player_id)

    if not is_npc_battle:
        socketio.emit('pvp_battle_created', {
            'battle_id':     battle['id'],
            'opponent_name': trainer.get('name', users[player_id]['username']),
            'mode':          'official',
            'league_slot':   slot_index,
            'your_team':     leader_team,
            'you_are':       'player2',
            'phase':         'selection'
        }, room=opponent_id)


# Patch handle_pvp_victory to handle gym and league battles
_original_handle_pvp_victory = handle_pvp_victory  # noqa: F821


def _extended_handle_pvp_victory(battle):
    """Wraps the original pvp victory handler to also process gym/league results."""
    extra = battle.get('extra', {})
    winner_key = battle.get('winner', 'player1')
    winner_id  = battle.get(winner_key, {}).get('id') if winner_key in battle else None

    player1_id = battle.get('player1', {}).get('id')

    # Gym battle
    if extra.get('gym_id'):
        # Only award if the challenger (player1) won
        if winner_id == player1_id:
            _award_gym_badge(winner_id, extra['gym_id'])

    # League battle
    league_slot = extra.get('league_slot')
    if league_slot is not None:
        player_id = player1_id
        league    = db.get_league()
        run       = league.get('active_runs', {}).get(player_id)
        if run and run.get('status') == 'in_progress':
            slots = league.get('slots', [])
            if winner_id == player_id:
                next_slot = league_slot + 1
                if next_slot >= len(slots):
                    # Champion defeated — league cleared!
                    run['status']       = 'completed'
                    run['current_slot'] = next_slot
                    league['active_runs'][player_id] = run
                    db.save_league(league)
                    socketio.emit('league_completed', {
                        'player_name': run['player_name']
                    }, room=f'players_{_tid()}')
                    socketio.emit('league_completed', {
                        'player_name': run['player_name']
                    }, room=f'master_{_tid()}')
                    socketio.emit('league_victory', {
                        'slots_total': len(slots)
                    }, room=player_id)
                else:
                    run['current_slot'] = next_slot
                    run['battle_id']    = None
                    league['active_runs'][player_id] = run
                    db.save_league(league)
                    socketio.emit('league_next_battle', {
                        'slot': next_slot,
                        'slot_title': slots[next_slot].get('title', f'Membro {next_slot+1}'),
                        'is_champion': slots[next_slot].get('is_champion', False),
                        'total': len(slots)
                    }, room=player_id)
                    _start_league_battle(player_id, next_slot)
            else:
                # Player lost — reset run
                run['status'] = 'failed'
                league['active_runs'][player_id] = run
                db.save_league(league)
                socketio.emit('league_failed', {
                    'slot': league_slot,
                    'slot_title': extra.get('slot_title', '')
                }, room=player_id)

    _original_handle_pvp_victory(battle)


# Replace the global reference used by socket handlers
handle_pvp_victory = _extended_handle_pvp_victory  # noqa: F811

# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    # Create default master account if no users exist
    users = get_users()
    if not users:
        master_id = secrets.token_hex(8)
        users[master_id] = {
            'username': 'mestre',
            'password_hash': generate_password_hash('mestre123'),
            'role': 'master',
            'trainer_data': {}
        }
        save_users(users)
        print("=== Conta do Mestre criada ===")
        print("Usuario: mestre")
        print("Senha: mestre123")
        print("==============================")
    
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('RENDER') is None  # debug only locally
    
    print(f"\n🎮 Pokemon 5e RPG - Servidor iniciado!")
    print(f"Acesse: http://localhost:{port}\n")
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
else:
    # When imported by gunicorn, still create default user
    users = get_users()
    if not users:
        master_id = secrets.token_hex(8)
        users[master_id] = {
            'username': 'mestre',
            'password_hash': generate_password_hash('mestre123'),
            'role': 'master',
            'trainer_data': {}
        }
        save_users(users)
