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
    const DAMAGE_SCALE_BASE = 0.20;
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
        return Math.floor(speEff / 10);
    }

    // ── Dano fixo ──
    function fixedDamageFor(moveNameLower, level, targetCurrentHp = null) {
        const fn = FIXED_DAMAGE_FORMULAS[moveNameLower];
        if (!fn) return null;
        const raw = fn(level, targetCurrentHp);
        if (moveNameLower === 'super fang') return Math.max(1, Math.floor(raw));
        return Math.max(1, Math.floor(raw * damageScale(level)));
    }

    return {
        RATIO_CLAMP, STAB_MULT, damageScale, TRAINING_POINTS_PER_LEVEL, TRAINING_CAP,
        DEFENSE_MODES, statAtLevel, hpAtLevel, trainingBudget, trainingCap,
        missThreshold, rollHits, levelTierMult, diceForPower, defenseStatKey,
        defenseTax, damage, stageMult, initiativeBonus, fixedDamageFor,
        TRAINING_STATS, parseEvolutionStage, statCost, nextPointCost, trainingSpent,
        potentialPoints, trainingPoints, pointsBudget, statTierLocked,
    };
})();
