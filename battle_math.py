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

# ── Constantes de balanceamento (ajustáveis em playtest) ──────────────────
RATIO_CLAMP = (0.5, 2.0)      # limites da razão Atk_ef / Def_ef
STAB_MULT = 1.5               # bônus de tipo igual (como nos jogos)
# Escala GLOBAL de dano: comprime todo dano por dados sem tocar em
# STAB/efetividade/posturas (que continuam relativos entre si).
# Antigo equivalente: 1.0 (janela de 2-4 turnos até o KO). Com ×0.20 as
# batalhas ficam na janela de 8-15 turnos em TODOS os níveis (validado por
# sweep de 2.100 batalhas com movesets realistas por nível: médias 9-12).
# O leve crescimento por nível compensa o HP subir mais rápido que os dados.
DAMAGE_SCALE_BASE = 0.20        # escala no nível 1
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
