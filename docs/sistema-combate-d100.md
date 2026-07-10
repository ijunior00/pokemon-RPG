# Sistema de Combate Pokémon RPG — v3 "d100/ACC"
### Precisão (d100) → Dano (Status + POW) → Resistência (d20)

> **Prompt definitivo** consolidando a transição d20 → d100. O d20 deixa de ser
> a camada de acerto e passa a ser exclusivamente a camada **defensiva**
> (Resistência/Esquiva). A precisão agora é do **golpe** (ACC canônico vs d100).
> Vale igualmente para selvagens, PvP e NPCs — a fórmula não distingue quem
> ataca, só os status e o nível envolvidos.

---

## 0. Identidade do sistema (o que mudou e por quê)

| Antes (d20) | Agora (v3) |
|---|---|
| d20 decidia acerto E crítico | **d100 vs ACC** decide se o golpe *conecta* |
| Defesa era denominador do dano | **d20 + Defesa + Nível** decide *quanto* do golpe é sentido |
| Uma rolagem concorria com a accuracy | Duas camadas independentes e complementares |

Um Fire Blast pode acertar — e mesmo assim "fazer cócegas" num alvo tanque.
**100% de acerto significa que o golpe conecta, nunca que machuca garantidamente.**

---

## 1. TABELA MESTRA (POW → dados, TN, cooldown)

Tudo no sistema deriva desta única tabela. 8 degraus, monotônica
(média dos dados sempre cresce: 3,5 → 4,5 → 5,5 → 7 → 9 → 10,5 → 13,5 → 16,5).

| POW do golpe | Dados de dano | TN de Resistência | Cooldown |
|---|---|---|---|
| ≤ 35 (fraco) | **1d6** | 10 | — |
| 36–50 | **1d8** | 12 | — |
| 51–65 | **1d10** | 14 | — |
| 66–80 (médio) | **2d6** | 16 | — |
| 81–95 (médio-alto) | **2d8** | 18 | **1 rodada** |
| 96–110 (alto) | **3d6** | 20 | **2 rodadas** |
| 111–125 (devastador) | **3d8** | 22 | **3 rodadas** |
| 126+ (cataclísmico) | **3d10** | 24 | **3 rodadas** |

Exemplos canônicos: Tackle 40 → 1d8 · Aerial Ace 60 → 1d10 · Slash 70 → 2d6 ·
Flamethrower 90 → 2d8 · Earthquake 100 / Thunder 110 / Fire Blast 110 → 3d6 ·
Future Sight 120 → 3d8 · Hyper Beam 150 → 3d10.

---

## 2. Camada 1 — Precisão (d100 vs ACC)

O atacante rola **1d100**. Conecta se o resultado for **≤ ACC Efetivo**.

```
ACC Efetivo = ACC Base
            + (estágios de Precisão do atacante × 10)
            − (estágios de Evasão do alvo × 10)
            ± modificadores de clima (Seção 12)
```

**Travas duras (sem exceções por acúmulo de buffs):**
- **Teto 100** — golpes de 85/90/95 nunca "viram" 100 por stacking.
- **Piso 5** — nem evasão máxima zera a chance de conectar.
- Só têm 100% real os golpes que **nascem** com ACC 100 (ou Certeiros, Seção 8).
- Exceção canônica legítima: propriedades do próprio move em clima
  (Thunder/Hurricane na Chuva = ACC 100; Blizzard na Neve = ACC 100) — o move
  "nasce" 100 naquele clima, não é stacking.

**Efeito secundário no mesmo dado (regra de mesa):** um único d100 resolve
conexão **e** efeito secundário — se o resultado também for ≤ chance do efeito
(Ember 10%, Scald 30%…), o efeito aplica. Uma rolagem, dois usos.

**Moves de status** (Growl, Thunder Wave, Sing…): rolam só esta camada
(d100 vs ACC do move). Não passam pela Resistência.

---

## 3. Camada 2 — Dano (Status Base + Dado de POW)

```
Dano Bruto = Componente de Status + Bônus de Nível + Rolagem de Dados + Momentum
```

### 3.1 Componente de Status
```
Componente = ⌊(Ataque ou Ataque Especial relevante) ÷ 8⌋   (mínimo 1)
```
O divisor **8** é a constante-mestra de calibração (Seção 20).

