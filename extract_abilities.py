"""
Corrige os dados de habilidades em server/data/pokemon.json.

O extrator original quebrou o campo `ability`: o name virou "Resistances"
(ou variações) e o nome real da habilidade ficou embutido na descrição,
no padrão: "<lista de resistências> <NomeDaHabilidade>: <descrição>".
Alguns pokémon têm ainda um segmento "Senses: ..." (visões) e/ou mais de
uma habilidade normal.

Este script:
  1. separa a descrição em segmentos "Nome: texto";
  2. remove prefixos que são nomes de tipos (a lista de resistências);
  3. valida os nomes contra um catálogo de habilidades conhecidas;
  4. grava:  p['abilities']  = [{name, description}, ...] (normais)
             p['senses']     = "Darkvision 60ft..." (se houver)
             p['ability']    = primeira habilidade normal (compatível)

Uso: python extract_abilities.py
"""
import json
import re
import unicodedata

POKEMON_FILE = 'server/data/pokemon.json'

TYPE_WORDS = {
    'normal', 'fire', 'water', 'grass', 'electric', 'ice', 'fighting',
    'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost',
    'dragon', 'dark', 'steel', 'fairy', 'resistances', 'resistance',
    'vulnerabilities', 'immunities',
}

# Catálogo de habilidades Gen 1-7 (nomes oficiais) para validar o parse.
KNOWN_ABILITIES = {
    'Adaptability', 'Aerilate', 'Aftermath', 'Air Lock', 'Analytic', 'Anger Point',
    'Anticipation', 'Arena Trap', 'Aroma Veil', 'Aura Break', 'Bad Dreams',
    'Battery', 'Battle Armor', 'Battle Bond', 'Beast Boost', 'Berserk',
    'Big Pecks', 'Blaze', 'Bulletproof', 'Cheek Pouch', 'Chlorophyll',
    'Clear Body', 'Cloud Nine', 'Color Change', 'Comatose', 'Competitive',
    'Compound Eyes', 'Contrary', 'Corrosion', 'Cursed Body', 'Cute Charm',
    'Damp', 'Dancer', 'Dark Aura', 'Dazzling', 'Defeatist', 'Defiant',
    'Delta Stream', 'Desolate Land', 'Disguise', 'Download', 'Drizzle',
    'Drought', 'Dry Skin', 'Early Bird', 'Effect Spore', 'Electric Surge',
    'Emergency Exit', 'Fairy Aura', 'Filter', 'Flame Body', 'Flare Boost',
    'Flash Fire', 'Flower Gift', 'Flower Veil', 'Fluffy', 'Forecast',
    'Forewarn', 'Friend Guard', 'Frisk', 'Full Metal Body', 'Fur Coat',
    'Gale Wings', 'Galvanize', 'Gluttony', 'Gooey', 'Grass Pelt',
    'Grassy Surge', 'Guts', 'Harvest', 'Healer', 'Heatproof', 'Heavy Metal',
    'Honey Gather', 'Huge Power', 'Hustle', 'Hydration', 'Hyper Cutter',
    'Ice Body', 'Illuminate', 'Illusion', 'Immunity', 'Imposter',
    'Infiltrator', 'Innards Out', 'Inner Focus', 'Insomnia', 'Intimidate',
    'Iron Barbs', 'Iron Fist', 'Justified', 'Keen Eye', 'Klutz',
    'Leaf Guard', 'Levitate', 'Light Metal', 'Lightning Rod', 'Limber',
    'Liquid Ooze', 'Liquid Voice', 'Long Reach', 'Magic Bounce',
    'Magic Guard', 'Magician', 'Magma Armor', 'Magnet Pull', 'Marvel Scale',
    'Mega Launcher', 'Merciless', 'Minus', 'Misty Surge', 'Mold Breaker',
    'Moody', 'Motor Drive', 'Moxie', 'Multiscale', 'Multitype', 'Mummy',
    'Natural Cure', 'Neuroforce', 'No Guard', 'Normalize', 'Oblivious',
    'Overcoat', 'Overgrow', 'Own Tempo', 'Parental Bond', 'Pickpocket',
    'Pickup', 'Pixilate', 'Plus', 'Poison Heal', 'Poison Point',
    'Poison Touch', 'Power Construct', 'Power of Alchemy', 'Prankster',
    'Pressure', 'Primordial Sea', 'Prism Armor', 'Protean', 'Psychic Surge',
    'Pure Power', 'Queenly Majesty', 'Quick Feet', 'Rain Dish', 'Rattled',
    'Receiver', 'Reckless', 'Refrigerate', 'Regenerator', 'Rivalry',
    'RKS System', 'Rock Head', 'Rough Skin', 'Run Away', 'Sand Force',
    'Sand Rush', 'Sand Stream', 'Sand Veil', 'Sap Sipper', 'Schooling',
    'Scrappy', 'Serene Grace', 'Shadow Shield', 'Shadow Tag', 'Shed Skin',
    'Sheer Force', 'Shell Armor', 'Shield Dust', 'Shields Down', 'Simple',
    'Skill Link', 'Slow Start', 'Slush Rush', 'Sniper', 'Snow Cloak',
    'Snow Warning', 'Solar Power', 'Solid Rock', 'Soul-Heart', 'Soundproof',
    'Speed Boost', 'Stakeout', 'Stall', 'Stamina', 'Stance Change', 'Static',
    'Steadfast', 'Steelworker', 'Stench', 'Sticky Hold', 'Storm Drain',
    'Strong Jaw', 'Sturdy', 'Suction Cups', 'Super Luck', 'Surge Surfer',
    'Swarm', 'Sweet Veil', 'Swift Swim', 'Symbiosis', 'Synchronize',
    'Tangled Feet', 'Tangling Hair', 'Technician', 'Telepathy', 'Teravolt',
    'Thick Fat', 'Tinted Lens', 'Torrent', 'Tough Claws', 'Toxic Boost',
    'Trace', 'Triage', 'Truant', 'Turboblaze', 'Unaware', 'Unburden',
    'Unnerve', 'Victory Star', 'Vital Spirit', 'Volt Absorb', 'Water Absorb',
    'Water Bubble', 'Water Compaction', 'Water Veil', 'Weak Armor',
    'White Smoke', 'Wimp Out', 'Wonder Guard', 'Wonder Skin', 'Zen Mode',
}
_KNOWN_LOWER = {a.lower(): a for a in KNOWN_ABILITIES}

