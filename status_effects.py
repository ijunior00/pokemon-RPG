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

# Accuracy canônica por move (sistema v2: moves de status aplicam por
# d20 vs Accuracy, como nos jogos — sem save D&D do alvo).
_CANONICAL_FILE = _os.path.join(_os.path.dirname(__file__),
                                'server', 'data', 'canonical_moves.json')
try:
    with open(_CANONICAL_FILE, encoding='utf-8') as _f:
        _CANONICAL_MOVES = _json.load(_f)
except (FileNotFoundError, ValueError):
    _CANONICAL_MOVES = {}


def _canon_ident(name):
    n = (name or '').lower().replace("'", '').replace('’', '')
    n = n.replace('.', '').replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return {'vise grip': 'vice-grip'}.get((name or '').lower(), n)


def move_accuracy(move_name):
    """Accuracy canônica 1-100 do move, ou None (move que não erra)."""
    return (_CANONICAL_MOVES.get(_canon_ident(move_name)) or {}).get('accuracy')

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
        'duration': 'permanent',
        'description': 'Perde HP crescente (1/8, 2/8...) e o dano FÍSICO é cortado pela metade. Dura até ser curado.'
    },
    'paralisado': {
        'name': 'Paralisado',
        'icon': '⚡',
        'color': '#f8d030',
        'turn_effect': 'skip_chance',
        'skip_chance': 0.25,             # 25% chance to not act
        'can_act': True,                 # can act (but might fail)
        'duration': 'permanent',
        'description': '25% de chance de não agir. Velocidade cortada pela metade.'
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


# A ponte D&D (CD de move = 8+prof+mod, saves FOR/DES/CON... do alvo) foi
# APOSENTADA no sistema v2: moves de status aplicam por d20 vs Accuracy
# canônica (move_accuracy acima). O campo 'power' PT ("FOR/DES") do
# moves.json virou texto cosmético da ficha.


def check_status_on_hit(move_name, attack_roll, damage_dealt, defender=None):
    """Check if a move inflicts a status effect on hit.
    Returns (status_key, inflicted) or (None, False).
    `defender` (opcional): respeita imunidades de habilidade (Limber, Immunity,
    Water Veil, Shield Dust...) — bloqueia o status secundário."""
    # Dados canônicos primeiro (chances reais dos jogos); mapa curado como fallback
    entry = MOVE_EFFECTS_DATA.get((move_name or '').lower())
    effect = (entry or {}).get('on_hit') or MOVE_STATUS_EFFECTS.get(move_name)
    if not effect:
        return None, False
    # imunidade por habilidade (Shield Dust bloqueia qualquer secundário)
    if defender is not None:
        try:
            import abilities as _ab
            if _ab.is_status_immune(defender, effect.get('status')):
                return None, False
        except Exception:
            pass

    trigger = effect.get('on', 'hit')
    chance = effect.get('chance', 0)
    
    if trigger == 'hit' and damage_dealt > 0:
        if random.random() < chance:
            return effect['status'], True
    elif trigger == 'nat15plus' and attack_roll >= 15 and damage_dealt > 0:
        if random.random() < chance:
            return effect['status'], True
    elif trigger in ('save_fail', 'next_turn'):
        # Aplica pela chance do move (sistema v2 — sem teste de resistência D&D)
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
        # superar a paralisia é SILENCIOSO (age normalmente) — evita poluir o log
        # com "Superou a paralisia!" todo turno
    
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


# Condições → MULTIPLICADORES de stat (sistema v2, escala 1-255).
# Queimado NÃO entra aqui: o corte de dano físico ×0.5 é aplicado direto na
# fórmula de dano (battle_math.damage burned=True) — evita duplicar o efeito.
_COND_STAT_MULT = {
    'paralisado': {'SPE': 0.5},
}


def _cond_stat_mult(pokemon, stat):
    """Multiplicador de stat vindo da CONDIÇÃO ativa (paralisado SPE ×0.5)."""
    status = pokemon.get('status') if isinstance(pokemon, dict) else None
    cond = (status or {}).get('condition') if isinstance(status, dict) else None
    return _COND_STAT_MULT.get(cond, {}).get(stat, 1.0)


def effective_stat(pokemon, stat):
    """Stat efetivo v2 = stat no nível × stage_mult(±6, oficial) × condição.
    Stages são MULTIPLICATIVOS na escala 1-255 (+2 = ×2, −2 = ×0.5)."""
    import battle_math as bm
    if not isinstance(pokemon, dict):
        return 10
    base = int((pokemon.get('stats') or {}).get(stat, 10) or 10)
    stage = int((pokemon.get('stat_stages') or {}).get(stat, 0))
    # multiplicador de habilidade (Huge Power, Fur Coat, Guts, Defeatist...)
    try:
        import abilities as _ab
        abil_mult = _ab.stat_multiplier_for(pokemon, stat)
    except Exception:
        abil_mult = 1.0
    return max(1, int(base * bm.stage_mult(stage) * _cond_stat_mult(pokemon, stat) * abil_mult))


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
        # Moves de dano fixo (canônico: Night Shade/Seismic Toss = nível do usuário)
        'night shade': {'type': 'fixed_damage', 'formula': 'level'},
        'seismic toss': {'type': 'fixed_damage', 'formula': 'level'},
        'sonic boom': {'type': 'fixed_damage', 'formula': 'half_level'},
        'bide': {'type': 'fixed_damage', 'formula': 'level'},          # energia acumulada devolvida
        'metal burst': {'type': 'fixed_damage', 'formula': 'level'},   # retalia o último golpe
        'beat up': {'type': 'fixed_damage', 'formula': 'half_level'},  # o time todo golpeia
        'fling': {'type': 'fixed_damage', 'formula': 'half_level'},    # arremesso improvisado
        'nightmare': {'type': 'fixed_damage', 'formula': 'half_level'},  # pesadelo devora o alvo
        'spikes': {'type': 'fixed_damage', 'formula': 'quarter_level'},        # farpas no terreno
        'stealth rock': {'type': 'fixed_damage', 'formula': 'quarter_level'},  # pedras flutuantes
        "nature's madness": {'type': 'fixed_damage', 'formula': 'half_target_hp'},  # canon: metade do HP
        'endeavor': {'type': 'fixed_damage', 'formula': 'endeavor'},   # canon: iguala HP do alvo ao seu
        'final gambit': {'type': 'fixed_damage', 'formula': 'user_hp'},  # canon: dano = seu HP; você desmaia
        'perish song': {'type': 'fixed_damage', 'formula': 'half_level', 'self': True},  # fere ambos
        'pain split': {'type': 'pain_split'},                          # canon: divide os HPs igualmente
        # OHKO (v2: d20 vs accuracy canônica ~30%; acertou → desmaia)
        'fissure': {'type': 'ohko'},
        'guillotine': {'type': 'ohko'},
        'horn drill': {'type': 'ohko'},
        # Haze: anula TODOS os buffs/debuffs acumulados (dos dois lados)
        'haze': {'type': 'reset_stages'},
        # Operações sobre stat stages (copiar/trocar/inverter)
        'psych up': {'type': 'stage_op', 'op': 'copy'},
        'role play': {'type': 'stage_op', 'op': 'copy'},
        'transform': {'type': 'stage_op', 'op': 'copy'},
        'heart swap': {'type': 'stage_op', 'op': 'swap'},
        'topsy-turvy': {'type': 'stage_op', 'op': 'invert'},
        # Teleport: foge da batalha selvagem (falha em batalha de treinador — canon)
        'teleport': {'type': 'flee'},
        # Moves "imprevisíveis": viram um move de DANO aleatório (caminho de ataque);
        # a entrada aqui é fallback p/ quando processados pelo motor de status.
        'metronome': {'type': 'variable'},
        'mirror move': {'type': 'variable'},
        'copycat': {'type': 'variable'},
        'assist': {'type': 'variable'},
        'me first': {'type': 'variable'},
        'mimic': {'type': 'variable'},
        'sketch': {'type': 'variable'},
        # Barreiras/proteções
        'aurora veil': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 5},
        'ally switch': {'type': 'protect'},
        'crafty shield': {'type': 'protect'},
        'magic coat': {'type': 'protect'},
        'quick guard': {'type': 'protect'},
        # Buffs próprios (homebrew p/ moves situacionais)
        'helping hand': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 1},
        'after you': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 1, 'duration': 1},
        'hold hands': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 1, 'duration': 1},
        'instruct': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 1, 'duration': 1},
        'foresight': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3},
        'odor sleuth': {'type': 'buff_self', 'stat': 'attack_roll', 'value': 2, 'duration': 3},
        'baton pass': {'type': 'buff_self', 'stat': 'SPE', 'value': 2, 'duration': 2},
        'camouflage': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3},
        'conversion': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3},
        'conversion 2': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 3},
        'reflect type': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3},
        'magnet rise': {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3},
        'lucky chant': {'type': 'buff_self', 'stat': 'AC', 'value': 1, 'duration': 5},
        'power trick': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
        'follow me': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 1},
        'rage powder': {'type': 'buff_self', 'stat': 'DEF', 'value': 2, 'duration': 1},
        'mud sport': {'type': 'buff_self', 'stat': 'SPD', 'value': 2, 'duration': 3},
        'water sport': {'type': 'buff_self', 'stat': 'SPD', 'value': 2, 'duration': 3},
        'electric terrain': {'type': 'buff_self', 'stat': 'SPA', 'value': 2, 'duration': 3},
        'ion deluge': {'type': 'buff_self', 'stat': 'SPA', 'value': 1, 'duration': 2},
        'recycle': {'type': 'heal_self', 'amount': 'quarter'},
        # Debuffs no alvo (homebrew p/ moves de manipulação)
        'block': {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'CON', 'duration': 3},
        'spider web': {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'DEX', 'duration': 3},
        'fairy lock': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'WIS', 'duration': 2},
        'quash': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'CON', 'duration': 2},
        'trick room': {'type': 'debuff_target', 'stat': 'SPE', 'value': -3, 'save': 'INT', 'duration': 3},
        'speed swap': {'type': 'debuff_target', 'stat': 'SPE', 'value': -2, 'save': 'CON', 'duration': 3},
        'gastro acid': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'CON', 'duration': 3},
        'entrainment': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 3},
        'skill swap': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'INT', 'duration': 3},
        'imprison': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 3},
        'destiny bond': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 3},
        'grudge': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 3},
        'powder': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'DEX', 'duration': 2},
        'trick': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 2},
        'switcheroo': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -2, 'save': 'WIS', 'duration': 2},
        'bestow': {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -1, 'save': 'WIS', 'duration': 2},
        'soak': {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'CON', 'duration': 3},
        "forest's curse": {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'WIS', 'duration': 3},
        'trick-or-treat': {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'WIS', 'duration': 3},
        'guard split': {'type': 'debuff_target', 'stat': 'DEF', 'value': -2, 'save': 'CON', 'duration': 3},
        'power split': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'CON', 'duration': 3},
        'power swap': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'CON', 'duration': 3},
        'simple beam': {'type': 'debuff_target', 'stat': 'SPA', 'value': -2, 'save': 'CON', 'duration': 3},
        'electrify': {'type': 'debuff_target', 'stat': 'SPA', 'value': -2, 'save': 'CON', 'duration': 2},
        'magic room': {'type': 'debuff_target', 'stat': 'SPD', 'value': -2, 'save': 'INT', 'duration': 3},
        'wonder room': {'type': 'debuff_target', 'stat': 'SPD', 'value': -2, 'save': 'INT', 'duration': 3},
        'gravity': {'type': 'debuff_target', 'stat': 'AC', 'value': -2, 'save': 'CON', 'duration': 3},
        'telekinesis': {'type': 'debuff_target', 'stat': 'AC', 'value': -3, 'save': 'CON', 'duration': 3},
        'spotlight': {'type': 'debuff_target', 'stat': 'AC', 'value': -2, 'save': 'WIS', 'duration': 1},
        # Psycho Shift: transfere o mal-estar (homebrew: confunde o alvo)
        'psycho shift': {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'},
        # Splash: canonicamente inútil
        'splash': {'type': 'utility', 'message': '💦 Splash! Nada aconteceu... absolutamente nada!'},
        # Debuffs conhecidos
        'noble roar': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 2},
        'captivate': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'CHA', 'duration': 2},
        'eerie impulse': {'type': 'debuff_target', 'stat': 'SPA', 'value': -3, 'save': 'CON', 'duration': 3},
        'memento': {'type': 'debuff_target', 'stat': 'ATK', 'value': -4, 'save': 'WIS', 'duration': 3},
        'parting shot': {'type': 'debuff_target', 'stat': 'ATK', 'value': -2, 'save': 'WIS', 'duration': 2},
        # Curse (não-Ghost): auto-buff (+Atk/+Def, -Spe). Aproximado como +Atk no
        # usuário — antes debuffava a Velocidade do ALVO, o que estava errado.
        'curse': {'type': 'buff_self', 'stat': 'ATK', 'value': 2, 'duration': 3},
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
            'message': f"{move_data.get('name', '???')}: efeito narrativo/situacional — "
                       f"o mestre adjudica o resultado.",
            'status_applied': None,
            'stat_changes': None
        }
    
    move_name = move_data.get('name', '???')

    # Sistema v2: moves de status aplicam por d20 vs ACCURACY canônica do
    # move (Thunder Wave 90%, Sleep Powder 75%...), como nos jogos.
    # Sem save do alvo — a chance é fixa por move.
    import battle_math as _bm

    def _accuracy_roll():
        acc = move_accuracy(move_name)
        roll = random.randint(1, 20)
        thr = _bm.miss_threshold(acc)
        acc_label = f'Acc {acc}%' if acc else 'não erra'
        return _bm.roll_hits(roll, acc), roll, thr, acc_label

    if effect['type'] == 'inflict_status':
        ok, roll, thr, acc_label = _accuracy_roll()
        if ok:
            return {
                'success': True,
                'effect_type': 'status',
                'message': f"{move_name}! d20({roll}) > {thr} ({acc_label}) → Status aplicado!",
                'status_applied': effect['status'],
                'stat_changes': None
            }
        return {
            'success': False,
            'effect_type': 'resisted',
            'message': f"{move_name}! d20({roll}) ≤ {thr} ({acc_label}) → Errou!",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'debuff_target':
        ok, roll, thr, acc_label = _accuracy_roll()
        if ok:
            return {
                'success': True,
                'effect_type': 'debuff',
                'message': f"{move_name}! d20({roll}) > {thr} ({acc_label}) → {effect['stat']} {effect['value']:+d}!",
                'status_applied': None,
                'stat_changes': {effect['stat']: effect['value']}
            }
        return {
            'success': False,
            'effect_type': 'resisted',
            'message': f"{move_name}! d20({roll}) ≤ {thr} ({acc_label}) → Errou!",
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

    elif effect['type'] == 'fixed_damage':
        # Dano fixo que ignora CA/save. Fórmulas: level (Night Shade/Seismic
        # Toss), half_level, quarter_level (chip), half_target_hp (Nature's
        # Madness), endeavor (iguala HP), user_hp (Final Gambit — você desmaia).
        # 'self': True fere o usuário com o mesmo valor (Perish Song).
        level = int(attacker_stats.get('level', 1) or 1)
        att_hp = attacker_stats.get('currentHp')
        tgt_hp = target_stats.get('currentHp')
        formula = effect.get('formula', 'half_level')
        self_damage = 0
        # fórmulas canônicas centralizadas (Seismic Toss/Night Shade/Dragon
        # Rage/Sonic Boom/Super Fang) vivem em battle_math
        _bm_fixed = _bm.fixed_damage_for(move_name.lower(), level, tgt_hp)
        if _bm_fixed is not None:
            dmg = _bm_fixed
        elif formula == 'level':
            dmg = level
        elif formula == 'quarter_level':
            dmg = max(2, level // 4)
        elif formula == 'half_target_hp':
            dmg = max(1, int(tgt_hp if tgt_hp is not None else level) // 2)
        elif formula == 'endeavor':
            dmg = max(0, int(tgt_hp or 0) - int(att_hp or 0))
            if dmg == 0:
                return {'success': False, 'effect_type': 'utility',
                        'message': f"{move_name}! Não teve efeito (o alvo já tem menos HP que você).",
                        'status_applied': None, 'stat_changes': None}
        elif formula == 'user_hp':
            dmg = max(1, int(att_hp if att_hp is not None else level))
            self_damage = dmg   # Final Gambit: o usuário desmaia junto
        else:
            dmg = max(4, level // 2)
        if effect.get('self'):
            self_damage = dmg
        extra = ' Vocês dois são feridos!' if effect.get('self') else (
                ' Você desmaia com o esforço!' if formula == 'user_hp' else '')
        return {
            'success': True,
            'effect_type': 'fixed_damage',
            'damage': dmg,
            'self_damage': self_damage,
            'message': f"{move_name}! Dano fixo de {dmg} (ignora CA)!{extra}",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'ohko':
        # OHKO (Fissure/Guillotine/Horn Drill) — accuracy canônica (30%):
        # d20 vs limiar; acertou → desmaia (dano = HP atual). Igual aos jogos.
        ok, roll, thr, acc_label = _accuracy_roll()
        if ok:
            tgt_hp = int(target_stats.get('currentHp') or 0) or (2 * int(attacker_stats.get('level', 1) or 1))
            return {
                'success': True,
                'effect_type': 'fixed_damage',
                'damage': tgt_hp,
                'self_damage': 0,
                'message': f"{move_name}! d20({roll}) > {thr} ({acc_label}) → 💀 GOLPE FATAL! {tgt_hp} de dano!",
                'status_applied': None,
                'stat_changes': None
            }
        return {
            'success': False,
            'effect_type': 'resisted',
            'message': f"{move_name}! d20({roll}) ≤ {thr} ({acc_label}) → Errou o golpe fatal!",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'pain_split':
        # Canon: soma os HPs dos dois e divide igualmente.
        att_hp = attacker_stats.get('currentHp')
        tgt_hp = target_stats.get('currentHp')
        if att_hp is None or tgt_hp is None:
            return {'success': True, 'effect_type': 'utility',
                    'message': f"{move_name}! (HPs desconhecidos — o mestre adjudica a divisão)",
                    'status_applied': None, 'stat_changes': None}
        att_hp, tgt_hp = max(0, int(att_hp)), max(0, int(tgt_hp))
        if att_hp >= tgt_hp:
            return {'success': False, 'effect_type': 'utility',
                    'message': f"{move_name}! Não teve efeito (você não tem menos HP que o alvo).",
                    'status_applied': None, 'stat_changes': None}
        avg = (att_hp + tgt_hp) // 2
        return {
            'success': True,
            'effect_type': 'fixed_damage',
            'damage': tgt_hp - avg,
            'heal': avg - att_hp,
            'self_damage': 0,
            'message': f"{move_name}! Os HPs foram somados e divididos: ambos ficam com {avg}!",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'stage_op':
        # Operações sobre os stat stages: copy (Psych Up/Role Play/Transform),
        # swap (Heart Swap), invert (Topsy-Turvy). O caller executa.
        op = effect.get('op', 'copy')
        op_msgs = {'copy': 'copiou os buffs/debuffs do alvo!',
                   'swap': 'trocou os buffs/debuffs com o alvo!',
                   'invert': 'inverteu os buffs/debuffs do alvo!'}
        return {
            'success': True,
            'effect_type': 'stage_op',
            'op': op,
            'message': f"{move_name}! {op_msgs.get(op, op)}",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'variable':
        # Metronome/Copycat/etc.: normalmente resolvidos como ATAQUE no caminho
        # de dano. Fallback quando processados aqui (ex.: cache do cliente).
        return {
            'success': True,
            'effect_type': 'utility',
            'message': f"{move_name}! Prepara um move imprevisível... (executa como ataque)",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'reset_stages':
        # Haze: o caller zera os stat_stages dos DOIS lados.
        return {
            'success': True,
            'effect_type': 'reset_stages',
            'message': f"{move_name}! Todos os buffs e debuffs foram anulados!",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'flee':
        # Teleport: foge de batalha selvagem; em batalha de treinador falha (canon).
        return {
            'success': True,
            'effect_type': 'flee',
            'message': f"{move_name}! Teletransportou para longe da batalha!",
            'status_applied': None,
            'stat_changes': None
        }

    elif effect['type'] == 'utility':
        return {
            'success': True,
            'effect_type': 'utility',
            'message': effect.get('message') or f"{move_name} foi usado!",
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
