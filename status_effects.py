"""
Status Effects System for Pokemon 5e RPG.
Defines conditions, their effects per turn, and which moves apply them.

Based on Pokemon 5e rules + PokemonDB general mechanics.
"""
import random

# ============================================================
# STATUS CONDITIONS
# ============================================================
STATUS_CONDITIONS = {
    'envenenado': {
        'name': 'Envenenado',
        'icon': '☠️',
        'color': '#a040a0',
        'turn_effect': 'damage',       # takes damage each turn
        'damage_formula': 'max_hp_fraction',  # 1/8 of max HP
        'damage_fraction': 8,
        'can_act': True,
        'duration': 'permanent',        # until cured
        'description': 'Perde 1/8 do HP máximo no início de cada turno.'
    },
    'badly_poisoned': {
        'name': 'Gravemente Envenenado',
        'icon': '☠️☠️',
        'color': '#7030a0',
        'turn_effect': 'scaling_damage',  # increases each turn
        'base_fraction': 16,             # starts at 1/16, increases
        'can_act': True,
        'duration': 'permanent',
        'description': 'Perde HP crescente a cada turno (1/16, 2/16, 3/16...).'
    },
    'queimado': {
        'name': 'Queimado',
        'icon': '🔥',
        'color': '#f08030',
        'turn_effect': 'damage',
        'damage_formula': 'max_hp_fraction',
        'damage_fraction': 16,           # 1/16 of max HP (5e uses less than poison)
        'can_act': True,
        'stat_modifier': {'STR': -2},    # burned reduces physical attack
        'duration': 'permanent',
        'description': 'Perde 1/16 do HP máximo no início de cada turno. -2 em ataques de FOR.'
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
    'Poison Jab': {'status': 'envenenado', 'chance': 0.30, 'on': 'hit'},
    'Poison Sting': {'status': 'envenenado', 'chance': 0.30, 'on': 'hit'},
    'Sludge Bomb': {'status': 'envenenado', 'chance': 0.30, 'on': 'hit'},
    'Sludge Wave': {'status': 'envenenado', 'chance': 0.10, 'on': 'hit'},
    'Gunk Shot': {'status': 'envenenado', 'chance': 0.30, 'on': 'hit'},
    'Cross Poison': {'status': 'envenenado', 'chance': 0.10, 'on': 'hit'},
    'Poison Fang': {'status': 'badly_poisoned', 'chance': 0.50, 'on': 'hit'},
    'Toxic': {'status': 'badly_poisoned', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Poison Powder': {'status': 'envenenado', 'chance': 1.0, 'on': 'save_fail', 'save': 'CON'},
    'Baneful Bunker': {'status': 'envenenado', 'chance': 1.0, 'on': 'contact'},
    
    # Burn moves
    'Ember': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Flamethrower': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Fire Blast': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Fire Punch': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
    'Fire Fang': {'status': 'queimado', 'chance': 0.10, 'on': 'hit'},
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
    'Thunder Fang': {'status': 'paralisado', 'chance': 0.10, 'on': 'hit'},
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
    'Ice Fang': {'status': 'congelado', 'chance': 0.10, 'on': 'hit'},
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
    'Swagger': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
    'Flatter': {'status': 'confuso', 'chance': 1.0, 'on': 'save_fail', 'save': 'WIS'},
}


def check_status_on_hit(move_name, attack_roll, damage_dealt):
    """Check if a move inflicts a status effect on hit.
    Returns (status_key, inflicted) or (None, False).
    """
    effect = MOVE_STATUS_EFFECTS.get(move_name)
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
# AUTO-DETECT STATUS EFFECT FROM MOVE DESCRIPTION
# For moves not explicitly in MOVE_STATUS_EFFECTS
# ============================================================
import re

def auto_detect_move_effect(move_data):
    """Analyze a move's description to determine what effect it should have.
    Returns a dict describing the effect, or None if no effect detected.
    
    This handles ALL 244+ status moves by parsing their Portuguese descriptions.
    """
    if not move_data:
        return None
    
    desc = (move_data.get('description', '') or '').lower()
    name = move_data.get('name', '')
    
    # Status conditions (inflict on target)
    if 'envenenad' in desc or 'veneno' in desc:
        if 'gravemente' in desc or name == 'Toxic':
            return {'type': 'inflict_status', 'status': 'badly_poisoned', 'save': 'CON'}
        return {'type': 'inflict_status', 'status': 'envenenado', 'save': 'CON'}
    
    if 'queimad' in desc and ('alvo' in desc or 'criatura' in desc):
        return {'type': 'inflict_status', 'status': 'queimado', 'save': 'DEX'}
    
    if 'paralis' in desc and ('alvo' in desc or 'criatura' in desc or 'atacante' in desc):
        return {'type': 'inflict_status', 'status': 'paralisado', 'save': 'CON'}
    
    if ('dormir' in desc or 'adormecer' in desc or 'sono' in desc or 'durma' in desc) and 'alvo' in desc:
        return {'type': 'inflict_status', 'status': 'dormindo', 'save': 'WIS'}
    
    if 'confus' in desc and ('alvo' in desc or 'criatura' in desc or 'falha' in desc):
        return {'type': 'inflict_status', 'status': 'confuso', 'save': 'WIS'}
    
    if 'congel' in desc:
        return {'type': 'inflict_status', 'status': 'congelado', 'save': 'CON'}
    
    # Accuracy debuffs (smokescreen, sand attack, flash, kinesis)
    if 'fumaça' in desc or 'areia nos olhos' in desc or 'precisão' in desc or ('acurácia' in desc and 'reduz' in desc):
        return {'type': 'debuff_target', 'stat': 'attack_roll', 'value': -3, 'save': 'CON', 'duration': 3}
    
    # Evasion buffs (double team, minimize)
    if 'evas' in desc or 'cópias' in desc or 'ilusóri' in desc or 'tamanho para' in desc:
        return {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3}
    
    # Attack debuffs (growl, charm, baby-doll eyes)
    if ('-1 a qualquer ataque que fizer' in desc) or ('ataque que fizer' in desc and '-1' in desc):
        return {'type': 'debuff_target', 'stat': 'STR', 'value': -1, 'save': 'WIS', 'duration': 3}
    if ('-2' in desc and 'ataque' in desc and 'alvo' in desc):
        return {'type': 'debuff_target', 'stat': 'STR', 'value': -2, 'save': 'WIS', 'duration': 3}
    
    # Defense debuffs (leer, tail whip, screech)
    if '+1 a qualquer ataque que o alvo sofrer' in desc or ('defesas' in desc and 'abrindo' in desc):
        return {'type': 'debuff_target', 'stat': 'AC', 'value': -1, 'save': 'WIS', 'duration': 3}
    if 'ca' in desc and '-2' in desc:
        return {'type': 'debuff_target', 'stat': 'AC', 'value': -2, 'save': 'CON', 'duration': 3}
    
    # Speed debuffs (scary face, string shot, cotton spore)
    if 'velocidade' in desc and ('reduz' in desc or 'diminui' in desc or 'perde' in desc):
        return {'type': 'debuff_target', 'stat': 'DEX', 'value': -3, 'save': 'DEX', 'duration': 3}
    
    # Self buffs - Attack up (swords dance, howl, hone claws)
    if ('espada' in desc or 'ataque' in desc) and 'aument' in desc and ('seu' in desc or 'você' in desc):
        return {'type': 'buff_self', 'stat': 'STR', 'value': 3, 'duration': 3}
    
    # Self buffs - Defense up (barrier, iron defense, harden, acid armor)
    if ('ca' in desc or 'defesa' in desc or 'barreira' in desc) and ('aument' in desc or 'ca em' in desc):
        return {'type': 'buff_self', 'stat': 'AC', 'value': 2, 'duration': 3}
    
    # Self buffs - Speed up (agility, rock polish, autotomize)
    if 'velocidade' in desc and ('aument' in desc or 'percorrer' in desc or '20 pés' in desc or '10 pés' in desc):
        return {'type': 'buff_self', 'stat': 'DEX', 'value': 4, 'duration': 3}
    
    # Self buffs - Sp.Atk up (calm mind, nasty plot)
    if 'stab' in desc and ('dobr' in desc or 'aument' in desc):
        return {'type': 'buff_self', 'stat': 'STAB', 'value': 2, 'duration': 3}
    
    # Self buffs - Sp.Def up (amnesia)
    if ('resistência' in desc or 'sp. def' in desc) and 'aument' in desc:
        return {'type': 'buff_self', 'stat': 'WIS', 'value': 3, 'duration': 3}
    
    # Healing moves (recover, rest, roost, synthesis, moonlight, etc.)
    if 'recupera' in desc or 'cura' in desc or 'restaura' in desc:
        if 'metade' in desc or '50%' in desc or 'half' in desc:
            return {'type': 'heal_self', 'amount': 'half'}
        if 'todo' in desc or 'total' in desc or 'máximo' in desc:
            return {'type': 'heal_self', 'amount': 'full'}
        return {'type': 'heal_self', 'amount': 'quarter'}
    
    # Protect moves (protect, detect, spiky shield, baneful bunker)
    if 'evitar automaticamente sofrer dano' in desc or 'proteg' in desc or 'invulnerável' in desc:
        return {'type': 'protect', 'duration': 1}
    
    # Weather
    if 'chuva' in desc or 'chover' in desc:
        return {'type': 'weather', 'weather': 'rain', 'duration': 5}
    if 'sol' in desc and ('intenso' in desc or 'brilha' in desc):
        return {'type': 'weather', 'weather': 'sun', 'duration': 5}
    if 'granizo' in desc:
        return {'type': 'weather', 'weather': 'hail', 'duration': 5}
    if 'tempestade de areia' in desc:
        return {'type': 'weather', 'weather': 'sandstorm', 'duration': 5}
    
    # Attract/Taunt
    if 'atraíd' in desc or 'apaixon' in desc:
        return {'type': 'inflict_status', 'status': 'amedrontado', 'save': 'WIS'}
    
    # If nothing detected, it's a utility move with no combat effect (like Teleport, Baton Pass, etc.)
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
            'message': f"{move_data.get('name', '???')} foi usado! (utilidade)',",
            'status_applied': None,
            'stat_changes': None
        }
    
    move_name = move_data.get('name', '???')
    attacker_level = attacker_stats.get('level', 1)
    
    # Calculate Move DC: 8 + proficiency + relevant stat mod
    prof = attacker_stats.get('proficiency', 2)
    power = (move_data.get('power', 'SAB')).upper()
    stat_mod = 0
    for stat_key in ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']:
        if stat_key[:3] in power or stat_key in power:
            mod = (attacker_stats.get(stat_key, 10) - 10) // 2
            stat_mod = max(stat_mod, mod)
    
    move_dc = 8 + prof + stat_mod
    
    if effect['type'] == 'inflict_status':
        # Target makes a saving throw
        save_stat = effect.get('save', 'WIS')
        save_val = target_stats.get(save_stat, 10)
        save_mod = (save_val - 10) // 2
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
        save_val = target_stats.get(save_stat, 10)
        save_mod = (save_val - 10) // 2
        save_roll = random.randint(1, 20)
        save_total = save_roll + save_mod
        
        if save_total < move_dc:
            return {
                'success': True,
                'effect_type': 'debuff',
                'message': f"{move_name}! CD {move_dc} vs d20({save_roll})+{save_mod}={save_total} → {effect['stat']} {effect['value']:+d} por {effect.get('duration',3)} turnos!",
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
            'message': f"{move_name}! {effect['stat']} +{effect['value']} por {effect.get('duration',3)} turnos!",
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
