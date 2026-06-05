/* ============================================
   POKEMON 5E RPG - PLAYER JS (UPDATED)
   ============================================ */

let currentEncounter = null;
let playerTeam = TRAINER_DATA.team || [];
let battleActive = false;

// ============================================
// SOCKET EVENTS
// ============================================
socket.on('xp_update', (data) => {
    const bar = document.getElementById('player-xp-bar');
    const text = document.getElementById('player-xp-text');
    const percentage = (data.xp / data.xp_to_next) * 100;
    bar.style.width = `${percentage}%`;
    text.textContent = `${data.xp} / ${data.xp_to_next} XP`;
    if (data.leveled_up) {
        const badge = document.getElementById('trainer-level-badge');
        if (badge) {
            badge.textContent = `Nível ${data.level}`;
            badge.classList.add('level-up-animation');
            setTimeout(() => badge.classList.remove('level-up-animation'), 1000);
        }
        alert(`🎉 Parabéns! Você subiu para o Nível ${data.level}!`);
    }
});

socket.on('new_quest', (quest) => {
    const list = document.getElementById('player-quests');
    const emptyState = list.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    list.innerHTML += `
        <div class="quest-card">
            <h4>${quest.title}</h4>
            <span class="quest-city">📍 ${quest.city}</span>
            ${quest.xp_reward ? `<span class="quest-xp">🌟 ${quest.xp_reward} XP</span>` : ''}
            <p>${quest.description}</p>
            <div class="quest-notes">
                <textarea placeholder="Suas anotações..." rows="2"></textarea>
            </div>
        </div>`;
    playNotificationSound();
});

socket.on('quest_completed', (data) => {
    if (data.xp_reward > 0) {
        alert(`✅ Quest completada! Você ganhou ${data.xp_reward} XP!`);
    }
});

socket.on('master_action', (data) => {
    if (data.type === 'forced_encounter') {
        currentEncounter = { pokemon: data.pokemon, level: data.level, is_shiny: false };
        displayEncounter(currentEncounter);
        alert(`⚠️ O Mestre enviou um Pokémon selvagem!`);
    }
});

// ============================================
// DICE ROLLER WITH ANIMATION
// ============================================
function rollDice(sides) {
    const result = Math.floor(Math.random() * sides) + 1;
    animateDice(result, `d${sides}`);
    addBattleLog(`🎲 Rolou d${sides}: <strong>${result}</strong>`);
    socket.emit('dice_roll', { sides, result, player: TRAINER_DATA.name });
}

function rollCustomDice() {
    const input = document.getElementById('dice-custom-input').value.trim();
    const match = input.match(/^(\d+)d(\d+)([+-]\d+)?$/i);
    if (!match) { alert('Formato inválido! Use: 2d6+3'); return; }
    const count = parseInt(match[1]);
    const sides = parseInt(match[2]);
    const mod = match[3] ? parseInt(match[3]) : 0;
    let total = mod;
    let rolls = [];
    for (let i = 0; i < count; i++) {
        const r = Math.floor(Math.random() * sides) + 1;
        rolls.push(r);
        total += r;
    }
    animateDice(total, input);
    addBattleLog(`🎲 Rolou ${input}: [${rolls.join(', ')}]${mod ? (mod > 0 ? '+' : '') + mod : ''} = <strong>${total}</strong>`);
}

function animateDice(result, label) {
    const anim = document.getElementById('dice-animation');
    const text = document.getElementById('dice-result-text');
    anim.innerHTML = '';
    // Create animated dice
    const dice = document.createElement('div');
    dice.className = 'dice-rolling';
    dice.textContent = '🎲';
    anim.appendChild(dice);
    // Animate random numbers
    let count = 0;
    const interval = setInterval(() => {
        dice.textContent = Math.floor(Math.random() * 20) + 1;
        dice.style.transform = `rotate(${Math.random() * 360}deg)`;
        count++;
        if (count > 10) {
            clearInterval(interval);
            dice.textContent = result;
            dice.style.transform = 'rotate(0deg)';
            dice.className = 'dice-final';
            text.innerHTML = `<strong>${label}</strong> → <span class="dice-value">${result}</span>`;
        }
    }, 80);
}

// ============================================
// ENCOUNTER SYSTEM
// ============================================
async function searchWildPokemon() {
    const routeId = document.getElementById('current-route').value;
    const huntMode = document.getElementById('hunt-mode').value;
    const playerLevel = TRAINER_DATA.level || 1;
    const response = await fetch('/api/encounter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ route_id: routeId, hunt_mode: huntMode, player_level: playerLevel })
    });
    const encounter = await response.json();
    if (encounter.error) { alert('Nenhum Pokémon encontrado!'); return; }
    currentEncounter = encounter;
    displayEncounter(encounter);
}

function displayEncounter(encounter) {
    const pokemon = encounter.pokemon;
    showElement('encounter-result');
    document.getElementById('wild-pokemon-name').textContent = `${pokemon.name} #${String(pokemon.number).padStart(3, '0')}`;
    document.getElementById('wild-pokemon-level').textContent = encounter.level;
    document.getElementById('wild-pokemon-hp').textContent = pokemon.hp;
    document.getElementById('wild-pokemon-ac').textContent = pokemon.ac;
    document.getElementById('wild-pokemon-types').innerHTML = formatTypes(pokemon.types);
    const sprite = document.getElementById('wild-pokemon-sprite');
    sprite.src = getPokemonSpriteUrl(pokemon.number);
    sprite.alt = pokemon.name;
    const shinyBadge = document.getElementById('shiny-badge');
    encounter.is_shiny ? shinyBadge.classList.remove('hidden') : shinyBadge.classList.add('hidden');
    // Populate team select
    const select = document.getElementById('send-pokemon');
    select.innerHTML = playerTeam.length === 0 
        ? '<option value="">Sem Pokémon no time</option>'
        : playerTeam.map((p, i) => `<option value="${i}">${p.nickname || p.name} Nv.${p.level}</option>`).join('');
}

// ============================================
// BATTLE SYSTEM (FULL)
// ============================================
async function startBattle() {
    if (!currentEncounter) return;
    const selectEl = document.getElementById('send-pokemon');
    const selectIdx = parseInt(selectEl.value) || 0;
    let playerPokemon = playerTeam[selectIdx];
    
    // Fallback if no valid pokemon in team
    if (!playerPokemon || !playerPokemon.name) {
        if (playerTeam.length > 0) {
            playerPokemon = playerTeam[0];
        } else {
            alert('Você não tem Pokémon no time!');
            return;
        }
    }
    
    // Always fetch full data from API to ensure number/stats/moves exist
    try {
        const searchName = playerPokemon.name;
        const resp = await fetch(`/api/pokemon?search=${encodeURIComponent(searchName)}`);
        const results = await resp.json();
        if (results.length > 0) {
            const api = results[0];
            playerPokemon.number = api.number;
            if (!playerPokemon.stats || !playerPokemon.stats.STR) playerPokemon.stats = api.stats;
            if (!playerPokemon.types || playerPokemon.types.length === 0) playerPokemon.types = api.types;
            if (!playerPokemon.speed) playerPokemon.speed = api.speed;
            if (!playerPokemon.vulnerabilities) playerPokemon.vulnerabilities = api.vulnerabilities;
            if (!playerPokemon.resistances) playerPokemon.resistances = api.resistances;
            if (!playerPokemon.immunities) playerPokemon.immunities = api.immunities;
            if (!playerPokemon.moves || playerPokemon.moves.length === 0) {
                // Build moves from level
                let moves = [...(api.startingMoves || [])];
                if (api.levelMoves) {
                    for (const [lv, m] of Object.entries(api.levelMoves)) {
                        if (parseInt(lv) <= (playerPokemon.level || 1)) moves.push(...m);
                    }
                }
                playerPokemon.moves = moves.slice(0, 4);
            }
        }
    } catch(e) { console.error('API fetch failed:', e); }
    
    const enemy = currentEncounter.pokemon;
    
    console.log('BATTLE - playerPokemon:', JSON.stringify(playerPokemon));
    console.log('BATTLE - heldItem:', playerPokemon.heldItem, '| bag has pedra-chave:', (TRAINER_DATA.bag || []).join(' ').toLowerCase().includes('pedra-chave'));
    console.log('BATTLE - enemy:', enemy.name);

    // Notify master with full pokemon data
    socket.emit('start_encounter', {
        pokemon: enemy, level: currentEncounter.level,
        is_shiny: currentEncounter.is_shiny, route_id: currentEncounter.route_id,
        player_pokemon: playerPokemon.nickname || playerPokemon.name,
        player_pokemon_idx: parseInt(selectIdx) || 0,
        wild_moves: currentEncounter.wild_moves || []
    });

    // Switch to battle tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="battle"]').classList.add('active');
    document.getElementById('tab-battle').classList.add('active');

    // Show battle area
    hideElement('no-battle-msg');
    showElement('battle-area');
    hideElement('encounter-result');
    battleActive = true;

    // Store current battle data
    window.currentBattleData = { enemy, playerPokemon, level: currentEncounter.level };

    // Fill enemy data
    document.getElementById('battle-enemy-sprite').src = getPokemonSpriteUrl(enemy.number);
    document.getElementById('battle-enemy-name-full').textContent = `${enemy.name} Nv.${currentEncounter.level}`;
    document.getElementById('battle-enemy-types').innerHTML = formatTypes(enemy.types);
    document.getElementById('battle-enemy-hp-text-full').textContent = `${enemy.hp}/${enemy.hp} HP`;
    document.getElementById('battle-enemy-hp-bar-full').style.width = '100%';
    document.getElementById('battle-enemy-ac').textContent = enemy.ac;
    document.getElementById('battle-enemy-speed').textContent = enemy.speed || '30ft';

    // Enemy stats
    const enemyStats = document.getElementById('battle-enemy-stats');
    if (enemy.stats) {
        enemyStats.innerHTML = Object.entries(enemy.stats).map(([k,v]) => 
            `<span>${k}: <strong>${v}</strong> (${Math.floor((v-10)/2) >= 0 ? '+' : ''}${Math.floor((v-10)/2)})</span>`
        ).join('');
    }

    // Enemy moves - use wild_moves from encounter (pre-randomized 4 moves)
    const enemyMoves = document.getElementById('battle-enemy-moves');
    const allEnemyMoves = currentEncounter.wild_moves || [...(enemy.startingMoves || [])].slice(0, 4);
    enemyMoves.innerHTML = allEnemyMoves.map(m => `<span class="move-btn">${m}</span>`).join('');

    // Enemy ability
    const abilityEl = document.getElementById('battle-enemy-ability');
    if (enemy.ability) abilityEl.textContent = `${enemy.ability.name}: ${enemy.ability.description}`;
    else if (enemy.hiddenAbility) abilityEl.textContent = `${enemy.hiddenAbility.name}: ${enemy.hiddenAbility.description}`;
    else abilityEl.textContent = '-';

    // Fill player pokemon data
    const pNum = playerPokemon.number || 0;
    document.getElementById('battle-player-sprite').src = pNum ? getPokemonSpriteUrl(pNum) : '';
    document.getElementById('battle-player-name-full').textContent = `${playerPokemon.nickname || playerPokemon.name} Nv.${playerPokemon.level}`;
    document.getElementById('battle-player-types').innerHTML = formatTypes(playerPokemon.types || []);
    const pHp = playerPokemon.currentHp || playerPokemon.maxHp || 20;
    const pMax = playerPokemon.maxHp || 20;
    document.getElementById('battle-player-hp-text-full').textContent = `${pHp}/${pMax} HP`;
    document.getElementById('battle-player-hp-bar-full').style.width = `${(pHp/pMax)*100}%`;
    document.getElementById('battle-player-ac').textContent = playerPokemon.ac || 10;
    document.getElementById('battle-player-speed').textContent = playerPokemon.speed || '30ft';

    // Player stats
    const playerStats = document.getElementById('battle-player-stats');
    if (playerPokemon.stats) {
        playerStats.innerHTML = Object.entries(playerPokemon.stats).map(([k,v]) => 
            `<span>${k}: <strong>${v}</strong> (${Math.floor((v-10)/2) >= 0 ? '+' : ''}${Math.floor((v-10)/2)})</span>`
        ).join('');
    }

    // Player moves (clickable - with tooltips and auto damage)
    const playerMovesEl = document.getElementById('battle-player-moves');
    const pMoves = playerPokemon.moves || [];
    await loadMovesData(pMoves.concat(allEnemyMoves));
    playerMovesEl.innerHTML = pMoves.map(m => renderMoveButton(m, true)).join('');
    
    // Also render enemy moves with tooltips
    enemyMoves.innerHTML = allEnemyMoves.map(m => renderMoveButton(m, false)).join('');

    // Clear battle log
    document.getElementById('battle-log-full').innerHTML = `<p>⚔️ Batalha iniciada! ${playerPokemon.nickname || playerPokemon.name} vs ${enemy.name} selvagem!</p><p>⏳ Aguardando Mestre rolar iniciativa...</p>`;
    
    // Check mega availability
    megaUsedThisBattle = false;
    checkMegaAvailable();
}

