# Recarga de sustain (dreno / cura instantânea)

**Data**: 09/07/2026 · **Pedido**: Junior (spec completa no chat)
**Problema**: golpes que recuperam HP na hora (Giga Drain, Recover, Roost…)
podiam ciclar todo turno — anulavam o desgaste da batalha e criavam lutas
intermináveis, principalmente contra tanques e em PvP.

## Decisão

Cooldown Inteligente na mesma filosofia da recarga por POW da Tabela Mestra:

| Recuperação | Critério | Recarga |
|---|---|---|
| Moderada | dreno com POW < 90 (Absorb 20, Mega Drain 40, Giga Drain 75, Drain Punch 75…) ou cura instantânea de ¼ | **1 rodada** |
| Elevada | dreno com POW ≥ 90 (Dream Eater 100, Bitter Blade 90…) ou cura de metade/total (Recover, Roost, Soft-Boiled, Rest, Wish…) | **2 rodadas** |

- **Detecção pela MECÂNICA, nunca por lista de nomes**: dano com `drain > 0`
  no dado canônico, ou efeito `heal_self` do motor de status. Move novo com a
  mesma mecânica entra sozinho na regra.
- **Combina com a recarga por POW pelo MAIOR valor**
  (`battle_math.v3_move_cooldown = max(pow_cd, drain_cd)`), espelhado 1:1 no
  `battle_math.js`.
- **Exceção**: cura GRADUAL (Leech Seed, Aqua Ring, Ingrain*, Leftovers,
  Grassy Terrain, Poison Heal…) fica de fora — já é balanceada por vir aos
  poucos. (*No nosso sistema Ingrain é cura instantânea de ¼ → recarga 1.)
- Bloqueio **não consome o turno** do jogador ("X ainda está em recarga.
  Aguarde N rodada(s)"); a IA de selvagens/NPCs evita golpes em recarga na
  escolha (`_npc_pick_move` filtra pelos cooldowns).

## Implementação (pontos de choque)

- `battle_math.v3_drain_cooldown / v3_heal_cooldown / v3_move_cooldown`
  (+ `V3_SUSTAIN_POW_HEAVY = 90`).
- `_v3_register_use` passa o drain canônico; `_calc_attack_core` anuncia o
  cooldown combinado ao cliente.
- `status_effects.process_status_move`: bloqueia heal_self em recarga e
  registra a recarga no `_v3` do lado (1 ação = 1 rodada decrementa as demais).
- `/api/process-status-move` anexa e PERSISTE o `_v3` da batalha ativa
  (payload novo `side: 'player'|'wild'`) — antes, cura de status em batalha
  selvagem não tinha estado de recarga nenhum no servidor.
- Cobertura nos 4 modos: selvagem (auto + manual do mestre), PvP, NPC, grupo.

## Validação

- Stress 396/396 (seção "Sustain/Recarga", 14 checks: valores da tabela,
  detecção canônica, usar→bloquear→destravar, Recover, exceção Leech Seed,
  IA evita recarga).
- `battle_sweep_v3` segue na janela 5-10 (cenários do sweep não usam dreno —
  a regra só encurta batalhas de stall).

Ver também: [[Decisoes/sistema-combate-v3]] · [[Bugs-Resolvidos/leech-seed-como-absorb]]
