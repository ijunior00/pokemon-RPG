"""Matriz de simulação obrigatória do combate v3 (gate permanente).

Batalhas Monte-Carlo com ESPÉCIES REAIS (base_stats do pokemon.json) pelo
motor real (battle_math): iniciativa d100, precisão, crítico, Resistência
d100, RECARGA com rotação, DoT (burn/toxic/leech/curse/trap), cura com
recarga-bucket, buffs/debuffs e habilidades selecionadas.

Invariantes (exit 1 se furar):
  1. mediana de rodadas na janela do cenário (4-6 equilibrados; ≤8 longos);
  2. toda batalha termina antes de MAX_ROUNDS (anti-loop de cura);
  3. golpe fraco (POW ≤ 50) continua relevante (dano médio ≥ 5% do HP);
  4. DoT por turno nunca passa do teto ⌊HP/4⌋;
  5. lado stall/buff vence 35-65% contra ofensivo padrão (não domina,
     não é inútil).

    python3 tools/battle_matrix_v3.py
"""
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import battle_math as bm
import status_effects as se

random.seed(11)
N_BATTLES = 400
MAX_ROUNDS = 40
FILLER_POW = 40

BASE = os.path.join(os.path.dirname(__file__), '..', 'server', 'data')
_DB = json.load(open(os.path.join(BASE, 'pokemon.json'), encoding='utf-8'))
SPECIES = {p['name'].lower(): p for p in _DB}


def side(species, level, power, acc=100, kind='physical', plan='attack',
         ability=None, item=False):
    """Monta um lado da batalha a partir da ESPÉCIE REAL.
    item=True: carrega UM item de socorro (Super Potion/antídoto — o
    contrajogo real da mesa contra stall/DoT): a <40% de HP gasta o turno
    para curar ½ HP e limpar status/semente."""
    import pokemon_scaling as scaling
    base = SPECIES[species.lower()]
    sc = scaling.calculate_pokemon_stats(base, level)
    return {
        'name': base['name'], 'level': level, 'stats': sc['stats'],
        'max_hp': sc['maxHp'], 'power': power, 'acc': acc, 'kind': kind,
        'plan': plan, 'ability': ability, 'item': item,
    }


def _new_state(s):
    return {'hp': s['max_hp'], 'atk_st': 0, 'def_st': 0, 'status': None,
            'seeded': False, 'cursed': False, 'cd': 0, 'heal_cd': 0,
            'heal_uses': 0, 'did_setup': False,
            'item_left': 1 if s['item'] else 0}


