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
    """Generate a random encounter based on route, hunt mode, rarity, variable levels."""
    data = request.json
    route_id = data.get('route_id')
    hunt_mode = data.get('hunt_mode', 'normal')  # normal, dungeon, night
    # Legacy support
    if data.get('is_dungeon') and hunt_mode == 'normal':
        hunt_mode = 'dungeon'
    player_level = data.get('player_level', 1)
    
    route = ROUTES_DATA.get(route_id, {})
    route_types = route.get('types', ['Normal'])
    route_level_range = route.get('level_range', [1, 20])
    
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
        min_lv = max(route_level_range[0], player_level)
        max_lv = route_level_range[1]
    elif hunt_mode == 'dungeon':
        min_lv = route_level_range[0]
        max_lv = route_level_range[1]
    else:
        min_lv = max(route_level_range[0], player_level - 3)
        max_lv = min(route_level_range[1], player_level + 3)
    
    filtered = [p for p in candidates if p.get('minLevel', 1) <= max_lv]
    
    if not filtered:
        filtered = sorted(candidates, key=lambda p: abs(p.get('minLevel', 1) - player_level))[:10]
    
    if not filtered:
        return jsonify({'error': 'No pokemon available for this route'}), 404
    
    # Rarity weights
    weights = []
    for p in filtered:
        stage = p.get('evolutionStage', '1/1')
        stage_num = int(stage.split('/')[0]) if '/' in stage else 1
        sr_str = p.get('sr', '1/2')
        if '/' in sr_str:
            sr_val = int(sr_str.split('/')[0]) / int(sr_str.split('/')[1])
        else:
            sr_val = int(sr_str)
        
        if hunt_mode in ('dungeon', 'night'):
            weight = max(1, sr_val * 2 + stage_num)
        else:
            weight = 10 if stage_num == 1 else (3 if stage_num == 2 else 1)
            if sr_val <= 0.5: weight *= 3
            elif sr_val <= 2: weight *= 2
        
        weights.append(max(1, weight))
    
    chosen = random.choices(filtered, weights=weights, k=1)[0]
    
    # Encounter level based on mode
    if hunt_mode == 'night':
        # Night: +3 to +10 above player level
        encounter_level = random.randint(player_level + 3, player_level + 10)
    elif hunt_mode == 'dungeon':
        # Dungeon: ±5 of player level
        encounter_level = random.randint(max(1, player_level - 5), player_level + 5)
    else:
        # Normal: ±3 of player level within route range
        low = max(chosen.get('minLevel', 1), min_lv, player_level - 3)
        high = min(max_lv, player_level + 3)
        if low > high:
            low = chosen.get('minLevel', 1)
            high = max(low, player_level + 1)
        encounter_level = random.randint(low, high)
    
    encounter_level = max(1, max(chosen.get('minLevel', 1), encounter_level))
    
    # Shiny chance: 5% in dungeon/night, 1% normal
    shiny_chance = 0.05 if hunt_mode in ('dungeon', 'night') else 0.01
    is_shiny = random.random() < shiny_chance
    
    # Generate random moveset (4 moves from pool)
    move_pool = list(chosen.get('startingMoves', []))
    if chosen.get('levelMoves'):
        for lv, moves in chosen['levelMoves'].items():
            if int(lv) <= encounter_level:
                move_pool.extend(moves)
    if chosen.get('eggMoves'):
        move_pool.extend(chosen['eggMoves'])
    
    # Clean pool (remove non-move junk)
    move_pool = [m for m in move_pool if len(m) > 2 and not m.startswith('©') and not m.isdigit()]
    move_pool = list(dict.fromkeys(move_pool))
    
    if len(move_pool) > 4:
        starting = chosen.get('startingMoves', [])
        guaranteed = [starting[-1]] if starting else []
        remaining = [m for m in move_pool if m not in guaranteed]
        random.shuffle(remaining)
        wild_moves = guaranteed + remaining[:4 - len(guaranteed)]
    else:
        wild_moves = move_pool[:4] if move_pool else ['Tackle']
    
    # If shiny, boost stats by 20%
    pokemon_data = dict(chosen)  # copy
    if is_shiny and 'stats' in pokemon_data:
        boosted_stats = {}
        for stat, val in pokemon_data['stats'].items():
            boosted_stats[stat] = int(val * 1.2)
        pokemon_data['stats'] = boosted_stats
        pokemon_data['hp'] = int(pokemon_data.get('hp', 20) * 1.2)
        pokemon_data['ac'] = pokemon_data.get('ac', 13) + 1
    
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
                         'avatar']
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
    """Roll initiative for battle - determines who goes first."""
    if current_user.is_authenticated and current_user.role == 'master':
        player_id = data.get('player_id')
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        wild_pokemon = encounter['pokemon']
        player_pokemon = encounter['player_pokemon']
        
        # Initiative = d20 + DEX modifier
        wild_dex = wild_pokemon.get('stats', {}).get('DEX', 10)
        wild_mod = (wild_dex - 10) // 2
        player_dex = player_pokemon.get('stats', {}).get('DEX', 10) if player_pokemon else 10
        player_mod = (player_dex - 10) // 2
        
        import random
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
