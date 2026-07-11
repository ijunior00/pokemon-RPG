# Cura grátis via pivô na troca (batalha selvagem) — jul/2026

**Origem**: campanha de QA hostil (loop Mestre/Jogador A/Jogador B). Jogador B
pivotou o Pokémon ativo para o banco e de volta procurando estado inconsistente.

## O sintoma
Na batalha selvagem, trocar o Pokémon ativo para o banco e depois **voltar**
para ele restaurava o HP para o **cheio**, sem gastar item nem turno de cura.
Sustain infinito: bastava pivotar out→in a cada vez que o HP ficava baixo.

## A causa (raiz)
Durante a batalha selvagem o dano do jogador vive **só** no
`battle_state['player_hp_current']`. O `currentHp` **armazenado no time**
(`trainer_data.team[i]`) **nunca é decrementado no servidor** — quem sincroniza
isso é o cliente (`player.js`), que persiste via `/player/team` só quando quer.

O handler de troca (`battle_action`, `action_type='switch'`) lia o `currentHp`
**armazenado** do Pokémon-alvo e o injetava no `battle_state`:

```python
cur = _sw_poke.get('currentHp')       # armazenado = CHEIO (nunca decrementado)
new_hp = ...
battle_state['player_hp_current'] = new_hp
```

Como o Pokémon que **saía** nunca tinha seu HP de batalha gravado no time, ao
voltar o servidor lia o valor cheio e curava. Um cliente malicioso nem
precisava de `/player/team`: só emitir os dois `switch`.

É a **mesma classe** do exploit já fechado no Centro Pokémon
(`/player/pokemon-center` bloqueado em encontro/PvP — "era cura grátis a cada
turno") e do C2 do [[Bugs-Resolvidos/auditoria-qa-exploits-client-side]] (HP
forjado no *payload* da troca). O buraco que sobrou era o `currentHp`
**armazenado** ficar obsoleto durante a batalha.

## A correção (mínima)
Na troca, **persistir o HP de batalha do Pokémon que SAI** no time antes de
trazer o novo (por `player_pokemon_idx`, com fallback por `uid`) e `save_users`.
Espelha a mecânica real: o HP persiste através da troca. Pivotar out→in agora
devolve o Pokémon com o HP real de batalha, não o armazenado.

Arquivo: `app.py`, handler `handle_battle_action`, bloco
`action_type == 'switch' and action_by == 'player'`.

## Testes
- Regressão nova: `tests/stress.py` seção Anti-Exploit **C2b** — semeia
  encontro com ativo a 5 HP, pivota banco→ativo, exige que o HP **não** suba.
- Stress **482/482** (banco descartável). Gates de ritmo
  `battle_sweep_v3` + `battle_matrix_v3` **exit 0** (sem regressão de balanço).

## Regra de ouro reforçada
Estado que o servidor considera autoritativo em batalha (HP de batalha) tem que
ser **gravado de volta** na fonte persistente quando o contexto muda (troca) —
senão a fonte persistente vira uma via de forja/obsolescência. Toda mudança de
estado é derivada/validada no servidor.
