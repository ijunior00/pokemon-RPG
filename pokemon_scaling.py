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

    # Bônus aditivo por faixa (encurta batalhas médias/altas; Nv<15 sem bônus)
    bonus = 3 if level >= 70 else 2 if level >= 40 else 1 if level >= 15 else 0
    new_count = max(count, math.ceil(count * multiplier)) + bonus
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
# Bônus de Pokémon Shiny: +35% em TODOS os atributos base, aplicado ANTES de
# qualquer escalonamento por nível/natureza — assim HP máximo, CAs, iniciativa,
# dano e modificadores derivam naturalmente dos atributos já acrescidos, sem
# duplicar bônus em estatísticas derivadas.
SHINY_MULT = 1.35


def calculate_pokemon_stats(base_pokemon, level, nature=None, is_shiny=None,
                            training=None):
    """Calculate all stats for a Pokemon at a given level — SISTEMA v2.

    Base stats REAIS (escala 1-255, pokemondb.net) do campo `base_stats` da
    espécie, escalonados pela fórmula dos jogos (battle_math.stat_at_level):
        stat  = (2 × base × nível) // 100 + 5 + treino
        maxHp = (2 × baseHP × nível) // 100 + nível + 10 + treino_HP

    - ATK×DEF (físico), SPA×SPD (especial), SPE (iniciativa/postura 2).
    - is_shiny: +35% nos atributos BASE antes de escalonar (None = lê a flag
      do próprio dict).
    - training: dict {stat: pontos} de treino do Pokémon (cada ponto = +1 no
      stat final; None = lê 'training' do próprio dict).
    - Assinatura e formato de retorno preservados p/ os call sites; as CAs
      D&D não existem mais (chaves mantidas como None p/ compat de leitura).
    """
    import battle_math as bm

    if is_shiny is None:
        is_shiny = bool(base_pokemon.get('is_shiny'))
    if training is None:
        training = base_pokemon.get('training') or {}

    base_stats = base_pokemon.get('base_stats') or {}
    if not base_stats:
        # Rede de segurança p/ espécie sem base_stats (não deveria ocorrer:
        # a tool cobre 808/808): aproxima da escala D&D antiga ×6.
        old = base_pokemon.get('stats', {})
        base_stats = {k: max(20, min(160, int(old.get(k, old.get(_LEGACY_KEYS.get(k, k), 10)) or 10) * 6))
                      for k in ('HP', 'ATK', 'DEF', 'SPA', 'SPD', 'SPE')}

    if is_shiny:
        base_stats = {k: int(round(v * SHINY_MULT)) for k, v in base_stats.items()}

    stats = {}
    for stat_name in ('ATK', 'DEF', 'SPA', 'SPD', 'SPE'):
        stats[stat_name] = bm.stat_at_level(base_stats.get(stat_name, 50), level,
                                            training.get(stat_name, 0))
    # 'HP' no dict de stats = o stat bruto escalado (informativo/compat);
    # o pool real de vida é maxHp abaixo.
    stats['HP'] = bm.stat_at_level(base_stats.get('HP', 50), level, 0)

    # Natureza ±10% (nunca HP) — mesma tabela dos jogos
    effective_nature = nature or base_pokemon.get('nature')
    if effective_nature:
        stats = apply_nature(stats, effective_nature)

    actual_hp = bm.hp_at_level(base_stats.get('HP', 50), level) + int(training.get('HP', 0) or 0)

    return {
        'level': level,
        'hp': actual_hp,
        'maxHp': actual_hp,
        'ac': base_pokemon.get('ac', 13),   # legado (cosmético; combate não usa)
        'phys_ac': None,                    # CAs D&D aposentadas
        'spec_ac': None,
        'dodge_ac': None,
        'stats': stats,
        'proficiency': calculate_proficiency(level),  # usado só em textos/habilidades
        'stab': calculate_stab(level),                # legado (combate usa ×1.5)
        'speed': base_pokemon.get('speed', '30ft')
    }


# chaves legadas D&D → novas (p/ a rede de segurança acima)
_LEGACY_KEYS = {'ATK': 'STR', 'DEF': 'CON', 'SPA': 'INT', 'SPD': 'WIS', 'SPE': 'DEX'}


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


