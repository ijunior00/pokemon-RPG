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


# Habilidades que dobram o STAB quando o HP está em 25% ou menos
# (texto 5e: "doubles its STAB bonus when it has 25% or less of its max health")
STAB_BOOST_ABILITIES = {
    'blaze': 'fire',
    'overgrow': 'grass',
    'torrent': 'water',
    'swarm': 'bug',
}


def stab_multiplier(ability, move_type_en: str, current_hp, max_hp) -> int:
    """2 se a habilidade dobra o STAB deste move com o HP atual, senão 1."""
    key = normalize_ability(ability)
    boosted_type = STAB_BOOST_ABILITIES.get(key)
    if not boosted_type or boosted_type != (move_type_en or '').lower():
        return 1
    try:
        if max_hp and current_hp is not None and current_hp <= max_hp * 0.25:
            return 2
    except TypeError:
        pass
    return 1


def check_contact_ability(ability, defender_prof: int) -> dict | None:
    """Reação do defensor a um ataque físico (contato).

    Retorna {'damage': int, 'status': str|None, 'message': str} ou None.
    O dano retornado é aplicado ao ATACANTE.
    """
    import random as _r
    key = normalize_ability(ability)
    prof = max(1, int(defender_prof or 2))

    if key == 'static' and _r.random() < 0.25:
        return {'damage': prof, 'status': None,
                'message': f'⚡ Static: o atacante levou {prof} de dano elétrico!'}
    if key == 'flame body' and _r.random() < 0.25:
        return {'damage': 0, 'status': 'queimado',
                'message': '🔥 Flame Body: o atacante foi queimado!'}
    if key == 'poison point' and _r.random() < 0.25:
        return {'damage': 0, 'status': 'badly_poisoned',
                'message': '☠️ Poison Point: o atacante foi envenenado!'}
    if key == 'effect spore' and _r.random() < 0.25:
        status = _r.choice(['dormindo', 'paralisado', 'badly_poisoned'])
        return {'damage': 0, 'status': status,
                'message': '🍄 Effect Spore: esporos atingiram o atacante!'}
    if key in ('rough skin', 'iron barbs'):
        return {'damage': prof, 'status': None,
                'message': f'🗡️ {ability if isinstance(ability, str) else key}: o atacante levou {prof} de dano!'}
    if key == 'cute charm' and _r.random() < 0.30:
        return {'damage': 0, 'status': 'apaixonado',
                'message': '💕 Cute Charm: o atacante ficou atraído!'}
    if key == 'aftermath':
        # dano ao atacante quando o portador cai por golpe de contato (~¼ do HP)
        return {'damage': prof * 2, 'status': None,
                'message': f'💥 Aftermath: o atacante levou {prof * 2} de dano de contato!'}
    return None


def check_attacker_contact_ability(ability) -> dict | None:
    """Habilidade do ATACANTE que reage ao acertar um golpe de contato (físico).

    Ao contrário de check_contact_ability (defensor), aqui é o ATACANTE quem tem a
    habilidade e o efeito recai sobre o DEFENSOR. Ex.: Poison Touch (30% envenena
    ao tocar). Retorna {'status': str|None, 'message': str} aplicado ao defensor,
    ou None.
    """
    import random as _r
    key = normalize_ability(ability)

    if key == 'poison touch' and _r.random() < 0.30:
        return {'status': 'badly_poisoned',
                'message': '☠️ Toque Venenoso: o alvo foi envenenado pelo contato!'}
    if key == 'toxic chain' and _r.random() < 0.30:
        return {'status': 'badly_poisoned',
                'message': '☠️ Corrente Tóxica: o alvo foi gravemente envenenado!'}
    if key == 'stench' and _r.random() < 0.10:
        return {'status': 'atordoado',
                'message': '🤢 Fedor: o alvo recuou de nojo!'}
    return None


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


def ability_blocks_weather_damage(pokemon) -> bool:
    """True se a habilidade impede o dano de clima (areia/granizo): Magic
    Guard (sem dano indireto), Overcoat, Sand Veil/Force/Rush, Ice Body/
    Snow Cloak/Slush Rush."""
    key = get_ability_key(pokemon or {})
    if ABILITY_PASSIVES.get(key) in ('no_indirect', 'immune_weather',
                                     'evasion_sand', 'evasion_hail'):
        return True
    return key in ('sand force', 'sand rush', 'ice body', 'slush rush')


