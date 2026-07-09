# Decisão — Sistema de Combate v3 (d100/ACC)

**Status**: implementado e em produção (PR #17, jul/2026).
**Spec canônica**: `docs/sistema-combate-d100.md` no `main` — esta nota é o
*porquê*, a spec é o *como*.

## O problema

O sistema herdado de D&D 5e (d20 vs CA, modificadores `(stat-10)//2`, saves
com CD) produzia batalhas ou instantâneas ou intermináveis, "two-curve"
(quem tinha stat maior sempre acertava/nunca era acertado), e dano "cinco,
cinco, cinco" sem drama. Playtests reais da mesa confirmaram.

## A decisão

Sistema em **3 camadas**, cada uma com um dado e um dono:

1. **Precisão** (atacante, d100): d100 ≤ ACC efetivo do golpe. A chance é do
   *golpe*, não do corpo — corta o two-curve por construção.
2. **Dano Bruto** (determinístico + dados): componente ⌊stat/8⌋ + ⌊nv/10⌋ +
   dados da Tabela Mestra (8 degraus por POW) + momentum.
3. **Resistência** (defensor, d20): d20 + min(⌊Def/10⌋,12) + ⌊nv/10⌋ vs TN
   → dano cheio / metade / anulado. O defensor participa de todo golpe.

## Escolhas dentro da decisão (e por quê)

- **Cooldown em vez de PP** — pedido explícito do usuário ("Não quero PP só
  cooldown"). Golpes fortes esperam 1–3 rodadas; bloqueio NÃO gasta o turno.
- **Momentum + Adaptação** — cenoura e chicote contra spam: variar golpe dá
  +1 dano (máx +3); repetir 3× dá +2 de resistência ao alvo. Com o cooldown,
  "apertar Fire Blast toda rodada" é a pior estratégia possível.
- **Janela 5–10 rodadas** — requisito duro do usuário, validado por
  monte-carlo (`tools/battle_sweep_v3.py`, mediana por faixa de nível).
- **Servidor rola o d100** — o cliente não manda rolagem (fechou o exploit
  de "sempre enviar 20").
- **Posturas de defesa aposentadas** — a camada de Resistência substituiu o
  seletor de postura/esquiva do sistema v2.
- **Shiny ×1,35 nos stats, nunca na precisão** — accuracy é do golpe.
- **Certeiros rebalanceados (spec de precisão, jul/2026)** — a penalidade
  original (componente 60% + dado −1 degrau) era severa demais; virou
  **dano final ×0,90** (`V3_CERTEIRO_DAMAGE_MULT`). ACC 100 ≠ ACC ∞:
  100% ainda sofre Precisão/Evasão; ∞ pula só esse teste. Imunidade de
  tipo passou a ser checada ANTES da precisão, e Fly/Dig/Dive... ganharam
  semi-invulnerabilidade real (PR #19).

## Calibração (alavancas em `battle_math.py`)

`V3_STATUS_DIVISOR=8`, `V3_DEF_BONUS_CAP=12`, `V3_STAB_DIE_LEVEL=25` (antes
disso STAB = +2 fixo), TN Efetiva = tabela + ⌊nv atacante/10⌋. Histórico dos
ajustes: L15 acabava rápido demais (STAB die cedo), L100 lento demais (bônus
de Def dominava o d20) — ver git log do PR #17.

## Regras de mesa adotadas (desvios conscientes do canon)

- Recoil e chip de clima **nunca nocauteiam** (param em 1 HP).
- Future Sight resolve imediato (cooldown 3) — versão "2 rodadas depois"
  ficou pra mesa narrar.
- Prioridade em turnos alternados: desempates da Resistência + Psychic
  Terrain + Protect (a ordenação completa é adjudicação do mestre).

Relacionadas: [[Sistemas/combate]], [[Decisoes/evs-customizados]]

## Adendo (09/07/2026): migração 5e→v3 dos moves concluída

Auditoria pedida pelo Junior (caso-guia: Curse) eliminou os últimos resquícios
de D&D 5e nos moves:

- **Curse canônico**: Fantasma sacrifica ⌊HPmáx/2⌋ e amaldiçoa (👻 condição
  `amaldicoado`, ⌊HPmáx/4⌋/rodada, sai de campo remove); demais tipos
  +1 ATK/+1 DEF/−1 SPE. Sem teste de Sabedoria.
- **Estágios canônicos multi-stat**: 129 entradas de buff/debuff normalizadas
  pelos `stat_changes` do dado canônico (Swords Dance +4→+2, Calm Mind
  SpA+1/SpD+1, Shell Smash completo…). Schema novo: `{'stats': {...}}`.
- **d100 único p/ Pokémon**: acordar 45% e descongelar 30% em d100 (mesmas
  probabilidades dos antigos d20≥12/15); `nat15plus` (quebrado desde o v3:
  attack_roll virou d100) removido; 195 campos `save` mortos expurgados;
  Sheer Cold corrigido p/ OHKO; Hidden Power não envenena; 26 descrições
  reescritas. Auditoria automática no stress trava regressão (zero termos 5e).
- **Fronteira oficial**: d20 do POKÉMON existe só na camada de Resistência do
  v3 (spec §5) e no OHKO (§17) — que É a Resistência. d20 fora disso = do
  TREINADOR (perícias/caçada). Pokémon rola d100 para todo o resto.
