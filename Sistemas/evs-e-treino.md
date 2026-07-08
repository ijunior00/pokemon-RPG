# Sistema — EVs e Treino

> Motivação: [[Decisoes/evs-customizados]].

## Fórmula de stat (v2, base stats reais 1–255)

```
stat  = (2 × base × nível) // 100 + 5 + treino     (ATK/DEF/SPA/SPD/SPE)
maxHp = (2 × baseHP × nível) // 100 + nível + 10
```
Natureza ±10% (`apply_nature`, nunca HP). Shiny ×1,35 nos base stats ANTES
de escalar.

## Orçamento de pontos (Custom EVs)

| Fonte | Quanto |
|---|---|
| Potencial | ⌊nível/2⌋ automático |
| Evolução | 1d6 (2º estágio) / 1d8 (final), rolado na evolução |
| Mestre | concessão manual (recompensa) |

- Custo progressivo: n-ésimo ponto num stat custa n → total n(n+1)/2.
- Anti-min-max: a cada múltiplo de 5 num stat, próximo tier tranca até
  diversificar.
- Saldo é DERIVADO (orçamento − gasto), nunca armazenado solto — level-up não
  apaga pontos (bug histórico do sistema v1).

## Onde no código

`battle_math.py`: `statCost`, `nextPointCost`, `trainingSpent`,
`potentialPoints`, `pointsBudget`, `statTierLocked` (espelhados no JS).
Endpoint de distribuição + validação server-side em `app.py`. Migração de
saves: flag de versão no dict do Pokémon, idempotente, HP preserva %.

Relacionadas: [[Sistemas/combate]] (o stat alimenta o componente de dano)
