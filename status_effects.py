"""
Status Effects System for Pokemon 5e RPG.
Defines conditions, their effects per turn, and which moves apply them.

Based on Pokemon 5e rules + PokemonDB general mechanics.
"""
import random
from re import search as _re_search
import json as _json
import os as _os

# ============================================================
# EFEITOS CANÔNICOS POR MOVE (gerado por tools/build_canonical_moves.py
# a partir dos CSVs do PokeAPI — mesma base do pokemondb/Bulbapedia —
# com overlay do mapa curado KNOWN_EFFECTS/MOVE_STATUS_EFFECTS).
# Chave: nome do move em minúsculas. Valores: {'effect': {...}, 'on_hit': {...}}.
# ============================================================
_MOVE_EFFECTS_FILE = _os.path.join(_os.path.dirname(__file__),
                                   'server', 'data', 'move_effects.json')
try:
    with open(_MOVE_EFFECTS_FILE, encoding='utf-8') as _f:
        MOVE_EFFECTS_DATA = _json.load(_f)
except (FileNotFoundError, ValueError):
    MOVE_EFFECTS_DATA = {}

# ============================================================
# STATUS CONDITIONS
# ============================================================
STATUS_CONDITIONS = {
    'badly_poisoned': {
        'name': 'Envenenado',
        'icon': '☠️',
        'color': '#7030a0',
        'turn_effect': 'scaling_damage',
        'base_fraction': 8,               # 1/8, 2/8, 3/8...
        'can_act': True,
        'duration': 'permanent',
        'description': 'Perde HP crescente (1/8, 2/8, 3/8...). Dura até ser curado.'
    },
    'queimado': {
        'name': 'Queimado',
        'icon': '🔥',
        'color': '#f08030',
        'turn_effect': 'scaling_damage',
        'base_fraction': 8,               # 1/8, 2/8, 3/8...
        'can_act': True,
        'stat_modifier': {'ATK': -2},    # queimadura reduz ataque físico
        'duration': 'permanent',
        'description': 'Perde HP crescente (1/8, 2/8...) e -2 ATK. Dura até ser curado.'
    },
    'paralisado': {
        'name': 'Paralisado',
        'icon': '⚡',
        'color': '#f8d030',
        'turn_effect': 'skip_chance',
        'skip_chance': 0.25,             # 25% chance to not act
        'can_act': True,                 # can act (but might fail)
        'stat_modifier': {'DEX': -3},    # reduced speed/dex
        'duration': 'permanent',
        'description': '25% de chance de não agir. -3 em DEX (velocidade reduzida).'
    },
    'dormindo': {
        'name': 'Dormindo',
        'icon': '💤',
        'color': '#6890f0',
        'turn_effect': 'skip',
        'can_act': False,
        'wake_check': True,              # d20 >= 12 to wake up
        'wake_dc': 12,
        'duration': 'turns',
        'max_turns': 3,
        'description': 'Não pode agir. No início do turno, rola d20: ≥12 acorda.'
    },
    'congelado': {
        'name': 'Congelado',
        'icon': '🧊',
        'color': '#98d8d8',
        'turn_effect': 'skip',
        'can_act': False,
        'thaw_check': True,              # d20 >= 15 to thaw
        'thaw_dc': 15,
        'duration': 'permanent',
        'description': 'Não pode agir. No início do turno, rola d20: ≥15 descongela. Moves de fogo descongelam.'
    },
    'confuso': {
        'name': 'Confuso',
        'icon': '💫',
        'color': '#f85888',
        'turn_effect': 'self_damage_chance',
        'self_damage_chance': 0.33,      # 33% hits self
        'self_damage': '1d6',
        'can_act': True,
        'duration': 'turns',
        'max_turns': 4,
        'description': '33% de chance de se machucar (1d6 dano) em vez de agir. Dura até 4 turnos.'
    },
    'atordoado': {
        'name': 'Atordoado',
        'icon': '😵',
        'color': '#705848',
        'turn_effect': 'skip',
        'can_act': False,
        'duration': 'turns',
        'max_turns': 1,                  # flinch = 1 turn only
        'description': 'Perde o próximo turno (flinch). Remove após 1 turno.'
    },
    'amedrontado': {
        'name': 'Amedrontado',
        'icon': '😰',
        'color': '#705898',
        'turn_effect': 'disadvantage',
        'can_act': True,
        'attack_modifier': -3,
        'duration': 'turns',
        'max_turns': 2,
        'description': '-3 nos ataques por 2 turnos.'
    }
}

