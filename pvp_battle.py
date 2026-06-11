"""
PVP Battle Engine for Pokemon 5e RPG.
Handles state management for player-vs-player battles.

Modes:
- official: Blind selection, bets, pokemon can only enter once, winner takes pot
- street: No bets upfront, free swaps (costs turn), winner steals 2 random items + 25% money
- tournament: Same rules as official but in bracket format
"""
import random
import secrets


def create_pvp_battle(mode, player1_id, player2_id, bets=None):
    """Create a new PVP battle state."""
    battle_id = f"pvp_{secrets.token_hex(6)}"
    battle = {
        'id': battle_id,
        'mode': mode,  # 'official', 'street', 'tournament'
        'player1': {
            'id': player1_id,
            'team': [],           # full team data set during selection
            'active_idx': None,   # index of current active pokemon
            'used_pokemon': [],   # indices of pokemon that have been used (official/tournament)
            'ready': False        # has selected starting pokemon
        },
        'player2': {
            'id': player2_id,
            'team': [],
            'active_idx': None,
            'used_pokemon': [],
            'ready': False
        },
        'bets': bets or {'player1': {'money': 0, 'items': []}, 'player2': {'money': 0, 'items': []}},
        'turn': None,            # 'player1' or 'player2'
        'round': 0,
        'phase': 'selection',    # 'selection', 'battle', 'finished'
        'log': [],
        'winner': None,
        'tournament_id': None    # set if part of tournament
    }
    return battle


def set_team(battle, player_key, team):
    """Set a player's team for the battle."""
    battle[player_key]['team'] = team


def select_pokemon(battle, player_key, pokemon_idx):
    """Player selects their starting pokemon (blind selection phase)."""
    player = battle[player_key]
    if pokemon_idx >= len(player['team']):
        return False, "Índice de Pokémon inválido"
    
    player['active_idx'] = pokemon_idx
    player['ready'] = True
    player['used_pokemon'].append(pokemon_idx)
    
    # Check if both players are ready
    p1 = battle['player1']
    p2 = battle['player2']
    if p1['ready'] and p2['ready']:
        battle['phase'] = 'battle'
        battle['round'] = 1
        # Roll initiative
        init1 = roll_initiative(p1['team'][p1['active_idx']])
        init2 = roll_initiative(p2['team'][p2['active_idx']])
        battle['turn'] = 'player1' if init1 >= init2 else 'player2'
        battle['log'].append({
            'type': 'initiative',
            'player1_roll': init1,
            'player2_roll': init2,
            'first': battle['turn']
        })
        return True, "battle_start"
    
    return True, "waiting_opponent"


def roll_initiative(pokemon):
    """Roll d20 + DEX modifier for initiative."""
    dex = pokemon.get('stats', {}).get('DEX', 10) if isinstance(pokemon, dict) else 10
    mod = (dex - 10) // 2
    roll = random.randint(1, 20)
    return roll + mod


def switch_pokemon(battle, player_key, new_idx):
    """Switch active pokemon. Returns (success, message)."""
    player = battle[player_key]
    mode = battle['mode']
    
    if new_idx >= len(player['team']):
        return False, "Índice inválido"
    
    new_poke = player['team'][new_idx]
    
    # Check if pokemon is alive
    if new_poke.get('currentHp', 0) <= 0:
        return False, "Pokémon desmaiado não pode batalhar"
    
    # Official/Tournament: pokemon can only enter once
    if mode in ('official', 'tournament'):
        if new_idx in player['used_pokemon']:
            return False, "Este Pokémon já foi usado nesta batalha e está bloqueado"
        player['used_pokemon'].append(new_idx)
    
    old_idx = player['active_idx']
    player['active_idx'] = new_idx
    
    # Street mode: switching costs a turn
    # Official/Tournament: switching is free when forced (faint) but costs turn if voluntary
    is_forced = player['team'][old_idx].get('currentHp', 0) <= 0 if old_idx is not None else False
    
    if not is_forced:
        # Voluntary switch costs the turn
        advance_turn(battle)
    
    return True, "switch_success"


