/* ============================================
   POKEMON 5E RPG - MASTER JS
   ============================================ */

// ── Aprovação de mestres (só o super-admin lusmar vê este painel) ──
async function loadPendingMasters() {
    if (!window.IS_SUPER_ADMIN) return;
    const list = document.getElementById('admin-pending-list');
    const count = document.getElementById('admin-pending-count');
    try {
        const resp = await fetch('/admin/pending-masters');
        const data = await resp.json();
        const pend = data.pending || [];
        if (count) count.textContent = pend.length ? `(${pend.length} pendente${pend.length > 1 ? 's' : ''})` : '(nenhum pendente)';
        if (!list) return;
        list.innerHTML = pend.length ? pend.map(p => `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;padding:0.4rem 0.5rem;border-bottom:1px solid var(--card-border,#333);">
                <span>🧙 <strong>${p.username}</strong> <span style="opacity:0.6;font-size:0.8rem;">${p.requested_at ? p.requested_at.slice(0,10) : ''}</span></span>
                <span style="display:flex;gap:0.4rem;">
                    <button class="btn btn-sm btn-success" onclick="approveMaster('${p.id}','${p.username.replace(/'/g,"\\'")}')">✅ Aprovar</button>
                    <button class="btn btn-sm btn-danger" onclick="rejectMaster('${p.id}','${p.username.replace(/'/g,"\\'")}')">✕ Recusar</button>
                </span>
            </div>`).join('') : '<span style="opacity:0.7;">Nenhum cadastro de mestre aguardando aprovação.</span>';
    } catch(e) { if (list) list.innerHTML = '⚠️ Erro ao carregar.'; }
}

async function approveMaster(uid, username) {
    if (!confirm(`Aprovar a conta de Mestre "${username}"? Uma mesa nova será criada para ele.`)) return;
    try {
        const resp = await fetch(`/admin/masters/${uid}/approve`, { method: 'POST' });
        const data = await resp.json();
        if (data.ok) alert(`✅ ${data.username} aprovado! Código de convite da mesa dele: ${data.invite}`);
        else alert('❌ ' + (data.error || 'Falha'));
    } catch(e) { alert('❌ Erro de conexão.'); }
    loadPendingMasters();
}

async function rejectMaster(uid, username) {
    if (!confirm(`Recusar e REMOVER o cadastro de "${username}"? Esta ação não pode ser desfeita.`)) return;
    try {
        const resp = await fetch(`/admin/masters/${uid}/reject`, { method: 'POST' });
        const data = await resp.json();
        if (!data.ok) alert('❌ ' + (data.error || 'Falha'));
    } catch(e) { alert('❌ Erro de conexão.'); }
    loadPendingMasters();
}

document.addEventListener('DOMContentLoaded', () => { if (window.IS_SUPER_ADMIN) loadPendingMasters(); });

// Status condition display names + icons (must match STATUS_CONDITIONS keys in status_effects.py)
const STATUS_DISPLAY = {
    'badly_poisoned': '☠️ Envenenado',
    'queimado':       '🔥 Queimado',
    'paralisado':     '⚡ Paralisado',
    'congelado':      '🧊 Congelado',
    'dormindo':       '💤 Dormindo',
    'confuso':        '💫 Confuso',
    'atordoado':      '⭐ Atordoado',
};
function statusLabel(key) {
    return key ? (STATUS_DISPLAY[key] || key) : '';
}

// Auto mode state — o template renderiza o valor persistido no checkbox;
// lê de lá no boot (antes o JS assumia sempre true após um reload)
let wildAutoMode = document.getElementById('wild-auto-mode')
    ? document.getElementById('wild-auto-mode').checked : true;

function _paintAutoModeLabel(enabled) {
    const label = document.getElementById('auto-mode-label');
    if (!label) return;
    if (enabled) {
        label.textContent = '🤖 AUTO: ON — Wild/NPC atacam sozinhos';
        label.style.color = 'var(--success)';
    } else {
        label.textContent = '🎮 MANUAL: OFF — Mestre controla Wild/NPC';
        label.style.color = 'var(--warning)';
    }
}

function toggleAutoMode(enabled) {
    wildAutoMode = enabled;
    _paintAutoModeLabel(enabled);
    // Notify server
    socket.emit('set_auto_mode', { enabled });
}

// Eco do servidor (confirma a troca e sincroniza outras abas do mestre)
socket.on('auto_mode_changed', (data) => {
    wildAutoMode = !!data.enabled;
    const cb = document.getElementById('wild-auto-mode');
    if (cb) cb.checked = wildAutoMode;
    _paintAutoModeLabel(wildAutoMode);
});

// NPC em modo manual aguardando o mestre (Forçar Ação na aba PvP/NPC)
socket.on('npc_awaiting_master', (data) => {
    showNotification(data.message || '🤖 NPC aguardando ação do Mestre.', 'info');
});

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

// Foco de evolução: a tela do mestre também roda o overlay quando qualquer
// Pokémon da mesa evolui (showEvolutionFocus/queueEvolutionFocus em app.js).
socket.on('evolution_focus', (data) => {
    queueEvolutionFocus(data);
});