// Listen for initiative result
socket.on('initiative_result', (data) => {
    addBattleLog(`🎲 Iniciativa - Você: <strong>${data.player_initiative}</strong> (DEX ${data.player_mod >= 0 ? '+' : ''}${data.player_mod}) | Selvagem: <strong>${data.wild_initiative}</strong> (DEX ${data.wild_mod >= 0 ? '+' : ''}${data.wild_mod})`);
    addBattleLog(`➡️ <strong>${data.first_turn === 'player' ? 'Você começa!' : 'Pokémon Selvagem começa!'}</strong>`);
    window.currentTurn = data.first_turn;
    updateTurnUI();
});

// Listen for battle updates
socket.on('battle_update', (data) => {
    const bs = data.battle_state;
    
    // Update HP bars
    document.getElementById('battle-enemy-hp-bar-full').style.width = `${(bs.wild_hp_current / bs.wild_hp_max) * 100}%`;
    document.getElementById('battle-enemy-hp-text-full').textContent = `${bs.wild_hp_current}/${bs.wild_hp_max} HP`;
    document.getElementById('battle-player-hp-bar-full').style.width = `${(bs.player_hp_current / bs.player_hp_max) * 100}%`;
    document.getElementById('battle-player-hp-text-full').textContent = `${bs.player_hp_current}/${bs.player_hp_max} HP`;
    
    // Log action
    const who = data.action_by === 'player' ? '🟢 Seu Pokémon' : '🔴 Selvagem';
    let msg = `${who} usou <strong>${data.move_name}</strong>`;
    if (data.damage > 0) msg += ` → ${data.damage} de dano!`;
    if (data.heal > 0) msg += ` → curou ${data.heal} HP!`;
    if (data.status_effect) msg += ` → ${data.status_effect}!`;
    if (data.message) msg += ` <em>(${data.message})</em>`;
    addBattleLog(msg);
    
    // Update turn
    window.currentTurn = bs.turn;
    updateTurnUI();
    
    // Check faint
    if (bs.wild_hp_current <= 0) {
        addBattleLog(`<strong>💀 Pokémon Selvagem desmaiou!</strong>`);
        addBattleLog(`🔴 Você pode <strong>Arremessar Pokébola</strong> para tentar capturar ou clicar <strong>Derrotei</strong> para encerrar.`);
        // Show post-defeat options, hide attack moves
        window.currentTurn = 'player'; // Allow actions
        window.wildFainted = true;
        document.querySelectorAll('#battle-player-moves .selectable-move').forEach(btn => {
            btn.style.opacity = '0.3';
            btn.style.pointerEvents = 'none';
        });
        // Keep pokeball and defeated buttons visible
        document.getElementById('btn-pass-turn')?.classList.add('hidden');
        document.getElementById('btn-switch-pokemon')?.classList.add('hidden');
    }
    if (bs.player_hp_current <= 0) addBattleLog(`<strong>😵 Seu Pokémon desmaiou!</strong>`);
});

function updateTurnUI() {
    const moveBtns = document.querySelectorAll('#battle-player-moves .selectable-move');
    const passBtn = document.getElementById('btn-pass-turn');
    if (window.currentTurn === 'player') {
        moveBtns.forEach(btn => { btn.style.opacity = '1'; btn.style.pointerEvents = 'auto'; });
        if (passBtn) passBtn.classList.remove('hidden');
    } else {
        moveBtns.forEach(btn => { btn.style.opacity = '0.5'; btn.style.pointerEvents = 'none'; });
        if (passBtn) passBtn.classList.add('hidden');
    }
}

// Fetch move data for tooltips
async function loadMovesData(moveNames) {
    const toFetch = moveNames.filter(m => !MOVES_CACHE[m]);
    if (toFetch.length > 0) {
        try {
            const resp = await fetch('/api/moves/batch', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({moves: toFetch})
            });
            const data = await resp.json();
            Object.assign(MOVES_CACHE, data);
        } catch(e) {}
    }
}

function getMoveTooltip(moveName) {
    const m = MOVES_CACHE[moveName];
    if (!m) return moveName;
    let tip = `<strong>${m.name}</strong> [${m.type}]`;
    if (m.power) tip += `\nPoder: ${m.power}`;
    if (m.baseDamage) tip += `\nDano: ${m.baseDamage} + MOVE`;
    if (m.pp) tip += ` | PP: ${m.pp}`;
    if (m.range) tip += `\nAlcance: ${m.range}`;
    if (m.time) tip += ` | ${m.time}`;
    if (m.description) tip += `\n${m.description}`;
    if (m.higherLevels) tip += `\n[Níveis Sup.] ${m.higherLevels}`;
    return tip;
}

function renderMoveButton(moveName, clickable) {
    const m = MOVES_CACHE[moveName] || {};
    const typeClass = m.type ? `type-${m.type.toLowerCase()}` : '';
    const dmgLabel = m.baseDamage ? ` (${m.baseDamage})` : '';
    if (clickable) {
        return `<span class="move-btn selectable-move ${typeClass}" 
                      data-move="${moveName}"
                      onclick="useMove('${moveName.replace(/'/g, "\\'")}')"
                      onmouseenter="showMoveTooltip(event, '${moveName.replace(/'/g, "\\'")}')"
                      onmouseleave="hideMoveTooltip()"
                      ontouchstart="showMoveModal('${moveName.replace(/'/g, "\\'")}')"
                >${moveName}${dmgLabel}</span>`;
    }
    return `<span class="move-btn ${typeClass}"
                  onmouseenter="showMoveTooltip(event, '${moveName.replace(/'/g, "\\'")}')"
                  onmouseleave="hideMoveTooltip()"
                  ontouchstart="showMoveModal('${moveName.replace(/'/g, "\\'")}')"
            >${moveName}${dmgLabel}</span>`;
}

function showMoveTooltip(event, moveName) {
    const m = MOVES_CACHE[moveName];
    if (!m) return;
    let tooltip = document.getElementById('move-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'move-tooltip';
        tooltip.className = 'move-tooltip';
        document.body.appendChild(tooltip);
    }
    tooltip.innerHTML = getMoveTooltip(moveName).replace(/\n/g, '<br>');
    tooltip.style.display = 'block';
    tooltip.style.left = (event.pageX + 10) + 'px';
    tooltip.style.top = (event.pageY - 10) + 'px';
}

function hideMoveTooltip() {
    const tooltip = document.getElementById('move-tooltip');
    if (tooltip) tooltip.style.display = 'none';
}

function showMoveModal(moveName) {
    const m = MOVES_CACHE[moveName];
    if (!m) return;
    hideMoveTooltip();
    let modal = document.getElementById('move-info-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'move-info-modal';
        modal.className = 'modal';
        modal.innerHTML = '<div class="modal-content"><button class="modal-close" onclick="this.parentElement.parentElement.classList.add(\'hidden\')">&times;</button><div id="move-info-content"></div></div>';
        document.body.appendChild(modal);
    }
    document.getElementById('move-info-content').innerHTML = getMoveTooltip(moveName).replace(/\n/g, '<br>');
    modal.classList.remove('hidden');
}