### 3.2 Bônus de Nível (curva suave)
```
Bônus de Nível = ⌊Nível ÷ 10⌋
```

### 3.3 Dados do golpe (curva em degraus)
Dados-base pela **Tabela Mestra** + modificadores, nesta ordem:

1. **Certeiro?** rebaixa 1 degrau (Seção 8)
2. **Marcos de nível** (acumulativo): Nv 25 → +1 dado · Nv 50 → +2 · Nv 75 → +3 · Nv 100 → +4
3. **STAB** (tipo do golpe = tipo do usuário): **+1 dado a partir do Nv 25**
   (1º marco). Antes do Nv 25, STAB = **+2 fixo no Dano Bruto** — dobrar os
   dados no early game derrubava as batalhas de nível baixo para ~4 rodadas
   (validado por simulação).
4. **Efetividade de tipo**: ×2 → **+1 dado** · ×4 → **+2 dados** · ×½ → **−1 dado** · ×¼ → **−2 dados** · **Imune → dano 0** (conecta, mas não afeta)
5. **Clima/Terreno** (Seções 12–13): ±1 dado conforme a tabela

*Se as reduções levarem abaixo de 1 dado, rola-se 1 dado e o resultado é
dividido por 2 (arredondado para baixo, mínimo 1).* Os dados extras são sempre
**do mesmo tipo** do dado-base do golpe.

> **Progressão dupla resolvida:** status cresce suave e constante (+1/10 níveis);
> dados crescem em picos sensíveis (25/50/75/100). Nenhuma fonte domina a outra
> — o Pokémon nunca para de crescer, e nunca cresce rápido demais numa fonte só.

---

## 4. Camada 3 — Resistência/Esquiva (d20 do defensor)

Todo golpe que conecta ainda passa pelo teste do defensor:

```
Resultado = 1d20 + ⌊Defesa relevante ÷ 10⌋ + ⌊Nível ÷ 10⌋ + estágios de DEF/SpD ± modificadores
```
- **Defesa** contra golpes físicos; **Defesa Especial** contra especiais.
- **TN Efetiva = TN da Tabela Mestra + ⌊Nível do ATACANTE ÷ 10⌋.**
  Sem este termo, o bônus do defensor (Defesa+Nível) cresce com o nível
  enquanto a TN fica parada — em nível alto TUDO viraria anulação e as
  batalhas nunca terminariam. Com ele, os termos de nível dos dois lados se
  cancelam em confrontos de nível igual, e a Resistência continua relevante
  do Nv 5 ao Nv 100.

| Resultado vs TN | Efeito |
|---|---|
| ≥ TN + 10 | **Esquiva/Anulação total** — dano 0 |
| ≥ TN (até +9) | **Resistência parcial** — dano ÷ 2 (arred. p/ baixo) |
| < TN | **Falha** — dano cheio |

**Empate técnico (Speed importa):** se o resultado ficar a **exatamente 1 ponto
da faixa superior** (TN−1, quase-parcial; ou TN+9, quase-anulação), compara-se
Speed: **defensor mais rápido** que o atacante → sobe para a faixa superior.
Caso contrário, vale a faixa normal. *(Corrigido: a versão anterior falava em
"cair na TN", que tornaria o empate melhor que passar com folga.)*

**Dano mínimo:** se a faixa for "cheio" ou "parcial", o dano final nunca é
menor que 1.

---

## 5. Crítico unificado (d100, pós-conexão)

Depois que o golpe conecta, rola-se **1d100 de crítico**:

```
Chance de crítico = 5% base + 10 p.p. por estágio de crítico   (teto 50%)
```

| Fonte | Estágios |
|---|---|
| Golpes de alta taxa (Slash, Night Slash, Stone Edge, Razor Leaf…) | +1 |
| Super Luck (passiva) | +1 |
| Scope Lens (item) | +1 |
| **Focus Energy** (move) | **+2** (dura até sair de campo) |

**Efeito do crítico:** em vez de dobrar dano, o crítico **fura a defesa** —
na Resistência do alvo, o bônus de Defesa (⌊Def÷10⌋) e os estágios positivos de
DEF/SpD contam **pela metade** (arred. p/ baixo). Pokémon frágeis continuam
sofrendo normalmente; muralhas defensivas deixam de ser imortais.
**Battle Armor / Shell Armor**: imunes a crítico.

---

## 6. Cooldown (substitui o PP — não existe PP)