MARKER_RE = re.compile(r"([A-Z][A-Za-z'’\- ]{1,40}?):\s")


def _norm(s: str) -> str:
    return unicodedata.normalize('NFKD', s).strip()


def _clean_marker(raw: str):
    """'Rock Steel Static' → ('Static', True). Remove tipos/lixo do prefixo.
    Retorna (nome, é_habilidade_conhecida)."""
    words = _norm(raw).replace('\n', ' ').replace(',', ' ').split()
    # tenta o sufixo mais longo que seja uma habilidade conhecida
    for start in range(len(words)):
        cand = ' '.join(words[start:])
        if cand.lower() in _KNOWN_LOWER:
            return _KNOWN_LOWER[cand.lower()], True
    # fallback: remove palavras de tipo do início
    while words and words[0].lower().strip('.,') in TYPE_WORDS:
        words.pop(0)
    return ' '.join(words), False


def parse_ability_blob(desc: str):
    """Extrai (abilities, senses) de uma descrição corrompida."""
    abilities, senses = [], None
    if not desc:
        return abilities, senses
    matches = list(MARKER_RE.finditer(desc))
    for i, m in enumerate(matches):
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(desc)
        seg_text = _norm(desc[m.end():seg_end]).rstrip(' .,')
        name, known = _clean_marker(m.group(1))
        if not name:
            continue
        if name.lower() == 'senses':
            senses = seg_text
        elif known:
            abilities.append({'name': name, 'description': seg_text})
        # nomes não reconhecidos e que não são Senses: ignora (lixo do parse)
    return abilities, senses


def main():
    with open(POKEMON_FILE, encoding='utf-8') as f:
        data = json.load(f)

    fixed = no_ability = unparsed = already_ok = 0
    for p in data:
        ab = p.get('ability') or {}
        name = (ab.get('name') or '').strip()
        desc = ab.get('description') or ''

        if not name and not desc:
            p['abilities'] = []
            no_ability += 1
            continue

        # nome já limpo (não contém 'Resistances' e é conhecido)?
        if name.lower() in _KNOWN_LOWER:
            p['abilities'] = [{'name': _KNOWN_LOWER[name.lower()],
                               'description': desc}]
            already_ok += 1
            continue

        abilities, senses = parse_ability_blob(desc)
        if senses:
            p['senses'] = senses
        if abilities:
            p['abilities'] = abilities
            p['ability'] = dict(abilities[0])   # compatibilidade
            fixed += 1
        else:
            p['abilities'] = []
            unparsed += 1
            print(f"  ⚠️ sem parse: {p['name']}: {desc[:90]!r}")

    with open(POKEMON_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f'corrigidos: {fixed} | já ok: {already_ok} | '
          f'sem habilidade: {no_ability} | sem parse: {unparsed}')


if __name__ == '__main__':
    main()
