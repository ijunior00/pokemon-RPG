"""
Motor de BATALHA EM DUPLA (caçada em grupo) — server-authoritative.

Dois jogadores (aliados) enfrentam juntos 1 selvagem forte (2v1) ou 2 selvagens
(2v2). O servidor é a fonte da verdade: guarda todos os combatentes, a ordem de
iniciativa e o HP. Os clientes só renderizam o estado e enviam a ação no seu turno.

O dano é calculado em app.py (que tem os helpers de combate) e aplicado aqui via
`apply_damage` — este módulo não importa app.py para evitar dependência circular.
"""
import random
import uuid


def _poke_hp(p):
    hp = p.get('currentHp')
    return hp if isinstance(hp, (int, float)) else p.get('maxHp', 20)


def _init_roll(pokemon):
    # Iniciativa v3 (d100): d100 + SPE_efetivo + Tática×5 do treinador.
    # Devolve (total, spe_eff) — o SPE desempata na ordenação. A regra de
    # upset (≥96 vs ≤5) não se aplica aqui (só faz sentido em duelo 1v1).
    import battle_math as bm
    import status_effects as effects
    spe = effects.effective_stat(pokemon, 'SPE') if isinstance(pokemon, dict) else 10
    tatica = int(pokemon.get('trainer_init_bonus') or 0) if isinstance(pokemon, dict) else 0
    return (random.randint(1, 100) + bm.initiative_bonus(spe)
            + bm.INIT_EXTRA_STEP * tatica, spe)


def build_battle(allies, wilds, hunt_mode='normal', route_id=None, table_id=None):
    """Monta uma batalha em grupo.

    allies: lista de {player_id, name, pokemon}  (Pokémon ativo de cada jogador)
    wilds:  lista de {pokemon, level, moves}
    Retorna o dict da batalha.
    """
    combatants = {}
    order_pairs = []  # (init, cid)

    import status_effects as effects
    for i, a in enumerate(allies):
        poke = dict(a['pokemon'])
        effects.new_battle_reset([poke])   # batalha nova: heal_uses/_weather zeram
        maxhp = int(poke.get('maxHp') or poke.get('hp') or 20)
        curhp = int(_poke_hp(poke)) if _poke_hp(poke) else maxhp
        cid = f'a{i}'
        init, init_spe = _init_roll(poke)
        combatants[cid] = {
            'cid': cid, 'side': 'ally', 'name': a.get('name') or poke.get('name', 'Aliado'),
            'trainer_name': a.get('name', ''),
            'player_id': str(a['player_id']),
            'pokemon': poke,
            'moves': list(poke.get('moves') or poke.get('startingMoves') or ['Tackle'])[:4],
            'hp': max(0, curhp), 'maxHp': maxhp,
            'status': None, 'fainted': curhp <= 0, 'init': init,
        }
        order_pairs.append((init, init_spe, cid))

    for i, w in enumerate(wilds):
        poke = dict(w['pokemon'])
        maxhp = int(poke.get('maxHp') or poke.get('hp') or 20)
        cid = f'w{i}'
        init, init_spe = _init_roll(poke)
        combatants[cid] = {
            'cid': cid, 'side': 'wild', 'name': poke.get('name', 'Selvagem'),
            'trainer_name': '',
            'player_id': None,
            'pokemon': poke,
            'level': int(w.get('level') or poke.get('level') or 1),
            'moves': list(w.get('moves') or poke.get('startingMoves') or ['Tackle'])[:4],
            'hp': maxhp, 'maxHp': maxhp,
            'status': None, 'fainted': False, 'init': init,
            'is_shiny': bool(poke.get('is_shiny')),
        }
        order_pairs.append((init, init_spe, cid))

    # Ordem de iniciativa: maior total primeiro; desempate por SPE_eff, depois aleatório
    order_pairs.sort(key=lambda t: (t[0], t[1], random.random()), reverse=True)
    order = [cid for _, _, cid in order_pairs]

    battle = {
        'id': uuid.uuid4().hex[:12],
        'mode': f'{len(allies)}v{len(wilds)}',   # 2v1, 2v2, 1v2 (emboscada)...
        'table_id': table_id,
        'combatants': combatants,
        'order': order,
        'turn_idx': 0,
        'round': 1,
        'phase': 'active',
        'winner': None,
        'log': [],
        'route_id': route_id,
        'hunt_mode': hunt_mode,
        'player_ids': [str(a['player_id']) for a in allies],
    }
    # Garante que o turno começe num combatente vivo
    _skip_to_alive(battle)
    battle['log'].append({'type': 'start',
                          'message': f'⚔️ Batalha em dupla iniciada! Ordem: '
                                     + ', '.join(combatants[c]['name'] for c in order)})
    return battle


def current_cid(battle):
    if battle['phase'] != 'active':
        return None
    return battle['order'][battle['turn_idx'] % len(battle['order'])]


