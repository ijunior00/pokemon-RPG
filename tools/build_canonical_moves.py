"""
Gera os dados canônicos de moves a partir dos CSVs do PokeAPI
(a mesma base de dados que o pokemondb.net e a Bulbapedia exibem).

Saídas (commitadas em server/data/):
  - canonical_moves.json: por identifier ("helping-hand") →
      {category, power, priority, ailment, ailment_chance, stat_changes,
       healing, drain, flinch_chance, effect_chance}
  - move_effects.json: por nome local em minúsculas ("helping hand") →
      {'effect': {...formato KNOWN_EFFECTS...}, 'on_hit': {status, chance, on}}
    Efeitos derivados do canônico + OVERLAY do mapa curado atual
    (KNOWN_EFFECTS/MOVE_STATUS_EFFECTS) para preservar o balanceamento.

Uso:  python3 tools/build_canonical_moves.py
"""
import csv
import io
import json
import os
import ssl
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, 'server', 'data')
MOVES_FILE = os.path.join(DATA, 'moves.json')
CANONICAL_FILE = os.path.join(DATA, 'canonical_moves.json')
EFFECTS_FILE = os.path.join(DATA, 'move_effects.json')

BASE = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
CA_BUNDLE = '/root/.ccr/ca-bundle.crt'

# damage_class_id → categoria local
DAMAGE_CLASS = {1: 'status', 2: 'physical', 3: 'special'}

# stat_id (stats.csv) → chave local
STAT_MAP = {2: 'ATK', 3: 'DEF', 4: 'SPA', 5: 'SPD', 6: 'SPE',
            7: 'attack_roll', 8: 'AC'}   # 7=accuracy, 8=evasion; 1=HP (ignorado)

# ailment canônico → chave PT de STATUS_CONDITIONS
AILMENT_MAP = {
    'paralysis': 'paralisado',
    'sleep': 'dormindo',
    'freeze': 'congelado',
    'burn': 'queimado',
    'poison': 'badly_poisoned',       # o sistema tem uma única condição de veneno
    'bad-poison': 'badly_poisoned',
    'confusion': 'confuso',
    'infatuation': 'amedrontado',
}
# saves default por condição (5e)
SAVE_MAP = {
    'paralisado': 'CON', 'badly_poisoned': 'CON', 'congelado': 'CON',
    'atordoado': 'CON', 'dormindo': 'WIS', 'confuso': 'WIS',
    'amedrontado': 'WIS', 'queimado': 'DEX',
}

# nomes locais que não resolvem pela normalização simples
MANUAL_NAME_MAP = {'vise grip': 'vice-grip'}


def normalize(name):
    """'King's Shield' → 'kings-shield' (regra do identifier do PokeAPI)."""
    n = name.lower().replace("'", '').replace('’', '')
    n = n.replace('.', '').replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return MANUAL_NAME_MAP.get(name.lower(), n)


def fetch(name):
    ctx = ssl.create_default_context(
        cafile=CA_BUNDLE if os.path.exists(CA_BUNDLE) else None)
    with urllib.request.urlopen(BASE + name, context=ctx, timeout=60) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode())))


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def build_canonical():
    moves_csv = fetch('moves.csv')
    meta_csv = fetch('move_meta.csv')
    stat_csv = fetch('move_meta_stat_changes.csv')
    ail_csv = fetch('move_meta_ailments.csv')

    ailment_names = {_int(r['id']): r['identifier'] for r in ail_csv}
    meta = {_int(r['move_id']): r for r in meta_csv}
    stat_changes = {}
    for r in stat_csv:
        stat_changes.setdefault(_int(r['move_id']), []).append(
            (_int(r['stat_id']), _int(r['change'])))

    canonical = {}
    for r in moves_csv:
        mid = _int(r['id'])
        if mid >= 10000:   # shadow moves etc.
            continue
        m = meta.get(mid, {})
        ail_name = ailment_names.get(_int(m.get('meta_ailment_id'), 0), 'none')
        changes = [{'stat': STAT_MAP[sid], 'change': ch}
                   for sid, ch in stat_changes.get(mid, []) if sid in STAT_MAP]
        canonical[r['identifier']] = {
            'category': DAMAGE_CLASS.get(_int(r['damage_class_id']), 'physical'),
            'power': _int(r['power'], None) if r['power'] else None,
            'accuracy': _int(r['accuracy'], None) if r['accuracy'] else None,
            'priority': _int(r['priority']),
            'effect_chance': _int(r['effect_chance'], None) if r['effect_chance'] else None,
            'ailment': ail_name if ail_name not in ('none', 'unknown') else None,
            'ailment_chance': _int(m.get('ailment_chance')),
            'flinch_chance': _int(m.get('flinch_chance')),
            'stat_chance': _int(m.get('stat_chance')),
            'healing': _int(m.get('healing')),
            'drain': _int(m.get('drain')),
            'stat_changes': changes,
        }
    return canonical


