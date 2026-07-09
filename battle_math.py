# battle_math.py — FONTE ÚNICA das fórmulas de combate (sistema de base stats
# reais 1-255, escala do pokemondb.net).
#
# ESPELHADO 1:1 em static/js/battle_math.js — qualquer mudança aqui precisa
# ser replicada lá (o teste de paridade no stress compara os dois).
#
# Princípios:
#  - Acerto: d20 vs Accuracy do move (chance FIXA por move — não existe mais
#    CA nem "sempre acerta/nunca acerta" por diferença de stats).
#  - Dano: dados derivados do Power × razão Atk/Def (clampada) × postura.
#  - Stats derivam SEMPRE dos base stats da espécie (+ shiny ×1.35 aplicado
#    antes, + treino) — nunca aplicar bônus direto em estatística derivada.
import math
import random as _random

# ── Constantes de balanceamento (ajustáveis em playtest) ──────────────────
RATIO_CLAMP = (0.5, 2.0)      # limites da razão Atk_ef / Def_ef
STAB_MULT = 1.5               # bônus de tipo igual (como nos jogos)
# Escala GLOBAL de dano: comprime todo dano por dados sem tocar em
# STAB/efetividade/posturas (que continuam relativos entre si).
# Antigo equivalente: 1.0 (janela de 2-4 turnos até o KO). Com ×0.20 as
# batalhas ficam na janela de 8-15 turnos em TODOS os níveis (validado por
# sweep de 2.100 batalhas com movesets realistas por nível: médias 9-12).
# O leve crescimento por nível compensa o HP subir mais rápido que os dados.
DAMAGE_SCALE_BASE = 0.30        # escala no nível 1 (0.20→0.30: batalhas mais
                                # curtas e dano com mais peso — ~9-13 → ~6-9
                                # golpes p/ nocaute; valida em tools/battle_sweep.py)
DAMAGE_SCALE_PER_LEVEL = 0.0003  # quase flat: os movesets já ganham Power com o nível


def damage_scale(level):
    """Multiplicador global de dano no nível (alvo: batalhas de 8-15 turnos)."""
    return DAMAGE_SCALE_BASE + DAMAGE_SCALE_PER_LEVEL * max(1, int(level or 50))


TRAINING_POINTS_PER_LEVEL = 4  # pontos de treino ganhos por nível (economia antiga)
TRAINING_CAP = 63             # teto de treino por stat (≈ 252 EVs)

# ── Custom EVs (economia v3): Pontos de Potencial + Treinamento ─────────────
# Substitui o "+4/nível a custo 1" por orçamento = Potencial + Treinamento e
# CUSTO PROGRESSIVO por stat: o n-ésimo ponto num stat custa n
# (custo acumulado = n(n+1)/2). Cada +1 continua valendo +1 no stat (impacto
# linear em combate), mas concentrar fica caro. Anti-min-max: um stat em
# múltiplo de 5 trava até outro alcançar o mesmo patamar.
TRAINING_STATS = ('HP', 'ATK', 'DEF', 'SPA', 'SPD', 'SPE')


def parse_evolution_stage(raw):
    """'2/3' → (2, 3). Sem/malformado → (1, 1) (tratado como sem evolução)."""
    try:
        cur, tot = str(raw or '1/1').split('/')
        cur, tot = int(cur), int(tot)
        if cur < 1 or tot < 1 or cur > tot:
            return (1, 1)
        return (cur, tot)
    except (ValueError, AttributeError):
        return (1, 1)


def stat_cost(n):
    """Custo acumulado para ter +n pontos em UM stat: n(n+1)/2."""
    n = max(0, int(n or 0))
    return n * (n + 1) // 2


def next_point_cost(n):
    """Custo do PRÓXIMO ponto num stat que já tem +n: n+1."""
    return max(0, int(n or 0)) + 1


def training_spent(training):
    """Total de pontos do orçamento já gastos na distribuição atual."""
    return sum(stat_cost(v) for v in (training or {}).values())


def potential_points(level, evo_bonus=0, special=0):
    """Pontos de Potencial = ⌊nível/2⌋ + bônus de evolução + bônus especiais."""
    return max(1, int(level or 1)) // 2 + int(evo_bonus or 0) + int(special or 0)


