"""Extract all Moves from the Pokemon 5e Rulebook into JSON."""
import fitz
import json
import re
import os

PDF_PATH = r'c:\Users\Barros-Roux\Desktop\RPG POKEMON\Pokémon 5e RPG\Pokémon 5e - Livro de Regras Gen 1-7.pdf'
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'server', 'data', 'moves.json')

def extract_moves():
    doc = fitz.open(PDF_PATH)
    
    # Moves section starts at page 38 (index) and goes to around page 135
    full_text = ""
    for i in range(38, 136):
        full_text += doc[i].get_text() + "\n"
    
    # Clean trailing spaces
    lines = [l.strip() for l in full_text.split('\n')]
    full_text = '\n'.join(lines)
    
    # Split into move blocks - each move starts with Name (Translation) followed by Tipo:
    blocks = re.split(r'\n(?=[A-Z][\w\s\-\'\.:]+\([^)]+\)\nTipo:)', full_text)
    
    moves = {}
    
    for block in blocks:
        if not block.strip() or 'Tipo:' not in block:
            continue
        
        lines = block.strip().split('\n')
        if len(lines) < 5:
            continue
        
        # Parse move name from first line
        name_match = re.match(r'^([A-Z][\w\s\-\'\.:]+?)\s*\(', lines[0])
        if not name_match:
            continue
        
        move_name = name_match.group(1).strip()
        move = {'name': move_name}
        
        # Join all text for regex
        block_text = '\n'.join(lines)
        
        # Type
        type_match = re.search(r'Tipo:\s*(\w+)', block_text)
        if type_match:
            move['type'] = type_match.group(1)
        
        # Move Power
        power_match = re.search(r'Poder do Move:\s*(.+)', block_text)
        if power_match:
            move['power'] = power_match.group(1).strip()
        
        # Execution time
        time_match = re.search(r'Tempo de Execução:\s*(.+)', block_text)
        if time_match:
            move['time'] = time_match.group(1).strip()
        
        # PP
        pp_match = re.search(r'PP:\s*(\d+)', block_text)
        if pp_match:
            move['pp'] = int(pp_match.group(1))
        
        # Duration
        dur_match = re.search(r'Duração:\s*(.+)', block_text)
        if dur_match:
            move['duration'] = dur_match.group(1).strip()
        
        # Range
        range_match = re.search(r'Alcance:\s*(.+)', block_text)
        if range_match:
            move['range'] = range_match.group(1).strip()
        
        # Description - everything after "Descrição:" until "Níveis Superiores:" or end
        desc_match = re.search(r'Descrição:\s*(.+?)(?=Níveis Superiores:|$)', block_text, re.DOTALL)
        if desc_match:
            move['description'] = ' '.join(desc_match.group(1).strip().split())
        
        # Higher levels
        higher_match = re.search(r'Níveis Superiores:\s*(.+?)$', block_text, re.DOTALL)
        if higher_match:
            move['higherLevels'] = ' '.join(higher_match.group(1).strip().split())
        
        # Extract base damage dice
        damage_match = re.search(r'(\d+d\d+)\s*[\+\s]*MOVE', move.get('description', ''))
        if damage_match:
            move['baseDamage'] = damage_match.group(1)
        
        # Determine attack type
        desc_lower = move.get('description', '').lower()
        if 'corpo a corpo' in desc_lower:
            move['attackType'] = 'melee'
        elif 'distância' in desc_lower or 'à distância' in desc_lower:
            move['attackType'] = 'ranged'
        
        # Check for save
        save_match = re.search(r'teste de (\w+)', desc_lower)
        if save_match and 'attackType' not in move:
            move['saveType'] = save_match.group(1).upper()
        
        if move_name and 'type' in move:
            moves[move_name] = move
    
    print(f"Extracted {len(moves)} moves")
    return moves

if __name__ == '__main__':
    moves_data = extract_moves()
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(moves_data, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {OUTPUT_PATH}")
    
    # Print samples
    samples = ['Aerial Ace', 'Thunderbolt', 'Flamethrower', 'Confusion', 'Thunder Wave']
    for s in samples:
        if s in moves_data:
            print(f"\n{s}: {json.dumps(moves_data[s], ensure_ascii=False)[:200]}")
