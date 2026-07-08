# Postmortem — Água sem super-efetivo

**Sintoma** (report do playtest): golpes de Água não davam dano dobrado em
Fogo/Pedra/Terra — "água sem super-efetivo".

**Causa raiz**: dado corrompido na FONTE — as listas de
vulnerabilities/resistances por espécie em `server/data/pokemon.json`
estavam erradas/incompletas para vários matchups, não era bug de lógica. O
motor (`_type_lists`) lia certo um dado errado.

**Fix**: ferramenta `tools/fix_type_matchups.py` reconstruiu os matchups a
partir da tabela canônica de tipos e regravou o JSON.

**Lição**: quando efetividade/imunidade parecer errada, suspeitar do DADO
antes da lógica — o pipeline é `pokemon.json → _type_lists → eff` e o
primeiro elo é gerado por ferramenta. Rodar a auditoria
(`tools/audit_combat.py`) antes de caçar bug no motor.

Relacionadas: [[Sistemas/combate]]
