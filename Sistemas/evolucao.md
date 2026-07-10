# Sistema de evolução

Como um Pokémon evolui no jogo (pós-revisão de 2026-07-10, PR #23). Só
existem **dois caminhos**: nível e pedra. Troca, amizade, golpe, stat check e
hora do dia **não existem** — tudo virou pedra ([[Decisoes/evolucao-tudo-pedra]]).

## Por nível (do PRÓPRIO Pokémon)

- Fonte: string `evolutionInfo` do `server/data/pokemon.json`, parseada por
  `pokemon_scaling.parse_level_evolution`.
- **Escala**: o `level N` do banco é escala 5e = canon/5. Limiar real =
  `N × EVO_LEVEL_SCALE (5)` → Ivysaur 15, Charizard 35, Dragonite 55 (bate
  com o canon; mesmo ×5 que os dados de golpes já usavam).
- O parser **pula ramos condicionais**: `with the help of <pedra>` (é
  evolução por pedra) e `loyalty` (ex-amizade). Ramo separa por `.` ou
  `or`/`, or` — vírgula sozinha NÃO separa (`", only if its Loyalty…"`).
- Gatilho autoritativo: `check_and_evolve_pokemon` (app.py), chamado por
  `apply_battle_rewards` (fim de batalha), `/player/level-evolve`,
  `/master/xp` e `/master/pokemon-xp`.

## Por pedra

- Tabela única: `pokemon_scaling.SPECIAL_EVOLUTIONS` (~64 espécies, tipo
  `stone` apenas). Espécies com ramos (Eevee, Gloom, Wurmple, Tyrogue,
  Poliwhirl) usam lista — a pedra escolhe o ramo.
- Endpoint: `/player/use-stone` — valida posse, chama
  `get_special_evolution(name, stone_used=item)` (nunca passa moves/wins),
  consome o item só no sucesso.
- `tools/audit_evolutions.py` garante cobertura total: toda espécie com
  "evolve into" no banco tem caminho por nível OU pedra (Rockruff é a única
  whitelist — Lycanroc não existe no banco).

## Fim de batalha (server-side, `apply_battle_rewards`)

No `end_encounter` com `result='defeated'` e encontro ativo:
1. slot ativo vem do servidor (`encounter['player_pokemon_idx']`, gravado no
   start e atualizado na troca) — fallback por nome p/ cliente antigo;
2. XP pela tabela oficial (`battle_xp_reward`), level-up com
   `level_from_xp(totalXp)` e recálculo de stats;
3. `battle_wins += 1` **por índice** (homônimos não colidem);
4. `check_and_evolve_pokemon` → **UM** `save_users`.

Sem encontro ativo = sem prêmio (anti-farm). O cliente NÃO calcula mais XP
(o `awardPokemonBattleXP` antigo foi removido; `endBattle` aguarda o save de
HP antes do `end_encounter` para o save atrasado não sobrescrever o prêmio).

## Foco na mesa (o evento da mesa inteira)

Toda evolução (batalha, pedra, level, /master/xp) emite **`evolution_focus`**
para `players_{tid}` E `master_{tid}`:

```
{player_id, player_name, slot, old_name/new_name, old_number/new_number,
 nickname, shiny, new_moves, source: 'battle'|'stone'|'level'}
```

Cliente: `showEvolutionFocus`/`queueEvolutionFocus` em `static/js/app.js`
(compartilhado por jogador e mestre) — overlay fullscreen com flash, sprite
**shiny correto**, dono do Pokémon no título, golpes novos e fila para
evoluções simultâneas (auto-fecha em 12s). O evento `pokemon_evolved` legado
foi aposentado.

## Builder único

`build_evolved_pokemon(pokemon, evolved_base)` (app.py) — usado por TODOS os
caminhos. Preserva shiny/nickname/nature/moves/heldItem/XP/treino/potencial
e recalcula stats. (O builder inline do use-stone perdia `immunities`.)

Ver também: [[Bugs-Resolvidos/evolucao-por-nivel-nunca-disparava]]