socket.on('initiative_result', (data) => {
    const log = document.querySelector(`[data-encounter-player="${data.player_id}"] .battle-log-master`);
    if (log) {
        log.innerHTML += `<p>🎲 Iniciativa - Jogador: <strong>${data.player_initiative}</strong> (SPE ${data.player_mod >= 0 ? '+' : ''}${data.player_mod}) | Selvagem: <strong>${data.wild_initiative}</strong> (SPE ${data.wild_mod >= 0 ? '+' : ''}${data.wild_mod})</p>`;
        if (data.upset) log.innerHTML += `<p>💨 <strong>Virada lendária!</strong> 20 natural vs 1 natural — o mais lento agiu primeiro!</p>`;
        log.innerHTML += `<p>➡️ <strong>${data.first_turn === 'player' ? 'Jogador' : 'Pokémon Selvagem'}</strong> começa!</p>`;
        // Update turn indicator
        const turnEl = document.querySelector(`[data-encounter-player="${data.player_id}"] .turn-indicator`);
        if (turnEl) turnEl.textContent = data.first_turn === 'player' ? '🟢 Turno do Jogador' : '🔴 Turno do Selvagem (Mestre)';
        // Show master attack controls if wild goes first AND auto is OFF
        const masterControls = document.querySelector(`[data-encounter-player="${data.player_id}"] .master-attack-controls`);
        if (masterControls && data.first_turn === 'wild' && !wildAutoMode) masterControls.classList.remove('hidden');
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
    
    // Log the action — com o cálculo v3 do servidor, mostra o log das 3
    // camadas (precisão → dano → resistência); senão, o resumo antigo
    if (log) {
        const who = data.action_by === 'player' ? '🟢 Jogador' : '🔴 Selvagem';
        const v3log = data.action_log || (data.server_calc && data.server_calc.log);
        let msg;
        if (v3log) {
            msg = `${who} — ${v3log}`;
        } else {
            msg = `${who} usou <strong>${data.move_name}</strong>`;
            if (data.damage > 0) msg += ` → <strong>${data.damage} de dano!</strong>`;
            if (data.heal > 0) msg += ` → curou ${data.heal} HP!`;
            if (data.status_effect) msg += ` → aplicou <strong>${statusLabel(data.status_effect)}</strong>!`;
            if (data.message) msg += ` <em>(${data.message})</em>`;
        }
        log.innerHTML += `<p>${msg}</p>`;
        log.scrollTop = log.scrollHeight;
    }

    // Update status badges
    const wildStatusBadge = card.querySelector('.wild-status-badge');
    const playerStatusBadge = card.querySelector('.player-status-badge');
    if (wildStatusBadge) {
        const ws = bs.wild_status;
        const wKey = ws ? (typeof ws === 'string' ? ws : ws.condition) : null;
        wildStatusBadge.textContent = wKey ? statusLabel(wKey) : '';
        wildStatusBadge.style.display = wKey ? 'inline-block' : 'none';
    }
    if (playerStatusBadge) {
        const ps = bs.player_status;
        const pKey = ps ? (typeof ps === 'string' ? ps : ps.condition) : null;
        playerStatusBadge.textContent = pKey ? statusLabel(pKey) : '';
        playerStatusBadge.style.display = pKey ? 'inline-block' : 'none';
    }

    // Update turn indicator + round counter
    const turnEl = card.querySelector('.turn-indicator');
    if (turnEl) turnEl.textContent = bs.turn === 'player' ? '🟢 Turno do Jogador' : '🔴 Turno do Selvagem (Mestre)';
    const roundEl = card.querySelector('.round-counter');
    if (roundEl) roundEl.textContent = `⚔️ Round ${bs.round || 1}`;
    
    // Show/hide master controls based on auto mode
    const masterControls = card.querySelector('.master-attack-controls');
    if (masterControls) {
        if (!wildAutoMode && bs.turn === 'wild') {
            masterControls.classList.remove('hidden');
        } else {
            masterControls.classList.add('hidden');
        }
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
            <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
                <span class="turn-indicator">Aguardando iniciativa...</span>
                <span class="round-counter" style="background:var(--darker);padding:0.2rem 0.6rem;border-radius:999px;font-size:0.8rem;font-weight:700;color:var(--accent);">⚔️ Round 1</span>
            </div>
            <button class="btn btn-sm btn-primary" onclick="rollInitiative('${data.player_id}')">🎲 Rolar Iniciativa</button>
        </div>
        
        <div class="battle-field-master">
            <div class="battle-col">
                <h5>🔴 ${pokemon.name} Nv.${data.level} (Selvagem)</h5>
                <img src="${getPokemonSpriteUrl(pokemon.number, data.is_shiny)}" width="80" style="image-rendering:pixelated;object-fit:contain;"${data.is_shiny ? ' class="sprite-shiny"' : ''}>
                <div class="type-badges">${formatTypes(pokemon.types)}</div>
                <div class="hp-bar-container"><div class="hp-bar enemy-hp wild-hp-bar" style="width:100%"></div></div>
                <span class="wild-hp-text">${pokemon.hp}/${pokemon.hp}</span>
                <span class="wild-status-badge" style="display:none;background:#7030a0;color:#fff;padding:0.1rem 0.5rem;border-radius:4px;font-size:0.75rem;margin-left:0.4rem;"></span>
                <div class="mini-stats-master">
                    <span>Desloc: ${pokemon.speed || '30ft'}</span>
                    ${pokemon.stats ? Object.entries(pokemon.stats).map(([k,v]) => `<span>${k}:${v}</span>`).join('') : ''}
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
                <span class="player-status-badge" style="display:none;background:#7030a0;color:#fff;padding:0.1rem 0.5rem;border-radius:4px;font-size:0.75rem;margin-left:0.4rem;"></span>
                <div class="mini-stats-master">
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
                        <option value="badly_poisoned">☠️ Envenenado</option>
                        <option value="queimado">🔥 Queimado</option>
                        <option value="paralisado">⚡ Paralisado</option>
                        <option value="congelado">🧊 Congelado</option>
                        <option value="dormindo">💤 Dormindo</option>
                        <option value="confuso">💫 Confuso</option>
                        <option value="atordoado">⭐ Atordoado</option>
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
    if (!moveName && !status) return;

    // v3: o SERVIDOR resolve tudo (d100 de precisão, dano, resistência d20,
    // cooldown) via _calc_wild_attack — o mestre só escolhe o golpe. O log
    // das 3 camadas volta no battle_update (action_log).
    if (moveName) {
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'attack',
            move_name: moveName, status_effect: status || null, message: ''
        });
    } else {
        // só condição, sem golpe (adjudicação direta do mestre)
        socket.emit('battle_action', {
            player_id: playerId, action_by: 'master', action_type: 'status',
            move_name: '', damage: 0, status_effect: status,
            message: 'Condição aplicada pelo Mestre'
        });
    }
    card.querySelector('.wild-status-select').value = '';
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
                    <small>HP base: ${pokemon.base_stats?.HP ?? pokemon.hp} | SPE base: ${pokemon.base_stats?.SPE ?? '?'} | Min Lv: ${pokemon.minLevel}</small>
                </div>
            </div>
        `;
    }
});

async function sendManualEncounter() {
    if (!manualPokemonData) { alert('Busque um Pokémon primeiro!'); return; }

    const level       = parseInt(document.getElementById('manual-pokemon-level').value);
    const targetPlayer = document.getElementById('manual-target-player').value;
    const isShiny     = document.getElementById('manual-shiny')?.checked || false;
    const isMega      = document.getElementById('manual-mega')?.checked  || false;

    let pokemon = { ...manualPokemonData };

    // Shiny: só a FLAG — o boost ×1.35 nos base stats é aplicado pelo
    // servidor no recálculo v2 quando o jogador recebe o encontro
    if (isShiny) pokemon.is_shiny = true;

    // 🎭 Stats de história: % por stat (só envia o que difere de 100)
    const statMods = {};
    [['hp', 'HP'], ['atk', 'ATK'], ['def', 'DEF'],
     ['spa', 'SPA'], ['spd', 'SPD'], ['spe', 'SPE']].forEach(([id, key]) => {
        const v = parseInt(document.getElementById(`manual-mod-${id}`)?.value) || 100;
        if (v !== 100) statMods[key] = Math.max(10, Math.min(500, v));
    });

    // Mega evolution: nome/tipos aqui; boost de stats aplicado no cliente
    // do jogador via applyMegaBonusesV2 (multiplicadores nos stats reais)
    let megaData = null;
    if (isMega) {
        try {
            const resp = await fetch(`/api/mega/${encodeURIComponent(pokemon.name)}`);
            const megas = await resp.json();
            if (megas && megas.length > 0) {
                megaData = megas[0];
                pokemon.mega = megaData;
                pokemon.name = megaData.megaName || pokemon.name;
                if (megaData.newTypes) pokemon.types = megaData.newTypes;
            } else {
                alert(`${manualPokemonData.name} não possui Mega Evolução.`);
                document.getElementById('manual-mega').checked = false;
            }
        } catch(e) {}
    }

    socket.emit('master_action', {
        type: 'forced_encounter',
        player_id: targetPlayer,
        pokemon,
        level,
        is_shiny: isShiny,
        is_mega: !!megaData,
        stat_mods: Object.keys(statMods).length ? statMods : null
    });

    const modsTxt = Object.keys(statMods).length
        ? ' · 🎭 ' + Object.entries(statMods).map(([k, v]) => `${k} ${v}%`).join(', ') : '';
    const flags = [isShiny ? '✨ Shiny' : '', megaData ? '🔮 Mega' : ''].filter(Boolean).join(' + ');
    alert(`Encontro enviado!${flags ? ' (' + flags + ')' : ''}${modsTxt}`);
}

function resetManualMods() {
    ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].forEach(id => {
        const el = document.getElementById(`manual-mod-${id}`);
        if (el) el.value = 100;
    });
}

// ============================================
// CAÇADA ALEATÓRIA (teste MANUAL: jogador rola d20 → mestre libera)
// ============================================
// Combina horário (dia/noite) + terreno (normal/dungeon) nos 4 modos do backend.
function _huntModeFromControls(period, terrain) {
    if (period === 'night') return terrain === 'dungeon' ? 'dungeon_night' : 'night';
    return terrain === 'dungeon' ? 'dungeon' : 'normal';
}

async function sendRandomHunt() {
    const playerId = document.getElementById('random-hunt-player')?.value;
    if (!playerId) { alert('Selecione um jogador'); return; }
    const period  = document.getElementById('random-hunt-period')?.value  || 'day';
    const terrain = document.getElementById('random-hunt-terrain')?.value || 'normal';
    const routeId = document.getElementById('random-hunt-route')?.value   || null;
    const huntMode = _huntModeFromControls(period, terrain);

    const out = document.getElementById('random-hunt-result');
    if (out) out.textContent = '⏳ Gerando caçada...';
    try {
        const resp = await fetch('/master/hunt/random', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ player_id: playerId, hunt_mode: huntMode, route_id: routeId })
        });
        const data = await resp.json();
        if (data.error) { if (out) out.textContent = `❌ ${data.error}`; return; }
        const enc = data.encounter || {};
        const p = enc.pokemon || {};
        if (out) out.innerHTML = `✅ Caçada liberada: <strong>${p.name || '?'}</strong> Nv.${enc.level || '?'} ` +
            `${enc.is_shiny ? '✨ ' : ''}${enc.ambush ? '💀 emboscada ' : ''}(${huntMode}) — enviada ao jogador.`;
    } catch(e) {
        if (out) out.textContent = '❌ Erro de conexão.';
    }
}

// Caixa de rolagens: mostra o d20 que cada jogador rolou no Teste de Caçada.
function _renderHuntRoll(r) {
    const inbox = document.getElementById('hunt-rolls-inbox');
    if (!inbox) return;
    const empty = inbox.querySelector('.empty-state');
    if (empty) empty.remove();
    const when = new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    const nat = r.roll === 20 ? ' 🌟NAT20' : r.roll === 1 ? ' 💀NAT1' : '';
    const src = r.manual ? '🎲 dado real' : '🖥️ virtual';
    const card = document.createElement('div');
    card.style.cssText = 'padding:0.45rem 0.6rem;border-radius:8px;background:rgba(255,203,5,0.1);border:1px solid rgba(255,203,5,0.35);font-size:0.88rem;';
    const mod = r.skill_mod ?? r.wis_mod ?? 0;
    card.innerHTML = `<strong>${r.player_name || 'Jogador'}</strong> — 🧭 Exploração: d20(${r.roll})${nat} ` +
        `${mod >= 0 ? '+' : ''}${mod}${r.proficient ? ' (prof.)' : ''} = <strong>${r.total}</strong> ` +
        `<span style="opacity:0.7;">· ${src} · ${r.used}/${r.limit} · ${when}</span>` +
        `<button class="btn btn-sm btn-success" style="margin-left:0.5rem;padding:0.1rem 0.5rem;" ` +
        `onclick="_selectHuntPlayer('${r.player_id}')">Selecionar</button>`;
    inbox.insertBefore(card, inbox.firstChild);
    // seleciona automaticamente o jogador que acabou de rolar
    _selectHuntPlayer(r.player_id);
}

function _selectHuntPlayer(pid) {
    const sel = document.getElementById('random-hunt-player');
    if (sel) sel.value = pid;
}

socket.on('hunt_roll', (data) => _renderHuntRoll(data));

// Testes de PERÍCIA do treinador (Afinidade, Análise, Sorte, ...) — mesma
// caixa de rolagens da caçada, com o atributo e a perícia usados.
socket.on('skill_roll', (r) => {
    const inbox = document.getElementById('hunt-rolls-inbox');
    if (!inbox) return;
    const empty = inbox.querySelector('.empty-state');
    if (empty) empty.remove();
    const when = new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    const nat = r.nat20 ? ' 🌟NAT20' : r.nat1 ? ' 💀NAT1' : '';
    const sign = r.bonus >= 0 ? '+' : '';
    const card = document.createElement('div');
    card.style.cssText = 'padding:0.45rem 0.6rem;border-radius:8px;background:rgba(94,158,255,0.1);border:1px solid rgba(94,158,255,0.35);font-size:0.88rem;';
    card.innerHTML = `<strong>${r.player_name || 'Jogador'}</strong> — ${r.skill_emoji || '🎲'} ` +
        `<strong>${r.skill}</strong> (${r.attribute_emoji || ''} ${r.attribute}${r.half_mod ? ', ½ mod' : ''}): ` +
        `d20(${r.roll})${nat} ${sign}${r.bonus}${r.proficient ? ' (prof.)' : ''} = <strong>${r.total}</strong> ` +
        `<span style="opacity:0.7;">· ${when}</span>`;
    inbox.insertBefore(card, inbox.firstChild);
});

// Rolagem de mesa (livre ou a pedido do Mestre) — mesma Caixa de Rolagens
socket.on('free_roll', (r) => {
    const inbox = document.getElementById('hunt-rolls-inbox');
    if (!inbox) return;
    const empty = inbox.querySelector('.empty-state');
    if (empty) empty.remove();
    const when = new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    const nat = r.nat20 ? ' 🌟NAT20' : r.nat1 ? ' 💀NAT1' : '';
    const sign = r.bonus >= 0 ? '+' : '';
    const src = r.manual ? '🎲 dado real' : '🖥️ virtual';
    const rollStr = r.kind === 'die' ? `d${r.sides}(${r.roll})`
        : `d20(${r.roll})${nat} ${sign}${r.bonus}${r.proficient ? ' (prof.)' : ''}`;
    const cdStr = (r.cd != null) ? ` <strong>${r.success ? '✅' : '❌'} vs CD ${r.cd}</strong>` : '';
    const noteStr = r.note ? ` <em style="opacity:0.85;">— ${r.note}</em>` : '';
    const card = document.createElement('div');
    card.style.cssText = 'padding:0.45rem 0.6rem;border-radius:8px;background:rgba(120,220,150,0.12);border:1px solid rgba(120,220,150,0.4);font-size:0.88rem;';
    card.innerHTML = `<strong>${r.player_name || 'Jogador'}</strong> — ${r.emoji || '🎲'} ` +
        `<strong>${r.label}</strong>: ${rollStr} = <strong>${r.total}</strong>${cdStr}${noteStr} ` +
        `<span style="opacity:0.7;">· ${src} · ${when}</span>`;
    inbox.insertBefore(card, inbox.firstChild);
});

// ── 🎁 Presentes do Mestre: dar Pokémon, itens ou dinheiro ──
async function _populateGiftLists() {
    const spList = document.getElementById('gift-species-list');
    if (spList && !spList.dataset.ready) {
        try {
            const resp = await fetch('/api/pokemon?search=');
            const all = await resp.json();
            spList.innerHTML = (all || []).map(p => `<option value="${p.name}">`).join('');
            spList.dataset.ready = '1';
        } catch(e) {}
    }
    const itList = document.getElementById('gift-item-list');
    if (itList && !itList.dataset.ready) {
        try {
            const resp = await fetch('/api/shop');
            const data = await resp.json();
            const items = data.items || data || [];
            itList.innerHTML = items.map(i => `<option value="${i.name}">`).join('');
            itList.dataset.ready = '1';
        } catch(e) {}
    }
}
document.addEventListener('DOMContentLoaded', _populateGiftLists);

async function givePokemon() {
    const out = document.getElementById('gift-result');
    const body = {
        player_id: document.getElementById('gift-player')?.value,
        species: document.getElementById('gift-species')?.value?.trim(),
        level: parseInt(document.getElementById('gift-level')?.value || 5),
        shiny: !!document.getElementById('gift-shiny')?.checked,
        nickname: document.getElementById('gift-nickname')?.value?.trim() || '',
        note: document.getElementById('gift-note')?.value || '',
        from: document.getElementById('gift-from')?.value || '',
    };
    if (!body.player_id || !body.species) { alert('Selecione o jogador e a espécie.'); return; }
    const resp = await fetch('/master/give-pokemon', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const r = await resp.json();
    if (out) out.textContent = r.ok
        ? `✅ ${r.pokemon.is_shiny ? '✨ ' : ''}${r.pokemon.nickname || r.pokemon.name} (Nv.${r.pokemon.level}) entregue — foi para o ${r.destination}.`
        : `❌ ${r.error || 'Falha'}`;
}

async function giveItem() {
    const out = document.getElementById('gift-result');
    const body = {
        player_id: document.getElementById('gift-player')?.value,
        item_name: document.getElementById('gift-item')?.value?.trim() || '',
        qty: parseInt(document.getElementById('gift-qty')?.value || 1),
        money: parseInt(document.getElementById('gift-money')?.value || 0),
        note: document.getElementById('gift-note')?.value || '',
        from: document.getElementById('gift-from')?.value || '',
    };
    if (!body.player_id || (!body.item_name && !body.money)) {
        alert('Informe um item e/ou dinheiro.'); return;
    }
    const resp = await fetch('/master/give-item', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const r = await resp.json();
    if (out) {
        const parts = [];
        if (r.item) parts.push(`${r.item.qty}x ${r.item.name}`);
        if (r.money) parts.push(`₽${r.money}`);
        out.textContent = r.ok ? `✅ Entregue: ${parts.join(' e ')}.` : `❌ ${r.error || 'Falha'}`;
    }
}

// Mestre pede um teste a um jogador (atributo/perícia/dado) com motivo e CD
async function requestRoll() {
    const playerId = document.getElementById('reqroll-player')?.value;
    const raw = document.getElementById('reqroll-target')?.value || 'attr:determinacao';
    const [kind, target] = raw.split(':');
    const note = document.getElementById('reqroll-note')?.value || '';
    const cdRaw = document.getElementById('reqroll-cd')?.value;
    if (!playerId) { alert('Selecione um jogador.'); return; }
    const body = { player_id: playerId, kind, target, note };
    if (cdRaw !== '' && cdRaw != null) body.cd = parseInt(cdRaw);
    const resp = await fetch('/master/request-roll', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const r = await resp.json();
    if (r.ok) {
        const note2 = document.getElementById('reqroll-note');
        if (note2) note2.value = '';
        alert('📨 Pedido de teste enviado ao jogador.');
    } else {
        alert('❌ ' + (r.error || 'Falha'));
    }
}

function _populateReqRollTargets() {
    const sel = document.getElementById('reqroll-target');
    if (!sel || sel.dataset.ready) return;
    const attrs = [['vinculo','❤️ Vínculo'],['tatica','♟️ Tática'],['conhecimento','📖 Conhecimento'],
        ['agilidade','🏃 Agilidade'],['influencia','👑 Influência'],['determinacao','🔥 Determinação']];
    const skills = ['Afinidade','Ressonância','Análise','Comando','Pesquisa','Cuidados','Atletismo',
        'Exploração','Diplomacia','Presença','Coragem','Resiliência','Sorte'];
    let html = '<optgroup label="Atributo">';
    attrs.forEach(([k,l]) => html += `<option value="attr:${k}">${l}</option>`);
    html += '</optgroup><optgroup label="Perícia">';
    skills.forEach(s => html += `<option value="skill:${s}">🎲 ${s}</option>`);
    html += '</optgroup><optgroup label="Dado">';
    [4,6,8,10,12,20,100].forEach(d => html += `<option value="die:${d}">🎲 d${d}</option>`);
    html += '</optgroup>';
    sel.innerHTML = html;
    sel.dataset.ready = '1';
}
document.addEventListener('DOMContentLoaded', _populateReqRollTargets);

// ============================================
// BATALHA EM DUPLA (caçada em grupo) — 2v1 / 2v2
// ============================================
async function startGroupHunt() {
    const p1 = document.getElementById('group-player-1')?.value;
    const p2 = document.getElementById('group-player-2')?.value;
    if (!p1 || !p2) { alert('Selecione os dois jogadores'); return; }
    if (p1 === p2) { alert('Escolha dois jogadores diferentes'); return; }
    const wildCount = parseInt(document.getElementById('group-mode')?.value || '1');
    const period  = document.getElementById('group-period')?.value  || 'day';
    const terrain = document.getElementById('group-terrain')?.value || 'normal';
    const routeId = document.getElementById('group-route')?.value   || null;
    const huntMode = _huntModeFromControls(period, terrain);

    const out = document.getElementById('group-hunt-result');
    if (out) out.textContent = '⏳ Montando batalha...';
    try {
        const resp = await fetch('/master/group-hunt', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ player_ids: [p1, p2], hunt_mode: huntMode,
                                   route_id: routeId, wild_count: wildCount })
        });
        const data = await resp.json();
        if (data.error) { if (out) out.textContent = `❌ ${data.error}`; return; }
        if (out) out.innerHTML = `✅ Batalha em dupla iniciada (${data.battle.mode}).`;
        renderGroupMonitor(data.battle);
    } catch(e) { if (out) out.textContent = '❌ Erro de conexão.'; }
}

function _hpBar(c) {
    const pct = c.maxHp ? Math.max(0, Math.round(100 * c.hp / c.maxHp)) : 0;
    const col = c.fainted ? '#666' : c.side === 'ally' ? '#4caf50' : '#e53935';
    return `<div style="background:rgba(255,255,255,0.12);border-radius:6px;height:10px;overflow:hidden;">
        <div style="width:${pct}%;height:100%;background:${col};"></div></div>`;
}

function renderGroupMonitor(view) {
    const mon = document.getElementById('group-battle-monitor');
    if (!mon || !view) return;
    mon.classList.remove('hidden');
    const rows = view.combatants.map(c => {
        const turn = c.cid === view.turn_cid ? '▶️ ' : '';
        const dead = c.fainted ? ' 💀' : '';
        const icon = c.side === 'ally' ? '🟢' : '🔴';
        return `<div style="margin:0.25rem 0;font-size:0.85rem;">
            ${turn}${icon} <strong>${c.name}</strong> Nv.${c.level || '?'}${dead}
            <span style="opacity:0.7;">(${c.hp}/${c.maxHp})</span>
            ${_hpBar(c)}</div>`;
    }).join('');
    const log = (view.log || []).slice(-6).map(l => `<div>• ${l.message || ''}</div>`).join('');
    // Botão SEMPRE que for a vez de um selvagem — não depende do checkbox
    // local (que pode estar dessincronizado do servidor após um reload).
    // O handler no servidor é idempotente: só age se for mesmo vez de selvagem.
    const curWild = view.combatants.find(c => c.cid === view.turn_cid && c.side === 'wild');
    const wildBtn = (view.phase === 'active' && curWild)
        ? `<button class="btn btn-sm btn-warning" onclick="advanceGroupWild('${view.id}')">▶️ Jogar selvagem (${curWild.name})</button>` : '';
    // Mestre sempre pode ENCERRAR a batalha em dupla (sem vencedor/XP)
    const endBtn = (view.phase === 'active')
        ? `<button class="btn btn-sm btn-danger" onclick="forceEndGroupBattle('${view.id}')">⏹ Finalizar batalha</button>` : '';
    let head = `Rodada ${view.round} · ${view.mode}`;
    if (view.phase === 'finished') {
        head = view.winner === 'ally' ? '🎉 A dupla venceu!'
             : view.winner === 'fled' ? '🏃 A dupla fugiu da batalha.'
             : view.winner === 'master_ended' ? '⏹ Batalha encerrada pelo Mestre.'
             : '💀 Os selvagens venceram!';
    }
    mon.innerHTML = `<div style="font-weight:700;margin-bottom:0.3rem;">👥 ${head}</div>${rows}
        <div style="margin-top:0.4rem;font-size:0.8rem;opacity:0.85;max-height:110px;overflow-y:auto;">${log}</div>
        <div style="margin-top:0.4rem;display:flex;gap:0.4rem;flex-wrap:wrap;">${wildBtn}${endBtn}</div>`;
}

function advanceGroupWild(battleId) {
    socket.emit('group_wild_turn', { battle_id: battleId });
}

async function forceEndGroupBattle(battleId) {
    if (!confirm('⏹ Encerrar a batalha em dupla agora? (sem vencedor nem XP)')) return;
    try {
        const r = await fetch(`/master/battles/group/${battleId}/force-end`, { method: 'POST' });
        const d = await r.json();
        if (!d.ok) showNotification('❌ ' + (d.error || 'Falha ao encerrar'), 'error');
    } catch (e) { showNotification('❌ Erro de conexão.', 'error'); }
}

socket.on('group_battle_start',  (v) => renderGroupMonitor(v));
socket.on('group_battle_update', (v) => renderGroupMonitor(v));
socket.on('group_battle_end',    (v) => renderGroupMonitor(v));

// Rehidrata batalhas após reload da página — sem isso o mestre perdia os
// cards de encontro 1v1 e o monitor da batalha em grupo (e a mesa travava).
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch('/master/battles/active');
        const data = await resp.json();
        // Encontros 1v1: o payload salvo tem o MESMO shape do evento
        // encounter_started, então o card remonta direto; depois reaplica
        // o battle_state salvo (HP/status/turno/round) por cima.
        for (const enc of Object.values(data.wild_encounters || {})) {
            if (!enc || !enc.pokemon) continue;
            if (document.querySelector(`[data-encounter-player="${enc.player_id}"]`)) continue;
            addEncounterCard(enc);
            _applyEncounterState(enc);
        }
        const groups = (data.group_battles || []).filter(g => g.phase === 'active');
        if (groups.length) renderGroupMonitor(groups[groups.length - 1]);
    } catch(e) {}
});

// Reaplica o battle_state persistido num card recém-remontado (reidratação)
function _applyEncounterState(enc) {
    const card = document.querySelector(`[data-encounter-player="${enc.player_id}"]`);
    const bs = enc.battle_state;
    if (!card || !bs) return;
    const wildBar = card.querySelector('.wild-hp-bar');
    const playerBar = card.querySelector('.player-hp-bar-master');
    if (wildBar && bs.wild_hp_max) wildBar.style.width = `${Math.max(0, (bs.wild_hp_current / bs.wild_hp_max) * 100)}%`;
    if (playerBar && bs.player_hp_max) playerBar.style.width = `${Math.max(0, (bs.player_hp_current / bs.player_hp_max) * 100)}%`;
    const wildHpText = card.querySelector('.wild-hp-text');
    const playerHpText = card.querySelector('.player-hp-text-master');
    if (wildHpText) wildHpText.textContent = `${bs.wild_hp_current}/${bs.wild_hp_max}`;
    if (playerHpText) playerHpText.textContent = `${bs.player_hp_current}/${bs.player_hp_max}`;
    const wildStatusBadge = card.querySelector('.wild-status-badge');
    const playerStatusBadge = card.querySelector('.player-status-badge');
    const wKey = bs.wild_status ? (typeof bs.wild_status === 'string' ? bs.wild_status : bs.wild_status.condition) : null;
    const pKey = bs.player_status ? (typeof bs.player_status === 'string' ? bs.player_status : bs.player_status.condition) : null;
    if (wildStatusBadge) {
        wildStatusBadge.textContent = wKey ? statusLabel(wKey) : '';
        wildStatusBadge.style.display = wKey ? 'inline-block' : 'none';
    }
    if (playerStatusBadge) {
        playerStatusBadge.textContent = pKey ? statusLabel(pKey) : '';
        playerStatusBadge.style.display = pKey ? 'inline-block' : 'none';
    }
    const turnEl = card.querySelector('.turn-indicator');
    if (turnEl && bs.initiative_rolled) {
        turnEl.textContent = bs.turn === 'player' ? '🟢 Turno do Jogador' : '🔴 Turno do Selvagem (Mestre)';
    }
    const roundEl = card.querySelector('.round-counter');
    if (roundEl) roundEl.textContent = `⚔️ Round ${bs.round || 1}`;
    const masterControls = card.querySelector('.master-attack-controls');
    if (masterControls && !wildAutoMode && bs.initiative_rolled && bs.turn === 'wild') {
        masterControls.classList.remove('hidden');
    }
    const log = card.querySelector('.battle-log-master');
    if (log) log.innerHTML += `<p>🔄 <em>Batalha retomada após recarregar a página (Round ${bs.round || 1}).</em></p>`;
}

// ============================================
// POKEDEX — Master (lista completa, sempre desbloqueada)
// ============================================
let _masterPokedexAll = [];

async function loadMasterPokedex() {
    if (_masterPokedexAll.length) { renderMasterPokedex(); return; }
    // Load slim list first (fast), then full detail on click
    const res = await fetch('/api/pokemon/all');
    _masterPokedexAll = await res.json();
    renderMasterPokedex();
}

function renderMasterPokedex() {
    const search     = (document.getElementById('pokedex-search')?.value || '').toLowerCase();
    const typeFilter = (document.getElementById('pokedex-type-filter')?.value || '').toLowerCase();

    let list = _masterPokedexAll;
    if (search)     list = list.filter(p => p.name.toLowerCase().includes(search) || String(p.number).includes(search));
    if (typeFilter) list = list.filter(p => (p.types||[]).map(t=>t.toLowerCase()).includes(typeFilter));

    const grid = document.getElementById('pokedex-results');
    if (!grid) return;
    grid.innerHTML = list.map(p => `
        <div class="pokedex-card" onclick="showPokemonDetail(${p.number})" style="cursor:pointer;">
            <div class="pokedex-card-header">
                <span class="pokedex-number">#${String(p.number).padStart(3, '0')}</span>
            </div>
            <img src="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${p.number}.png"
                 style="width:56px;height:56px;object-fit:contain;" loading="lazy" alt="${p.name}">
            <h4 style="margin:0.2rem 0 0;font-size:0.85rem;">${p.name}</h4>
            <div class="type-badges" style="margin-top:0.2rem;">${formatTypes(p.types||[])}</div>
        </div>
    `).join('');
}

async function searchPokedex() {
    if (!_masterPokedexAll.length) { await loadMasterPokedex(); return; }
    renderMasterPokedex();
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
                <div class="stat-item"><div class="stat-label">Desloc.</div><div class="stat-value">${p.speed || '-'}</div></div>
                ${p.base_stats ? `
                <div class="stat-item"><div class="stat-label">HP</div><div class="stat-value">${p.base_stats.HP || '-'}</div></div>
                <div class="stat-item"><div class="stat-label">ATK</div><div class="stat-value">${p.base_stats.ATK || '-'}</div></div>
                <div class="stat-item"><div class="stat-label">DEF</div><div class="stat-value">${p.base_stats.DEF || '-'}</div></div>
                <div class="stat-item"><div class="stat-label">SpA</div><div class="stat-value">${p.base_stats.SPA || '-'}</div></div>
                <div class="stat-item"><div class="stat-label">SpD</div><div class="stat-value">${p.base_stats.SPD || '-'}</div></div>
                <div class="stat-item"><div class="stat-label">SPE</div><div class="stat-value">${p.base_stats.SPE || '-'}</div></div>
                ` : ''}
            </div>
            <p style="font-size:0.75rem;opacity:0.7;margin:0.25rem 0;">Base stats reais (pokemondb) — o total em batalha escala com o nível.</p>
            
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
function addObjectiveField(text = '') {
    const list = document.getElementById('quest-objectives-list');
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:0.3rem;align-items:center;';
    div.innerHTML = `<input type="text" class="quest-obj-input" placeholder="Ex: Derrotar o Gym Leader" value="${text}" style="flex:1;">
        <button type="button" class="btn btn-sm btn-danger" onclick="this.parentElement.remove()">✕</button>`;
    list.appendChild(div);
}

function clearQuestForm() {
    document.getElementById('quest-edit-id').value = '';
    document.getElementById('quest-title').value = '';
    document.getElementById('quest-city').value = '';
    document.getElementById('quest-description').value = '';
    document.getElementById('quest-xp-reward').value = '50';
    document.getElementById('quest-money-reward').value = '0';
    document.getElementById('quest-repeatable').checked = false;
    document.getElementById('quest-category').value = 'main';
    document.getElementById('quest-objectives-list').innerHTML = '';
    document.getElementById('quest-items-list').innerHTML = '';
    document.querySelectorAll('input[name="quest-players"]').forEach(cb => cb.checked = false);
    document.getElementById('quest-cancel-btn').style.display = 'none';
}

function editQuest(questId) {
    const card = document.getElementById(`quest-${questId}`);
    if (!card) return;
    document.getElementById('quest-edit-id').value = questId;
    document.getElementById('quest-title').value = card.querySelector('h4')?.textContent?.trim() || '';
    document.getElementById('quest-city').value = card.querySelector('.quest-city')?.textContent?.replace('📍','').trim() || '';
    document.getElementById('quest-description').value = card.querySelector('p')?.textContent?.trim() || '';
    // Re-populate objectives
    document.getElementById('quest-objectives-list').innerHTML = '';
    card.querySelectorAll('.quest-objectives label').forEach(lbl => {
        const text = lbl.textContent.trim();
        if (text) addObjectiveField(text);
    });
    document.getElementById('quest-cancel-btn').style.display = '';
    document.getElementById('quest-title').scrollIntoView({ behavior:'smooth', block:'center' });
}

function addQuestItemField(name='', qty=1) {
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:0.4rem;align-items:center;';
    div.innerHTML = `
        <input class="quest-item-name" type="text" placeholder="Nome do item" value="${name}" style="flex:2;">
        <input class="quest-item-qty" type="number" min="1" value="${qty}" style="width:60px;">
        <button type="button" class="btn btn-sm btn-danger" onclick="this.parentElement.remove()">✕</button>`;
    document.getElementById('quest-items-list').appendChild(div);
}

async function createQuest() {
    const editId = document.getElementById('quest-edit-id').value;
    const title = document.getElementById('quest-title').value.trim();
    const city = document.getElementById('quest-city').value.trim();
    const description = document.getElementById('quest-description').value.trim();
    const category = document.getElementById('quest-category').value;
    const xpReward = parseInt(document.getElementById('quest-xp-reward').value) || 0;
    const moneyReward = parseInt(document.getElementById('quest-money-reward').value) || 0;
    const repeatable = document.getElementById('quest-repeatable').checked;
    const checkboxes = document.querySelectorAll('input[name="quest-players"]:checked');
    const assignedTo = Array.from(checkboxes).map(cb => cb.value);
    const objectives = Array.from(document.querySelectorAll('.quest-obj-input'))
        .map(i => i.value.trim()).filter(Boolean);
    const itemRows = document.querySelectorAll('#quest-items-list > div');
    const itemRewards = Array.from(itemRows).map(row => ({
        name: row.querySelector('.quest-item-name').value.trim(),
        qty: parseInt(row.querySelector('.quest-item-qty').value) || 1
    })).filter(r => r.name);

    if (!title) { alert('Preencha o título da quest!'); return; }

    const payload = { title, city, description, category,
        xp_reward: xpReward, money_reward: moneyReward,
        item_rewards: itemRewards, repeatable_per_player: repeatable,
        assigned_to: assignedTo, objectives };

    if (editId) {
        // Update existing
        const res = await fetch(`/master/quests/${editId}`, {
            method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        });
        const quest = await res.json();
        const card = document.getElementById(`quest-${editId}`);
        if (card) card.outerHTML = renderMasterQuestCard(quest);
    } else {
        // Create new
        const res = await fetch('/master/quests', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        });
        const quest = await res.json();
        document.getElementById('quests-list').insertAdjacentHTML('afterbegin', renderMasterQuestCard(quest));
    }
    clearQuestForm();
}

function renderMasterQuestCard(quest) {
    const catIcon = quest.category === 'urgent' ? '🔥' : quest.category === 'side' ? '📌' : '⭐';
    const objDone = (quest.objectives || []).filter(o => o.done).length;
    const objTotal = (quest.objectives || []).length;
    const pct = objTotal ? Math.round(objDone / objTotal * 100) : 0;
    const objHtml = objTotal ? `
        <div class="quest-progress">
            <div style="height:6px;background:var(--border);border-radius:4px;margin-bottom:3px;">
                <div style="width:${pct}%;height:100%;background:var(--success);border-radius:4px;"></div>
            </div>
            <small style="color:var(--muted);">${objDone}/${objTotal} objetivos</small>
            <div class="quest-objectives" style="margin-top:0.3rem;">
                ${(quest.objectives || []).map((o,i) => `
                    <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.85rem;cursor:pointer;${o.done?'opacity:0.5;text-decoration:line-through;':''}">
                        <input type="checkbox" ${o.done?'checked':''} onchange="masterToggleObjective('${quest.id}',${i})">
                        ${o.text}
                    </label>`).join('')}
            </div>
        </div>` : '';

    // Rewards badges
    const rewardParts = [];
    if (quest.xp_reward) rewardParts.push(`🌟 ${quest.xp_reward} XP`);
    if (quest.money_reward) rewardParts.push(`💰 ₽${quest.money_reward}`);
    (quest.item_rewards || []).forEach(r => rewardParts.push(`🎒 ${r.name}${r.qty > 1 ? ` x${r.qty}` : ''}`));
    const rewardsHtml = rewardParts.length
        ? `<div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-top:0.3rem;">${rewardParts.map(r => `<span style="background:rgba(255,255,255,0.08);padding:1px 7px;border-radius:10px;font-size:0.78rem;">${r}</span>`).join('')}</div>`
        : '';

    // Per-player completions
    const perPlayerBadge = quest.repeatable_per_player
        ? `<span style="background:rgba(59,76,202,0.25);color:#7ca7ff;padding:1px 7px;border-radius:10px;font-size:0.75rem;">👤 por jogador</span>` : '';

    const completions = quest.completions || {};
    const completionCount = Object.keys(completions).length;
    const completionHtml = quest.repeatable_per_player && completionCount
        ? `<div style="margin-top:0.3rem;font-size:0.78rem;color:var(--text-muted);">✅ ${completionCount} jogador(es) completaram</div>` : '';

    // Complete button — per-player shows player picker
    const completeBtn = quest.repeatable_per_player
        ? `<button class="btn btn-sm btn-success" onclick="completeQuestForPlayer('${quest.id}')">✓ Dar recompensa</button>`
        : `<button class="btn btn-sm btn-success" onclick="completeQuest('${quest.id}')">✓ Completar</button>`;

    return `<div class="quest-card" id="quest-${quest.id}" data-quest-id="${quest.id}">
        <div class="quest-header" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
            <span class="quest-category-badge cat-${quest.category||'main'}">${catIcon}</span>
            <h4 style="margin:0;flex:1;">${quest.title}</h4>
            ${perPlayerBadge}
            <span class="quest-city">📍 ${quest.city||''}</span>
            <button class="btn btn-sm btn-warning" onclick="editQuest('${quest.id}')">✏️</button>
            ${completeBtn}
            <button class="btn btn-sm btn-danger" onclick="deleteQuest('${quest.id}')">🗑️</button>
        </div>
        <p style="margin:0.3rem 0;color:var(--text-muted);font-size:0.9rem;">${quest.description||''}</p>
        ${rewardsHtml}
        ${completionHtml}
        ${objHtml}
    </div>`;
}

async function masterToggleObjective(questId, idx) {
    const res = await fetch(`/quests/${questId}/objectives/${idx}/toggle`, { method: 'POST' });
    const data = await res.json();
    if (data.quest) {
        const card = document.getElementById(`quest-${questId}`);
        if (card) card.outerHTML = renderMasterQuestCard(data.quest);
        if (data.auto_completed) showNotification(`✅ Quest auto-completada! Todos os objetivos marcados.`, 'success');
    }
}

async function completeQuest(questId) {
    if (!confirm('Completar esta quest e dar recompensas a todos os jogadores atribuídos?')) return;
    const res = await fetch(`/master/quests/${questId}/complete`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({})
    });
    const data = await res.json();
    if (data.success) {
        const card = document.getElementById(`quest-${questId}`);
        if (card) card.remove();
        showNotification(`✅ Quest completada! Recompensas entregues.`, 'success');
    } else {
        showNotification(`❌ ${data.error || 'Erro ao completar quest'}`, 'error');
    }
}