def current_combatant(battle):
    cid = current_cid(battle)
    return battle['combatants'][cid] if cid else None


def alive_cids(battle, side):
    return [c['cid'] for c in battle['combatants'].values()
            if c['side'] == side and not c['fainted']]


def _skip_to_alive(battle):
    """Avança turn_idx até cair num combatente vivo (segurança)."""
    n = len(battle['order'])
    for _ in range(n + 1):
        cid = battle['order'][battle['turn_idx'] % n]
        if not battle['combatants'][cid]['fainted']:
            return
        battle['turn_idx'] += 1


def advance_turn(battle):
    """Passa para o próximo combatente vivo; incrementa round ao dar a volta."""
    if battle['phase'] != 'active':
        return
    n = len(battle['order'])
    start_pos = battle['turn_idx'] % n
    for step in range(1, n + 1):
        battle['turn_idx'] += 1
        pos = battle['turn_idx'] % n
        if pos <= start_pos:
            battle['round'] += 1
            start_pos = -1  # só conta a virada uma vez
        if not battle['combatants'][battle['order'][pos]]['fainted']:
            return


def _check_over(battle):
    if not alive_cids(battle, 'wild'):
        battle['phase'] = 'finished'
        battle['winner'] = 'ally'
        battle['log'].append({'type': 'end', 'winner': 'ally',
                              'message': '🎉 Os selvagens foram derrotados! Vitória da dupla!'})
        return True
    if not alive_cids(battle, 'ally'):
        battle['phase'] = 'finished'
        battle['winner'] = 'wild'
        battle['log'].append({'type': 'end', 'winner': 'wild',
                              'message': '💀 A dupla foi derrotada pelos selvagens!'})
        return True
    return False


def apply_damage(battle, attacker_cid, target_cid, damage, move_name='', message='', hit=True):
    """Aplica dano (calculado em app.py) do atacante no alvo. Avança o turno.

    Retorna dict de evento com o que aconteceu.
    """
    attacker = battle['combatants'].get(attacker_cid)
    target = battle['combatants'].get(target_cid)
    if not attacker or not target:
        return {'ok': False, 'error': 'combatente inválido'}

    fainted = False
    if hit and damage > 0:
        target['hp'] = max(0, target['hp'] - int(damage))
        target['pokemon']['currentHp'] = target['hp']
        if target['hp'] <= 0:
            target['fainted'] = True
            fainted = True
            # limpa buffs/debuffs acumulados ao desmaiar
            p = target.get('pokemon')
            if isinstance(p, dict):
                p['stat_stages'] = {k: 0 for k in ('ATK', 'DEF', 'SPA', 'SPD', 'SPE', 'AC', 'attack_roll')}

    battle['log'].append({
        'type': 'attack', 'attacker': attacker_cid, 'attacker_name': attacker['name'],
        'target': target_cid, 'target_name': target['name'],
        'move': move_name, 'damage': int(damage) if hit else 0, 'hit': hit,
        'message': message, 'target_hp': target['hp'], 'target_max_hp': target['maxHp'],
        'fainted': fainted,
    })
    if fainted:
        battle['log'].append({'type': 'faint', 'cid': target_cid, 'name': target['name'],
                              'message': f"{target['name']} desmaiou!"})

    over = _check_over(battle)
    if not over:
        advance_turn(battle)
    return {'ok': True, 'fainted': fainted, 'over': over, 'winner': battle.get('winner')}


def choose_wild_target(battle, wild_cid):
    """Alvo do selvagem: um aliado vivo aleatório."""
    allies = alive_cids(battle, 'ally')
    return random.choice(allies) if allies else None


def state_view(battle):
    """Estado público (co-op: todos veem tudo)."""
    cur = current_cid(battle)
    combatants = []
    for cid in battle['order']:
        c = battle['combatants'][cid]
        p = c['pokemon']
        combatants.append({
            'cid': cid, 'side': c['side'], 'name': c['name'],
            'player_id': c.get('player_id'),
            'number': p.get('number'), 'types': p.get('types', []),
            'level': p.get('level') or c.get('level'),
            'hp': c['hp'], 'maxHp': c['maxHp'], 'status': c['status'],
            'fainted': c['fainted'], 'init': c['init'],
            'moves': c['moves'], 'is_shiny': bool(p.get('is_shiny')),
            'stat_stages': p.get('stat_stages'),
            'defense_mode': p.get('defense_mode', 1),
        })
    return {
        'id': battle['id'], 'mode': battle['mode'], 'phase': battle['phase'],
        'ambush': bool(battle.get('ambush')),
        'turn_cid': cur, 'round': battle['round'], 'winner': battle.get('winner'),
        'combatants': combatants,
        'player_ids': battle['player_ids'],
        'log': battle['log'][-25:],
    }
