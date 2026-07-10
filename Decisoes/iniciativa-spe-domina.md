# Decisão: iniciativa — Speed decide, o dado é o imprevisto

**Data:** 2026-07-10 · PR #23 · Spec: `docs/sistema-combate-d100.md` §7.1

## Problema

Fórmula antiga `d20 + SPE_eff//10`: o d20 (amplitude 19) dominava o bônus
(+1..+9 nos níveis 10-30) — um Snorlax ganhava iniciativa de um Jolteon com
frequência absurda, só na sorte.

## Fórmula nova

`1d20 + ⌊SPE_eff/5⌋ (+ Tática 0..+2)`, decidida por
`battle_math.initiative_winner(nat_a, nat_b, spe_a, spe_b, extra_a, extra_b)`
— **fonte única** espelhada 1:1 no JS (paridade verificada, 500 amostras):

1. **Upset 20vs1**: se o mais LENTO tira 20 natural e o mais rápido tira 1
   natural, o lento age primeiro ignorando modificadores (1/400 = 0,25%).
   É o upset "raro e estatisticamente justificável" pedido pelo usuário —
   sempre possível, em qualquer gap.
2. Maior total. 3. Empate → maior SPE_eff. 4. Empate completo → jogador.

## Matemática (por que /5)

P(lento vence) = `(19−g)(20−g)/800` para gap `g` de bônus (desempate para o
rápido). No nível 50:

| Gap de base | g | P(upset) |
|---|---|---|
| ±15 | ~3 | ~34% (equilibrado) |
| ±30 | ~6 | ~23% (favorece rápido) |
| ±60 | ~12 | ~7% (rápido domina) |
| ±100+ | ≥19 | 0,25% (só 20vs1) |

Com /10 os mesmos gaps davam ~40/33/23% — sorte decidia. /4 mataria o dado
em gaps médios. /5 é o ponto em que Speed manda na média e o d20 segue vivo.

## Onde vive

- `battle_math.initiative_bonus` (//5) + `initiative_winner` (+ espelho JS).
- 4 call sites: `handle_initiative` e `_auto_roll_initiative` (app.py),
  `pvp_battle.accept_battle`, `group_battle.build_battle` (grupo: ordenação
  desempata por SPE; **sem** 20vs1 — só faz sentido em duelo).
- Paralisia (SPE×0,5), estágios e natureza entram via `effective_stat`.
- Payload `initiative_result` ganhou `upset: bool` (log "💨 Virada lendária").
- Rótulo dos logs: DEX → SPE.
