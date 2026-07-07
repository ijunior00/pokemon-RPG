# migrations.py — migração de saves v1 (stats D&D 6-19) → v2 (base stats
# reais 1-255, pokemondb.net).
#
# IDEMPOTENTE: cada Pokémon migrado ganha a flag poke['sv'] = STATS_VERSION e
# nunca é migrado de novo. Chamada nos PONTOS DE LEITURA (equipe, PC, NPCs,
# builders de batalha) — não em database.py genérico.
#
# O que a migração preserva: nível, moves, apelido, natureza, is_shiny, XP,
# held item, notas. O que ela recalcula: stats/maxHp (da espécie, escala
# nova), currentHp (mesma % do máximo antigo), treino (pontos antigos
# distribuídos convertidos ×3 no MESMO stat).
import random

import battle_math as bm
import pokemon_scaling as scaling

STATS_VERSION = 2
# Economia Custom EVs (Pontos de Potencial + Treinamento, custo progressivo).
# Flag independente de sv: um Pokémon já v2 ainda precisa migrar para pp=1.
PP_VERSION = 1

_COMBAT_STATS = ('ATK', 'DEF', 'SPA', 'SPD', 'SPE')
# chaves legadas D&D → novas (saves pré-históricos)
_LEGACY = {'STR': 'ATK', 'CON': 'DEF', 'INT': 'SPA', 'WIS': 'SPD', 'DEX': 'SPE'}


def _expected_v1_stats(species, level, nature, is_shiny):
    """Reconstrói os stats que a fórmula ANTIGA produzia para a espécie no
    nível (sem pontos distribuídos) — base p/ inferir o treino antigo."""
    old_base = dict(species.get('stats') or {})
    if not old_base:
        return None
    if is_shiny:
        old_base = {k: (int(round(v * scaling.SHINY_MULT)) if isinstance(v, (int, float)) else v)
                    for k, v in old_base.items()}
    expected = {}
    for k in _COMBAT_STATS + ('HP',):
        expected[k] = scaling.calculate_stat(int(old_base.get(k, 10) or 10), level)
    if nature:
        expected = scaling.apply_nature(expected, nature)
    return expected


