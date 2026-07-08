# Backlog e Ideias

## Em aberto

- **Future Sight com resolução atrasada** (2 rodadas depois) — hoje resolve
  imediato com cooldown 3; a versão atrasada precisaria de fila de eventos
  por batalha nos 3 modos. Ver [[Decisoes/sistema-combate-v3]]. (Temos que revisar isso)
- **UI de campo** — banner de clima/terreno na tela de batalha (hoje o
  estado aparece só nas linhas de log; o servidor já emite `field` no
  battle_update).
- **Ordenação completa de prioridade** — a tabela de prioridade (+4 a −6)
  vale na adjudicação do mestre; o motor implementa o subconjunto que faz
  sentido em turnos alternados.

## Decidido e adiado

- **CSP estrito** — exige tirar os scripts inline dos templates; fazer se o
  site for divulgado amplamente.
- **CAPTCHA no registro** — só se honeypot + Código de Fundador não bastarem.

- **F7 do combate** (se houver): itens seguráveis, entry hazards persistentes
  (Spikes/Stealth Rock hoje são dano fixo pontual).

## Descartado (e por quê)

- **PP dos jogos** — usuário: "Não quero PP só cooldown". O cooldown +
  momentum + adaptação cobre o mesmo objetivo (anti-spam) sem contabilidade.
- **IVs/EVs canônicos** — grind não funciona em mesa; substituído pelos
  Custom EVs ([[Decisoes/evs-customizados]]).
- **Posturas de defesa** (padrão/velocidade/contra-ataque, sistema v2) —
  substituídas pela camada de Resistência do v3; o defensor agora rola d20
  em todo golpe, o que dá a mesma agência com menos micro-gestão.
- **Sincronizar o Obsidian no branch `main`** — 2.130 arquivos/197MB, PNG de
  40MB (acima do limite do Fit) e main é deploy de produção; o vault vive no
  branch órfão `cofre`.