- O cooldown vem da **Tabela Mestra**: POW 81–95 → 1 rodada · 96–110 → 2 · 111+ → 3.
- Após usar o golpe, o Pokémon precisa esperar esse nº de **rodadas de batalha**
  antes de reutilizá-lo (a contagem continua mesmo se ele for trocado — trocar
  não zera cooldown).
- Objetivo: acabar com o "aperta só o move mais forte". Os golpes de POW menor
  (sem cooldown) são o arroz-com-feijão; os devastadores são momentos.

---

## 7. Prioridade (quebra a regra da Speed)

Ordem de ação: **maior prioridade age primeiro**; empate de prioridade → maior
Speed; empate de Speed → 1d20 de desempate.

| Prioridade | Exemplos |
|---|---|
| +4 | Protect, Detect (só defensivos) |
| +3 | Fake Out (apenas na 1ª rodada em campo), Quick Guard |
| +2 | Extreme Speed, Feint |
| +1 | Quick Attack, Mach Punch, Aqua Jet, Ice Shard, Bullet Punch, Shadow Sneak, Vacuum Wave, Sucker Punch |
| 0 | todos os demais |
| −4 a −6 | Counter/Mirror Coat (−5), Roar/Whirlwind (−6) |

**Protect/Detect:** bloqueia o golpe recebido na rodada. Usos **consecutivos**
caem pela metade: 100% → 50% → 25%… (teste no d100). Errou = falhou e a corrente
reinicia.

### 7.1 Iniciativa (quem começa a batalha)

**Fórmula:** `1d20 + ⌊SPE_efetivo / 5⌋ (+ Tática do treinador, 0 a +2)`

O SPE efetivo entra com estágios, paralisia (×0,5), natureza e treino — um
Pokémon paralisado ou com a Speed rebaixada realmente perde iniciativa.

Ordem de decisão:

1. **Upset 20 vs 1** — se o mais LENTO tira **20 natural** e o mais rápido tira
   **1 natural**, o lento age primeiro, ignorando modificadores (1/400 ≈ 0,25%).
   É a "virada lendária": rara, mas sempre possível.
2. Maior **total**.
3. Empate de total → maior **SPE efetivo**.
4. Empate completo → jogador (ou player1 no PvP).

Por que ⌊SPE/5⌋ (antes era ⌊SPE/10⌋): o d20 tem amplitude 19; com /10 o bônus
típico (+1 a +9 nos níveis 10-30) deixava a sorte decidir a ordem. Com /5 a
Speed vira o fator principal e o dado vira o imprevisto. Probabilidade de o
mais lento agir primeiro, por gap `g` de bônus — `P = (19−g)(20−g)/800`:

| Diferença de Speed base (Nv 50) | Gap de bônus | P(lento primeiro) |
|---|---|---|
| ±15 (ex.: 75 vs 90) | ~3 | ~34% — disputa equilibrada |
| ±30 (ex.: 60 vs 90) | ~6 | ~23% — favorece o rápido |
| ±60 (ex.: 30 vs 90) | ~12 | ~7% — rápido domina |
| ±100+ (ex.: 30 vs 150) | ≥19 | 0,25% — só pela regra do 20 vs 1 |

**Batalha em grupo:** cada combatente rola `1d20 + ⌊SPE_eff/5⌋ + Tática` e a
ordem é decrescente; empate de total → maior SPE efetivo. A regra do 20 vs 1
não se aplica (só faz sentido em duelo).

---

## 8. Precisão 100% vs ACC ∞ (Certeiros: Aerial Ace, Swift, Shock Wave…)

**ACC 100% NÃO é acerto garantido** — é só a precisão *base*. O golpe continua
sujeito a:
- estágios de **Precisão** do usuário (Sand Attack, Mud-Slap, Flash → −10 p.p.
  por estágio) e de **Evasão** do alvo (Double Team, Minimize → −10 p.p.);
- **Névoa** (−10 ACC global) e demais efeitos de campo.

**ACC ∞ (golpes com ACC "—")** ignora **apenas** o teste de Precisão×Evasão:
- Não rola d100 de acerto; estágios de Precisão/Evasão são irrelevantes.
- **Compensação pela confiabilidade: dano final ×0,90** (aplicado DEPOIS da
  Resistência; alavanca `V3_CERTEIRO_DAMAGE_MULT` — conservador 0,95,
  competitivo 0,85). Componente e dados são os NORMAIS do golpe.

