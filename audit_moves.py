"""
Auditoria de dados de moves e movesets — ferramenta de busca reutilizável.

Detecta:
  1. Moves de categoria 'status' que ainda têm baseDamage (dariam dano);
  2. Moves cujo papel é 100% cura/buff/proteção mas têm baseDamage
     (lista canônica — ignora golpes de dreno/dano+buff legítimos);
  3. Entradas de startingMoves/levelMoves que não existem no banco de moves
     (nomes quebrados como 'Air','Cutter').

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
    by_name = {k.lower(): k for k in moves}
    problems = {'status_com_dano': [], 'pure_status_com_dano': [], 'moveset_quebrado': {}}

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

    if fix:
        # 1+2: força category status e remove baseDamage
        for n in set(problems['status_com_dano'] + problems['pure_status_com_dano']):
            moves[n]['category'] = 'status'
            moves[n].pop('baseDamage', None)
            moves[n].pop('higherLevels', None)
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