# ============================================================
# SPECIAL EVOLUTION TABLE
# Maps base pokemon name (lowercase) → evolution condition dict
# TODA condição especial é 'stone' (troca/amizade/golpe/stat foram
# convertidas para pedras — decisão de design para simplificar a mesa).
# ============================================================
SPECIAL_EVOLUTIONS = {
    # ── Fire Stone ─────────────────────────────────────────
    'vulpix':    {'into': 'Ninetales',  'type': 'stone', 'stone': 'Fire Stone'},
    'growlithe': {'into': 'Arcanine',   'type': 'stone', 'stone': 'Fire Stone'},
    'pansear':   {'into': 'Simisear',   'type': 'stone', 'stone': 'Fire Stone'},
    'magby':     {'into': 'Magmar',     'type': 'stone', 'stone': 'Fire Stone'},    # ex-amizade

    # ── Water Stone ────────────────────────────────────────
    'shellder':  {'into': 'Cloyster',   'type': 'stone', 'stone': 'Water Stone'},
    'staryu':    {'into': 'Starmie',    'type': 'stone', 'stone': 'Water Stone'},
    'lombre':    {'into': 'Ludicolo',   'type': 'stone', 'stone': 'Water Stone'},
    'panpour':   {'into': 'Simipour',   'type': 'stone', 'stone': 'Water Stone'},
    'azurill':   {'into': 'Marill',     'type': 'stone', 'stone': 'Water Stone'},   # ex-amizade
    'pyukumuku': {'into': 'Silvally',   'type': 'stone', 'stone': 'Water Stone'},   # ex-lealdade (dado do banco)

    # ── Thunder Stone ──────────────────────────────────────
    'pikachu':   {'into': 'Raichu',     'type': 'stone', 'stone': 'Thunder Stone'},
    'pichu':     {'into': 'Pikachu',    'type': 'stone', 'stone': 'Thunder Stone'}, # ex-amizade
    'elekid':    {'into': 'Electabuzz', 'type': 'stone', 'stone': 'Thunder Stone'}, # ex-amizade
    'charjabug': {'into': 'Vikavolt',   'type': 'stone', 'stone': 'Thunder Stone'}, # texto do banco pede Thunder Stone
    'eelektrik': {'into': 'Eelektross', 'type': 'stone', 'stone': 'Thunder Stone'}, # texto do banco

    # ── Leaf Stone ─────────────────────────────────────────
    'weepinbell':{'into': 'Victreebel', 'type': 'stone', 'stone': 'Leaf Stone'},
    'exeggcute': {'into': 'Exeggutor',  'type': 'stone', 'stone': 'Leaf Stone'},
    'nuzleaf':   {'into': 'Shiftry',    'type': 'stone', 'stone': 'Leaf Stone'},
    'pansage':   {'into': 'Simisage',   'type': 'stone', 'stone': 'Leaf Stone'},    # texto do banco
    'tangela':   {'into': 'Tangrowth',  'type': 'stone', 'stone': 'Leaf Stone'},    # ex-move
    'steenee':   {'into': 'Tsareena',   'type': 'stone', 'stone': 'Leaf Stone'},    # ex-move (órfã)
    'bonsly':    {'into': 'Sudowoodo',  'type': 'stone', 'stone': 'Leaf Stone'},    # ex-move (órfã)
    'budew':     {'into': 'Roselia',    'type': 'stone', 'stone': 'Leaf Stone'},    # ex-amizade
    'swadloon':  {'into': 'Leavanny',   'type': 'stone', 'stone': 'Leaf Stone'},    # ex-lealdade

    # ── Moon Stone ─────────────────────────────────────────
    'nidorina':  {'into': 'Nidoqueen',  'type': 'stone', 'stone': 'Moon Stone'},
    'nidorino':  {'into': 'Nidoking',   'type': 'stone', 'stone': 'Moon Stone'},
    'clefairy':  {'into': 'Clefable',   'type': 'stone', 'stone': 'Moon Stone'},
    'jigglypuff':{'into': 'Wigglytuff', 'type': 'stone', 'stone': 'Moon Stone'},
    'munna':     {'into': 'Musharna',   'type': 'stone', 'stone': 'Moon Stone'},
    'cleffa':    {'into': 'Clefairy',   'type': 'stone', 'stone': 'Moon Stone'},    # ex-amizade
    'igglybuff': {'into': 'Jigglypuff', 'type': 'stone', 'stone': 'Moon Stone'},    # ex-amizade
    'buneary':   {'into': 'Lopunny',    'type': 'stone', 'stone': 'Moon Stone'},    # ex-amizade
    'munchlax':  {'into': 'Snorlax',    'type': 'stone', 'stone': 'Moon Stone'},    # ex-amizade
    'lickitung': {'into': 'Lickilicky', 'type': 'stone', 'stone': 'Moon Stone'},    # ex-move
    'skitty':    {'into': 'Delcatty',   'type': 'stone', 'stone': 'Moon Stone'},    # texto do banco pede Moon Stone
    'happiny':   {'into': 'Chansey',    'type': 'stone', 'stone': 'Moon Stone'},    # ex-Oval Stone (não existe no jogo)

    # ── Sun Stone ──────────────────────────────────────────
    'sunkern':   {'into': 'Sunflora',   'type': 'stone', 'stone': 'Sun Stone'},
    'helioptile':{'into': 'Heliolisk',  'type': 'stone', 'stone': 'Sun Stone'},
    'cottonee':  {'into': 'Whimsicott', 'type': 'stone', 'stone': 'Sun Stone'},
    'petilil':   {'into': 'Lilligant',  'type': 'stone', 'stone': 'Sun Stone'},
    'yanma':     {'into': 'Yanmega',    'type': 'stone', 'stone': 'Sun Stone'},     # ex-move

    # ── Shiny Stone ────────────────────────────────────────
    'togetic':   {'into': 'Togekiss',   'type': 'stone', 'stone': 'Shiny Stone'},
    'roselia':   {'into': 'Roserade',   'type': 'stone', 'stone': 'Shiny Stone'},
    'minccino':  {'into': 'Cinccino',   'type': 'stone', 'stone': 'Shiny Stone'},
    'togepi':    {'into': 'Togetic',    'type': 'stone', 'stone': 'Shiny Stone'},   # ex-amizade
    'chansey':   {'into': 'Blissey',    'type': 'stone', 'stone': 'Shiny Stone'},   # ex-amizade
    'aipom':     {'into': 'Ambipom',    'type': 'stone', 'stone': 'Shiny Stone'},   # ex-move
    'spritzee':  {'into': 'Aromatisse', 'type': 'stone', 'stone': 'Shiny Stone'},   # ex-Sachet (não existe no jogo)
    'swirlix':   {'into': 'Slurpuff',   'type': 'stone', 'stone': 'Shiny Stone'},   # ex-Whipped Dream (não existe no jogo)
    'floette':   {'into': 'Florges',    'type': 'stone', 'stone': 'Shiny Stone'},   # texto do banco

    # ── Dusk Stone ─────────────────────────────────────────
    'misdreavus':{'into': 'Mismagius',  'type': 'stone', 'stone': 'Dusk Stone'},
    'murkrow':   {'into': 'Honchkrow',  'type': 'stone', 'stone': 'Dusk Stone'},
    'doublade':  {'into': 'Aegislash',  'type': 'stone', 'stone': 'Dusk Stone'},
    'golbat':    {'into': 'Crobat',     'type': 'stone', 'stone': 'Dusk Stone'},    # ex-amizade
    'woobat':    {'into': 'Swoobat',    'type': 'stone', 'stone': 'Dusk Stone'},    # ex-amizade
    'lampent':   {'into': 'Chandelure', 'type': 'stone', 'stone': 'Dusk Stone'},    # texto do banco

    # ── Dawn Stone ─────────────────────────────────────────
    'snorunt':   {'into': 'Froslass',   'type': 'stone', 'stone': 'Dawn Stone'},
    'riolu':     {'into': 'Lucario',    'type': 'stone', 'stone': 'Dawn Stone'},    # ex-amizade
    'mime jr.':  {'into': 'Mr. Mime',   'type': 'stone', 'stone': 'Dawn Stone'},    # ex-move (órfã)

    # ── Ice Stone ──────────────────────────────────────────
    'sandshrew': {'into': 'Sandslash',  'type': 'stone', 'stone': 'Ice Stone'},
    'piloswine': {'into': 'Mamoswine',  'type': 'stone', 'stone': 'Ice Stone'},     # ex-move
    'smoochum':  {'into': 'Jynx',       'type': 'stone', 'stone': 'Ice Stone'},     # ex-amizade

    # ── Gloom (a pedra escolhe o ramo) ─────────────────────
    'gloom': [
        {'into': 'Vileplume',  'type': 'stone', 'stone': 'Leaf Stone'},
        {'into': 'Bellossom',  'type': 'stone', 'stone': 'Sun Stone'},
    ],

    # ── Eevee (a pedra escolhe o ramo; ex-amizade → Sun/Moon) ─
    'eevee': [
        {'into': 'Flareon',   'type': 'stone', 'stone': 'Fire Stone'},
        {'into': 'Vaporeon',  'type': 'stone', 'stone': 'Water Stone'},
        {'into': 'Jolteon',   'type': 'stone', 'stone': 'Thunder Stone'},
        {'into': 'Leafeon',   'type': 'stone', 'stone': 'Leaf Stone'},
        {'into': 'Glaceon',   'type': 'stone', 'stone': 'Ice Stone'},
        {'into': 'Espeon',    'type': 'stone', 'stone': 'Sun Stone'},
        {'into': 'Umbreon',   'type': 'stone', 'stone': 'Moon Stone'},
        {'into': 'Sylveon',   'type': 'stone', 'stone': 'Shiny Stone'},
    ],

    # ── Wurmple (a pedra escolhe o casulo; ex-dia/noite) ───
    'wurmple': [
        {'into': 'Silcoon',    'type': 'stone', 'stone': 'Sun Stone'},
        {'into': 'Cascoon',    'type': 'stone', 'stone': 'Moon Stone'},
    ],

    # ── Tyrogue (a pedra escolhe a forma; ex-stat check) ───
    'tyrogue': [
        {'into': 'Hitmonlee',  'type': 'stone', 'stone': 'Sun Stone'},
        {'into': 'Hitmonchan', 'type': 'stone', 'stone': 'Moon Stone'},
        {'into': 'Hitmontop',  'type': 'stone', 'stone': 'Dawn Stone'},
    ],

    # ── Pedra por tipo (ex-trade simples) ─────────────────────
    'kadabra':   {'into': 'Alakazam',   'type': 'stone', 'stone': 'Dawn Stone'},    # Psychic
    'machoke':   {'into': 'Machamp',    'type': 'stone', 'stone': 'Sun Stone'},     # Fighting
    'haunter':   {'into': 'Gengar',     'type': 'stone', 'stone': 'Dusk Stone'},    # Ghost
    'graveler':  {'into': 'Golem',      'type': 'stone', 'stone': 'Shiny Stone'},   # Rock/Ground
    'boldore':   {'into': 'Gigalith',   'type': 'stone', 'stone': 'Shiny Stone'},   # Rock
    'gurdurr':   {'into': 'Conkeldurr', 'type': 'stone', 'stone': 'Sun Stone'},     # Fighting

    # ── Pedra com item temático (ex-trade com item) ────────────
    'poliwhirl': [
        {'into': 'Poliwrath',  'type': 'stone', 'stone': 'Water Stone'},
        {'into': 'Politoed',   'type': 'stone', 'stone': "King's Rock"},
    ],
    'slowpoke':  {'into': 'Slowking',   'type': 'stone', 'stone': 'Dawn Stone'},    # Slowbro vai por nível (evolutionInfo)
    'onix':      {'into': 'Steelix',    'type': 'stone', 'stone': 'Metal Coat'},    # vira Steel
    'scyther':   {'into': 'Scizor',     'type': 'stone', 'stone': 'Metal Coat'},    # vira Steel
    'seadra':    {'into': 'Kingdra',    'type': 'stone', 'stone': 'Dragon Scale'},  # vira Dragon
    'porygon':   {'into': 'Porygon2',   'type': 'stone', 'stone': 'Moon Stone'},    # Normal
    'porygon2':  {'into': 'Porygon-Z',  'type': 'stone', 'stone': 'Shiny Stone'},   # Normal (upgrade)
    'dusclops':  {'into': 'Dusknoir',   'type': 'stone', 'stone': 'Dusk Stone'},    # Ghost
    'rhydon':    {'into': 'Rhyperior',  'type': 'stone', 'stone': 'Shiny Stone'},   # Rock/Ground
    'electabuzz':{'into': 'Electivire', 'type': 'stone', 'stone': 'Thunder Stone'}, # Electric
    'magmar':    {'into': 'Magmortar',  'type': 'stone', 'stone': 'Fire Stone'},    # Fire
    'feebas':    {'into': 'Milotic',    'type': 'stone', 'stone': 'Water Stone'},   # Water
    # NOTA: Rockruff→Lycanroc fica FORA — a espécie Lycanroc não existe no
    # banco de dados (tools/audit_evolutions.py monitora este caso).
}

