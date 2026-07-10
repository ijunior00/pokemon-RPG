#!/usr/bin/env python3
"""Auditoria do sistema de evolução (read-only).

Varre server/data/pokemon.json e confere que TODA espécie que menciona
evolução tem um caminho funcional no jogo:
  1. evolução por nível pura (parse_level_evolution) com alvo existente; ou
  2. entrada em SPECIAL_EVOLUTIONS (pedra) com alvo existente.

Também flagga:
  - chaves de SPECIAL_EVOLUTIONS que não existem no banco (chave morta);
  - alvos de SPECIAL_EVOLUTIONS inexistentes;
  - espécies com 'evolve' no evolutionInfo sem NENHUM caminho (órfãs).

Exit 1 se houver qualquer problema fora da whitelist.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pokemon_scaling as scaling  # noqa: E402

# Casos conhecidos e aceitos (documentar o porquê):
KNOWN_MISSING = {
    # Lycanroc não existe no banco de espécies → Rockruff fica sem evolução
    # até a espécie ser adicionada (aí vira pedras Sun/Dusk/Moon).
    'rockruff',
}

DATA = os.path.join(os.path.dirname(__file__), '..', 'server', 'data', 'pokemon.json')


def main():
    db = json.load(open(DATA, encoding='utf-8'))
    by_name = {p['name'].strip().lower(): p for p in db}
    problems = []
    level_evos = []
    stone_only = []
    orphans = []

    for p in db:
        name = p['name'].strip().lower()
        info = p.get('evolutionInfo') or ''
        if 'evolve into' not in info.lower():
            continue

        target, evo_level = scaling.parse_level_evolution(info)
        special = scaling.SPECIAL_EVOLUTIONS.get(name)

        if target:
            tkey = target.lower()
            tkey = scaling.EVO_TARGET_ALIASES.get(tkey, tkey)
            if tkey not in by_name:
                problems.append(f"{p['name']}: alvo por nível '{target}' NÃO existe no banco")
            else:
                level_evos.append((p['name'], target, evo_level))
        if special:
            conds = special if isinstance(special, list) else [special]
            for c in conds:
                if c['into'].strip().lower() not in by_name:
                    problems.append(f"{p['name']}: alvo por pedra '{c['into']}' NÃO existe no banco")
            if not target:
                stone_only.append(p['name'])
        if not target and not special:
            if name in KNOWN_MISSING:
                print(f"⚠️  {p['name']}: sem caminho (whitelist — alvo inexistente no banco)")
            else:
                orphans.append(f"{p['name']}: '{info[:100]}…'")

    # Chaves mortas em SPECIAL_EVOLUTIONS
    for key in scaling.SPECIAL_EVOLUTIONS:
        if key not in by_name:
            problems.append(f"SPECIAL_EVOLUTIONS['{key}']: chave morta (espécie não existe no banco)")

    print(f"\n✅ Evoluções por nível parseadas: {len(level_evos)}")
    for n, t, lv in sorted(level_evos)[:10]:
        print(f"   {n} → {t} no nível {lv}")
    print(f"   … ({len(level_evos)} no total)")
    print(f"✅ Espécies só-pedra cobertas por SPECIAL_EVOLUTIONS: {len(stone_only)}")

    if orphans:
        print(f"\n❌ ÓRFÃS ({len(orphans)}) — mencionam evolução mas não têm caminho:")
        for o in orphans:
            print(f"   {o}")
    if problems:
        print(f"\n❌ PROBLEMAS ({len(problems)}):")
        for pr in problems:
            print(f"   {pr}")

    if orphans or problems:
        sys.exit(1)
    print("\n🎉 Auditoria OK: toda espécie que evolui tem caminho válido.")


if __name__ == '__main__':
    main()