def derive_effect(local_name, canon):
    """Deriva o efeito 5e de um move a partir do registro canônico.
    Retorna {'effect': ..., 'on_hit': ...} (chaves opcionais)."""
    out = {}
    ail_pt = AILMENT_MAP.get(canon.get('ailment') or '')
    changes = canon.get('stat_changes') or []
    healing = canon.get('healing') or 0

    if canon['category'] == 'status':
        if ail_pt:
            out['effect'] = {'type': 'inflict_status', 'status': ail_pt,
                             'save': SAVE_MAP.get(ail_pt, 'WIS')}
        elif changes:
            # maior mudança define o efeito; positivo = buff próprio,
            # negativo = debuff no alvo (regra dos jogos p/ moves de status)
            main = max(changes, key=lambda c: abs(c['change']))
            value = max(-4, min(4, main['change'] * 2))
            if main['change'] > 0:
                out['effect'] = {'type': 'buff_self', 'stat': main['stat'],
                                 'value': value, 'duration': 3}
            else:
                out['effect'] = {'type': 'debuff_target', 'stat': main['stat'],
                                 'value': value, 'save': 'WIS', 'duration': 3}
        elif healing > 0:
            amount = 'full' if local_name == 'rest' else (
                'half' if healing >= 50 else 'quarter')
            out['effect'] = {'type': 'heal_self', 'amount': amount}
    else:
        # move de dano com efeito secundário → on_hit com a chance real
        chance = canon.get('ailment_chance') or canon.get('effect_chance') or 0
        if ail_pt:
            out['on_hit'] = {'status': ail_pt,
                             'chance': (chance or 100) / 100.0, 'on': 'hit'}
        elif canon.get('flinch_chance'):
            out['on_hit'] = {'status': 'atordoado',
                             'chance': canon['flinch_chance'] / 100.0, 'on': 'hit'}
    return out


def main():
    print('Baixando CSVs canônicos do PokeAPI...')
    canonical = build_canonical()
    with open(CANONICAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(canonical, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f'✅ {CANONICAL_FILE}: {len(canonical)} moves canônicos')

    with open(MOVES_FILE, encoding='utf-8') as f:
        local_moves = json.load(f)

    # Overlay curado: extrai KNOWN_EFFECTS via auto_detect com descrição vazia
    # (só o nome casa) e MOVE_STATUS_EFFECTS direto do módulo. Zera
    # MOVE_EFFECTS_DATA antes p/ não ler um move_effects.json antigo.
    import status_effects as fx
    fx.MOVE_EFFECTS_DATA = {}

    effects_out = {}
    unmatched = []
    for name in local_moves:
        key = name.lower()
        ident = normalize(name)
        canon = canonical.get(ident)
        if not canon:
            unmatched.append(name)
            continue
        entry = derive_effect(key, canon)
        # overlay 1: KNOWN_EFFECTS (curado) tem prioridade sobre o derivado
        curated = fx.auto_detect_move_effect({'name': name, 'description': ''})
        if curated:
            entry['effect'] = curated
        # overlay 2: MOVE_STATUS_EFFECTS (on-hit curado) — só para moves de DANO
        # e só condições reais (ignora pseudo-status como 'debuff')
        curated_hit = fx.MOVE_STATUS_EFFECTS.get(name)
        if (curated_hit and canon['category'] != 'status'
                and curated_hit.get('status') in fx.STATUS_CONDITIONS):
            entry['on_hit'] = dict(curated_hit)
        # move de status nunca tem efeito on-hit (não causa dano)
        if canon['category'] == 'status':
            entry.pop('on_hit', None)
        if entry:
            effects_out[key] = entry

    with open(EFFECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(effects_out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f'✅ {EFFECTS_FILE}: {len(effects_out)} moves com efeito')

    if unmatched:
        print(f'\n⚠️ {len(unmatched)} nomes locais SEM correspondência canônica:')
        for n in unmatched:
            print(f'   - {n} (tentado: {normalize(n)})')
        sys.exit(1)
    print('Todos os nomes locais resolvidos. ✔')


if __name__ == '__main__':
    main()
