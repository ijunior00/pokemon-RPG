"""
Script para extrair dados de todos os Pokemon do Monster Manual PDF
e salvar em formato JSON estruturado.
"""
import fitz
import json
import re
import os

PDF_PATH = r'c:\Users\Barros-Roux\Desktop\RPG POKEMON\Pokémon 5e RPG\Pokémon 5e - Monster Manual Gen 1-7.pdf'
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'server', 'data', 'pokemon.json')

def parse_stats(text):
    """Parse the 6 ability scores from text block."""
    pattern = r'(\d+)\s*\([+-]\d+\)\s*(\d+)\s*\([+-]\d+\)\s*(\d+)\s*\([+-]\d+\)\s*(\d+)\s*\([+-]\d+\)\s*(\d+)\s*\([+-]\d+\)\s*(\d+)\s*\([+-]\d+\)'
    match = re.search(pattern, text)
    if match:
        return {
            'STR': int(match.group(1)),
            'DEX': int(match.group(2)),
            'CON': int(match.group(3)),
            'INT': int(match.group(4)),
            'WIS': int(match.group(5)),
            'CHA': int(match.group(6))
        }
    return None

def parse_pokemon_block(block):
    """Parse a single Pokemon text block into structured data."""
    pokemon = {}
    
    # Name and Number
    name_match = re.search(r'^(.+?)\s*#(\d+)', block, re.MULTILINE)
    if not name_match:
        return None
    pokemon['name'] = name_match.group(1).strip()
    pokemon['number'] = int(name_match.group(2))
    
    # Type
    type_match = re.search(r'Type:\s*(.+)', block)
    if type_match:
        types = [t.strip() for t in type_match.group(1).split('/')]
        pokemon['types'] = types
    
    # Classification and SR
    class_match = re.search(r'Classification:\s*(\w+)\s*\|\s*SR\s*([\d/]+)', block)
    if class_match:
        pokemon['size'] = class_match.group(1)
        pokemon['sr'] = class_match.group(2)
    
    # Minimum Level Found
    level_match = re.search(r'Minimum Level Found:\s*(\d+)', block)
    if level_match:
        pokemon['minLevel'] = int(level_match.group(1))
    
    # Egg Group
    egg_match = re.search(r'Egg Group:\s*(.+)', block)
    if egg_match:
        pokemon['eggGroup'] = [e.strip() for e in egg_match.group(1).split(',')]
    
    # Gender Rate
    gender_match = re.search(r'Gender Rate:\s*(.+)', block)
    if gender_match:
        pokemon['genderRate'] = gender_match.group(1).strip()
    
    # Evolution Stage
    evo_match = re.search(r'Evolution Stage:\s*(\d+/\d+)\s*\|\s*(\d+)\s*ASI', block)
    if evo_match:
        pokemon['evolutionStage'] = evo_match.group(1)
        pokemon['asi'] = int(evo_match.group(2))
    
    # AC
    ac_match = re.search(r'Armor Class:\s*(\d+)', block)
    if ac_match:
        pokemon['ac'] = int(ac_match.group(1))
    
    # HP and Hit Dice
    hp_match = re.search(r'Hit Points:\s*(\d+)\s*\|\s*Hit Dice:\s*(d\d+)', block)
    if hp_match:
        pokemon['hp'] = int(hp_match.group(1))
        pokemon['hitDice'] = hp_match.group(2)
    
    # Speed
    speed_match = re.search(r'Speed:\s*(.+)', block)
    if speed_match:
        pokemon['speed'] = speed_match.group(1).strip()
    
    # Ability Scores
    stats = parse_stats(block)
    if stats:
        pokemon['stats'] = stats
    
    # Proficient Skills
    skills_match = re.search(r'Proficient Skills:\s*(.+)', block)
    if skills_match:
        pokemon['skills'] = [s.strip() for s in skills_match.group(1).split(',')]
    
    # Saving Throws
    saves_match = re.search(r'Saving Throws:\s*(.+)', block)
    if saves_match:
        pokemon['savingThrows'] = [s.strip() for s in saves_match.group(1).split(',')]
    
    # Vulnerabilities
    vuln_match = re.search(r'Vulnerabilities:\s*(.+)', block)
    if vuln_match:
        pokemon['vulnerabilities'] = [v.strip() for v in vuln_match.group(1).split(',')]
    
    # Resistances
    res_match = re.search(r'Resistances:\s*(.+)', block)
    if res_match:
        pokemon['resistances'] = [r.strip() for r in res_match.group(1).split(',')]
    
    # Immunities
    imm_match = re.search(r'Immunities:\s*(.+)', block)
    if imm_match:
        pokemon['immunities'] = [i.strip() for i in imm_match.group(1).split(',')]
    
    # Abilities
    ability_patterns = [
        r'(?:Immunities|Resistances|Vulnerabilities):.+?\n(.+?)(?=Hidden Ability)',
        r'(?:Immunities|Resistances|Vulnerabilities):.+?\n(.+?)(?=Evolution:)',
        r'(?:Immunities|Resistances|Vulnerabilities):.+?\n(.+?)(?=Starting Moves:)',
    ]
    for pat in ability_patterns:
        ability_match = re.search(pat, block, re.DOTALL)
        if ability_match:
            ability_text = ability_match.group(1).strip()
            ab_match = re.search(r'^([A-Z][\w\s\-]+?):\s*(.+)', ability_text, re.DOTALL)
            if ab_match:
                pokemon['ability'] = {
                    'name': ab_match.group(1).strip(),
                    'description': ' '.join(ab_match.group(2).strip().split())
                }
            break
    
    # Hidden Ability
    hidden_pattern = r'Hidden Ability\s*\n?Hidden Ability\s*\n(.+?):\s*(.+?)(?=\nEvolution:|\nStarting Moves:|\n[A-Z][\w\s]+#\d)'
    hidden_match = re.search(hidden_pattern, block, re.DOTALL)
    if hidden_match:
        pokemon['hiddenAbility'] = {
            'name': hidden_match.group(1).strip(),
            'description': ' '.join(hidden_match.group(2).strip().split())
        }
    
    # Evolution info
    evo_info_match = re.search(r'Evolution:\s*(.+?)(?=\nStarting Moves:)', block, re.DOTALL)
    if evo_info_match:
        pokemon['evolutionInfo'] = ' '.join(evo_info_match.group(1).strip().split())
    
    # Starting Moves
    start_moves_match = re.search(r'Starting Moves:\s*(.+?)(?=\nLevel \d|\nTM:|\Z)', block, re.DOTALL)
    if start_moves_match:
        moves_text = start_moves_match.group(1).strip().replace('\n', ', ')
        pokemon['startingMoves'] = [m.strip() for m in moves_text.split(',') if m.strip()]
    
    # Level-up Moves
    level_moves = {}
    for lm in re.finditer(r'Level (\d+):\s*(.+)', block):
        level = int(lm.group(1))
        moves = [m.strip() for m in lm.group(2).split(',') if m.strip()]
        level_moves[str(level)] = moves
    if level_moves:
        pokemon['levelMoves'] = level_moves
    
    # TM moves
    tm_match = re.search(r'TM:\s*([\d,\s]+)', block)
    if tm_match:
        tms = [int(t.strip()) for t in tm_match.group(1).split(',') if t.strip().isdigit()]
        pokemon['tmMoves'] = tms
    
    # Egg Moves
    egg_moves_match = re.search(r'Egg Moves:\s*(.+?)(?=\n[A-Z][\w\s\-]*#\d|\Z)', block, re.DOTALL)
    if egg_moves_match:
        egg_moves_text = egg_moves_match.group(1).strip().replace('\n', ', ')
        pokemon['eggMoves'] = [m.strip() for m in egg_moves_text.split(',') if m.strip()]
    
    return pokemon