# ═══════════════════════════════════════════════════════════════════════════
# HABILIDADES PASSIVAS — expansão (multiplicadores de stat/dano, imunidades de
# status, crítico). Aplicadas em chokepoints únicos: effective_stat (stats) e
# _calc_attack_core (dano/crítico) — valem em TODOS os modos de batalha.
# ═══════════════════════════════════════════════════════════════════════════

# Multiplicadores CONSTANTES de stat (Huge Power dobra ATK etc.). Cada valor é
# (stat, mult) ou uma função(pokemon)->(stat,mult)|None para as condicionais.
ABILITY_STAT_MULT = {
    'huge power':  ('ATK', 2.0),
    'pure power':  ('ATK', 2.0),
    'hustle':      ('ATK', 1.5),   # (também -20% accuracy física; simplificado)
    'fur coat':    ('DEF', 2.0),
    'gorilla tactics': ('ATK', 1.5),
}

# Condicionais: função recebe o pokemon e devolve {stat: mult}
def _cond_ability_mult(pokemon):
    key = get_ability_key(pokemon)
    out = {}
    hp = pokemon.get('currentHp')
    mx = pokemon.get('maxHp') or 1
    statused = bool(pokemon.get('status'))
    if key == 'defeatist' and isinstance(hp, (int, float)) and hp <= mx * 0.5:
        out['ATK'] = out.get('ATK', 1.0) * 0.5
        out['SPA'] = out.get('SPA', 1.0) * 0.5
    if key == 'slow start' and pokemon.get('slow_start_active'):
        out['ATK'] = out.get('ATK', 1.0) * 0.5
        out['SPE'] = out.get('SPE', 1.0) * 0.5
    if key == 'solar power':          # sem clima: bônus permanente de SpA modesto
        out['SPA'] = out.get('SPA', 1.0) * 1.3
    if key == 'guts' and statused:
        out['ATK'] = out.get('ATK', 1.0) * 1.5
    if key == 'marvel scale' and statused:
        out['DEF'] = out.get('DEF', 1.0) * 1.5
    if key == 'quick feet' and statused:
        out['SPE'] = out.get('SPE', 1.0) * 1.5
    if key == 'toxic boost' and (pokemon.get('status') or {}).get('condition') in ('badly_poisoned', 'poisoned'):
        out['ATK'] = out.get('ATK', 1.0) * 1.5
    if key == 'flare boost' and (pokemon.get('status') or {}).get('condition') == 'queimado':
        out['SPA'] = out.get('SPA', 1.0) * 1.5
    return out


def stat_multiplier_for(pokemon, stat):
    """Multiplicador da habilidade sobre um stat (1.0 se nenhum). Chamado por
    effective_stat — logo vale em qualquer caminho de batalha."""
    if not isinstance(pokemon, dict):
        return 1.0
    key = get_ability_key(pokemon)
    mult = 1.0
    fixed = ABILITY_STAT_MULT.get(key)
    if fixed and fixed[0] == stat:
        mult *= fixed[1]
    mult *= _cond_ability_mult(pokemon).get(stat, 1.0)
    return mult


# ── Multiplicadores de DANO por classe de golpe ──
_PUNCH = {'mach punch', 'bullet punch', 'mega punch', 'fire punch', 'ice punch',
          'thunder punch', 'comet punch', 'dizzy punch', 'focus punch', 'dynamic punch',
          'sky uppercut', 'hammer arm', 'meteor mash', 'shadow punch', 'drain punch',
          'power-up punch', 'ice hammer', 'plasma fists', 'double iron bash'}
_BITE = {'bite', 'crunch', 'hyper fang', 'thunder fang', 'ice fang', 'fire fang',
         'poison fang', 'psychic fangs', 'fishious rend', 'jaw lock', 'super fang'}
_PULSE = {'water pulse', 'dragon pulse', 'dark pulse', 'aura sphere', 'origin pulse',
          'heal pulse', 'terrain pulse'}
_RECOIL = {'take down', 'double-edge', 'submission', 'volt tackle', 'flare blitz',
           'brave bird', 'wood hammer', 'head smash', 'wild charge', 'head charge',
           'light of ruin', 'wave crash'}