async function completeQuestForPlayer(questId) {
    // Build a player picker from the quest's assigned_to or all players
    const card = document.getElementById(`quest-${questId}`);
    // Collect player checkboxes visible on page
    const playerOptions = Array.from(document.querySelectorAll('input[name="quest-players"]'))
        .map(cb => ({ id: cb.value, name: cb.closest('label')?.textContent?.trim() || cb.value }));

    if (!playerOptions.length) {
        showNotification('Nenhum jogador disponível', 'error');
        return;
    }

    // Simple modal-like prompt using a quick inline form
    const existing = document.getElementById('quest-player-picker');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.id = 'quest-player-picker';
    div.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;';
    div.innerHTML = `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.5rem;min-width:260px;max-width:400px;">
            <h4 style="margin:0 0 1rem;">Dar recompensa para qual jogador?</h4>
            <div style="display:flex;flex-direction:column;gap:0.5rem;margin-bottom:1rem;">
                ${playerOptions.map(p => `
                    <label style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;">
                        <input type="radio" name="quest-reward-player" value="${p.id}"> ${p.name}
                    </label>`).join('')}
            </div>
            <div style="display:flex;gap:0.5rem;">
                <button class="btn btn-success" onclick="confirmQuestReward('${questId}')">✓ Dar recompensa</button>
                <button class="btn btn-secondary" onclick="document.getElementById('quest-player-picker').remove()">Cancelar</button>
            </div>
        </div>`;
    document.body.appendChild(div);
}

