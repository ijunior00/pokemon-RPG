"""
Grava os BASE STATS REAIS de Pokémon (escala 1-255, os mesmos exibidos no
pokemondb.net) num campo novo `base_stats` em server/data/pokemon.json,
a partir dos CSVs oficiais do PokeAPI.

O campo `stats` antigo (escala D&D 6-19) fica INTACTO — rollback trivial.

Uso:  python3 tools/build_pokemon_stats.py
Sai com código 1 listando espécies sem correspondência.
"""
import csv
import io
import json
import os
import ssl
import sys
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'server', 'data')
POKEMON_FILE = os.path.join(DATA, 'pokemon.json')

BASE = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
CA_BUNDLE = '/root/.ccr/ca-bundle.crt'

# stat_id (stats.csv do PokeAPI) → chave local
STAT_MAP = {1: 'HP', 2: 'ATK', 3: 'DEF', 4: 'SPA', 5: 'SPD', 6: 'SPE'}


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


def norm_name(name):
    """Nome local → identifier PokeAPI ('Nidoran ♀' → 'nidoran-f',
    "Farfetch'd" → 'farfetchd', 'Mr. Mime' → 'mr-mime')."""
    n = unicodedata.normalize('NFKD', name).strip().lower()
    n = n.replace('♀', '-f').replace('♂', '-m')
    n = n.replace('female', '-f').replace('male', '-m')
    n = n.replace("'", '').replace('’', '').replace('.', '').replace(':', '')
    n = n.replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return n.strip('-')


def main():
    print('Baixando pokemon.csv + pokemon_stats.csv do PokeAPI...')
    pokemon_csv = fetch('pokemon.csv')
    stats_csv = fetch('pokemon_stats.csv')

    # id → identifier e species_id (formas default: id == species_id p/ gen 1-3)
    by_id = {}
    by_ident = {}
    for r in pokemon_csv:
        pid = _int(r['id'])
        if not _int(r['is_default'], 1):
            continue
        by_id[_int(r['species_id'])] = pid
        by_ident[r['identifier']] = pid

    # pokemon_id → {HP, ATK, DEF, SPA, SPD, SPE}
    base_stats = {}
    for r in stats_csv:
        sid = _int(r['stat_id'])
        if sid not in STAT_MAP:
            continue
        base_stats.setdefault(_int(r['pokemon_id']), {})[STAT_MAP[sid]] = _int(r['base_stat'])

    with open(POKEMON_FILE, encoding='utf-8') as f:
        pokemon = json.load(f)

    unmatched = []
    updated = 0
    for p in pokemon:
        number = _int(p.get('number'))
        pid = by_id.get(number)                      # casa por número (dex nacional)
        if pid is None:
            pid = by_ident.get(norm_name(p.get('name', '')))   # fallback por nome
        stats = base_stats.get(pid) if pid else None
        if not stats or len(stats) != 6:
            unmatched.append(f"{p.get('name')} (#{number})")
            continue
        p['base_stats'] = stats
        updated += 1

    with open(POKEMON_FILE, 'w', encoding='utf-8') as f:
        json.dump(pokemon, f, ensure_ascii=False, indent=1)

    print(f'✅ base_stats gravado em {updated}/{len(pokemon)} espécies')

    # Sanidade: valores dentro de 1-255 e Pikachu confere com o pokemondb
    pika = next((p for p in pokemon if p.get('number') == 25), None)
    assert pika and pika['base_stats'] == {
        'HP': 35, 'ATK': 55, 'DEF': 40, 'SPA': 50, 'SPD': 50, 'SPE': 90}, \
        f"Pikachu divergente: {pika and pika.get('base_stats')}"
    for p in pokemon:
        bs = p.get('base_stats')
        if bs:
            assert all(1 <= v <= 255 for v in bs.values()), f"fora de 1-255: {p['name']} {bs}"
    print('✔ Sanidade: Pikachu = 35/55/40/50/50/90 e todos os valores em 1-255')

    if unmatched:
        print(f'\n⚠️ {len(unmatched)} espécies SEM base_stats:')
        for n in unmatched:
            print(f'   - {n}')
        sys.exit(1)
    print('Todas as espécies resolvidas. ✔')


if __name__ == '__main__':
    main()