function useMove(moveName) {
    if (window.currentTurn !== 'player') { alert('Não é seu turno!'); return; }
    
    const m = MOVES_CACHE[moveName] || {};
    const poke = window.currentBattleData?.playerPokemon;
    const stats = poke?.stats || {};
    const pokeLevel = poke?.level || 1;
    
    // Determine MOVE modifier based on move's power stat
    let moveMod = 0;
    const power = (m.power || 'FOR').toUpperCase();
    if (power.includes('FOR')) moveMod = Math.max(moveMod, Math.floor(((stats.STR||10) - 10) / 2));
    if (power.includes('DES')) moveMod = Math.max(moveMod, Math.floor(((stats.DEX||10) - 10) / 2));
    if (power.includes('INT')) moveMod = Math.max(moveMod, Math.floor(((stats.INT||10) - 10) / 2));
    if (power.includes('SAB')) moveMod = Math.max(moveMod, Math.floor(((stats.WIS||10) - 10) / 2));
    if (power.includes('CAR')) moveMod = Math.max(moveMod, Math.floor(((stats.CHA||10) - 10) / 2));
    if (power.includes('CON')) moveMod = Math.max(moveMod, Math.floor(((stats.CON||10) - 10) / 2));
    if (power === 'NENHUM') moveMod = 0;
    
    // Proficiency bonus based on level
    const profBonus = pokeLevel >= 17 ? 6 : pokeLevel >= 13 ? 5 : pokeLevel >= 9 ? 4 : pokeLevel >= 5 ? 3 : 2;
    
    // If move has no damage (status move), skip attack roll
    if (!m.baseDamage && !m.attackType && power === 'NENHUM') {
        addBattleLog(`▶️ <strong>${moveName}</strong> usado! (Move de status)`);
        socket.emit('battle_action', {
            action_by: 'player', action_type: 'status',
            move_name: moveName, damage: 0, message: m.description || ''
        });
        return;
    }
    
    // Roll d20 for attack
    const attackRoll = Math.floor(Math.random() * 20) + 1;
    const isCrit = attackRoll === 20;
    const isMiss = attackRoll === 1;
    const totalAttack = attackRoll + moveMod + profBonus;
    
    addBattleLog(`▶️ <strong>${moveName}</strong> → d20(${attackRoll}) + MOD(${moveMod}) + Prof(${profBonus}) = <strong>${totalAttack}</strong>${isCrit ? ' 💥 CRÍTICO!' : ''}${isMiss ? ' 💨 Falha!' : ''}`);
    animateDice(attackRoll, 'd20');
    
    const enemyAC = window.currentBattleData?.enemy?.ac || 13;
    
    if (isMiss) {
        addBattleLog(`❌ Falha crítica!`);
        socket.emit('battle_action', { action_by: 'player', action_type: 'attack', move_name: moveName, damage: 0, message: 'Nat 1 - Falha' });
    } else if (totalAttack >= enemyAC || isCrit) {
        // Auto-calculate damage
        const diceRoll = rollDamageFromString(m.baseDamage || '1d6', pokeLevel);
        let damage = diceRoll + moveMod;
        if (isCrit) {
            const critExtra = rollDamageFromString(m.baseDamage || '1d6', pokeLevel);
            damage = diceRoll + critExtra + moveMod;
        }
        
        // STAB check
        const pokeTypes = (poke?.types || []).map(t => t.toLowerCase());
        const moveType = (m.type || '').toLowerCase();
        const stabTable = [0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5];
        const stab = pokeTypes.includes(moveType) ? (stabTable[pokeLevel] || 0) : 0;
        damage += stab;
        
        if (damage < 1) damage = 1;
        
        // Type effectiveness vs enemy
        const enemy = window.currentBattleData?.enemy || {};
        const enemyTypes = (enemy.types || []).map(t => t.toLowerCase());
        const enemyVulns = (enemy.vulnerabilities || []).map(t => t.toLowerCase());
        const enemyResists = (enemy.resistances || []).map(t => t.toLowerCase());
        const enemyImmunities = (enemy.immunities || []).map(t => t.toLowerCase());
        
        let effectiveness = 1;
        let effectLabel = '';
        if (enemyImmunities.includes(moveType)) {
            effectiveness = 0;
            effectLabel = '⛔ IMUNE (0x)';
        } else {
            // Count how many of enemy's types are vulnerable/resistant
            if (enemyVulns.includes(moveType)) effectiveness *= 2;
            if (enemyResists.includes(moveType)) effectiveness *= 0.5;
        }
        
        damage = Math.floor(damage * effectiveness);
        if (effectiveness === 0) damage = 0;
        if (effectiveness > 1) effectLabel = `⚡ Super Efetivo (x${effectiveness})`;
        else if (effectiveness < 1 && effectiveness > 0) effectLabel = `🛡️ Não Efetivo (x${effectiveness})`;
        
        const powerLabel = m.power || 'FOR';
        addBattleLog(`✅ Acertou! (${totalAttack} vs AC ${enemyAC}) → ${m.baseDamage||'1d6'}(${diceRoll}) + MOVE/${powerLabel}(${moveMod})${stab > 0 ? ` + STAB(${stab})` : ''}${isCrit ? ' x2 CRIT' : ''}${effectLabel ? ' ' + effectLabel : ''} = <strong>${damage} dano ${m.type||''}</strong>`);
        
        socket.emit('battle_action', {
            action_by: 'player', action_type: 'attack', move_name: moveName,
            damage: damage, message: `${totalAttack} vs AC ${enemyAC}${isCrit ? ' Crítico!' : ''}`
        });
    } else {
        addBattleLog(`❌ Errou! (${totalAttack} < AC ${enemyAC})`);
        socket.emit('battle_action', { action_by: 'player', action_type: 'attack', move_name: moveName, damage: 0, message: `Errou (${totalAttack} vs AC ${enemyAC})` });
    }
}

function rollDamageFromString(diceStr, pokeLevel) {
    if (!diceStr) return 0;
    // Adjust dice for higher levels
    // For simplicity, use base damage (higher level scaling would need full parsing)
    const match = diceStr.match(/(\d+)d(\d+)/);
    if (!match) return 0;
    const count = parseInt(match[1]);
    const sides = parseInt(match[2]);
    let total = 0;
    for (let i = 0; i < count; i++) total += Math.floor(Math.random() * sides) + 1;
    return total;
}

function passTurn() {
    if (window.currentTurn !== 'player') return;
    addBattleLog(`⏭️ Turno passado.`);
    socket.emit('battle_action', { action_by: 'player', action_type: 'pass', move_name: 'Passar', damage: 0, message: 'Passou o turno' });
}

function throwPokeball() {
    // Allow pokeball at any time if enemy is fainted (HP 0)
    const hpText = document.getElementById('battle-enemy-hp-text-full').textContent;
    const hpMatch = hpText.match(/(\d+)\/(\d+)/);
    const currentHp = hpMatch ? parseInt(hpMatch[1]) : 999;
    const enemyFainted = currentHp <= 0;
    
    if (!enemyFainted && window.currentTurn !== 'player') { alert('Não é seu turno!'); return; }
    
    const enemy = window.currentBattleData?.enemy || {};
    const encounter = currentEncounter || {};
    const trainerLevel = TRAINER_DATA.level || 1;
    
    // Calculate capture DC: 10 + SR(floor) + pokemon level + (currentHp / 10 floor)
    let srVal = 0;
    const srStr = enemy.sr || '1/2';
    if (srStr.includes('/')) {
        srVal = Math.floor(parseInt(srStr.split('/')[0]) / parseInt(srStr.split('/')[1]));
    } else {
        srVal = parseInt(srStr);
    }
    
    const pokeLevel = encounter.level || 5;
    const hpComponent = Math.floor(currentHp / 10);
    const captureDC = enemyFainted ? Math.max(5, 5 + srVal) : 10 + srVal + pokeLevel + hpComponent;
    
    // Trainer's Animal Handling bonus (WIS mod + proficiency)
    const trainerWis = TRAINER_DATA.wis || 10;
    const wisMod = Math.floor((trainerWis - 10) / 2);
    const profBonus = trainerLevel >= 17 ? 6 : trainerLevel >= 13 ? 5 : trainerLevel >= 9 ? 4 : trainerLevel >= 5 ? 3 : 2;
    const animalHandlingBonus = wisMod + profBonus;
    
    // Roll d20 (or 2d20 take highest if advantage)
    let roll1 = Math.floor(Math.random() * 20) + 1;
    let roll2 = Math.floor(Math.random() * 20) + 1;
    let finalRoll = roll1;
    let advantageText = '';
    
    // Advantage if enemy has status OR is fainted
    const logContent = document.getElementById('battle-log-full')?.innerHTML || '';
    const hasStatusAdvantage = enemyFainted || /Envenenado|Queimado|Paralisado|Congelado|Dormindo|Confuso/i.test(logContent);
    
    if (hasStatusAdvantage) {
        finalRoll = Math.max(roll1, roll2);
        advantageText = ` (Vantagem! ${roll1}, ${roll2} → ${finalRoll})`;
    }
    
    const totalRoll = finalRoll + animalHandlingBonus;
    
    addBattleLog(`🔴 <strong>Arremessando Pokébola!</strong>${enemyFainted ? ' (Pokémon desmaiado - CD reduzida)' : ''}`);
    addBattleLog(`  CD de Captura: ${enemyFainted ? `5 + SR(${srVal})` : `10 + SR(${srVal}) + Nível(${pokeLevel}) + HP÷10(${hpComponent})`} = <strong>${captureDC}</strong>`);
    addBattleLog(`  Adestrar Animais: d20(${finalRoll})${advantageText} + SAB(${wisMod}) + Prof(${profBonus}) = <strong>${totalRoll}</strong>`);
    
    animateDice(finalRoll, 'd20');
    
    if (totalRoll >= captureDC) {
        addBattleLog(`✅ <strong>CAPTURADO!</strong> 🎉 (${totalRoll} ≥ ${captureDC})`);
        setTimeout(() => endBattle('caught'), 1500);
    } else {
        addBattleLog(`❌ A Pokébola falhou! (${totalRoll} < ${captureDC})`);
        addBattleLog(`🏃 <strong>O Pokémon selvagem fugiu!</strong> O encontro acabou.`);
        // Pokemon flees - end encounter automatically
        setTimeout(() => endBattle('fled_after_capture'), 2000);
    }
}

function showDamageConfirm(moveName, isCrit) { /* removed - now auto */ }
function confirmDamage(moveName, isCrit) { /* removed - now auto */ }