def ability_damage_mult(pokemon, move_name, move_type_en, category, power,
                        is_crit=False, effectiveness=1.0, attacker_types=None):
    """Multiplicador de dano da habilidade do ATACANTE. Chamado uma vez em
    _calc_attack_core → vale em PvP, NPC, selvagem e grupo."""
    if not isinstance(pokemon, dict):
        return 1.0
    key = get_ability_key(pokemon)
    nm = (move_name or '').lower()
    mt = (move_type_en or '').lower()
    mult = 1.0
    contact = category == 'physical'   # aproximação: físico ≈ contato

    if key == 'iron fist' and nm in _PUNCH:
        mult *= 1.2
    if key == 'strong jaw' and (nm in _BITE or 'fang' in nm):
        mult *= 1.5
    if key == 'tough claws' and contact:
        mult *= 1.3
    if key in ('mega launcher',) and (nm in _PULSE or 'pulse' in nm or nm == 'aura sphere'):
        mult *= 1.5
    if key in ('steelworker', 'steely spirit') and mt == 'steel':
        mult *= 1.5
    if key == 'technician' and power and int(power) <= 60:
        mult *= 1.5
    if key == 'reckless' and nm in _RECOIL:
        mult *= 1.2
    if key in ('sheer force',) and _move_has_secondary(nm):
        mult *= 1.3
    if key == 'adaptability' and attacker_types and mt in [t.lower() for t in attacker_types]:
        mult *= 1.33   # STAB 1.5 → 2.0 ≈ +33% sobre o dano já com STAB
    if key == 'tinted lens' and effectiveness < 1:
        mult *= 2.0
    if key in ('neuroforce',) and effectiveness > 1:
        mult *= 1.25
    # Analytic depende de agir por último (ordem de turno) — não aplicado aqui
    if key == 'sniper' and is_crit:
        mult *= 1.5
    if key == 'sand force' and mt in ('rock', 'ground', 'steel'):
        mult *= 1.1
    if key == 'punk rock' and _is_sound(nm):
        mult *= 1.3
    return mult


def _move_has_secondary(nm):
    from status_effects import MOVE_STATUS_EFFECTS
    return nm.title() in MOVE_STATUS_EFFECTS or nm in ('flamethrower', 'ice beam', 'thunderbolt')


_SOUND = {'hyper voice', 'boomburst', 'bug buzz', 'echoed voice', 'round',
          'snarl', 'uproar', 'overdrive', 'sparkling aria', 'clanging scales',
          'disarming voice', 'relic song', 'clangorous soul'}


def _is_sound(nm):
    return nm in _SOUND


# ── Imunidades a STATUS ──
STATUS_IMMUNITIES = {
    'immunity':      ['badly_poisoned', 'poisoned'],
    'pastel veil':   ['badly_poisoned', 'poisoned'],
    'limber':        ['paralisado'],
    'insomnia':      ['dormindo'],
    'vital spirit':  ['dormindo'],
    'sweet veil':    ['dormindo'],
    'comatose':      ['dormindo', 'paralisado', 'queimado', 'congelado', 'badly_poisoned', 'poisoned'],
    'water veil':    ['queimado'],
    'water bubble':  ['queimado'],
    'thermal exchange': ['queimado'],
    'magma armor':   ['congelado'],
    'own tempo':     ['confuso'],
    'oblivious':     ['apaixonado'],
    'inner focus':   ['atordoado'],
    'shield dust':   [],   # bloqueia efeitos SECUNDÁRIOS (tratado no on-hit)
    'purifying salt': ['badly_poisoned', 'poisoned', 'paralisado', 'dormindo',
                       'queimado', 'congelado', 'confuso'],
    'leaf guard':    [],   # só sob sol; sem clima não imuniza
    'full metal body': [],
}


def is_status_immune(pokemon, status_key):
    """True se a habilidade do Pokémon o torna imune a este status."""
    if not isinstance(pokemon, dict) or not status_key:
        return False
    key = get_ability_key(pokemon)
    if key == 'shield dust':
        return True   # efeitos secundários de golpe não pegam
    return status_key in STATUS_IMMUNITIES.get(key, [])


# ── Crítico ──
ABILITY_NO_CRIT_AGAINST = {'battle armor', 'shell armor'}


def ability_prevents_crit(defender_ability):
    """Battle Armor / Shell Armor impedem crítico contra o portador."""
    return normalize_ability(defender_ability) in ABILITY_NO_CRIT_AGAINST