async function confirmQuestReward(questId) {
    const selected = document.querySelector('input[name="quest-reward-player"]:checked');
    if (!selected) { showNotification('Selecione um jogador', 'error'); return; }
    const playerId = selected.value;
    document.getElementById('quest-player-picker')?.remove();

    const res = await fetch(`/master/quests/${questId}/complete`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ player_id: playerId })
    });
    const data = await res.json();
    if (data.success) {
        showNotification(`✅ Recompensa entregue!`, 'success');
        // Re-render card with updated completions
        const gameState = await fetch('/api/game-state').then(r => r.json()).catch(() => null);
        if (gameState) {
            const quest = (gameState.quests || []).find(q => q.id === questId);
            if (quest) {
                const card = document.getElementById(`quest-${questId}`);
                if (card) card.outerHTML = renderMasterQuestCard(quest);
            }
        }
    } else {
        showNotification(`❌ ${data.error || 'Erro'}`, 'error');
    }
}

async function deleteQuest(questId) {
    if (!confirm('Excluir esta quest permanentemente?')) return;
    await fetch(`/master/quests/${questId}`, { method: 'DELETE' });
    const card = document.getElementById(`quest-${questId}`);
    if (card) card.remove();
}

function toggleCompletedQuests() {
    const el = document.getElementById('quests-completed');
    const btn = document.getElementById('toggle-completed-btn');
    if (!el) return;
    const visible = el.style.display !== 'none';
    el.style.display = visible ? 'none' : '';
    btn.textContent = visible ? 'Ver Completas' : 'Ocultar Completas';
}

// Real-time: quest updated from toggle
socket.on('quest_updated', (quest) => {
    const card = document.getElementById(`quest-${quest.id}`);
    if (card) card.outerHTML = renderMasterQuestCard(quest);
});
socket.on('quest_deleted', (data) => {
    const card = document.getElementById(`quest-${data.quest_id}`);
    if (card) card.remove();
});

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

async function givePokemonXP() {
    const playerId = document.getElementById('poke-xp-player').value;
    const pokemonIdx = parseInt(document.getElementById('poke-xp-slot').value);
    const amount = parseInt(document.getElementById('poke-xp-amount').value);
    if (!playerId || isNaN(pokemonIdx) || isNaN(amount) || amount <= 0) {
        alert('Preencha todos os campos corretamente.'); return;
    }
    const resp = await fetch('/master/pokemon-xp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId, pokemon_idx: pokemonIdx, xp: amount })
    });
    const result = await resp.json();
    if (result.success) {
        let msg = `✅ ${result.pokemon_name} recebeu ${amount} XP`;
        if (result.leveled_up) msg += ` e subiu para nível ${result.level}!`;
        if (result.evolution) msg += `\n🌟 Evoluiu para ${result.evolution.to}!`;
        alert(msg);
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

async function givePokemonPoints(kind) {
    const playerId = document.getElementById('poke-xp-player').value;
    const pokemonIdx = parseInt(document.getElementById('poke-xp-slot').value);
    const amount = parseInt(document.getElementById('poke-points-amount').value);
    if (!playerId || isNaN(pokemonIdx) || isNaN(amount) || amount === 0) {
        alert('Selecione jogador e Pokémon e informe uma quantidade (± diferente de 0).'); return;
    }
    const resp = await fetch('/master/pokemon-points', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId, pokemon_idx: pokemonIdx, kind, amount })
    });
    const result = await resp.json();
    if (result.success) {
        const label = kind === 'training' ? 'Treinamento' : 'Potencial';
        alert(`✅ ${label}: agora ${result.value} (disponível: ${result.statPointsAvailable})`);
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

async function loadPokemonXPSlots() {
    const playerId = document.getElementById('poke-xp-player').value;
    const slotSelect = document.getElementById('poke-xp-slot');
    slotSelect.innerHTML = '<option value="">Carregando...</option>';
    if (!playerId) { slotSelect.innerHTML = '<option value="">Selecione jogador primeiro</option>'; return; }
    const resp = await fetch(`/master/player-team/${playerId}`);
    const data = await resp.json();
    slotSelect.innerHTML = '';
    (data.team || []).forEach((p, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `${i+1}. ${p.name} (Nv. ${p.level || 1})`;
        slotSelect.appendChild(opt);
    });
    if (!slotSelect.options.length) slotSelect.innerHTML = '<option value="">Sem Pokémon</option>';
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
    if (results.length === 0) return;
    const p = results[0];

    // Stats escalados pelo nível (mesma escala dos selvagens)
    let scaled = null;
    try {
        const sresp = await fetch('/api/pokemon/stats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ number: p.number, level })
        });
        scaled = await sresp.json();
        if (scaled.error) scaled = null;
    } catch(e) {}

    // Moveset da espécie: iniciais + por nível até o nível do pokémon (últimos 4)
    let moves = [...(p.startingMoves || [])];
    try {
        const lresp = await fetch(`/api/pokemon/${p.number}/learnset`);
        const learnset = await lresp.json();
        if (!learnset.error) {
            moves = [...(learnset.starting || [])];
            Object.keys(learnset.level || {}).map(Number).sort((a, b) => a - b).forEach(lv => {
                if (lv <= level) moves.push(...learnset.level[lv]);
            });
            moves = [...new Set(moves)].slice(-4);
        }
    } catch(e) {}
    if (moves.length === 0) moves = ['Tackle'];

    npcTeamTemp.push({
        name: p.name, number: p.number, level, types: p.types,
        hp: scaled?.hp || p.hp, maxHp: scaled?.maxHp || p.hp, currentHp: scaled?.hp || p.hp,
        stats: scaled?.stats || p.stats,
        // nasce no sistema v2 (stats reais do servidor) — nunca re-inferir
        sv: 2, training: {}, defense_mode: 1,
        moves, speed: p.speed,
        ability: p.ability?.name || '',
        vulnerabilities: p.vulnerabilities || [],
        resistances: p.resistances || [],
        immunities: p.immunities || []
    });
    renderNpcTeamPreview();
    document.getElementById('npc-poke-search').value = '';
}