function addBattleLog(msg) {
    const log = document.getElementById('battle-log-full');
    if (log) {
        log.innerHTML += `<p>${msg}</p>`;
        log.scrollTop = log.scrollHeight;
    }
}

function fleeBattle() {
    hideElement('encounter-result');
    hideElement('battle-area');
    showElement('no-battle-msg');
    currentEncounter = null;
    battleActive = false;
    socket.emit('end_encounter', { result: 'fled' });
}

function endBattle(result) {
    const messages = {
        'caught': '🔴 Pokémon capturado!',
        'defeated': '💀 Pokémon selvagem derrotado!',
        'fled': '🏃 Você fugiu da batalha!',
        'fled_after_capture': '🏃 O Pokémon selvagem escapou da Pokébola e fugiu!',
        'fainted': '😵 Seu Pokémon desmaiou!'
    };
    addBattleLog(`<strong>${messages[result] || result}</strong>`);
    window.wildFainted = false;
    socket.emit('end_encounter', { result });

    // If caught, add to team
    if (result === 'caught' && currentEncounter) {
        const pokemon = currentEncounter.pokemon;
        const trainerLevel = TRAINER_DATA.level || 1;
        let pokeLevel = currentEncounter.level;
        if (pokeLevel < trainerLevel - 2) pokeLevel = Math.max(1, trainerLevel - 2);

        // Register in pokedex
        registerPokedex(pokemon.number);

        if (playerTeam.length < 6) {
            if (confirm(`Adicionar ${pokemon.name} Nv.${pokeLevel} ao time?`)) {
                playerTeam.push({
                    name: pokemon.name, nickname: '', number: pokemon.number,
                    types: pokemon.types, level: pokeLevel,
                    maxHp: pokemon.hp, currentHp: pokemon.hp, ac: pokemon.ac,
                    stats: pokemon.stats, moves: pokemon.startingMoves || [],
                    ability: pokemon.ability ? pokemon.ability.name : '',
                    speed: pokemon.speed, heldItem: '', notes: ''
                });
                saveTeam();
                refreshTeamDisplay();
            }
        } else {
            alert('Time cheio! Máximo de 6 Pokémon.');
        }
    }

    // Also register seen pokemon in pokedex
    if (currentEncounter && result !== 'caught') {
        registerPokedex(currentEncounter.pokemon.number);
    }

    setTimeout(() => {
        hideElement('battle-area');
        showElement('no-battle-msg');
        currentEncounter = null;
        battleActive = false;
    }, 2000);
}

// ============================================
// POKEDEX REGISTRATION
// ============================================
async function registerPokedex(pokemonNumber) {
    const response = await fetch('/player/pokedex/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pokemon_number: pokemonNumber })
    });
    const result = await response.json();
    if (result.success && !result.already_registered) {
        const counter = document.getElementById('pokedex-count');
        if (counter) counter.textContent = result.total_seen;
    }
}

async function searchPlayerPokedex() {
    const search = document.getElementById('player-pokedex-search').value;
    const response = await fetch(`/api/pokemon?search=${encodeURIComponent(search)}`);
    const results = await response.json();
    const seen = TRAINER_DATA.pokedex_seen || [];
    const grid = document.getElementById('player-pokedex-results');
    grid.innerHTML = results.map(p => `
        <div class="pokedex-card ${seen.includes(p.number) ? 'pokedex-seen' : ''}" onclick="registerAndShow(${p.number})">
            <div class="pokedex-card-header">
                <span class="pokedex-number">#${String(p.number).padStart(3, '0')}</span>
                ${seen.includes(p.number) ? '<span class="seen-badge">✓ Visto</span>' : '<span class="new-badge">Novo!</span>'}
            </div>
            <h4>${p.name}</h4>
            <div class="type-badges">${formatTypes(p.types)}</div>
        </div>
    `).join('');
}

async function registerAndShow(number) {
    await registerPokedex(number);
    if (!TRAINER_DATA.pokedex_seen) TRAINER_DATA.pokedex_seen = [];
    if (!TRAINER_DATA.pokedex_seen.includes(number)) TRAINER_DATA.pokedex_seen.push(number);
    searchPlayerPokedex(); // Refresh
}

// ============================================
// TEAM MANAGEMENT
// ============================================
function addPokemon(slot) {
    document.getElementById('poke-slot').value = slot;
    clearPokemonForm();
    showElement('pokemon-edit-modal');
}

function editPokemon(slot) {
    const pokemon = playerTeam[slot];
    if (!pokemon) return;
    document.getElementById('poke-slot').value = slot;
    document.getElementById('poke-nickname').value = pokemon.nickname || '';
    document.getElementById('poke-species').value = pokemon.name || '';
    document.getElementById('poke-level').value = pokemon.level || 1;
    document.getElementById('poke-current-hp').value = pokemon.currentHp || 0;
    document.getElementById('poke-max-hp').value = pokemon.maxHp || 0;
    document.getElementById('poke-ac').value = pokemon.ac || 10;
    document.getElementById('poke-hit-dice').value = pokemon.hitDice || '';
    document.getElementById('poke-speed').value = pokemon.speed || '';
    document.getElementById('poke-saves').value = pokemon.savingThrows || '';
    if (pokemon.stats) {
        document.getElementById('poke-str').value = pokemon.stats.STR || 10;
        document.getElementById('poke-dex').value = pokemon.stats.DEX || 10;
        document.getElementById('poke-con').value = pokemon.stats.CON || 10;
        document.getElementById('poke-int').value = pokemon.stats.INT || 10;
        document.getElementById('poke-wis').value = pokemon.stats.WIS || 10;
        document.getElementById('poke-cha').value = pokemon.stats.CHA || 10;
    }
    document.getElementById('poke-moves').value = (pokemon.moves || []).join(', ');
    document.getElementById('poke-ability').value = pokemon.ability || '';
    document.getElementById('poke-hidden-ability').value = pokemon.hiddenAbility || '';
    document.getElementById('poke-held-item').value = pokemon.heldItem || '';
    document.getElementById('poke-nature').value = pokemon.nature || '';
    document.getElementById('poke-vulnerabilities').value = (pokemon.vulnerabilities || []).join(', ');
    document.getElementById('poke-resistances').value = (pokemon.resistances || []).join(', ');
    document.getElementById('poke-notes').value = pokemon.notes || '';
    showElement('pokemon-edit-modal');
}

function clearPokemonForm() {
    ['poke-nickname','poke-species','poke-hit-dice','poke-speed','poke-saves',
     'poke-ability','poke-hidden-ability','poke-held-item','poke-vulnerabilities',
     'poke-resistances','poke-notes'].forEach(id => document.getElementById(id).value = '');
    ['poke-level'].forEach(id => document.getElementById(id).value = 1);
    ['poke-current-hp','poke-max-hp'].forEach(id => document.getElementById(id).value = 0);
    ['poke-ac'].forEach(id => document.getElementById(id).value = 10);
    ['poke-str','poke-dex','poke-con','poke-int','poke-wis','poke-cha'].forEach(id => document.getElementById(id).value = 10);
    document.getElementById('poke-moves').value = '';
    document.getElementById('poke-nature').value = '';
}

async function savePokemon() {
    const slot = parseInt(document.getElementById('poke-slot').value);
    const pokemon = {
        name: document.getElementById('poke-species').value,
        nickname: document.getElementById('poke-nickname').value,
        level: parseInt(document.getElementById('poke-level').value),
        currentHp: parseInt(document.getElementById('poke-current-hp').value),
        maxHp: parseInt(document.getElementById('poke-max-hp').value),
        ac: parseInt(document.getElementById('poke-ac').value),
        hitDice: document.getElementById('poke-hit-dice').value,
        speed: document.getElementById('poke-speed').value,
        savingThrows: document.getElementById('poke-saves').value,
        stats: {
            STR: parseInt(document.getElementById('poke-str').value),
            DEX: parseInt(document.getElementById('poke-dex').value),
            CON: parseInt(document.getElementById('poke-con').value),
            INT: parseInt(document.getElementById('poke-int').value),
            WIS: parseInt(document.getElementById('poke-wis').value),
            CHA: parseInt(document.getElementById('poke-cha').value)
        },
        moves: document.getElementById('poke-moves').value.split(',').map(m => m.trim()).filter(m => m),
        ability: document.getElementById('poke-ability').value,
        hiddenAbility: document.getElementById('poke-hidden-ability').value,
        heldItem: document.getElementById('poke-held-item').value,
        nature: document.getElementById('poke-nature').value,
        vulnerabilities: document.getElementById('poke-vulnerabilities').value.split(',').map(m => m.trim()).filter(m => m),
        resistances: document.getElementById('poke-resistances').value.split(',').map(m => m.trim()).filter(m => m),
        notes: document.getElementById('poke-notes').value,
        types: []
    };
    // Auto-fill from API
    try {
        const response = await fetch(`/api/pokemon?search=${encodeURIComponent(pokemon.name.toLowerCase())}`);
        const results = await response.json();
        if (results.length > 0) {
            const r = results[0];
            pokemon.types = r.types;
            pokemon.number = r.number;
            if (!pokemon.maxHp) { pokemon.maxHp = r.hp; pokemon.currentHp = r.hp; }
            if (pokemon.ac === 10) pokemon.ac = r.ac;
        }
    } catch(e) {}
    if (slot < playerTeam.length) playerTeam[slot] = pokemon;
    else playerTeam.push(pokemon);
    await saveTeam();
    closePokemonModal();
    refreshTeamDisplay();
}

function closePokemonModal() { hideElement('pokemon-edit-modal'); }

async function saveTeam() {
    await fetch('/player/team', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team: playerTeam })
    });
}

function refreshTeamDisplay() {
    const grid = document.getElementById('team-grid');
    grid.innerHTML = '';
    for (let i = 0; i < 6; i++) {
        const slot = document.createElement('div');
        slot.className = 'team-slot';
        if (i < playerTeam.length && playerTeam[i]) {
            const poke = playerTeam[i];
            slot.innerHTML = `
                <div class="team-pokemon-card filled">
                    <h4>${poke.nickname || poke.name}</h4>
                    <span class="level-badge">Nv. ${poke.level}</span>
                    <div class="type-badges">${formatTypes(poke.types || [])}</div>
                    <small>HP: ${poke.currentHp}/${poke.maxHp} | AC: ${poke.ac}</small>
                    <div style="margin-top:0.5rem;">
                        <button class="btn btn-sm btn-secondary" onclick="editPokemon(${i})">Editar</button>
                        <button class="btn btn-sm btn-danger" onclick="removePokemon(${i})">✕</button>
                    </div>
                </div>`;
        } else {
            slot.innerHTML = `
                <div class="team-pokemon-card empty" onclick="addPokemon(${i})">
                    <span class="add-icon">+</span>
                    <span>Adicionar Pokémon</span>
                </div>`;
        }
        grid.appendChild(slot);
    }
}