def _training_rate(stage_current, stage_total):
    """Ganho de treino por nível como fração (num, den): 1, 1.5 (=3/2) ou 2."""
    st, tot = int(stage_current or 1), int(stage_total or 1)
    if tot >= 3:
        return (1, 1) if st == 1 else (3, 2) if st == 2 else (2, 1)
    if tot == 2:
        return (3, 2) if st == 1 else (2, 1)
    return (2, 1)   # sem evolução = considerado forma final


def training_points(level, stage_current, stage_total, bonus=0):
    """Pontos de Treinamento acumulados até o nível, pelo estágio ATUAL
    (aproximação: não guardamos histórico de nível por estágio)."""
    num, den = _training_rate(stage_current, stage_total)
    return num * (max(1, int(level or 1)) - 1) // den + int(bonus or 0)


def points_budget(level, stage_current, stage_total,
                  evo_bonus=0, special=0, train_bonus=0):
    """Orçamento total de pontos (Potencial + Treinamento)."""
    return (potential_points(level, evo_bonus, special)
            + training_points(level, stage_current, stage_total, train_bonus))


def stat_tier_locked(stat_key, training):
    """Anti min-max: stat em múltiplo de 5 (>0) trava até OUTRO stat alcançar
    esse mesmo patamar."""
    tr = training or {}
    v = int(tr.get(stat_key, 0) or 0)
    if v > 0 and v % 5 == 0:
        return not any(k != stat_key and int(tr.get(k, 0) or 0) >= v for k in tr)
    return False

# Faixas de nível → multiplicador de QUANTIDADE de dados (cortes herdados
# do sistema antigo: 10/20/40/60/80 — familiares aos jogadores)
LEVEL_TIERS = ((80, 3.0), (60, 2.5), (40, 2.0), (20, 1.5), (10, 1.25))

# Posturas defensivas: modo → (stat que defende físico, stat especial, taxa)
# 2 (Velocidade) defende AMBAS as categorias com SPE; 3 (Contra-ataque)
# defende com o próprio stat ofensivo da categoria recebida.
DEFENSE_MODES = {
    1: {'physical': 'DEF', 'special': 'SPD', 'tax': 1.0,  'label': '🛡️ Padrão'},
    2: {'physical': 'SPE', 'special': 'SPE', 'tax': 1.25, 'label': '💨 Velocidade'},
    3: {'physical': 'ATK', 'special': 'SPA', 'tax': 1.5,  'label': '⚔️ Contra-ataque'},
}

