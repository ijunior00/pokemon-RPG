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
get_users = db.get_users
save_users = db.save_users
get_game_state = db.get_game_state
save_game_state = db.save_game_state

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
        
        uid = secrets.token_hex(8)
        users[uid] = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
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
    users = get_users()
    players = {uid: u for uid, u in users.items() if u['role'] == 'player'}
    game_state = get_game_state()
    return render_template('master.html', 
                         players=players, 
                         game_state=game_state,
                         routes=ROUTES_DATA)

@app.route('/master/quests', methods=['POST'])
@login_required
def add_quest():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    game_state = get_game_state()
    quest = {
        'id': secrets.token_hex(4),
        'title': data.get('title', ''),
        'city': data.get('city', ''),
        'description': data.get('description', ''),
        'assigned_to': data.get('assigned_to', []),  # list of player ids
        'xp_reward': int(data.get('xp_reward', 0)),  # XP reward on completion
        'completed': False
    }
    game_state['quests'].append(quest)
    save_game_state(game_state)
    # Notify players in real-time
    socketio.emit('new_quest', quest, room='players')
    return jsonify(quest)

@app.route('/master/quests/<quest_id>/complete', methods=['POST'])
@login_required
def complete_quest(quest_id):
    """Mark a quest as complete and award XP to assigned players."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    game_state = get_game_state()
    users = get_users()
    
    for quest in game_state['quests']:
        if quest['id'] == quest_id and not quest['completed']:
            quest['completed'] = True
            xp_reward = quest.get('xp_reward', 0)
            
            # Award XP to assigned players
            if xp_reward > 0:
                assigned = quest.get('assigned_to', [])
                if not assigned:
                    assigned = [uid for uid, u in users.items() if u['role'] == 'player']
                
                for player_id in assigned:
                    if player_id in users:
                        trainer = users[player_id].get('trainer_data', {})
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
                        users[player_id]['trainer_data'] = trainer
                        
                        socketio.emit('xp_update', {
                            'player_id': player_id,
                            'xp': trainer['xp'],
                            'level': trainer['level'],
                            'xp_to_next': trainer['xp_to_next'],
                            'leveled_up': new_level > old_level
                        }, room=player_id)
                
                save_users(users)
            
            save_game_state(game_state)
            socketio.emit('quest_completed', {'quest_id': quest_id, 'xp_reward': xp_reward}, room='players')
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
        
        # Auto-level Pokemon (trainer level - 2, min 1)
        for pokemon in trainer.get('team', []):
            if pokemon.get('level', 1) < new_level - 2:
                pokemon['level'] = max(1, new_level - 2)
        
        users[player_id]['trainer_data'] = trainer
        save_users(users)
        
        # Emit XP update to specific player
        socketio.emit('xp_update', {
            'player_id': player_id,
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level
        }, room=player_id)
        
        # Also notify master
        socketio.emit('xp_update', {
            'player_id': player_id,
            'username': users[player_id]['username'],
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level
        }, room='master')
        
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
    
    return jsonify(results[:50])  # Limit to 50 results

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
    
    # Get all pokemon of matching types
    candidates = []
    for ptype in route_types:
        candidates.extend(POKEMON_BY_TYPE.get(ptype.lower(), []))
    
    # Remove duplicates
    seen_nums = set()
    unique_candidates = []
    for c in candidates:
        if c['number'] not in seen_nums:
            seen_nums.add(c['number'])
            unique_candidates.append(c)
    candidates = unique_candidates
    
    if not candidates:
        candidates = POKEMON_BY_TYPE.get('normal', [])
    
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
    
    # Shiny boost: +20% HP, +2 AC, +2 all stats
    if is_shiny:
        pokemon_data['hp'] = int(pokemon_data['hp'] * 1.2)
        pokemon_data['maxHp'] = pokemon_data['hp']
        pokemon_data['ac'] += 2
        for stat in pokemon_data['stats']:
            pokemon_data['stats'][stat] += 2
    
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
                         routes=ROUTES_DATA)

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
    
    base_pokemon = POKEMON_BY_NUMBER.get(pokemon_number)
    if not base_pokemon:
        return jsonify({'error': 'Pokemon not found'}), 404
    
    stats = scaling.calculate_pokemon_stats(base_pokemon, level)
    stats['growth_rate'] = scaling.get_growth_rate(base_pokemon)
    stats['xp_to_next'] = scaling.xp_to_next_level(level, stats['growth_rate'])
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
        pokemon_status = data.get('pokemon_status')  # {condition: 'envenenado', turns_active: 2}
        max_hp = int(data.get('max_hp', 20))
        can_act, damage, messages, removed = effects.process_turn_start(pokemon_status, max_hp)
        return jsonify({
            'can_act': can_act,
            'damage': damage,
            'messages': messages,
            'status_removed': removed
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
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(current_user.id)
        if current_user.role == 'master':
            join_room('master')
        else:
            join_room('players')
        print(f"[CONNECTED] {current_user.username} ({current_user.role})")

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
        # Save to game state
        game_state = get_game_state()
        game_state['active_encounters'][current_user.id] = encounter_data
        save_game_state(game_state)
        
        # Notify master
        emit('encounter_started', encounter_data, room='master')

@socketio.on('roll_initiative')
def handle_initiative(data):
    """Roll initiative for battle - determines who goes first.
    Can be triggered by master OR player (auto mode)."""
    if not current_user.is_authenticated:
        return
    
    # Determine player_id: if master triggers, use data; if player triggers, use own id
    if current_user.role == 'master':
        player_id = data.get('player_id')
    else:
        player_id = current_user.id
    
    if not player_id:
        player_id = current_user.id
    
    game_state = get_game_state()
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter:
        return
    
    # Don't re-roll if already rolled
    if encounter.get('battle_state', {}).get('initiative_rolled'):
        return
    
    wild_pokemon = encounter['pokemon']
    player_pokemon = encounter.get('player_pokemon') or {}
    
    # Initiative = d20 + DEX modifier
    wild_dex = wild_pokemon.get('stats', {}).get('DEX', 10)
    wild_mod = (wild_dex - 10) // 2
    player_dex = player_pokemon.get('stats', {}).get('DEX', 10) if player_pokemon else 10
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
        'first_turn': first_turn
    }
    
    emit('initiative_result', result, room='master')
    emit('initiative_result', result, room=player_id)

@socketio.on('battle_action')
def handle_battle_action(data):
    """Handle a battle action (attack, status move, etc.)."""
    if current_user.is_authenticated:
        player_id = data.get('player_id', current_user.id)
        action_by = data.get('action_by')  # 'player' or 'master' (for wild pokemon)
        action_type = data.get('action_type')  # 'attack', 'status', 'item'
        move_name = data.get('move_name', '')
        damage = data.get('damage', 0)
        heal = data.get('heal', 0)
        status_effect = data.get('status_effect', None)
        message = data.get('message', '')
        
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        battle_state = encounter['battle_state']
        
        # Apply damage
        if action_by == 'player' and damage > 0:
            battle_state['wild_hp_current'] = max(0, battle_state['wild_hp_current'] - damage)
        elif action_by == 'master' and damage > 0:
            battle_state['player_hp_current'] = max(0, battle_state['player_hp_current'] - damage)
        
        # Apply healing
        if action_by == 'player' and heal > 0:
            battle_state['player_hp_current'] = min(battle_state['player_hp_max'], battle_state['player_hp_current'] + heal)
        elif action_by == 'master' and heal > 0:
            battle_state['wild_hp_current'] = min(battle_state['wild_hp_max'], battle_state['wild_hp_current'] + heal)
        
        # Apply status
        if status_effect:
            if action_by == 'player':
                battle_state['wild_status'] = status_effect
            else:
                battle_state['player_status'] = status_effect
        
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
            'battle_state': battle_state
        }
        
        # Notify both sides
        emit('battle_update', action_result, room='master')
        emit('battle_update', action_result, room=player_id)

@socketio.on('end_encounter')
def handle_end_encounter(data):
    """End an encounter."""
    if current_user.is_authenticated:
        game_state = get_game_state()
        player_id = data.get('player_id', current_user.id)
        if player_id in game_state['active_encounters']:
            del game_state['active_encounters'][player_id]
            save_game_state(game_state)
        emit('encounter_ended', {'player_id': player_id, 'result': data.get('result')}, room='master')
        emit('encounter_ended', {'player_id': player_id, 'result': data.get('result')}, room=player_id)

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
        player_id = data.get('player_id', current_user.id)
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
        
        emit('mega_evolved', result, room='master')
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
        }, room='master')

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
        }, room='master')

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
        
        if result == 'battle_start':
            # Both ready - send full battle state to each
            p1_state = pvp.get_battle_state_for_player(battle, 'player1')
            p2_state = pvp.get_battle_state_for_player(battle, 'player2')
            emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
            emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
            # Notify master
            emit('pvp_battle_update_master', {
                'battle_id': battle_id,
                'event': 'battle_started',
                'turn': battle['turn'],
                'round': battle['round']
            }, room='master')
        elif result == 'waiting_opponent':
            emit('pvp_waiting', {'message': 'Aguardando oponente escolher Pokémon...'})

@socketio.on('pvp_attack')
def handle_pvp_attack(data):
    """Player attacks in PVP battle."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        move_name = data.get('move_name', '')
        damage = int(data.get('damage', 0))
        message = data.get('message', '')
        
        battle = ACTIVE_PVP.get(battle_id)
        if not battle or battle['phase'] != 'battle':
            return
        
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        
        # Validate it's this player's turn
        if battle['turn'] != player_key:
            emit('pvp_error', {'message': 'Não é seu turno!'})
            return
        
        # Apply damage
        result = pvp.apply_damage(battle, player_key, damage, move_name, message)
        
        # Send updated state to both players
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        
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
        
        if battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])

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