async function removePokemon(slot) {
    if (confirm('Remover este Pokémon do time?')) {
        playerTeam.splice(slot, 1);
        await saveTeam();
        refreshTeamDisplay();
    }
}

// Species autocomplete
let searchTimeout = null;
document.getElementById('poke-species').addEventListener('input', function() {
    clearTimeout(searchTimeout);
    const query = this.value.trim();
    if (query.length < 2) { document.getElementById('poke-species-results').innerHTML = ''; return; }
    searchTimeout = setTimeout(async () => {
        const response = await fetch(`/api/pokemon?search=${encodeURIComponent(query)}`);
        const results = await response.json();
        document.getElementById('poke-species-results').innerHTML = results.slice(0, 8).map(p => `
            <div class="autocomplete-item" onclick='selectSpecies(${JSON.stringify(p).replace(/'/g, "&#39;")})'>
                #${p.number} ${p.name} (${p.types.join('/')})
            </div>
        `).join('');
    }, 300);
});

function selectSpecies(pokemon) {
    document.getElementById('poke-species').value = pokemon.name;
    document.getElementById('poke-species-results').innerHTML = '';
    if (pokemon.stats) {
        document.getElementById('poke-str').value = pokemon.stats.STR;
        document.getElementById('poke-dex').value = pokemon.stats.DEX;
        document.getElementById('poke-con').value = pokemon.stats.CON;
        document.getElementById('poke-int').value = pokemon.stats.INT;
        document.getElementById('poke-wis').value = pokemon.stats.WIS;
        document.getElementById('poke-cha').value = pokemon.stats.CHA;
    }
    document.getElementById('poke-max-hp').value = pokemon.hp || 0;
    document.getElementById('poke-current-hp').value = pokemon.hp || 0;
    document.getElementById('poke-ac').value = pokemon.ac || 10;
    document.getElementById('poke-hit-dice').value = pokemon.hitDice || '';
    document.getElementById('poke-speed').value = pokemon.speed || '';
    if (pokemon.startingMoves) document.getElementById('poke-moves').value = pokemon.startingMoves.join(', ');
    if (pokemon.ability) document.getElementById('poke-ability').value = pokemon.ability.name || '';
    if (pokemon.hiddenAbility) document.getElementById('poke-hidden-ability').value = pokemon.hiddenAbility.name || '';
    if (pokemon.vulnerabilities) document.getElementById('poke-vulnerabilities').value = pokemon.vulnerabilities.join(', ');
    if (pokemon.resistances) document.getElementById('poke-resistances').value = pokemon.resistances.join(', ');
    if (pokemon.savingThrows) document.getElementById('poke-saves').value = pokemon.savingThrows.join(', ');
}

// ============================================
// TRAINER DATA SAVE
// ============================================
async function saveTrainerData() {
    const data = {
        name: document.getElementById('trainer-name-input').value,
        str: parseInt(document.getElementById('trainer-str').value) || 10,
        dex: parseInt(document.getElementById('trainer-dex').value) || 10,
        con: parseInt(document.getElementById('trainer-con').value) || 10,
        int: parseInt(document.getElementById('trainer-int').value) || 10,
        wis: parseInt(document.getElementById('trainer-wis').value) || 10,
        cha: parseInt(document.getElementById('trainer-cha').value) || 10,
        hp_max: parseInt(document.getElementById('trainer-hp-max').value) || 8,
        hp_current: parseInt(document.getElementById('trainer-hp-current').value) || 8,
        race: document.getElementById('trainer-race').value,
        background: document.getElementById('trainer-background').value,
        path: document.getElementById('trainer-path').value,
        specializations: document.getElementById('trainer-specializations').value,
        proficiencies: document.getElementById('trainer-proficiencies').value,
        pokeslots: parseInt(document.getElementById('trainer-pokeslots').value) || 3,
        money: parseInt(document.getElementById('trainer-money').value) || 0,
        bag: window.bagItems || [],
        notes: document.getElementById('trainer-notes').value,
        visited_routes: TRAINER_DATA.visited_routes || []
    };
    await fetch('/player/trainer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    alert('✅ Ficha salva com sucesso!');
}

// Attribute modifier calculator
function updateModifiers() {
    ['str','dex','con','int','wis','cha'].forEach(attr => {
        const val = parseInt(document.getElementById(`trainer-${attr}`).value) || 10;
        const mod = Math.floor((val - 10) / 2);
        const el = document.getElementById(`mod-${attr}`);
        if (el) el.textContent = `(${mod >= 0 ? '+' : ''}${mod})`;
    });
}

// Badge toggle
function toggleBadge(index) {
    const badges = TRAINER_DATA.badges || [];
    const slot = document.querySelector(`.badge-slot[data-badge="${index}"]`);
    if (badges.includes(index)) {
        badges.splice(badges.indexOf(index), 1);
        slot.classList.remove('earned');
    } else {
        badges.push(index);
        slot.classList.add('earned');
    }
    TRAINER_DATA.badges = badges;
    fetch('/player/trainer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ badges })
    });
}

// ============================================
// MAP - VISITED ROUTES
// ============================================
function markRouteVisited(routeId) {
    const visited = TRAINER_DATA.visited_routes || [];
    if (!visited.includes(routeId)) {
        visited.push(routeId);
        TRAINER_DATA.visited_routes = visited;
        fetch('/player/trainer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ visited_routes: visited })
        });
        renderMapRoutes();
    }
}

function unmarkRoute(routeId) {
    const visited = TRAINER_DATA.visited_routes || [];
    const idx = visited.indexOf(routeId);
    if (idx > -1) {
        visited.splice(idx, 1);
        TRAINER_DATA.visited_routes = visited;
        fetch('/player/trainer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ visited_routes: visited })
        });
        renderMapRoutes();
    }
}

function renderMapRoutes() {
    const section = document.getElementById('map-routes-section');
    const visited = TRAINER_DATA.visited_routes || [];
    let html = '<h4>Rotas:</h4><div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem;">';
    for (const [routeId, route] of Object.entries(ROUTES_DATA)) {
        const isVisited = visited.includes(routeId);
        html += `<button class="btn btn-sm ${isVisited ? 'btn-success' : 'btn-secondary'}" 
                  onclick="${isVisited ? `unmarkRoute('${routeId}')` : `markRouteVisited('${routeId}')`}">
                  ${isVisited ? '✓ ' : ''}${route.name}</button>`;
    }
    html += '</div>';
    if (visited.length > 0) {
        html += `<p style="margin-top:0.5rem;color:var(--text-muted);">${visited.length} rotas visitadas</p>`;
    }
    section.innerHTML = html;
}

// ============================================
// INIT
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    updateModifiers();
    renderMapRoutes();
    // Listen for attribute changes
    ['str','dex','con','int','wis','cha'].forEach(attr => {
        document.getElementById(`trainer-${attr}`).addEventListener('input', updateModifiers);
    });
    // Hunt mode info
    const huntSelect = document.getElementById('hunt-mode');
    if (huntSelect) {
        huntSelect.addEventListener('change', () => {
            const info = document.getElementById('hunt-mode-info');
            const descriptions = {
                'normal': '🌿 <strong>Normal:</strong> Pokémon comuns, nível ±3 do seu. Shiny: 1%.',
                'dungeon': '🏰 <strong>Dungeon:</strong> Pokémon raros e evoluídos, nível ±5 do seu. Shiny: 5%.',
                'night': '🌙 <strong>Noturno:</strong> O terror da noite! Pokémon +3 a +10 níveis acima. Shiny: 5%.'
            };
            info.innerHTML = `<p>${descriptions[huntSelect.value]}</p>`;
        });
    }
});

// ============================================
// MEGA EVOLUTION
// ============================================
let megaUsedThisBattle = false;

async function checkMegaAvailable() {
    // Read bag from TRAINER_DATA (now array of {name, qty, file} objects)
    const bagItems = window.bagItems || TRAINER_DATA.bag || [];
    const bag = Array.isArray(bagItems) ? bagItems.map(i => typeof i === 'string' ? i : (i.name || '')).join(' ').toLowerCase() : '';
    
    const hasKeyStone = bag.includes('pedra-chave') || bag.includes('pedra chave') || bag.includes('key stone') || bag.includes('mega ring') || bag.includes('mega bracelete');
    
    if (!hasKeyStone || megaUsedThisBattle) {
        hideElement('btn-mega-evolve');
        return;
    }
    
    const poke = window.currentBattleData?.playerPokemon;
    if (!poke) { hideElement('btn-mega-evolve'); return; }
    
    const heldItem = (poke.heldItem || '').toLowerCase();
    if (!heldItem.includes('ite') && !heldItem.includes('mega')) {
        hideElement('btn-mega-evolve');
        return;
    }
    
    // Check if this pokemon has mega data
    const pokeName = poke.name || '';
    try {
        const resp = await fetch(`/api/mega/${encodeURIComponent(pokeName)}`);
        const megas = await resp.json();
        if (megas && megas.length > 0) {
            window.megaData = megas;
            showElement('btn-mega-evolve');
            return;
        }
    } catch(e) { console.error('Mega check failed:', e); }
    hideElement('btn-mega-evolve');
}

