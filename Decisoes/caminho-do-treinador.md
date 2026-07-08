# Decisão — Caminho do Treinador

**Status**: implementado (PR #15).

## O que é

Progressão de *classe* para o treinador humano: 4 caminhos temáticos, cada um
com marcos nos níveis **3 / 6 / 10** que destravam escolhas (Talentos). O
jogador escolhe o caminho uma vez (o mestre pode resetar).

## Por quê

Os Pokémon tinham progressão rica ([[Decisoes/evs-customizados]]) mas o
treinador só subia número. O caminho dá identidade de mesa (o "domador", o
"estrategista"...) sem virar árvore de skills gigante — 3 marcos por caminho
é o suficiente pra sentir build sem afogar o mestre em regra.

## Como pluga

- Dados dos caminhos e helpers de bônus em `trainer_attrs.py`;
- Bônus entram nas mecânicas existentes (captura, caçada, iniciativa, loja)
  pelos mesmos pontos de integração dos 6 atributos
  ([[Decisoes/atributos-do-treinador]]);
- Endpoint de escolha + reset do mestre em `app.py`; UI com seletor e
  escolhas por marco na ficha do jogador.

Relacionadas: [[Decisoes/atributos-do-treinador]], [[Sistemas/mesa-e-papeis]]
