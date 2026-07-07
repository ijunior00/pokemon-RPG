"""Recalcula vulnerabilities/resistances/immunities de TODAS as espécies em
server/data/pokemon.json a partir da tabela de tipos oficial (Gen 6+, 18
tipos). Corrige dados incompletos (ex.: Graveler sem fraqueza a Water, que
fazia 'água não reconhecer super-efetivo').

    python3 tools/fix_type_matchups.py
"""
import json
import os

DATA = os.path.join(os.path.dirname(__file__), '..', 'server', 'data', 'pokemon.json')

# Tabela oficial: para cada tipo ATACANTE, os multiplicadores contra cada
# tipo DEFENSOR (só listamos ≠1; 2 = super efetivo, 0.5 = resistido, 0 = imune)
CHART = {
    'Normal':   {'Rock': .5, 'Ghost': 0, 'Steel': .5},
    'Fire':     {'Fire': .5, 'Water': .5, 'Grass': 2, 'Ice': 2, 'Bug': 2, 'Rock': .5, 'Dragon': .5, 'Steel': 2},
    'Water':    {'Fire': 2, 'Water': .5, 'Grass': .5, 'Ground': 2, 'Rock': 2, 'Dragon': .5},
    'Electric': {'Water': 2, 'Electric': .5, 'Grass': .5, 'Ground': 0, 'Flying': 2, 'Dragon': .5},
    'Grass':    {'Fire': .5, 'Water': 2, 'Grass': .5, 'Poison': .5, 'Ground': 2, 'Flying': .5,
                 'Bug': .5, 'Rock': 2, 'Dragon': .5, 'Steel': .5},
    'Ice':      {'Fire': .5, 'Water': .5, 'Grass': 2, 'Ice': .5, 'Ground': 2, 'Flying': 2, 'Dragon': 2, 'Steel': .5},
    'Fighting': {'Normal': 2, 'Ice': 2, 'Poison': .5, 'Flying': .5, 'Psychic': .5, 'Bug': .5,
                 'Rock': 2, 'Ghost': 0, 'Dark': 2, 'Steel': 2, 'Fairy': .5},
    'Poison':   {'Grass': 2, 'Poison': .5, 'Ground': .5, 'Rock': .5, 'Ghost': .5, 'Steel': 0, 'Fairy': 2},
    'Ground':   {'Fire': 2, 'Electric': 2, 'Grass': .5, 'Poison': 2, 'Flying': 0, 'Bug': .5, 'Rock': 2, 'Steel': 2},
    'Flying':   {'Electric': .5, 'Grass': 2, 'Fighting': 2, 'Bug': 2, 'Rock': .5, 'Steel': .5},
    'Psychic':  {'Fighting': 2, 'Poison': 2, 'Psychic': .5, 'Dark': 0, 'Steel': .5},
    'Bug':      {'Fire': .5, 'Grass': 2, 'Fighting': .5, 'Poison': .5, 'Flying': .5, 'Psychic': 2,
                 'Ghost': .5, 'Dark': 2, 'Steel': .5, 'Fairy': .5},
    'Rock':     {'Fire': 2, 'Ice': 2, 'Fighting': .5, 'Ground': .5, 'Flying': 2, 'Bug': 2, 'Steel': .5},
    'Ghost':    {'Normal': 0, 'Psychic': 2, 'Ghost': 2, 'Dark': .5},
    'Dragon':   {'Dragon': 2, 'Steel': .5, 'Fairy': 0},
    'Dark':     {'Fighting': .5, 'Psychic': 2, 'Ghost': 2, 'Dark': .5, 'Fairy': .5},
    'Steel':    {'Fire': .5, 'Water': .5, 'Electric': .5, 'Ice': 2, 'Rock': 2, 'Steel': .5, 'Fairy': 2},
    'Fairy':    {'Fire': .5, 'Fighting': 2, 'Poison': .5, 'Dragon': 2, 'Dark': 2, 'Steel': .5},
}
ALL_TYPES = list(CHART.keys())


def matchup(defender_types):
    vuln, res, imm = [], [], []
    for atk in ALL_TYPES:
        mult = 1.0
        for dt in defender_types:
            mult *= CHART[atk].get(dt, 1.0)
        if mult == 0:
            imm.append(atk)
        elif mult > 1:
            vuln.append(atk)
        elif mult < 1:
            res.append(atk)
    return vuln, res, imm


def main():
    data = json.load(open(DATA, encoding='utf-8'))
    changed = 0
    for p in data:
        types = [t for t in (p.get('types') or []) if t in CHART]
        if not types:
            continue
        v, r, i = matchup(types)
        if (set(p.get('vulnerabilities') or []) != set(v)
                or set(p.get('resistances') or []) != set(r)
                or set(p.get('immunities') or []) != set(i)):
            changed += 1
        p['vulnerabilities'] = v
        p['resistances'] = r
        p['immunities'] = i
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # sanidade: Graveler (Rock/Ground) fraco a Water; Gengar (Ghost) imune a Normal
    by = {x['name'].lower(): x for x in data}
    assert 'Water' in by['graveler']['vulnerabilities'], 'Graveler ainda sem Water'
    assert 'Normal' in by['gengar']['immunities'], 'Gengar sem imunidade a Normal'
    assert 'Ground' in by['gyarados']['immunities'], 'Gyarados (Flying) sem imunidade a Ground'
    print(f'✅ {changed} espécies corrigidas de {len(data)}. Sanidade OK.')


if __name__ == '__main__':
    main()
