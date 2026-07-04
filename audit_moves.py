"""
Auditoria de dados de moves e movesets — ferramenta de busca reutilizável.

Detecta:
  1. Moves de categoria 'status' que ainda têm baseDamage (dariam dano);
  2. Moves cujo papel é 100% cura/buff/proteção mas têm baseDamage
     (lista canônica — ignora golpes de dreno/dano+buff legítimos);
  3. Entradas de startingMoves/levelMoves que não existem no banco de moves
     (nomes quebrados como 'Air','Cutter');
  4. Divergências vs os dados CANÔNICOS do PokeAPI (canonical_moves.json,
     gerado por tools/build_canonical_moves.py — mesma base do pokemondb):
     categoria errada (status↔physical↔special) e moves de dano sem dados.

Uso:
    python audit_moves.py            # só relata
    python audit_moves.py --fix      # corrige o que for seguro
"""
import json
import os
import sys

DATA = os.path.join(os.path.dirname(__file__), 'server', 'data')
MOVES_FILE = os.path.join(DATA, 'moves.json')
POKE_FILE = os.path.join(DATA, 'pokemon.json')
CANONICAL_FILE = os.path.join(DATA, 'canonical_moves.json')

# Mapa manual de nomes locais → identifier canônico (casos especiais)
MANUAL_NAME_MAP = {'vise grip': 'vice-grip'}


def normalize(name):
    """'King's Shield' → 'kings-shield' (regra do identifier do PokeAPI)."""
    n = name.lower().replace("'", '').replace('’', '')
    n = n.replace('.', '').replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return MANUAL_NAME_MAP.get(name.lower(), n)


def dice_for_power(power):
    """Dados 5e pela potência canônica (correlação real do moves.json)."""
    if power is None:
        return None
    bands = [(25, '1d4'), (45, '1d6'), (55, '1d8'), (65, '1d10'), (75, '1d12'),
             (85, '2d6'), (95, '2d8'), (110, '3d6'), (125, '2d10'), (140, '3d8')]
    for cap, dice in bands:
        if power <= cap:
            return dice
    return '2d12'