# ============================================================
# MOVE → STATUS MAPPING
# Maps move names to the status they can inflict + chance
# ============================================================
MOVE_STATUS_EFFECTS = {
    # Poison moves
    'Poison Jab': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Poison Sting': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Sludge Bomb': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Sludge Wave': {'status': 'badly_poisoned', 'chance': 0.10, 'on': 'hit'},
    'Gunk Shot': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Cross Poison': {'status': 'badly_poisoned', 'chance': 0.10, 'on': 'hit'},
    'Poison Fang': {'status': 'badly_poisoned', 'chance': 0.50, 'on': 'hit'},
    'Toxic': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Poison Powder': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Poison Gas': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Sludge': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Mud Bomb': {'status': 'badly_poisoned', 'chance': 0.30, 'on': 'hit'},
    'Venom Drench': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'hit'},
    'Acid': {'status': 'badly_poisoned', 'chance': 0.10, 'on': 'hit'},
    'Acid Spray': {'status': 'badly_poisoned', 'chance': 0.10, 'on': 'hit'},
    'Poison Tail': {'status': 'badly_poisoned', 'chance': 0.10, 'on': 'hit'},
    'Baneful Bunker': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'contact'},
    
    # Burn moves
    'Ember': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Flamethrower': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Fire Blast': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Fire Punch': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Lava Plume': {'status': 'queimado', 'chance': 0.30, 'on': 'hit'},
    'Scald': {'status': 'queimado', 'chance': 0.30, 'on': 'hit'},
    'Blaze Kick': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Sacred Fire': {'status': 'queimado', 'chance': 0.50, 'on': 'hit'},
    'Will-O-Wisp': {'status': 'queimado', 'chance': 1.0, 'on': 'save_fail', 'save': 'DEX'},
    'Inferno': {'status': 'queimado', 'chance': 1.0, 'on': 'hit'},
    'Beak Blast': {'status': 'queimado', 'chance': 1.0, 'on': 'contact'},
    
    # Paralysis moves
    'Thunder Wave': {'status': 'paralisado', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Stun Spore': {'status': 'paralisado', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Nuzzle': {'status': 'paralisado', 'chance': 1.0, 'on': 'hit'},
    'Thunder': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Thunderbolt': {'status': 'paralisado', 'chance': 0.10, 'on': 'hit'},
    'Thunder Punch': {'status': 'paralisado', 'chance': 0.10, 'on': 'hit'},
    'Spark': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Body Slam': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Lick': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Force Palm': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Bounce': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Discharge': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    'Zap Cannon': {'status': 'paralisado', 'chance': 1.0, 'on': 'hit'},
    'Bolt Strike': {'status': 'paralisado', 'chance': 0.20, 'on': 'hit'},
    
    # Sleep moves
    'Hypnosis': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Sleep Powder': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Spore': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Sing': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Grass Whistle': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Lovely Kiss': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Dark Void': {'status': 'dormindo', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Yawn': {'status': 'dormindo', 'chance': 1.0, 'on': 'next_turn', 'save': 'CON'},
    'Relic Song': {'status': 'dormindo', 'chance': 0.10, 'on': 'hit'},
    
    # Freeze moves
    'Ice Beam': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
    'Blizzard': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
    'Ice Punch': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
    'Freeze-Dry': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
    'Powder Snow': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
    'Freeze Shock': {'status': 'paralisado', 'chance': 0.30, 'on': 'hit'},
    
    # Confusion moves
    'Confuse Ray': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Confusion': {'status': 'confuso', 'chance': 0.10, 'on': 'hit'},
    'Psybeam': {'status': 'confuso', 'chance': 0.10, 'on': 'hit'},
    'Signal Beam': {'status': 'confuso', 'chance': 0.10, 'on': 'hit'},
    'Dizzy Punch': {'status': 'confuso', 'chance': 0.20, 'on': 'hit'},
    'Dynamic Punch': {'status': 'confuso', 'chance': 1.0, 'on': 'hit'},
    'Chatter': {'status': 'confuso', 'chance': 1.0, 'on': 'hit'},
    'Hurricane': {'status': 'confuso', 'chance': 0.30, 'on': 'hit'},
    'Water Pulse': {'status': 'confuso', 'chance': 0.20, 'on': 'hit'},
    'Supersonic': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Sweet Kiss': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Swagger': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Flatter': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Teeter Dance': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    
    # Flinch/Stun moves (atordoado = loses next turn if hit)
    'Air Slash': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Astonish': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Bite': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Dark Pulse': {'status': 'atordoado', 'chance': 0.20, 'on': 'nat15plus'},
    'Dragon Rush': {'status': 'atordoado', 'chance': 0.20, 'on': 'nat15plus'},
    'Extrasensory': {'status': 'atordoado', 'chance': 0.10, 'on': 'nat15plus'},
    'Fake Out': {'status': 'atordoado', 'chance': 1.0, 'on': 'hit'},
    'Fire Fang': {'status': 'atordoado', 'chance': 0.10, 'on': 'nat15plus'},
    'Headbutt': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Heart Stamp': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Hyper Fang': {'status': 'atordoado', 'chance': 0.10, 'on': 'nat15plus'},
    'Ice Fang': {'status': 'atordoado', 'chance': 0.10, 'on': 'nat15plus'},
    'Icicle Crash': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Iron Head': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Needle Arm': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Rock Slide': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Rolling Kick': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Sky Attack': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Snore': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Stomp': {'status': 'atordoado', 'chance': 0.30, 'on': 'nat15plus'},
    'Thunder Fang': {'status': 'atordoado', 'chance': 0.10, 'on': 'nat15plus'},
    'Twister': {'status': 'atordoado', 'chance': 0.20, 'on': 'nat15plus'},
    'Waterfall': {'status': 'atordoado', 'chance': 0.20, 'on': 'nat15plus'},
    'Zen Headbutt': {'status': 'atordoado', 'chance': 0.20, 'on': 'nat15plus'},
    
    # Stat modifiers (buffs/debuffs) - these don't apply a "condition" but modify stats
    'Growl': {'status': 'debuff', 'stat': 'STR', 'value': -1, 'on': 'save_fail', 'save': 'WIS'},
    'Leer': {'status': 'debuff', 'stat': 'AC', 'value': -1, 'on': 'save_fail', 'save': 'WIS'},
    'Tail Whip': {'status': 'debuff', 'stat': 'AC', 'value': -1, 'on': 'save_fail', 'save': 'WIS'},
    'Screech': {'status': 'debuff', 'stat': 'AC', 'value': -2, 'on': 'save_fail', 'save': 'CON'},
    'Charm': {'status': 'debuff', 'stat': 'STR', 'value': -2, 'on': 'save_fail', 'save': 'WIS'},
    'Scary Face': {'status': 'debuff', 'stat': 'DEX', 'value': -2, 'on': 'save_fail', 'save': 'WIS'},
    'String Shot': {'status': 'debuff', 'stat': 'DEX', 'value': -2, 'on': 'save_fail', 'save': 'DEX'},
    'Cotton Spore': {'status': 'debuff', 'stat': 'DEX', 'value': -3, 'on': 'save_fail', 'save': 'DEX'},
    'Smokescreen': {'status': 'debuff', 'stat': 'attack_roll', 'value': -3, 'on': 'save_fail', 'save': 'CON'},
    'Sand Attack': {'status': 'debuff', 'stat': 'attack_roll', 'value': -3, 'on': 'save_fail', 'save': 'DEX'},
    'Flash': {'status': 'debuff', 'stat': 'attack_roll', 'value': -3, 'on': 'save_fail', 'save': 'CON'},
    'Kinesis': {'status': 'debuff', 'stat': 'attack_roll', 'value': -2, 'on': 'save_fail', 'save': 'WIS'},
}


# PT power abbreviations → stat keys (new system first, legacy fallback)
_POWER_TO_STATS = {
    'FOR': ('ATK', 'STR'),
    'DES': ('SPE', 'DEX'),
    'CON': ('DEF', 'CON'),
    'INT': ('SPA', 'INT'),
    'SAB': ('SPD', 'WIS'),
    'CAR': ('SPA', 'CHA'),
}

# Saving throw stat → pokemon stat (new system first, legacy fallback)
_SAVE_TO_STATS = {
    'STR': ('ATK', 'STR'),
    'DEX': ('SPE', 'DEX'),
    'CON': ('DEF', 'CON'),
    'INT': ('SPA', 'INT'),
    'WIS': ('SPD', 'WIS'),
    'CHA': ('SPD', 'CHA'),
}


def _stat_value(stats: dict, keys) -> int:
    """Get first available stat value from a (new, legacy) key pair."""
    for key in keys:
        val = stats.get(key)
        if isinstance(val, (int, float)) and val:
            return int(val)
    return 10


def _best_attacker_mod(attacker_stats: dict, power: str) -> int:
    """Best ability modifier among the stats listed in a move's power field."""
    power = (power or '').upper()
    best = 0
    for abbrev, keys in _POWER_TO_STATS.items():
        if abbrev in power:
            best = max(best, (_stat_value(attacker_stats, keys) - 10) // 2)
    if not best:
        # No power field → use the better of ATK/SPA
        best = max(
            (_stat_value(attacker_stats, ('ATK', 'STR')) - 10) // 2,
            (_stat_value(attacker_stats, ('SPA', 'INT')) - 10) // 2,
            0
        )
    return best


def _save_mod(target_stats: dict, save_stat: str) -> int:
    """Target's saving throw modifier for a given save stat."""
    keys = _SAVE_TO_STATS.get((save_stat or 'WIS').upper(), ('SPD', 'WIS'))
    return (_stat_value(target_stats, keys) - 10) // 2


def check_status_on_hit(move_name, attack_roll, damage_dealt):
    """Check if a move inflicts a status effect on hit.
    Returns (status_key, inflicted) or (None, False).
    """
    # Dados canônicos primeiro (chances reais dos jogos); mapa curado como fallback
    entry = MOVE_EFFECTS_DATA.get((move_name or '').lower())
    effect = (entry or {}).get('on_hit') or MOVE_STATUS_EFFECTS.get(move_name)
    if not effect:
        return None, False

    trigger = effect.get('on', 'hit')
    chance = effect.get('chance', 0)
    
    if trigger == 'hit' and damage_dealt > 0:
        if random.random() < chance:
            return effect['status'], True
    elif trigger == 'nat15plus' and attack_roll >= 15 and damage_dealt > 0:
        if random.random() < chance:
            return effect['status'], True
    elif trigger in ('save_fail', 'next_turn'):
        # Treat as automatic on hit (server can roll saving throw if needed)
        if random.random() < chance:
            return effect['status'], True

    return None, False


def process_turn_start(pokemon_status, max_hp):
    """Process status effects at the start of a pokemon's turn.
    Returns (can_act: bool, damage: int, messages: list, status_removed: bool).
    """
    if not pokemon_status:
        return True, 0, [], False
    
    status_key = pokemon_status.get('condition')
    condition = STATUS_CONDITIONS.get(status_key)
    if not condition:
        return True, 0, [], False
    
    messages = []
    damage = 0
    can_act = True
    status_removed = False
    turns_active = pokemon_status.get('turns_active', 0) + 1
    pokemon_status['turns_active'] = turns_active
    
    turn_effect = condition.get('turn_effect')
    
    if turn_effect == 'damage':
        fraction = condition.get('damage_fraction', 8)
        damage = max(1, max_hp // fraction)
        messages.append(f"{condition['icon']} {condition['name']}: -{damage} HP")
    
    elif turn_effect == 'scaling_damage':
        fraction = condition.get('base_fraction', 16)
        damage = max(1, (max_hp * turns_active) // fraction)
        messages.append(f"{condition['icon']} {condition['name']}: -{damage} HP (turno {turns_active})")
    
    elif turn_effect == 'skip':
        can_act = False
        messages.append(f"{condition['icon']} {condition['name']}: Não pode agir!")
        # Check wake/thaw
        if condition.get('wake_check'):
            roll = random.randint(1, 20)
            if roll >= condition['wake_dc']:
                can_act = True
                status_removed = True
                messages.append(f"🎲 d20({roll}) ≥ {condition['wake_dc']} → Acordou!")
            else:
                messages.append(f"🎲 d20({roll}) < {condition['wake_dc']} → Continua dormindo...")
        elif condition.get('thaw_check'):
            roll = random.randint(1, 20)
            if roll >= condition['thaw_dc']:
                can_act = True
                status_removed = True
                messages.append(f"🎲 d20({roll}) ≥ {condition['thaw_dc']} → Descongelou!")
            else:
                messages.append(f"🎲 d20({roll}) < {condition['thaw_dc']} → Ainda congelado...")
    
    elif turn_effect == 'skip_chance':
        skip_chance = condition.get('skip_chance', 0.25)
        if random.random() < skip_chance:
            can_act = False
            messages.append(f"{condition['icon']} {condition['name']}: Corpo paralisado! Não conseguiu agir.")
        else:
            messages.append(f"{condition['icon']} {condition['name']}: Superou a paralisia!")
    
    elif turn_effect == 'self_damage_chance':
        self_chance = condition.get('self_damage_chance', 0.33)
        if random.random() < self_chance:
            damage = random.randint(1, 6)
            can_act = False
            messages.append(f"{condition['icon']} {condition['name']}: Se machucou na confusão! -{damage} HP")
    
    elif turn_effect == 'disadvantage':
        messages.append(f"{condition['icon']} {condition['name']}: Atacando com desvantagem (-3)")
    
    # Check duration
    if condition.get('duration') == 'turns':
        max_turns = condition.get('max_turns', 3)
        if turns_active >= max_turns:
            status_removed = True
            messages.append(f"✨ {condition['name']} passou!")
    
    return can_act, damage, messages, status_removed


def get_attack_modifier(pokemon_status):
    """Get attack modifier from active status conditions."""
    if not pokemon_status:
        return 0
    status_key = pokemon_status.get('condition')
    condition = STATUS_CONDITIONS.get(status_key, {})
    return condition.get('attack_modifier', 0)


def get_stat_modifiers(pokemon_status):
    """Get stat modifiers from active status conditions."""
    if not pokemon_status:
        return {}
    status_key = pokemon_status.get('condition')
    condition = STATUS_CONDITIONS.get(status_key, {})
    return condition.get('stat_modifier', {})


# ============================================================
# STAT STAGES — buffs/debuffs acumulados por batalha
# ------------------------------------------------------------
# Moves de status (Growl, Leer, Swords Dance...) empilham bônus/penalidades
# PLANOS estilo D&D no dict do pokémon sob 'stat_stages'. Persistem pela
# batalha e são consumidos pelo cálculo autoritativo do servidor:
#   - ATK/SPA do atacante entram no DANO (via stat efetivo)
#   - DEF/SPD do defensor entram na CA (via stat efetivo)
#   - 'AC' entra direto na CA; 'attack_roll' entra direto no acerto
# A condição ativa (queimado/paralisado) também soma pelo mesmo caminho.
# ============================================================
STAGE_KEYS = ('ATK', 'DEF', 'SPA', 'SPD', 'SPE', 'AC', 'attack_roll')
STAGE_CLAMP = 6
# condição legada usa DEX; o sistema novo usa SPE
_COND_STAT_ALIAS = {'DEX': 'SPE', 'STR': 'ATK', 'INT': 'SPA', 'WIS': 'SPD'}


def init_stat_stages():
    return {k: 0 for k in STAGE_KEYS}


def apply_stat_changes(pokemon, stat_changes, clamp=STAGE_CLAMP):
    """Acumula {stat: value} em pokemon['stat_stages'], limitado a [-clamp, clamp].
    Ignora chaves fora de STAGE_KEYS. Retorna o dict de stages atualizado."""
    if not isinstance(pokemon, dict) or not stat_changes:
        return (pokemon or {}).get('stat_stages') if isinstance(pokemon, dict) else {}
    stages = pokemon.get('stat_stages')
    if not stages:
        stages = init_stat_stages()
        pokemon['stat_stages'] = stages
    for stat, val in stat_changes.items():
        key = _COND_STAT_ALIAS.get(stat, stat)
        if key in stages:
            stages[key] = max(-clamp, min(clamp, stages[key] + int(val)))
    return stages


def _cond_stat_mod(pokemon, stat):
    """Modificador de stat vindo da CONDIÇÃO ativa (queimado -ATK etc.)."""
    mods = get_stat_modifiers(pokemon.get('status')) if isinstance(pokemon, dict) else {}
    total = 0
    for k, v in mods.items():
        if _COND_STAT_ALIAS.get(k, k) == stat:
            total += int(v)
    return total


def effective_stat(pokemon, stat):
    """Stat efetivo = base + stage acumulado + modificador de condição ativa."""
    if not isinstance(pokemon, dict):
        return 10
    base = int((pokemon.get('stats') or {}).get(stat, 10) or 10)
    stage = int((pokemon.get('stat_stages') or {}).get(stat, 0))
    return base + stage + _cond_stat_mod(pokemon, stat)


def attack_roll_bonus(pokemon):
    """Bônus/penalidade na ROLAGEM de acerto (stage 'attack_roll' + condição)."""
    if not isinstance(pokemon, dict):
        return 0
    stage = int((pokemon.get('stat_stages') or {}).get('attack_roll', 0))
    total = stage + get_attack_modifier(pokemon.get('status'))
    return max(-STAGE_CLAMP, min(STAGE_CLAMP, total))


def ac_bonus(pokemon):
    """Bônus/penalidade direta na CA (stage 'AC')."""
    if not isinstance(pokemon, dict):
        return 0
    return max(-STAGE_CLAMP, min(STAGE_CLAMP, int((pokemon.get('stat_stages') or {}).get('AC', 0))))


def reset_stat_stages(pokemon):
    """Zera as stages (troca de pokémon / fim de batalha)."""
    if isinstance(pokemon, dict) and pokemon.get('stat_stages'):
        pokemon['stat_stages'] = init_stat_stages()



# ============================================================
# AUTO-DETECT STATUS EFFECT FROM MOVE DESCRIPTION
# For moves not explicitly in MOVE_STATUS_EFFECTS
# ============================================================

def auto_detect_move_effect(move_data):
    """Analyze a move's description (PT/EN) and name to determine what effect it should have.
    Returns a dict describing the effect, or None if no effect detected.
    
    Bilingual: checks Portuguese AND English keywords.
    Also uses move name as fallback for known moves.
    """
    if not move_data:
        return None
    
    desc = (move_data.get('description', '') or '').lower()
    name = (move_data.get('name', '') or '')
    name_lower = name.lower()

    # ========== DADOS CANÔNICOS (prioridade máxima) ==========
    # move_effects.json já inclui o overlay curado, então cobre todos os
    # 263 moves de status com o efeito real dos jogos.
    _data_entry = MOVE_EFFECTS_DATA.get(name_lower)
    if _data_entry and _data_entry.get('effect'):
        return _data_entry['effect']

    # ========== KNOWN MOVES BY NAME (mapa curado, fallback) ==========
    KNOWN_EFFECTS = {
        # Confusion
        'supersonic': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        'confuse ray': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        'swagger': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        'flatter': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        'sweet kiss': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        'teeter dance': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        # Sleep
        'hypnosis': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'},
        'sleep powder': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'CON'},
        'spore': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'CON'},
        'sing': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'},
        'grass whistle': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'},
        'lovely kiss': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'},
        'dark void': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'},
        'yawn': {'type': 'inflict_status', 'status': 'dormindo', 'save': 'CON'},
        # Paralysis
        'thunder wave': {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'},
        'stun spore': {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'},
        'glare': {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'},
        'nuzzle': {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'},
        # Poison
        'toxic': {'type': 'inflict_status', 'status': 'badly_poisoned', 'save': 'CON'},
        'poison powder': {'type': 'inflict_status', 'status': 'badly_poisoned', 'save': 'CON'},
        'poison gas': {'type': 'inflict_status', 'status': 'badly_poisoned', 'save': 'CON'},
        # Burn
        'will-o-wisp': {'type': 'inflict_status', 'status': 'queimado', 'save': 'DEX'},
        # Accuracy down
        'smokescreen': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'CON', 'duration': 3},
        'sand attack': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'DEX', 'duration': 3},
        'flash': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'CON', 'duration': 3},
        'kinesis': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 3},
        'mud-slap': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'DEX', 'duration': 3},
        'muddy water': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -1, 'save': 'DEX', 'duration': 2},
        'octazooka': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'DEX', 'duration': 3},
        # Attack down
        'growl': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 3},
        'charm': {'type': 'debuff_target', 'stat': 'ATK', 'value': -3, 'save': 'WIS', 'duration': 3},
        'baby-doll eyes': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 3},
        'feather dance': {'type': 'debuff_target', 'stat': 'ATK', 'value': -3, 'save': 'WIS', 'duration': 3},
        'tickle': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 3},
        # Defense down
        'leer': {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'WIS', 'duration': 3},
        'tail whip': {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'WIS', 'duration': 3},
        'screech': {'type': 'debuff_target', 'stat': 'DEF', 'value': -3, 'save': 'CON', 'duration': 3},
        'fake tears': {'type': 'debuff_target', 'stat': 'SPD', 'value': -3, 'save': 'WIS', 'duration': 3},
        'metal sound': {'type': 'debuff_target', 'stat': 'SPD', 'value': -3, 'save': 'CON', 'duration': 3},
        # Speed down
        'scary face': {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'WIS', 'duration': 3},
        'string shot': {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'DEX', 'duration': 3},
        'cotton spore': {'type': 'debuff_target', 'stat': 'SPE', 'value': -4, 'save': 'DEX', 'duration': 3},
        'sticky web': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'DEX', 'duration': 5},
        'electroweb': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'DEX', 'duration': 3},
        # Flinch/Fear
        'fake out': {'type': 'inflict_status', 'status': 'atordoado', 'save': 'CON'},
        # Self buffs - Attack
        'swords dance': {'type': 'buff_self', 'stat': 'ATK', 'value': 4, 'duration': 3},
        'howl': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        'hone claws': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        'work up': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        'belly drum': {'type': 'buff_self', 'stat': 'ATK', 'value': 6, 'duration': 5},
        'dragon dance': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        'bulk up': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        # Self buffs - Sp.Attack
        'nasty plot': {'type': 'buff_self', 'stat': 'SPA', 'value': 4, 'duration': 3},
        'calm mind': {'type': 'buff_self', 'stat': 'SPA', 'value': 2, 'duration': 3},
        'quiver dance': {'type': 'buff_self', 'stat': 'SPA', 'value': 2, 'duration': 3},
        'tail glow': {'type': 'buff_self', 'stat': 'SPA', 'value': 4, 'duration': 3},
        # Self buffs - Defense
        'barrier': {'type': 'buff_self', 'stat': 'DEF', 'value': 3, 'duration': 3},
        'iron defense': {'type': 'buff_self', 'stat': 'DEF', 'value': 3, 'duration': 3},
        'harden': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3},
        'withdraw': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3},
        'acid armor': {'type': 'buff_self', 'stat': 'DEF', 'value': 3, 'duration': 3},
        'cotton guard': {'type': 'buff_self', 'stat': 'DEF', 'value': 4, 'duration': 3},
        'defend order': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3},
        'cosmic power': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3},
        # Self buffs - Sp.Defense
        'amnesia': {'type': 'buff_self', 'stat': 'SPD', 'value': 3, 'duration': 3},
        'light screen': {'type': 'buff_self', 'stat': 'SPD', 'value': 3, 'duration': 5},
        'reflect': {'type': 'buff_self', 'stat': 'DEF', 'value': 3, 'duration': 5},
        # Self buffs - Speed
        'agility': {'type': 'buff_self', 'stat': 'SPE', 'value': 4, 'duration': 3},
        'rock polish': {'type': 'buff_self', 'stat': 'SPE', 'value': 4, 'duration': 3},
        'autotomize': {'type': 'buff_self', 'stat': 'SPE', 'value': 4, 'duration': 3},
        'shell smash': {'type': 'buff_self', 'stat': 'SPE', 'value': 3, 'duration': 3},
        'shift gear': {'type': 'buff_self', 'stat': 'SPE', 'value': 3, 'duration': 3},
        # Self buffs - Evasion/AC
        'double team': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3},
        'minimize': {'type': 'buff_self', 'stat': 'AC', 'value': 3, 'duration': 3},
        # Healing
        'recover': {'type': 'heal_self', 'amount': 'half'},
        'roost': {'type': 'heal_self', 'amount': 'half'},
        'soft-boiled': {'type': 'heal_self', 'amount': 'half'},
        'milk drink': {'type': 'heal_self', 'amount': 'half'},
        'synthesis': {'type': 'heal_self', 'amount': 'half'},
        'moonlight': {'type': 'heal_self', 'amount': 'half'},
        'morning sun': {'type': 'heal_self', 'amount': 'half'},
        'slack off': {'type': 'heal_self', 'amount': 'half'},
        'rest': {'type': 'heal_self', 'amount': 'full'},
        'wish': {'type': 'heal_self', 'amount': 'half'},
        'heal order': {'type': 'heal_self', 'amount': 'half'},
        'heal pulse': {'type': 'heal_self', 'amount': 'half'},
        'ingrain': {'type': 'heal_self', 'amount': 'quarter'},
        'swallow': {'type': 'heal_self', 'amount': 'half'},
        # Protect
        'protect': {'type': 'protect', 'duration': 1},
        'detect': {'type': 'protect', 'duration': 1},
        'endure': {'type': 'protect', 'duration': 1},
        'spiky shield': {'type': 'protect', 'duration': 1},
        'king\'s shield': {'type': 'protect', 'duration': 1},
        'baneful bunker': {'type': 'protect', 'duration': 1},
        # Weather
        'rain dance': {'type': 'weather', 'weather': 'rain', 'duration': 5},
        'sunny day': {'type': 'weather', 'weather': 'sun', 'duration': 5},
        'sandstorm': {'type': 'weather', 'weather': 'sandstorm', 'duration': 5},
        'hail': {'type': 'weather', 'weather': 'hail', 'duration': 5},
        # Taunt/Encore
        'taunt': {'type': 'debuff_target', 'stat': 'no_status_moves', 'value': -1, 'save': 'WIS', 'duration': 3},
        'encore': {'type': 'debuff_target', 'stat': 'locked_move', 'value': -1, 'save': 'WIS', 'duration': 3},
        'disable': {'type': 'debuff_target', 'stat': 'locked_move', 'value': -1, 'save': 'WIS', 'duration': 3},
        'torment': {'type': 'debuff_target', 'stat': 'locked_move', 'value': -1, 'save': 'WIS', 'duration': 3},
        # Attract
        'attract': {'type': 'inflict_status', 'status': 'amedrontado', 'save': 'WIS'},
        # Buffs de CA / ataque (5e homebrew)
        'defense curl': {'type': 'buff_self', 'stat': 'AC', 'value': 4, 'duration': 1},
        'focus energy': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3},
        'coil': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 1, 'duration': 3},
        'meditate': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 1, 'duration': 3},
        'sharpen': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3},
        'growth': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3},
        'sweet scent': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 3, 'duration': 2},
        'laser focus': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 1},
        'lock-on': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 4, 'duration': 1},
        'mind reader': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 4, 'duration': 1},
        # Debuffs conhecidos
        'noble roar': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 2},
        'captivate': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'CHA', 'duration': 2},
        'eerie impulse': {'type': 'debuff_target', 'stat': 'SPA', 'value': -3, 'save': 'CON', 'duration': 3},
        'memento': {'type': 'debuff_target', 'stat': 'ATK', 'value': -4, 'save': 'WIS', 'duration': 3},
        'parting shot': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 2},
        'curse': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'WIS', 'duration': 3},
        'spite': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 2},
    }
    
    # Check by name first
    if name_lower in KNOWN_EFFECTS:
        return KNOWN_EFFECTS[name_lower]
    
    # ========== DESCRIPTION-BASED DETECTION (PT + EN) ==========
    
    # Confusion
    if any(kw in desc for kw in ['confus', 'confused', 'confusion']):
        return {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'}
    
    # Sleep
    if any(kw in desc for kw in ['dormir', 'adormecer', 'sono', 'durma', 'sleep', 'asleep', 'drowsy']):
        return {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'}
    
    # Paralysis
    if any(kw in desc for kw in ['paralis', 'paralyz', 'paralyze']):
        return {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'}
    
    # Poison
    if any(kw in desc for kw in ['envenenad', 'veneno', 'poison', 'toxic']):
        return {'type': 'inflict_status', 'status': 'badly_poisoned', 'save': 'CON'}
    
    # Burn
    if any(kw in desc for kw in ['queimad', 'queimadura', 'burn', 'burned']):
        return {'type': 'inflict_status', 'status': 'queimado', 'save': 'DEX'}
    
    # Freeze
    if any(kw in desc for kw in ['congel', 'frozen', 'freeze']):
        return {'type': 'inflict_status', 'status': 'congelado', 'save': 'CON'}
    
    # Fear/Flinch
    if any(kw in desc for kw in ['amedront', 'frightened', 'flinch', 'assustador']):
        return {'type': 'inflict_status', 'status': 'amedrontado', 'save': 'WIS'}
    
    # Accuracy debuffs
    if any(kw in desc for kw in ['fumaça', 'areia', 'cegar', 'blind', 'accuracy', 'precisão']):
        return {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'CON', 'duration': 3}
    
    # Attack debuffs
    if any(kw in desc for kw in ['ataque que fizer', 'attack.*lower', 'rosnado', 'intimidador']):
        return {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 3}
    
    # Defense debuffs
    if any(kw in desc for kw in ['defesas', 'ataque que o alvo sofrer', 'defense.*lower']):
        return {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'WIS', 'duration': 3}
    
    # Speed debuffs
    if any(kw in desc for kw in ['velocidade', 'speed']) and any(kw in desc for kw in ['reduz', 'diminui', 'lower', 'decrease']):
        return {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'DEX', 'duration': 3}
    
    # Self speed buff
    if any(kw in desc for kw in ['velocidade', 'speed']) and any(kw in desc for kw in ['aument', 'increase', 'raise', 'percorrer']):
        return {'type': 'buff_self', 'stat': 'SPE', 'value': 4, 'duration': 3}
    
    # Self attack buff
    if any(kw in desc for kw in ['espada', 'sword', 'attack.*raise']) and any(kw in desc for kw in ['aument', 'raise', 'boost']):
        return {'type': 'buff_self', 'stat': 'ATK', 'value': 3, 'duration': 3}
    
    # Self defense buff
    if any(kw in desc for kw in ['ca em', 'ca aument', 'defense.*raise', 'barreira', 'barrier', 'harden', 'endurec']):
        return {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3}
    
    # STAB buff
    if 'stab' in desc and any(kw in desc for kw in ['dobr', 'double', 'aument']):
        return {'type': 'buff_self', 'stat': 'SPA', 'value': 3, 'duration': 3}
    
    # Healing
    if any(kw in desc for kw in ['recupera', 'cura', 'restaura', 'heal', 'restore', 'recover']):
        if any(kw in desc for kw in ['metade', '50%', 'half']):
            return {'type': 'heal_self', 'amount': 'half'}
        if any(kw in desc for kw in ['todo', 'total', 'máximo', 'full']):
            return {'type': 'heal_self', 'amount': 'full'}
        return {'type': 'heal_self', 'amount': 'quarter'}
    
    # Protect
    if any(kw in desc for kw in ['evitar automaticamente sofrer dano', 'proteg', 'invulnerável', 'protect', 'shields']):
        return {'type': 'protect', 'duration': 1}

    # Buff de CA descrito no texto ("ganhe +4 na sua CA", "aumentando sua CA em 1")
    m_ca = _re_search(r'(?:\+(\d+)\s+(?:na|em)\s+(?:sua\s+)?ca|(?:sua\s+)?ca\s+em\s+(\d+))', desc)
    if m_ca:
        val = int(m_ca.group(1) or m_ca.group(2))
        return {'type': 'buff_self', 'stat': 'AC', 'value': val, 'duration': 3}

    # Bônus de ataque descrito no texto ("+1 em testes de ataque", "adicionar um d4
    # a qualquer jogada de ataque", "vantagem em seus próximos ataques")
    if _re_search(r'\+\d+\s+(?:em|nos?)\s+(?:seus\s+)?testes?\s+de\s+ataque', desc) or \
       _re_search(r'(?:adicionar|adicione)\s+(?:um\s+)?1?d4\s+a\s+(?:qualquer|todas)', desc) or \
       'vantagem em seus próximos' in desc or 'margem de acerto crítico' in desc:
        return {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3}

    # Desvantagem no ataque do alvo
    if 'desvantagem na rolagem de ataque' in desc or 'desvantagem em suas rolagens de ataque' in desc:
        return {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'WIS', 'duration': 2}

    # If nothing detected
    return None


def process_status_move(move_data, attacker_stats, target_stats):
    """Process a status move being used. Returns the effect result.
    
    Returns dict: {
        'success': bool,
        'effect_type': str,
        'message': str,
        'status_applied': str or None,
        'stat_changes': dict or None
    }
    """
    effect = auto_detect_move_effect(move_data)
    if not effect:
        return {
            'success': True,
            'effect_type': 'utility',
            'message': f"{move_data.get('name', '???')} foi usado! (utilidade)",
            'status_applied': None,
            'stat_changes': None
        }
    
    move_name = move_data.get('name', '???')

    # Calculate Move DC: 8 + proficiency + relevant stat mod.
    # The 'power' field uses PT abbreviations (FOR/DES/CON/INT/SAB/CAR);
    # pokemon stats use the new system (ATK/DEF/SPA/SPD/SPE/HP) with
    # possible legacy keys (STR/DEX/CON/INT/WIS/CHA).
    prof = attacker_stats.get('proficiency', 2)
    move_dc = 8 + prof + _best_attacker_mod(attacker_stats, move_data.get('power', ''))

    if effect['type'] == 'inflict_status':
        # Target makes a saving throw
        save_stat = effect.get('save', 'WIS')
        save_mod = _save_mod(target_stats, save_stat)
        save_roll = random.randint(1, 20)
        save_total = save_roll + save_mod
        
        if save_total < move_dc:
            # Status applied!
            return {
                'success': True,
                'effect_type': 'status',
                'message': f"{move_name}! CD {move_dc} vs d20({save_roll})+{save_mod}={save_total} → Falhou no save! Status aplicado!",
                'status_applied': effect['status'],
                'stat_changes': None
            }
        else:
            return {
                'success': False,
                'effect_type': 'resisted',
                'message': f"{move_name}! CD {move_dc} vs d20({save_roll})+{save_mod}={save_total} → Resistiu!",
                'status_applied': None,
                'stat_changes': None
            }
    
    elif effect['type'] == 'debuff_target':
        save_stat = effect.get('save', 'WIS')
        save_mod = _save_mod(target_stats, save_stat)
        save_roll = random.randint(1, 20)
        save_total = save_roll + save_mod
        
        if save_total < move_dc:
            return {
                'success': True,
                'effect_type': 'debuff',
                'message': f"{move_name}! CD {move_dc} vs d20({save_roll})+{save_mod}={save_total} → {effect['stat']} {effect['value']:+d}!",
                'status_applied': None,
                'stat_changes': {effect['stat']: effect['value']}
            }
        else:
            return {
                'success': False,
                'effect_type': 'resisted',
                'message': f"{move_name}! CD {move_dc} vs d20({save_roll})+{save_mod}={save_total} → Resistiu!",
                'status_applied': None,
                'stat_changes': None
            }
    
    elif effect['type'] == 'buff_self':
        return {
            'success': True,
            'effect_type': 'buff',
            'message': f"{move_name}! {effect['stat']} {effect['value']:+d}!",
            'status_applied': None,
            'stat_changes': {effect['stat']: effect['value']}
        }
    
    elif effect['type'] == 'heal_self':
        max_hp = attacker_stats.get('maxHp', 20)
        if effect['amount'] == 'full':
            heal = max_hp
        elif effect['amount'] == 'half':
            heal = max_hp // 2
        else:
            heal = max_hp // 4
        return {
            'success': True,
            'effect_type': 'heal',
            'message': f"{move_name}! Recuperou {heal} HP!",
            'status_applied': None,
            'stat_changes': None,
            'heal': heal
        }
    
    elif effect['type'] == 'protect':
        return {
            'success': True,
            'effect_type': 'protect',
            'message': f"{move_name}! Protegido contra o próximo ataque!",
            'status_applied': None,
            'stat_changes': None
        }
    
    # Default
    return {
        'success': True,
        'effect_type': 'utility',
        'message': f"{move_name} foi usado!",
        'status_applied': None,
        'stat_changes': None
    }
