# abilities.py — Pokémon ability effect data and helpers

# Abilities that grant full immunity to a move type.
# Key = ability name (lowercase), Value = list of immune types (lowercase English)
ABILITY_IMMUNITIES = {
    'levitate':      ['ground'],
    'flash fire':    ['fire'],
    'water absorb':  ['water'],
    'volt absorb':   ['electric'],
    'motor drive':   ['electric'],
    'sap sipper':    ['grass'],
    'storm drain':   ['water'],
    'lightning rod': ['electric'],
    'dry skin':      ['water'],
    'wonder guard':  [],   # handled separately (only super-effective hits)
    'earth eater':   ['ground'],
    'well-baked body': ['fire'],
}

# Abilities that heal the user when hit by a specific type (instead of taking damage).
# Value = list of types that trigger healing (empty = just blocks, no heal)
ABILITY_ABSORB_HEAL = {
    'water absorb':  ['water'],
    'volt absorb':   ['electric'],
    'dry skin':      ['water'],
    'storm drain':   ['water'],
    'lightning rod': ['electric'],
    'earth eater':   ['ground'],
    'well-baked body': ['fire'],
}

# Abilities that boost an offensive stat when hit by a specific type
ABILITY_ABSORB_BOOST = {
    'flash fire':  {'type': 'fire',     'stat': 'fire_boost'},   # boosts own Fire moves
    'motor drive': {'type': 'electric', 'stat': 'SPE'},
    'sap sipper':  {'type': 'grass',    'stat': 'ATK'},
}

# Abilities that reduce incoming damage of certain types (multiplier)
ABILITY_RESISTANCES = {
    'thick fat':   {'fire': 0.5, 'ice': 0.5},
    'heatproof':   {'fire': 0.5},
    'water bubble': {'fire': 0.5},
    'fluffy':      {'fire': 2.0, 'contact': 0.5},  # contact special-cased
    'purifying salt': {'ghost': 0.5},
}

# Abilities that reduce super-effective damage
ABILITY_FILTER = {'filter', 'solid rock', 'prism armor'}  # reduce SE by 25%

# Abilities triggered on entering battle (switch-in or battle start)
# 'target': 'enemy' = affects opponent, 'self' = affects this pokemon
ABILITY_ON_ENTER = {
    'intimidate':   {'target': 'enemy', 'stat': 'ATK',  'mod': -2, 'msg': '{name} intimidou o inimigo! ATK -2'},
    'download':     {'target': 'self',  'stat': 'auto', 'mod': +2, 'msg': '{name} analisou o inimigo! Stat ofensivo +2'},
    'drought':      {'target': 'field', 'weather': 'sun',  'msg': '{name} trouxe o sol forte!'},
    'drizzle':      {'target': 'field', 'weather': 'rain', 'msg': '{name} invocou chuva forte!'},
    'sand stream':  {'target': 'field', 'weather': 'sandstorm', 'msg': '{name} invocou tempestade de areia!'},
    'snow warning': {'target': 'field', 'weather': 'hail', 'msg': '{name} invocou granizo!'},
    'pressure':     {'target': 'log',   'msg': '{name} está exercendo pressão!'},
    'unnerve':      {'target': 'log',   'msg': '{name} deixou o inimigo nervoso! Não pode usar bagas.'},
    'trace':        {'target': 'log',   'msg': '{name} copiou a habilidade do inimigo!'},
}

# Passive abilities (checked every turn or on specific events)
ABILITY_PASSIVES = {
    'sturdy':        'survive_ko',       # survive a KO hit at full HP (1 HP remaining)
    'magic guard':   'no_indirect',      # no burn/poison/weather damage
    'poison heal':   'heal_poison',      # gain HP from poison instead of losing
    'natural cure':  'cure_on_switch',   # cure status when switching out
    'regenerator':   'heal_on_switch',   # heal 1/3 HP when switching out
    'speed boost':   'speed_up_turn',    # +1 SPE every turn
    'guts':          'boost_on_status',  # ATK ×1.5 when statused
    'marvel scale':  'def_on_status',    # DEF ×1.5 when statused
    'toxic boost':   'atk_on_poison',    # ATK ×1.5 when poisoned
    'flare boost':   'spa_on_burn',      # SPA ×1.5 when burned
    'quick feet':    'spe_on_status',    # SPE ×1.5 when statused
    'overcoat':      'immune_weather',   # no weather damage, immune to powder moves
    'sand veil':     'evasion_sand',     # +1 evasion in sandstorm
    'snow cloak':    'evasion_hail',     # +1 evasion in hail
    'magic bounce':  'reflect_status',   # reflects status moves back
}