# Stones that can be used as items (all lowercase for matching)
EVOLUTION_STONES = {
    'fire stone', 'water stone', 'thunder stone', 'leaf stone',
    'moon stone', 'sun stone', 'shiny stone', 'dusk stone',
    'dawn stone', 'ice stone',
    # itens temáticos usados como pedra de evolução
    "king's rock", 'metal coat', 'dragon scale',
}

_STONE_PT_TO_EN = {
    'pedra fogo':        'fire stone',
    'pedra água':        'water stone',
    'pedra agua':        'water stone',
    'pedra trovão':      'thunder stone',
    'pedra trovao':      'thunder stone',
    'pedra folha':       'leaf stone',
    'pedra lua':         'moon stone',
    'pedra solar':       'sun stone',
    'pedra brilhante':   'shiny stone',
    'pedra crepúsculo':  'dusk stone',
    'pedra crepusculo':  'dusk stone',
    'pedra aurora':      'dawn stone',
    'pedra gelo':        'ice stone',
}

EVO_LEVEL_SCALE = 5  # níveis do evolutionInfo são escala 5e = canon/5 (Dragonair 11→55)


# Alvos cujo nome no texto difere do nome da espécie no banco
EVO_TARGET_ALIASES = {
    'meowstic': 'meowstic ♂',   # Espurr → "Meowstic"; banco tem "Meowstic ♂"
}