function megaEvolve() {
    if (!window.megaData || window.megaData.length === 0) return;
    
    // If multiple megas (like Charizard X/Y), let player choose
    let chosen = window.megaData[0];
    if (window.megaData.length > 1) {
        const options = window.megaData.map((m, i) => `${i+1}. ${m.megaName} (${m.stone})`).join('\n');
        const pick = prompt(`Escolha a Mega Evolução:\n${options}\nDigite o número:`);
        const idx = parseInt(pick) - 1;
        if (idx >= 0 && idx < window.megaData.length) chosen = window.megaData[idx];
        else return;
    }
    
    megaUsedThisBattle = true;
    hideElement('btn-mega-evolve');
    
    // Apply bonuses visually
    const bonuses = chosen.bonuses || {};
    const poke = window.currentBattleData.playerPokemon;
    
    // Update displayed stats
    if (poke.stats) {
        if (bonuses.STR) poke.stats.STR += bonuses.STR;
        if (bonuses.DEX) poke.stats.DEX += bonuses.DEX;
        if (bonuses.CON) poke.stats.CON += bonuses.CON;
        if (bonuses.INT) poke.stats.INT += bonuses.INT;
        if (bonuses.WIS) poke.stats.WIS += bonuses.WIS;
        if (bonuses.CHA) poke.stats.CHA += bonuses.CHA;
    }
    if (bonuses.ac) poke.ac = (poke.ac || 13) + bonuses.ac;
    if (chosen.newTypes) poke.types = chosen.newTypes;
    
    // Update UI
    const nameEl = document.getElementById('battle-player-name-full');
    nameEl.textContent = `🔮 ${chosen.megaName} Nv.${poke.level}`;
    nameEl.style.color = 'var(--accent)';
    
    document.getElementById('battle-player-ac').textContent = poke.ac;
    if (chosen.newTypes) {
        document.getElementById('battle-player-types').innerHTML = formatTypes(chosen.newTypes);
    }
    const playerStats = document.getElementById('battle-player-stats');
    if (poke.stats) {
        playerStats.innerHTML = Object.entries(poke.stats).map(([k,v]) => 
            `<span>${k}: <strong>${v}</strong> (${Math.floor((v-10)/2) >= 0 ? '+' : ''}${Math.floor((v-10)/2)})</span>`
        ).join('');
    }
    
    addBattleLog(`🔮 <strong>MEGA EVOLUÇÃO!</strong> ${poke.nickname || poke.name} → ${chosen.megaName}!`);
    addBattleLog(`  Habilidade: ${chosen.ability || '-'} | Bônus: AC+${bonuses.ac||0}, STR+${bonuses.STR||0}, DEX+${bonuses.DEX||0}`);
    
    // Notify server/master
    socket.emit('mega_evolve', { side: 'player', stone_name: chosen.stone });
}

// Listen for wild mega (master triggered)
socket.on('mega_evolved', (data) => {
    if (data.side === 'wild') {
        const bonuses = data.bonuses || {};
        const nameEl = document.getElementById('battle-enemy-name-full');
        nameEl.textContent = `🔮 ${data.mega_name} (MEGA!)`;
        nameEl.style.color = '#ff6b9d';
        addBattleLog(`🔮 <strong>O Pokémon Selvagem MEGA EVOLUIU!</strong> → ${data.mega_name}!`);
        addBattleLog(`  Nova habilidade: ${data.ability} | Bônus: AC+${bonuses.ac||0}, STR+${bonuses.STR||0}, DEX+${bonuses.DEX||0}`);
        // Update enemy AC display
        const acEl = document.getElementById('battle-enemy-ac');
        if (acEl && bonuses.ac) acEl.textContent = parseInt(acEl.textContent) + bonuses.ac;
    }
});

// ============================================
// SWITCH POKEMON IN BATTLE
// ============================================
function switchPokemon() {
    if (window.currentTurn !== 'player') { alert('Não é seu turno!'); return; }
    
    const currentPoke = window.currentBattleData?.playerPokemon;
    const list = document.getElementById('switch-pokemon-list');
    
    list.innerHTML = playerTeam.map((p, i) => {
        const isCurrent = p.name === currentPoke?.name && p.level === currentPoke?.level;
        const isFainted = (p.currentHp || 0) <= 0;
        return `
            <div class="switch-option ${isCurrent ? 'current' : ''} ${isFainted ? 'fainted' : ''}" 
                 ${!isCurrent && !isFainted ? `onclick="confirmSwitch(${i})"` : ''}>
                <strong>${p.nickname || p.name}</strong> Nv.${p.level}
                <span>HP: ${p.currentHp || p.maxHp || '?'}/${p.maxHp || '?'}</span>
                ${isCurrent ? '<em>(em batalha)</em>' : ''}
                ${isFainted ? '<em>(desmaiado)</em>' : ''}
            </div>
        `;
    }).join('');
    
    showElement('switch-pokemon-modal');
}

async function confirmSwitch(teamIdx) {
    hideElement('switch-pokemon-modal');
    
    let newPoke = playerTeam[teamIdx];
    
    // Fetch full data
    try {
        const resp = await fetch(`/api/pokemon?search=${encodeURIComponent(newPoke.name)}`);
        const results = await resp.json();
        if (results.length > 0) {
            const api = results[0];
            newPoke.number = api.number;
            if (!newPoke.stats || !newPoke.stats.STR) newPoke.stats = api.stats;
            if (!newPoke.types || newPoke.types.length === 0) newPoke.types = api.types;
            if (!newPoke.speed) newPoke.speed = api.speed;
            if (!newPoke.moves || newPoke.moves.length === 0) newPoke.moves = api.startingMoves || [];
            if (!newPoke.vulnerabilities) newPoke.vulnerabilities = api.vulnerabilities;
            if (!newPoke.resistances) newPoke.resistances = api.resistances;
            if (!newPoke.immunities) newPoke.immunities = api.immunities;
        }
    } catch(e) {}
    
    // Update battle data
    window.currentBattleData.playerPokemon = newPoke;
    
    // Update UI
    const pNum = newPoke.number || 0;
    document.getElementById('battle-player-sprite').src = pNum ? getPokemonSpriteUrl(pNum) : '';
    document.getElementById('battle-player-name-full').textContent = `${newPoke.nickname || newPoke.name} Nv.${newPoke.level}`;
    document.getElementById('battle-player-types').innerHTML = formatTypes(newPoke.types || []);
    const pHp = newPoke.currentHp || newPoke.maxHp || 20;
    const pMax = newPoke.maxHp || 20;
    document.getElementById('battle-player-hp-text-full').textContent = `${pHp}/${pMax} HP`;
    document.getElementById('battle-player-hp-bar-full').style.width = `${(pHp/pMax)*100}%`;
    document.getElementById('battle-player-ac').textContent = newPoke.ac || 10;
    document.getElementById('battle-player-speed').textContent = newPoke.speed || '30ft';
    
    if (newPoke.stats) {
        document.getElementById('battle-player-stats').innerHTML = Object.entries(newPoke.stats).map(([k,v]) => 
            `<span>${k}: <strong>${v}</strong> (${Math.floor((v-10)/2) >= 0 ? '+' : ''}${Math.floor((v-10)/2)})</span>`
        ).join('');
    }
    
    // Reload moves
    const pMoves = newPoke.moves || [];
    await loadMovesData(pMoves);
    document.getElementById('battle-player-moves').innerHTML = pMoves.map(m => renderMoveButton(m, true)).join('');
    
    addBattleLog(`🔄 Trocou para <strong>${newPoke.nickname || newPoke.name}</strong>! (gasta ação)`);
    
    // Switching uses the action - pass turn
    socket.emit('battle_action', { action_by: 'player', action_type: 'switch', move_name: `Trocou → ${newPoke.name}`, damage: 0, message: 'Troca de Pokémon' });
    
    // Check mega for new pokemon
    megaUsedThisBattle = false;
    checkMegaAvailable();
}

// ============================================
// VISUAL BAG SYSTEM
// ============================================
window.bagItems = [];
window.allItemSprites = [];

async function loadItemSprites() {
    try {
        const resp = await fetch('/api/items');
        window.allItemSprites = await resp.json();
    } catch(e) { window.allItemSprites = []; }
}

function initBag() {
    // Convert legacy bag (array of strings) to new format (array of objects)
    const rawBag = TRAINER_DATA.bag || [];
    if (rawBag.length > 0 && typeof rawBag[0] === 'string') {
        // Legacy format: "5 Pokébolas" or "Poção"
        window.bagItems = rawBag.map(line => {
            const match = line.match(/^(\d+)\s+(.+)$/);
            if (match) {
                return { name: match[2].trim(), qty: parseInt(match[1]), file: nameToFile(match[2].trim()) };
            }
            return { name: line.trim(), qty: 1, file: nameToFile(line.trim()) };
        }).filter(i => i.name);
    } else if (rawBag.length > 0 && typeof rawBag[0] === 'object') {
        window.bagItems = rawBag;
    } else {
        window.bagItems = [];
    }
    renderBag();
}

function nameToFile(name) {
    // Try to find a matching sprite file
    const normalized = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9\-]/g, '');
    const found = window.allItemSprites.find(i => 
        i.file.replace('.png', '') === normalized ||
        i.name.toLowerCase() === name.toLowerCase()
    );
    return found ? found.file : null;
}

function renderBag() {
    const grid = document.getElementById('bag-grid');
    if (!grid) return;
    if (window.bagItems.length === 0) {
        grid.innerHTML = '<p class="empty-state" style="grid-column:1/-1;">Bolsa vazia. Use a busca acima para adicionar itens.</p>';
        return;
    }
    grid.innerHTML = window.bagItems.map((item, idx) => {
        const imgSrc = item.file ? `/static/img/items/${item.file}` : '/static/img/pokeball-icon.svg';
        return `
            <div class="bag-item" title="${item.name}">
                <button class="bag-item-remove" onclick="removeBagItem(${idx})">×</button>
                <span class="bag-item-qty">${item.qty}</span>
                <img src="${imgSrc}" alt="${item.name}" onerror="this.src='/static/img/pokeball-icon.svg'">
                <span class="bag-item-name">${item.name}</span>
                <div class="bag-item-qty-controls">
                    <button onclick="changeBagQty(${idx}, -1)">−</button>
                    <button onclick="changeBagQty(${idx}, 1)">+</button>
                </div>
            </div>
        `;
    }).join('');
}

function addBagItem() {
    const searchInput = document.getElementById('bag-item-search');
    const qtyInput = document.getElementById('bag-item-qty');
    const name = searchInput.value.trim();
    const qty = parseInt(qtyInput.value) || 1;
    if (!name) return;
    
    // Check if already exists
    const existing = window.bagItems.find(i => i.name.toLowerCase() === name.toLowerCase());
    if (existing) {
        existing.qty += qty;
    } else {
        window.bagItems.push({ name, qty, file: nameToFile(name) });
    }
    
    searchInput.value = '';
    qtyInput.value = '1';
    document.getElementById('bag-item-results').innerHTML = '';
    renderBag();
}