# Moves cujo papel canônico é 100% status/cura/buff/armadilha (não causam dano no uso).
PURE_STATUS = {
    'harden', 'heal order', 'heal pulse', 'ingrain', 'milk drink', 'moonlight',
    'morning sun', 'poison gas', 'powder', 'recover', 'rest', 'roost',
    'soft-boiled', 'spikes', 'stealth rock', 'swallow', 'swords dance',
    'synthesis', 'wish', 'toxic spikes', 'sticky web',
}


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def audit(fix=False):
    moves = load(MOVES_FILE)
    pokes = load(POKE_FILE)
    canonical = load(CANONICAL_FILE) if os.path.exists(CANONICAL_FILE) else {}
    by_name = {k.lower(): k for k in moves}
    problems = {'status_com_dano': [], 'pure_status_com_dano': [], 'moveset_quebrado': {},
                'categoria_errada': [], 'dano_sem_dado': [], 'sem_canonico': [],
                'power_null': []}

    # 4: reconciliação com os dados canônicos (pokemondb/PokeAPI)
    for name, v in moves.items():
        canon = canonical.get(normalize(name))
        if not canon:
            if canonical:
                problems['sem_canonico'].append(name)
            continue
        local_cat, canon_cat = v.get('category'), canon['category']
        if local_cat != canon_cat:
            if canon_cat != 'status' and canon.get('power') is None:
                # dano variável (Beat Up, Bide, Endeavor...) — sem dado seguro
                problems['power_null'].append((name, local_cat, canon_cat))
            else:
                problems['categoria_errada'].append(
                    (name, local_cat, canon_cat, canon.get('power')))
        elif canon_cat != 'status' and not v.get('baseDamage'):
            if canon.get('power') is None:
                problems['power_null'].append((name, local_cat, canon_cat))
            else:
                problems['dano_sem_dado'].append((name, canon['power']))

    # 1 + 2: moves
    for name, v in moves.items():
        cat = v.get('category')
        bd = v.get('baseDamage')
        if cat == 'status' and bd:
            problems['status_com_dano'].append(name)
        if name.lower() in PURE_STATUS and (cat != 'status' or bd):
            problems['pure_status_com_dano'].append(name)

    # 3: movesets que referenciam moves inexistentes
    for p in pokes:
        bad = set()
        pools = list(p.get('startingMoves') or [])
        for ms in (p.get('levelMoves') or {}).values():
            pools += ms or []
        pools += list(p.get('eggMoves') or [])
        for mv in pools:
            if not isinstance(mv, str):
                continue
            low = mv.lower()
            if len(mv) <= 2 or '©' in mv:
                bad.add(mv)
            elif low not in by_name and mv not in moves:
                bad.add(mv)
        if bad:
            problems['moveset_quebrado'][p['name']] = sorted(bad)

    # relatório
    print(f"1. Moves 'status' com baseDamage: {len(problems['status_com_dano'])}")
    for n in problems['status_com_dano']:
        print(f"   - {n} ({moves[n].get('baseDamage')})")
    print(f"2. Moves puramente status com dano: {len(problems['pure_status_com_dano'])}")
    for n in problems['pure_status_com_dano']:
        print(f"   - {n} ({moves[n].get('category')}/{moves[n].get('baseDamage')})")
    tot_bad = sum(len(v) for v in problems['moveset_quebrado'].values())
    print(f"3. Movesets com nomes quebrados: {len(problems['moveset_quebrado'])} espécies, {tot_bad} entradas")
    print(f"4. Categoria divergente do canônico: {len(problems['categoria_errada'])}")
    for n, lc, cc, pw in problems['categoria_errada']:
        print(f"   - {n}: {lc} → {cc}" + (f" (power {pw})" if cc != 'status' else ''))
    print(f"5. Moves de dano sem baseDamage: {len(problems['dano_sem_dado'])}")
    for n, pw in problems['dano_sem_dado']:
        print(f"   - {n} (power {pw} → {dice_for_power(pw)})")
    print(f"6. Dano variável (power NULL, decisão manual): {len(problems['power_null'])}")
    for item in problems['power_null']:
        print(f"   - {item[0]} (local={item[1]}, canônico={item[2]})")
    if problems['sem_canonico']:
        print(f"7. Sem correspondência canônica: {problems['sem_canonico']}")

    if fix:
        # 1+2: força category status e remove baseDamage
        for n in set(problems['status_com_dano'] + problems['pure_status_com_dano']):
            moves[n]['category'] = 'status'
            moves[n].pop('baseDamage', None)
            moves[n].pop('higherLevels', None)
        # 4: corrige categorias pela canônica
        for n, lc, cc, pw in problems['categoria_errada']:
            moves[n]['category'] = cc
            if cc == 'status':
                moves[n].pop('baseDamage', None)
                moves[n].pop('higherLevels', None)
            elif not moves[n].get('baseDamage'):
                moves[n]['baseDamage'] = dice_for_power(pw)
        # 5: adiciona dados aos moves de dano sem baseDamage
        for n, pw in problems['dano_sem_dado']:
            moves[n]['baseDamage'] = dice_for_power(pw)
        # 3: remove entradas quebradas dos movesets
        removed = 0
        for p in pokes:
            def clean(lst):
                nonlocal removed
                out = []
                for mv in lst or []:
                    low = str(mv).lower()
                    if isinstance(mv, str) and len(mv) > 2 and '©' not in mv and (low in by_name or mv in moves):
                        out.append(mv)
                    else:
                        removed += 1
                return out
            if 'startingMoves' in p:
                p['startingMoves'] = clean(p['startingMoves'])
            if 'levelMoves' in p:
                p['levelMoves'] = {lv: clean(ms) for lv, ms in p['levelMoves'].items()}
            if 'eggMoves' in p:
                p['eggMoves'] = clean(p['eggMoves'])
        with open(MOVES_FILE, 'w', encoding='utf-8') as f:
            json.dump(moves, f, ensure_ascii=False, indent=1)
        with open(POKE_FILE, 'w', encoding='utf-8') as f:
            json.dump(pokes, f, ensure_ascii=False, indent=1)
        print(f"\n✅ Corrigido. Entradas de moveset removidas: {removed}")

    return problems


if __name__ == '__main__':
    audit(fix='--fix' in sys.argv)
