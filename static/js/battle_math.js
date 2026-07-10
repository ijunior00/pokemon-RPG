/* battle_math.js — ESPELHO 1:1 de battle_math.py (fonte única das fórmulas
   de combate do sistema de base stats reais 1-255).
   Qualquer mudança aqui precisa ser replicada no battle_math.py. */

const BattleMath = (() => {
    // ── Constantes de balanceamento ──
    const RATIO_CLAMP = [0.5, 2.0];
    const STAB_MULT = 1.5;
    // Escala GLOBAL de dano (espelho do battle_math.py): levemente crescente
    // com o nível porque o HP cresce mais rápido que os dados.
    // Antigo equivalente: 1.0 em todos os níveis (janela de 2-4 turnos).
    const DAMAGE_SCALE_BASE = 0.30;   // espelho de battle_math.py (batalhas mais curtas)
    const DAMAGE_SCALE_PER_LEVEL = 0.0003;
    function damageScale(level) {
        return DAMAGE_SCALE_BASE + DAMAGE_SCALE_PER_LEVEL * Math.max(1, level || 50);
    }
    const TRAINING_POINTS_PER_LEVEL = 4;
    const TRAINING_CAP = 63;
    const LEVEL_TIERS = [[80, 3.0], [60, 2.5], [40, 2.0], [20, 1.5], [10, 1.25]];

    const DEFENSE_MODES = {
        1: { physical: 'DEF', special: 'SPD', tax: 1.0,  label: '🛡️ Padrão' },
        2: { physical: 'SPE', special: 'SPE', tax: 1.25, label: '💨 Velocidade' },
        3: { physical: 'ATK', special: 'SPA', tax: 1.5,  label: '⚔️ Contra-ataque' },
    };

    const FIXED_DAMAGE_FORMULAS = {
        'seismic toss': (level) => level,
        'night shade':  (level) => level,
        'dragon rage':  (level) => 15 + Math.floor(level / 4),
        'sonic boom':   (level) => 10 + Math.floor(level / 5),
        'super fang':   (level, targetHp) => Math.max(1, Math.floor((targetHp || 2) / 2)),
    };

    // ── Stats por nível ──
    function statAtLevel(base, level, training = 0) {
        return Math.floor((2 * base * level) / 100) + 5 + (training || 0);
    }
    function hpAtLevel(baseHp, level) {
        return Math.floor((2 * baseHp * level) / 100) + level + 10;
    }
    function trainingBudget(level) {
        return TRAINING_POINTS_PER_LEVEL * (Math.max(1, level) - 1);
    }
    function trainingCap(level) {
        return Math.min(TRAINING_CAP, Math.max(1, level));
    }

    // ── Custom EVs (economia v3): Pontos de Potencial + Treinamento ──
    const TRAINING_STATS = ['HP', 'ATK', 'DEF', 'SPA', 'SPD', 'SPE'];
    function parseEvolutionStage(raw) {
        const m = String(raw || '1/1').split('/');
        const cur = parseInt(m[0]), tot = parseInt(m[1]);
        if (!(cur >= 1) || !(tot >= 1) || cur > tot) return [1, 1];
        return [cur, tot];
    }
    function statCost(n) { n = Math.max(0, n | 0); return n * (n + 1) / 2; }
    function nextPointCost(n) { return Math.max(0, n | 0) + 1; }
    function trainingSpent(training) {
        return Object.values(training || {}).reduce((s, v) => s + statCost(v), 0);
    }
    function potentialPoints(level, evoBonus = 0, special = 0) {
        return Math.floor(Math.max(1, level | 0) / 2) + (evoBonus | 0) + (special | 0);
    }
    function trainingRate(stageCur, stageTot) {
        const st = stageCur | 0, tot = stageTot | 0;
        if (tot >= 3) return st === 1 ? [1, 1] : st === 2 ? [3, 2] : [2, 1];
        if (tot === 2) return st === 1 ? [3, 2] : [2, 1];
        return [2, 1];
    }
    function trainingPoints(level, stageCur, stageTot, bonus = 0) {
        const [num, den] = trainingRate(stageCur, stageTot);
        return Math.floor(num * (Math.max(1, level | 0) - 1) / den) + (bonus | 0);
    }
    function pointsBudget(level, stageCur, stageTot, evoBonus = 0, special = 0, trainBonus = 0) {
        return potentialPoints(level, evoBonus, special)
             + trainingPoints(level, stageCur, stageTot, trainBonus);
    }
    // Power representativo p/ moves de potência variável (espelho do servidor)
    const VARIABLE_POWER = {
        'return': 90, 'frustration': 90, 'low kick': 60, 'grass knot': 60,
        'heavy slam': 80, 'heat crash': 80, 'gyro ball': 70, 'electro ball': 70,
        'flail': 80, 'reversal': 80, 'crush grip': 80, 'wring out': 80,
        'magnitude': 70, 'present': 60, 'natural gift': 80, 'punishment': 60,
        'trump card': 70, 'spit up': 60, 'hidden power': 60,
    };

    // ── Crítico (estágios) ──
    const HIGH_CRIT_MOVES = new Set(['slash','razor leaf','crabhammer','karate chop',
        'aeroblast','air cutter','attack order','blaze kick','cross chop','cross poison',
        'drill run','leaf blade','night slash','poison tail','psycho cut','razor wind',
        'shadow claw','sky attack','spacial rend','stone edge','razor shell','snipe shot',
        'esper wing','shell side arm']);
    function critThreshold(critStage = 0) { return Math.max(17, 20 - (critStage | 0)); }
    function critStageFor(moveName, ability, focusEnergy) {
        if (ability && typeof ability === 'object') ability = ability.name || '';
        let s = 0;
        if (HIGH_CRIT_MOVES.has((moveName || '').toLowerCase())) s += 1;
        if (String(ability || '').trim().toLowerCase() === 'super luck') s += 1;
        if (focusEnergy) s += 2;
        return s;
    }

    function statTierLocked(statKey, training) {
        const tr = training || {};
        const v = (tr[statKey] | 0);
        if (v > 0 && v % 5 === 0)
            return !Object.keys(tr).some(k => k !== statKey && (tr[k] | 0) >= v);
        return false;
    }

    // ── Acerto ──
    function missThreshold(accuracy) {
        if (!accuracy) return 0;
        if (accuracy >= 100) return 1;
        return Math.max(1, Math.ceil((100 - accuracy) / 5));
    }
    function rollHits(d20, accuracy, attackStage = 0, evasionStage = 0) {
        const thr = missThreshold(accuracy);
        if (thr === 0) return true;   // move que não erra (Swift) — nem no nat 1
        if (d20 >= 20) return true;
        if (d20 <= 1) return false;
        return (d20 + (attackStage || 0) - (evasionStage || 0)) > thr;
    }

    // ── Dano ──
    function levelTierMult(level) {
        for (const [cut, mult] of LEVEL_TIERS) if (level >= cut) return mult;
        return 1.0;
    }
    function diceForPower(power, level) {
        if (!power) power = 40;
        const n = Math.ceil(power / 20);
        const count = Math.ceil(n * levelTierMult(level));
        const sides = level < 20 ? 4 : 6;
        return `${count}d${sides}`;
    }
    function defenseStatKey(category, defenseMode) {
        const mode = DEFENSE_MODES[defenseMode || 1] || DEFENSE_MODES[1];
        return category === 'special' ? mode.special : mode.physical;
    }
    function defenseTax(defenseMode) {
        return (DEFENSE_MODES[defenseMode || 1] || DEFENSE_MODES[1]).tax;
    }
    function damage(diceTotal, atkEff, defEff, stab = false, effectiveness = 1.0,
                    tax = 1.0, burned = false, stabMult = null, level = null) {
        const ratio = Math.max(RATIO_CLAMP[0],
            Math.min(RATIO_CLAMP[1], atkEff / Math.max(1, defEff)));
        let dmg = diceTotal * ratio * tax;
        if (stab) dmg *= (stabMult || STAB_MULT);
        dmg *= effectiveness;
        if (burned) dmg *= 0.5;
        if (effectiveness <= 0) return 0;
        return Math.max(1, Math.floor(dmg * damageScale(level)));
    }

    // ── Stat stages multiplicativos ──
    function stageMult(n) {
        n = Math.max(-6, Math.min(6, n || 0));
        return n >= 0 ? (2 + n) / 2 : 2 / (2 - n);
    }

    // ── Iniciativa ──
    function initiativeBonus(speEff) {
        return Math.floor(speEff / 5);
    }

    // Decide a iniciativa entre 'a' e 'b' (espelho de initiative_winner):
    // 1) upset 20vs1 (lento tira 20 natural, rápido tira 1) → lento primeiro;
    // 2) maior total; 3) empate → maior SPE_eff; 4) empate completo → 'a'.
    function initiativeWinner(natA, natB, speA, speB, extraA = 0, extraB = 0) {
        speA = Math.trunc(speA); speB = Math.trunc(speB);
        const totalA = Math.trunc(natA) + initiativeBonus(speA) + Math.trunc(extraA || 0);
        const totalB = Math.trunc(natB) + initiativeBonus(speB) + Math.trunc(extraB || 0);
        if (speA < speB && natA === 20 && natB === 1) return ['a', totalA, totalB, true];
        if (speB < speA && natB === 20 && natA === 1) return ['b', totalA, totalB, true];
        if (totalA !== totalB) return [totalA > totalB ? 'a' : 'b', totalA, totalB, false];
        if (speA !== speB) return [speA > speB ? 'a' : 'b', totalA, totalB, false];
        return ['a', totalA, totalB, false];
    }

    // ── Dano fixo ──
    function fixedDamageFor(moveNameLower, level, targetCurrentHp = null) {
        const fn = FIXED_DAMAGE_FORMULAS[moveNameLower];
        if (!fn) return null;
        const raw = fn(level, targetCurrentHp);
        if (moveNameLower === 'super fang') return Math.max(1, Math.floor(raw));
        return Math.max(1, Math.floor(raw * damageScale(level)));
    }

    // ═════════════════════════════════════════════════════════════════════
    // SISTEMA v3 — d100/ACC → Dano → Resistência d20 (espelho de battle_math.py)
    // ═════════════════════════════════════════════════════════════════════
    const V3_STATUS_DIVISOR = 8, V3_TN_SHIFT = 0;
    const V3_DEF_BONUS_CAP = 12, V3_STAB_DIE_LEVEL = 25, V3_STAB_FLAT = 2;
    const V3_ACC_CAP = 100, V3_ACC_FLOOR = 5;
    const V3_CRIT_BASE = 5, V3_CRIT_PER_STAGE = 10, V3_CRIT_CAP = 50;
    const V3_MOMENTUM_MAX = 3, V3_CERTEIRO_DAMAGE_MULT = 0.90;
    // (pow_máx, nº dados, lados, TN, cooldown)
    const V3_MASTER_TABLE = [
        [35, 1, 6, 10, 0], [50, 1, 8, 12, 0], [65, 1, 10, 14, 0], [80, 2, 6, 16, 0],
        [95, 2, 8, 18, 1], [110, 3, 6, 20, 2], [125, 3, 8, 22, 3], [1e9, 3, 10, 24, 3],
    ];
    function v3Tier(power) {
        const p = Math.max(1, power | 0 || 40);
        for (let i = 0; i < V3_MASTER_TABLE.length; i++)
            if (p <= V3_MASTER_TABLE[i][0]) return i;
        return V3_MASTER_TABLE.length - 1;
    }
    function v3DiceBase(power) { const r = V3_MASTER_TABLE[v3Tier(power)]; return [r[1], r[2]]; }
    function v3Tn(power, attackerLevel = 1) {
        return V3_MASTER_TABLE[v3Tier(power)][3] + V3_TN_SHIFT
            + Math.floor(Math.max(1, attackerLevel | 0) / 10);
    }
    function v3Cooldown(power) { return V3_MASTER_TABLE[v3Tier(power)][4]; }
    // ── Cooldown de SUSTAIN (dreno/cura instantânea) — espelho do Python ──
    const V3_SUSTAIN_POW_HEAVY = 90;
    function v3DrainCooldown(power, drain) {
        if ((drain | 0) <= 0) return 0;
        return (power | 0) >= V3_SUSTAIN_POW_HEAVY ? 2 : 1;
    }
    function v3HealCooldown(amount) {
        if (amount === 'full' || amount === 'half') return 2;
        return amount ? 1 : 0;
    }
    function v3MoveCooldown(power, drain = 0) {
        return Math.max(v3Cooldown(power), v3DrainCooldown(power, drain));
    }
    function v3MilestoneDice(level) { return Math.max(0, Math.min(4, Math.floor((level || 1) / 25))); }
    function v3StatusComponent(stat, atkStages = 0) {
        // Certeiro (ACC ∞) NÃO reduz o componente — compensação é v3CerteiroMult
        const c = Math.floor((stat || 10) / V3_STATUS_DIVISOR) + 2 * (atkStages | 0);
        return Math.max(1, c);
    }
    function v3LevelBonus(level) { return Math.floor(Math.max(1, level | 0) / 10); }
    function v3EffectivenessDiceDelta(e) {
        e = (e == null) ? 1 : +e;
        if (e >= 4) return 2; if (e >= 2) return 1;
        if (e <= 0.25) return -2; if (e <= 0.5) return -1;
        return 0;
    }
    function v3BuildDice(power, level, stab = false, effectiveness = 1, fieldDelta = 0) {
        // Certeiro (ACC ∞) rola os dados NORMAIS — compensação é v3CerteiroMult
        const tier = v3Tier(power);
        let n = V3_MASTER_TABLE[tier][1];
        const sides = V3_MASTER_TABLE[tier][2];
        n += v3MilestoneDice(level) + ((stab && (level | 0) >= V3_STAB_DIE_LEVEL) ? 1 : 0)
           + v3EffectivenessDiceDelta(effectiveness) + (fieldDelta | 0);
        return [Math.max(1, n), sides, n < 1];
    }
    function v3StabFlat(stab, level) {
        return (stab && (level | 0) < V3_STAB_DIE_LEVEL) ? V3_STAB_FLAT : 0;
    }
    function v3AccEffective(accBase, accStages = 0, evaStages = 0, weatherMod = 0) {
        if (accBase == null) return null;
        const acc = (accBase | 0) + 10 * (accStages | 0) - 10 * (evaStages | 0) + (weatherMod | 0);
        return Math.max(V3_ACC_FLOOR, Math.min(V3_ACC_CAP, acc));
    }
    function v3Connects(d100, accEff) { return accEff == null || (d100 | 0) <= accEff; }
    function v3CritChance(stages = 0) { return Math.min(V3_CRIT_CAP, V3_CRIT_BASE + V3_CRIT_PER_STAGE * (stages | 0)); }
    function v3ResistanceTotal(d20, defenseStat, level, defStages = 0, crit = false, extra = 0, critZeroes = false) {
        let bonus = Math.min(V3_DEF_BONUS_CAP, Math.floor((defenseStat || 10) / 10)) + (defStages | 0);
        if (crit) bonus = critZeroes ? 0 : (bonus > 0 ? Math.floor(bonus / 2) : bonus);
        return (d20 | 0) + bonus + v3LevelBonus(level) + (extra | 0);
    }
    function v3ResistOutcome(result, tn, defenderFaster = false) {
        result |= 0; tn |= 0;
        if (result >= tn + 10) return 'negate';
        if (result >= tn) return (defenderFaster && result === tn + 9) ? 'negate' : 'half';
        return (defenderFaster && result === tn - 1) ? 'half' : 'full';
    }
    function v3ApplyOutcome(gross, outcome) {
        if (outcome === 'negate') return 0;
        if (outcome === 'half') return Math.max(1, Math.floor(gross / 2));
        return Math.max(1, gross | 0);
    }
    function v3GrossDamage(component, level, diceTotal, momentum = 0, halveDice = false, flat = 0) {
        const dice = halveDice ? Math.floor(diceTotal / 2) : (diceTotal | 0);
        return Math.max(1, (component | 0) + v3LevelBonus(level)
            + Math.max(1, dice) + Math.max(0, Math.min(V3_MOMENTUM_MAX, momentum | 0))
            + (flat | 0));
    }

    // ── v3 F5: Clima, Terreno, Prioridade e Casos Especiais ──────────────
    const V3_FIELD_ROUNDS = 5;
    const V3_WEATHER_CHIP_DIV = 16;
    const V3_PROTECT_FLOOR = 5;
    const V3_SAND_IMMUNE = ['rock', 'ground', 'steel'];
    const V3_HAIL_IMMUNE = ['ice'];
    const V3_GROUND_SLAMS = ['earthquake', 'bulldoze', 'magnitude'];
    function v3WeatherDiceDelta(weather, moveType) {
        const w = (weather || '').toLowerCase(), t = (moveType || '').toLowerCase();
        if (w === 'sun') return t === 'fire' ? 1 : (t === 'water' ? -1 : 0);
        if (w === 'rain') return t === 'water' ? 1 : (t === 'fire' ? -1 : 0);
        return 0;
    }
    function v3TerrainDiceDelta(terrain, moveType, moveName = '') {
        const tr = (terrain || '').toLowerCase(), t = (moveType || '').toLowerCase();
        const ml = (moveName || '').toLowerCase();
        if (tr === 'grassy') {
            if (V3_GROUND_SLAMS.includes(ml)) return -1;
            return t === 'grass' ? 1 : 0;
        }
        if (tr === 'electric') return t === 'electric' ? 1 : 0;
        if (tr === 'psychic') return t === 'psychic' ? 1 : 0;
        if (tr === 'misty') return t === 'dragon' ? -1 : 0;
        return 0;
    }
    function v3WeatherAcc(weather, moveName, accuracy) {
        const w = (weather || '').toLowerCase(), ml = (moveName || '').toLowerCase();
        if (ml === 'thunder' || ml === 'hurricane') {
            if (w === 'sun') accuracy = 50;
            else if (w === 'rain') accuracy = 100;
        } else if (ml === 'blizzard' && (w === 'hail' || w === 'snow')) {
            accuracy = 100;
        }
        if (w === 'fog' && accuracy != null) accuracy = Math.max(V3_ACC_FLOOR, (accuracy | 0) - 10);
        return accuracy;
    }
    function v3WeatherResistBonus(weather, defenderTypes, category) {
        const w = (weather || '').toLowerCase();
        const types = (defenderTypes || []).map(t => String(t).toLowerCase());
        if (w === 'sandstorm' && types.includes('rock') && category === 'special') return 2;
        if ((w === 'hail' || w === 'snow') && types.includes('ice') && category === 'physical') return 2;
        return 0;
    }
    function v3WeatherChip(weather, maxHp, defenderTypes) {
        const w = (weather || '').toLowerCase();
        const types = (defenderTypes || []).map(t => String(t).toLowerCase());
        if (w === 'sandstorm' && !types.some(t => V3_SAND_IMMUNE.includes(t)))
            return Math.max(1, Math.floor((maxHp || 1) / V3_WEATHER_CHIP_DIV));
        if ((w === 'hail' || w === 'snow') && !types.some(t => V3_HAIL_IMMUNE.includes(t)))
            return Math.max(1, Math.floor((maxHp || 1) / V3_WEATHER_CHIP_DIV));
        return 0;
    }
    function v3TerrainHeal(terrain, maxHp) {
        if ((terrain || '').toLowerCase() === 'grassy')
            return Math.max(1, Math.floor((maxHp || 1) / V3_WEATHER_CHIP_DIV));
        return 0;
    }
    const V3_MULTI_HIT = {
        'double kick': [2, 2], 'double hit': [2, 2], 'dual chop': [2, 2],
        'bonemerang': [2, 2], 'double iron bash': [2, 2], 'dragon darts': [2, 2],
        'twineedle': [2, 2], 'gear grind': [2, 2], 'dual wingbeat': [2, 2],
        'triple kick': [3, 3], 'triple axel': [3, 3], 'surging strikes': [3, 3],
        'double slap': [2, 5], 'fury attack': [2, 5], 'fury swipes': [2, 5],
        'pin missile': [2, 5], 'rock blast': [2, 5], 'bullet seed': [2, 5],
        'icicle spear': [2, 5], 'spike cannon': [2, 5], 'comet punch': [2, 5],
        'barrage': [2, 5], 'arm thrust': [2, 5], 'tail slap': [2, 5],
        'water shuriken': [2, 5], 'bone rush': [2, 5], 'scale shot': [2, 5],
    };
    function v3MultiHits(moveName) {
        const span = V3_MULTI_HIT[(moveName || '').toLowerCase()];
        if (!span) return null;
        if (span[0] === span[1]) return span[0];
        return 1 + (1 + Math.floor(Math.random() * 4));
    }
    const V3_CHARGE_MOVES = ['solar beam', 'solar blade', 'sky attack', 'skull bash',
                             'razor wind', 'freeze shock', 'ice burn', 'meteor beam'];
    function v3NeedsCharge(moveName, weather) {
        const ml = (moveName || '').toLowerCase();
        if (V3_SEMI_INVULN[ml]) return true;   // Fly/Dig/Dive... preparam 1 rodada
        if (!V3_CHARGE_MOVES.includes(ml)) return false;
        if ((ml === 'solar beam' || ml === 'solar blade') && (weather || '').toLowerCase() === 'sun') return false;
        return true;
    }
    function v3Recoil(finalDamage, canonDrain) {
        if ((canonDrain | 0) < 0 && (finalDamage | 0) > 0) return Math.max(1, Math.floor(finalDamage / 3));
        return 0;
    }
    function v3DrainHeal(finalDamage, canonDrain) {
        if ((canonDrain | 0) > 0 && (finalDamage | 0) > 0) return Math.max(1, Math.floor(finalDamage / 2));
        return 0;
    }
    function v3ProtectChance(chain) {
        return Math.max(V3_PROTECT_FLOOR, 100 >> Math.max(0, chain | 0));
    }

    // ── ACC ∞ (certeiros) e invulnerabilidade ──
    function v3CerteiroMult(damage) {
        const d = damage | 0;
        if (d <= 0) return d;
        return Math.max(1, Math.floor(d * V3_CERTEIRO_DAMAGE_MULT));
    }
    const V3_SEMI_INVULN = {
        'fly': 'no ar', 'bounce': 'no ar', 'sky drop': 'no ar',
        'dig': 'no subsolo', 'dive': 'debaixo d’água',
        'phantom force': 'nas sombras', 'shadow force': 'nas sombras',
    };
    const V3_INVULN_PIERCE = {
        'no ar': ['gust', 'twister', 'thunder', 'hurricane', 'sky uppercut',
                  'smack down', 'thousand arrows'],
        'no subsolo': ['earthquake', 'magnitude', 'fissure'],
        'debaixo d’água': ['surf', 'whirlpool'],
        'nas sombras': [],
    };
    function v3SemiInvulnState(moveName) {
        return V3_SEMI_INVULN[(moveName || '').toLowerCase()] || null;
    }
    function v3PiercesInvuln(state, incomingMove) {
        return (V3_INVULN_PIERCE[state || ''] || []).includes((incomingMove || '').toLowerCase());
    }

    return {
        RATIO_CLAMP, STAB_MULT, damageScale, TRAINING_POINTS_PER_LEVEL, TRAINING_CAP,
        DEFENSE_MODES, statAtLevel, hpAtLevel, trainingBudget, trainingCap,
        missThreshold, rollHits, levelTierMult, diceForPower, defenseStatKey,
        defenseTax, damage, stageMult, initiativeBonus, initiativeWinner, fixedDamageFor,
        TRAINING_STATS, parseEvolutionStage, statCost, nextPointCost, trainingSpent,
        potentialPoints, trainingPoints, pointsBudget, statTierLocked,
        HIGH_CRIT_MOVES, critThreshold, critStageFor, VARIABLE_POWER,
        V3_MASTER_TABLE, V3_MOMENTUM_MAX, v3Tier, v3DiceBase, v3Tn, v3Cooldown,
        v3DrainCooldown, v3HealCooldown, v3MoveCooldown,
        v3MilestoneDice, v3StatusComponent, v3LevelBonus, v3EffectivenessDiceDelta,
        v3BuildDice, v3StabFlat, v3AccEffective, v3Connects, v3CritChance,
        v3ResistanceTotal, v3ResistOutcome, v3ApplyOutcome, v3GrossDamage,
        V3_FIELD_ROUNDS, V3_MULTI_HIT, V3_CHARGE_MOVES,
        v3WeatherDiceDelta, v3TerrainDiceDelta, v3WeatherAcc,
        v3WeatherResistBonus, v3WeatherChip, v3TerrainHeal, v3MultiHits,
        v3NeedsCharge, v3Recoil, v3DrainHeal, v3ProtectChance,
        V3_CERTEIRO_DAMAGE_MULT, V3_SEMI_INVULN, V3_INVULN_PIERCE,
        v3CerteiroMult, v3SemiInvulnState, v3PiercesInvuln,
    };
})();
