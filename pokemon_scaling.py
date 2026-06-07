"""
Pokemon Level Scaling System (1-100)
Handles stat growth, damage scaling, HP calculation, XP progression.

Growth Rates:
- Fast: Quick levelers (Pikachu, starters early stages)
- Medium: Standard growth (most Pokemon)
- Slow: Late bloomers (pseudo-legendaries, evolved forms)

Trainer Level: 1-20
Pokemon max controllable level = Trainer Level × 5
"""
import math

# ============================================================
# NATURE MODIFIERS
# Each nature boosts one stat by +10% and lowers another by -10%.
# Neutral natures (Hardy, Docile, Bashful, Quirky, Serious) have no effect.
# ============================================================
NATURE_MODIFIERS = {
    'Adamant':  {'ATK': 1.1, 'SPA': 0.9},
    'Modest':   {'SPA': 1.1, 'ATK': 0.9},
    'Jolly':    {'SPE': 1.1, 'SPA': 0.9},
    'Timid':    {'SPE': 1.1, 'ATK': 0.9},
    'Bold':     {'DEF': 1.1, 'ATK': 0.9},
    'Impish':   {'DEF': 1.1, 'SPA': 0.9},
    'Calm':     {'SPD': 1.1, 'ATK': 0.9},
    'Careful':  {'SPD': 1.1, 'SPA': 0.9},
    'Brave':    {'ATK': 1.1, 'SPE': 0.9},
    'Quiet':    {'SPA': 1.1, 'SPE': 0.9},
    'Relaxed':  {'DEF': 1.1, 'SPE': 0.9},
    'Sassy':    {'SPD': 1.1, 'SPE': 0.9},
    'Lonely':   {'ATK': 1.1, 'DEF': 0.9},
    'Naughty':  {'ATK': 1.1, 'SPD': 0.9},
    'Mild':     {'SPA': 1.1, 'DEF': 0.9},
    'Rash':     {'SPA': 1.1, 'SPD': 0.9},
    'Lax':      {'DEF': 1.1, 'SPD': 0.9},
    'Gentle':   {'SPD': 1.1, 'DEF': 0.9},
    'Hasty':    {'SPE': 1.1, 'DEF': 0.9},
    'Naive':    {'SPE': 1.1, 'SPD': 0.9},
}


def apply_nature(stats, nature):
    """Return a copy of stats with nature multipliers applied (±10%)."""
    if not nature or nature not in NATURE_MODIFIERS:
        return stats
    result = dict(stats)
    for stat, mult in NATURE_MODIFIERS[nature].items():
        if stat in result:
            result[stat] = int(result[stat] * mult)
    return result


# ============================================================
# XP TABLE - Per level (index 0 = Nv1->2, index 99 = Nv99->100)
# Matches reference curve exactly for 1-42, extrapolated 43-100
# ============================================================
POKEMON_XP_PER_LEVEL = [5, 7, 9, 11, 14, 17, 21, 25, 29, 35, 42, 50, 60, 72, 86, 102, 121, 142, 166, 192, 221, 254, 289, 327, 369, 413, 461, 511, 565, 623, 683, 747, 815, 886, 961, 1040, 1123, 1210, 1301, 1397, 1498, 1603, 1718, 1841, 1973, 2115, 2267, 2430, 2604, 2791, 2991, 3206, 3436, 3683, 3948, 4232, 4536, 4862, 5212, 5587, 5989, 6420, 6882, 7377, 7908, 8477, 9087, 9741, 10442, 11193, 11998, 12861, 13786, 14778, 15842, 16982, 18204, 19514, 20919, 22425, 24039, 25769, 27624, 29612, 31744, 34029, 36479, 39105, 41920, 44938, 48173, 51641, 55359, 59344, 63616, 68196, 73106, 78369, 84011, 90059]


def xp_for_level(level, growth_rate='medium'):
    """XP needed to go from (level) to (level+1)."""
    if level < 1 or level >= 100:
        return 0
    idx = level - 1
    base = POKEMON_XP_PER_LEVEL[idx]
    # Growth rate modifiers
    if growth_rate == 'fast':
        return int(base * 0.7)
    elif growth_rate == 'slow':
        return int(base * 1.4)
    return base


def total_xp_for_level(level, growth_rate='medium'):
    """Total accumulated XP to reach this level from Nv.1."""
    if level <= 1:
        return 0
    total = 0
    for lv in range(1, level):
        total += xp_for_level(lv, growth_rate)
    return total