def _infer_old_training(poke, species, level):
    """Pontos distribuídos no sistema antigo = stat salvo − esperado v1,
    clampado ao budget antigo plausível (protege fichas editadas à mão)."""
    saved = poke.get('stats') or {}
    if not saved:
        return {}
    expected = _expected_v1_stats(species, level, poke.get('nature'),
                                  bool(poke.get('is_shiny')))
    if not expected:
        return {}
    spent = {}
    for k in _COMBAT_STATS:
        val = saved.get(k, saved.get({v: lk for lk, v in _LEGACY.items()}.get(k, k)))
        if not isinstance(val, (int, float)):
            # chave legada direta (STR/DEX/...)
            for lk, nk in _LEGACY.items():
                if nk == k and isinstance(saved.get(lk), (int, float)):
                    val = saved[lk]
                    break
        if isinstance(val, (int, float)):
            spent[k] = max(0, int(val) - int(expected.get(k, val)))
    # budget antigo: +1/nível e +1 extra a cada 5 níveis
    budget = max(0, (level - 1) + level // 5)
    total = sum(spent.values())
    if total > budget and total > 0:
        # ficha editada à mão — reduz proporcionalmente
        spent = {k: (v * budget) // total for k, v in spent.items()}
    return spent


def migrate_pokemon_v2(poke, species_by_name, species_by_number=None):
    """Migra UM dict de Pokémon in-place. Retorna True se mudou algo."""
    if not isinstance(poke, dict) or poke.get('sv') == STATS_VERSION:
        return False
    if not poke.get('name') and not poke.get('number'):
        return False

    species = species_by_name.get((poke.get('name') or '').lower())
    if not species and species_by_number:
        species = species_by_number.get(poke.get('number'))
    level = max(1, int(poke.get('level') or 1))

    # % de HP antes da migração (desmaiado continua desmaiado)
    old_max = poke.get('maxHp') or poke.get('hp') or 0
    cur = poke.get('currentHp')
    hp_ratio = None
    if isinstance(cur, (int, float)) and old_max:
        hp_ratio = max(0.0, min(1.0, float(cur) / float(old_max)))

    # treino: converte pontos antigos ×3 no mesmo stat, respeitando o teto
    training = {}
    if species:
        old_spent = _infer_old_training(poke, species, level)
        cap = bm.training_cap(level)
        budget = bm.training_budget(level)
        for k in _COMBAT_STATS:
            training[k] = min(cap, int(old_spent.get(k, 0)) * 3)
        # não deixa o treino convertido estourar o budget novo
        total = sum(training.values())
        if total > budget and total > 0:
            training = {k: (v * budget) // total for k, v in training.items()}
    poke['training'] = {k: training.get(k, 0) for k in _COMBAT_STATS + ('HP',)}

    # recalcula stats/HP do zero pela fórmula v2 (espécie + shiny + treino)
    base = species or poke
    scaled = scaling.calculate_pokemon_stats(base, level, poke.get('nature'),
                                             is_shiny=bool(poke.get('is_shiny')),
                                             training=poke['training'])
    poke['stats'] = scaled['stats']
    poke['maxHp'] = scaled['maxHp']
    poke['hp'] = scaled['maxHp']
    if hp_ratio is None:
        poke['currentHp'] = scaled['maxHp']
    elif cur <= 0:
        poke['currentHp'] = 0 if cur == 0 else cur   # preserva negativo (permadeath)
    else:
        poke['currentHp'] = max(1, round(scaled['maxHp'] * hp_ratio))

    # saldo de treino DERIVADO (conserta o bug antigo de pontos apagados)
    poke['statPointsAvailable'] = max(0, bm.training_budget(level)
                                      - sum(poke['training'].values()))
    poke.setdefault('defense_mode', 1)
    # stages/CAs antigos não fazem sentido na escala nova
    poke.pop('stat_stages', None)
    poke.pop('phys_ac', None)
    poke.pop('spec_ac', None)
    poke.pop('dodge_ac', None)
    poke['sv'] = STATS_VERSION
    return True


# ── Custom EVs (economia v3): Pontos de Potencial + Treinamento ─────────────
def _species_of(poke, species_by_name, species_by_number=None):
    sp = species_by_name.get((poke.get('name') or '').lower())
    if not sp and species_by_number:
        sp = species_by_number.get(poke.get('number'))
    return sp


def budget_for(poke, species):
    """Orçamento total de pontos (Potencial + Treinamento) do Pokémon,
    usado pela migração e pela validação do endpoint de distribuição."""
    level = max(1, int(poke.get('level') or 1))
    cur, tot = bm.parse_evolution_stage((species or {}).get('evolutionStage'))
    return bm.points_budget(
        level, cur, tot,
        evo_bonus=int(poke.get('potential_evo_bonus') or 0),
        special=int(poke.get('potential_special') or 0),
        train_bonus=int(poke.get('training_bonus') or 0),
    )


def _retro_evo_bonus(stage_current):
    """Bônus de evolução RETROATIVO p/ Pokémon que já estava evoluído antes
    do sistema existir. Determinístico (média do dado) de propósito: a
    migração roda em pontos de leitura sem persistir, então um valor aleatório
    daria orçamentos diferentes a cada carga. Evoluções DURANTE o jogo rolam
    o dado de verdade (roll_evolution_bonus). ≈média(1d6)=4, ≈média(1d8)=5."""
    b = 0
    if stage_current >= 2:
        b += 4
    if stage_current >= 3:
        b += 5
    return b


def roll_evolution_bonus(from_stage, to_stage):
    """Bônus rolado NA hora de uma evolução real durante o jogo (permanente):
    1d6 ao chegar no estágio 2, 1d8 ao chegar no 3. Retorna o total a somar."""
    b = 0
    for st in range(int(from_stage) + 1, int(to_stage) + 1):
        if st == 2:
            b += random.randint(1, 6)
        elif st >= 3:
            b += random.randint(1, 8)
    return b


def migrate_pokemon_pp(poke, species_by_name, species_by_number=None):
    """Migra UM Pokémon para a economia Custom EVs. Idempotente (flag pp).
    A distribuição antiga (custo linear) é incompatível com o custo
    progressivo, então é ZERADA (backup em training_old_v2) e o jogador
    redistribui sob as novas regras."""
    if not isinstance(poke, dict) or poke.get('pp') == PP_VERSION:
        return False
    if not poke.get('name') and not poke.get('number'):
        return False
    species = _species_of(poke, species_by_name, species_by_number)
    level = max(1, int(poke.get('level') or 1))
    cur, _tot = bm.parse_evolution_stage((species or {}).get('evolutionStage'))

    if 'potential_evo_bonus' not in poke:
        poke['potential_evo_bonus'] = _retro_evo_bonus(cur)
    poke.setdefault('potential_special', 0)   # bônus de Potencial do mestre
    poke.setdefault('training_bonus', 0)       # bônus de Treinamento do mestre

    old = poke.get('training') or {}
    if any((old.get(k) or 0) for k in old):
        poke['training_old_v2'] = dict(old)
    poke['training'] = {k: 0 for k in bm.TRAINING_STATS}

    if species:
        scaled = scaling.calculate_pokemon_stats(
            species, level, poke.get('nature'),
            is_shiny=bool(poke.get('is_shiny')), training=poke['training'])
        old_max = poke.get('maxHp') or scaled['maxHp']
        cur_hp = poke.get('currentHp')
        ratio = (max(0.0, min(1.0, float(cur_hp) / float(old_max)))
                 if isinstance(cur_hp, (int, float)) and old_max else None)
        poke['stats'] = scaled['stats']
        poke['maxHp'] = scaled['maxHp']
        poke['hp'] = scaled['maxHp']
        if ratio is None:
            poke['currentHp'] = scaled['maxHp']
        elif cur_hp <= 0:
            poke['currentHp'] = cur_hp
        else:
            poke['currentHp'] = max(1, round(scaled['maxHp'] * ratio))

    budget = budget_for(poke, species)
    poke['statPointsAvailable'] = max(0, budget - bm.training_spent(poke['training']))
    poke['pp'] = PP_VERSION
    return True


def ensure_v2(pokes, species_by_name, species_by_number=None):
    """Migra uma LISTA de Pokémon in-place (v2 + Custom EVs). Retorna True se
    algum mudou."""
    changed = False
    for p in (pokes or []):
        c2 = migrate_pokemon_v2(p, species_by_name, species_by_number)
        cp = migrate_pokemon_pp(p, species_by_name, species_by_number)
        changed = changed or c2 or cp
    return changed
