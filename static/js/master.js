/* ============================================
   POKEMON 5E RPG - MASTER JS
   ============================================ */

// ============================================
// ENCOUNTERS - MASTER BATTLE CONTROL
// ============================================
socket.on('encounter_started', (data) => {
    console.log('Encounter started:', data);
    addEncounterCard(data);
    playNotificationSound();
});

socket.on('encounter_ended', (data) => {
    const card = document.querySelector(`[data-encounter-player="${data.player_id}"]`);
    if (card) card.remove();
    checkEmptyEncounters();
});

socket.on('initiative_result', (data) => {
    const log = document.querySelector(`[data-encounter-player="${data.player_id}"] .battle-log-master`);
    if (log) {
        log.innerHTML += `<p>🎲 Iniciativa - Jogador: <strong>${data.player_initiative}</strong> (DEX ${data.player_mod >= 0 ? '+' : ''}${data.player_mod}) | Selvagem: <strong>${data.wild_initiative}</strong> (DEX ${data.wild_mod >= 0 ? '+' : ''}${data.wild_mod})</p>`;
        log.innerHTML += `<p>➡️ <strong>${data.first_turn === 'player' ? 'Jogador' : 'Pokémon Selvagem'}</strong> começa!</p>`;
        // Update turn indicator
        const turnEl = document.querySelector(`[data-encounter-player="${data.player_id}"] .turn-indicator`);
        if (turnEl) turnEl.textContent = data.first_turn === 'player' ? '🟢 Turno do Jogador' : '🔴 Turno do Selvagem (Mestre)';
        // Show master attack controls if wild goes first
        const masterControls = document.querySelector(`[data-encounter-player="${data.player_id}"] .master-attack-controls`);
        if (masterControls && data.first_turn === 'wild') masterControls.classList.remove('hidden');
    }
});

socket.on('battle_update', (data) => {
    const card = document.querySelector(`[data-encounter-player="${data.player_id}"]`);
    if (!card) return;
    const log = card.querySelector('.battle-log-master');
    const bs = data.battle_state;
    
    // Update HP bars
    const wildBar = card.querySelector('.wild-hp-bar');
    const playerBar = card.querySelector('.player-hp-bar-master');
    if (wildBar) wildBar.style.width = `${(bs.wild_hp_current / bs.wild_hp_max) * 100}%`;
    if (playerBar) playerBar.style.width = `${(bs.player_hp_current / bs.player_hp_max) * 100}%`;
    
    // Update HP text
    const wildHpText = card.querySelector('.wild-hp-text');
    const playerHpText = card.querySelector('.player-hp-text-master');
    if (wildHpText) wildHpText.textContent = `${bs.wild_hp_current}/${bs.wild_hp_max}`;
    if (playerHpText) playerHpText.textContent = `${bs.player_hp_current}/${bs.player_hp_max}`;
    
    // Log the action
    if (log) {
        const who = data.action_by === 'player' ? '🟢 Jogador' : '🔴 Selvagem';
        let msg = `${who} usou <strong>${data.move_name}</strong>`;
        if (data.damage > 0) msg += ` → ${data.damage} de dano!`;
        if (data.heal > 0) msg += ` → curou ${data.heal} HP!`;
        if (data.status_effect) msg += ` → aplicou ${data.status_effect}!`;
        if (data.message) msg += ` (${data.message})`;
        log.innerHTML += `<p>${msg}</p>`;
        log.scrollTop = log.scrollHeight;
    }
    
    // Update turn indicator
    const turnEl = card.querySelector('.turn-indicator');
    if (turnEl) turnEl.textContent = bs.turn === 'player' ? '🟢 Turno do Jogador' : '🔴 Turno do Selvagem (Mestre)';
    
    // Show/hide master controls
    const masterControls = card.querySelector('.master-attack-controls');
    if (masterControls) {
        bs.turn === 'wild' ? masterControls.classList.remove('hidden') : masterControls.classList.add('hidden');
    }
    
    // Check faint
    if (bs.wild_hp_current <= 0) {
        log.innerHTML += `<p><strong>💀 Pokémon Selvagem desmaiou!</strong></p>`;
    }
    if (bs.player_hp_current <= 0) {
        log.innerHTML += `<p><strong>😵 Pokémon do Jogador desmaiou!</strong></p>`;
    }
});

socket.on('xp_update', (data) => {
    const card = document.querySelector(`.xp-player-card[data-player-id="${data.player_id}"]`);
    if (card) {
        const bar = card.querySelector('.xp-bar');
        const info = card.querySelector('.xp-info');
        const levelBadge = card.querySelector('.level-badge');
        if (data.leveled_up) {
            levelBadge.classList.add('level-up-animation');
            setTimeout(() => levelBadge.classList.remove('level-up-animation'), 1000);
        }
        levelBadge.textContent = `Nv. ${data.level}`;
        bar.style.width = `${(data.xp / data.xp_to_next) * 100}%`;
        info.innerHTML = `<span class="level-badge">Nv. ${data.level}</span><span>${data.xp} / ${data.xp_to_next} XP</span>`;
    }
});

