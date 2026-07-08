# Decisão — Custom EVs (em vez de IVs/EVs canônicos)

**Status**: implementado (PR #15).

## O problema

Os pontos de treino antigos eram lineares e sem identidade: todo mundo
maximizava o stat de ataque e pronto. O usuário queria progressão de Pokémon
com escolha real, sem copiar o grind de EVs dos jogos.

## A decisão

Sistema próprio de pontos, três fontes:

- **Potencial**: ⌊nível/2⌋ pontos automáticos por nível.
- **Evolução**: bônus rolado — 1d6 (estágio 2) / 1d8 (estágio final).
- **Mestre**: pode conceder pontos como recompensa narrativa.

Gastos com **custo progressivo** n(n+1)/2 (o 1º ponto num stat custa 1, o
n-ésimo custa n) e trava **anti-min-max**: a cada múltiplo de 5 investido num
stat, o próximo tier daquele stat tranca até espalhar pontos em outros.

## Por quê assim

- Custo progressivo torna especializar caro sem proibir.
- A trava de múltiplos de 5 força builds híbridas sem regra manual do mestre.
- Evolução com dado (1d6/1d8) dá momento de mesa ("rola aí!") em vez de
  tabela fixa.

## Onde vive

`battle_math.py` (statCost/pointsBudget/tier lock, espelhado no JS),
endpoint de distribuição em `app.py`, UI na ficha com breakdown por fonte.
Migração de saves antigos: flag de versão no dict do Pokémon (idempotente).

Relacionadas: [[Sistemas/evs-e-treino]], [[Decisoes/caminho-do-treinador]]
