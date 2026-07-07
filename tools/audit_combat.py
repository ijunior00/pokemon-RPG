"""Auditoria do sistema de combate v2 (base stats reais dos Pokémon).

Verifica, sem depender do Flask/DB:
  1. Categoria física/especial/status: moves.json × canônico (damage_class).
  2. Moves de DANO (físico/especial) sem Power e sem fórmula de dano fixo →
     "dano variável, mestre adjudica" (candidatos a corrigir).
  3. Moves de STATUS com Power no canônico (inconsistência de categoria).
  4. Resíduo do sistema D&D nos módulos de COMBATE (saving throw / Constitution
     / Wisdom / Dexterity / DC / ability check) — o `d20` do acerto v2 é legítimo.
  5. Cobertura de Passive Abilities: quais habilidades das espécies estão
     implementadas em abilities.py.

    python3 tools/audit_combat.py
"""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..')
DATA = os.path.join(ROOT, 'server', 'data')


def load(name):
    return json.load(open(os.path.join(DATA, name), encoding='utf-8'))


_CANON_MANUAL = {'vise grip': 'vice-grip'}


def canon_ident(name):
    n = (name or '').lower().replace("'", '').replace('’', '')
    n = n.replace('.', '').replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return _CANON_MANUAL.get((name or '').lower(), n)


import sys
sys.path.insert(0, ROOT)
import battle_math as _bm

# fórmulas de dano fixo conhecidas (espelha battle_math.FIXED_DAMAGE_FORMULAS)
FIXED = set(_bm.FIXED_DAMAGE_FORMULAS)
# potência variável com Power representativo (dão dano; não são "adjudica")
VARIABLE = set(_bm.VARIABLE_POWER)
# moves roteados PELO MOTOR DE EFEITOS (categoria 'status' de propósito):
# dano fixo / OHKO / retaliação. A divergência de categoria é intencional.
EFFECT_ROUTED = {
    'night shade', 'seismic toss', 'sonic boom', 'bide', 'metal burst', 'beat up',
    'fling', 'endeavor', 'final gambit', 'fissure', 'guillotine', 'horn drill',
    "nature's madness", 'psywave', 'sheer cold', 'super fang', 'counter',
    'mirror coat', 'pain split', 'dragon rage',
}
# retaliação: dependem do dano recebido → mestre adjudica (correto)
RETALIATION = {'counter', 'mirror coat', 'metal burst'}


def main():
    moves = load('moves.json')
    canon = load('canonical_moves.json')

    cat_mismatch, dmg_no_power, status_with_power = [], [], []
    for name, mv in moves.items():
        local_cat = (mv.get('category') or '').lower()
        c = canon.get(canon_ident(name))
        if not c:
            continue
        canon_cat = (c.get('category') or '').lower()
        power = c.get('power')
        nm = name.lower()
        if local_cat and canon_cat and local_cat != canon_cat \
                and nm not in EFFECT_ROUTED:
            cat_mismatch.append((name, local_cat, canon_cat))
        if local_cat in ('physical', 'special') and not power \
                and nm not in FIXED and nm not in VARIABLE \
                and nm not in EFFECT_ROUTED and nm not in RETALIATION:
            dmg_no_power.append((name, local_cat))
        if local_cat == 'status' and power:
            status_with_power.append((name, power))

    # 4. resíduo D&D nos módulos de combate
    combat_files = ['app.py', 'status_effects.py', 'abilities.py', 'pvp_battle.py',
                    'group_battle.py', 'battle_math.py', 'pokemon_scaling.py']
    # padrões proibidos (o d20 do acerto v2 é permitido; miramos saves/atributos D&D)
    banned = re.compile(r'saving[_ ]?throw|\bsave_dc\b|\bability_check\b|'
                        r'constitution|wisdom|dexterity|_POWER_TO_STATS|_SAVE_TO_STATS',
                        re.IGNORECASE)
    residue = []
    for fn in combat_files:
        path = os.path.join(ROOT, fn)
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path, encoding='utf-8'), 1):
            # ignora a linha que REMOVE a chave legada (limpeza, não uso)
            if 'pop(' in line or 'legacy' in line or "('hitDice'" in line:
                continue
            if banned.search(line) and 'audit' not in line.lower():
                residue.append((fn, i, line.strip()[:90]))

    # 5. cobertura de abilities
    pokes = load('pokemon.json')
    species_abilities = set()
    for p in pokes:
        for a in (p.get('abilities') or []):
            if isinstance(a, str):
                species_abilities.add(a.strip())
            elif isinstance(a, dict) and a.get('name'):
                species_abilities.add(a['name'].strip())
        for key in ('ability', 'hiddenAbility'):
            a = p.get(key)
            if isinstance(a, dict) and a.get('name'):
                species_abilities.add(a['name'].strip())
    abil_src = open(os.path.join(ROOT, 'abilities.py'), encoding='utf-8').read().lower()
    implemented, missing = [], []
    for a in sorted(species_abilities):
        # heurística: nome normalizado aparece no módulo de abilities
        key = a.lower()
        if key in abil_src or key.replace(' ', '_') in abil_src or key.replace(' ', '') in abil_src:
            implemented.append(a)
        else:
            missing.append(a)

    # ── relatório ──
    def sec(t):
        print(f'\n{"="*60}\n{t}\n{"="*60}')

    sec('1-2. CATEGORIA (moves.json × canônico)')
    print(f'  Moves em moves.json: {len(moves)} | casados com canônico: '
          f'{sum(1 for n in moves if canon.get(canon_ident(n)))}')
    print(f'  ❗ Divergência de categoria: {len(cat_mismatch)}')
    for n, l, cc in cat_mismatch[:40]:
        print(f'      {n}: local={l} vs canônico={cc}')

    sec('2. MOVES DE DANO SEM POWER (mestre adjudica)')
    print(f'  ❗ {len(dmg_no_power)} moves físicos/especiais sem Power e sem dano fixo:')
    for n, c in dmg_no_power[:60]:
        print(f'      {n} ({c})')

    sec('3. MOVES DE STATUS COM POWER (inconsistência)')
    print(f'  ❗ {len(status_with_power)}')
    for n, p in status_with_power[:40]:
        print(f'      {n}: power={p}')

    sec('4. RESÍDUO D&D NO COMBATE')
    if residue:
        print(f'  ❗ {len(residue)} ocorrências:')
        for fn, i, ln in residue:
            print(f'      {fn}:{i}  {ln}')
    else:
        print('  ✅ Nenhum resíduo (saving throw / Constitution / Wisdom / '
              'Dexterity / DC) no caminho de combate.')

    sec('5. COBERTURA DE ABILITIES')
    print(f'  Espécies citam {len(species_abilities)} habilidades distintas.')
    print(f'  ✅ implementadas (heurística): {len(implemented)}')
    print(f'  ⚠️  sem menção em abilities.py: {len(missing)}')
    print('     ' + ', '.join(missing[:60]))

    print('\n' + '='*60)
    print(f'RESUMO: cat_mismatch={len(cat_mismatch)} dmg_no_power={len(dmg_no_power)} '
          f'status_with_power={len(status_with_power)} residuo_dnd={len(residue)} '
          f'abilities_sem_menção={len(missing)}')


if __name__ == '__main__':
    main()