function addEncounterCard(data) {
    const container = document.getElementById('active-encounters');
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    
    // Store encounter data for auto-calc
    if (!window.activeEncounters) window.activeEncounters = {};
    window.activeEncounters[data.player_id] = data;
    
    const pokemon = data.pokemon;
    const playerPoke = data.player_pokemon || {};
    
    // Build moves list for wild pokemon (use pre-randomized wild_moves)
    let wildMoves = data.wild_moves || [...(pokemon.startingMoves || [])].slice(0, 4);
    
    // Load moves data for auto-calc
    loadMasterMoves(wildMoves);
    
    const card = document.createElement('div');
    card.className = 'encounter-card-full';
    card.dataset.encounterPlayer = data.player_id;
    
    card.innerHTML = `
        <div class="encounter-header">
            <h4>⚔️ ${data.player_name}</h4>
            <span class="turn-indicator">Aguardando iniciativa...</span>
            <button class="btn btn-sm btn-primary" onclick="rollInitiative('${data.player_id}')">🎲 Rolar Iniciativa</button>
        </div>
        
        <div class="battle-field-master">
            <div class="battle-col">
                <h5>🔴 ${pokemon.name} Nv.${data.level} (Selvagem)</h5>
                <img src="${getPokemonSpriteUrl(pokemon.number)}" width="80" style="image-rendering:pixelated;">
                <div class="type-badges">${formatTypes(pokemon.types)}</div>
                <div class="hp-bar-container"><div class="hp-bar enemy-hp wild-hp-bar" style="width:100%"></div></div>
                <span class="wild-hp-text">${pokemon.hp}/${pokemon.hp}</span>
                <div class="mini-stats-master">
                    <span>AC: ${pokemon.ac}</span> <span>SPD: ${pokemon.speed || '30ft'}</span>
                    ${pokemon.stats ? Object.entries(pokemon.stats).map(([k,v]) => `<span>${k}:${v}(${Math.floor((v-10)/2) >= 0 ? '+' : ''}${Math.floor((v-10)/2)})</span>`).join('') : ''}
                </div>
                <div class="wild-moves-master">
                    <strong>Moves:</strong> ${wildMoves.map(m => `<span class="move-btn">${m}</span>`).join('')}
                </div>
                ${pokemon.ability ? `<p class="ability-text"><strong>Habilidade:</strong> ${pokemon.ability.name}</p>` : ''}
                ${data.is_shiny ? '<span class="shiny-badge">✨ SHINY</span>' : ''}
            </div>
            <div class="battle-col">
                <h5>🟢 ${playerPoke.nickname || playerPoke.name || '???'} Nv.${playerPoke.level || '?'} (Jogador)</h5>
                <div class="hp-bar-container"><div class="hp-bar player-hp player-hp-bar-master" style="width:100%"></div></div>
                <span class="player-hp-text-master">${playerPoke.currentHp || playerPoke.maxHp || '?'}/${playerPoke.maxHp || '?'}</span>
                <div class="mini-stats-master">
                    <span>AC: ${playerPoke.ac || '?'}</span>
                    ${playerPoke.stats ? Object.entries(playerPoke.stats).map(([k,v]) => `<span>${k}:${v}</span>`).join('') : ''}
                </div>
            </div>
        </div>
        
        <!-- Master Attack Controls (for wild pokemon) -->
        <div class="master-attack-controls hidden">
            <h5>🔴 Ação do Pokémon Selvagem (seu turno):</h5>
            <div class="form-row">
                <div class="form-group">
                    <label>Move</label>
                    <select class="wild-move-select">
                        ${wildMoves.map(m => `<option value="${m}">${m}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Status (extra)</label>
                    <select class="wild-status-select">
                        <option value="">Nenhum</option>
                        <option value="Envenenado">Envenenado</option>
                        <option value="Queimado">Queimado</option>
                        <option value="Paralisado">Paralisado</option>
                        <option value="Congelado">Congelado</option>
                        <option value="Dormindo">Dormindo</option>
                        <option value="Confuso">Confuso</option>
                        <option value="Atordoado">Atordoado</option>
                    </select>
                </div>
                <button class="btn btn-danger" onclick="masterAttack('${data.player_id}', this)">⚔️ Atacar!</button>
            </div>
            <div class="form-row">
                <button class="btn btn-sm btn-dice" onclick="masterRollDice(20, '${data.player_id}')">🎲 d20</button>
                <button class="btn btn-sm btn-dice" onclick="masterRollDice(6, '${data.player_id}')">🎲 d6</button>
                <button class="btn btn-sm btn-dice" onclick="masterRollDice(8, '${data.player_id}')">🎲 d8</button>
                <button class="btn btn-sm btn-dice" onclick="masterRollDice(10, '${data.player_id}')">🎲 d10</button>
                <button class="btn btn-sm btn-dice" onclick="masterRollDice(12, '${data.player_id}')">🎲 d12</button>
                <button class="btn btn-sm btn-secondary" onclick="masterPassTurn('${data.player_id}')">⏭️ Passar Turno</button>
            </div>
        </div>
        
        <div class="battle-log-master"></div>
        
        <div style="margin-top:0.5rem;">
            <button class="btn btn-sm btn-secondary" onclick="endEncounterMaster('${data.player_id}')">Encerrar Encontro</button>
            ${data.is_shiny ? `<button class="btn btn-sm btn-accent" onclick="megaEvolveWild('${data.player_id}', '${pokemon.name}')">🔮 Mega Evolução (Wild)</button>` : ''}
        </div>
    `;
    
    container.appendChild(card);
}

function rollInitiative(playerId) {
    socket.emit('roll_initiative', { player_id: playerId });
}

// Load moves data for master auto-calc
async function loadMasterMoves(moveNames) {
    if (!window.masterMovesCache) window.masterMovesCache = {};
    const toFetch = moveNames.filter(m => !window.masterMovesCache[m]);
    if (toFetch.length > 0) {
        try {
            const resp = await fetch('/api/moves/batch', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({moves: toFetch})
            });
            const data = await resp.json();
            Object.assign(window.masterMovesCache, data);
        } catch(e) {}
    }
}

function masterAttack(playerId, btn) {
    const card = btn.closest('.encounter-card-full');
    const moveName = card.querySelector('.wild-move-select').value;
    const status = card.querySelector('.wild-status-select').value;
    
    // Get wild pokemon data from the card's stored encounter
    const encounter = window.activeEncounters?.[playerId];
    if (!encounter) {
        // Fallback: manual damage
        const damage = parseInt(card.querySelector('.wild-damage-input').value) || 0;
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'attack',
            move_name: moveName, damage, status_effect: status || null, message: ''
        });
        card.querySelector('.wild-damage-input').value = '0';
        card.querySelector('.wild-status-select').value = '';
        return;
    }
    
    const wildPoke = encounter.pokemon;
    const playerPoke = encounter.player_pokemon || {};
    const wildStats = wildPoke.stats || {};
    const wildLevel = encounter.level || 5;
    const moveData = window.masterMovesCache?.[moveName] || {};
    
    // Determine MOVE modifier from move's power stat
    let moveMod = 0;
    const power = (moveData.power || 'FOR').toUpperCase();
    if (power.includes('FOR')) moveMod = Math.max(moveMod, Math.floor(((wildStats.STR||10) - 10) / 2));
    if (power.includes('DES')) moveMod = Math.max(moveMod, Math.floor(((wildStats.DEX||10) - 10) / 2));
    if (power.includes('INT')) moveMod = Math.max(moveMod, Math.floor(((wildStats.INT||10) - 10) / 2));
    if (power.includes('SAB')) moveMod = Math.max(moveMod, Math.floor(((wildStats.WIS||10) - 10) / 2));
    if (power.includes('CAR')) moveMod = Math.max(moveMod, Math.floor(((wildStats.CHA||10) - 10) / 2));
    if (power.includes('CON')) moveMod = Math.max(moveMod, Math.floor(((wildStats.CON||10) - 10) / 2));
    
    // Proficiency bonus
    const profBonus = wildLevel >= 17 ? 6 : wildLevel >= 13 ? 5 : wildLevel >= 9 ? 4 : wildLevel >= 5 ? 3 : 2;
    
    // If no damage move (status), send directly
    if (!moveData.baseDamage && power === 'NENHUM') {
        const log = card.querySelector('.battle-log-master');
        if (log) log.innerHTML += `<p>🔴 Selvagem usou <strong>${moveName}</strong> (status)</p>`;
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'status',
            move_name: moveName, damage: 0, status_effect: status || null, message: moveData.description || ''
        });
        card.querySelector('.wild-status-select').value = '';
        return;
    }
    
    // Roll d20 attack
    const attackRoll = Math.floor(Math.random() * 20) + 1;
    const isCrit = attackRoll === 20;
    const isMiss = attackRoll === 1;
    const totalAttack = attackRoll + moveMod + profBonus;
    const targetAC = playerPoke.ac || 13;
    
    const log = card.querySelector('.battle-log-master');
    
    if (isMiss) {
        if (log) log.innerHTML += `<p>🔴 <strong>${moveName}</strong> → d20(${attackRoll}) + MOD(${moveMod}) + Prof(${profBonus}) = ${totalAttack} 💨 Falha Crítica!</p>`;
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'attack',
            move_name: moveName, damage: 0, message: 'Nat 1 - Falha'
        });
    } else if (totalAttack >= targetAC || isCrit) {
        // Calculate damage
        const diceRoll = rollDamageMaster(moveData.baseDamage || '1d6');
        let damage = diceRoll + moveMod;
        if (isCrit) {
            const critExtra = rollDamageMaster(moveData.baseDamage || '1d6');
            damage = diceRoll + critExtra + moveMod;
        }
        
        // STAB
        const wildTypes = (wildPoke.types || []).map(t => t.toLowerCase());
        const moveType = (moveData.type || '').toLowerCase();
        const stabTable = [0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5];
        const stab = wildTypes.includes(moveType) ? (stabTable[wildLevel] || 0) : 0;
        damage += stab;
        if (damage < 1) damage = 1;
        
        // Type effectiveness vs player pokemon
        const pVulns = (playerPoke.vulnerabilities || []).map(t => t.toLowerCase());
        const pResists = (playerPoke.resistances || []).map(t => t.toLowerCase());
        const pImmunities = (playerPoke.immunities || []).map(t => t.toLowerCase());
        
        let effectiveness = 1;
        let effectLabel = '';
        if (pImmunities.includes(moveType)) {
            effectiveness = 0;
            effectLabel = '⛔ IMUNE (0x)';
        } else {
            if (pVulns.includes(moveType)) effectiveness *= 2;
            if (pResists.includes(moveType)) effectiveness *= 0.5;
        }
        
        damage = Math.floor(damage * effectiveness);
        if (effectiveness === 0) damage = 0;
        if (effectiveness > 1) effectLabel = `⚡ Super Efetivo (x${effectiveness})`;
        else if (effectiveness < 1 && effectiveness > 0) effectLabel = `🛡️ Não Efetivo (x${effectiveness})`;
        
        const powerLabel = moveData.power || 'FOR';
        if (log) log.innerHTML += `<p>🔴 <strong>${moveName}</strong> → d20(${attackRoll}) + MOD(${moveMod}) + Prof(${profBonus}) = ${totalAttack} ✅ Acertou! (AC ${targetAC}) → ${moveData.baseDamage||'1d6'}(${diceRoll}) + MOVE/${powerLabel}(${moveMod})${stab > 0 ? ` + STAB(${stab})` : ''}${isCrit ? ' x2 CRIT' : ''}${effectLabel ? ' ' + effectLabel : ''} = <strong>${damage} dano ${moveData.type||''}</strong></p>`;
        
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'attack',
            move_name: moveName, damage, status_effect: status || null,
            message: `${totalAttack} vs AC ${targetAC}${isCrit ? ' Crítico!' : ''}`
        });
    } else {
        if (log) log.innerHTML += `<p>🔴 <strong>${moveName}</strong> → d20(${attackRoll}) + MOD(${moveMod}) + Prof(${profBonus}) = ${totalAttack} ❌ Errou! (AC ${targetAC})</p>`;
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'attack',
            move_name: moveName, damage: 0, message: `Errou (${totalAttack} vs AC ${targetAC})`
        });
    }
    
    if (log) log.scrollTop = log.scrollHeight;
    card.querySelector('.wild-status-select').value = '';
}

function rollDamageMaster(diceStr) {
    if (!diceStr) return 0;
    const match = diceStr.match(/(\d+)d(\d+)/);
    if (!match) return 0;
    let total = 0;
    for (let i = 0; i < parseInt(match[1]); i++) total += Math.floor(Math.random() * parseInt(match[2])) + 1;
    return total;
}

function masterPassTurn(playerId) {
    socket.emit('battle_action', {
        player_id: playerId,
        action_by: 'master',
        action_type: 'pass',
        move_name: 'Passar',
        damage: 0,
        message: 'Selvagem passou o turno'
    });
}

function masterRollDice(sides, playerId) {
    const result = Math.floor(Math.random() * sides) + 1;
    const card = document.querySelector(`[data-encounter-player="${playerId}"]`);
    const log = card.querySelector('.battle-log-master');
    if (log) {
        log.innerHTML += `<p>🎲 Mestre rolou d${sides}: <strong>${result}</strong>${result === 20 ? ' 💥 CRÍTICO!' : ''}${result === 1 ? ' 💨 Falha Crítica!' : ''}</p>`;
        log.scrollTop = log.scrollHeight;
    }
}

function endEncounterMaster(playerId) {
    if (confirm('Encerrar este encontro?')) {
        socket.emit('end_encounter', { player_id: playerId, result: 'ended_by_master' });
    }
}

async function megaEvolveWild(playerId, pokemonName) {
    // Fetch mega data for this pokemon
    const resp = await fetch(`/api/mega/${encodeURIComponent(pokemonName)}`);
    const megas = await resp.json();
    if (!megas || megas.length === 0) {
        alert(`${pokemonName} não possui Mega Evolução.`);
        return;
    }
    let chosen = megas[0];
    if (megas.length > 1) {
        const pick = prompt(`Escolha: ${megas.map((m,i) => `${i+1}. ${m.stone}`).join(', ')}`);
        const idx = parseInt(pick) - 1;
        if (idx >= 0 && idx < megas.length) chosen = megas[idx];
        else return;
    }
    
    socket.emit('mega_evolve', { player_id: playerId, side: 'wild', stone_name: chosen.stone });
    
    // Update local display
    const card = document.querySelector(`[data-encounter-player="${playerId}"]`);
    if (card) {
        const log = card.querySelector('.battle-log-master');
        if (log) log.innerHTML += `<p>🔮 <strong>MEGA EVOLUÇÃO!</strong> ${pokemonName} → ${chosen.megaName}! Habilidade: ${chosen.ability}</p>`;
    }
}

function checkEmptyEncounters() {
    const container = document.getElementById('active-encounters');
    if (!container.querySelector('.encounter-card-full')) {
        container.innerHTML = '<p class="empty-state">Nenhum encontro ativo. Aguardando jogadores...</p>';
    }
}

// ============================================
// MANUAL ENCOUNTER
// ============================================
let manualPokemonData = null;

document.getElementById('manual-pokemon-search').addEventListener('input', async function() {
    const query = this.value.trim();
    if (query.length < 2) {
        document.getElementById('manual-pokemon-preview').innerHTML = '';
        return;
    }
    
    const response = await fetch(`/api/pokemon?search=${encodeURIComponent(query)}`);
    const results = await response.json();
    
    if (results.length > 0) {
        const pokemon = results[0];
        manualPokemonData = pokemon;
        document.getElementById('manual-pokemon-preview').innerHTML = `
            <div style="display: flex; align-items: center; gap: 1rem; margin-top: 0.5rem; padding: 0.5rem; background: var(--darker); border-radius: 8px;">
                <img src="${getPokemonSpriteUrl(pokemon.number)}" width="60" style="image-rendering: pixelated;">
                <div>
                    <strong>${pokemon.name}</strong> #${pokemon.number}<br>
                    ${formatTypes(pokemon.types)}<br>
                    <small>HP: ${pokemon.hp} | AC: ${pokemon.ac} | Min Lv: ${pokemon.minLevel}</small>
                </div>
            </div>
        `;
    }
});

function sendManualEncounter() {
    if (!manualPokemonData) {
        alert('Busque um Pokémon primeiro!');
        return;
    }
    
    const level = parseInt(document.getElementById('manual-pokemon-level').value);
    const targetPlayer = document.getElementById('manual-target-player').value;
    
    socket.emit('master_action', {
        type: 'forced_encounter',
        player_id: targetPlayer,
        pokemon: manualPokemonData,
        level: level
    });
    
    alert(`Encontro enviado para o jogador!`);
}

// ============================================
// POKEDEX
// ============================================
async function searchPokedex() {
    const search = document.getElementById('pokedex-search').value;
    const typeFilter = document.getElementById('pokedex-type-filter').value;
    
    let url = '/api/pokemon?';
    if (search) url += `search=${encodeURIComponent(search)}&`;
    if (typeFilter) url += `type=${typeFilter}&`;
    
    const response = await fetch(url);
    const results = await response.json();
    
    const grid = document.getElementById('pokedex-results');
    grid.innerHTML = results.map(p => `
        <div class="pokedex-card" onclick="showPokemonDetail(${p.number})">
            <div class="pokedex-card-header">
                <span class="pokedex-number">#${String(p.number).padStart(3, '0')}</span>
                <span>Nv.${p.minLevel}+</span>
            </div>
            <h4>${p.name}</h4>
            <div class="type-badges">${formatTypes(p.types)}</div>
            <small>HP: ${p.hp} | AC: ${p.ac}</small>
        </div>
    `).join('');
}

async function showPokemonDetail(number) {
    const response = await fetch(`/api/pokemon/${number}`);
    const p = await response.json();
    
    const content = document.getElementById('pokemon-detail-content');
    content.innerHTML = `
        <div class="pokemon-detail">
            <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem;">
                <img src="${getPokemonSpriteUrl(p.number)}" width="96" style="image-rendering: pixelated;">
                <div>
                    <h2>${p.name} #${String(p.number).padStart(3, '0')}</h2>
                    <div class="type-badges">${formatTypes(p.types)}</div>
                    <p><small>${p.size} | SR ${p.sr} | Min Level: ${p.minLevel}</small></p>
                </div>
            </div>
            
            <div class="stat-grid">
                <div class="stat-item"><div class="stat-label">HP</div><div class="stat-value">${p.hp}</div></div>
                <div class="stat-item"><div class="stat-label">AC</div><div class="stat-value">${p.ac}</div></div>
                <div class="stat-item"><div class="stat-label">Speed</div><div class="stat-value">${p.speed || '-'}</div></div>
                ${p.stats ? `
                <div class="stat-item"><div class="stat-label">STR</div><div class="stat-value">${p.stats.STR}</div></div>
                <div class="stat-item"><div class="stat-label">DEX</div><div class="stat-value">${p.stats.DEX}</div></div>
                <div class="stat-item"><div class="stat-label">CON</div><div class="stat-value">${p.stats.CON}</div></div>
                <div class="stat-item"><div class="stat-label">INT</div><div class="stat-value">${p.stats.INT}</div></div>
                <div class="stat-item"><div class="stat-label">WIS</div><div class="stat-value">${p.stats.WIS}</div></div>
                <div class="stat-item"><div class="stat-label">CHA</div><div class="stat-value">${p.stats.CHA}</div></div>
                ` : ''}
            </div>
            
            ${p.ability ? `<p><strong>Habilidade:</strong> ${p.ability.name} - ${p.ability.description}</p>` : ''}
            ${p.hiddenAbility ? `<p><strong>Hidden Ability:</strong> ${p.hiddenAbility.name} - ${p.hiddenAbility.description}</p>` : ''}
            
            ${p.vulnerabilities ? `<p><strong>Vulnerabilidades:</strong> ${p.vulnerabilities.join(', ')}</p>` : ''}
            ${p.resistances ? `<p><strong>Resistências:</strong> ${p.resistances.join(', ')}</p>` : ''}
            ${p.immunities ? `<p><strong>Imunidades:</strong> ${p.immunities.join(', ')}</p>` : ''}
            
            ${p.evolutionInfo ? `<p><strong>Evolução:</strong> ${p.evolutionInfo}</p>` : ''}
            
            ${p.startingMoves ? `
            <div style="margin-top: 0.5rem;">
                <strong>Starting Moves:</strong>
                <div class="moves-list">${p.startingMoves.map(m => `<span class="move-tag">${m}</span>`).join('')}</div>
            </div>` : ''}
            
            ${p.levelMoves ? `
            <div style="margin-top: 0.5rem;">
                <strong>Level Moves:</strong>
                ${Object.entries(p.levelMoves).map(([lv, moves]) => 
                    `<div><small>Lv.${lv}:</small> ${moves.map(m => `<span class="move-tag">${m}</span>`).join('')}</div>`
                ).join('')}
            </div>` : ''}
            
            ${p.savingThrows ? `<p><strong>Saving Throws:</strong> ${p.savingThrows.join(', ')}</p>` : ''}
            ${p.skills ? `<p><strong>Skills:</strong> ${p.skills.join(', ')}</p>` : ''}
        </div>
    `;
    
    showElement('pokemon-detail-modal');
}

function closeModal() {
    hideElement('pokemon-detail-modal');
}

// ============================================
// PLAYER FULL VIEW
// ============================================
function togglePlayerDetails(playerId) {
    const details = document.getElementById(`details-${playerId}`);
    if (details) details.classList.toggle('hidden');
}

// ============================================
// QUESTS
// ============================================
async function createQuest() {
    const title = document.getElementById('quest-title').value;
    const city = document.getElementById('quest-city').value;
    const description = document.getElementById('quest-description').value;
    const xpReward = parseInt(document.getElementById('quest-xp-reward').value) || 0;
    const checkboxes = document.querySelectorAll('input[name="quest-players"]:checked');
    const assignedTo = Array.from(checkboxes).map(cb => cb.value);
    
    if (!title) { alert('Preencha o título da quest!'); return; }
    
    const response = await fetch('/master/quests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, city, description, xp_reward: xpReward, assigned_to: assignedTo })
    });
    
    const quest = await response.json();
    const list = document.getElementById('quests-list');
    list.innerHTML += `
        <div class="quest-card" id="quest-${quest.id}">
            <div class="quest-header">
                <h4>${quest.title}</h4>
                <button class="btn btn-sm btn-success" onclick="completeQuest('${quest.id}')">✓ Completar</button>
            </div>
            <span class="quest-city">📍 ${quest.city}</span>
            <span class="quest-xp">🌟 ${quest.xp_reward} XP</span>
            <p>${quest.description}</p>
        </div>`;
    
    document.getElementById('quest-title').value = '';
    document.getElementById('quest-city').value = '';
    document.getElementById('quest-description').value = '';
    document.getElementById('quest-xp-reward').value = '50';
    checkboxes.forEach(cb => cb.checked = false);
}

async function completeQuest(questId) {
    if (!confirm('Completar esta quest e dar XP aos jogadores?')) return;
    await fetch(`/master/quests/${questId}/complete`, { method: 'POST' });
    const card = document.getElementById(`quest-${questId}`);
    if (card) { card.style.opacity = '0.5'; card.querySelector('button').remove(); }
}

// ============================================
// XP
// ============================================
async function giveXP() {
    const playerId = document.getElementById('xp-player').value;
    const amount = parseInt(document.getElementById('xp-amount').value);
    
    await fetch('/master/xp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId, xp: amount })
    });
}

async function giveXPAll() {
    const amount = parseInt(document.getElementById('xp-amount').value);
    const select = document.getElementById('xp-player');
    
    for (let option of select.options) {
        await fetch('/master/xp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ player_id: option.value, xp: amount })
        });
    }
}

// Initial pokedex load
document.addEventListener('DOMContentLoaded', () => {
    searchPokedex();
    loadNpcs();
});

// ============================================
// NPC MANAGEMENT
// ============================================
let npcTeamTemp = [];

async function addNpcPokemon() {
    const search = document.getElementById('npc-poke-search').value.trim();
    const level = parseInt(document.getElementById('npc-poke-level').value) || 10;
    if (!search) return;
    const resp = await fetch(`/api/pokemon?search=${encodeURIComponent(search)}`);
    const results = await resp.json();
    if (results.length > 0) {
        const p = results[0];
        npcTeamTemp.push({ name: p.name, number: p.number, level, types: p.types, hp: p.hp, ac: p.ac, stats: p.stats });
        renderNpcTeamPreview();
        document.getElementById('npc-poke-search').value = '';
    }
}

function renderNpcTeamPreview() {
    document.getElementById('npc-team-preview').innerHTML = npcTeamTemp.map((p, i) => 
        `<span class="team-pokemon">${p.name} Nv.${p.level} <button class="btn btn-sm btn-danger" onclick="npcTeamTemp.splice(${i},1);renderNpcTeamPreview()">✕</button></span>`
    ).join('');
}

async function saveNpc() {
    const npc = {
        name: document.getElementById('npc-name').value,
        npc_class: document.getElementById('npc-class').value,
        level: parseInt(document.getElementById('npc-level').value),
        team: npcTeamTemp,
        notes: document.getElementById('npc-notes').value
    };
    if (!npc.name) { alert('Nome obrigatório!'); return; }
    await fetch('/master/npcs', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(npc) });
    npcTeamTemp = [];
    renderNpcTeamPreview();
    document.getElementById('npc-name').value = '';
    document.getElementById('npc-class').value = '';
    document.getElementById('npc-notes').value = '';
    loadNpcs();
}

async function loadNpcs() {
    const resp = await fetch('/master/npcs');
    const npcs = await resp.json();
    const list = document.getElementById('npcs-list');
    if (!list) return;
    list.innerHTML = npcs.map(n => `
        <div class="npc-card">
            <div class="npc-header">
                <h4>${n.name}</h4>
                <span class="level-badge">Nv.${n.level}</span>
                <span style="color:var(--text-muted)">${n.npc_class}</span>
                <button class="btn btn-sm btn-danger" onclick="deleteNpc('${n.id}')">🗑️</button>
            </div>
            <div class="npc-team">${(n.team||[]).map(p => `<span class="team-pokemon">${p.name} Nv.${p.level}</span>`).join('')}</div>
            ${n.notes ? `<p class="npc-notes">${n.notes}</p>` : ''}
        </div>
    `).join('') || '<p class="empty-state">Nenhum NPC criado.</p>';
}

async function deleteNpc(id) {
    if (!confirm('Deletar este NPC?')) return;
    await fetch(`/master/npcs/${id}`, { method: 'DELETE' });
    loadNpcs();
}

// ============================================
// SITE SETTINGS (VISUAL CUSTOMIZATION)
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    // Theme radio buttons - instant apply on click
    document.querySelectorAll('input[name="theme"]').forEach(radio => {
        radio.addEventListener('change', async () => {
            const theme = radio.value;
            await updateSiteSettings({ theme });
        });
    });

    // Background radio buttons - instant apply on click
    document.querySelectorAll('input[name="background"]').forEach(radio => {
        radio.addEventListener('change', async () => {
            const background = radio.value;
            await updateSiteSettings({ background });
        });
    });

    // Load NPCs on page load
    loadNpcs();
});

async function updateSiteSettings(data) {
    try {
        const resp = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const settings = await resp.json();
        // Apply locally too (in case socket hasn't delivered yet)
        applyTheme(settings);
    } catch (e) {
        console.error('Failed to update settings:', e);
    }
}

async function saveMesaName() {
    const name = document.getElementById('settings-mesa-name').value.trim();
    if (!name) { alert('Digite um nome para a mesa!'); return; }
    await updateSiteSettings({ mesa_name: name });
}


// ============================================
// NPC GENERATOR
// ============================================
async function generateNpc() {
    const npcClass = document.getElementById('gen-npc-class').value;
    const level = parseInt(document.getElementById('gen-npc-level').value) || 10;
    const teamSize = parseInt(document.getElementById('gen-npc-team-size').value) || 3;
    const typesRaw = document.getElementById('gen-npc-types').value.trim();
    const types = typesRaw ? typesRaw.split(',').map(t => t.trim().toLowerCase()).filter(t => t) : [];
    
    const resultDiv = document.getElementById('gen-npc-result');
    resultDiv.innerHTML = '<span style="color:var(--warning);">⏳ Gerando NPC...</span>';
    
    try {
        const resp = await fetch('/master/npcs/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ npc_class: npcClass, level, team_size: teamSize, types })
        });
        const npc = await resp.json();
        
        if (npc.error) {
            resultDiv.innerHTML = `<span style="color:var(--danger);">❌ ${npc.error}</span>`;
            return;
        }
        
        resultDiv.innerHTML = `
            <div style="background:var(--darker);padding:1rem;border-radius:var(--radius);border:1px solid var(--success);">
                <h4 style="color:var(--accent);">✅ ${npc.name}</h4>
                <p style="color:var(--text-muted);font-size:0.85rem;">${npc.npc_class} | Nível ${npc.level}</p>
                <div style="margin-top:0.5rem;display:flex;flex-wrap:wrap;gap:0.3rem;">
                    ${npc.team.map(p => `
                        <span class="team-pokemon" style="display:inline-flex;align-items:center;gap:0.3rem;">
                            <img src="${getPokemonSpriteUrl(p.number)}" width="24" height="24" style="image-rendering:pixelated;">
                            ${p.name} Nv.${p.level}
                        </span>
                    `).join('')}
                </div>
                <p style="margin-top:0.5rem;color:var(--success);font-size:0.8rem;">NPC salvo com sucesso!</p>
            </div>
        `;
        
        // Refresh NPC list
        loadNpcs();
    } catch(e) {
        resultDiv.innerHTML = `<span style="color:var(--danger);">❌ Erro de conexão</span>`;
    }
}


// ============================================
// TOURNAMENT MANAGEMENT
// ============================================
window.activeTournament = null;

async function createTournament() {
    const name = document.getElementById('tourney-name').value.trim();
    const size = parseInt(document.getElementById('tourney-size').value);
    const prize1Money = parseInt(document.getElementById('tourney-prize-1-money').value) || 0;
    const prize2Money = parseInt(document.getElementById('tourney-prize-2-money').value) || 0;
    const prize3Money = parseInt(document.getElementById('tourney-prize-3-money').value) || 0;
    const prizeExtra = document.getElementById('tourney-prize-extra').value;
    const prizePlaces = parseInt(document.getElementById('tourney-prize-places').value);
    
    if (!name) { alert('Digite o nome do campeonato!'); return; }
    
    const resp = await fetch('/master/tournament', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name, max_participants: size,
            prize_1_money: prize1Money, prize_2_money: prize2Money, prize_3_money: prize3Money,
            prize_extra: prizeExtra, prize_places: prizePlaces
        })
    });
    const tournament = await resp.json();
    
    if (tournament.error) { alert(tournament.error); return; }
    
    window.activeTournament = tournament;
    showElement('tournament-active');
    document.getElementById('tourney-active-name').textContent = `🏆 ${tournament.name}`;
    showElement('tourney-registration');
    
    // Load NPCs for dropdown
    loadTourneyNpcs();
    renderTourneyParticipants();
}

async function loadTourneyNpcs() {
    const resp = await fetch('/master/npcs');
    const npcs = await resp.json();
    const select = document.getElementById('tourney-add-npc');
    select.innerHTML = npcs.map(n => `<option value="${n.id}">${n.name} (Nv.${n.level})</option>`).join('');
}

async function tourneyAddPlayer() {
    const playerId = document.getElementById('tourney-add-player').value;
    if (!playerId || !window.activeTournament) return;
    
    const resp = await fetch(`/master/tournament/${window.activeTournament.id}/participants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'player', player_id: playerId })
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    window.activeTournament.participants = data.participants;
    renderTourneyParticipants();
}