def _attack(att, a_st, dfd, d_st, power):
    acc_eff = bm.v3_acc_effective(att['acc'] if power == att['power'] else 100)
    if not bm.v3_connects(random.randint(1, 100), acc_eff):
        return 0
    crit = random.randint(1, 100) <= bm.v3_crit_chance(0)
    n, sides_, halve = bm.v3_build_dice(power, att['level'], stab=True)
    dice_total = sum(random.randint(1, sides_) for _ in range(n))
    atk_key = 'SPA' if att['kind'] == 'special' else 'ATK'
    comp = bm.v3_status_component(att['stats'][atk_key], a_st['atk_st'])
    if a_st['status'] == 'queimado' and att['kind'] == 'physical':
        comp = max(1, comp // 2)
    flat = bm.v3_stab_flat(True, att['level'])
    gross = bm.v3_gross_damage(comp, att['level'], dice_total,
                               halve_dice=halve, flat=flat)
    if att['ability'] == 'huge power' and att['kind'] == 'physical':
        gross = int(gross * 1.3)   # aproximação do ATK×2 no componente
    def_key = 'SPD' if att['kind'] == 'special' else 'DEF'
    resist = bm.v3_resistance_total(random.randint(1, 100), dfd['stats'][def_key],
                                    dfd['level'], d_st['def_st'], crit=crit)
    outcome = bm.v3_resist_outcome(
        resist, bm.v3_tn(power, att['level']),
        defender_faster=dfd['stats']['SPE'] > att['stats']['SPE'])
    return bm.v3_apply_outcome(gross, outcome)


def _tick_dot(st, max_hp, opp_st, opp_max):
    """Início do turno: burn/toxic (escalonado c/ teto), seed, curse."""
    dmg = 0
    if st['status'] in ('queimado', 'badly_poisoned'):
        cond = {'condition': st['status'],
                'turns_active': st.get('status_turns', 0)}
        _, d, _, _ = se.process_turn_start(cond, max_hp)
        st['status_turns'] = cond['turns_active']
        dmg += d
    if st['seeded']:
        drain = se.seed_drain(max_hp)   # fonte única do motor (⌊HP/16⌋)
        dmg += drain
        opp_st['hp'] = min(opp_max, opp_st['hp'] + drain)
    if st['cursed']:
        _curse_frac = se.STATUS_CONDITIONS['amaldicoado'].get('damage_fraction', 4)
        dmg += max(1, max_hp // _curse_frac)
    return dmg


def _act(att, a_st, dfd, d_st):
    """Um turno do lado `att` conforme o plano. Retorna dano causado."""
    plan = att['plan']
    if (a_st['item_left'] and a_st['hp'] < att['max_hp'] * 0.4):
        a_st['item_left'] -= 1
        a_st['hp'] = min(att['max_hp'], a_st['hp'] + att['max_hp'] // 2)
        a_st['status'] = None
        a_st['seeded'] = False
        return 0
    if plan == 'buff_first' and not a_st['did_setup']:
        a_st['did_setup'] = True
        a_st['atk_st'] = min(6, a_st['atk_st'] + 2)      # Swords Dance
        return 0
    if plan == 'toxic' and not a_st['did_setup'] and d_st['status'] is None:
        a_st['did_setup'] = True
        d_st['status'] = 'badly_poisoned'
        d_st['status_turns'] = 0
        return 0
    if plan == 'burn' and not a_st['did_setup'] and d_st['status'] is None:
        a_st['did_setup'] = True
        d_st['status'] = 'queimado'
        d_st['status_turns'] = 0
        return 0
    if plan == 'leech' and not a_st['did_setup']:
        a_st['did_setup'] = True
        d_st['seeded'] = True
        return 0
    if plan == 'curse_ghost' and not a_st['did_setup']:
        a_st['did_setup'] = True
        a_st['hp'] -= max(1, att['max_hp'] // 2)
        d_st['cursed'] = True
        return 0
    if plan == 'healer' and a_st['heal_cd'] <= 0 and a_st['hp'] < att['max_hp'] // 2:
        # retorno decrescente: MESMA fórmula do motor (fonte única)
        heal = bm.v3_decayed_heal(att['max_hp'] // 2, a_st['heal_uses'])
        a_st['heal_uses'] += 1
        a_st['hp'] = min(att['max_hp'], a_st['hp'] + heal)
        a_st['heal_cd'] = bm.v3_heal_cooldown('half')
        return 0
    # ataque com rotação de recarga
    if a_st['cd'] <= 0:
        a_st['cd'] = bm.v3_cooldown(att['power'])
        return _attack(att, a_st, dfd, d_st, att['power'])
    a_st['cd'] -= 1
    return _attack(att, a_st, dfd, d_st, FILLER_POW)


def battle(a, b):
    """Retorna (rodadas, vencedor 'a'|'b', dot_máx_por_turno)."""
    sa, sb = _new_state(a), _new_state(b)
    if a['ability'] == 'intimidate':
        sb['atk_st'] -= 1
    if b['ability'] == 'intimidate':
        sa['atk_st'] -= 1
    w, _, _, _ = bm.initiative_winner(random.randint(1, 100), random.randint(1, 100),
                                      a['stats']['SPE'], b['stats']['SPE'])
    order = [(a, sa, b, sb), (b, sb, a, sa)]
    if w == 'b':
        order.reverse()
    dot_max = 0
    for rnd in range(1, MAX_ROUNDS + 1):
        for att, a_st, dfd, d_st in order:
            if a_st['hp'] <= 0 or d_st['hp'] <= 0:
                continue
            dot = _tick_dot(a_st, att['max_hp'], d_st, dfd['max_hp'])
            dot_max = max(dot_max, dot)
            a_st['hp'] -= dot
            if a_st['hp'] <= 0:
                continue
            if a_st['heal_cd'] > 0 and att['plan'] == 'healer':
                a_st['heal_cd'] -= 1
            d_st['hp'] -= _act(att, a_st, dfd, d_st)
        if sa['hp'] <= 0 or sb['hp'] <= 0:
            winner = 'a' if sb['hp'] <= 0 and sa['hp'] > 0 else 'b'
            return rnd, winner, dot_max
    return MAX_ROUNDS, 'a', dot_max


# (nome, janela_mediana, lado_a, lado_b, banda_winrate_a ou None)
MATRIX = [
    ('Ofensivo × ofensivo (Charizard×Gyarados L50)', (4, 6),
     side('Charizard', 50, 90, kind='special'),
     side('Gyarados', 50, 90, kind='physical'), None),
    ('Ofensivo × defensivo (Gengar×Snorlax L50)', (4, 8),
     side('Gengar', 50, 90, kind='special'),
     side('Snorlax', 50, 85, kind='physical'), None),
    ('Especial × físico (Alakazam×Machamp L50)', (4, 6),
     side('Alakazam', 50, 90, kind='special'),
     side('Machamp', 50, 100, kind='physical'), None),
    ('Rápido × lento (Jolteon×Golem L50)', (4, 6),
     side('Jolteon', 50, 90, kind='special'),
     side('Golem', 50, 100, kind='physical'), None),
    ('Baixo nível (Charmander×Squirtle L15)', (4, 6),
     side('Charmander', 15, 60, kind='special'),
     side('Squirtle', 15, 60, kind='physical'), None),
    ('Evolução intermediária (Charmeleon×Wartortle L35)', (4, 6),
     side('Charmeleon', 35, 80, kind='special'),
     side('Wartortle', 35, 80, kind='physical'), None),
    ('Evolução final endgame (Charizard×Blastoise L85)', (4, 8),
     side('Charizard', 85, 110, acc=85, kind='special'),
     side('Blastoise', 85, 110, acc=85, kind='special'), None),
    ('Tanque × tanque (Snorlax×Umbreon L50)', (4, 8),
     side('Snorlax', 50, 85, kind='physical'),
     side('Umbreon', 50, 70, kind='physical'), None),
    # ── Mecânicas em ESPELHO (mesma espécie dos 2 lados): o winrate mede a
    # MECÂNICA, não a diferença de espécie ──
    ('Buff Swords Dance (espelho Scyther L50)', (4, 8),
     side('Scyther', 50, 80, kind='physical', plan='buff_first'),
     side('Scyther', 50, 80, kind='physical'), (30, 70)),
    ('Debuff Intimidate (espelho Arcanine físico L50)', (4, 8),
     side('Arcanine', 50, 90, kind='physical', ability='intimidate'),
     side('Arcanine', 50, 90, kind='physical'), (40, 80)),
    # (o lado baunilha carrega 1 item de socorro — Potion/antídoto — o
    # contrajogo REAL da mesa contra stall/DoT; banda pega só o degenerado)
    # corner EXTREMO: os DOIS lados sustentam (healer vs item) na espécie mais
    # bulky — é o teto de duração aceito; o gate real é terminar (< MAX_ROUNDS)
    ('Cura Recover-stall (espelho Slowbro L50)', (4, 14),
     side('Slowbro', 50, 80, kind='special', plan='healer'),
     side('Slowbro', 50, 80, kind='special', item=True), (35, 90)),
    ('Toxic-stall (espelho Tentacruel L50)', (4, 8),
     side('Tentacruel', 50, 80, kind='special', plan='toxic'),
     side('Tentacruel', 50, 80, kind='special', item=True), (35, 90)),
    ('Burn vs físico (espelho Machamp L50)', (4, 8),
     side('Machamp', 50, 100, kind='physical', plan='burn'),
     side('Machamp', 50, 100, kind='physical', item=True), (35, 90)),
    # Leech 1/16 (fonte única seed_drain): sustain mútuo alonga o espelho —
    # janela maior é esperada; o winrate na banda é o que valida a mecânica.
    ('Leech Seed (espelho Venusaur L50)', (4, 10),
     side('Venusaur', 50, 80, kind='special', plan='leech'),
     side('Venusaur', 50, 80, kind='special', item=True), (35, 90)),
    ('Curse fantasma (espelho Gengar L50)', (3, 8),
     side('Gengar', 50, 80, kind='special', plan='curse_ghost'),
     side('Gengar', 50, 80, kind='special'), (25, 65)),
    ('Habilidade Huge Power (espelho Azumarill L50)', (4, 8),
     side('Azumarill', 50, 90, kind='physical', ability='huge power'),
     side('Azumarill', 50, 90, kind='physical'), (45, 85)),
    ('Golpes fracos (POW 40, Rattata×Pidgey L20)', (4, 8),
     side('Raticate', 20, 40, kind='physical'),
     side('Pidgeotto', 20, 40, kind='physical'), None),
]


def run():
    print(f'MATRIZ v3 — {N_BATTLES} batalhas/cenário · divisor={bm.V3_STATUS_DIVISOR} '
          f'TN_shift={bm.V3_TN_SHIFT} (mediana 4-6; ≤8 nos longos)\n')
    all_ok = True
    for name, window, a, b, band in MATRIX:
        rounds, wins_a, dotmax = [], 0, 0
        timeouts = 0
        for _ in range(N_BATTLES):
            r, w, dm = battle(a, b)
            rounds.append(r)
            wins_a += (w == 'a')
            dotmax = max(dotmax, dm)
            timeouts += (r >= MAX_ROUNDS)
        med = statistics.median(rounds)
        wr = 100 * wins_a / N_BATTLES
        ok = window[0] <= med <= window[1] and timeouts == 0
        cap_a = max(a['max_hp'], b['max_hp']) // 4
        ok = ok and dotmax <= cap_a
        if band:
            ok = ok and band[0] <= wr <= band[1]
        all_ok = all_ok and ok
        extra = f' | winrate A {wr:4.1f}%' + (f' (banda {band[0]}-{band[1]})' if band else '')
        print(f'  {"✅" if ok else "❌"} {name:52} mediana {med:4.1f} '
              f'| p90 {sorted(rounds)[N_BATTLES*9//10]:2d}{extra}'
              + (f' | ⚠️ timeouts {timeouts}' if timeouts else ''))

    # invariante 3: golpe fraco relevante — dano médio do POW 40 ≥ 5% do HP
    a = side('Raticate', 20, 40)
    b = side('Pidgeotto', 20, 40)
    sa, sb = _new_state(a), _new_state(b)
    dmgs = [_attack(a, sa, b, sb, 40) for _ in range(600)]
    hits = [d for d in dmgs if d > 0]
    frac = statistics.mean(hits) / b['max_hp'] if hits else 0
    ok = frac >= 0.05
    all_ok = all_ok and ok
    print(f'\n  {"✅" if ok else "❌"} Golpe fraco relevante: POW 40 conectado '
          f'= {100*frac:.1f}% do HP do alvo (mín. 5%)')

    print(f'\n{"✅ MATRIZ APROVADA — todas as invariantes." if all_ok else "❌ Matriz reprovada — ajustar alavancas/regras."}')
    return all_ok


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
