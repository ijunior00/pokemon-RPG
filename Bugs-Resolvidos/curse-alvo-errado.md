# Postmortem — Curse aplicava SPE−2 no alvo errado

**Sintoma** (log de playtest Blaziken vs Haunter): o jogador usava um golpe e
o PRÓPRIO Pokémon dele aparecia com debuff de Speed — Curse do oponente
"vazando" pro lado errado.

**Causa raiz**: no roteamento de stat_changes dos moves de status, o alvo é
decidido por `effect_type == 'debuff' → alvo, senão → o próprio` — e o Curse
(que tem componente de self-buff E de debuff dependendo do tipo do usuário)
caía no ramo errado, aplicando o par buff/debuff invertido.

**Fix**: tratamento explícito do Curse na tabela de efeitos + o roteamento
dos stat_changes carrega o alvo correto por efeito, não por convenção do tipo.

**Lição**: a convenção "debuff→alvo, resto→self" é frágil para moves
híbridos (buff+debuff no mesmo uso). Ao adicionar move de status com efeitos
dos dois lados, dar entrada explícita em `STATUS_MOVE_EFFECTS` em vez de
confiar na auto-detecção por descrição.

Relacionadas: [[Sistemas/combate]]