def apply_damage(battle, attacker_key, damage, move_name='', message=''):
    """Apply damage from attacker to defender's active pokemon."""
    defender_key = 'player2' if attacker_key == 'player1' else 'player1'
    defender = battle[defender_key]

    active_poke = defender['team'][defender['active_idx']]
    old_hp = active_poke.get('currentHp', active_poke.get('maxHp', 20))
    raw_hp = old_hp - damage
    new_hp = max(-999, raw_hp)  # allow negative for permadeath detection
    active_poke['currentHp'] = new_hp

    battle['log'].append({
        'type': 'attack',
        'attacker': attacker_key,
        'move': move_name,
        'damage': damage,
        'message': message,
        'defender_hp': max(0, new_hp),
        'defender_max_hp': active_poke.get('maxHp', 20)
    })

    # Check if pokemon fainted
    if new_hp <= 0:
        is_permadeath = raw_hp <= -30
        if is_permadeath:
            active_poke['permanently_dead'] = True
            battle['last_permadeath'] = {
                'player_key': defender_key,
                'player_id': battle[defender_key]['id'],
                'pokemon_name': active_poke.get('nickname') or active_poke.get('name', '?'),
                'pokemon': active_poke
            }
        battle['log'].append({'type': 'faint', 'player': defender_key, 'permadeath': is_permadeath})
        # Check if defender has any alive pokemon left
        alive = [i for i, p in enumerate(defender['team']) 
                 if p.get('currentHp', p.get('maxHp', 20)) > 0 and i != defender['active_idx']]
        
        # In official/tournament, also filter by used_pokemon
        if battle['mode'] in ('official', 'tournament'):
            alive = [i for i in alive if i not in defender['used_pokemon']]
        
        if not alive:
            # Battle over - attacker wins
            battle['phase'] = 'finished'
            battle['winner'] = attacker_key
            return 'battle_end'
        else:
            # Defender must switch - don't advance turn yet
            return 'must_switch'
    
    # Advance turn
    advance_turn(battle)
    return 'continue'


def advance_turn(battle):
    """Switch to the other player's turn."""
    battle['turn'] = 'player2' if battle['turn'] == 'player1' else 'player1'
    if battle['turn'] == 'player1':
        battle['round'] += 1


def get_battle_state_for_player(battle, player_key):
    """Get battle state visible to a specific player."""
    opponent_key = 'player2' if player_key == 'player1' else 'player1'
    player = battle[player_key]
    opponent = battle[opponent_key]
    
    state = {
        'id': battle['id'],
        'mode': battle['mode'],
        'phase': battle['phase'],
        'turn': battle['turn'],
        'round': battle['round'],
        'you_are': player_key,
        'your_team': player['team'],
        'your_active_idx': player['active_idx'],
        'your_used_pokemon': player['used_pokemon'],
        'opponent_active': None,
        'opponent_team_count': len(opponent['team']),
        'opponent_alive_count': sum(1 for p in opponent['team'] if max(0, p.get('currentHp', p.get('maxHp', 20))) > 0),
        'winner': battle.get('winner'),
        'log': battle.get('log', [])[-20:]  # last 20 log entries
    }
    
    # Include own active pokemon's status
    if player['active_idx'] is not None:
        own_active = player['team'][player['active_idx']]
        state['your_status'] = own_active.get('status')

    # Only reveal opponent's active pokemon if battle has started
    if battle['phase'] in ('battle', 'finished') and opponent['active_idx'] is not None:
        active = opponent['team'][opponent['active_idx']]
        state['opponent_active'] = {
            'name': active.get('name', '???'),
            'nickname': active.get('nickname', ''),
            'level': active.get('level', 1),
            'types': active.get('types', []),
            'currentHp': max(0, active.get('currentHp', active.get('maxHp', 20))),
            'maxHp': active.get('maxHp', 20),
            'ac': active.get('ac', 10),
            'number': active.get('number', 0),
            'stats': active.get('stats', {}),
            'moves': active.get('moves', []),
            'speed': active.get('speed', '30ft')
        }
    
    return state


def apply_status(battle, player_key, status_condition):
    """Apply a status condition to the active pokemon. Returns True if applied."""
    player = battle[player_key]
    active = player['team'][player['active_idx']]
    if active.get('status'):
        return False  # already statused
    active['status'] = dict(status_condition, turns_active=0)
    return True