function removeBagItem(idx) {
    window.bagItems.splice(idx, 1);
    renderBag();
}

function changeBagQty(idx, delta) {
    window.bagItems[idx].qty = Math.max(0, window.bagItems[idx].qty + delta);
    if (window.bagItems[idx].qty <= 0) {
        window.bagItems.splice(idx, 1);
    }
    renderBag();
}

// Bag item search autocomplete
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('bag-item-search');
    const resultsDiv = document.getElementById('bag-item-results');
    if (!searchInput) return;
    
    searchInput.addEventListener('input', () => {
        const query = searchInput.value.toLowerCase().trim();
        if (query.length < 2) { resultsDiv.innerHTML = ''; return; }
        
        const matches = window.allItemSprites.filter(i => 
            i.name.toLowerCase().includes(query)
        ).slice(0, 12);
        
        resultsDiv.innerHTML = matches.map(item => `
            <div class="autocomplete-item" onclick="selectBagItem('${item.name.replace(/'/g, "\\'")}', '${item.file}')">
                <img src="/static/img/items/${item.file}" width="20" height="20" style="image-rendering:pixelated;vertical-align:middle;margin-right:0.5rem;">
                ${item.name}
            </div>
        `).join('');
    });
    
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); addBagItem(); }
    });
    
    // Close on click outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
            resultsDiv.innerHTML = '';
        }
    });
});

function selectBagItem(name, file) {
    document.getElementById('bag-item-search').value = name;
    document.getElementById('bag-item-results').innerHTML = '';
    // Auto-set file for this item
    window._selectedItemFile = file;
}

// Override nameToFile to use selection when available
const _origNameToFile = nameToFile;
function nameToFileWithCache(name) {
    if (window._selectedItemFile) {
        const f = window._selectedItemFile;
        window._selectedItemFile = null;
        return f;
    }
    return _origNameToFile(name);
}
// Patch addBagItem to use it
const _origAddBagItem = addBagItem;

// ============================================
// AVATAR UPLOAD
// ============================================
async function uploadAvatar(input) {
    if (!input.files || !input.files[0]) return;
    const formData = new FormData();
    formData.append('avatar', input.files[0]);
    
    try {
        const resp = await fetch('/player/avatar', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
            document.getElementById('trainer-avatar-img').src = data.avatar_url + '?t=' + Date.now();
        } else {
            alert('Erro: ' + (data.error || 'Falha no upload'));
        }
    } catch(e) {
        alert('Erro no upload da imagem');
    }
}

// ============================================
// SPECIALIZATION AUTOCOMPLETE
// ============================================
const SPECIALIZATIONS_LIST = [
    // Treinador Ás
    'Líder Nato', 'Estrategista', 'Comandante de Batalha',
    // Versátil
    'Piromaníaco', 'Nadador', 'Alpinista', 'Acrobata', 'Lutador',
    'Naturalista', 'Músico', 'Cozinheiro', 'Inventor',
    // Mentor Pokémon
    'Criador', 'Curandeiro', 'Treinador de Pokémon',
    // Pesquisador
    'Arqueólogo', 'Biólogo', 'Paleontólogo', 'Químico', 'Meteorologista',
    'Geólogo', 'Tecnólogo', 'Professor',
    // Colecionador Pokémon
    'Caçador de Shinies', 'Completista', 'Colecionador de Fósseis',
    // Extras comuns
    'Detetive', 'Guarda', 'Médico', 'Artista', 'Explorador',
    'Pirata', 'Ninja', 'Cavaleiro', 'Ranger', 'Coordenador',
    'Cientista', 'Ferreiro', 'Pescador', 'Surfista',
    'Mergulhador', 'Ciclista', 'Corredor', 'Ladrão',
    'Espião', 'Diplomata', 'Comerciante', 'Fazendeiro'
];

document.addEventListener('DOMContentLoaded', () => {
    const specInput = document.getElementById('trainer-specializations');
    const specResults = document.getElementById('spec-autocomplete');
    if (!specInput || !specResults) return;
    
    specInput.addEventListener('input', () => {
        const val = specInput.value;
        // Get the last part after comma
        const parts = val.split(',');
        const query = parts[parts.length - 1].trim().toLowerCase();
        
        if (query.length < 1) { specResults.innerHTML = ''; return; }
        
        const matches = SPECIALIZATIONS_LIST.filter(s => 
            s.toLowerCase().includes(query)
        ).slice(0, 8);
        
        if (matches.length === 0) { specResults.innerHTML = ''; return; }
        
        specResults.innerHTML = matches.map(s => `
            <div class="autocomplete-item" onclick="selectSpecialization('${s}')">${s}</div>
        `).join('');
    });
    
    specInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') specResults.innerHTML = '';
    });
    
    document.addEventListener('click', (e) => {
        if (!specInput.contains(e.target) && !specResults.contains(e.target)) {
            specResults.innerHTML = '';
        }
    });
});

function selectSpecialization(spec) {
    const input = document.getElementById('trainer-specializations');
    const parts = input.value.split(',');
    parts[parts.length - 1] = ' ' + spec;
    input.value = parts.join(',').replace(/^,\s*/, '').replace(/\s+,/g, ',');
    document.getElementById('spec-autocomplete').innerHTML = '';
    input.focus();
}

// ============================================
// INIT BAG ON PAGE LOAD
// ============================================
document.addEventListener('DOMContentLoaded', async () => {
    await loadItemSprites();
    initBag();
});


// ============================================
// PVP ARENA SYSTEM
// ============================================
window.pvpState = { inArena: false, currentBattle: null };

// Join arena when tab is clicked
document.addEventListener('DOMContentLoaded', () => {
    const pvpTab = document.querySelector('[data-tab="pvp"]');
    if (pvpTab) {
        pvpTab.addEventListener('click', () => {
            if (!window.pvpState.inArena) {
                socket.emit('pvp_join_arena', {});
                window.pvpState.inArena = true;
            }
        });
    }
});

// Receive player list
socket.on('pvp_arena_players', (players) => {
    renderPvpPlayers(players);
});

socket.on('pvp_player_joined', (player) => {
    // Just refresh the list
    socket.emit('pvp_join_arena', {});
});

function renderPvpPlayers(players) {
    const container = document.getElementById('pvp-players-list');
    if (!container) return;
    if (players.length === 0) {
        container.innerHTML = '<p class="empty-state">Nenhum jogador disponível.</p>';
        return;
    }
    const currentId = TRAINER_DATA.name || '';
    container.innerHTML = players.map(p => {
        const isSelf = (p.name === TRAINER_DATA.name);
        return `
            <div class="pvp-player-card ${isSelf ? 'is-self' : ''}">
                <span class="pvp-player-name">${p.name}</span>
                <span class="pvp-player-level">Nv.${p.level} | Time: ${p.team_size} Pokémon</span>
                ${!isSelf ? `<button class="btn btn-sm btn-danger" onclick="sendPvpChallenge('${p.id}', '${p.name}')">⚔️ Desafiar</button>` : '<span style="color:var(--success);font-size:0.75rem;">Você</span>'}
            </div>
        `;
    }).join('');
}

function sendPvpChallenge(targetId, targetName) {
    const team = playerTeam || [];
    if (team.length === 0) {
        alert('Você precisa ter pelo menos 1 Pokémon no time para desafiar!');
        return;
    }
    const pokeName = team[0]?.nickname || team[0]?.name || '???';
    socket.emit('pvp_challenge', { target_id: targetId, pokemon_name: pokeName });
    addPvpMessage(`⚔️ Desafio enviado para ${targetName}! Aguardando resposta...`);
}

// Receive challenge
socket.on('pvp_challenge_received', (data) => {
    const container = document.getElementById('pvp-challenges');
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    
    container.innerHTML += `
        <div class="pvp-challenge-card" id="challenge-${data.challenger_id}">
            <div class="pvp-challenge-info">
                <strong>⚔️ ${data.challenger_name}</strong> (Nv.${data.challenger_level}) te desafiou!
                <span style="color:var(--text-muted);font-size:0.8rem;">Pokémon líder: ${data.pokemon_name}</span>
            </div>
            <div class="pvp-challenge-actions">
                <button class="btn btn-sm btn-success" onclick="acceptPvpChallenge('${data.challenger_id}', '${data.challenger_name}')">✓ Aceitar</button>
                <button class="btn btn-sm btn-danger" onclick="declinePvpChallenge('${data.challenger_id}')">✕ Recusar</button>
            </div>
        </div>
    `;
    playNotificationSound();
});

function acceptPvpChallenge(challengerId, challengerName) {
    socket.emit('pvp_accept', { challenger_id: challengerId, challenger_name: challengerName });
    const card = document.getElementById(`challenge-${challengerId}`);
    if (card) card.remove();
}

function declinePvpChallenge(challengerId) {
    socket.emit('pvp_decline', { challenger_id: challengerId });
    const card = document.getElementById(`challenge-${challengerId}`);
    if (card) card.remove();
}

// Challenge declined
socket.on('pvp_challenge_declined', (data) => {
    addPvpMessage(`❌ ${data.decliner_name} recusou seu desafio.`);
});