def handle_npc_turn(battle, npc_key):
    """Handle NPC's automatic turn."""
    import time
    move = pvp.npc_choose_action(battle, npc_key)
    # Simple damage calc for NPC: random 3-12
    damage = random.randint(3, 12)
    result = pvp.apply_damage(battle, npc_key, damage, move, 'NPC auto-attack')
    
    p1_state = pvp.get_battle_state_for_player(battle, 'player1')
    p2_state = pvp.get_battle_state_for_player(battle, 'player2')
    socketio.emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
    socketio.emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
    
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
    }, room='master')
    
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
    
    # Notify all players
    for p in tournament['participants']:
        if not p.get('is_npc'):
            socketio.emit('tournament_started', {
                'tournament_id': tourney_id,
                'name': tournament['name'],
                'participants': len(tournament['participants'])
            }, room=p['id'])
    
    return jsonify({'success': True, 'bracket': bracket})

@app.route('/master/tournament/<tourney_id>/bracket')
@login_required
def get_tournament_bracket(tourney_id):
    """Get current bracket state."""
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(tournament)

@app.route('/master/tournament/<tourney_id>/match/<match_id>/result', methods=['POST'])
@login_required
def set_match_result(tourney_id, match_id):
    """Set the winner of a tournament match."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404
    
    data = request.json
    winner_id = data.get('winner_id')
    
    # Find and update match
    for match in tournament['bracket']:
        if match['id'] == match_id:
            match['winner'] = winner_id
            break
    
    # Check if current round is complete
    current_round = tournament['current_round']
    round_matches = [m for m in tournament['bracket'] if m['round'] == current_round]
    all_decided = all(m['winner'] is not None for m in round_matches)
    
    if all_decided:
        # Generate next round
        winners = []
        for m in round_matches:
            winner_participant = m['player1'] if m['player1'] and m['player1']['id'] == m['winner'] else m['player2']
            if winner_participant:
                winners.append(winner_participant)
        
        if len(winners) <= 1:
            # Tournament over
            tournament['status'] = 'finished'
            tournament['results'] = {
                'first': winners[0] if winners else None,
                'second': None,  # loser of final
                'third': None
            }
            # Find final loser
            final_match = round_matches[0] if round_matches else None
            if final_match:
                loser = final_match['player1'] if final_match['player1'] and final_match['player1']['id'] != final_match['winner'] else final_match['player2']
                tournament['results']['second'] = loser
            
            # Award prizes
            award_tournament_prizes(tournament)
            
            return jsonify({'success': True, 'status': 'finished', 'results': tournament['results']})
        else:
            # Generate next round matches
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