# Dano fixo (moves de dano sem Power no canônico) — por identifier local
FIXED_DAMAGE_FORMULAS = {
    'seismic toss': lambda level, target_hp: level,
    'night shade':  lambda level, target_hp: level,
    'dragon rage':  lambda level, target_hp: 15 + level // 4,
    'sonic boom':   lambda level, target_hp: 10 + level // 5,
    'super fang':   lambda level, target_hp: max(1, (target_hp or 2) // 2),
}

# Power REPRESENTATIVO para moves de dano de potência VARIÁVEL (peso, HP,
# felicidade, velocidade...). Sem isso o move caía em "mestre adjudica" (dano
# 0). Usamos um valor médio p/ o move ter dano automático coerente. Moves de
# RETALIAÇÃO (Counter/Mirror Coat/Metal Burst) dependem do dano recebido e
# continuam adjudicados pelo mestre.
VARIABLE_POWER = {
    'return': 90, 'frustration': 90,          # felicidade
    'low kick': 60, 'grass knot': 60,          # peso do alvo
    'heavy slam': 80, 'heat crash': 80,        # razão de peso
    'gyro ball': 70, 'electro ball': 70,       # razão de velocidade
    'flail': 80, 'reversal': 80,               # HP do usuário (baixo = forte)
    'crush grip': 80, 'wring out': 80,         # HP do alvo
    'magnitude': 70, 'present': 60,            # aleatório
    'natural gift': 80, 'punishment': 60,      # item / buffs do alvo
    'trump card': 70, 'spit up': 60,           # PP / stockpile
    'hidden power': 60,                        # tipo/força variável
}


# ── Stats por nível ────────────────────────────────────────────────────────
# ── Crítico (sistema de estágios v2) ────────────────────────────────────────
# Moves de alta taxa de crítico (canon): +1 estágio. Base = só nat 20; cada
# estágio abaixa o limiar em 1 (teto 17 = crítico em 17-20).
HIGH_CRIT_MOVES = {
    'slash', 'razor leaf', 'crabhammer', 'karate chop', 'aeroblast', 'air cutter',
    'attack order', 'blaze kick', 'cross chop', 'cross poison', 'drill run',
    'leaf blade', 'night slash', 'poison tail', 'psycho cut', 'razor wind',
    'shadow claw', 'sky attack', 'spacial rend', 'stone edge', 'razor shell',
    'snipe shot', 'esper wing', 'shell side arm',
}


def crit_threshold(crit_stage=0):
    """Limiar do d20 p/ crítico: base 20; cada estágio -1, teto 17."""
    return max(17, 20 - int(crit_stage or 0))


def crit_stage_for(move_name, ability=None, focus_energy=False):
    """Estágio de crítico do golpe: move de alta taxa (+1), Super Luck (+1),
    Focus Energy ativo (+2). `ability` pode ser str ou dict {'name':...}."""
    if isinstance(ability, dict):
        ability = ability.get('name', '')
    stage = 0
    if (move_name or '').lower() in HIGH_CRIT_MOVES:
        stage += 1
    if str(ability or '').strip().lower() == 'super luck':
        stage += 1
    if focus_energy:
        stage += 2
    return stage


# ── Stats por nível ────────────────────────────────────────────────────────
def stat_at_level(base, level, training=0):
    """Stat real no nível (fórmula dos jogos sem IV/EV; treino = +1/ponto).
    ATK/DEF/SPA/SPD/SPE. `base` já vem com shiny ×1.35 quando aplicável."""
    return (2 * int(base) * int(level)) // 100 + 5 + int(training or 0)


def hp_at_level(base_hp, level):
    """HP máximo no nível (fórmula dos jogos sem IV/EV)."""
    return (2 * int(base_hp) * int(level)) // 100 + int(level) + 10


def training_budget(level):
    """Pontos de treino totais disponíveis até este nível."""
    return TRAINING_POINTS_PER_LEVEL * (max(1, int(level)) - 1)


def training_cap(level):
    """Teto de treino por stat neste nível."""
    return min(TRAINING_CAP, max(1, int(level)))


# ── Acerto ────────────────────────────────────────────────────────────────
def miss_threshold(accuracy):
    """Limiar de erro no d20 para uma accuracy 1-100.
    None/0 = move que não erra (Swift). 100 → erra só no nat 1;
    90 → ≤2; 80 → ≤4; 55 (Sing) → ≤9... nat 20 SEMPRE acerta (crítico)."""
    if not accuracy:
        return 0
    if accuracy >= 100:
        return 1
    return max(1, math.ceil((100 - accuracy) / 5))


def roll_hits(d20, accuracy, attack_stage=0, evasion_stage=0):
    """True se o ataque acerta. Stages de acerto/evasão deslizam o d20."""
    thr = miss_threshold(accuracy)
    if thr == 0:
        return True          # move que não erra (Swift) — nem no nat 1
    if d20 >= 20:
        return True          # nat 20 sempre acerta
    if d20 <= 1:
        return False         # nat 1 sempre erra
    return (d20 + int(attack_stage or 0) - int(evasion_stage or 0)) > thr


# ── Dano ──────────────────────────────────────────────────────────────────
def level_tier_mult(level):
    for cut, mult in LEVEL_TIERS:
        if level >= cut:
            return mult
    return 1.0


def dice_for_power(power, level):
    """Power do move → expressão de dados. 40→2, 80→4, 90→5, 120→6 dados;
    quantidade × faixa de nível; d4 abaixo do Nv20, d6 do Nv20 em diante
    (a transição no 10 dava um salto de +40% de dano cedo demais)."""
    if not power:
        power = 40
    n = math.ceil(power / 20)
    count = math.ceil(n * level_tier_mult(int(level)))
    sides = 4 if int(level) < 20 else 6
    return f'{count}d{sides}'


def defense_stat_key(category, defense_mode):
    """Qual stat do DEFENSOR entra como denominador, conforme a postura."""
    mode = DEFENSE_MODES.get(int(defense_mode or 1), DEFENSE_MODES[1])
    return mode['special' if category == 'special' else 'physical']


def defense_tax(defense_mode):
    """Taxa de dano da postura (×1.0 / ×1.25 / ×1.5) se o golpe atingir."""
    return DEFENSE_MODES.get(int(defense_mode or 1), DEFENSE_MODES[1])['tax']


def damage(dice_total, atk_eff, def_eff, stab=False, effectiveness=1.0,
           tax=1.0, burned=False, stab_mult=None, level=None):
    """Dano final: rolagem × clamp(Atk/Def) × taxa da postura × STAB × tipo,
    tudo × damage_scale(nível) — a escala global controla a duração das
    batalhas (alvo 8-15 turnos) sem mexer nos multiplicadores relativos.
    Queimado corta dano físico pela metade (aplicar só se o move é físico).
    stab_mult sobrepõe o ×1.5 (Blaze/Overgrow com HP baixo dobram → 2.0)."""
    lo, hi = RATIO_CLAMP
    ratio = max(lo, min(hi, float(atk_eff) / max(1.0, float(def_eff))))
    dmg = dice_total * ratio * float(tax)
    if stab:
        dmg *= (stab_mult if stab_mult else STAB_MULT)
    dmg *= float(effectiveness)
    if burned:
        dmg *= 0.5
    if effectiveness <= 0:
        return 0
    return max(1, int(dmg * damage_scale(level)))


# ── Stat stages (multiplicativos, regra oficial) ──────────────────────────
def stage_mult(n):
    """Estágio ±6 → multiplicador oficial: +1=×1.5, +2=×2 ... −1=×0.67, −6=×0.25."""
    n = max(-6, min(6, int(n or 0)))
    return (2 + n) / 2 if n >= 0 else 2 / (2 - n)


# ── Iniciativa ────────────────────────────────────────────────────────────
def initiative_bonus(spe_eff):
    """Bônus de iniciativa: d20 + SPE_efetivo//10 (Speed decide na média,
    o dado ainda importa)."""
    return int(spe_eff) // 10


# ── Dano fixo ─────────────────────────────────────────────────────────────
def fixed_damage_for(move_name_lower, level, target_current_hp=None):
    """Dano de moves de valor fixo, ou None se o move não é desse grupo.
    Escala junto com o dano geral (senão Seismic Toss viraria a melhor
    opção do jogo depois do rebalance) — exceto Super Fang, que é
    percentual do HP atual e se auto-limita."""
    fn = FIXED_DAMAGE_FORMULAS.get(move_name_lower)
    if not fn:
        return None
    raw = fn(int(level), target_current_hp)
    if move_name_lower == 'super fang':
        return max(1, int(raw))
    return max(1, int(raw * damage_scale(level)))


# ═══════════════════════════════════════════════════════════════════════════
# SISTEMA v3 — "d100/ACC": Precisão (d100) → Dano (Status+POW) → Resistência
# (d20 do defensor). Documento de design: docs/sistema-combate-d100.md.
# As funções v2 acima permanecem até o cutover completo do motor.
# ═══════════════════════════════════════════════════════════════════════════

# Alavancas de calibração (alvo: batalhas de 5-10 turnos — battle_sweep_v3)
V3_STATUS_DIVISOR = 8     # Componente de Status = stat // divisor
V3_TN_SHIFT = 0           # desloca a coluna de TN inteira
V3_DEF_BONUS_CAP = 12     # teto do bônus de Defesa na Resistência: ⌊def/10⌋
                          # chega a +20 no Nv100 e dominaria o d20 (anulação
                          # eterna, batalhas de 13+ rodadas)
V3_STAB_DIE_LEVEL = 25    # STAB: +1 dado a partir do 1º marco; antes disso
                          # +2 fixo no bruto (dobrar dados no early game
                          # derrubava o L15 para 4 rodadas)
V3_STAB_FLAT = 2
V3_ACC_CAP, V3_ACC_FLOOR = 100, 5
V3_CRIT_BASE, V3_CRIT_PER_STAGE, V3_CRIT_CAP = 5, 10, 50
V3_MOMENTUM_MAX = 3
V3_CERTEIRO_DAMAGE_MULT = 0.90   # ACC ∞: dano final ×0,90 (compensa a
                                 # confiabilidade — não há outra penalidade)

# TABELA MESTRA: (pow_máx, nº dados, lados, TN, cooldown em rodadas)
V3_MASTER_TABLE = (
    (35,        1, 6,  10, 0),
    (50,        1, 8,  12, 0),
    (65,        1, 10, 14, 0),
    (80,        2, 6,  16, 0),
    (95,        2, 8,  18, 1),
    (110,       3, 6,  20, 2),
    (125,       3, 8,  22, 3),
    (10 ** 9,   3, 10, 24, 3),
)


def v3_tier(power):
    """Índice do degrau da Tabela Mestra para um POW."""
    p = max(1, int(power or 40))
    for i, row in enumerate(V3_MASTER_TABLE):
        if p <= row[0]:
            return i
    return len(V3_MASTER_TABLE) - 1


def v3_dice_base(power):
    """(n, lados) do degrau do POW."""
    row = V3_MASTER_TABLE[v3_tier(power)]
    return row[1], row[2]


def v3_tn(power, attacker_level=1):
    """TN Efetiva = TN da tabela + ⌊nível do atacante/10⌋ + shift de calibração.
    O termo do atacante cancela o ⌊nível/10⌋ do defensor em níveis iguais —
    sem ele, em nível alto o defensor anularia tudo."""
    return (V3_MASTER_TABLE[v3_tier(power)][3] + V3_TN_SHIFT
            + max(1, int(attacker_level or 1)) // 10)


def v3_cooldown(power):
    """Rodadas de espera após usar o golpe (0 = sem cooldown)."""
    return V3_MASTER_TABLE[v3_tier(power)][4]


# ── Cooldown de SUSTAIN (dreno / cura instantânea) ─────────────────────────
# Golpe que recupera HP na hora não pode ciclar todo turno (anulava o
# desgaste natural da batalha). Detecção pela MECÂNICA, nunca por lista de
# nomes: dano com drain canônico > 0, ou status heal_self. Recuperação
# moderada → 1 rodada de recarga; elevada → 2. Combina com a recarga por
# POW pelo MAIOR valor. Cura gradual (Leech Seed/Aqua Ring/Leftovers…) fica
# de fora — já é balanceada por vir aos poucos.
V3_SUSTAIN_POW_HEAVY = 90    # dreno com POW ≥ isto = recuperação elevada


def v3_drain_cooldown(power, drain):
    """Recarga de sustain de golpe de DANO com dreno (drain canônico > 0):
    Absorb/Mega Drain/Giga Drain/Drain Punch… → 1; pesados (POW ≥ 90,
    ex. Dream Eater, Bitter Blade) → 2."""
    if int(drain or 0) <= 0:
        return 0
    return 2 if int(power or 0) >= V3_SUSTAIN_POW_HEAVY else 1


def v3_heal_cooldown(amount):
    """Recarga de move de STATUS de cura instantânea (heal_self).
    'full'/'half' (≥50% do HP máx: Recover, Roost, Rest…) = elevada → 2;
    frações menores (quarter…) = moderada → 1."""
    if amount in ('full', 'half'):
        return 2
    if amount:
        return 1
    return 0


def v3_move_cooldown(power, drain=0):
    """Recarga total de um golpe de dano: o MAIOR entre a recarga por POW
    (Tabela Mestra) e a recarga de sustain (dreno)."""
    return max(v3_cooldown(power), v3_drain_cooldown(power, drain))


def v3_milestone_dice(level):
    """Dados extras acumulados pelos marcos 25/50/75/100."""
    return max(0, min(4, int(level or 1) // 25))


def v3_status_component(stat, atk_stages=0):
    """Componente de Status: ⌊stat/divisor⌋ ± 2 por estágio de ATK/SpA (mín 1).
    Certeiro (ACC ∞) NÃO reduz o componente — a compensação é o ×0,90 no
    dano final (v3_certeiro_mult)."""
    comp = int(stat or 10) // V3_STATUS_DIVISOR + 2 * int(atk_stages or 0)
    return max(1, comp)


def v3_level_bonus(level):
    return max(1, int(level or 1)) // 10


def v3_effectiveness_dice_delta(effectiveness):
    """×2→+1 dado, ×4→+2, ×½→−1, ×¼→−2, neutro→0. Imune é tratado fora."""
    e = float(effectiveness if effectiveness is not None else 1.0)
    if e >= 4:   return 2
    if e >= 2:   return 1
    if e <= 0.25: return -2
    if e <= 0.5: return -1
    return 0


def v3_build_dice(power, level, stab=False,
                  effectiveness=1.0, field_delta=0):
    """Constrói a rolagem final: (n, lados, halve).
    Ordem: degrau → marcos → STAB (+1) → efetividade → clima/terreno.
    Certeiro (ACC ∞) rola os dados NORMAIS — a compensação é só o ×0,90 no
    dano final. Se n cair abaixo de 1: rola 1 dado e divide por 2."""
    tier = v3_tier(power)
    n, sides = V3_MASTER_TABLE[tier][1], V3_MASTER_TABLE[tier][2]
    n += v3_milestone_dice(level)
    if stab and int(level or 1) >= V3_STAB_DIE_LEVEL:
        n += 1
    n += v3_effectiveness_dice_delta(effectiveness)
    n += int(field_delta or 0)
    halve = n < 1
    return max(1, n), sides, halve


def v3_stab_flat(stab, level):
    """STAB antes do 1º marco (Nv < 25): +2 fixo no bruto em vez do dado."""
    return V3_STAB_FLAT if stab and int(level or 1) < V3_STAB_DIE_LEVEL else 0


def v3_acc_effective(acc_base, acc_stages=0, eva_stages=0, weather_mod=0):
    """ACC Efetivo com teto 100 / piso 5. acc_base None = certeiro (retorna
    None: sempre conecta, ignora evasão)."""
    if acc_base is None:
        return None
    acc = (int(acc_base) + 10 * int(acc_stages or 0)
           - 10 * int(eva_stages or 0) + int(weather_mod or 0))
    return max(V3_ACC_FLOOR, min(V3_ACC_CAP, acc))


def v3_connects(d100, acc_effective):
    """True se o golpe conecta (certeiro conecta sempre)."""
    if acc_effective is None:
        return True
    return int(d100) <= int(acc_effective)


def v3_crit_chance(crit_stages=0):
    return min(V3_CRIT_CAP, V3_CRIT_BASE + V3_CRIT_PER_STAGE * int(crit_stages or 0))


def v3_resistance_total(d20, defense_stat, level, def_stages=0,
                        crit=False, extra=0, crit_zeroes_defense=False):
    """Total da Resistência do defensor. Crítico FURA a defesa: o bônus de
    Defesa (⌊def/10⌋ + estágios positivos) conta pela metade (Sniper: zero)."""
    bonus = min(V3_DEF_BONUS_CAP, int(defense_stat or 10) // 10) + int(def_stages or 0)
    if crit:
        bonus = 0 if crit_zeroes_defense else (bonus // 2 if bonus > 0 else bonus)
    return int(d20) + bonus + v3_level_bonus(level) + int(extra or 0)


def v3_resist_outcome(result, tn, defender_faster=False):
    """'full' | 'half' | 'negate'. Empate técnico: a exatamente 1 ponto da
    faixa superior (TN−1 ou TN+9), defensor mais rápido sobe de faixa."""
    result, tn = int(result), int(tn)
    if result >= tn + 10:
        return 'negate'
    if result >= tn:
        if defender_faster and result == tn + 9:
            return 'negate'
        return 'half'
    if defender_faster and result == tn - 1:
        return 'half'
    return 'full'


def v3_apply_outcome(gross, outcome):
    """Aplica a faixa da Resistência ao Dano Bruto (mín. 1 se não anulado)."""
    if outcome == 'negate':
        return 0
    if outcome == 'half':
        return max(1, int(gross) // 2)
    return max(1, int(gross))


def v3_gross_damage(component, level, dice_total, momentum=0, halve_dice=False,
                    flat=0):
    """Dano Bruto = Componente + ⌊nível/10⌋ + dados + Momentum + flats
    (ex.: STAB pré-Nv25)."""
    dice = int(dice_total) // 2 if halve_dice else int(dice_total)
    return max(1, int(component) + v3_level_bonus(level) + max(1, dice)
               + max(0, min(V3_MOMENTUM_MAX, int(momentum or 0)))
               + int(flat or 0))


# ── v3 F5: Clima, Terreno, Prioridade e Casos Especiais ────────────────────
# Doc: docs/sistema-combate-d100.md seções 7, 12, 13 e 17.

V3_FIELD_ROUNDS = 5          # duração padrão de clima e terreno
V3_WEATHER_CHIP_DIV = 16     # areia/granizo: ⌊HPmáx/16⌋ por rodada
V3_PROTECT_FLOOR = 5         # a corrente 100→50→25… nunca cai abaixo de 5%

# tipos poupados pelo chip de cada clima
_V3_SAND_IMMUNE = ('rock', 'ground', 'steel')
_V3_HAIL_IMMUNE = ('ice',)


def v3_weather_dice_delta(weather, move_type):
    """Clima → ±1 dado por tipo (Sol: Fogo+1/Água−1; Chuva: Água+1/Fogo−1)."""
    w, t = (weather or '').lower(), (move_type or '').lower()
    if w == 'sun':
        return 1 if t == 'fire' else (-1 if t == 'water' else 0)
    if w == 'rain':
        return 1 if t == 'water' else (-1 if t == 'fire' else 0)
    return 0


# golpes que golpeiam o CHÃO — Grassy Terrain amortece (−1 dado)
_V3_GROUND_SLAMS = ('earthquake', 'bulldoze', 'magnitude')


def v3_terrain_dice_delta(terrain, move_type, move_name=''):
    """Terreno → ±1 dado (Grassy/Electric/Psychic +1 no tipo; Misty: Dragão −1;
    Grassy amortece Earthquake/Bulldoze/Magnitude)."""
    tr, t = (terrain or '').lower(), (move_type or '').lower()
    ml = (move_name or '').lower()
    if tr == 'grassy':
        if ml in _V3_GROUND_SLAMS:
            return -1
        return 1 if t == 'grass' else 0
    if tr == 'electric':
        return 1 if t == 'electric' else 0
    if tr == 'psychic':
        return 1 if t == 'psychic' else 0
    if tr == 'misty':
        return -1 if t == 'dragon' else 0
    return 0


def v3_weather_acc(weather, move_name, accuracy):
    """ACC base ajustado pelo clima: Thunder/Hurricane (Sol 50 / Chuva 100),
    Blizzard (Granizo 100), Névoa −10 global. Retorna o ACC base final."""
    w, ml = (weather or '').lower(), (move_name or '').lower()
    if ml in ('thunder', 'hurricane'):
        if w == 'sun':
            accuracy = 50
        elif w == 'rain':
            accuracy = 100
    elif ml == 'blizzard' and w in ('hail', 'snow'):
        accuracy = 100
    if w == 'fog' and accuracy is not None:
        accuracy = max(V3_ACC_FLOOR, int(accuracy) - 10)
    return accuracy


def v3_weather_resist_bonus(weather, defender_types, category):
    """Areia: Pedra +2 na Resistência ESPECIAL; Granizo/Neve: Gelo +2 na
    FÍSICA."""
    w = (weather or '').lower()
    types = [str(t).lower() for t in (defender_types or [])]
    if w == 'sandstorm' and 'rock' in types and category == 'special':
        return 2
    if w in ('hail', 'snow') and 'ice' in types and category == 'physical':
        return 2
    return 0


def v3_weather_chip(weather, max_hp, defender_types):
    """Dano de clima por rodada (0 se o tipo é poupado). Habilidades imunes
    (Magic Guard, Overcoat, Sand Veil...) são checadas pelo caller."""
    w = (weather or '').lower()
    types = [str(t).lower() for t in (defender_types or [])]
    if w == 'sandstorm' and not any(t in _V3_SAND_IMMUNE for t in types):
        return max(1, int(max_hp or 1) // V3_WEATHER_CHIP_DIV)
    if w in ('hail', 'snow') and not any(t in _V3_HAIL_IMMUNE for t in types):
        return max(1, int(max_hp or 1) // V3_WEATHER_CHIP_DIV)
    return 0


def v3_terrain_heal(terrain, max_hp):
    """Grassy Terrain cura ⌊HPmáx/16⌋ por rodada."""
    if (terrain or '').lower() == 'grassy':
        return max(1, int(max_hp or 1) // V3_WEATHER_CHIP_DIV)
    return 0


# Multi-hit: nome → (mín, máx) de hits. 1 ACC, 1 Componente, 1 Resistência;
# só os DADOS rolam por hit (doc §17). 2-5 hits = 1d4+1.
V3_MULTI_HIT = {
    'double kick': (2, 2), 'double hit': (2, 2), 'dual chop': (2, 2),
    'bonemerang': (2, 2), 'double iron bash': (2, 2), 'dragon darts': (2, 2),
    'twineedle': (2, 2), 'gear grind': (2, 2), 'dual wingbeat': (2, 2),
    'triple kick': (3, 3), 'triple axel': (3, 3), 'surging strikes': (3, 3),
    'double slap': (2, 5), 'fury attack': (2, 5), 'fury swipes': (2, 5),
    'pin missile': (2, 5), 'rock blast': (2, 5), 'bullet seed': (2, 5),
    'icicle spear': (2, 5), 'spike cannon': (2, 5), 'comet punch': (2, 5),
    'barrage': (2, 5), 'arm thrust': (2, 5), 'tail slap': (2, 5),
    'water shuriken': (2, 5), 'bone rush': (2, 5), 'scale shot': (2, 5),
}


def v3_multi_hits(move_name, rng=None):
    """Nº de hits do golpe (None se não é multi-hit). 2-5 → 1d4+1."""
    span = V3_MULTI_HIT.get((move_name or '').lower())
    if not span:
        return None
    lo, hi = span
    if lo == hi:
        return lo
    roll = (rng or _random).randint(1, 4)
    return 1 + roll


# Carga: 1 rodada carregando antes de disparar (doc §17).
V3_CHARGE_MOVES = ('solar beam', 'solar blade', 'sky attack', 'skull bash',
                   'razor wind', 'freeze shock', 'ice burn', 'meteor beam')


def v3_needs_charge(move_name, weather=None):
    """True se o golpe precisa de 1 rodada de preparo: carga (Solar Beam —
    dispara direto no Sol) ou semi-invulnerabilidade (Fly/Dig/Dive...)."""
    ml = (move_name or '').lower()
    if ml in V3_SEMI_INVULN:
        return True
    if ml not in V3_CHARGE_MOVES:
        return False
    if ml in ('solar beam', 'solar blade') and (weather or '').lower() == 'sun':
        return False
    return True


def v3_recoil(final_damage, canon_drain):
    """Recoil (drain canônico < 0): usuário sofre ⌊dano final ÷ 3⌋."""
    if int(canon_drain or 0) < 0 and int(final_damage or 0) > 0:
        return max(1, int(final_damage) // 3)
    return 0


def v3_drain_heal(final_damage, canon_drain):
    """Dreno (drain canônico > 0): usuário cura ⌊dano final ÷ 2⌋."""
    if int(canon_drain or 0) > 0 and int(final_damage or 0) > 0:
        return max(1, int(final_damage) // 2)
    return 0


def v3_protect_chance(chain):
    """Protect/Detect: usos consecutivos caem pela metade (100→50→25…)."""
    return max(V3_PROTECT_FLOOR, 100 >> max(0, int(chain or 0)))


def v3_ohko_resist_tn():
    """OHKO (Fissure/Guillotine): Resistência vs TN 22 — qualquer sucesso
    anula o golpe inteiro."""
    return 22


# ── ACC ∞ (certeiros) e estados de invulnerabilidade (spec de precisão) ────
# Certeiro (ACC "—"): ignora SÓ os testes de Precisão×Evasão. Continua
# respeitando imunidade de tipo, habilidades, Protect e invulnerabilidade.
# Compensação pela confiabilidade: dano final ×0,90 (nenhuma outra penalidade).

def v3_certeiro_mult(damage):
    """Aplica o redutor de balanceamento do ACC ∞ ao dano final (mín. 1)."""
    d = int(damage or 0)
    if d <= 0:
        return d
    return max(1, int(d * V3_CERTEIRO_DAMAGE_MULT))


# Golpes de 2 turnos que deixam o usuário INVULNERÁVEL na rodada de preparo.
# move → rótulo do estado (para logs).
V3_SEMI_INVULN = {
    'fly': 'no ar', 'bounce': 'no ar', 'sky drop': 'no ar',
    'dig': 'no subsolo', 'dive': 'debaixo d’água',
    'phantom force': 'nas sombras', 'shadow force': 'nas sombras',
}

# Exceções canônicas: golpes que ATINGEM cada estado invulnerável.
V3_INVULN_PIERCE = {
    'no ar': ('gust', 'twister', 'thunder', 'hurricane', 'sky uppercut',
              'smack down', 'thousand arrows'),
    'no subsolo': ('earthquake', 'magnitude', 'fissure'),
    'debaixo d’água': ('surf', 'whirlpool'),
    'nas sombras': (),
}


def v3_semi_invuln_state(move_name):
    """Rótulo do estado invulnerável do golpe, ou None."""
    return V3_SEMI_INVULN.get((move_name or '').lower())


def v3_pierces_invuln(state, incoming_move):
    """True se o golpe recebido atinge o alvo mesmo invulnerável (Earthquake
    acerta quem usou Dig, Thunder acerta quem usou Fly...)."""
    return (incoming_move or '').lower() in V3_INVULN_PIERCE.get(state or '', ())
