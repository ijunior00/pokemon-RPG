# Postmortem — Leech Seed curava como Absorb

**Sintoma** (playtest do Gabriel): "a cura do leech seed tá muito forte...
no lugar ele puxa uma vida sinistra, isso é o absorv kkk".

**Causa raiz**: Leech Seed não tinha entrada explícita em
`STATUS_MOVE_EFFECTS` nem em `move_effects.json` — caía na
`auto_detect_move_effect`, que lia a descrição 5e local ("...recupera pontos
de vida...") e o classificava como **heal_self instantâneo** (metade do HP
máx!). Pior que o Absorb.

**Fix** (PR #20): condição nova **`seeded`** — alvo perde ⌊HPmáx/8⌋ por
rodada e quem plantou CURA o mesmo tanto (tick nos hooks de rodada dos 3
modos); Grama imune (`type_blocks_status`); Rapid Spin e troca removem.

**Lição (a mesma do Curse)**: a auto-detecção por descrição é fallback, não
regra — todo move de status com mecânica própria PRECISA de entrada
explícita. A auditoria da tabela do tester expôs também que os
`stat_changes` canônicos de golpes de DANO nunca eram aplicados (Icy Wind
não reduzia SPE...) — corrigido no mesmo PR, aplicado direto nos dicts vivos
no `_calc_attack_core`.

Relacionadas: [[Bugs-Resolvidos/curse-alvo-errado]], [[Sistemas/combate]]