**O que NENHUM dos dois atravessa** (nem ACC 100, nem ACC ∞):
1. **Imunidade de tipo** (Elétrico vs Terrestre, Normal/Lutador vs Fantasma…)
   — checada ANTES de qualquer rolagem;
2. **Habilidades** que anulam/absorvem (Levitate, Flash Fire, Volt/Water
   Absorb, Motor Drive, Sap Sipper, Storm Drain, Lightning Rod, Wonder Guard);
3. **Protect/Detect** e equivalentes;
4. **Estados invulneráveis** (alvo que usou Fly, Bounce, Dig, Dive, Phantom
   Force, Shadow Force, Sky Drop — ver §17), salvo as exceções canônicas do
   golpe (Earthquake acerta quem cavou; Thunder/Gust/Hurricane acertam quem
   voou; Surf/Whirlpool acertam quem mergulhou);
5. **Resistência do defensor (§4)** — a garantia é de *conectar*, nunca de
   atravessar as defesas.

Certeiro = excelente contra times de evasão, e sempre um tico mais fraco
(×0,9) que o golpe equivalente que pode errar.

---

## 9. Regra universal de estágios (buffs e debuffs)

**Todos** os moves de buff/debuff e passivas usam a mesma gramática — nenhum
efeito inventa matemática própria. Clamp: **±6 estágios** por stat.

| Estágio em… | Efeito por estágio (±) |
|---|---|
| **ATK / Sp.ATK** | ±2 no Componente de Status (mínimo 1) |
| **DEF / Sp.DEF** | ±1 na rolagem de Resistência |
| **Precisão** | ±10 no ACC Efetivo (respeitando teto 100 / piso 5) |
| **Evasão** | ∓10 no ACC Efetivo do oponente |
| **Speed** | ±25% de Speed (iniciativa, desempates, reflexos) |
| **Crítico** | +10 p.p. na chance de crítico |

Exemplos canônicos mapeados:

| Move | Efeito no sistema |
|---|---|
| Growl | alvo: −1 estágio ATK (−2 no Componente físico dele) |
| Swords Dance | usuário: +2 ATK (+4 no Componente físico) |
| Iron Defense | usuário: +2 DEF (+2 na Resistência física) |
| Calm Mind | usuário: +1 Sp.ATK e +1 Sp.DEF |
| Sand Attack | alvo: −1 Precisão (−10 ACC nos golpes dele) |
| Double Team | usuário: +1 Evasão (−10 ACC dos golpes contra ele) |
| Agility | usuário: +2 Speed |
| Focus Energy | usuário: +2 estágios de crítico |
| Screech | alvo: −2 DEF (−2 na Resistência física dele) |

---

## 10. Habilidades passivas — regra universal

**Nenhuma passiva soma dano direto.** Toda passiva modifica apenas:
**estágios/status · precisão · resistência · dados · cooldown · condições ·
ordem de ação.** Assim todas usam a mesma matemática. Mapeamento de referência
(as demais seguem a mesma gramática):

| Passiva | Efeito no sistema |
|---|---|
| **Solar Power** (Charizard) | sob Sol: +2 estágios Sp.ATK; perde ⌊HPmáx/16⌋ por rodada |
| **Super Luck** (Absol) | +1 estágio de crítico permanente |
| Guts | com condição de status: +2 estágios ATK e ignora o corte do Burn |
| Huge Power / Pure Power | Ataque conta em dobro para o Componente de Status |
| Intimidate | ao entrar: −1 estágio ATK do oponente |
| Compound Eyes | +1 estágio de Precisão permanente (+10 ACC) |
| Sand Veil / Snow Cloak | +1 Evasão no clima correspondente |
| Sniper | crítico: a Defesa do alvo conta **zero** na Resistência (em vez de metade) |
| Battle Armor / Shell Armor | imune a crítico |
| Sturdy | com HP cheio, sobrevive a 1 HP de um golpe fatal |
| Levitate | imune a golpes de Terra |
| Static / Flame Body / Poison Point | 25% de aplicar a condição em quem acerta golpe de contato (d100) |
| Speed Boost | +1 estágio de Speed ao fim de cada rodada |
| Swift Swim / Chlorophyll / Sand Rush / Slush Rush | Speed em dobro no clima correspondente |
| Technician | golpes de POW ≤ 60: +1 dado |
| Blaze / Torrent / Overgrow / Swarm | HP ≤ 25%: golpes do tipo ganham +1 dado |

