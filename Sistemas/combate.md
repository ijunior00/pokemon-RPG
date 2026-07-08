# Sistema — Combate v3 (visão de 1 página)

> Spec completa e canônica: `docs/sistema-combate-d100.md` no `main`.
> Motivação e histórico: [[Decisoes/sistema-combate-v3]].

## As 3 camadas de todo ataque

```
1. PRECISÃO   d100 (servidor) ≤ ACC efetivo?   → errou / conectou
2. DANO       comp ⌊stat/8⌋ + ⌊nv/10⌋ + dados(POW) + momentum  = bruto
3. RESISTÊNCIA d20 defensor + ⌊def/10⌋(≤12) + ⌊nv/10⌋ vs TN → cheio/metade/anulado
```

- Crítico: d100 próprio, 5% base (+10 p.p./estágio, teto 50) — fura metade do
  bônus de Def do defensor (Sniper zera).
- Certeiros (ACC "—"): conectam sempre, componente 60%, −1 degrau de dado.
- Cooldown por POW (0–3 rodadas), momentum (+1/golpe variado, máx 3),
  adaptação (3ª repetição → alvo +2). Sem PP.
- Clima/terreno: 5 rodadas, ±1 dado por tipo, chips ⌊HP/16⌋, ACC especiais
  (Thunder na chuva = 100). Estado em `field` da batalha.
- Casos especiais: multi-hit, recoil ⌊dano/3⌋, dreno ⌊dano/2⌋, carga,
  Protect decaindo 100→50→25%, OHKO = ACC 30 × Resistência TN 22.

## Onde no código

| O quê | Onde |
|---|---|
| Fórmulas puras (fonte única) | `battle_math.py` seção v3 (+ espelho `static/js/battle_math.js`) |
| Motor do ataque (3 camadas) | `app.py` → `_calc_attack_core` |
| Estado por lado (`_v3`: cooldowns/momentum/streak/charging/protected) | dict do Pokémon em batalha — morre com ela |
| Estado de campo (clima/terreno) | `_field_of()` no battle_state (selvagem) ou dict da batalha (PvP/grupo) |
| Moves de status → efeitos | `status_effects.py` → `process_status_move` |
| Validação de ritmo | `tools/battle_sweep_v3.py` (mediana 5–10 por faixa, exit 1 se furar) |
| Testes dedicados | `tests/stress.py` seção 17 "Sistema v3" (23 checks) |

## Armadilhas conhecidas

- `battle_math.py` e `battle_math.js` são ESPELHOS 1:1 — mudou um, muda o outro.
- A troca de Pokémon zera momentum/streak mas **mantém cooldowns** (regra).
- Golpe bloqueado (cooldown/protect indisponível) **não consome o turno** —
  eventos `action_blocked`/`pvp_error`/`group_battle_error`.
- Cópias rasas de dicts de Pokémon (grupo!) precisam garantir `_v3` ANTES do
  `dict()` pra compartilhar o estado aninhado.
