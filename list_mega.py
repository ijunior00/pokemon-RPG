import json
data = json.load(open(r'c:\Users\Barros-Roux\Desktop\RPG POKEMON\Pokémon 5e RPG\pokemon5e-app\server\data\mega_stones.json', 'r', encoding='utf-8'))

print(f"{'MEGA PEDRA':<22} {'POKÉMON':<15} {'HABILIDADE':<20} {'BÔNUS'}")
print("-" * 90)
for v in sorted(data.values(), key=lambda x: x['pokemon']):
    bonuses = v.get('bonuses', {})
    bonus_str = ', '.join([f"{k}:{val}" for k, val in bonuses.items()])
    types_str = f" Tipo:{'/'.join(v['newTypes'])}" if v.get('newTypes') else ''
    print(f"{v['stone']:<22} {v['pokemon']:<15} {v.get('ability','-'):<20} {bonus_str}{types_str}")