function renderNpcTeamPreview() {
    // Time editável: nível inline (re-escala stats/moves) + remover
    document.getElementById('npc-team-preview').innerHTML = npcTeamTemp.map((p, i) => `
        <span class="team-pokemon" style="display:inline-flex;align-items:center;gap:0.3rem;margin:0.15rem;">
            ${p.name}
            Nv.<input type="number" value="${p.level}" min="1" max="100"
                style="width:58px;padding:0.1rem 0.3rem;background:var(--darker,rgba(0,0,0,0.3));border:1px solid var(--border,#444);border-radius:4px;color:inherit;"
                onchange="updateNpcPokeLevel(${i}, this.value)">
            <button class="btn btn-sm btn-danger" onclick="npcTeamTemp.splice(${i},1);renderNpcTeamPreview()">✕</button>
        </span>`
    ).join('');
}

async function updateNpcPokeLevel(idx, value) {
    const p = npcTeamTemp[idx];
    if (!p) return;
    const level = Math.max(1, Math.min(100, parseInt(value) || 1));
    p.level = level;
    // Re-escala stats e moveset para o novo nível
    try {
        const sresp = await fetch('/api/pokemon/stats', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ number: p.number, name: p.name, level })
        });
        const scaled = await sresp.json();
        if (!scaled.error) {
            p.stats = scaled.stats; p.hp = scaled.hp; p.maxHp = scaled.maxHp;
            p.currentHp = scaled.hp;
        }
        if (p.number) {
            const lresp = await fetch(`/api/pokemon/${p.number}/learnset`);
            const learnset = await lresp.json();
            if (!learnset.error) {
                let moves = [...(learnset.starting || [])];
                Object.keys(learnset.level || {}).map(Number).sort((a, b) => a - b).forEach(lv => {
                    if (lv <= level) moves.push(...learnset.level[lv]);
                });
                moves = [...new Set(moves)].slice(-4);
                if (moves.length) p.moves = moves;
            }
        }
    } catch(e) {}
    renderNpcTeamPreview();
}

const NPC_ROLE_LABELS = {
    gym_leader: '🏟️ Líder de Ginásio',
    elite4:     '⭐ Elite 4',
    champion:   '👑 Campeão',
    rival:      '🔥 Rival',
    villain:    '💀 Vilão',
    trainer:    '🎒 Treinador',
};

async function saveNpc() {
    const editId = document.getElementById('npc-edit-id')?.value || '';
    const npc = {
        name:       document.getElementById('npc-name').value.trim(),
        npc_class:  document.getElementById('npc-class').value.trim(),
        level:      parseInt(document.getElementById('npc-level').value) || 1,
        role:       document.getElementById('npc-role')?.value || '',
        specialty:  document.getElementById('npc-specialty')?.value.trim() || '',
        money:      parseInt(document.getElementById('npc-money')?.value) || 0,
        team:       npcTeamTemp,
        notes:      document.getElementById('npc-notes').value.trim(),
        growth_rate: document.getElementById('npc-growth-rate')?.value || 'normal',
        progression_enabled: document.getElementById('npc-progression')?.checked || false
    };
    if (!npc.name) { alert('Nome obrigatório!'); return; }

    if (editId) {
        // Update existing NPC
        npc.id = editId;
        await fetch(`/master/npcs/${editId}`, {
            method: 'PUT',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(npc)
        });
    } else {
        await fetch('/master/npcs', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(npc)
        });
    }

    cancelNpcEdit();
    loadNpcs();
}

function editNpcById(id) {
    // Busca pelo id em vez de embutir o JSON no onclick — NPCs gerados têm
    // times grandes/caracteres especiais que quebravam o atributo HTML.
    const npc = (window.ALL_NPCS || []).find(n => n.id === id);
    if (!npc) { alert('NPC não encontrado — recarregue a lista.'); return; }
    editNpc(npc);
}

function editNpc(npc) {
    document.getElementById('npc-edit-id').value  = npc.id || '';
    document.getElementById('npc-name').value     = npc.name || '';
    document.getElementById('npc-class').value    = npc.npc_class || '';
    document.getElementById('npc-level').value    = npc.level || 10;
    document.getElementById('npc-role').value     = npc.role || '';
    document.getElementById('npc-specialty').value = npc.specialty || '';
    document.getElementById('npc-money').value    = npc.money || 0;
    document.getElementById('npc-notes').value    = npc.notes || '';
    const grSel = document.getElementById('npc-growth-rate');
    if (grSel) grSel.value = npc.growth_rate || 'normal';
    const progChk = document.getElementById('npc-progression');
    if (progChk) progChk.checked = !!npc.progression_enabled;
    npcTeamTemp = (npc.team || []).map(p => ({...p}));
    renderNpcTeamPreview();
    document.getElementById('npc-form-title').textContent = `✏️ Editando: ${npc.name}`;
    document.getElementById('npc-cancel-edit')?.classList.remove('hidden');
    document.getElementById('npc-form-panel')?.scrollIntoView({ behavior: 'smooth' });
}

function cancelNpcEdit() {
    document.getElementById('npc-edit-id').value  = '';
    document.getElementById('npc-name').value     = '';
    document.getElementById('npc-class').value    = '';
    document.getElementById('npc-level').value    = 10;
    document.getElementById('npc-role').value     = '';
    document.getElementById('npc-specialty').value = '';
    document.getElementById('npc-money').value    = 500;
    document.getElementById('npc-notes').value    = '';
    const grSel2 = document.getElementById('npc-growth-rate');
    if (grSel2) grSel2.value = 'normal';
    const progChk2 = document.getElementById('npc-progression');
    if (progChk2) progChk2.checked = false;
    npcTeamTemp = [];
    renderNpcTeamPreview();
    document.getElementById('npc-form-title').textContent = '✏️ Criar NPC Manual';
    document.getElementById('npc-cancel-edit')?.classList.add('hidden');
}

async function loadNpcs() {
    const resp = await fetch('/master/npcs');
    const npcs = await resp.json();
    window.ALL_NPCS = npcs;

    // Populate PVP NPC select
    const pvpSel = document.getElementById('master-pvp-npc');
    if (pvpSel) {
        pvpSel.innerHTML = '<option value="">Selecionar NPC...</option>' +
            npcs.map(n => `<option value="${n.id}">${n.name}${n.role ? ' — ' + (NPC_ROLE_LABELS[n.role]||n.role) : ''}</option>`).join('');
    }
    // Populate gym leader NPC select
    const gymSel = document.getElementById('gym-leader-npc');
    if (gymSel) {
        gymSel.innerHTML = '<option value="">— Sem NPC —</option>' +
            npcs.map(n => `<option value="${n.id}">${n.name}</option>`).join('');
    }

    const list = document.getElementById('npcs-list');
    if (!list) return;

    if (!npcs.length) { list.innerHTML = '<p class="empty-state">Nenhum NPC criado.</p>'; return; }

    const roleColors = { gym_leader:'#ff9800', elite4:'#9c27b0', champion:'#ffd700', rival:'#f44336', villain:'#607d8b', trainer:'#4caf50' };

    const growthIcons = { slow: '🐢', normal: '🚶', fast: '🐇' };
    list.innerHTML = npcs.map(n => {
        const roleLabel = NPC_ROLE_LABELS[n.role] || '';
        const roleBadge = n.role
            ? `<span style="font-size:0.75rem;padding:0.1rem 0.5rem;border-radius:10px;background:${roleColors[n.role]||'#555'};color:#fff;margin-left:0.5rem;">${roleLabel}</span>` : '';
        const teamHtml = (n.team||[]).map(p =>
            `<span class="team-pokemon">${p.nickname||p.name} Nv.${p.level}</span>`
        ).join('');
        const specialtyBadge = n.specialty
            ? `<span style="font-size:0.8rem;color:var(--muted);margin-left:0.5rem;">• ${n.specialty}</span>` : '';
        const progBadge = n.progression_enabled
            ? `<span title="Progride sozinho" style="font-size:0.75rem;padding:0.1rem 0.5rem;border-radius:10px;background:#2e7d32;color:#fff;">${growthIcons[n.growth_rate]||'🚶'} treina</span>` : '';
        const diary = (n.diary || []).slice(-15).reverse();
        const diaryHtml = diary.length
            ? diary.map(d => `<div style="padding:0.15rem 0;"><strong>${d.day_key}</strong>: ${d.message}</div>`).join('')
            : '<em>Sem registros ainda.</em>';
        return `
        <div class="npc-card">
            <div class="npc-header" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                <h4 style="margin:0">${n.name}</h4>
                <span class="level-badge">Nv.${n.level}</span>
                ${roleBadge} ${progBadge}
                <span style="color:var(--text-muted);font-size:0.85rem">${n.npc_class||''}${specialtyBadge}</span>
                <div style="margin-left:auto;display:flex;gap:0.4rem;">
                    <button class="btn btn-sm btn-secondary" onclick="editNpcById('${n.id}')">✏️ Editar</button>
                    <button class="btn btn-sm btn-secondary" onclick="this.closest('.npc-card').querySelector('.npc-diary').classList.toggle('hidden')">📖 Diário</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteNpc('${n.id}')">🗑️</button>
                </div>
            </div>
            <div class="npc-team" style="margin-top:0.4rem;">${teamHtml || '<em style="color:var(--muted);font-size:0.8rem">Sem time</em>'}</div>
            ${n.notes ? `<p class="npc-notes" style="font-size:0.8rem;color:var(--muted);margin-top:0.25rem;">${n.notes}</p>` : ''}
            ${n.money ? `<p style="font-size:0.8rem;color:var(--muted);">₽${n.money}</p>` : ''}
            <div class="npc-diary hidden" style="margin-top:0.4rem;padding:0.5rem;background:var(--darker,rgba(0,0,0,0.2));border-radius:6px;font-size:0.8rem;max-height:160px;overflow-y:auto;">${diaryHtml}</div>
        </div>`;
    }).join('');
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
    const rounds = {};
    t.bracket.forEach(m => {
        if (!rounds[m.round]) rounds[m.round] = [];
        rounds[m.round].push(m);
    });

    const roundNames = { 1: 'Rodada 1', 2: 'Quartas', 3: 'Semifinal', 4: 'Final' };

    let html = '<div style="display:flex;gap:2rem;overflow-x:auto;padding:1rem 0;">';

    for (const [roundNum, matches] of Object.entries(rounds).sort((a, b) => a[0] - b[0])) {
        html += `<div style="min-width:240px;">`;
        html += `<h5 style="color:var(--accent);margin-bottom:0.75rem;">${roundNames[roundNum] || 'Rodada ' + roundNum}</h5>`;

        matches.forEach(match => {
            const p1 = match.player1, p2 = match.player2;
            const p1Name = p1 ? p1.name : 'BYE';
            const p2Name = p2 ? p2.name : 'BYE';
            const isDecided  = match.winner !== null;
            const battleActive = !!match.battle_id && !isDecided;
            const p1Won = isDecided && p1 && match.winner === p1.id;
            const p2Won = isDecided && p2 && match.winner === p2.id;
            const canStart  = !isDecided && !battleActive && p1 && p2 && parseInt(roundNum) === t.current_round;
            const canForce  = !isDecided && p1 && p2 && parseInt(roundNum) === t.current_round;
            const borderCol = isDecided ? 'var(--success)' : battleActive ? 'var(--warning)' : 'var(--card-border)';

            html += `
                <div style="background:var(--darker);border:2px solid ${borderCol};border-radius:var(--radius);padding:0.5rem;margin-bottom:0.75rem;">
                    <div style="padding:0.2rem 0;${p1Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        ${p1Won ? '🏆 ' : ''}${p1Name}${p1?.is_npc ? ' 🤖' : ''}
                    </div>
                    <div style="border-top:1px solid var(--card-border);margin:0.2rem 0;font-size:0.75rem;color:var(--text-muted);text-align:center;">vs</div>
                    <div style="padding:0.2rem 0;${p2Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        ${p2Won ? '🏆 ' : ''}${p2Name}${p2?.is_npc ? ' 🤖' : ''}
                    </div>
                    ${battleActive ? `<div style="color:var(--warning);font-size:0.75rem;margin-top:0.3rem;">⚔️ Batalha em andamento...</div>` : ''}
                    ${canStart ? `
                        <button class="btn btn-sm btn-primary" onclick="startTournamentMatch('${t.id}','${match.id}')"
                            style="width:100%;margin-top:0.4rem;font-size:0.75rem;">⚔️ Iniciar Batalha</button>
                    ` : ''}
                    ${canForce && !canStart ? `
                        <div style="display:flex;gap:0.3rem;margin-top:0.4rem;">
                            <button class="btn btn-sm btn-secondary" onclick="setMatchWinner('${match.id}','${p1.id}')"
                                style="flex:1;font-size:0.7rem;" title="Forçar vitória de ${p1Name}">✓ ${p1Name}</button>
                            <button class="btn btn-sm btn-secondary" onclick="setMatchWinner('${match.id}','${p2.id}')"
                                style="flex:1;font-size:0.7rem;" title="Forçar vitória de ${p2Name}">✓ ${p2Name}</button>
                        </div>
                        <div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.2rem;text-align:center;">↑ override manual</div>
                    ` : ''}
                </div>`;
        });
        html += '</div>';
    }
    html += '</div>';

    if (t.status === 'finished') {
        html += `<div style="text-align:center;margin-top:1rem;padding:1rem;background:var(--card-bg);border:2px solid var(--accent);border-radius:var(--radius);">
            <h3 style="color:var(--accent);">🏆 Campeonato Finalizado!</h3>
            ${t.results?.first  ? `<p>🥇 1º: <strong>${t.results.first.name}</strong></p>`  : ''}
            ${t.results?.second ? `<p>🥈 2º: <strong>${t.results.second.name}</strong></p>` : ''}
            ${t.results?.third  ? `<p>🥉 3º: <strong>${t.results.third.name}</strong></p>`  : ''}
        </div>`;
    }

    container.innerHTML = html;
}