---

## 11. Condições de status (identidade completa)

| Condição | Efeito no sistema |
|---|---|
| **Burn** | ⌊HPmáx/16⌋ por rodada; **Componente de Status físico pela metade** |
| **Poison** | ⌊HPmáx/10⌋ por rodada |
| **Toxic** | ⌊HPmáx/16⌋ na 1ª rodada, **+⌊HPmáx/16⌋ acumulando** a cada rodada |
| **Paralysis** | Speed pela metade; a cada ação, d100 ≤ 25 → perde a ação |
| **Sleep** | dorme 1d3 rodadas, sem agir |
| **Freeze** | não age; a cada rodada d100 ≤ 20 → descongela; golpe de Fogo recebido descongela na hora |
| **Confusion** | dura 1d3 rodadas; antes de agir, d100 ≤ 33 → acerta a si mesmo (1d6 + metade do próprio Componente físico, sem Resistência) |
| **Flinch** | perde a ação da rodada (só funciona se o causador agiu antes) |

Imunidades canônicas valem (Elétrico não paralisa, Fogo não queima,
Veneno/Aço não envenenam etc.), assim como passivas (Limber, Water Veil,
Insomnia, Immunity…).

---

## 12. Clima (5 rodadas, um por vez)

| Clima | Efeitos |
|---|---|
| **Sol** | Fogo +1 dado; Água −1 dado; Solar Power ativa; Solar Beam sem carregar; Thunder/Hurricane ACC 50 |
| **Chuva** | Água +1 dado; Fogo −1 dado; Thunder/Hurricane ACC 100 |
| **T. de Areia** | ⌊HPmáx/16⌋/rodada em não-Pedra/Terra/Aço; Pedra: +2 na Resistência especial |
| **Neve/Granizo** | ⌊HPmáx/16⌋/rodada em não-Gelo; Gelo: +2 na Resistência física; Blizzard ACC 100 |
| **Névoa** | −10 ACC global (todos) |

Invocado por moves (Rain Dance, Sunny Day…) ou passivas (Drizzle, Drought…).

## 13. Terreno (5 rodadas, afeta quem toca o chão)

| Terreno | Efeitos |
|---|---|
| **Grassy** | Grama +1 dado; cura ⌊HPmáx/16⌋/rodada; Earthquake −1 dado |
| **Electric** | Elétrico +1 dado; imunidade a Sleep |
| **Psychic** | Psíquico +1 dado; bloqueia golpes de prioridade contra quem está no terreno |
| **Misty** | Dragão −1 dado; imunidade a condições de status |

---

## 14. Momentum (recompensa por variar)

*Definição consolidada (era citada mas não estava especificada):*

- Cada vez que o Pokémon usa um golpe **diferente** do que usou na rodada
  anterior: **+1 de Momentum** (máximo **+3**).
- O Momentum atual **soma direto no Dano Bruto** do golpe.
- **Zera** ao repetir o golpe da rodada anterior, ao trocar de Pokémon ou ao ser
  nocauteado.

É a cenoura; a Adaptação (abaixo) é o chicote; o Cooldown é a trava. Os três
juntos fazem "apertar Fire Blast toda rodada" ser a pior estratégia possível.

## 15. Adaptação em Combate (punição por repetir)

- Ao usar **o mesmo golpe pela 3ª vez consecutiva contra o mesmo alvo**, o
  adversário compreende o padrão: enquanto a repetição continuar, o defensor
  ganha **+2 na Resistência** contra esse golpe.
- Termina quando: o usuário usa outro golpe · troca de Pokémon · o alvo é
  derrotado ou substituído.

Cobre exatamente o buraco que o Cooldown não cobre: spam de golpes fracos/médios
(que não têm cooldown).

---

## 16. Shiny (+35% em todos os status)

Shinies aplicam **×1,35** a HP, ATK, DEF, Sp.ATK, Sp.DEF e Speed **antes** de
qualquer fórmula.

- O bônus **NÃO entra na precisão** (Seção 2) — accuracy é do golpe, não do
  corpo: um Charizard shiny não lança um Thunder mais preciso.
