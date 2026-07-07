"""Estima a DURAÇÃO das batalhas (golpes para nocaute) em vários cenários e
escalas de dano — usado para calibrar battle_math.DAMAGE_SCALE_BASE.

    python3 tools/battle_sweep.py
"""
import os
import re
import sys
import random
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import battle_math as bm

random.seed(1)


def _roll(dstr):
    m = re.match(r'(\d+)d(\d+)', str(dstr))
    if not m:
        return int(dstr) if str(dstr).isdigit() else 0
    n, s = int(m.group(1)), int(m.group(2))
    return sum(random.randint(1, s) for _ in range(n))


def hits_to_ko(scale, atk_b, def_b, hp_b, power, level=40, stab=True, tax=1.0, n=400):
    orig = bm.DAMAGE_SCALE_BASE
    bm.DAMAGE_SCALE_BASE = scale
    atk = bm.stat_at_level(atk_b, level)
    dfe = bm.stat_at_level(def_b, level)
    hp = bm.hp_at_level(hp_b, level)
    dice = bm.dice_for_power(power, level)
    totals = []
    for _ in range(n):
        remaining, h = hp, 0
        while remaining > 0 and h < 80:
            dmg = bm.damage(_roll(dice), atk, dfe, stab=stab,
                            effectiveness=1.0, tax=tax, level=level)
            remaining -= max(1, dmg)
            h += 1
        totals.append(h)
    bm.DAMAGE_SCALE_BASE = orig
    return statistics.mean(totals)


SCEN = [
    ('padrão Nv40 (DEF80/HP80, Power90 STAB)', dict(atk_b=100, def_b=80, hp_b=80, power=90, level=40)),
    ('parede Nv40 (DEF120/HP100)', dict(atk_b=90, def_b=120, hp_b=100, power=90, level=40)),
    ('veloz na postura Velocidade (SPE110, tax1.25)', dict(atk_b=90, def_b=110, hp_b=60, power=90, level=40, tax=1.25)),
    ('early game Nv15 (DEF60/HP60, Power60)', dict(atk_b=80, def_b=60, hp_b=60, power=60, level=15)),
    ('endgame Nv80 (DEF90/HP90, Power100)', dict(atk_b=110, def_b=90, hp_b=90, power=100, level=80)),
]


def main():
    scales = (0.20, 0.25, 0.30, 0.32)
    print(f"{'cenário':48} " + ' '.join(f'{s:>6}' for s in scales))
    for name, kw in SCEN:
        row = [f'{hits_to_ko(s, **kw):.1f}' for s in scales]
        print(f'{name:48} ' + ' '.join(f'{v:>6}' for v in row))
    print("\n(golpes de UM lado p/ nocautear; a batalha real ≈ max dos dois lados)")
    print(f"escala atual em battle_math: {bm.DAMAGE_SCALE_BASE}")


if __name__ == '__main__':
    main()