def parse_level_evolution(info):
    """Extrai do evolutionInfo a evolução por nível PURA (sem condição).
    Retorna (nome_alvo, nível_do_pokemon) ou (None, None).
    - Ramos com 'with the help of <pedra>' são pulados — são evolução por
      pedra (ex.: 'Raichu at level 8 ... with the help of a Thunder Stone'
      NÃO pode evoluir de graça por nível).
    - Ramos com gate de lealdade ('if its loyalty...') também são pulados —
      as ex-evoluções por amizade viraram pedra (SPECIAL_EVOLUTIONS).
    - O 'level N' do banco é escala 5e; o nível do Pokémon do jogo é escala
      canon (1-100) → limiar = N × EVO_LEVEL_SCALE (Ivysaur 3→15, canon 16)."""
    import re
    for m in re.finditer(r"evolve into ([A-Za-z0-9\-\.'\s]+?) at (?:trainer )?level (\d+)",
                         info or '', re.IGNORECASE):
        # só o trecho DESTE ramo: para no ponto ou no próximo "or"/", or"
        # (vírgula sozinha NÃO separa ramo: "…, only if its Loyalty…")
        tail = re.split(r'\.|,? or ', info[m.end():], maxsplit=1)[0].lower()
        if 'with the help' in tail or 'loyalty' in tail:
            continue  # ramo condicional (pedra/ex-amizade) — SPECIAL_EVOLUTIONS
        return m.group(1).strip(), int(m.group(2)) * EVO_LEVEL_SCALE
    return None, None


def get_special_evolution(pokemon_name: str, stone_used: str = None, battle_wins: int = 0, moves: list = None):
    """
    Returns (evolved_into: str, condition_met: bool) for special evolutions.
    stone_used: item name from bag (Portuguese or English).
    battle_wins/moves: aceitos por compatibilidade e ignorados — toda
    condição especial virou pedra.
    """
    name_lower = pokemon_name.strip().lower()
    entry = SPECIAL_EVOLUTIONS.get(name_lower)
    if not entry or not stone_used:
        return None, False

    candidates = entry if isinstance(entry, list) else [entry]

    # Normalise stone name: Portuguese → English
    stone_normalised = _STONE_PT_TO_EN.get(stone_used.strip().lower(), stone_used.strip().lower())

    for cond in candidates:
        if cond['type'] == 'stone' and stone_normalised == cond['stone'].lower():
            return cond['into'], True

    return None, False
