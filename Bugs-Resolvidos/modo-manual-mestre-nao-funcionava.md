# Modo manual do mestre não funcionava (wild/NPC)

**Data**: 09/07/2026 · **Reportado por**: Junior (print do celular)
**Sintoma**: com o toggle "Wild/NPC atacam sozinhos" DESLIGADO, o mestre não
conseguia conduzir o Pokémon selvagem nem os NPCs — os controles apareciam,
mas clicar não tinha efeito.

## Causa raiz (três camadas de podridão)

1. **O cliente do JOGADOR auto-jogava o selvagem incondicionalmente.**
   `player.js` disparava `wildPokemonAutoAttack()` em `initiative_result` e em
   todo `battle_update` com `turn === 'wild'` — sem consultar o modo. E não
   tinha COMO consultar: a flag `wild_auto` não era emitida em nenhum payload
   do encontro 1v1 (a batalha em grupo já fazia certo via `view.wild_auto`).
   O disparo do jogador (~1,2s) consumia o turno antes de o mestre clicar —
   a validação de turno do servidor então descartava a ação do mestre.
2. **O caminho manual do mestre ficou para trás na migração v3.**
   `masterAttack()` ainda calculava dano NO CLIENTE com o motor v2
   (d20/accuracy/`BattleMath.damage`) e o servidor confiava no valor, porque o
   recálculo v3 (`_calc_wild_attack`) era pulado quando `role == 'master'`.
3. **NPCs ignoravam o toggle**: `handle_npc_turn` (IA) rodava sempre.
   Bônus: `wildAutoMode` no master.js nascia `true` no boot mesmo com o
   checkbox persistido OFF — após um reload o painel manual nunca aparecia.

## Correção

- **Servidor é o guardião**: com AUTO OFF, `battle_action` de selvagem vinda
  de um JOGADOR é descartada (`action_blocked {manual_wild}`); o ataque do
  selvagem é SEMPRE recalculado no v3, inclusive quando o mestre conduz
  (mestre só escolhe o golpe — status do selvagem também passa pelo motor).
- `wild_auto` agora viaja em `initiative_result` e `battle_update`;
  `set_auto_mode` re-emite `auto_mode_changed` para a mesa (vale no meio da
  batalha). Cliente do jogador gateia o auto-attack e mostra "⏳ Aguardando o
  Mestre…".
- `handle_npc_turn(forced=False)`: IA não age em modo manual; avisa o mestre
  (`npc_awaiting_master`) e o "Forçar Ação" passa `forced=True`.

## Lições

- **Toda migração de motor precisa de um grep pelos CAMINHOS SECUNDÁRIOS**
  (mestre/NPC/admin). O v3 cobriu o fluxo principal e os testes só exercitavam
  o modo AUTO — o caminho manual ficou v2 por meses sem ninguém notar.
- **Flag de servidor que o cliente precisa respeitar tem que VIAJAR no
  payload** — o gate no cliente é UX; o gate no servidor é a regra.
- Teste novo no stress (seção "4b. Modo manual") cobre: bloqueio da ação do
  jogador, recálculo v3 do golpe do mestre, `wild_auto` nos payloads, NPC
  aguardando mestre + Forçar Ação.

Ver também: [[Decisoes/sistema-combate-v3]] · [[Sistemas/combate]]