def extract_all_pokemon():
    """Extract all Pokemon from the Monster Manual PDF."""
    doc = fitz.open(PDF_PATH)
    all_pokemon = []
    
    print(f"Processing {len(doc)} pages...")
    
    full_text = ""
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        full_text += text + "\n"
    
    # Split by Pokemon entries - name followed by #number
    pokemon_blocks = re.split(r'(?=^[A-Z][\w\s\-\'\.♀♂éè]+#\d{3})', full_text, flags=re.MULTILINE)
    
    print(f"Found {len(pokemon_blocks)} potential blocks")
    
    for block in pokemon_blocks:
        if not block.strip() or len(block) < 100:
            continue
        pokemon = parse_pokemon_block(block)
        if pokemon and 'number' in pokemon and 'name' in pokemon and 'types' in pokemon:
            all_pokemon.append(pokemon)
    
    # Sort by number and deduplicate
    all_pokemon.sort(key=lambda x: x['number'])
    seen = set()
    unique_pokemon = []
    for p in all_pokemon:
        if p['number'] not in seen:
            seen.add(p['number'])
            unique_pokemon.append(p)
    
    print(f"Successfully parsed {len(unique_pokemon)} unique Pokemon")
    return unique_pokemon

if __name__ == '__main__':
    pokemon_data = extract_all_pokemon()
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(pokemon_data, f, ensure_ascii=False, indent=2)
    
    print(f"\nData saved to {OUTPUT_PATH}")
    
    if pokemon_data:
        print(f"\nFirst: #{pokemon_data[0]['number']} {pokemon_data[0]['name']}")
        print(f"Last: #{pokemon_data[-1]['number']} {pokemon_data[-1]['name']}")
        print(json.dumps(pokemon_data[0], ensure_ascii=False, indent=2))
