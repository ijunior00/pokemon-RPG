# CLAUDE.md — Pokémon RPG 5e

App web de mesa para Pokémon RPG tabletop: Flask + Flask-SocketIO + Postgres
(JSONB), multi-mesa (todo estado escopado por `_tid()`), combate próprio
**v3 d100/ACC** (spec canônica: `docs/sistema-combate-d100.md`). O `main` é
auto-deployado no Render a cada push — mudanças de código entram por PR.

## 🧠 Memória do projeto: branch `cofre`

Este repo tem um **cofre de memória** (vault Obsidian) no branch órfão
`cofre` — decisões de arquitetura, visões por sistema, postmortems e
glossário. **No início de uma sessão, leia o índice antes de assumir que não
há contexto anterior:**

```bash
git fetch origin cofre
git show origin/cofre:00-Indice.md        # hub — linka todas as notas
git show origin/cofre:Sistemas/combate.md # exemplo: ler uma nota específica
```

Convenções do cofre:

- **Ler**: sempre via `git show origin/cofre:<caminho>` (o branch não coexiste
  no working tree) ou worktree temporário
  (`git worktree add --checkout /tmp/cofre-wt cofre`).
- **Escrever**: ao fechar uma decisão de arquitetura/design não-trivial ou
  resolver um bug de causa raiz interessante, registre/atualize a nota e
  linke em `00-Indice.md`. Commit **direto no branch `cofre`, sem PR**
  (são notas, não código).
- **Nunca** colocar código do jogo no `cofre`, nem notas no `main` — o
  usuário sincroniza o `cofre` com o app do Obsidian (plugin Fit) no celular.

## Regras do projeto

- `battle_math.py` e `static/js/battle_math.js` são **espelhos 1:1** — mudou
  um, mude o outro (o stress tem teste de paridade).
- Testes: `tests/stress.py` (323 checks) **só em banco descartável**
  (`DATABASE_URL` de teste); ritmo de combate validado por
  `tools/battle_sweep_v3.py` (mediana 5–10 rodadas por faixa, exit 1 se furar).
- Toda query de estado de jogo passa por `_tid()` (multi-mesa) — query sem
  escopo de mesa é bug de segurança.
- Documentação e commits em PT-BR.
