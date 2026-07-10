# Decisão: combate v3.1 — d100 total, Tabela Mestra nova, DoT/cura balanceados

**Data:** 2026-07-10 · Spec: `docs/sistema-combate-d100.md` (§1, §4, §7.1, §11, §20)

## Pedido

Revisão completa da fórmula de dano: nova tabela POW→dados/recarga definida
pelo usuário, auditoria de todos os efeitos secundários, DoT/cura moderados
("dano contínuo nunca substitui golpes principais", "sem ciclo infinito de
cura") e fase obrigatória de simulações com meta de **4–6 turnos de mediana**
(até 8 nos naturalmente longos). Decisões explícitas do usuário:

1. **Migrar TUDO para d100** — Resistência do defensor e iniciativa saem do
   d20. O d20 que fica é só perícia de treinador (D&D de mesa, fora do combate).
2. **Recarga conforme a tabela dele** — recarga 1 já a partir de POW 55.
3. **Burn/Poison escalonados começando em 1/16** ("vai evoluindo").

## O que mudou

### Tabela Mestra (10 degraus)

> **Revisão pós-mesa (mesmo dia, com o sistema em produção):** com recarga
> desde POW 55, movesets médios ficavam sem ação ("cooldown infinito" — as
> recargas só caem quando o Pokémon age). O usuário mandou a tabela revisada
> abaixo: recarga só a partir do degrau 70–80, e 5d6/6d6 nos degraus altos
> (elimina o quase-empate 3d8≈4d6; médias monotônicas 13,5 → 17,5 → 21 → 22).
> Sweep e matriz seguiram verdes sem tocar em outra alavanca.

| POW | Dados | TN | Recarga |
|---|---|---|---|
| 10–20 | 1d6 | 50 | 0 |
| 25–35 | 1d8 | 60 | 0 |
| 40–50 | 1d10 | 70 | 0 |
| 55–65 | 2d6 | 80 | 0 |
| 70–80 | 2d8 | 90 | 1 |
| 85–95 | 3d6 | 100 | 1 |
| 100–110 | 3d8 | 110 | 2 |
| 115–125 | 5d6 | 120 | 2 |
| 130–140 | 6d6 | 130 | 3 |
| 145+ | 4d10 | 140 | 3 |

POW >150 cai no último degrau.

### Migração d100 (×5 fiel do d20)

- **Resistência**: `d100 + min(50,⌊def/2⌋) + 5/estágio + ⌊nv/2⌋ + extra×5`
  vs TN; anula em ≥TN+50; janelas de empate técnico do defensor rápido ±5;
  OHKO resiste em TN 110.
- **Iniciativa**: `d100 + SPE_eff + Tática×5`; upset lento≥96 E rápido≤5
  (0,25% = o antigo 20vs1). Fórmula da sessão anterior preservada ×5.
- Resíduo garantido por teste: **zero** `randint(1, 20)` nos caminhos de
  combate (whitelist explícita das rotas de perícia do treinador).

### Pesos do dano

`V3_STATUS_DIVISOR` 8→10 (status ~39% do bruto no Nv100, dados sempre
majoritários); marcos de nível //25→//20 com teto +5; `V3_DEF_BONUS_CAP` 50.
Calibrado pelo sweep: medianas 5/5/5/6/7/7 por faixa (janela 4–6, até 8).

### DoT e cura

- Burn/Toxic: escalonado 1/16→2/16→… com **teto ⌊HP/4⌋/turno**
  (`DOT_SCALING_CAP_DIV`). Leech Seed nerfado ⌊HP/8⌋→⌊HP/16⌋ (fonte única
  `effects.seed_drain`). Curse ⌊HP/4⌋ e traps ⌊HP/16⌋×4 mantidos.
- Cura instantânea: recarga 2→**3** + **cura decrescente** — cada uso na
  mesma batalha cura metade do anterior (`heal_uses` no `_v3`, zera só em
  batalha nova). Sem ela, Recover-stall vencia 99% no espelho da matriz;
  com ela, 48,5%. Recarga 4 sozinha não bastou (92,7%).

### Fidelidade de efeitos

Static agora paralisa 30% (dava dano); Solar Power só sob Sol (×1,5 SpA +
⌊HP/8⌋/turno de custo); Strength Sap cura = ATK do alvo (tipo novo
`drain_stat_heal`); chave duplicada `'electric terrain'` removida (o terreno
nunca ativava); Infestation/Magma Storm prendem. Auditoria permanente:
`tools/audit_effects_v3.py --strict` (canônico × move_effects × motor) —
zero divergências.

## Gates permanentes (exit 1)

- `tools/battle_sweep_v3.py` — calibrador rápido, mediana 4–6 (até 8).
- `tools/battle_matrix_v3.py` — 17 arquétipos com espécies reais (espelhos
  de mecânica: Swords Dance, Intimidate, Recover, Toxic, burn, Leech, Curse,
  Huge Power…), 400 batalhas cada; invariantes de mediana, timeout zero,
  DoT ≤ ⌊HP/4⌋/turno, golpe fraco relevante, winrate de stall 35–65%.
  O lado "baunilha" dos cenários de sustain modela **item de contra-jogo**
  (1 cura/limpeza por batalha) — sem isso o espelho mente.

Ver também: [[Decisoes/sistema-combate-v3]] · [[Decisoes/recarga-de-sustain]]
· [[Decisoes/iniciativa-spe-domina]] · [[Sistemas/combate]]
