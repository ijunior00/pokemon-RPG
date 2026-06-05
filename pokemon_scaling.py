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
# GROWTH RATES - XP required per level
# ============================================================
def xp_for_level(level, growth_rate='medium'):
    """Calculate total XP needed to reach a given level."""
    if level <= 1:
        return 0
    if growth_rate == 'fast':
        return int((4 * level ** 3) / 5)
    elif growth_rate == 'slow':
        return int((5 * level ** 3) / 4)
    else:  # medium
        return int(level ** 3)


def level_from_xp(total_xp, growth_rate='medium'):
    """Get level from total XP."""
    level = 1
    while xp_for_level(level + 1, growth_rate) <= total_xp and level < 100:
        level += 1
    return level


def xp_to_next_level(current_level, growth_rate='medium'):
    """XP needed from current level to next."""
    if current_level >= 100:
        return 0
    return xp_for_level(current_level + 1, growth_rate) - xp_for_level(current_level, growth_rate)


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
# XP REWARDS
# ============================================================
def battle_xp_reward(winner_level, loser_level, loser_sr='1/2', is_wild=True):
    """Calculate XP reward for winning a battle.
    
    Base XP = loser_level × SR_value × 10
    Difficulty modifier:
    - loser > winner+10: ×2.0 (very hard)
    - loser > winner+5: ×1.5 (hard)  
    - loser within ±5: ×1.0 (normal)
    - loser < winner-5: ×0.5 (easy)
    - loser < winner-10: ×0.25 (trivial)
    
    Wild pokemon give base XP. Trainer battles give ×1.5.
    """
    # Parse SR
    sr_val = 0.5
    if isinstance(loser_sr, str):
        if '/' in loser_sr:
            parts = loser_sr.split('/')
            sr_val = int(parts[0]) / int(parts[1])
        else:
            try:
                sr_val = float(loser_sr)
            except:
                sr_val = 0.5
    else:
        sr_val = float(loser_sr)
    
    base_xp = int(loser_level * max(sr_val, 0.5) * 10)
    
    # Difficulty modifier
    level_diff = loser_level - winner_level
    if level_diff > 10:
        modifier = 2.0
    elif level_diff > 5:
        modifier = 1.5
    elif level_diff >= -5:
        modifier = 1.0
    elif level_diff >= -10:
        modifier = 0.5
    else:
        modifier = 0.25
    
    # Trainer vs wild
    trainer_bonus = 1.0 if is_wild else 1.5
    
    total = int(base_xp * modifier * trainer_bonus)
    return max(1, total)


def trainer_level_up_xp(trainer_new_level):
    """Large XP dump to all pokemon when trainer levels up.
    Gives each Pokemon XP equal to their current level × 50."""
    return trainer_new_level * 50


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
def calculate_pokemon_stats(base_pokemon, level):
    """Calculate all stats for a Pokemon at a given level.
    
    base_pokemon: dict with base stats from JSON (hp, ac, stats: {STR, DEX, CON, INT, WIS, CHA})
    level: 1-100
    
    Returns dict with all calculated combat stats.
    """
    base_stats = base_pokemon.get('stats', {})
    base_hp = base_pokemon.get('hp', 20)
    base_ac = base_pokemon.get('ac', 13)
    con = base_stats.get('CON', 10)
    dex = base_stats.get('DEX', 10)
    
    stats = {}
    for stat_name in ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']:
        base = base_stats.get(stat_name, 10)
        stats[stat_name] = calculate_stat(base, level)
    
    return {
        'level': level,
        'hp': calculate_hp(base_hp, level, con),
        'maxHp': calculate_hp(base_hp, level, con),
        'ac': calculate_ac(base_ac, level, dex),
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
