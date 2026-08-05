# Decisão: estado durável + vigia de turno (não é problema de escala)

**Data:** 2026-08-05 · **Status:** implementada (PR #47)

## Problema

Travamentos na mesa: Pokémon/NPC que não agem, batalhas que somem, demora
no primeiro clique. O mestre perguntou se a solução seria a arquitetura
clássica de escala (load balancer + 2 web servers + cache + DB
master/slave).

## Decisão: NÃO escalar — durabilidade e autonomia

A mesa tem ~5 pessoas; o gargalo nunca foi capacidade. E o app é
**single-process por design**: SocketIO sem message_queue, dicts de
batalha em memória, guards `_BATTLE_BUSY`/`_ECON_BUSY` e o
[[Decisoes/cache-de-processo-db|cache de processo]] — TUDO depende do
`-w 1`. Dois workers quebrariam broadcast, guards e cache de uma vez.
Master/slave adicionaria lag de replicação (HP voltando no combate) sem
ganho algum. **Se um dia escalar de verdade: Redis como message_queue +
estado de batalha movido pro banco + DB_CACHE=off, tudo junto.**

As causas reais (medidas):

1. Render free hiberna (~15 min): 1ª request 31,7s. Mitigação: `/ping`
   sem banco (acordar antes da sessão) — o mestre optou por seguir no
   plano grátis.
2. Restart apagava PvP/grupo/torneio (7 deploys num dia de sessão!).
3. O turno do selvagem 1v1 rodava num setTimeout NO NAVEGADOR do
   jogador — celular bloqueado = trava permanente.
4. Socket que caía nunca re-sincronizava.
5. `get_conn()` sem retry → cochilo do Neon virava 500.

## O que foi construído

- **💾 Batalhas duráveis**: `live_battles_{mesa}` no game_state (linha
  única por mesa, cache write-through de graça). Dirty-flag nos
  broadcasts + flush debounced (10s) no loop do vigia + flush no
  **SIGTERM** (o Render manda antes de todo deploy/hibernação).
  Restauração LAZY na primeira conexão (boot nunca falha por banco
  frio), TTL 6h. Custo: ~5,3 KB/batalha.
- **🛡️ Vigia de turno** (`_battle_watchdog`): background task gevent,
  tick 5s; age em turno de INIMIGO parado 25s+ (1v1/grupo/PvP-NPC).
  O 1v1 ganhou caminho server-side (`_wild_turn_server`) reusando
  `_npc_pick_move` + `_calc_wild_attack` + `process_turn_start`
  (dormindo perde o turno). A race antiga do auto-attack server-side
  não volta: relê estado fresco, respeita `_BATTLE_BUSY`, revalida o
  turno e usa token `turn_seq`/`_expect_seq` (jogada descartada se o
  cliente acordou no meio). Jogador humano nunca é forçado; modo manual
  só avisa o mestre (1x por turno). AUTO lido POR MESA (bug pego pelos
  testes: fora de request caía na mesa default).
- **🔌 Resync no reconnect**: cliente distingue reconexão e re-busca;
  servidor empurra estado no connect (PvP não tinha reidratação
  NENHUMA). `_groupBattleView = null` antes do render de resync — senão
  o diff de FX explodia animações falsas.
- **`_run_battle_action`**: núcleo extraído de handle_battle_action sem
  contexto de socket (current_user/emit/_tid → parâmetros). Extração
  mecânica validada pela suíte inteira ANTES de qualquer feature nova.

## Verificação que importa

Teste end-to-end do bug real: batalha 2v1 viva → SIGTERM no processo →
processo novo → batalha voltou com HP/rodada corretos. Stress 666/666.

## Regras de mesa derivadas

- Acordar o app 1-2 min antes da sessão (`/ping`).
- **Sem deploy com mesa ao vivo** — as batalhas agora sobrevivem, mas o
  reinício ainda custa ~30s de espera.