// PVP Battle starts
socket.on('pvp_battle_start', (data) => {
    window.pvpState.currentBattle = data;
    const area = document.getElementById('pvp-battle-area');
    const content = document.getElementById('pvp-battle-content');
    area.classList.remove('hidden');
    
    content.innerHTML = `
        <div style="text-align:center;padding:1rem;">
            <h3>⚔️ Batalha PVP vs ${data.opponent_name}</h3>
            <p>Você é: <strong>${data.you_are === 'player1' ? 'Desafiante' : 'Desafiado'}</strong></p>
            <p style="color:var(--text-muted);">Use o sistema de batalha normal. Comuniquem os turnos via chat/voz.</p>
            <p style="color:var(--text-muted);">O Mestre pode acompanhar a batalha pelo painel dele.</p>
            <div class="dice-section" style="margin-top:1rem;">
                <h4>🎲 Rolar Dados PVP</h4>
                <div class="dice-buttons">
                    <button class="btn btn-dice" onclick="pvpRollDice(4)">d4</button>
                    <button class="btn btn-dice" onclick="pvpRollDice(6)">d6</button>
                    <button class="btn btn-dice" onclick="pvpRollDice(8)">d8</button>
                    <button class="btn btn-dice" onclick="pvpRollDice(10)">d10</button>
                    <button class="btn btn-dice" onclick="pvpRollDice(12)">d12</button>
                    <button class="btn btn-dice" onclick="pvpRollDice(20)">d20</button>
                </div>
                <div id="pvp-dice-result" style="min-height:40px;margin-top:0.5rem;"></div>
            </div>
            <div id="pvp-battle-log" class="battle-log-full" style="margin-top:1rem;text-align:left;"></div>
            <div style="margin-top:1rem;">
                <button class="btn btn-success" onclick="endPvpBattle('won')">🏆 Eu Venci!</button>
                <button class="btn btn-danger" onclick="endPvpBattle('lost')">💀 Eu Perdi</button>
                <button class="btn btn-secondary" onclick="endPvpBattle('draw')">🤝 Empate</button>
            </div>
        </div>
    `;
    
    // Switch to PVP tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="pvp"]').classList.add('active');
    document.getElementById('tab-pvp').classList.add('active');
});

// PVP battle updates
socket.on('pvp_battle_update', (data) => {
    const log = document.getElementById('pvp-battle-log');
    if (log) {
        let msg = `<strong>${data.actor_name}</strong>: ${data.move_name}`;
        if (data.damage > 0) msg += ` → ${data.damage} dano`;
        if (data.message) msg += ` (${data.message})`;
        log.innerHTML += `<p>${msg}</p>`;
        log.scrollTop = log.scrollHeight;
    }
});

function pvpRollDice(sides) {
    const result = Math.floor(Math.random() * sides) + 1;
    const resultDiv = document.getElementById('pvp-dice-result');
    resultDiv.innerHTML = `<span class="dice-value">d${sides}: ${result}</span>${result === 20 ? ' 💥 CRIT!' : ''}${result === 1 ? ' 💨 Falha!' : ''}`;
    
    // Share with opponent
    if (window.pvpState.currentBattle) {
        socket.emit('pvp_action', {
            room_id: window.pvpState.currentBattle.room_id,
            action_type: 'dice',
            move_name: `🎲 d${sides}: ${result}`,
            damage: 0,
            message: result === 20 ? 'CRIT!' : (result === 1 ? 'Falha!' : '')
        });
    }
}

function endPvpBattle(result) {
    if (!window.pvpState.currentBattle) return;
    if (!confirm(`Encerrar batalha como: ${result}?`)) return;
    
    socket.emit('pvp_end', { room_id: window.pvpState.currentBattle.room_id, result });
    window.pvpState.currentBattle = null;
    document.getElementById('pvp-battle-area').classList.add('hidden');
    addPvpMessage(`Batalha PVP encerrada: ${result}`);
}

socket.on('pvp_battle_ended', (data) => {
    window.pvpState.currentBattle = null;
    document.getElementById('pvp-battle-area')?.classList.add('hidden');
    addPvpMessage(`Batalha encerrada por ${data.ender}: ${data.result}`);
});

function addPvpMessage(msg) {
    const container = document.getElementById('pvp-challenges');
    if (container) {
        const p = document.createElement('p');
        p.style.color = 'var(--text-muted)';
        p.style.fontSize = '0.85rem';
        p.innerHTML = msg;
        container.appendChild(p);
    }
}


// ============================================
// TRANSFER SYSTEM (Money & Items)
// ============================================
window.transferItems = [];

// Load players for transfer dropdown
async function loadTransferTargets() {
    try {
        const resp = await fetch('/api/players');
        const players = await resp.json();
        const select = document.getElementById('transfer-target');
        if (!select) return;
        select.innerHTML = '<option value="">Selecionar jogador...</option>' + 
            players.map(p => `<option value="${p.id}">${p.name} (Nv.${p.level})</option>`).join('');
    } catch(e) {}
}

// Search items from player's own bag for transfer
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('transfer-item-search');
    const resultsDiv = document.getElementById('transfer-item-results');
    if (!searchInput || !resultsDiv) return;
    
    searchInput.addEventListener('input', () => {
        const query = searchInput.value.toLowerCase().trim();
        if (query.length < 1) { resultsDiv.innerHTML = ''; return; }
        
        const bag = window.bagItems || [];
        const matches = bag.filter(i => i.name.toLowerCase().includes(query)).slice(0, 8);
        
        if (matches.length === 0) {
            resultsDiv.innerHTML = '<div class="autocomplete-item" style="color:var(--text-muted)">Nenhum item encontrado na bolsa</div>';
            return;
        }
        
        resultsDiv.innerHTML = matches.map(item => `
            <div class="autocomplete-item" onclick="selectTransferItem('${item.name.replace(/'/g, "\\'")}', '${item.file || ''}', ${item.qty})">
                ${item.file ? `<img src="/static/img/items/${item.file}" width="16" height="16" style="image-rendering:pixelated;vertical-align:middle;margin-right:0.4rem;">` : ''}
                ${item.name} (x${item.qty})
            </div>
        `).join('');
    });
    
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
            resultsDiv.innerHTML = '';
        }
    });
    
    // Load transfer targets when PVP tab opens
    const pvpTab = document.querySelector('[data-tab="pvp"]');
    if (pvpTab) {
        pvpTab.addEventListener('click', loadTransferTargets);
    }
});

function selectTransferItem(name, file, maxQty) {
    document.getElementById('transfer-item-search').value = name;
    document.getElementById('transfer-item-results').innerHTML = '';
    document.getElementById('transfer-item-qty').max = maxQty;
    window._transferSelectedFile = file;
}

function addTransferItem() {
    const name = document.getElementById('transfer-item-search').value.trim();
    const qty = parseInt(document.getElementById('transfer-item-qty').value) || 1;
    if (!name) return;
    
    // Validate against bag
    const bag = window.bagItems || [];
    const bagItem = bag.find(i => i.name.toLowerCase() === name.toLowerCase());
    if (!bagItem) { alert('Item não encontrado na sua bolsa!'); return; }
    if (qty > bagItem.qty) { alert(`Você só tem ${bagItem.qty}x ${name}`); return; }
    
    // Check if already in transfer list
    const existing = window.transferItems.find(i => i.name.toLowerCase() === name.toLowerCase());
    if (existing) {
        existing.qty += qty;
    } else {
        window.transferItems.push({ name, qty, file: window._transferSelectedFile || bagItem.file || '' });
    }
    
    document.getElementById('transfer-item-search').value = '';
    document.getElementById('transfer-item-qty').value = '1';
    renderTransferItems();
}

function renderTransferItems() {
    const container = document.getElementById('transfer-items-list');
    container.innerHTML = window.transferItems.map((item, idx) => `
        <span style="background:var(--darker);padding:0.2rem 0.5rem;border-radius:4px;font-size:0.8rem;display:inline-flex;align-items:center;gap:0.3rem;">
            ${item.file ? `<img src="/static/img/items/${item.file}" width="14" height="14" style="image-rendering:pixelated;">` : ''}
            ${item.qty}x ${item.name}
            <button onclick="removeTransferItem(${idx})" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:0.7rem;">✕</button>
        </span>
    `).join('');
}

function removeTransferItem(idx) {
    window.transferItems.splice(idx, 1);
    renderTransferItems();
}

async function executeTransfer() {
    const targetId = document.getElementById('transfer-target').value;
    const money = parseInt(document.getElementById('transfer-money').value) || 0;
    const items = window.transferItems;
    
    if (!targetId) { alert('Selecione um jogador!'); return; }
    if (money <= 0 && items.length === 0) { alert('Selecione dinheiro ou itens para enviar!'); return; }
    
    // Confirm
    let confirmMsg = 'Confirmar transferência:\n';
    if (money > 0) confirmMsg += `💰 ₽${money}\n`;
    items.forEach(i => confirmMsg += `📦 ${i.qty}x ${i.name}\n`);
    if (!confirm(confirmMsg)) return;
    
    const statusDiv = document.getElementById('transfer-status');
    statusDiv.innerHTML = '<span style="color:var(--warning);">Processando...</span>';
    
    try {
        const resp = await fetch('/player/transfer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: targetId, money, items })
        });
        const data = await resp.json();
        
        if (data.success) {
            statusDiv.innerHTML = `<span style="color:var(--success);">✅ ${data.message}</span>`;
            // Update local money display
            TRAINER_DATA.money = data.new_money;
            const moneyInput = document.getElementById('trainer-money');
            if (moneyInput) moneyInput.value = data.new_money;
            // Remove items from local bag
            items.forEach(sentItem => {
                const bagIdx = window.bagItems.findIndex(i => i.name.toLowerCase() === sentItem.name.toLowerCase());
                if (bagIdx >= 0) {
                    window.bagItems[bagIdx].qty -= sentItem.qty;
                    if (window.bagItems[bagIdx].qty <= 0) window.bagItems.splice(bagIdx, 1);
                }
            });
            renderBag();
            // Clear form
            window.transferItems = [];
            renderTransferItems();
            document.getElementById('transfer-money').value = '0';
        } else {
            statusDiv.innerHTML = `<span style="color:var(--danger);">❌ ${data.error}</span>`;
        }
    } catch(e) {
        statusDiv.innerHTML = `<span style="color:var(--danger);">❌ Erro de conexão</span>`;
    }
}

// Listen for incoming transfers
socket.on('transfer_received', (data) => {
    alert(`💸 Transferência recebida de ${data.from}!\n${data.message}`);
    // Refresh bag data
    if (data.money > 0) {
        TRAINER_DATA.money = (TRAINER_DATA.money || 0) + data.money;
        const moneyInput = document.getElementById('trainer-money');
        if (moneyInput) moneyInput.value = TRAINER_DATA.money;
    }
    if (data.items && data.items.length > 0) {
        data.items.forEach(item => {
            const existing = window.bagItems.find(i => i.name.toLowerCase() === item.name.toLowerCase());
            if (existing) {
                existing.qty += item.qty;
            } else {
                window.bagItems.push({ name: item.name, qty: item.qty, file: item.file || '' });
            }
        });
        renderBag();
    }
});
