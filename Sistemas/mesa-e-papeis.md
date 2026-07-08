# Sistema — Mesa, multi-tenant e papéis

## Multi-tenant por mesa

Todo dado do jogo é escopado por **mesa** (table). O helper `_tid()` em
`app.py` resolve a mesa do usuário logado — TODA leitura/escrita de estado
de jogo passa por ele. Bug clássico já corrigido: query sem `_tid` vazava
dados entre mesas (quests cross-mesa).

- Persistência: Postgres com colunas **JSONB** (users/trainer_data,
  game_state) — não há ORM relacional fino; os "documentos" JSON são a
  verdade.
- Salas Socket.IO: `players_{tid}`, `master_{tid}`, e sala por player_id.

## Papéis

| Papel | Pode |
|---|---|
| **Jogador** | entra numa mesa via **convite** (código gerado pelo mestre) |
| **Mestre** | dono da mesa: caçadas, NPCs, quests, calendário, batalhas, concessões |
| **Super-admin (`lusmar`)** | aprova cadastros de novos mestres — mestre pendente não loga nem tem mesa |

Fluxo de mestre novo: registra → fica pendente → `lusmar` vê a fila e
aprova → mesa + convite criados.

## Estado de batalha (onde vive cada modo)

| Modo | Estado |
|---|---|
| Selvagem | `game_state['active_encounters'][player_id]` → `battle_state` |
| PvP / vs NPC | `ACTIVE_PVP` (memória) + persistência p/ retomada |
| Grupo (dupla) | `ACTIVE_GROUP_BATTLES` |

`WILD_AUTO_MODE` por mesa: selvagens jogam sozinhos ou o mestre conduz.

## Deploy

`main` → Render (auto-deploy a cada push; `render.yaml`: gunicorn + gevent
websocket, DATABASE_URL externo Neon/Supabase com `sync:false`). Por isso:
**nunca** commitar direto no `main` sem passar pelo fluxo de PR — exceto que
NADA além de código deployável deve ir pro `main` de qualquer forma.

Relacionadas: [[Decisoes/atributos-do-treinador]], [[Sistemas/combate]]
