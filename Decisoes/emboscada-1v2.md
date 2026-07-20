# Emboscada = 1v2 no motor de grupo (Nat 1 na caçada)

**Decisão (2026-07):** o Nat 1 no Teste de Caçada (🧭 Exploração) vira uma
**batalha 1v2** — um jogador cercado por dois selvagens — reusando o motor da
batalha em grupo (`group_battle.py`), como espelho do 2v1 que já existia.

## Como funciona

1. `api_hunt_roll` guarda o **d20 cru** (`last_roll`) na entrada de caçadas
   do jogador (estado por mesa, JSONB).
2. Quando o mestre libera a **Caçada Aleatória** para esse jogador,
   `master_hunt_random` consome o `last_roll` (1 rolagem = 1 liberação); se
   foi 1 → cria batalha de grupo com 1 aliado + 2 selvagens da rota e
   `battle['ambush'] = True`. O mestre também pode **forçar** pelo checkbox
   "💀 Emboscada 1v2" (payload `is_ambush`).
3. `build_battle` rotula o modo genericamente como `NvM`
   (`f'{len(allies)}v{len(wilds)}'`) — 2v1/2v2 continuam iguais, 1v2 é a
   emboscada. `state_view` expõe `ambush`.

## Escolhas de design (e porquês)

- **Servidor detecta o Nat 1 sozinho** (estado, não payload do cliente):
  o mestre não precisa lembrar, e ninguém forja/escapa da emboscada por
  request. O flag antigo `is_ambush` continua como override do mestre.
- **Selvagens na faixa NORMAL da rota** — o ambush 1v1 antigo dava +5..10 de
  nível; no 1v2 o castigo já é a desvantagem numérica (2 ações inimigas por
  rodada). Nível alto + 2v1 contra seria massacre, não tensão.
- **Sem fuga**: `battle['ambush']` bloqueia o flee no servidor ("vença ou
  desmaie") e some com o botão 🏃. Válvula de escape da mesa = o mestre pode
  ⏹ Finalizar a batalha (rota force-end, sem XP).
- **Tudo do motor de grupo vale de graça**: captura por Pokébola
  (`/player/capture` com `battle_id`), reidratação pós-refresh
  (`/player/battle/active`), modo manual do selvagem, espectador.

## Armadilha de teste (flake real)

As rolagens **virtuais** do stress podem tirar Nat 1 por sorte → o
`hunt/random` seguinte viraria 1v2 e quebraria asserts de encontro 1v1.
`tests/stress.py` tem `clear_nat1(uid)` e chama antes dos hunt/random
antigos. Qualquer teste novo que role caçada virtual e depois espere
encontro comum precisa do mesmo cuidado.

Relacionadas: [[Sistemas/combate]], [[Decisoes/sistema-combate-v3]].