- Entra naturalmente em: **dano** (Componente maior), **Resistência** (Defesa
  maior), **HP** e **Speed** (iniciativa/desempates/reflexos).
- Como o bônus é **simétrico** (vale atacando e defendendo), a proporção entre
  todos os Pokémon do jogo permanece consistente — o shiny é mais forte nos
  dois lados da moeda, nunca em um só.

---

## 17. Casos especiais

| Caso | Regra |
|---|---|
| **Multi-hit** (Double Kick, Rock Blast…) | 1 rolagem de ACC; nº de hits: 2 fixos ou 1d4+1 (moves 2-5); o Componente de Status soma **uma vez**; cada hit rola só os dados; **uma** Resistência vale para todos |
| **Dano fixo** (Seismic Toss, Night Shade) | dano = Nível do usuário; sem dados, sem Componente; Resistência normal aplica |
| **OHKO** (Fissure, Guillotine…) | ACC 30 fixo (ignora estágios); se conectar: Resistência vs **TN 22** — qualquer sucesso (parcial ou total) anula tudo; falha total = nocaute |
| **Recoil** (Double-Edge, Flare Blitz…) | usuário sofre ⌊dano final ÷ 3⌋ |
| **Dreno** (Giga Drain, Drain Punch…) | usuário cura ⌊dano final ÷ 2⌋ |
| **Carga** (Solar Beam, Sky Attack…) | 1 rodada carregando (salvo exceção: Solar Beam no Sol dispara direto) |
| **Semi-invulnerável** (Fly, Bounce, Dig, Dive, Phantom Force, Shadow Force, Sky Drop) | 1 rodada de preparo em que o usuário fica FORA DE ALCANCE (nem certeiros acertam); exceções canônicas atravessam: Earthquake/Magnitude/Fissure acertam quem cavou; Gust/Twister/Thunder/Hurricane/Sky Uppercut/Smack Down acertam quem voou; Surf/Whirlpool acertam quem mergulhou. Trocar de golpe ou de Pokémon perde o preparo |
| **Future Sight** | resolve 2 rodadas depois com os dados/TN do POW 120; entra em cooldown normalmente ao declarar |

**Notas de implementação (F5, motor digital):**
- **Recoil e chip de clima nunca nocauteiam**: deixam o usuário/alvo em 1 HP —
  quem decide o nocaute é sempre um golpe. Regra de mesa (evita anticlímax de
  morrer para a própria Take Down ou para a areia).
- **Future Sight (simplificado)**: no motor resolve imediato como ataque POW
  120 com cooldown 3. A versão "2 rodadas depois" fica como regra narrada pelo
  mestre na mesa até a F7.
- **Prioridade no motor**: como os turnos alternam (não são simultâneos), a
  prioridade atua onde a Speed decidiria: (a) desempates da Resistência
  (§4 — o golpe de prioridade conta como "mais rápido"; prioridade negativa
  conta como "mais lento"), (b) Psychic Terrain bloqueia golpes de prioridade
  contra alvos no chão, (c) Protect/Detect com a corrente 100%→50%→25%…
  A ordem completa da tabela (§7) vale na adjudicação manual do mestre.
- **IA**: selvagens/NPCs nunca desperdiçam a carga (disparam o golpe carregado
  na rodada seguinte) e não escolhem golpes em cooldown.

---

## 18. Fluxo completo de uma rodada

1. **Ordem**: prioridade → Speed → d20 de desempate.
2. Na vez de cada Pokémon:
   a. Golpe em **cooldown**? Não pode ser escolhido.
   b. Testes de condição (Paralysis d100≤25, Sleep, Freeze, Confusion).
   c. **Bloqueios absolutos**, nesta ordem: Protect do alvo → alvo
      invulnerável (Fly/Dig…, salvo exceção do golpe) → **imunidade de tipo**
      → habilidade que anula/absorve. Qualquer um → fim da ação.
   d. **Precisão**: calcula ACC Efetivo → rola **d100**. Certeiro (ACC ∞)
      pula este passo. Errou → fim da ação. (O mesmo d100 resolve efeito
      secundário.)
   e. **Crítico**: d100 vs chance (5% + estágios).
   f. **Dano Bruto** = Componente (+estágios ATK) + ⌊Nível/10⌋ + dados
      (Tabela Mestra → marcos → STAB → efetividade → clima/terreno)
      + Momentum.
   g. **Resistência** do defensor: d20 + ⌊Def/10⌋ + ⌊Nível/10⌋ + estágios
      (crítico corta esses bônus pela metade) vs TN → cheio / metade / zero.
      **Certeiro: aplicar ×0,90 ao dano final** depois desta camada.
      (empate exato → Speed decide).
   h. Aplica dano (mínimo 1 se não anulado), efeitos on-hit, contadores de
      Momentum/Adaptação, inicia cooldown.
