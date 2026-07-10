# Postmortem: evolução por nível quase nunca disparava (e Pikachu evoluía de graça)

**Resolvido em:** 2026-07-10 · PR #23

## Sintomas

- Pokémon atingia o nível de evoluir vencendo batalhas e… nada acontecia.
- Ninguém além do dono via a evolução quando ela acontecia.
- Pikachu (e toda espécie de pedra) evoluía **sem pedra** via /master/xp.

## Causas raiz (três, empilhadas)

1. **Gatilho na escala errada**: `check_and_evolve_pokemon` comparava o
   `level N` do `evolutionInfo` com o nível do **TREINADOR**. O fim de
   batalha só sobe o nível do POKÉMON (e no cliente!), então o gatilho
   pós-batalha quase nunca via a condição. Além disso o `N` do banco é
   escala 5e (= canon/5) — "Ivysaur at level 3" significava canon 15/16, e
   nenhum código fazia essa conversão (os dados de GOLPES já usavam ×5).
2. **Regex ingênuo**: `evolve into X at level N` casava também os ramos
   `"...at level 8 and above with the help of a Thunder Stone"` — toda
   espécie de pedra tinha uma evolução por nível grátis escondida. E ramos
   com `loyalty` idem.
3. **Loop de XP client-side**: `awardPokemonBattleXP` (player.js) buscava o
   XP, somava no navegador, salvava o time e ENTÃO pedia a evolução — duas
   escritas concorrentes, tabela de XP duplicada e zero broadcast para a
   mesa. `pokemon_evolved` só ia para `master_{tid}` e nenhum cliente abria
   overlay ao recebê-lo.

## Correção

- Servidor autoritativo: `apply_battle_rewards` no `end_encounter` (XP +
  level-up + battle_wins por índice + evolução, um save só).
- `parse_level_evolution` (pokemon_scaling): pula ramos com
  `with the help`/`loyalty`, limiar = `N×5`, ramo separado por `.`/`or`
  (vírgula sozinha não separa — pegadinha do "…, only if its Loyalty…").
- Broadcast `evolution_focus` para `players_{tid}` + `master_{tid}` → todas
  as telas rodam o overlay (`showEvolutionFocus` em app.js, com shiny).
- `tools/audit_evolutions.py` fecha o ciclo: varre as 370 espécies com
  evolutionInfo e falha se alguma ficar sem caminho — foi ele que achou 13
  órfãs extras (Bonsly, Wurmple, Skitty…) e o evolutionInfo do Volcanion
  com texto de OUTRA espécie (Alolan Rattata — dado corrompido na fonte).

## Lições

- Dados de terceiros (pokemon5e) têm escala própria — confirmar a escala
  numérica ANTES de comparar (a pista estava no ×5 dos golpes).
- Regex sobre texto em inglês precisa tratar o RESTO da frase, não só o
  match: condições vêm depois ("with the help of…", "only if…").
- Auditoria automatizada de cobertura (toda espécie tem caminho) pega o que
  a revisão manual nunca pegaria — 13 órfãs em 370.