def level_from_xp(total_xp, growth_rate='medium'):
    """Get level from total accumulated XP."""
    level = 1
    accumulated = 0
    while level < 100:
        needed = xp_for_level(level, growth_rate)
        if accumulated + needed > total_xp:
            break
        accumulated += needed
        level += 1
    return level


def xp_to_next_level(current_level, growth_rate='medium'):
    """XP needed from current level to next."""
    return xp_for_level(current_level, growth_rate)


# ============================================================
# BATTLE XP REWARDS
# Formula: wild_pokemon_level x multiplier
# Multipliers: wild=2, official_pvp=3, street_pvp=4, gym_leader=5
# ============================================================
def battle_xp_reward(winner_level, loser_level, battle_type='wild'):
    """Calculate XP reward for winning a battle.
    
    Formula: loser_level x multiplier
    battle_type: 'wild', 'official', 'street', 'gym_leader', 'elite', 'champion'
    """
    multipliers = {
        'wild': 2,
        'official': 3,
        'street': 4,
        'gym_leader': 5,
        'elite': 6,
        'champion': 8
    }
    mult = multipliers.get(battle_type, 2)
    base_xp = loser_level * mult
    
    # Bonus for fighting stronger opponents
    level_diff = loser_level - winner_level
    if level_diff > 20:
        base_xp = int(base_xp * 2.0)
    elif level_diff > 10:
        base_xp = int(base_xp * 1.5)
    elif level_diff > 5:
        base_xp = int(base_xp * 1.2)
    # Penalty for fighting much weaker
    elif level_diff < -20:
        base_xp = max(1, int(base_xp * 0.2))
    elif level_diff < -10:
        base_xp = max(1, int(base_xp * 0.5))
    
    return max(1, base_xp)


def trainer_level_up_xp(trainer_new_level):
    """XP given to all pokemon when trainer levels up.
    Each pokemon gets: trainer_level x 10."""
    return trainer_new_level * 10


# ============================================================
# STAT SCALING
# ============================================================
def calculate_hp(base_hp, level, con_stat=10):
    """Calculate HP at a given level.
    Formula: base_hp + (CON modifier × level) + (level × 2)
    This gives meaningful HP growth. A Pikachu Nv.5 has ~45 HP, Nv.50 has ~135."""
    con_mod = (con_stat - 10) // 2
    return base_hp + (con_mod * level) + (level * 2)


