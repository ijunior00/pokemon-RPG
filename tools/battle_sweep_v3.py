"""Calibração do sistema v3 (d100/ACC → Dano → Resistência d20).

Simula batalhas COMPLETAS (os dois lados atacam por rodada, com precisão,
crítico e resistência) e mede a duração. ALVO OFICIAL: mediana de 5-10 rodadas
em todos os cenários. Alavancas: V3_STATUS_DIVISOR e V3_TN_SHIFT.

    python3 tools/battle_sweep_v3.py
"""
import os
import sys
import random
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import battle_math as bm

random.seed(7)
N_BATTLES = 500
MAX_ROUNDS = 40


def make_side(level, atk_b, def_b, hp_b, spe_b, power, acc=100, stab=True):
    return {
        'level': level,
        'atk': bm.stat_at_level(atk_b, level),
        'dfn': bm.stat_at_level(def_b, level),
        'spe': bm.stat_at_level(spe_b, level),
        'hp': bm.hp_at_level(hp_b, level),
        'power': power, 'acc': acc, 'stab': stab,
    }


def attack(att, dfd):
    """Uma ação de ataque v3 completa. Retorna o dano aplicado."""
    acc_eff = bm.v3_acc_effective(att['acc'])
    if not bm.v3_connects(random.randint(1, 100), acc_eff):
        return 0
    crit = random.randint(1, 100) <= bm.v3_crit_chance(0)
    n, sides, halve = bm.v3_build_dice(att['power'], att['level'], stab=att['stab'])
    dice_total = sum(random.randint(1, sides) for _ in range(n))
    comp = bm.v3_status_component(att['atk'])
    flat = bm.v3_stab_flat(att['stab'], att['level'])
    gross = bm.v3_gross_damage(comp, att['level'], dice_total,
                               halve_dice=halve, flat=flat)
    resist = bm.v3_resistance_total(random.randint(1, 20), dfd['dfn'],
                                    dfd['level'], crit=crit)
    outcome = bm.v3_resist_outcome(resist, bm.v3_tn(att['power'], att['level']),
                                   defender_faster=dfd['spe'] > att['spe'])
    return bm.v3_apply_outcome(gross, outcome)


def battle(a, b):
    hp_a, hp_b = a['hp'], b['hp']
    for rnd in range(1, MAX_ROUNDS + 1):
        first, second = (a, b) if a['spe'] >= b['spe'] else (b, a)
        # primeiro ataca
        if first is a:
            hp_b -= attack(a, b)
            if hp_b <= 0:
                return rnd
            hp_a -= attack(b, a)
            if hp_a <= 0:
                return rnd
        else:
            hp_a -= attack(b, a)
            if hp_a <= 0:
                return rnd
            hp_b -= attack(a, b)
            if hp_b <= 0:
                return rnd
    return MAX_ROUNDS


# Cenários: espelhados (A vs B com os mesmos arquétipos) — cobre early/mid/end
# e os extremos sweeper × tanque.
SCENARIOS = [
    ('L15 iniciais (POW 60, ACC 100)',
     dict(level=15, atk_b=80, def_b=60, hp_b=60, spe_b=70, power=60),
     dict(level=15, atk_b=80, def_b=60, hp_b=60, spe_b=65, power=60)),
    ('L40 equilibrados (POW 90)',
     dict(level=40, atk_b=100, def_b=80, hp_b=80, spe_b=90, power=90),
     dict(level=40, atk_b=100, def_b=80, hp_b=80, spe_b=85, power=90)),
    ('L40 sweeper vs tanque (POW 90 vs 75)',
     dict(level=40, atk_b=125, def_b=60, hp_b=60, spe_b=110, power=90),
     dict(level=40, atk_b=75, def_b=120, hp_b=110, spe_b=45, power=75)),
    ('L60 fortes (POW 100)',
     dict(level=60, atk_b=105, def_b=85, hp_b=85, spe_b=95, power=100),
     dict(level=60, atk_b=105, def_b=85, hp_b=85, spe_b=90, power=100)),
    ('L80 endgame (POW 110, ACC 85)',
     dict(level=80, atk_b=110, def_b=90, hp_b=90, spe_b=100, power=110, acc=85),
     dict(level=80, atk_b=110, def_b=90, hp_b=90, spe_b=95, power=110, acc=85)),
    ('L100 lendários (POW 120, ACC 90)',
     dict(level=100, atk_b=130, def_b=100, hp_b=100, spe_b=110, power=120, acc=90),
     dict(level=100, atk_b=130, def_b=100, hp_b=100, spe_b=105, power=120, acc=90)),
]

TARGET = (5, 10)


def run():
    print(f'Sistema v3 — divisor={bm.V3_STATUS_DIVISOR} TN_shift={bm.V3_TN_SHIFT} '
          f'(alvo: mediana {TARGET[0]}-{TARGET[1]} rodadas)\n')
    all_ok = True
    for name, ka, kb in SCENARIOS:
        rounds = [battle(make_side(**ka), make_side(**kb)) for _ in range(N_BATTLES)]
        med = statistics.median(rounds)
        mean = statistics.mean(rounds)
        ok = TARGET[0] <= med <= TARGET[1]
        all_ok = all_ok and ok
        print(f'  {"✅" if ok else "❌"} {name:42} mediana {med:>4.1f} | média {mean:4.1f} '
              f'| p10-p90 {sorted(rounds)[N_BATTLES//10]}-{sorted(rounds)[N_BATTLES*9//10]}')
    print(f'\n{"✅ TODOS os cenários na janela 5-10." if all_ok else "❌ Fora da janela — ajustar alavancas."}')
    return all_ok


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
