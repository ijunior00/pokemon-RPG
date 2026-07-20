# Cache de processo no banco (write-through, 1 worker)

**Decisão (2026-07):** todas as leituras de `users`, `game_state` (todas as
chaves: estado, site_settings, gyms, league) e `npcs` são servidas de um
**cache de processo** em `database.py`; o Postgres só é acionado para
**escrever**. Write-through: toda função de escrita atualiza o cache logo
após o commit.

## Por quê

A cota de **data transfer do Neon free estourou e derrubou a mesa**
(19/07/2026): o app lia o `users` e o `game_state` inteiros (JSONB grandes)
a cada evento de socket — cada leitura é egress cobrado. Medido com o
stress (564 checks): **2.258 conexões sem cache → ~400 com cache (−83%)**,
e as restantes são quase todas escrita (ingress, fora da cota).

## O que sustenta a decisão

- O deploy roda **UM worker** gunicorn (`-w 1`, GeventWebSocketWorker) —
  o processo é o único dono do banco, então a memória não fica obsoleta.
- O cache guarda **strings JSON** e o `get` faz `json.loads`: o chamador
  recebe exatamente o que um roundtrip pelo Postgres devolveria (chaves
  int→str, tuplas→listas, colunas canônicas de usuário via `_user_row`),
  com o mesmo isolamento de antes (cada get é uma cópia independente).
- A tabela `tables` fica **fora** do cache (app.py tem UPDATEs crus nela).
- Defaults de "linha inexistente" não entram no cache; fallback de chaves
  legadas continua e é cacheado sob a chave nova.

## ⚠️ Armadilhas para o futuro

- **Escalar para >1 worker** no Render? O cache de cada worker divergiria.
  Obrigatório setar `DB_CACHE=off` (ou implementar invalidação
  cross-process) ANTES de subir o número de workers.
- Qualquer **SQL cru novo** que escreva em users/game_state/npcs por fora
  das funções de `database.py` fura o cache — passe pelas funções ou
  chame `database.cache_reset()`.
- `DB_STATS=1` imprime o total de conexões no exit — régua rápida para
  medir regressões de consumo.

Relacionadas: [[Sistemas/mesa-e-papeis]], [[Sistemas/economia-e-seguranca]].
