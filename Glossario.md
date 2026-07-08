# Glossário do projeto

| Termo | Significado |
|---|---|
| **Mesa** | Instância isolada do jogo (um mestre + jogadores). Todo estado é escopado por mesa. |
| **`_tid()`** | Helper que resolve o ID da mesa do usuário logado — obrigatório em toda query de estado. |
| **v2** | Sistema de base stats reais (1–255, pokemondb) que substituiu os atributos D&D. |
| **v3** | Sistema de combate d100/ACC + Resistência d20 + cooldown (o atual). |
| **Tabela Mestra** | Mapa POW → dados/TN/cooldown, 8 degraus (1d6…3d10). |
| **Componente de Status** | Parte fixa do dano: ⌊stat de ataque/8⌋ ± 2/estágio. |
| **TN Efetiva** | Alvo da Resistência: TN da tabela + ⌊nível do atacante/10⌋. |
| **Momentum** | +1 de dano por golpe DIFERENTE do anterior (máx +3); zera ao repetir/trocar. |
| **Adaptação em Combate** | 3ª repetição consecutiva do mesmo golpe → defensor +2 na Resistência. |
| **Certeiro** | Golpe com ACC ∞ (Swift...): pula só o teste de Precisão×Evasão; dano final ×0,90. Não atravessa imunidade/Protect/invulnerabilidade. |
| **Semi-invulnerável** | Estado de Fly/Dig/Dive...: 1 rodada fora de alcance (nem certeiro acerta); Earthquake/Thunder/Surf furam os estados correspondentes. |
| **Chip** | Dano passivo por rodada (areia/granizo ⌊HP/16⌋); nunca nocauteia (para em 1 HP). |
| **`_v3`** | Dict de estado por lado na batalha: cooldowns, last_move, streak, momentum, charging, protected. |
| **`field`** | Estado de campo da batalha: clima + terreno com durações (5 rodadas). |
| **Custom EVs** | Sistema próprio de pontos de treino (potencial + evolução + mestre), custo progressivo. |
| **Caminho do Treinador** | "Classe" do treinador: 4 caminhos, marcos nos níveis 3/6/10. |
| **lusmar** | Super-admin: aprova cadastros de mestres novos. |
| **WILD_AUTO_MODE** | Por mesa: selvagens jogam sozinhos (auto) ou o mestre conduz. |
| **Permadeath** | HP ≤ −30 em certas condições → morte permanente do Pokémon. |
| **Cofre** | Este branch: vault Obsidian com a memória do projeto. |
