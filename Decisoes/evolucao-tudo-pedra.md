# Decisão: toda evolução especial é por pedra

**Data:** 2026-07-10 · **Decisor:** dono do projeto (AskUserQuestion) · PR #23

## O que foi decidido

1. Evolução por nível usa o **nível do próprio Pokémon** (canon), não o do
   treinador.
2. **TODA condição especial vira pedra** — amizade (13), golpe (5), stat
   check (Tyrogue) e as condições exóticas do banco (dia/noite, itens que
   não existem no jogo como Oval Stone/Sachet/Whipped Dream).
3. Eevee: **Sun→Espeon, Moon→Umbreon**, Shiny→Sylveon (Sylveon saiu da Moon
   para liberar o Umbreon, que era inalcançável).

## Por quê

- Simplicidade de mesa: o jogador escolhe e usa um item — sem depender de
  relógio do jogo, contadores ocultos ou condições que o mestre teria que
  arbitrar. Mesma lógica da conversão anterior troca→pedra.
- O sistema de amizade (battle_wins ≥ 10) tinha bugs estruturais: Eevee por
  amizade sempre retornava Espeon (primeiro match); Tyrogue por stat não
  tinha rota nenhuma; evolução por golpe disparava com QUALQUER pedra e a
  consumia.

## Mapa das conversões (flavor)

| Pedra | Espécies |
|---|---|
| Fire | Magby |
| Water | Azurill, Pyukumuku(→Silvally, dado do banco) |
| Thunder | Pichu, Elekid, Charjabug, Eelektrik |
| Leaf | Tangela, Steenee, Bonsly, Budew, Swadloon, Pansage |
| Moon | Cleffa, Igglybuff, Buneary, Munchlax, Lickitung, Skitty, Happiny, Eevee→Umbreon, Wurmple→Cascoon, Tyrogue→Hitmonchan |
| Sun | Yanma, Eevee→Espeon, Wurmple→Silcoon, Tyrogue→Hitmonlee, Gloom→Bellossom |
| Shiny | Togepi, Chansey, Aipom, Spritzee, Swirlix, Floette, Eevee→Sylveon |
| Dusk | Golbat, Woobat, Lampent |
| Dawn | Riolu, Mime Jr., Tyrogue→Hitmontop |
| Ice | Piloswine, Smoochum |

`/player/friendship-evolve` e o botão 💛 foram removidos (código morto).
Rockruff ficou sem caminho (Lycanroc não existe no banco — whitelist do
`tools/audit_evolutions.py`; adicionar a espécie destrava Sun/Dusk/Moon).
