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

- [[Sistemas/combate]] — as 3 camadas do v3.1, 100% d100 (precisão → dano → resistência)
- [[Sistemas/evolucao]] — nível (canon = 5e×5) e pedra; foco de evolução na mesa inteira
- [[Sistemas/habilidades]] — 100% das abilities funcionais e onde elas plugam
- [[Sistemas/evs-e-treino]] — Custom EVs: potencial, treino, custo progressivo
- [[Sistemas/mesa-e-papeis]] — multi-tenant (`_tid`), papéis, aprovação de mestre
- [[Sistemas/economia-e-seguranca]] — loja/apostas/NPCs com bolsa, presentes do mestre, defesas de acesso

## Decisões (por que o sistema é assim)

- [[Decisoes/sistema-combate-v3]] — d20→d100, cooldown no lugar de PP, janela 5–10 rodadas
- [[Decisoes/combate-v3-1-d100-total]] — v3.1: d100 total, Tabela Mestra nova, DoT 1/16 c/ teto, cura decrescente, meta 4–6
- [[Decisoes/recarga-de-sustain]] — dreno/cura instantânea com cooldown 1-2 (detecção por mecânica)
- [[Decisoes/evolucao-tudo-pedra]] — amizade/golpe/stat viraram pedra; nível é do Pokémon
- [[Decisoes/iniciativa-spe-domina]] — Speed decide, dado é o imprevisto (hoje em d100: ver v3.1)
- [[Decisoes/evs-customizados]] — escolhido em vez de IVs/EVs canônicos
- [[Decisoes/caminho-do-treinador]] — 4 caminhos, marcos 3/6/10
- [[Decisoes/atributos-do-treinador]] — 6 atributos novos + point-buy 20 pts
- [[Decisoes/emboscada-1v2]] — Nat 1 na caçada → 1 jogador vs 2 selvagens (motor de grupo, sem fuga)
- [[Decisoes/cache-de-processo-db]] — leituras da memória, Postgres só p/ escrever (cota do Neon; requer 1 worker)

## Bugs resolvidos (postmortems)

- [[Bugs-Resolvidos/agua-sem-super-efetivo]] — dado de matchup corrompido na fonte
- [[Bugs-Resolvidos/curse-alvo-errado]] — debuff aplicado no lado errado
- [[Bugs-Resolvidos/leech-seed-como-absorb]] — auto-detecção virou cura instantânea
- [[Bugs-Resolvidos/modo-manual-mestre-nao-funcionava]] — cliente do jogador auto-jogava o selvagem; caminho do mestre preso no v2
- [[Bugs-Resolvidos/auditoria-qa-exploits-client-side]] — captura/HP/cura/status forjados + PvP hijack (Lote 1 pronto; concorrência pendente)
- [[Bugs-Resolvidos/evolucao-por-nivel-nunca-disparava]] — gatilho no nível do treinador + escala 5e sem ×5 + Pikachu evoluía sem pedra
- [[Bugs-Resolvidos/cura-gratis-via-pivo-na-troca]] — HP de batalha não persistia no time; pivotar na troca curava de graça

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
| `tests/stress.py` | suíte de 465 checks (rodar em DB descartável!) |
| `tools/battle_sweep_v3.py` + `tools/battle_matrix_v3.py` | gates de ritmo: janela 4–6 (até 8) + matriz de arquétipos |