# All known ability names (used for validation/display)
ALL_ABILITIES = (
    set(ABILITY_IMMUNITIES)
    | set(ABILITY_ABSORB_HEAL)
    | set(ABILITY_ABSORB_BOOST)
    | set(ABILITY_RESISTANCES)
    | ABILITY_FILTER
    | set(ABILITY_ON_ENTER)
    | set(ABILITY_PASSIVES)
)


def normalize_ability(ability) -> str:
    """Aceita string ou dict {'name': ...} (formato do pokemon.json)."""
    if isinstance(ability, dict):
        ability = ability.get('name', '')
    return (ability or '').strip().lower()


def get_ability_key(pokemon: dict) -> str:
    """Return the ability name in lowercase from a pokemon dict."""
    return normalize_ability(pokemon.get('ability'))


def check_defender_ability(ability: str, move_type: str, damage: int, current_hp: int, max_hp: int) -> dict:
    """
    Check how the defender's ability reacts to an incoming move.

    Returns a dict:
    {
        'modified_damage': int,   # damage after ability (may be 0)
        'heal': int,              # HP to restore on defender (from absorb abilities)
        'blocked': bool,          # True if move was fully blocked
        'triggered': bool,        # True if any ability effect fired
        'boost': str|None,        # stat/field boosted (e.g. 'ATK', 'fire_boost')
        'message': str,           # description for battle log
    }
    """
    ability = normalize_ability(ability)
    move_type = (move_type or '').strip().lower()

    result = {
        'modified_damage': damage,
        'heal': 0,
        'blocked': False,
        'triggered': False,
        'boost': None,
        'message': '',
    }

    if not ability or damage <= 0:
        return result

    # Full immunity
    immune_types = ABILITY_IMMUNITIES.get(ability, [])
    if move_type in immune_types:
        result['modified_damage'] = 0
        result['blocked'] = True
        result['triggered'] = True

        # Heal if absorb ability
        heal_types = ABILITY_ABSORB_HEAL.get(ability, [])
        if move_type in heal_types:
            heal_amount = max(1, max_hp // 4)
            result['heal'] = heal_amount
            result['message'] = f'Habilidade "{ability}" absorveu o ataque! +{heal_amount} HP'
        else:
            # Check stat boost
            boost_info = ABILITY_ABSORB_BOOST.get(ability)
            if boost_info and boost_info['type'] == move_type:
                result['boost'] = boost_info['stat']
                result['message'] = f'Habilidade "{ability}" absorveu o ataque! {boost_info["stat"]} aumentou!'
            else:
                result['message'] = f'Habilidade "{ability}" tornou {move_type} ineficaz!'
        return result

    # Damage reduction
    resistances = ABILITY_RESISTANCES.get(ability, {})
    if move_type in resistances:
        mult = resistances[move_type]
        result['modified_damage'] = max(1, int(damage * mult))
        result['triggered'] = True
        result['message'] = f'Habilidade "{ability}" reduziu o dano {move_type}!'

    # Sturdy — survive KO at full HP
    if ability == 'sturdy' and current_hp >= max_hp and result['modified_damage'] >= current_hp:
        result['modified_damage'] = current_hp - 1
        result['triggered'] = True
        result['message'] = f'Sturdy! Sobreviveu com 1 HP!'

    return result


def check_on_enter(ability: str, pokemon_name: str) -> dict | None:
    """
    Returns on-enter effect info for a Pokémon entering battle, or None.
    """
    ability = normalize_ability(ability)
    effect = ABILITY_ON_ENTER.get(ability)
    if not effect:
        return None
    return {
        'ability': ability,
        'target': effect.get('target'),
        'stat': effect.get('stat'),
        'mod': effect.get('mod', 0),
        'weather': effect.get('weather'),
        'message': effect.get('msg', '').replace('{name}', pokemon_name),
    }


def get_passive(ability) -> str | None:
    """Return passive key for an ability, or None."""
    return ABILITY_PASSIVES.get(normalize_ability(ability))
