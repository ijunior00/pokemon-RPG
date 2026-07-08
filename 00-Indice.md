# 🧠 Cofre — Pokémon RPG 5e

Hub de memória do projeto. Começa por aqui: cada seção linka as notas vivas.
Convenção: notas em PT-BR, `[[wikilinks]]`, uma ideia por nota.

> Para sessões do Claude Code: leia este índice ANTES de assumir que não há
> contexto anterior. Ao fechar uma decisão não-trivial, crie/atualize a nota
> e linke aqui (commit direto neste branch, sem PR).

## O projeto em uma linha

App web de mesa para Pokémon RPG tabletop (Flask + Socket.IO + Postgres
JSONB), multi-mesa, com combate próprio **v3 d100/ACC** — jogado ao vivo com
mestre e jogadores, deploy no Render a partir do `main`.

## Sistemas

- [[Sistemas/combate]] — as 3 camadas do v3 (precisão d100 → dano → resistência d20)
- [[Sistemas/habilidades]] — 100% das abilities funcionais e onde elas plugam
- [[Sistemas/evs-e-treino]] — Custom EVs: potencial, treino, custo progressivo
- [[Sistemas/mesa-e-papeis]] — multi-tenant (`_tid`), papéis, aprovação de mestre
- [[Sistemas/economia-e-seguranca]] — loja/apostas/NPCs com bolsa, presentes do mestre, defesas de acesso

## Decisões (por que o sistema é assim)

- [[Decisoes/sistema-combate-v3]] — d20→d100, cooldown no lugar de PP, janela 5–10 rodadas
- [[Decisoes/evs-customizados]] — escolhido em vez de IVs/EVs canônicos
- [[Decisoes/caminho-do-treinador]] — 4 caminhos, marcos 3/6/10
- [[Decisoes/atributos-do-treinador]] — 6 atributos novos + point-buy 20 pts

## Bugs resolvidos (postmortems)

- [[Bugs-Resolvidos/agua-sem-super-efetivo]] — dado de matchup corrompido na fonte
- [[Bugs-Resolvidos/curse-alvo-errado]] — debuff aplicado no lado errado
- [[Bugs-Resolvidos/leech-seed-como-absorb]] — auto-detecção virou cura instantânea

## Outras notas

- [[Backlog-Ideias]] — em aberto, adiado e descartado (com o porquê)
- [[Glossario]] — vocabulário do projeto (mesa, tid, momentum, certeiro...)
- [[LEIA-ME]] — o que é este branch e como sincronizar com o Obsidian (plugin Fit)

## Mapa rápido do código (branch `main`)

| Arquivo | Papel |
|---|---|
| `app.py` | rotas Flask + handlers Socket.IO + motor de ataque (`_calc_attack_core`) |
| `battle_math.py` | FONTE ÚNICA das fórmulas (espelhado em `static/js/battle_math.js`) |
| `status_effects.py` | condições, stat stages, moves de status |
| `abilities.py` | habilidades passivas/ativas |
| `pvp_battle.py` / `group_battle.py` | estado de batalha PvP e em dupla |
| `docs/sistema-combate-d100.md` | spec canônica do combate v3 (não duplicar aqui) |
| `tests/stress.py` | suíte de 323 checks (rodar em DB descartável!) |
| `tools/battle_sweep_v3.py` | monte-carlo da janela 5–10 rodadas |