def process_turn_status(battle, player_key):
    """Process status damage at turn start for the active pokemon.
    Returns (damage_dealt, status_dict_or_None)."""
    player = battle[player_key]
    active = player['team'][player['active_idx']]
    status = active.get('status')
    if not status:
        return 0, None

    condition = status.get('condition', '')
    turns = status.get('turns_active', 0) + 1
    status['turns_active'] = turns
    active['status'] = status

    max_hp = active.get('maxHp', 20)
    damage = 0

    if condition in ('badly_poisoned', 'queimado'):
        damage = max(1, int(max_hp * turns / 8))
        active['currentHp'] = max(0, active.get('currentHp', 0) - damage)
    # paralysis / sleep — no HP damage, handled client-side for skip

    return damage, status


def clear_status(battle, player_key):
    """Clear status from active pokemon."""
    player = battle[player_key]
    active = player['team'][player['active_idx']]
    active.pop('status', None)


def npc_choose_action(battle, npc_key):
    """NPC AI: choose a random move from active pokemon's moveset."""
    player = battle[npc_key]
    active = player['team'][player['active_idx']]
    moves = active.get('moves', ['Tackle'])
    if not moves:
        moves = ['Tackle']
    return random.choice(moves)


def npc_choose_pokemon(battle, npc_key):
    """NPC AI: choose next pokemon when current faints."""
    player = battle[npc_key]
    alive = [i for i, p in enumerate(player['team']) 
             if p.get('currentHp', p.get('maxHp', 20)) > 0 and i != player['active_idx']]
    if battle['mode'] in ('official', 'tournament'):
        alive = [i for i in alive if i not in player['used_pokemon']]
    if alive:
        return random.choice(alive)
    return None


def calculate_street_loot(loser_trainer_data):
    """Calculate what the winner steals in street mode: 2 random items + 25% money."""
    bag = loser_trainer_data.get('bag', [])
    money = loser_trainer_data.get('money', 0)
    
    stolen_money = int(money * 0.25)
    stolen_items = []
    
    if bag:
        # Pick up to 2 random items
        available = [i for i in bag if isinstance(i, dict) and i.get('qty', 0) > 0]
        pick_count = min(2, len(available))
        if pick_count > 0:
            chosen = random.sample(available, pick_count)
            for item in chosen:
                stolen_items.append({'name': item['name'], 'qty': 1, 'file': item.get('file', '')})
    
    return stolen_money, stolen_items


def create_tournament(name, prize_config, max_participants=16):
    """Create a tournament bracket."""
    tournament_id = f"tourney_{secrets.token_hex(4)}"
    return {
        'id': tournament_id,
        'name': name,
        'status': 'registration',  # registration, in_progress, finished
        'max_participants': max_participants,
        'participants': [],  # list of {id, name, is_npc, team}
        'bracket': [],       # generated when tournament starts
        'current_round': 0,
        'prizes': prize_config,  # {first: {money, items, pokemon}, second: {...}, third: {...}}
        'results': {}
    }


def generate_bracket(tournament):
    """Generate single elimination bracket from participants."""
    participants = tournament['participants'][:]
    random.shuffle(participants)
    
    # Pad to power of 2 if needed (byes)
    while len(participants) < tournament['max_participants']:
        participants.append(None)  # bye
    
    bracket = []
    for i in range(0, len(participants), 2):
        match = {
            'id': f"match_{secrets.token_hex(3)}",
            'round': 1,
            'player1': participants[i],
            'player2': participants[i + 1] if i + 1 < len(participants) else None,
            'winner': None,
            'battle_id': None
        }
        # Auto-win if opponent is None (bye)
        if match['player2'] is None and match['player1'] is not None:
            match['winner'] = match['player1']['id']
        elif match['player1'] is None and match['player2'] is not None:
            match['winner'] = match['player2']['id']
        bracket.append(match)
    
    tournament['bracket'] = bracket
    tournament['current_round'] = 1
    tournament['status'] = 'in_progress'
    return bracket