def ability_forces_crit(attacker_pokemon, defender_pokemon):
    """Merciless: crítico garantido contra alvo envenenado."""
    if get_ability_key(attacker_pokemon or {}) != 'merciless':
        return False
    cond = (defender_pokemon.get('status') or {}).get('condition') if isinstance(defender_pokemon, dict) else None
    return cond in ('badly_poisoned', 'poisoned')


# ── On-KO: sobe um stat ofensivo ao nocautear ──
ABILITY_KO_BOOST = {
    'moxie': 'ATK', 'beast boost': 'ATK', 'chilling neigh': 'ATK',
    'grim neigh': 'SPA', 'soul-heart': 'SPA', "as one": 'ATK',
}


def ability_ko_boost(ability):
    """Stat ofensivo que sobe +1 estágio ao nocautear, ou None."""
    return ABILITY_KO_BOOST.get(normalize_ability(ability))


# ═══════════════════════════════════════════════════════════════════════════
# DESCRIÇÕES — TODAS as habilidades citadas pelas espécies ficam "conhecidas"
# e exibidas na ficha (as narrativas são adjudicadas pelo Mestre).
# ═══════════════════════════════════════════════════════════════════════════
ABILITY_DESCRIPTIONS = {
    'adaptability': 'STAB aumenta de ×1,5 para ×2,0.',
    'aftermath': 'Ao ser nocauteado por contato, causa dano ao atacante.',
    'air lock': 'Anula os efeitos do clima enquanto está em campo.',
    'analytic': 'Golpes ficam mais fortes se você age por último.',
    'anger point': 'Ao sofrer um crítico, o Ataque vai ao máximo.',
    'anticipation': 'Pressente golpes perigosos do oponente.',
    'arena trap': 'Impede o oponente terrestre de fugir/trocar.',
    'aroma veil': 'Protege a equipe de efeitos que impedem o uso de golpes.',
    'bad dreams': 'Adversários adormecidos perdem HP a cada turno.',
    'battery': 'Fortalece os golpes especiais dos aliados.',
    'battle armor': 'Bloqueia acertos críticos contra você.',
    'beast boost': 'Ao nocautear, aumenta seu melhor stat.',
    'berserk': 'Ao cair abaixo de 50% de HP, aumenta o Ataque Especial.',
    'big pecks': 'Sua Defesa não pode ser reduzida.',
    'blaze': 'Fortalece golpes de Fogo quando o HP está baixo.',
    'bulletproof': 'Imune a golpes de bola/bomba.',
    'cheek pouch': 'Recupera HP extra ao usar uma baga.',
    'chlorophyll': 'Dobra a Velocidade sob sol forte.',
    'clear body': 'Seus stats não podem ser reduzidos pelo oponente.',
    'cloud nine': 'Anula os efeitos do clima.',
    'color change': 'Muda de tipo para o do golpe que o atingiu.',
    'comatose': 'Está sempre "dormindo"; imune a outras condições.',
    'competitive': 'Ao ter um stat reduzido, aumenta muito o Atq. Especial.',
    'compound eyes': 'Aumenta a precisão dos golpes.',
    'contrary': 'Inverte as mudanças de stats (quedas viram ganhos).',
    'corrosion': 'Pode envenenar até tipos Aço e Veneno.',
    'cursed body': 'Pode desabilitar o golpe que o atingiu.',
    'cute charm': 'Pode apaixonar quem o toca.',
    'damp': 'Impede golpes de explosão.',
    'dancer': 'Copia golpes de dança usados em campo.',
    'dark aura': 'Fortalece todos os golpes do tipo Sombrio.',
    'dazzling': 'Bloqueia golpes de prioridade contra sua equipe.',
    'defeatist': 'Com metade ou menos do HP, Ataque e Atq. Especial caem à metade.',
    'defiant': 'Ao ter um stat reduzido, aumenta muito o Ataque.',
    'disguise': 'Evita o dano do primeiro golpe (a forma se desfaz).',
    'early bird': 'Acorda do sono mais rápido.',
    'electric surge': 'Cria o Terreno Elétrico ao entrar.',
    'emergency exit': 'Sai de campo ao cair abaixo de 50% de HP.',
    'fairy aura': 'Fortalece todos os golpes do tipo Fada.',
    'flame body': 'Pode queimar quem o toca.',
    'flower gift': 'Sob sol, fortalece Ataque e Def. Especial da equipe.',
    'flower veil': 'Protege aliados do tipo Grama de perder stats/condições.',
    'forecast': 'Muda de tipo conforme o clima.',
    'forewarn': 'Revela o golpe mais forte do oponente.',
    'friend guard': 'Reduz o dano sofrido pelos aliados.',
    'frisk': 'Revela o item que o oponente carrega.',
    'full metal body': 'Seus stats não podem ser reduzidos pelo oponente.',
    'fur coat': 'Dobra a Defesa física.',
    'gale wings': 'Golpes Voadores ganham prioridade com o HP cheio.',
    'gluttony': 'Usa bagas de recuperação mais cedo.',
    'gooey': 'Reduz a Velocidade de quem o toca.',
    'grass pelt': 'Aumenta a Defesa em terreno de grama.',
    'grassy surge': 'Cria o Terreno de Grama ao entrar.',
    'harvest': 'Pode recuperar uma baga consumida.',
    'healer': 'Pode curar condições dos aliados.',
    'heavy metal': 'Dobra o próprio peso.',
    'honey gather': 'Pode coletar mel após a batalha.',
    'huge power': 'Dobra o Ataque físico.',
    'hustle': 'Aumenta o Ataque, mas reduz a precisão física.',
    'hydration': 'Cura condições sob chuva.',
    'hyper cutter': 'Seu Ataque não pode ser reduzido.',
    'ice body': 'Recupera HP sob granizo; imune ao dano dele.',
    'illuminate': 'Sua precisão não pode ser reduzida; atrai encontros.',
    'illusion': 'Entra disfarçado de outro Pokémon da equipe.',
    'immunity': 'Imune a envenenamento.',
    'imposter': 'Transforma-se no oponente ao entrar.',
    'infiltrator': 'Ignora telas e barreiras do oponente.',
    'innards out': 'Ao ser nocauteado, causa dano igual ao HP perdido.',
    'inner focus': 'Não recua (imune a flinch).',
    'insomnia': 'Não pode dormir.',
    'iron barbs': 'Causa dano a quem o toca.',
    'iron fist': 'Fortalece golpes de soco.',
    'justified': 'Aumenta o Ataque ao ser atingido por golpe Sombrio.',
    'keen eye': 'Sua precisão não pode ser reduzida.',
    'klutz': 'Não consegue usar itens seguráveis.',
    'leaf guard': 'Não sofre condições sob sol forte.',
    'light metal': 'Reduz o próprio peso à metade.',
    'limber': 'Não pode ser paralisado.',
    'liquid ooze': 'Golpes de dreno ferem quem tenta drenar.',
    'liquid voice': 'Golpes sonoros viram do tipo Água.',
    'long reach': 'Golpes não fazem contato.',
    'magician': 'Rouba o item do alvo ao acertá-lo.',
    'magma armor': 'Não pode ser congelado.',
    'magnet pull': 'Impede tipos Aço de fugir/trocar.',
    'mega launcher': 'Fortalece golpes de pulso/aura.',
    'merciless': 'Sempre acerta crítico em alvos envenenados.',
    'minus': 'Aumenta o Atq. Especial se um aliado tem Plus/Minus.',
    'misty surge': 'Cria o Terreno Enevoado ao entrar.',
    'mold breaker': 'Ignora habilidades defensivas do alvo.',
    'moody': 'A cada turno, sobe muito um stat e reduz outro.',
    'moxie': 'Ao nocautear, aumenta o Ataque.',
    'multiscale': 'Reduz o dano recebido com o HP cheio.',
    'multitype': 'Muda de tipo conforme a placa segurada.',
    'mummy': 'Contato transforma a habilidade do atacante em Mummy.',
    'no guard': 'Todos os golpes (seus e contra você) sempre acertam.',
    'normalize': 'Todos os golpes viram do tipo Normal.',
    'oblivious': 'Imune a atração e provocação.',
    'overgrow': 'Fortalece golpes de Grama quando o HP está baixo.',
    'own tempo': 'Imune à confusão.',
    'pickpocket': 'Rouba o item de quem o toca.',
    'pickup': 'Pode pegar itens após a batalha.',
    'pixilate': 'Golpes Normais viram Fada e ficam mais fortes.',
    'plus': 'Aumenta o Atq. Especial se um aliado tem Plus/Minus.',
    'poison heal': 'Recupera HP com veneno em vez de perder.',
    'poison point': 'Pode envenenar quem o toca.',
    'poison touch': 'Pode envenenar o alvo ao tocá-lo.',
    'power construct': 'Muda para a Forma Completa com HP baixo.',
    'prankster': 'Golpes de status ganham prioridade.',
    'protean': 'Muda para o tipo do golpe que vai usar.',
    'psychic surge': 'Cria o Terreno Psíquico ao entrar.',
    'pure power': 'Dobra o Ataque físico.',
    'queenly majesty': 'Bloqueia golpes de prioridade contra a equipe.',
    'rain dish': 'Recupera HP sob chuva.',
    'rattled': 'Aumenta a Velocidade ao ser atingido por Inseto/Fantasma/Sombrio.',
    'receiver': 'Herda a habilidade de um aliado que cair.',
    'reckless': 'Fortalece golpes com recuo.',
    'refrigerate': 'Golpes Normais viram Gelo e ficam mais fortes.',
    'rivalry': 'Mais dano contra o mesmo gênero, menos contra o oposto.',
    'rock head': 'Não sofre recuo dos próprios golpes.',
    'rks system': 'Muda de tipo conforme o disco de memória.',
    'run away': 'Sempre foge de Pokémon selvagens.',
    'sand force': 'Fortalece golpes Rocha/Terra/Aço na tempestade de areia.',
    'sand rush': 'Dobra a Velocidade na tempestade de areia.',
    'sand veil': 'Aumenta a evasão na tempestade de areia.',
    'schooling': 'Fica mais forte em cardume com HP alto.',
    'scrappy': 'Golpes Normais/Lutador atingem tipos Fantasma.',
    'serene grace': 'Dobra a chance de efeitos secundários.',
    'shadow shield': 'Reduz o dano recebido com o HP cheio.',
    'shadow tag': 'Impede o oponente de fugir/trocar.',
    'shed skin': 'Pode curar condições a cada turno.',
    'sheer force': 'Golpes com efeito secundário ficam mais fortes (sem o efeito).',
    'shell armor': 'Bloqueia acertos críticos contra você.',
    'shield dust': 'Bloqueia efeitos secundários dos golpes recebidos.',
    'shields down': 'Muda de forma conforme o HP (Minior).',
    'simple': 'Dobra as mudanças de stats.',
    'skill link': 'Golpes de múltiplos acertos sempre acertam o máximo.',
    'slow start': 'Ataque e Velocidade reduzidos nos primeiros turnos.',
    'slush rush': 'Dobra a Velocidade sob granizo/neve.',
    'sniper': 'Críticos causam ainda mais dano.',
    'snow cloak': 'Aumenta a evasão sob granizo.',
    'snow warning': 'Invoca granizo/neve ao entrar.',
    'solar power': 'Sob sol, aumenta o Atq. Especial (perde HP).',
    'soul-heart': 'Aumenta o Atq. Especial quando um Pokémon cai.',
    'soundproof': 'Imune a golpes sonoros.',
    'stakeout': 'Dobra o dano contra quem acabou de entrar.',
    'stall': 'Age por último.',
    'stamina': 'Aumenta a Defesa ao ser atingido.',
    'stance change': 'Alterna entre formas Escudo e Lâmina (Aegislash).',
    'static': 'Pode paralisar quem o toca.',
    'steadfast': 'Aumenta a Velocidade ao recuar.',
    'steelworker': 'Fortalece golpes do tipo Aço.',
    'stench': 'Pode fazer o alvo recuar.',
    'sticky hold': 'Seu item não pode ser roubado.',
    'strong jaw': 'Fortalece golpes de mordida.',
    'suction cups': 'Não pode ser forçado a trocar.',
    'super luck': 'Aumenta a taxa de acerto crítico.',
    'swarm': 'Fortalece golpes de Inseto quando o HP está baixo.',
    'sweet veil': 'A equipe não pode dormir.',
    'swift swim': 'Dobra a Velocidade sob chuva.',
    'symbiosis': 'Passa o próprio item a um aliado que usar o seu.',
    'synchronize': 'Passa queimadura/veneno/paralisia de volta ao causador.',
    'tangled feet': 'Aumenta a evasão quando confuso.',
    'technician': 'Fortalece golpes fracos (potência ≤ 60).',
    'telepathy': 'Evita golpes de aliados em batalha dupla.',
    'teravolt': 'Ignora habilidades defensivas do alvo.',
    'tinted lens': 'Dobra o dano de golpes pouco eficazes.',
    'tough claws': 'Fortalece golpes de contato.',
    'triage': 'Golpes de cura ganham prioridade.',
    'truant': 'Só age em turnos alternados.',
    'turboblaze': 'Ignora habilidades defensivas do alvo.',
    'unaware': 'Ignora as mudanças de stats do oponente.',
    'unburden': 'Dobra a Velocidade ao perder o item seguro.',
    'victory star': 'Aumenta a precisão da equipe.',
    'vital spirit': 'Não pode dormir.',
    'water compaction': 'Aumenta muito a Defesa ao ser atingido por Água.',
    'water veil': 'Não pode ser queimado.',
    'weak armor': 'Ao sofrer golpe físico, Defesa cai e Velocidade sobe.',
    'white smoke': 'Seus stats não podem ser reduzidos pelo oponente.',
    'wimp out': 'Sai de campo ao cair abaixo de 50% de HP.',
    'wonder skin': 'Reduz a chance de golpes de status acertarem.',
    'zen mode': 'Muda de forma com HP baixo (Darmanitan).',
    # já implementadas mecanicamente (descrição p/ exibição)
    'intimidate': 'Reduz o Ataque do oponente ao entrar.',
    'levitate': 'Imune a golpes do tipo Terra.',
    'sturdy': 'Sobrevive a um golpe fatal com o HP cheio (1 HP).',
    'guts': 'Aumenta o Ataque quando afetado por uma condição.',
    'marvel scale': 'Aumenta a Defesa quando afetado por uma condição.',
    'quick feet': 'Aumenta a Velocidade quando afetado por uma condição.',
    'toxic boost': 'Aumenta o Ataque quando envenenado.',
    'flare boost': 'Aumenta o Atq. Especial quando queimado.',
    'rough skin': 'Causa dano a quem o toca.',
    'thick fat': 'Resiste a golpes de Fogo e Gelo.',
    'flash fire': 'Imune a Fogo; fortalece os próprios golpes de Fogo.',
    'water absorb': 'Recupera HP ao ser atingido por Água.',
    'volt absorb': 'Recupera HP ao ser atingido por Eletricidade.',
    'sap sipper': 'Imune a Grama; aumenta o Ataque.',
    'lightning rod': 'Atrai e absorve golpes Elétricos.',
    'storm drain': 'Atrai e absorve golpes de Água.',
    'motor drive': 'Imune a Eletricidade; aumenta a Velocidade.',
    'dry skin': 'Recupera com Água; sofre mais com Fogo.',
    'speed boost': 'Aumenta a Velocidade a cada turno.',
    'magic guard': 'Só sofre dano de golpes diretos.',
    'natural cure': 'Cura condições ao sair de campo.',
    'regenerator': 'Recupera HP ao sair de campo.',
    'overcoat': 'Imune a clima e golpes de pó.',
    'magic bounce': 'Reflete golpes de status de volta.',
    'download': 'Aumenta o stat ofensivo conforme a defesa do oponente.',
    'drought': 'Invoca sol forte ao entrar.',
    'drizzle': 'Invoca chuva ao entrar.',
    'sand stream': 'Invoca tempestade de areia ao entrar.',
    'pressure': 'O oponente gasta mais PP.',
    'unnerve': 'O oponente não consegue usar bagas.',
    'trace': 'Copia a habilidade do oponente ao entrar.',
    'filter': 'Reduz o dano de golpes super eficazes.',
    'solid rock': 'Reduz o dano de golpes super eficazes.',
    'prism armor': 'Reduz o dano de golpes super eficazes.',
    'effect spore': 'Contato pode causar sono, paralisia ou veneno.',
    'poison heal ': 'Recupera HP com veneno.',
    'heatproof': 'Resiste a golpes de Fogo.',
}


def ability_description(ability) -> str:
    """Descrição curta da habilidade (para exibição na ficha)."""
    return ABILITY_DESCRIPTIONS.get(normalize_ability(ability), '')


def is_known_ability(ability) -> bool:
    key = normalize_ability(ability)
    return bool(key) and (key in ABILITY_DESCRIPTIONS or key in ALL_ABILITIES
                          or key in ABILITY_STAT_MULT or key in STATUS_IMMUNITIES
                          or key in STAB_BOOST_ABILITIES or key in ABILITY_KO_BOOST)
