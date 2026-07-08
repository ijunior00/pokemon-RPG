# Sistema — Habilidades (abilities)

**Cobertura**: 100% das habilidades das espécies têm efeito funcional ou
descrição adjudicável (as ~166 restantes entraram no PR #15).

## Arquitetura: chokepoints, não ifs espalhados

Tudo em `abilities.py`, consumido em POUCOS pontos:

| Categoria | Tabela em abilities.py | Chokepoint |
|---|---|---|
| Multiplicador de stat (Huge Power...) | `ABILITY_STAT_MULT` + condicionais | `status_effects.effective_stat` |
| Multiplicador de dano (Iron Fist, Technician, Tinted Lens...) | via `ability_damage_mult` | `app._calc_attack_core` |
| Imunidade/absorção (Levitate, Volt Absorb...) | `ABILITY_IMMUNITIES`/`ABSORB_*` | `check_defender_ability` nos handlers |
| Contato (Static, Rough Skin, Poison Touch...) | `check_contact_ability` / `check_attacker_contact_ability` | pós-dano físico nos handlers |
| Imunidade a status (Limber, Insomnia...) | `is_status_immune` | aplicação de condição |
| On-enter (Intimidate, Drought/Drizzle...) | `ABILITY_ON_ENTER` | iniciativa/entrada em batalha |
| Crítico (Merciless, Super Luck, Shell Armor, Sniper) | `crit_stage_for` etc. | `_calc_attack_core` |
| Clima (imunidade a chip) | `ability_blocks_weather_damage` | `_field_chip` |

Regra do projeto: habilidade nova = entrada de dado numa tabela + (se
preciso) um hook num chokepoint existente. **Nunca** if de nome de
habilidade dentro de handler.

## STAB condicional

Blaze/Torrent/Overgrow/Swarm com HP ≤ 25%: +1 dado extra do tipo (v3) —
`stab_multiplier` consumido no cálculo dos dados.

Relacionadas: [[Sistemas/combate]]
