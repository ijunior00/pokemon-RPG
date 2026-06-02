"""Extract Mega Evolution data from the supplement PDF."""
import fitz, json, re, os

PDF_PATH = r'c:\Users\Barros-Roux\Desktop\RPG POKEMON\Pokémon 5e RPG\Livros Suplementos\Mega Evolução - Pokémon 5e.pdf'
OUTPUT = os.path.join(os.path.dirname(__file__), 'server', 'data', 'mega_stones.json')

doc = fitz.open(PDF_PATH)
full = ''
for i in range(2, 13):
    full += doc[i].get_text() + '\n'

# Clean: join lines, then split by stone names
lines = [l.strip() for l in full.split('\n')]
text = '\n'.join(lines)

# Split by stone names
blocks = re.split(r'\n(?=[A-Z][\w]+ite(?:\s[XY])?\nPermite)', text)

stones = {}
for block in blocks:
    block = block.strip()
    if not block or 'Permite que' not in block:
        continue
    
    first_line = block.split('\n')[0]
    name_match = re.match(r'^([A-Z][\w]+ite(?:\s[XY])?)', first_line)
    if not name_match:
        continue
    stone_name = name_match.group(1)
    
    # Flatten to single line for reliable regex
    flat = ' '.join(block.split('\n'))
    
    poke_match = re.search(r'Permite que (\w+) Mega Evolua', flat)
    if not poke_match:
        continue
    pokemon = poke_match.group(1)
    
    stone = {'stone': stone_name, 'pokemon': pokemon, 'megaName': f"Mega {pokemon}", 'bonuses': {}}
    
    ability_match = re.search(r'ganha a habilidade ([\w\s]+?)(?:,| e | além)', flat)
    if ability_match:
        stone['ability'] = ability_match.group(1).strip()
    
    type_match = re.search(r'tipo muda para ([\w/]+)', flat)
    if type_match:
        stone['newTypes'] = [t.strip() for t in type_match.group(1).split('/')]
    
    for stat_match in re.finditer(r'([+-]\d+) na sua (CA|Força|Destreza|Constituição|Inteligência|Sabedoria)', flat):
        val = int(stat_match.group(1))
        stat_name = stat_match.group(2)
        mapping = {'CA': 'ac', 'Força': 'STR', 'Destreza': 'DEX', 'Constituição': 'CON', 'Inteligência': 'INT', 'Sabedoria': 'WIS'}
        stone['bonuses'][mapping[stat_name]] = val
    
    cha_match = re.search(r'([+-]\d+) no seu Carisma', flat)
    if cha_match:
        stone['bonuses']['CHA'] = int(cha_match.group(1))
    
    spd_match = re.search(r'([+-]\d+) pés.*?velocidades de movimento', flat)
    if spd_match:
        stone['bonuses']['speed'] = spd_match.group(1) + 'ft'
    
    size_match = re.search(r'tamanho muda para (\w+)', flat)
    if size_match:
        stone['size'] = size_match.group(1)
    
    stones[stone_name] = stone

print(f"Extracted {len(stones)} Mega Stones")
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(stones, f, ensure_ascii=False, indent=2)

for name in ['Charizardite X', 'Charizardite Y', 'Venusaurite', 'Gengarite', 'Blazikenite']:
    s = stones.get(name, {})
    print(f"  {name}: {s.get('pokemon')} -> ability={s.get('ability')}, types={s.get('newTypes')}, bonuses={s.get('bonuses')}")
