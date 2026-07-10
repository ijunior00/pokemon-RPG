# Sistema — Combate v3.1 (visão de 1 página)

> Spec completa e canônica: `docs/sistema-combate-d100.md` no `main`.
> Motivação e histórico: [[Decisoes/sistema-combate-v3]] ·
> [[Decisoes/combate-v3-1-d100-total]].

## As 3 camadas de todo ataque (100% d100)

```
1. PRECISÃO   d100 (servidor) ≤ ACC efetivo?   → errou / conectou
2. DANO       comp ⌊stat/10⌋ + ⌊nv/10⌋ + dados(POW) + marcos + momentum = bruto
3. RESISTÊNCIA d100 defensor + min(50,⌊def/2⌋) + 5/estágio + ⌊nv/2⌋ vs TN
              → cheio / metade (≥TN) / anulado (≥TN+50)
```

- Não existe mais d20 no combate de Pokémon (Resistência e iniciativa também
  são d100). O d20 que sobrou é só perícia de TREINADOR (/api/roll, caçada).
- Tabela Mestra: 10 degraus, 1d6 (POW≤20) até 4d10 (POW>140); TN 50→140;
  recarga 0/0/0/1/1/1/2/2/3/3 (recarga 1 já a partir de POW 55).
- Marcos de nível: +1 dado a cada 20 níveis (teto +5).
- Crítico: d100 próprio, 5% base (+10 p.p./estágio, teto 50) — fura metade do
  bônus de Def do defensor (Sniper zera).
- Certeiros (ACC ∞): pulam SÓ Precisão×Evasão; dano final ×0,90. Não
  atravessam imunidade, habilidades, Protect nem invulnerabilidade.
- Iniciativa: `d100 + SPE_eff + Tática×5`; upset lento≥96 vs rápido≤5 (0,25%).
- DoT: burn/toxic escalonados 1/16→2/16→… com teto ⌊HP/4⌋/turno; Leech Seed
  ⌊HP/16⌋; Curse ⌊HP/4⌋; traps ⌊HP/16⌋×4.
- Cura instantânea: recarga 3 (metade/total) + **cura decrescente** — cada uso
  na mesma batalha cura metade do anterior (mata loop infinito de Recover).
- Meta de ritmo: mediana **4–6 turnos** (até 8 nos naturalmente longos).

## Onde no código

| O quê | Onde |
|---|---|
| Fórmulas puras (fonte única) | `battle_math.py` seção v3 (+ espelho `static/js/battle_math.js`) |
| Motor do ataque (3 camadas) | `app.py` → `_calc_attack_core` |
| Estado por lado (`_v3`: cooldowns/momentum/streak/charging/protected/heal_uses) | dict do Pokémon em batalha — morre com ela (`_v3_new_battle` zera heal_uses) |
| Estado de campo (clima/terreno) | `_field_of()` no battle_state (selvagem) ou dict da batalha (PvP/grupo) |
| Moves de status → efeitos | `status_effects.py` → `process_status_move` |
| Validação de ritmo (2 gates) | `tools/battle_sweep_v3.py` (mediana 4–6, até 8) + `tools/battle_matrix_v3.py` (17 arquétipos, invariantes) |
| Auditoria de efeitos | `tools/audit_effects_v3.py --strict` (canônico × move_effects × motor) |
| Testes dedicados | `tests/stress.py` (465 checks) |

## Armadilhas conhecidas

- `battle_math.py` e `battle_math.js` são ESPELHOS 1:1 — mudou um, muda o outro.
- A troca de Pokémon zera momentum/streak mas **mantém cooldowns e heal_uses**
  (regra); heal_uses só zera em batalha NOVA.
- Golpe bloqueado (cooldown/protect indisponível) **não consome o turno** —
  eventos `action_blocked`/`pvp_error`/`group_battle_error`.
- Cópias rasas de dicts de Pokémon (grupo!) precisam garantir `_v3` ANTES do
  `dict()` pra compartilhar o estado aninhado.
- 3d8 (13,5) ≈ 4d6 (14,0) na média — fiel à tabela do usuário; TN e variância
  diferenciam os degraus.
