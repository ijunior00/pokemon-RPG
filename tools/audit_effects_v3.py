#!/usr/bin/env python3
"""Auditoria de FIDELIDADE dos efeitos secundários (read-only).

Cruza três fontes:
  1. server/data/canonical_moves.json — mecânica bruta do PokeAPI
     (ailment/ailment_chance/stat_changes/stat_chance/drain/healing/
     flinch_chance/priority);
  2. server/data/move_effects.json — overlay estruturado curado;
  3. status_effects.MOVE_STATUS_EFFECTS — tabela on-hit do motor.

Lista divergências mecânicas: golpes com efeito canônico que o motor não
conhece (status on-hit, stat drop on-hit, flinch) e moves de status com
stat_changes canônicos sem entrada estruturada. Uso:

    python3 tools/audit_effects_v3.py            # relatório
    python3 tools/audit_effects_v3.py --strict   # exit 1 se houver faltas
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import status_effects as se  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), '..', 'server', 'data')
AILMENT_MAP = {
    'paralysis': 'paralisado', 'burn': 'queimado', 'poison': 'badly_poisoned',
    'freeze': 'congelado', 'sleep': 'dormindo', 'confusion': 'confuso',
    'flinch': 'atordoado', 'trap': 'trapped', 'leech-seed': 'seeded',
}


def main():
    strict = '--strict' in sys.argv
    canon = json.load(open(os.path.join(BASE, 'canonical_moves.json'), encoding='utf-8'))
    mfx = json.load(open(os.path.join(BASE, 'move_effects.json'), encoding='utf-8'))
    moves_local = json.load(open(os.path.join(BASE, 'moves.json'), encoding='utf-8'))
    local_names = {(m.get('name') or n).strip().lower()
                   for n, m in (moves_local.items() if isinstance(moves_local, dict)
                                else ((x.get('name'), x) for x in moves_local))}

    def in_game(identifier, entry):
        name = (entry.get('name') or identifier.replace('-', ' ')).strip().lower()
        return name if name in local_names else None

    # tabela do motor é chaveada por nome capitalizado ('Wrap') — normaliza
    motor_onhit = {k.strip().lower() for k in se.MOVE_STATUS_EFFECTS}

    missing_onhit, missing_flinch, missing_stat_status = [], [], []
    statdrop_engine = 0   # stat_changes canônicos: o motor aplica direto
                          # (_calc_attack_core lê stat_changes/stat_chance)

    for ident, c in canon.items():
        name = in_game(ident, c)
        if not name:
            continue
        has_mfx = name in mfx and mfx[name]
        onhit = (mfx.get(name) or {}).get('on_hit') if has_mfx else None
        mfx_type = ((mfx.get(name) or {}).get('effect') or {}).get('type') if has_mfx else None
        in_motor = (name in motor_onhit or bool(onhit)
                    or mfx_type == 'inflict_status')
        is_damage = (c.get('category') in ('physical', 'special')
                     or (c.get('power') or 0) > 0)

        # 1. golpe de DANO com ailment canônico (chance > 0) sem on-hit no motor
        ail = (c.get('ailment') or '').strip()
        chance = int(c.get('ailment_chance') or 0)
        if is_damage and ail in AILMENT_MAP and chance > 0 and not in_motor:
            missing_onhit.append((name, ail, chance))

        # 2. stat_changes canônicos de golpes de DANO: cobertos pelo motor
        # (aplicados data-driven em _calc_attack_core) — só conta
        if is_damage and (c.get('stat_changes') or []) and int(c.get('stat_chance') or 0):
            statdrop_engine += 1

        # 3. flinch canônico sem efeito
        fl = int(c.get('flinch_chance') or 0)
        if is_damage and fl > 0 and not in_motor:
            missing_flinch.append((name, fl))

        # 4. move de STATUS com stat_changes canônicos sem entrada estruturada
        schanges = c.get('stat_changes') or []
        if not is_damage and schanges and not has_mfx:
            detected = se.auto_detect_move_effect({'name': name, 'category': 'status'})
            if not detected or detected.get('type') not in (
                    'buff_self', 'debuff_target', 'terrain', 'weather'):
                missing_stat_status.append((name, schanges))

    def show(title, items, fmt):
        print(f'\n{"❌" if items else "✅"} {title}: {len(items)}')
        for it in items[:15]:
            print(f'   {fmt(it)}')
        if len(items) > 15:
            print(f'   … (+{len(items) - 15})')

    show('Dano com status canônico on-hit SEM efeito no motor', missing_onhit,
         lambda i: f'{i[0]} → {i[1]} {i[2]}%')
    show('Flinch canônico SEM efeito', missing_flinch,
         lambda i: f'{i[0]} → flinch {i[1]}%')
    show('Status com stat_changes canônicos SEM entrada estruturada',
         missing_stat_status, lambda i: f'{i[0]} → {i[1]}')
    print(f'\nℹ️  stat_changes canônicos de golpes de dano aplicados pelo motor: '
          f'{statdrop_engine} moves (data-driven em _calc_attack_core)')

    total = (len(missing_onhit) + len(missing_flinch)
             + len(missing_stat_status))
    print(f'\n{"🎉 Zero divergências." if total == 0 else f"Total de divergências: {total}"}')
    if strict and total:
        sys.exit(1)


if __name__ == '__main__':
    main()
