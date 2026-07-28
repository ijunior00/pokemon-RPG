# Decisão: painéis em sub-abas deslizantes (opção B do redesign)

**Data:** 2026-07-28 · **Status:** implementada (PR #40)

## Problema

Painéis com muitos fluxos empilhados numa coluna só (aba Batalhas do
mestre tinha SETE formulários + o ao-vivo misturados; Ficha do Treinador
idem). Rolagem infinita, nada respirava.

## Decisão

O mestre escolheu (entre 3 mockups) o padrão **"um fluxo por tela"**:

- **Sub-abas deslizantes** (`.subtab-bar`/`.subtab-content` no style.css,
  transição GSAP x:26→0) — reutilizáveis em qualquer página.
- **Faixa viva** no topo quando a página tem ao-vivo (toggles + chips com
  contagem que pulsam e navegam ao clicar — `.master-live-strip`).
- Última sub-aba lembrada via localStorage (`masterSubTab`,
  `playerSheetTab`).

Aplicado em: Central de Batalhas do mestre (Caçadas/Batalhas/Presentes/
Testes), Ficha do Treinador (Ficha/Perícias/Mochila), Jogadores+XP
fundidas (cartões compactos com `.xp-player-card` embutido — o socket
`xp_update` continua valendo), PvP (monitor dono da tela + desafio em
`<details>`).

## Regra de ouro (para futuras reorganizações)

**Reorganizar sem renomear**: nenhum id/handler muda — só re-parenting
de HTML. O stress não cobre layout; a garantia é (a) ids conferidos por
script após a remontagem, (b) smoke Playwright real logado como jogador
E mestre. A remontagem grande é feita por script python cortando
segmentos por linha (Edit manual em bloco gigante erra).

Relacionadas: [[Decisoes/batalha-de-vilao]] (card movido para a
sub-aba Batalhas), [[Sistemas/mesa-e-papeis]].