3. **Fim da rodada**: dano de Burn/Poison/Toxic e clima; cura de terreno;
   decrementa cooldowns, durações de clima/terreno, Sleep/Confusion.

---

## 19. Exemplo completo (recalculado nesta versão)

**Charizard Nv 50** usa **Flamethrower** (Fogo, POW 90, ACC 100) contra
**Snorlax Nv 50** (SpD 65). Charizard variou de golpe na rodada anterior
(Momentum +1).

- **Precisão:** ACC 100 puro → conecta sem rolar.
- **Crítico:** d100 → 47 vs 5% → não crita.
- **Dano Bruto:**
  - Componente: Sp.ATK 109 → ⌊109/8⌋ = **13**
  - Bônus de Nível: ⌊50/10⌋ = **5**
  - Dados: POW 90 → 2d8 base **+2 marcos** (Nv 25 e 50) **+1 STAB** = **5d8** → rola **22**
  - Momentum: **+1**
  - Bruto = 13 + 5 + 22 + 1 = **41**
- **Resistência do Snorlax:** d20(12) + ⌊65/10⌋=6 + ⌊50/10⌋=5 = **23**
  vs TN Efetiva 18 + ⌊50/10⌋ = **23** (POW 81–95, atacante Nv 50)
  → faixa 23–32 → **parcial: dano ÷ 2**
- **Dano final: 20.** Flamethrower entra em **cooldown de 1 rodada**.

Mesmo um golpe ACC 100 / POW alto foi sentido pela metade graças à Sp.DEF e ao
nível do Snorlax — exatamente o equilíbrio pedido.

---

## 20. Calibração (as únicas alavancas livres)

1. **Divisor 8** do Componente de Status (Seção 3.1).
2. **Coluna de TN** da Tabela Mestra (deslocá-la inteira ±2).
3. **Redutor do ACC ∞** (`V3_CERTEIRO_DAMAGE_MULT`): padrão **0,90**;
   conservador 0,95; competitivo 0,85 (Seção 8).

**Alvo oficial da mesa: batalhas de 5 a 10 turnos** (mediana por faixa de
nível, validada por `tools/battle_sweep_v3.py` — 500 batalhas completas por
cenário, com precisão, crítico e resistência dos dois lados):

| Cenário | Mediana | p10–p90 |
|---|---|---|
| Nv 15 iniciais (POW 60) | 5,0 | 4–6 |
| Nv 40 equilibrados (POW 90) | 5,0 | 4–6 |
| Nv 40 sweeper vs tanque | 6,0 | 5–7 |
| Nv 60 fortes (POW 100) | 6,0 | 5–7 |
| Nv 80 endgame (POW 110, ACC 85) | 8,0 | 6–10 |
| Nv 100 lendários (POW 120, ACC 90) | 6,0 | 5–8 |

Calibrações que fizeram a janela fechar (documentadas nas seções 3.3 e 4):
- **Teto de +12 no bônus de Defesa** da Resistência — ⌊def/10⌋ chegava a +20
  no Nv 100 e dominava o d20 (anulação eterna, batalhas de 13+ rodadas).
- **STAB pré-Nv 25 = +2 fixo** (o dado extra chega no 1º marco) — dobrar dados
  no early game derrubava o Nv 15 para 4 rodadas.

Ajuste **uma alavanca por vez** (V3_STATUS_DIVISOR, V3_TN_SHIFT,
V3_DEF_BONUS_CAP) e re-rode o sweep até a mediana de todos os cenários cair
na janela.

Regras de ouro do balanceamento:
- Nenhum efeito cria matemática própria: tudo passa por **estágios, dados, ACC,
  Resistência, cooldown ou condições**.
- Teto 100 / piso 5 no ACC são invioláveis por stacking.
- A Tabela Mestra é a única fonte de dados/TN/cooldown — mudou lá, mudou em
  tudo, e o sistema permanece interligado.