function startTournamentMatch(tourneyId, matchId) {
    socket.emit('tournament_start_match', { tournament_id: tourneyId, match_id: matchId });
}

// Update bracket when server sends an update (master side)
socket.on('tournament_bracket_update', (data) => {
    if (!window.activeTournament || window.activeTournament.id !== data.tournament_id) return;
    window.activeTournament.bracket      = data.bracket;
    window.activeTournament.status       = data.status;
    window.activeTournament.current_round = data.current_round;
    if (data.results) window.activeTournament.results = data.results;
    renderBracket();
    if (data.status === 'finished') alert('🏆 Campeonato finalizado! Prêmios distribuídos.');
});

socket.on('tournament_match_started', (data) => {
    // Match started — bracket re-render triggered by tournament_bracket_update
    console.log(`Batalha iniciada: ${data.p1_name} vs ${data.p2_name}`);
});

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


// ============================================
// MASTER EDIT PLAYER (Full access to all fields)
// ============================================
let _editingPlayerId = null;
let _editingPlayerData = null;

async function openMasterEdit(playerId, playerName) {
    _editingPlayerId = playerId;
    
    // Fetch full player data
    const resp = await fetch(`/master/players/${playerId}`);
    const playerData = await resp.json();
    _editingPlayerData = playerData;
    const trainer = playerData.trainer_data || {};
    const team = trainer.team || [];
    
    document.getElementById('master-edit-title').textContent = `✏️ Editar: ${playerName}`;
    
    const content = document.getElementById('master-edit-content');
    content.innerHTML = `
        <div style="display:grid;gap:1rem;">
            <!-- Trainer Info -->
            <div style="background:var(--darker);padding:1rem;border-radius:var(--radius);">
                <h4 style="color:var(--accent);">📋 Dados do Treinador</h4>
                <div class="form-row">
                    <div class="form-group"><label>Nome</label><input type="text" id="me-name" value="${trainer.name || ''}"></div>
                    <div class="form-group"><label>Nível</label><input type="number" id="me-level" value="${trainer.level || 1}"></div>
                    <div class="form-group"><label>XP</label><input type="number" id="me-xp" value="${trainer.xp || 0}"></div>
                    <div class="form-group"><label>XP Próx</label><input type="number" id="me-xp-next" value="${trainer.xp_to_next || 100}"></div>
                </div>
                <div class="form-row">
                    <div class="form-group"><label>❤️ Vínculo</label><input type="number" id="me-vinculo" value="${trainer.vinculo ?? trainer.wis ?? 10}"></div>
                    <div class="form-group"><label>♟️ Tática</label><input type="number" id="me-tatica" value="${trainer.tatica ?? trainer.str ?? 10}"></div>
                    <div class="form-group"><label>📖 Conhecimento</label><input type="number" id="me-conhecimento" value="${trainer.conhecimento ?? trainer.int ?? 10}"></div>
                    <div class="form-group"><label>🏃 Agilidade</label><input type="number" id="me-agilidade" value="${trainer.agilidade ?? trainer.dex ?? 10}"></div>
                    <div class="form-group"><label>👑 Influência</label><input type="number" id="me-influencia" value="${trainer.influencia ?? trainer.cha ?? 10}"></div>
                    <div class="form-group"><label>🔥 Determinação</label><input type="number" id="me-determinacao" value="${trainer.determinacao ?? trainer.con ?? 10}"></div>
                </div>
                <div class="form-row">
                    <div class="form-group"><label>HP Máx</label><input type="number" id="me-hp-max" value="${trainer.hp_max || 8}"></div>
                    <div class="form-group"><label>HP Atual</label><input type="number" id="me-hp-current" value="${trainer.hp_current || 8}"></div>
                    <div class="form-group"><label>₽ Dinheiro</label><input type="number" id="me-money" value="${trainer.money || 0}"></div>
                    <div class="form-group"><label>Pokéslots</label><input type="number" id="me-pokeslots" value="${trainer.pokeslots || 3}"></div>
                </div>
                <button class="btn btn-primary" onclick="saveMasterEditTrainer()">💾 Salvar Treinador</button>
            </div>
            
            <!-- Pokemon Team -->
            <div style="background:var(--darker);padding:1rem;border-radius:var(--radius);">
                <h4 style="color:var(--accent);">🔴 Time Pokémon (${team.length})</h4>
                <div id="me-team-list">
                    ${team.map((p, i) => `
                        <div style="background:var(--card-bg);padding:0.75rem;border-radius:var(--radius);margin-bottom:0.5rem;border:1px solid var(--card-border);">
                            <div class="form-row">
                                <div class="form-group"><label>Nome</label><input type="text" id="me-poke-${i}-name" value="${p.name || ''}"></div>
                                <div class="form-group"><label>Apelido</label><input type="text" id="me-poke-${i}-nick" value="${p.nickname || ''}"></div>
                                <div class="form-group"><label>Nível</label><input type="number" id="me-poke-${i}-level" value="${p.level || 1}"></div>
                            </div>
                            <div class="form-row">
                                <div class="form-group"><label>HP Atual</label><input type="number" id="me-poke-${i}-hp" value="${p.currentHp || 0}"></div>
                                <div class="form-group"><label>HP Máx</label><input type="number" id="me-poke-${i}-maxhp" value="${p.maxHp || 0}"></div>
                            </div>
                            <div class="form-row">
                                <div class="form-group"><label>ATK</label><input type="number" id="me-poke-${i}-atk" value="${p.stats?.ATK || p.stats?.STR || 10}"></div>
                                <div class="form-group"><label>DEF</label><input type="number" id="me-poke-${i}-def" value="${p.stats?.DEF || p.stats?.DEX || 10}"></div>
                                <div class="form-group"><label>SPA</label><input type="number" id="me-poke-${i}-spa" value="${p.stats?.SPA || p.stats?.CON || 10}"></div>
                                <div class="form-group"><label>SPD</label><input type="number" id="me-poke-${i}-spd" value="${p.stats?.SPD || p.stats?.INT || 10}"></div>
                                <div class="form-group"><label>SPE</label><input type="number" id="me-poke-${i}-spe" value="${p.stats?.SPE || p.stats?.WIS || 10}"></div>
                                <div class="form-group"><label>HP Stat</label><input type="number" id="me-poke-${i}-hpstat" value="${p.stats?.HP || p.stats?.CHA || 10}"></div>
                            </div>
                            <div class="form-row">
                                <div class="form-group"><label>XP Total</label><input type="number" id="me-poke-${i}-xp" value="${p.totalXp || 0}"></div>
                                <div class="form-group"><label>Pontos Disp.</label><input type="number" id="me-poke-${i}-points" value="${p.statPointsAvailable || 0}"></div>
                            </div>
                        </div>
                    `).join('')}
                </div>
                <button class="btn btn-primary" onclick="saveMasterEditTeam()">💾 Salvar Time</button>
            </div>
        </div>
    `;
    
    showElement('master-edit-modal');
}

