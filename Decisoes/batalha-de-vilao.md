# Decisão: Batalha de Vilão — grupo vs NPCs com reforço automático

**Data:** 2026-07-27 · **Status:** implementada (rota `/master/villain-battle`)

## Problema

Na mesa, um vilão com 3 Pokémon contra jogadores virava várias lutas 1v1:
cada Pokémon do vilão enfrentava UM jogador — mas o jogador tinha o time
inteiro. Resultado: batalhas fáceis demais e sem clima de "chefe".

## Decisão

Reusar o **motor de batalha em grupo** (`group_battle.py`) para lutas de
**1–4 jogadores vs 1–3 NPCs treinadores**, com a regra de mesa:

- Cada vilão põe **UM Pokémon em campo**; o resto do time fica no
  **banco por slot** (`battle['villain_bench'][cid]`).
- Quando o de campo cai, o próximo **entra sozinho**
  (`app._group_villain_reinforce`, chamada após cada ação/rodada) —
  espelho exato da reposição pós-desmaio dos jogadores.
- `gb._check_over` só declara vitória dos aliados quando o lado selvagem
  está sem vivos **e sem banco** (mesmo gate que já segurava o lado dos
  jogadores).
- **Captura bloqueada** (400 "tem dono") — Pokémon de treinador.
- **Fuga permitida** (não é emboscada).
- AUTO/manual do selvagem vale: no manual o mestre conduz cada golpe do
  vilão com `group_wild_turn` — batalha de chefe "na mão".

## Alternativas descartadas

- *Todos os Pokémon dos vilões em campo ao mesmo tempo*: viraria 4v6+,
  fora da janela de ritmo do v3.1 e ilegível na tela do celular.
- *Motor PvP encadeado (um 1v1 por Pokémon)*: era exatamente o problema
  relatado — o jogador renova o time entre lutas, o vilão não.

## Onde mexe

`group_battle.py` (`_check_over` gate + `state_view` com
`villain`/`trainer_name`), `app.py` (rota, reforço, bloqueio de captura),
card 🎭 no `master.html`/`master.js`, cliente do jogador esconde a linha
de captura e mostra o dono + banco no card inimigo. 7 checks no stress.

Relacionadas: [[Decisoes/emboscada-1v2]] (mesmo motor, outro tempero),
[[Sistemas/combate]].
