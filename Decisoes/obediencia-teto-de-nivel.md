# Obediência: teto de nível para USAR Pokémon em batalha

**Decisão (2026-07, escolha do usuário):** jogador não usa Pokémon acima de
**(nível do treinador ×5) + 10**. A escala ×5 é a ponte canônica nível de
treinador (5e, 1-20) → nível de Pokémon (1-100); o +10 é a folga da regra
da mesa ("10 níveis acima"). Régua alternativa considerada e rejeitada:
`treinador + 10` direto (quebraria o endgame — treinador 20 nunca usaria
Nv.31+).

## Alcance (também escolha do usuário)

- Bloqueia **só o uso em batalha** — o Pokémon fica no time/PC normalmente
  e destrava sozinho quando o treinador sobe de nível.
- **NPCs do mestre ficam fora da regra** (vilão usa o que quiser).

## Onde o servidor guarda a porta (app.py)

`_obedience_cap` / `_poke_obeys` / `_disobey_msg`; chokepoints:

- 1v1: `start_encounter` (nega e **devolve o vale** de encontro) e a troca
  em batalha (recusa sem consumir turno).
- Dupla/emboscada: `_group_active_pokemon` (sem fallback de desmaiado),
  `_group_switch`, e o **banco só conta vivos obedientes** — sem isso a
  batalha ficava aberta esperando reposição impossível.
- PvP/ginásio: `pvp_select_pokemon` e `pvp_switch` (só lado humano).
- Avanço no treinador: vivo-mas-desobediente **não conta como defesa**.

Cliente espelha com "☠️ não obedece" desabilitado (seletor 1v1, modal de
troca, banco da dupla, seleção PvP) e o aviso de captura usa o mesmo teto.

## Armadilha de teste

Os treinadores do stress nasciam nível 1 (teto 15) com times Nv.18-20 —
a regra bloqueou a suíte inteira. `tests/stress.py` nivela u1/u2 para
Nv.4 (teto 30) no setup; teste novo que crie treinador + time precisa
respeitar a régua (ou o start_encounter nega com `encounter_denied`).

Relacionadas: [[Decisoes/emboscada-1v2]], [[Sistemas/evolucao]].