def calculate_stat(base_stat, level):
    """Calculate a stat value at a given level.
    Stats grow gradually: base + (level / 5) rounded down.
    A stat of 14 at Nv.1 becomes 14+10=24 at Nv.50, 14+20=34 at Nv.100."""
    return base_stat + (level // 5)


def calculate_ac(base_ac, level, dex_stat=10):
    """Calculate AC at a given level.
    Formula: base_ac + (level / 25) rounded down.
    Gives +1 AC every 25 levels (max +4 at Nv.100)."""
    return base_ac + (level // 25)


def calculate_proficiency(level):
    """Proficiency bonus for Pokemon based on level 1-100.
    Scales from +2 to +10."""
    if level >= 91:
        return 10
    elif level >= 81:
        return 9
    elif level >= 71:
        return 8
    elif level >= 61:
        return 7
    elif level >= 51:
        return 6
    elif level >= 41:
        return 5
    elif level >= 31:
        return 4
    elif level >= 17:
        return 3
    else:
        return 2


def calculate_stab(level):
    """STAB bonus based on Pokemon level."""
    if level >= 81:
        return 6
    elif level >= 61:
        return 5
    elif level >= 41:
        return 4
    elif level >= 26:
        return 3
    elif level >= 11:
        return 2
    else:
        return 1


# ============================================================
# MOVE DAMAGE SCALING
# ============================================================
def get_scaled_damage_dice(base_damage, level, higher_levels_text=''):
    """Get the damage dice for a move at a given Pokemon level.
    Uses the higherLevels field from move data when available.
    
    Default scaling (if no higherLevels defined):
    - Nv.1-9: base dice
    - Nv.10-19: base dice + 1 extra die
    - Nv.20-39: base dice × 1.5 (round up)
    - Nv.40-59: base dice × 2
    - Nv.60-79: base dice × 2.5
    - Nv.80-100: base dice × 3
    """
    if not base_damage:
        return None
    
    # Parse base damage (e.g., "2d6" -> count=2, sides=6)
    import re
    match = re.match(r'(\d+)d(\d+)', base_damage)
    if not match:
        return base_damage
    
    count = int(match.group(1))
    sides = int(match.group(2))
    
    # If higherLevels text specifies exact dice, use Pokemon 5e thresholds
    # "O dado muda para 2d4 no nível 5, 1d12 no nível 10 e 4d4 no nível 17."
    # These are TRAINER levels in 5e, we map: trainer Nv.5 = Pokemon Nv.25, etc.
    if higher_levels_text:
        # Extract level thresholds from text
        level_matches = re.findall(r'(\d+d\d+)\s+no\s+n[ií]vel\s+(\d+)', higher_levels_text.lower())
        if level_matches:
            # Convert trainer levels to pokemon levels (×5)
            scaled_dice = base_damage
            for dice_str, trainer_lv in level_matches:
                pokemon_lv = int(trainer_lv) * 5
                if level >= pokemon_lv:
                    scaled_dice = dice_str
            return scaled_dice
    
    # Default scaling
    if level >= 80:
        multiplier = 3.0
    elif level >= 60:
        multiplier = 2.5
    elif level >= 40:
        multiplier = 2.0
    elif level >= 20:
        multiplier = 1.5
    elif level >= 10:
        multiplier = 1.25
    else:
        multiplier = 1.0
    
    new_count = max(count, math.ceil(count * multiplier))
    return f"{new_count}d{sides}"


# ============================================================
# TRAINER CONTROL
# ============================================================
def max_pokemon_level(trainer_level):
    """Maximum Pokemon level a trainer can control.
    Formula: Trainer Level × 5"""
    return min(100, trainer_level * 5)


def can_control_pokemon(trainer_level, pokemon_level):
    """Check if a trainer can use a Pokemon."""
    return pokemon_level <= max_pokemon_level(trainer_level)


# ============================================================
# FULL POKEMON STAT BLOCK AT LEVEL
# ============================================================
def calculate_pokemon_stats(base_pokemon, level, nature=None):
    """Calculate all stats for a Pokemon at a given level.

    New Pokemon stat system: ATK, DEF, SPA, SPD, SPE, HP
    - ATK: Physical attack power
    - DEF: Physical defense (AC vs physical moves)
    - SPA: Special attack power
    - SPD: Special defense (AC vs special moves)
    - SPE: Speed (initiative + dodge AC)
    - HP: Hit points bonus
    """
    base_stats = base_pokemon.get('stats', {})
    base_hp = base_pokemon.get('hp', 20)
    base_ac = base_pokemon.get('ac', 13)
    hp_stat = base_stats.get('HP', base_stats.get('CON', 10))

    stats = {}
    for stat_name in ['ATK', 'DEF', 'SPA', 'SPD', 'SPE', 'HP']:
        base = base_stats.get(stat_name, 10)
        stats[stat_name] = calculate_stat(base, level)

    # Apply nature modifier if provided
    effective_nature = nature or base_pokemon.get('nature')
    if effective_nature:
        stats = apply_nature(stats, effective_nature)
    
    # Calculate actual HP
    hp_mod = (stats['HP'] - 10) // 2
    actual_hp = calculate_hp(base_hp, level, hp_stat)
    
    # AC values: physical AC based on DEF, special AC based on SPD
    phys_ac = 8 + ((stats['DEF'] - 10) // 2) + calculate_proficiency(level) // 2
    spec_ac = 8 + ((stats['SPD'] - 10) // 2) + calculate_proficiency(level) // 2
    dodge_ac = 8 + ((stats['SPE'] - 10) // 2) + calculate_proficiency(level) // 2
    
    return {
        'level': level,
        'hp': actual_hp,
        'maxHp': actual_hp,
        'ac': base_ac,  # legacy field
        'phys_ac': phys_ac,
        'spec_ac': spec_ac,
        'dodge_ac': dodge_ac,
        'stats': stats,
        'proficiency': calculate_proficiency(level),
        'stab': calculate_stab(level),
        'speed': base_pokemon.get('speed', '30ft')
    }


# ============================================================
# GROWTH RATE ASSIGNMENT
# ============================================================
def get_growth_rate(pokemon):
    """Assign growth rate based on Pokemon characteristics."""
    sr_str = pokemon.get('sr', '1/2')
    if '/' in str(sr_str):
        parts = str(sr_str).split('/')
        sr_val = int(parts[0]) / int(parts[1])
    else:
        sr_val = float(sr_str)
    
    stage = pokemon.get('evolutionStage', '1/1')
    stage_num = int(stage.split('/')[0]) if '/' in stage else 1
    
    # High SR or final evolutions = slow growth
    if sr_val >= 5 or stage_num >= 3:
        return 'slow'
    # Low SR or first stage = fast growth
    elif sr_val <= 1 and stage_num == 1:
        return 'fast'
    else:
        return 'medium'
