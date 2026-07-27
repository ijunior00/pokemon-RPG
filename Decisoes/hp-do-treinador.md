# Decisão: HP do Treinador — o avanço do selvagem machuca de verdade

**Data:** 2026-07-27 · **Status:** implementada

## Problema

O sistema de avanço no treinador ([[Sistemas/combate]]) criava a CENA
(time caído → selvagem parte pra cima, mestre pede Coragem/Atletismo),
mas sem HP de treinador não havia consequência mecânica — "o jogador
ficou frente a frente com um selvagem e não teve um medo real".

## Decisão (escolhas do mestre via mesa)

- **HP máximo = 20 + nível×2 + mod(Determinação)×2** — DERIVADO, nunca
  gravado (só `trainer_hp` atual persiste); nível/atributo atualizam o
  teto sozinhos. Nv.4 com Det 10 → 28 HP (~3 golpes de um selvagem médio).
- **Ataque só na cena de avanço**, disparado pelo MESTRE (botão 🩸 no
  card de ameaça): dano server-side **1d8 + nível//2** do selvagem; a
  reação do jogador (d20 + Coragem/Atletismo, dado físico digitado pelo
  mestre) contra **CD 10 + nível//2** corta o dano pela metade. Sem
  automação por turno — a mesa controla o ritmo.
- **0 HP → teste de morte HARDCORE**: d20 + Determinação vs CD 10.
  Sucesso = estabiliza com 1 HP (inconsciente, mestre narra). Falha =
  **morte do personagem** (flag `dead`; caçada e encontro bloqueados).
  Coerente com o permadeath de Pokémon que a mesa já usa.
  `/master/trainer-revive` desfaz (nova ficha/milagre — decisão de mesa).
- **Cura: só o Centro Pokémon** (restaura o treinador junto com o time;
  morto não). Sem botão de cura avulso, sem descanso diário — escolha
  explícita do mestre para manter a cura escassa.

## Alternativas descartadas

- Ataque automático a cada turno exposto: tira o controle do mestre numa
  cena que é dramática por natureza.
- HP frágil (10+Det×2): terror máximo, mas 1-2 golpes derrubando viraria
  loteria; e fixo por nível deixaria Determinação sem papel.
- 0 HP → acordar no Centro com multa: seguro demais para o tom da mesa.

## Onde mexe

`app.py`: `_trainer_max_hp`/`_trainer_hp`, rotas `/master/threat-attack`,
`/master/death-test`, `/master/trainer-revive`, Centro cura treinador,
gates de morto em `start_encounter`/`api_hunt_roll`. Ficha do jogador:
barra ❤️ (template + FX de dano). master.js: botões nos cards do inbox.
14 checks no stress.

Relacionadas: [[Decisoes/atributos-do-treinador]] (Determinação vira
vida), [[Decisoes/obediencia-teto-de-nivel]] (desobediente não defende →
avanço dispara).