async function saveMasterEditTrainer() {
    const data = {
        name: document.getElementById('me-name').value,
        level: parseInt(document.getElementById('me-level').value) || 1,
        xp: parseInt(document.getElementById('me-xp').value) || 0,
        xp_to_next: parseInt(document.getElementById('me-xp-next').value) || 100,
        vinculo: parseInt(document.getElementById('me-vinculo').value) || 10,
        tatica: parseInt(document.getElementById('me-tatica').value) || 10,
        conhecimento: parseInt(document.getElementById('me-conhecimento').value) || 10,
        agilidade: parseInt(document.getElementById('me-agilidade').value) || 10,
        influencia: parseInt(document.getElementById('me-influencia').value) || 10,
        determinacao: parseInt(document.getElementById('me-determinacao').value) || 10,
        hp_max: parseInt(document.getElementById('me-hp-max').value) || 8,
        hp_current: parseInt(document.getElementById('me-hp-current').value) || 8,
        money: parseInt(document.getElementById('me-money').value) || 0,
        pokeslots: parseInt(document.getElementById('me-pokeslots').value) || 3
    };
    
    const resp = await fetch(`/master/players/${_editingPlayerId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    const result = await resp.json();
    if (result.success) {
        alert('✅ Treinador atualizado!');
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

async function masterResetPassword(playerId, playerName) {
    const newPass = prompt(`Nova senha para ${playerName}:`);
    if (!newPass || newPass.trim().length < 4) {
        if (newPass !== null) alert('Senha deve ter pelo menos 4 caracteres.');
        return;
    }
    const resp = await fetch(`/master/players/${playerId}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: newPass.trim() })
    });
    const result = await resp.json();
    if (result.success) {
        alert(`✅ Senha de ${result.username} redefinida!`);
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

async function deletePlayerAccount(playerId, playerName) {
    if (!confirm(`⚠️ DELETAR a conta de ${playerName}?\n\nIsso apaga PERMANENTEMENTE o treinador, o time, o PC e todo o progresso. NÃO tem como desfazer.`)) return;
    const typed = prompt(`Para confirmar, digite o nome de usuário exatamente: ${playerName}`);
    if (typed === null) return;
    if (typed.trim() !== playerName) { alert('❌ Nome não confere — exclusão cancelada.'); return; }
    const resp = await fetch(`/master/players/${playerId}/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_username: playerName })
    });
    const result = await resp.json();
    if (result.success) {
        alert(`🗑️ Conta de ${result.username} deletada.`);
        // fecha o modal de edição se estava aberto neste jogador
        if (typeof _editingPlayerId !== 'undefined' && _editingPlayerId === playerId) {
            document.getElementById('master-edit-modal')?.classList.add('hidden');
        }
        // remove as linhas do jogador das listas
        document.querySelectorAll('#mesa-players-list > div, #players-list > div').forEach(row => {
            if (row.querySelector('button')?.getAttribute('onclick')?.includes(playerId)) row.remove();
        });
        if (typeof loadPlayers === 'function') loadPlayers();
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

async function saveMasterEditTeam() {
    const team = _editingPlayerData.trainer_data.team || [];
    
    for (let i = 0; i < team.length; i++) {
        team[i].name = document.getElementById(`me-poke-${i}-name`).value;
        team[i].nickname = document.getElementById(`me-poke-${i}-nick`).value;
        team[i].level = parseInt(document.getElementById(`me-poke-${i}-level`).value) || 1;
        team[i].currentHp = parseInt(document.getElementById(`me-poke-${i}-hp`).value) || 0;
        team[i].maxHp = parseInt(document.getElementById(`me-poke-${i}-maxhp`).value) || 0;
        team[i].totalXp = parseInt(document.getElementById(`me-poke-${i}-xp`).value) || 0;
        team[i].statPointsAvailable = parseInt(document.getElementById(`me-poke-${i}-points`).value) || 0;
        team[i].stats = {
            ATK: parseInt(document.getElementById(`me-poke-${i}-atk`).value) || 10,
            DEF: parseInt(document.getElementById(`me-poke-${i}-def`).value) || 10,
            SPA: parseInt(document.getElementById(`me-poke-${i}-spa`).value) || 10,
            SPD: parseInt(document.getElementById(`me-poke-${i}-spd`).value) || 10,
            SPE: parseInt(document.getElementById(`me-poke-${i}-spe`).value) || 10,
            HP: parseInt(document.getElementById(`me-poke-${i}-hpstat`).value) || 10
        };
    }
    
    const resp = await fetch(`/master/players/${_editingPlayerId}/team`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team })
    });
    const result = await resp.json();
    if (result.success) {
        alert('✅ Time atualizado!');
    } else {
        alert('❌ Erro: ' + (result.error || 'Falha'));
    }
}

// ============================================================
// PVP MONITOR — MASTER
// ============================================================

const masterActivePvp = {};  // battle_id → last known state

socket.on('pvp_master_update', (data) => {
    masterActivePvp[data.battle_id] = data;
    renderMasterPvpBattles();
});

function renderMasterPvpBattles() {
    const el = document.getElementById('master-pvp-battles');
    if (!el) return;
    const battles = Object.values(masterActivePvp);
    const alive = battles.filter(b => b.event !== 'battle_ended');
    if (!alive.length) {
        el.innerHTML = '<em style="color:var(--muted)">Nenhuma batalha PVP ativa no momento.</em>';
        return;
    }
    el.innerHTML = alive.map(b => {
        const phaseLabel = { selection:'Seleção', battle:'Em Batalha', finished:'Finalizada' }[b.phase] || b.phase;
        const modeLabel  = { official:'Oficial', street:'Rua', tournament:'Torneio' }[b.mode] || b.mode;
        const gymInfo    = b.extra?.gym_id   ? `<span style="color:#ff9800">🏟️ Ginásio</span>` : '';
        const leagueInfo = b.extra?.league_slot != null ? `<span style="color:#9c27b0">🌟 Liga — ${b.extra.slot_title||''}</span>` : '';
        const turnName   = b.turn === 'player1' ? b.p1_name : b.p2_name;
        const turnIsNpc  = b.turn === 'player1' ? b.p1_is_npc : b.p2_is_npc;
        const turnLabel  = b.turn
            ? `<span style="color:${b.turn==='player1'?'#4caf50':'#f44336'}">Vez: ${turnName}${turnIsNpc?' 🤖':''}</span>`
            : '';
        const forceBtn = (b.phase === 'battle' && b.turn)
            ? `<button style="background:#ff9800;color:#000;border:none;padding:0.2rem 0.6rem;border-radius:4px;cursor:pointer;font-size:0.8rem;"
                  onclick="masterForceAction('${b.battle_id}','${b.turn}')">⚡ Forçar Ação</button>`
            : '';
        // Button to force NPC pokemon selection when stuck in selection phase
        const p1NeedsSelect = b.phase === 'selection' && b.p1_is_npc && b.p1_pokemon === '?';
        const p2NeedsSelect = b.phase === 'selection' && b.p2_is_npc && b.p2_pokemon === '?';
        const forceSelectBtn = (p1NeedsSelect || p2NeedsSelect)
            ? `<button style="background:#2196f3;color:#fff;border:none;padding:0.2rem 0.6rem;border-radius:4px;cursor:pointer;font-size:0.8rem;"
                  onclick="masterForceNpcSelect('${b.battle_id}','${p1NeedsSelect ? 'player1' : 'player2'}')">🎯 Forçar Seleção NPC</button>`
            : '';
        const p1HpColor = b.p1_hp <= 0 ? '#f44336' : (b.p1_hp < b.p1_maxhp * 0.3 ? '#ff9800' : '#4caf50');
        const p2HpColor = b.p2_hp <= 0 ? '#f44336' : (b.p2_hp < b.p2_maxhp * 0.3 ? '#ff9800' : '#4caf50');
        return `
        <div style="padding:0.75rem;background:var(--darker);border-radius:var(--radius);border-left:3px solid var(--accent);margin-bottom:0.5rem;">
            <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
                <strong>${b.p1_name}${b.p1_is_npc?' 🤖':''}</strong>
                <span style="color:var(--muted)">vs</span>
                <strong>${b.p2_name}${b.p2_is_npc?' 🤖':''}</strong>
                <span style="font-size:0.8rem;color:var(--muted)">[${modeLabel}]</span>
                ${gymInfo}${leagueInfo}
            </div>
            <div style="font-size:0.85rem;margin-top:0.4rem;display:flex;gap:1rem;flex-wrap:wrap;align-items:center;">
                <span>${b.p1_pokemon} — <span style="color:${p1HpColor}">HP: ${Math.max(0,b.p1_hp)}/${b.p1_maxhp}</span></span>
                <span>${b.p2_pokemon} — <span style="color:${p2HpColor}">HP: ${Math.max(0,b.p2_hp)}/${b.p2_maxhp}</span></span>
                <span>Round ${b.round || 0} • ${phaseLabel}</span>
                ${turnLabel}
                ${b.winner ? `<span style="color:#ffd700">🏆 Vencedor: ${b.winner==='player1'?b.p1_name:b.p2_name}</span>` : ''}
                ${forceBtn}
                ${forceSelectBtn}
            </div>
        </div>`;
    }).join('');
}

function masterSendNpcChallenge() {
    const npcId    = document.getElementById('master-pvp-npc')?.value;
    const targetId = document.getElementById('master-pvp-target')?.value;
    const mode     = document.getElementById('master-pvp-mode')?.value || 'official';
    if (!npcId || !targetId) { alert('Selecione NPC e jogador alvo.'); return; }
    socket.emit('master_pvp_challenge', { npc_id: npcId, target_id: targetId, mode });
}

socket.on('master_pvp_created', (data) => {
    const msg = document.getElementById('master-pvp-msg');
    if (msg) {
        msg.textContent = `✅ Batalha criada: ${data.npc} vs ${data.target}`;
        msg.style.color = '#4caf50';
        setTimeout(() => msg.textContent = '', 4000);
    }
});

socket.on('master_error', (data) => {
    alert('❌ ' + (data.msg || 'Erro'));
});

function masterForceAction(battleId, playerKey) {
    socket.emit('master_force_npc_action', { battle_id: battleId, player_key: playerKey });
}

function masterForceNpcSelect(battleId, playerKey) {
    socket.emit('master_force_npc_select', { battle_id: battleId, player_key: playerKey });
}

socket.on('master_force_npc_result', (data) => {
    showNotification(data.message || 'Ação forçada!', 'success');
});

socket.on('pvp_master_permadeath', (data) => {
    showNotification(`💀 MORTE PERMANENTE: ${data.pokemon} (jogador ${data.player_id}) foi removido do time!`, 'error');
    renderMasterPvpBattles();
});

// Load PVP tab on open
document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="pvp-master"]')?.addEventListener('click', renderMasterPvpBattles);
});

// ============================================================
// GYMS & LEAGUE — MASTER
// ============================================================

let masterGyms = [];
let leagueSlots = [];

async function loadMasterGyms() {
    try {
        const res = await fetch('/api/gyms');
        masterGyms = await res.json();
        renderMasterGyms();
    } catch(e) { console.error('loadMasterGyms', e); }
}

async function loadMasterLeague() {
    try {
        const res = await fetch('/api/league');
        const data = await res.json();
        leagueSlots = data.slots || [];
        renderLeagueEditor();
    } catch(e) { console.error('loadMasterLeague', e); }
}

function renderMasterGyms() {
    const el = document.getElementById('master-gyms-list');
    if (!el) return;
    if (!masterGyms.length) {
        el.innerHTML = '<em style="color:var(--muted)">Nenhum ginásio cadastrado.</em>';
        return;
    }
    const sorted = [...masterGyms].sort((a, b) => (a.order || 0) - (b.order || 0));
    el.innerHTML = sorted.map(gym => `
        <div style="display:flex;align-items:center;gap:1rem;padding:0.75rem;background:var(--darker);border-radius:var(--radius);">
            <span style="font-size:2rem">${gym.badge_icon || '🏅'}</span>
            <div style="flex:1">
                <div style="font-weight:bold">${gym.name}</div>
                <div style="font-size:0.85rem;color:var(--muted)">
                    Líder: ${gym.leader_name} • Tipo: ${gym.type} • Insígnia: ${gym.badge_name}
                    ${gym.required_badges?.length ? ` • Requer: ${gym.required_badges.join(', ')}` : ''}
                </div>
            </div>
            <button class="btn btn-sm btn-danger" onclick="deleteGym('${gym.id}')">🗑️ Remover</button>
        </div>
    `).join('');
}

async function createGym() {
    const name        = document.getElementById('gym-name')?.value.trim();
    const badge_name  = document.getElementById('gym-badge-name')?.value.trim();
    const badge_icon  = document.getElementById('gym-badge-icon')?.value.trim() || '🏅';
    const type        = document.getElementById('gym-type')?.value.trim();
    const leader_name = document.getElementById('gym-leader-name')?.value.trim();
    const npc_id      = document.getElementById('gym-leader-npc')?.value || null;
    const player_id   = document.getElementById('gym-leader-player')?.value || null;
    const level_cap   = parseInt(document.getElementById('gym-level-cap')?.value) || 5;
    const req_raw     = document.getElementById('gym-required-badges')?.value.trim();
    const description = document.getElementById('gym-description')?.value.trim();

    if (!name || !badge_name || !type || !leader_name) {
        alert('Preencha: Nome, Insígnia, Tipo e Nome do Líder.');
        return;
    }
    const required_badges = req_raw ? req_raw.split(',').map(s => s.trim()).filter(Boolean) : [];

    const res = await fetch('/api/gyms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, badge_name, badge_icon, type, leader_name,
            leader_npc_id: npc_id || undefined,
            leader_player_id: player_id || undefined,
            required_badges, level_cap, description })
    });
    if (res.ok) {
        // clear form
        ['gym-name','gym-badge-name','gym-type','gym-leader-name','gym-required-badges','gym-description']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        document.getElementById('gym-badge-icon').value = '🏅';
        document.getElementById('gym-level-cap').value = '5';
    } else {
        const err = await res.json();
        alert('Erro: ' + (err.error || 'Falha ao criar ginásio'));
    }
}

async function deleteGym(gymId) {
    if (!confirm('Remover este ginásio?')) return;
    await fetch(`/api/gyms/${gymId}`, { method: 'DELETE' });
}

// League editor
function renderLeagueEditor() {
    const el = document.getElementById('league-slots-editor');
    if (!el) return;
    el.innerHTML = leagueSlots.map((s, i) => `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:0.5rem;align-items:end;padding:0.5rem;background:var(--darker);border-radius:var(--radius);">
            <div>
                <label style="font-size:0.8rem">Título</label>
                <input type="text" class="form-input" id="league-slot-title-${i}" value="${s.title || ''}" placeholder="ex: Elite 1">
            </div>
            <div>
                <label style="font-size:0.8rem">Nome do Líder</label>
                <input type="text" class="form-input" id="league-slot-leader-${i}" value="${s.leader_name || ''}" placeholder="ex: Lorelei">
            </div>
            <div>
                <label style="font-size:0.8rem">NPC</label>
                <select class="form-input" id="league-slot-npc-${i}">
                    <option value="">— Sem NPC —</option>
                    ${window.ALL_NPCS ? window.ALL_NPCS.map(n => `<option value="${n.id}" ${s.leader_npc_id===n.id?'selected':''}>${n.name}</option>`).join('') : ''}
                </select>
            </div>
            <div style="display:flex;gap:0.25rem;align-items:center;padding-top:1.25rem;">
                <label style="font-size:0.75rem;white-space:nowrap">
                    <input type="checkbox" id="league-slot-champion-${i}" ${s.is_champion?'checked':''}>
                    Campeão
                </label>
                <button class="btn btn-sm btn-danger" onclick="removeLeagueSlot(${i})">✕</button>
            </div>
        </div>
    `).join('');
}

function addLeagueSlot() {
    leagueSlots.push({ title: `Elite ${leagueSlots.length + 1}`, leader_name: '', leader_npc_id: null, is_champion: false });
    renderLeagueEditor();
}

function removeLeagueSlot(i) {
    leagueSlots.splice(i, 1);
    renderLeagueEditor();
}

async function saveLeagueSlots() {
    // Read current form values
    leagueSlots = leagueSlots.map((_, i) => ({
        title:          document.getElementById(`league-slot-title-${i}`)?.value.trim() || `Membro ${i+1}`,
        leader_name:    document.getElementById(`league-slot-leader-${i}`)?.value.trim() || '',
        leader_npc_id:  document.getElementById(`league-slot-npc-${i}`)?.value || null,
        is_champion:    document.getElementById(`league-slot-champion-${i}`)?.checked || false
    }));

    const res = await fetch('/api/league/slots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slots: leagueSlots })
    });
    if (res.ok) {
        const msg = document.getElementById('league-save-msg');
        if (msg) { msg.style.display = 'block'; setTimeout(() => msg.style.display = 'none', 2500); }
    }
}

// Populate NPC select in gym form when NPCs load
socket.on('npcs_update', data => {
    window.ALL_NPCS = data.npcs || [];
    const sel = document.getElementById('gym-leader-npc');
    if (sel) {
        sel.innerHTML = '<option value="">— Sem NPC —</option>' +
            window.ALL_NPCS.map(n => `<option value="${n.id}">${n.name}</option>`).join('');
    }
});

socket.on('gyms_updated', data => {
    masterGyms = data.gyms || [];
    renderMasterGyms();
});

socket.on('league_updated', data => {
    leagueSlots = data.slots || [];
    renderLeagueEditor();
});

socket.on('badge_awarded', data => {
    console.log(`[Liga] ${data.player || 'Jogador'} conquistou: ${data.badge} (${data.gym})`);
});

socket.on('league_completed', data => {
    alert(`🏆 ${data.player_name} se tornou Campeão da Liga Pokémon!`);
});

// Load when tab opened
document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="gyms"]')?.addEventListener('click', () => {
        loadMasterGyms();
        loadMasterLeague();
    });
    document.querySelector('[data-tab="pokedex"]')?.addEventListener('click', loadMasterPokedex);
});

// ============================================
// MAP PICKER
// ============================================
let _allMaps = [];

async function loadMapList() {
    if (_allMaps.length) return;
    const res = await fetch('/api/maps');
    _allMaps = await res.json();
    renderMapGrid(_allMaps);
}

function renderMapGrid(maps) {
    const grid = document.getElementById('map-grid');
    if (!grid) return;
    grid.innerHTML = maps.map(m => `
        <div onclick="selectMap('${m.id}','${m.file}','${m.name.replace(/'/g, "\\'")}')"
             style="cursor:pointer;border:2px solid var(--border);border-radius:8px;overflow:hidden;transition:border-color .15s;"
             onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
            <img src="/static/maps/${m.file}" alt="${m.name}"
                 style="width:100%;height:90px;object-fit:cover;display:block;"
                 onerror="this.style.display='none'">
            <div style="padding:4px 6px;font-size:0.72rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${m.name}</div>
        </div>`).join('');
}

function filterMaps(q) {
    const filtered = q ? _allMaps.filter(m => m.name.toLowerCase().includes(q.toLowerCase())) : _allMaps;
    renderMapGrid(filtered);
}

function toggleMapPicker() {
    const picker = document.getElementById('map-picker');
    const visible = picker.style.display !== 'none';
    picker.style.display = visible ? 'none' : '';
    if (!visible) loadMapList();
}

async function selectMap(id, file, name) {
    await fetch('/master/table/set-map', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({map_id: id, map_file: file, map_name: name})
    });
    document.getElementById('active-map-img').src = `/static/maps/${file}`;
    document.getElementById('map-name-badge').textContent = name;
    document.getElementById('map-tab-title').textContent = `🗺️ ${name}`;
    document.getElementById('map-picker').style.display = 'none';
    showNotification(`🗺️ Mapa alterado: ${name}`, 'success');
}

socket.on('map_changed', data => {
    // Update map in master view too if needed (already handled above)
    console.log('[Mapa] Alterado para:', data.map_name);
});

// ============================================
// MESA (table management)
// ============================================
function copyInviteCode() {
    const code = document.getElementById('invite-code-display')?.textContent?.trim();
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
        showNotification('📋 Código copiado!', 'success');
    });
}

async function regenerateInvite() {
    if (!confirm('Gerar um novo código? O código atual vai parar de funcionar para novos registros.')) return;
    const res = await fetch('/master/table/new-invite', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        document.getElementById('invite-code-display').textContent = data.invite_code;
        showNotification(`🔑 Novo código: ${data.invite_code}`, 'success');
    }
}

async function renameMesa() {
    const name = document.getElementById('mesa-name-input')?.value?.trim();
    if (!name) return;
    const res = await fetch('/master/table/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (data.ok) showNotification(`✅ Mesa renomeada para "${data.name}"`, 'success');
}

// Transfer requests
async function loadPendingTransfers() {
    const res = await fetch('/master/table/pending-transfers');
    const list = await res.json();
    renderPendingTransfers(list);
}

function renderPendingTransfers(list) {
    const el = document.getElementById('pending-transfers-list');
    if (!el) return;
    if (!list.length) {
        el.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Nenhuma solicitação pendente.</p>';
        return;
    }
    el.innerHTML = list.map(r => `
        <div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem;padding:0.6rem;background:rgba(255,255,255,0.05);border-radius:8px;margin-bottom:0.4rem;">
            <span style="flex:1;font-size:0.9rem;">👤 <strong>${r.username}</strong> quer entrar nesta mesa</span>
            <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                <button class="btn btn-sm btn-success" onclick="approveTransfer('${r.request_id}',true,true)">✅ Aceitar (manter progresso)</button>
                <button class="btn btn-sm btn-warning" onclick="approveTransfer('${r.request_id}',true,false)">🆕 Aceitar (reset)</button>
                <button class="btn btn-sm btn-danger" onclick="approveTransfer('${r.request_id}',false,false)">❌ Recusar</button>
            </div>
        </div>`).join('');
}

async function approveTransfer(requestId, approved, keepProgress) {
    const res = await fetch('/master/table/approve-transfer', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({request_id: requestId, approved, keep_progress: keepProgress})
    });
    const data = await res.json();
    if (data.ok) {
        showNotification(approved
            ? `✅ Transferência ${keepProgress ? 'aprovada (progresso mantido)' : 'aprovada (reset)'}`
            : '❌ Transferência recusada', approved ? 'success' : 'warning');
        loadPendingTransfers();
    }
}

// Socket: incoming transfer request
socket.on('transfer_request', req => {
    showNotification(`🔀 ${req.username} quer entrar nesta mesa!`, 'warning');
    loadPendingTransfers();
});

// Load pending transfers when mesa tab opens
document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="mesa"]')?.addEventListener('click', loadPendingTransfers);
    document.querySelector('[data-tab="map"]')?.addEventListener('click', () => {});
});

async function kickPlayer(playerId, playerName) {
    if (!confirm(`Remover ${playerName} desta mesa? O jogador não poderá mais acessar até se registrar novamente com um código válido.`)) return;
    const res = await fetch(`/master/table/kick/${playerId}`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        // Remove from UI
        const rows = document.querySelectorAll('#mesa-players-list > div');
        rows.forEach(row => {
            if (row.querySelector('button')?.getAttribute('onclick')?.includes(playerId)) {
                row.remove();
            }
        });
        showNotification(`✅ ${playerName} removido da mesa.`, 'success');
    } else {
        showNotification(`❌ ${data.error || 'Erro'}`, 'error');
    }
}

// ============================================
// CALENDÁRIO DO JOGO (mestre)
// ============================================
function _calDateLabel(cal) {
    return `Dia ${cal.day}, Mês ${cal.month}, Ano ${cal.year}`;
}

async function loadCalendar() {
    try {
        const resp = await fetch('/api/calendar');
        const data = await resp.json();
        renderCalendar(data);
    } catch(e) {}
}

function renderCalendar(data) {
    const dateEl = document.getElementById('cal-date');
    if (dateEl && data.calendar) dateEl.textContent = _calDateLabel(data.calendar);
    const list = document.getElementById('calendar-events-list');
    if (!list) return;
    const events = data.events || [];
    if (!events.length) {
        list.innerHTML = '<p class="empty-state">Nenhum evento criado.</p>';
        return;
    }
    list.innerHTML = events.map(renderCalendarEventCard).join('');
}

function renderCalendarEventCard(evt) {
    const du = evt.days_until;
    let badge, style = '';
    if (du === 0) badge = '<span style="background:#e53935;color:#fff;padding:0.1rem 0.5rem;border-radius:10px;font-size:0.75rem;">🔴 HOJE!</span>';
    else if (du > 0) badge = `<span style="background:#1976d2;color:#fff;padding:0.1rem 0.5rem;border-radius:10px;font-size:0.75rem;">⏳ faltam ${du} dia(s)</span>`;
    else { badge = '<span style="background:#616161;color:#fff;padding:0.1rem 0.5rem;border-radius:10px;font-size:0.75rem;">✔ ocorrido</span>'; style = 'opacity:0.55;'; }
    return `
    <div class="quest-card" id="evt-${evt.id}" style="${style}margin-bottom:0.5rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
            <strong>📅 ${evt.title}</strong> ${badge}
            <span style="color:var(--muted);font-size:0.85rem;">${evt.city ? '📍 ' + evt.city + ' · ' : ''}Dia ${evt.day}/Mês ${evt.month}/Ano ${evt.year}</span>
            <div style="margin-left:auto;display:flex;gap:0.4rem;">
                <button class="btn btn-sm btn-secondary" onclick='editCalendarEvent(${JSON.stringify(evt).replace(/'/g, "&#39;")})'>✏️</button>
                <button class="btn btn-sm btn-danger" onclick="deleteCalendarEvent('${evt.id}')">🗑️</button>
            </div>
        </div>
        ${evt.description ? `<p style="font-size:0.85rem;margin:0.3rem 0 0;">${evt.description}</p>` : ''}
    </div>`;
}

async function advanceCalendar(days) {
    const resp = await fetch('/master/calendar/advance', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ days })
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    const log = document.getElementById('cal-advance-log');
    if (log) {
        let html = `<p>☀️ Avançou ${days} dia(s) → <strong>${_calDateLabel(data.calendar)}</strong>. Caçadas resetadas.</p>`;
        (data.npc_log || []).forEach(e => { html += `<p>🧑‍🤝‍🧑 <strong>${e.name}</strong> [${e.day_key || ''}]: ${e.message}</p>`; });
        (data.events_triggered || []).forEach(e => { html += `<p>🔴 Evento HOJE: <strong>${e.title}</strong> ${e.city ? 'em ' + e.city : ''}</p>`; });
        log.innerHTML = html + log.innerHTML;
    }
    loadCalendar();
    loadNpcs();
}

function advanceCalendarN() {
    const n = parseInt(document.getElementById('cal-advance-days')?.value) || 1;
    advanceCalendar(Math.max(1, Math.min(30, n)));
}

async function setCalendarDate() {
    const payload = {
        day:   parseInt(document.getElementById('cal-set-day')?.value) || 1,
        month: parseInt(document.getElementById('cal-set-month')?.value) || 1,
        year:  parseInt(document.getElementById('cal-set-year')?.value) || 1
    };
    const resp = await fetch('/master/calendar/set', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    loadCalendar();
}

async function createCalendarEvent() {
    const editId = document.getElementById('evt-edit-id')?.value || '';
    const payload = {
        title: document.getElementById('evt-title').value.trim(),
        city:  document.getElementById('evt-city').value.trim(),
        description: document.getElementById('evt-desc').value.trim(),
        day:   parseInt(document.getElementById('evt-day').value) || 1,
        month: parseInt(document.getElementById('evt-month').value) || 1,
        year:  parseInt(document.getElementById('evt-year').value) || 1,
        notify_days_before: parseInt(document.getElementById('evt-notify').value) || 3
    };
    if (!payload.title) { alert('Título obrigatório!'); return; }
    const url = editId ? `/master/calendar/events/${editId}` : '/master/calendar/events';
    const resp = await fetch(url, {
        method: editId ? 'PUT' : 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    clearEventForm();
    loadCalendar();
}

function editCalendarEvent(evt) {
    document.getElementById('evt-edit-id').value = evt.id;
    document.getElementById('evt-title').value = evt.title || '';
    document.getElementById('evt-city').value = evt.city || '';
    document.getElementById('evt-desc').value = evt.description || '';
    document.getElementById('evt-day').value = evt.day || 1;
    document.getElementById('evt-month').value = evt.month || 1;
    document.getElementById('evt-year').value = evt.year || 1;
    document.getElementById('evt-notify').value = evt.notify_days_before ?? 3;
    document.getElementById('evt-save-btn').textContent = '💾 Salvar Evento';
    document.getElementById('evt-cancel-btn')?.classList.remove('hidden');
    document.getElementById('evt-title').scrollIntoView({ behavior: 'smooth' });
}

function clearEventForm() {
    document.getElementById('evt-edit-id').value = '';
    ['evt-title','evt-city','evt-desc'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('evt-day').value = 1;
    document.getElementById('evt-month').value = 1;
    document.getElementById('evt-year').value = 1;
    document.getElementById('evt-notify').value = 3;
    document.getElementById('evt-save-btn').textContent = '📅 Criar Evento';
    document.getElementById('evt-cancel-btn')?.classList.add('hidden');
}

async function deleteCalendarEvent(id) {
    if (!confirm('Deletar este evento?')) return;
    await fetch(`/master/calendar/events/${id}`, { method: 'DELETE' });
    document.getElementById(`evt-${id}`)?.remove();
}

async function masterHunts(action) {
    const playerId = document.getElementById('hunt-player')?.value;
    if (!playerId) { alert('Selecione um jogador'); return; }
    const resp = await fetch('/master/hunts', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ player_id: playerId, action, amount: 1 })
    });
    const data = await resp.json();
    const out = document.getElementById('hunt-master-result');
    if (out) out.textContent = data.error ? `❌ ${data.error}`
        : `✅ ${action === 'grant' ? 'Caçada extra concedida' : 'Contador resetado'} — agora ${data.used}/${data.limit}.`;
}

socket.on('calendar_update', (data) => renderCalendar(data));
socket.on('npc_diary_update', (data) => {
    const log = document.getElementById('cal-advance-log');
    if (log && data.npc_log) {
        data.npc_log.forEach(e => log.insertAdjacentHTML('afterbegin',
            `<p>🧑‍🤝‍🧑 <strong>${e.name}</strong>: ${e.message}</p>`));
    }
    loadNpcs();
});

document.addEventListener('DOMContentLoaded', loadCalendar);
