# Decisão — Atributos do Treinador (6 novos + point-buy)

**Status**: implementado.

## O problema

O treinador humano ainda usava os 6 atributos de D&D (FOR/DES/CON/INT/SAB/CAR)
que não diziam nada sobre *ser treinador Pokémon*, e os valores vinham
travados/arbitrários.

## A decisão

- **6 atributos próprios** do universo do jogo (Vínculo, Tática, etc. — ver
  `trainer_attrs.py` para a lista canônica e as perícias de cada um), com
  migração automática dos saves antigos.
- **Point-buy na criação**: 20 pontos, base 10, teto 16 por atributo.
- Perícias roláveis pela ficha + inbox do mestre (pedido de teste).

## Onde os atributos mordem as mecânicas

Captura, loja (preços), caçada, iniciativa e as rolagens livres da mesa —
integrados nos pontos que já existiam, sem criar subsistema paralelo.

## Por quê point-buy 20/10/16

Rolar atributo dava treinador aleijado ou semideus; array fixo dava todo
mundo igual. 20 pontos sobre base 10 com teto 16 permite um pico e um dump
sem extremos.

Relacionadas: [[Decisoes/caminho-do-treinador]], [[Sistemas/mesa-e-papeis]]
