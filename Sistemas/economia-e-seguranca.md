# Sistema — Economia de itens e segurança de acesso

## Economia (jul/2026, PR #19)

- **Loja**: compra/venda resolvidas 100% no servidor (dinheiro + bolsa
  atômicos); preços modulados por 👑 Influência. O bug relatado de "comprei e
  não apareceu" era só o cliente não re-renderizar a aba Bolsa.
- **Apostas PvP**: transferidas de verdade da ficha do perdedor (dinheiro e
  itens, limitado ao que ele TEM — nada é cunhado). Rua: 25% do dinheiro + 2
  itens aleatórios.
- **NPCs têm ficha econômica**: nascem com **₽3000 + 5 Pokébola, 3 Poção,
  1 Super Poção** (antigos migram na primeira leitura); ganham ₽100–400 por
  dia de jogo e às vezes compram um item (diário registra). Espólio de
  batalha de rua sai/entra do bolso REAL do NPC (`_party_sheet` no
  `handle_pvp_victory` resolve jogador OU NPC).
- **🎁 Presentes do Mestre**: `/master/give-pokemon` (espécie/nível/shiny/
  apelido, escalado no servidor, time→PC, pokédex, notificação) e
  `/master/give-item` (catálogo ou item de história de nome livre —
  não-vendável — e/ou dinheiro). Painel na tela do mestre.

## Segurança de acesso (jul/2026, PR #19)

Gatilho: bots acharam o `/register` público antes da divulgação do site.

| Camada | Defesa |
|---|---|
| Registro | honeypot invisível (sucesso falso p/ bot) · **Código de Fundador** p/ mestres (`MASTER_SIGNUP_CODE` no Render, opcional) · username [A-Za-z0-9_]{3,20} · senha ≥8 |
| Login | rate-limit por IP (10/min) + **lockout por conta** (5 falhas → ~10 min, independe de IP) |
| Sessão | cookies HttpOnly + SameSite=Lax (anti-CSRF sem token) + Secure em produção |
| Respostas | X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, HSTS em prod |
| Já existia | aprovação de mestre pelo super-admin lusmar · convite p/ jogador · hash de senha · `_tid()` em toda query |

Descartado consciente: CAPTCHA (UX; honeypot+código bastam no volume atual)
e CSP estrito (quebraria scripts inline — ver [[Backlog-Ideias]]).

Relacionadas: [[Sistemas/mesa-e-papeis]]