async function tourneyAddNpc() {
    const npcId = document.getElementById('tourney-add-npc').value;
    if (!npcId || !window.activeTournament) return;
    
    const resp = await fetch(`/master/tournament/${window.activeTournament.id}/participants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'npc', npc_id: npcId })
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    window.activeTournament.participants = data.participants;
    renderTourneyParticipants();
}

function renderTourneyParticipants() {
    const container = document.getElementById('tourney-participants');
    const t = window.activeTournament;
    if (!t) return;
    
    container.innerHTML = t.participants.map((p, i) => `
        <span style="background:${p.is_npc ? 'var(--warning)' : 'var(--secondary)'};color:${p.is_npc ? 'var(--dark)' : 'white'};padding:0.3rem 0.6rem;border-radius:4px;font-size:0.85rem;">
            ${i + 1}. ${p.name} ${p.is_npc ? '(NPC)' : ''}
        </span>
    `).join('');
    
    container.innerHTML += `<span style="color:var(--text-muted);font-size:0.8rem;margin-left:0.5rem;">${t.participants.length}/${t.max_participants}</span>`;
}

async function startTournament() {
    if (!window.activeTournament) return;
    const t = window.activeTournament;
    
    if (t.participants.length < 2) {
        alert('Mínimo 2 participantes para iniciar!');
        return;
    }
    
    if (!confirm(`Iniciar ${t.name} com ${t.participants.length} participantes?`)) return;
    
    const resp = await fetch(`/master/tournament/${t.id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    const data = await resp.json();
    
    if (data.error) { alert(data.error); return; }
    
    window.activeTournament.bracket = data.bracket;
    window.activeTournament.status = 'in_progress';
    window.activeTournament.current_round = 1;
    
    hideElement('tourney-registration');
    showElement('tourney-bracket');
    renderBracket();
}

function renderBracket() {
    const t = window.activeTournament;
    if (!t || !t.bracket) return;
    
    const container = document.getElementById('tourney-bracket-display');
    
    // Group by round
    const rounds = {};
    t.bracket.forEach(m => {
        if (!rounds[m.round]) rounds[m.round] = [];
        rounds[m.round].push(m);
    });
    
    const roundNames = { 1: 'Rodada 1', 2: 'Quartas', 3: 'Semifinal', 4: 'Final' };
    
    let html = '<div style="display:flex;gap:2rem;overflow-x:auto;padding:1rem 0;">';
    
    for (const [roundNum, matches] of Object.entries(rounds).sort((a, b) => a[0] - b[0])) {
        html += `<div style="min-width:220px;">`;
        html += `<h5 style="color:var(--accent);margin-bottom:0.75rem;">${roundNames[roundNum] || 'Rodada ' + roundNum}</h5>`;
        
        matches.forEach(match => {
            const p1Name = match.player1 ? match.player1.name : 'BYE';
            const p2Name = match.player2 ? match.player2.name : 'BYE';
            const isDecided = match.winner !== null;
            const p1Won = match.winner === (match.player1 ? match.player1.id : null);
            const p2Won = match.winner === (match.player2 ? match.player2.id : null);
            const canDecide = !isDecided && match.player1 && match.player2 && parseInt(roundNum) === t.current_round;
            
            html += `
                <div style="background:var(--darker);border:1px solid ${isDecided ? 'var(--success)' : 'var(--card-border)'};border-radius:var(--radius);padding:0.5rem;margin-bottom:0.5rem;">
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0;${p1Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        <span>${p1Name}</span>
                        ${canDecide ? `<button class="btn btn-sm btn-success" onclick="setMatchWinner('${match.id}', '${match.player1.id}')" style="padding:0.1rem 0.4rem;font-size:0.7rem;">✓</button>` : ''}
                        ${p1Won ? '🏆' : ''}
                    </div>
                    <div style="border-top:1px solid var(--card-border);margin:0.2rem 0;"></div>
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0;${p2Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        <span>${p2Name}</span>
                        ${canDecide ? `<button class="btn btn-sm btn-success" onclick="setMatchWinner('${match.id}', '${match.player2.id}')" style="padding:0.1rem 0.4rem;font-size:0.7rem;">✓</button>` : ''}
                        ${p2Won ? '🏆' : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
    }
    html += '</div>';
    
    // Status
    if (t.status === 'finished') {
        html += `<div style="text-align:center;margin-top:1rem;padding:1rem;background:var(--card-bg);border:2px solid var(--accent);border-radius:var(--radius);">
            <h3 style="color:var(--accent);">🏆 Campeonato Finalizado!</h3>
            ${t.results?.first ? `<p>🥇 1º: <strong>${t.results.first.name}</strong></p>` : ''}
            ${t.results?.second ? `<p>🥈 2º: <strong>${t.results.second.name}</strong></p>` : ''}
            ${t.results?.third ? `<p>🥉 3º: <strong>${t.results.third.name}</strong></p>` : ''}
        </div>`;
    }
    
    container.innerHTML = html;
}

async function setMatchWinner(matchId, winnerId) {
    const t = window.activeTournament;
    if (!t) return;
    
    const resp = await fetch(`/master/tournament/${t.id}/match/${matchId}/result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ winner_id: winnerId })
    });
    const data = await resp.json();
    
    if (data.error) { alert(data.error); return; }
    
    if (data.status === 'finished') {
        window.activeTournament.status = 'finished';
        window.activeTournament.results = data.results;
        alert('🏆 Campeonato finalizado! Prêmios distribuídos.');
    }
    
    window.activeTournament.bracket = data.bracket;
    if (data.bracket) {
        // Update current round
        const maxRound = Math.max(...data.bracket.map(m => m.round));
        window.activeTournament.current_round = maxRound;
    }
    renderBracket();
}
