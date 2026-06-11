/* ============================================
   POKEMON 5E RPG - PLAYER JS (UPDATED)
   ============================================ */

let currentEncounter = null;
let playerTeam = TRAINER_DATA.team || [];
let battleActive = false;

// Nature modifiers: +10% boosted stat, -10% lowered stat
const NATURE_MODIFIERS = {
    Adamant:{ATK:1.1,SPA:0.9}, Modest:{SPA:1.1,ATK:0.9}, Jolly:{SPE:1.1,SPA:0.9},
    Timid:{SPE:1.1,ATK:0.9},  Bold:{DEF:1.1,ATK:0.9},   Impish:{DEF:1.1,SPA:0.9},
    Calm:{SPD:1.1,ATK:0.9},   Careful:{SPD:1.1,SPA:0.9}, Brave:{ATK:1.1,SPE:0.9},
    Quiet:{SPA:1.1,SPE:0.9},  Relaxed:{DEF:1.1,SPE:0.9}, Sassy:{SPD:1.1,SPE:0.9},
    Lonely:{ATK:1.1,DEF:0.9}, Naughty:{ATK:1.1,SPD:0.9}, Mild:{SPA:1.1,DEF:0.9},
    Rash:{SPA:1.1,SPD:0.9},   Lax:{DEF:1.1,SPD:0.9},     Gentle:{SPD:1.1,DEF:0.9},
    Hasty:{SPE:1.1,DEF:0.9},  Naive:{SPE:1.1,SPD:0.9}
};

function applyNatureToStats(stats, nature) {
    if (!nature || !NATURE_MODIFIERS[nature]) return stats;
    const result = {...stats};
    for (const [stat, mult] of Object.entries(NATURE_MODIFIERS[nature])) {
        if (result[stat] != null) result[stat] = Math.round(result[stat] * mult);
    }
    return result;
}

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
    // Show evolution animations sequentially then refresh team
    if (data.evolutions && data.evolutions.length > 0) {
        (async () => {
            for (const evo of data.evolutions) {
                await triggerEvolutionSequence(evo);
            }
            // Reload team from server to reflect evolved data
            fetch('/player/team-data').then(r => r.json()).then(team => {
                if (team && !team.error) {
                    playerTeam = team;
                    TRAINER_DATA.team = team;
                    if (typeof renderTeam === 'function') renderTeam();
                }
            }).catch(() => {});
        })();
    }
});

function renderPlayerQuestCard(quest) {
    const catIcon = quest.category === 'urgent' ? '🔥' : quest.category === 'side' ? '📌' : '⭐';
    const objDone = (quest.objectives || []).filter(o => o.done).length;
    const objTotal = (quest.objectives || []).length;
    const pct = objTotal ? Math.round(objDone / objTotal * 100) : 0;
    const objHtml = objTotal ? `
        <div style="margin:0.5rem 0;">
            <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:var(--muted);margin-bottom:2px;">
                <span>Progresso</span><span>${objDone}/${objTotal}</span>
            </div>
            <div style="height:6px;background:var(--border);border-radius:4px;">
                <div id="progress-bar-${quest.id}" style="width:${pct}%;height:100%;background:var(--success);border-radius:4px;transition:width 0.3s;"></div>
            </div>
            <div style="margin-top:0.4rem;">
                ${(quest.objectives || []).map((o, i) => `
                    <label id="obj-label-${quest.id}-${i}" style="display:flex;align-items:center;gap:0.4rem;font-size:0.9rem;cursor:pointer;margin-bottom:0.2rem;${o.done ? 'opacity:0.5;text-decoration:line-through;' : ''}">
                        <input type="checkbox" ${o.done ? 'checked' : ''} onchange="playerToggleObjective('${quest.id}', ${i}, this)">
                        ${o.text}
                    </label>`).join('')}
            </div>
        </div>` : '';
    return `<div class="quest-card" id="player-quest-${quest.id}" data-quest-id="${quest.id}">
        <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.3rem;">
            <span class="quest-category-badge cat-${quest.category||'main'}">${catIcon}</span>
            <h4 style="margin:0;flex:1;">${quest.title}</h4>
            <span class="quest-city">📍 ${quest.city||''}</span>
            ${quest.xp_reward ? `<span class="quest-xp">🌟 ${quest.xp_reward} XP</span>` : ''}
        </div>
        <p style="margin:0.2rem 0;color:var(--text-muted);font-size:0.9rem;">${quest.description||''}</p>
        ${objHtml}
        <textarea id="notes-${quest.id}" placeholder="Suas anotações..." rows="2"
                  style="width:100%;resize:vertical;font-size:0.85rem;margin-top:0.4rem;"
                  onblur="saveQuestNotes('${quest.id}')">${quest._my_note || ''}</textarea>
    </div>`;
}

socket.on('new_quest', (quest) => {
    const list = document.getElementById('player-quests');
    const emptyState = document.getElementById('no-quests-msg');
    if (emptyState) emptyState.remove();
    list.insertAdjacentHTML('afterbegin', renderPlayerQuestCard(quest));
    playNotificationSound();
    showNotification(`📜 Nova quest: ${quest.title}`, 'info');
});

socket.on('quest_updated', (quest) => {
    const card = document.getElementById(`player-quest-${quest.id}`);
    if (card) {
        const note = document.getElementById(`notes-${quest.id}`)?.value || '';
        quest._my_note = note;
        card.outerHTML = renderPlayerQuestCard(quest);
    }
});

socket.on('quest_deleted', (data) => {
    const card = document.getElementById(`player-quest-${data.quest_id}`);
    if (card) card.remove();
});

socket.on('quest_completed', (data) => {
    const card = document.getElementById(`player-quest-${data.quest_id}`);
    if (card) {
        card.classList.add('quest-completed');
        card.style.opacity = '0.6';
        card.querySelectorAll('button, input').forEach(el => el.disabled = true);
    }
    if (data.xp_reward > 0) showNotification(`✅ Quest completada! +${data.xp_reward} XP!`, 'success');
});

async function playerToggleObjective(questId, idx, checkbox) {
    const res = await fetch(`/quests/${questId}/objectives/${idx}/toggle`, { method: 'POST' });
    const data = await res.json();
    if (!data.quest) { checkbox.checked = !checkbox.checked; return; }
    // Update progress bar
    const objs = data.quest.objectives || [];
    const done = objs.filter(o => o.done).length;
    const total = objs.length;
    const bar = document.getElementById(`progress-bar-${questId}`);
    if (bar) bar.style.width = `${total ? Math.round(done/total*100) : 0}%`;
    // Update label style
    const lbl = document.getElementById(`obj-label-${questId}-${idx}`);
    if (lbl) {
        if (checkbox.checked) {
            lbl.style.opacity = '0.5'; lbl.style.textDecoration = 'line-through';
        } else {
            lbl.style.opacity = ''; lbl.style.textDecoration = '';
        }
    }
    if (data.auto_completed) showNotification('🎉 Todos os objetivos completos! A quest foi finalizada!', 'success');
}

async function saveQuestNotes(questId) {
    const note = document.getElementById(`notes-${questId}`)?.value || '';
    await fetch(`/quests/${questId}/notes`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ note })
    });
}

function togglePlayerCompleted() {
    const el = document.getElementById('player-completed-quests');
    const icon = document.getElementById('completed-toggle-icon');
    if (!el) return;
    const visible = el.style.display !== 'none';
    el.style.display = visible ? 'none' : '';
    if (icon) icon.textContent = visible ? '▼' : '▲';
}

socket.on('master_action', (data) => {
    if (data.type === 'forced_encounter') {
        const flags = [data.is_shiny ? '✨ SHINY' : '', data.is_mega ? '🔮 MEGA' : ''].filter(Boolean).join(' + ');
        currentEncounter = {
            pokemon:  data.pokemon,
            level:    data.level,
            is_shiny: data.is_shiny || false,
            is_mega:  data.is_mega  || false,
            wild_moves: data.pokemon?.startingMoves?.slice(-4) || []
        };
        displayEncounter(currentEncounter);
        alert(`⚠️ O Mestre enviou um Pokémon Selvagem!${flags ? ' ' + flags : ''}`);
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
    // Use the highest Pokemon level in team (1-100 scale), not trainer level
    const team = playerTeam || [];
    const highestPokeLv = team.length > 0 ? Math.max(...team.map(p => p.level || 1)) : 5;
    const response = await fetch('/api/encounter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ route_id: routeId, hunt_mode: huntMode, player_level: highestPokeLv })
    });
    const encounter = await response.json();
    if (encounter.error) { alert('Nenhum Pokémon encontrado!'); return; }
    currentEncounter = encounter;
    await displayEncounter(encounter);
}

async function displayEncounter(encounter) {
    const pokemon = encounter.pokemon;
    
    // Calculate scaled stats for the wild pokemon
    try {
        const resp = await fetch('/api/pokemon/stats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ number: pokemon.number, level: encounter.level })
        });
        const scaledStats = await resp.json();
        if (!scaledStats.error) {
            pokemon.hp = scaledStats.hp;
            pokemon.maxHp = scaledStats.maxHp;
            pokemon.ac = scaledStats.ac;
            pokemon.stats = scaledStats.stats;
            pokemon.proficiency = scaledStats.proficiency;
            pokemon.stab = scaledStats.stab;
            encounter.pokemon = pokemon;
        }
    } catch(e) {}
    
    // Check if player can control (for capture preview)
    const trainerLevel = TRAINER_DATA.level || 1;
    const maxControlLevel = trainerLevel * 5;
    const canControl = encounter.level <= maxControlLevel;
    
    showElement('encounter-result');
    document.getElementById('wild-pokemon-name').textContent = `${pokemon.name} #${String(pokemon.number).padStart(3, '0')}`;
    document.getElementById('wild-pokemon-level').textContent = encounter.level;
    document.getElementById('wild-pokemon-hp').textContent = pokemon.hp;
    document.getElementById('wild-pokemon-ac').textContent = pokemon.ac;
    document.getElementById('wild-pokemon-types').innerHTML = formatTypes(pokemon.types);
    const sprite = document.getElementById('wild-pokemon-sprite');
    sprite.src = getPokemonSpriteUrl(pokemon.number, encounter.is_shiny);
    sprite.alt = pokemon.name;
    const shinyBadge = document.getElementById('shiny-badge');
    encounter.is_shiny ? shinyBadge.classList.remove('hidden') : shinyBadge.classList.add('hidden');
    
    // Show control warning
    if (!canControl) {
        addBattleLog(`⚠️ <strong>Atenção:</strong> Este Pokémon é Nv.${encounter.level} — seu limite é Nv.${maxControlLevel} (Treinador Nv.${trainerLevel}). Você pode batalhar mas NÃO controlar se capturar.`);
    }
    
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
            if (!playerPokemon.types || playerPokemon.types.length === 0) playerPokemon.types = api.types;
            if (!playerPokemon.speed) playerPokemon.speed = api.speed;
            if (!playerPokemon.vulnerabilities) playerPokemon.vulnerabilities = api.vulnerabilities;
            if (!playerPokemon.resistances) playerPokemon.resistances = api.resistances;
            if (!playerPokemon.immunities) playerPokemon.immunities = api.immunities;
            if (!playerPokemon.moves || playerPokemon.moves.length === 0) {
                let moves = [...(api.startingMoves || [])];
                if (api.levelMoves) {
                    for (const [lv, m] of Object.entries(api.levelMoves)) {
                        if (parseInt(lv) <= (playerPokemon.level || 1)) moves.push(...m);
                    }
                }
                playerPokemon.moves = moves.slice(-4);
            }
            
            // Apply level scaling to player's pokemon
            const scaledResp = await fetch('/api/pokemon/stats', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ number: api.number, level: playerPokemon.level || 1 })
            });
            const scaled = await scaledResp.json();
            if (!scaled.error) {
                playerPokemon.stats = applyNatureToStats(scaled.stats, playerPokemon.nature);
                playerPokemon.maxHp = scaled.maxHp;
                playerPokemon.currentHp = Math.min(playerPokemon.currentHp || scaled.hp, scaled.maxHp);
                playerPokemon.ac = scaled.ac;
                playerPokemon.proficiency = scaled.proficiency;
                playerPokemon.stab = scaled.stab;
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

    // Auto-roll initiative (no longer needs master)
    socket.emit('roll_initiative', { player_id: null, auto: true });

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
    window._permadeathTriggered  = false;
    window._masterBallCapture    = false;
    window._wildIntimidateMod    = 0;
    window._playerTrapped        = false;
    window._playerTrappedBy      = null;
    window._enemyTrapped         = false;
    window._enemyTrappedBy       = null;

    // Store current battle data
    window.currentBattleData = { enemy, playerPokemon, level: currentEncounter.level };

    // Fire battle transition, then fill data
    await playBattleTransition();
    showBattlePanel('menu');

    // Fill enemy data
    const enemySpriteUrl = getPokemonSpriteUrl(enemy.number, currentEncounter.is_shiny);
    document.getElementById('battle-enemy-sprite').src = enemySpriteUrl;
    battleSpriteEnter('battle-enemy-sprite', 'enemy');
    document.getElementById('battle-enemy-name-full').textContent = enemy.name;
    document.getElementById('battle-enemy-level-badge').textContent = `Nv.${currentEncounter.level}`;
    document.getElementById('battle-enemy-types').innerHTML = formatTypes(enemy.types);
    document.getElementById('battle-enemy-hp-text-full').textContent = `${enemy.hp}/${enemy.hp} HP`;
    document.getElementById('battle-enemy-hp-bar-full').style.width = '100%';
    const eac = document.getElementById('battle-enemy-ac'); if (eac) eac.textContent = enemy.ac;
    const espd = document.getElementById('battle-enemy-speed'); if (espd) espd.textContent = enemy.speed || '30ft';

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
    const playerSpriteUrl = pNum ? getPokemonSpriteUrl(pNum) : '';
    console.log('SPRITE player:', pNum, playerSpriteUrl);
    document.getElementById('battle-player-sprite').src = playerSpriteUrl;
    battleSpriteEnter('battle-player-sprite', 'player');
    document.getElementById('battle-player-name-full').textContent = playerPokemon.nickname || playerPokemon.name;
    const plvlBadge = document.getElementById('battle-player-level-badge');
    if (plvlBadge) plvlBadge.textContent = `Nv.${playerPokemon.level}`;
    document.getElementById('battle-player-types').innerHTML = formatTypes(playerPokemon.types || []);
    const pHp = playerPokemon.currentHp || playerPokemon.maxHp || 20;
    const pMax = playerPokemon.maxHp || 20;
    document.getElementById('battle-player-hp-text-full').textContent = `${pHp}/${pMax} HP`;
    setHpBar('battle-player-hp-bar-full', pHp, pMax);
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
    document.getElementById('battle-log-full').innerHTML = `<p>⚔️ Batalha iniciada! ${playerPokemon.nickname || playerPokemon.name} vs ${enemy.name} selvagem!</p><p>⏳ Rolando iniciativa...</p>`;
    
    // Auto-roll initiative (player can trigger it themselves)
    socket.emit('roll_initiative', {});
    
    // Check mega availability
    megaUsedThisBattle = false;
    checkMegaAvailable();
}

// Listen for initiative result
socket.on('initiative_result', (data) => {
    addBattleLog(`🎲 Iniciativa - Você: <strong>${data.player_initiative}</strong> (DEX ${data.player_mod >= 0 ? '+' : ''}${data.player_mod}) | Selvagem: <strong>${data.wild_initiative}</strong> (DEX ${data.wild_mod >= 0 ? '+' : ''}${data.wild_mod})`);
    addBattleLog(`➡️ <strong>${data.first_turn === 'player' ? 'Você começa!' : 'Pokémon Selvagem começa!'}</strong>`);
    // Show on-enter ability messages
    if (data.on_enter_abilities?.length) {
        data.on_enter_abilities.forEach(msg => addBattleLog(`✨ <em>${msg}</em>`));
    }
    if (data.weather) {
        const weatherNames = { sun:'☀️ Sol forte!', rain:'🌧️ Chuva forte!', sandstorm:'🌪️ Tempestade de areia!', hail:'❄️ Granizo!' };
        addBattleLog(`🌤️ <strong>${weatherNames[data.weather] || data.weather}</strong>`);
        window.currentWeather = data.weather;
    }
    window.currentTurn = data.first_turn;
    updateTurnUI();
    if (data.first_turn === 'wild') {
        setTimeout(() => wildPokemonAutoAttack(), 1500);
    }
});

// Listen for battle updates
socket.on('battle_update', (data) => {
    const bs = data.battle_state;
    const prevEnemyHp = parseInt(document.getElementById('battle-enemy-hp-text-full')?.textContent) || bs.wild_hp_current;
    const prevPlayerHp = parseInt(document.getElementById('battle-player-hp-text-full')?.textContent) || bs.player_hp_current;

    // Update HP bars
    setHpBar('battle-enemy-hp-bar-full', bs.wild_hp_current, bs.wild_hp_max);
    document.getElementById('battle-enemy-hp-text-full').textContent = `${bs.wild_hp_current}/${bs.wild_hp_max} HP`;
    setHpBar('battle-player-hp-bar-full', bs.player_hp_current, bs.player_hp_max);
    document.getElementById('battle-player-hp-text-full').textContent = `${bs.player_hp_current}/${bs.player_hp_max} HP`;

    // Hit flash & sounds
    if (data.damage > 0) {
        if (data.action_by === 'player' && bs.wild_hp_current < prevEnemyHp) {
            battleSpriteHit('battle-enemy-sprite');
            hpBarShake(document.querySelector('.enemy-side .hp-bar-container'));
            playSound('hit');
        } else if (data.action_by === 'master' && bs.player_hp_current < prevPlayerHp) {
            battleSpriteHit('battle-player-sprite');
            hpBarShake(document.querySelector('.player-side .hp-bar-container'));
            playSound('hit');
        }
    }

    // Keep active pokémon's HP in sync with battle state in real-time
    if (window.currentBattleData?.playerPokemon) {
        window.currentBattleData.playerPokemon.currentHp = Math.max(0, bs.player_hp_current);
        const activePoke = window.currentBattleData.playerPokemon;
        const teamIdx = playerTeam.findIndex(p =>
            (p.nickname || p.name) === (activePoke.nickname || activePoke.name) && p.level === activePoke.level
        );
        if (teamIdx >= 0) playerTeam[teamIdx].currentHp = Math.max(0, bs.player_hp_current);
    }

    // Log action (only if not already logged locally by wild auto-attack)
    if (!window._wildIsActing || data.action_by === 'player') {
        const who = data.action_by === 'player' ? '🟢 Seu Pokémon' : '🔴 Selvagem';
        let msg = `${who} usou <strong>${data.move_name}</strong>`;
        if (data.damage > 0) msg += ` → ${data.damage} de dano!`;
        if (data.heal > 0) msg += ` → curou ${data.heal} HP!`;
        if (data.status_effect) msg += ` → ${data.status_effect}!`;
        if (data.message) msg += ` <em>(${data.message})</em>`;
        addBattleLog(msg);
    }
    // Show ability trigger from server
    if (data.ability_trigger) {
        addBattleLog(`🛡️ <strong>Habilidade</strong>: ${data.ability_trigger.message}`);
    }

    // Sync status from server (source of truth)
    if (bs.wild_status && !window.wildPokemonStatus) {
        const ws = typeof bs.wild_status === 'string'
            ? { condition: bs.wild_status, turns_active: 0 }
            : bs.wild_status;
        window.wildPokemonStatus = ws;
        const cond = window.statusEffectsData?.conditions?.[ws.condition];
        if (cond) addBattleLog(`${cond.icon} Pokémon selvagem ficou <strong>${cond.name}</strong>!`);
        updateStatusDisplay();
    }
    if (bs.player_status && !window.playerPokemonStatus) {
        const ps = typeof bs.player_status === 'string'
            ? { condition: bs.player_status, turns_active: 0 }
            : bs.player_status;
        window.playerPokemonStatus = ps;
        const cond = window.statusEffectsData?.conditions?.[ps.condition];
        if (cond) addBattleLog(`${cond.icon} Seu Pokémon ficou <strong>${cond.name}</strong>! ${cond.description}`);
        updateStatusDisplay();
    }

    // Update turn
    window.currentTurn = bs.turn;
    updateTurnUI();

    // Wild Pokemon auto-attack when it's their turn
    if (bs.turn === 'wild' && bs.wild_hp_current > 0 && bs.player_hp_current > 0 && !window.wildFainted && !window._wildIsActing) {
        setTimeout(() => wildPokemonAutoAttack(), 1200);
    }

    // Check faint
    if (bs.wild_hp_current <= 0) {
        battleSpriteFaint('battle-enemy-sprite');
        playSound('faint');
        addBattleLog(`<strong>💀 Pokémon Selvagem desmaiou!</strong>`);
        addBattleLog(`🔴 Você pode <strong>Arremessar Pokébola</strong> para tentar capturar ou clicar <strong>Derrotei</strong> para encerrar.`);
        window.currentTurn = 'player';
        window.wildFainted = true;
        document.querySelectorAll('#battle-player-moves .selectable-move').forEach(btn => {
            btn.style.opacity = '0.3';
            btn.style.pointerEvents = 'none';
        });
        document.getElementById('btn-pass-turn')?.classList.add('hidden');
        document.getElementById('btn-switch-pokemon')?.classList.add('hidden');
    }
    if (bs.player_hp_current <= 0 && bs.player_hp_current > -30 && !window._playerFaintLogged) {
        window._playerFaintLogged = true;
        battleSpriteFaint('battle-player-sprite');
        playSound('faint');
        addBattleLog(`<strong>😵 Seu Pokémon desmaiou!</strong>`);
    }
    if (bs.player_hp_current > 0) {
        window._playerFaintLogged = false;
    }
    // Morte permanente: HP chegou a -30 ou abaixo
    if (bs.player_hp_current <= -30 && !window._permadeathTriggered) {
        window._permadeathTriggered = true;
        triggerPermanentDeath();
    }
});

function updateTurnUI() {
    const moveBtns = document.querySelectorAll('#battle-player-moves .selectable-move');
    const passBtn = document.getElementById('btn-pass-turn');
    if (window.currentTurn === 'player') {
        moveBtns.forEach(btn => { btn.style.opacity = '1'; btn.style.pointerEvents = 'auto'; });
        if (passBtn) passBtn.classList.remove('hidden');
        if (battleActive && !window.wildFainted) startTurnCountdown();
    } else {
        moveBtns.forEach(btn => { btn.style.opacity = '0.5'; btn.style.pointerEvents = 'none'; });
        if (passBtn) passBtn.classList.add('hidden');
        clearTurnCountdown();
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
    const catIcon = m.category === 'special' ? '✨' : m.category === 'status' ? '◉' : '⚔️';
    const escapedName = moveName.replace(/'/g, "\\'");
    
    if (clickable) {
        return `<span class="move-btn selectable-move ${typeClass}" 
                      data-move="${moveName}"
                      onclick="handleMoveTap('${escapedName}')"
                      onmouseenter="showMoveTooltip(event, '${escapedName}')"
                      onmouseleave="hideMoveTooltip()"
                      ontouchstart="startMoveHold(event, '${escapedName}')"
                      ontouchend="endMoveHold(event, '${escapedName}')"
                      ontouchcancel="cancelMoveHold()"
                >${catIcon} ${moveName}${dmgLabel}</span>`;
    }
    return `<span class="move-btn ${typeClass}"
                  onmouseenter="showMoveTooltip(event, '${escapedName}')"
                  onmouseleave="hideMoveTooltip()"
                  ontouchstart="startMoveHold(event, '${escapedName}')"
                  ontouchend="endMoveHoldInfo(event, '${escapedName}')"
                  ontouchcancel="cancelMoveHold()"
            >${catIcon} ${moveName}${dmgLabel}</span>`;
}

// Mobile long-press handling: tap = attack, hold 1.5s = show info
let _moveHoldTimer = null;
let _moveHoldTriggered = false;

function startMoveHold(event, moveName) {
    event.preventDefault();
    _moveHoldTriggered = false;
    _moveHoldTimer = setTimeout(() => {
        _moveHoldTriggered = true;
        showMoveModal(moveName);
        // Vibrate on long press if supported
        if (navigator.vibrate) navigator.vibrate(50);
    }, 1500);
}

function endMoveHold(event, moveName) {
    event.preventDefault();
    clearTimeout(_moveHoldTimer);
    if (!_moveHoldTriggered) {
        // Short tap = attack
        useMove(moveName);
    }
    _moveHoldTriggered = false;
}

function endMoveHoldInfo(event, moveName) {
    // For non-clickable moves (enemy moves), tap shows info
    event.preventDefault();
    clearTimeout(_moveHoldTimer);
    if (!_moveHoldTriggered) {
        showMoveModal(moveName);
    }
    _moveHoldTriggered = false;
}

function cancelMoveHold() {
    clearTimeout(_moveHoldTimer);
    _moveHoldTriggered = false;
}

function handleMoveTap(moveName) {
    // Desktop click handler (mouse only, touch is handled by touchstart/end)
    if (_moveHoldTriggered) return; // Ignore if long-press was triggered
    useMove(moveName);
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

async function useMove(moveName) {
    if (window.currentTurn !== 'player') { alert('Não é seu turno!'); return; }
    
    const m = MOVES_CACHE[moveName] || {};
    const poke = window.currentBattleData?.playerPokemon;
    const stats = poke?.stats || {};
    const pokeLevel = poke?.level || 1;
    
    // NEW STAT SYSTEM: Physical (ATK vs DEF) or Special (SPA vs SPD)
    const moveCategory = m.category || 'physical'; // 'physical', 'special', 'status'
    let moveMod = 0;
    
    if (moveCategory === 'physical') {
        moveMod = Math.floor(((stats.ATK || stats.STR || 10) - 10) / 2);
    } else if (moveCategory === 'special') {
        moveMod = Math.floor(((stats.SPA || stats.INT || 10) - 10) / 2);
    }
    
    // Proficiency bonus based on Pokemon level (1-100 scale)
    const profBonus = poke?.proficiency || getProficiencyForLevel(pokeLevel);
    
    // If move has no baseDamage OR is known as a status move, process as status
    const PLAYER_STATUS_MOVES = ['harden', 'withdraw', 'iron defense', 'acid armor', 'barrier', 'cotton guard',
        'cosmic power', 'defend order', 'swords dance', 'bulk up', 'calm mind', 'dragon dance',
        'nasty plot', 'quiver dance', 'shell smash', 'work up', 'curse', 'stockpile',
        'amnesia', 'double team', 'minimize', 'growth', 'meditate', 'sharpen',
        'belly drum', 'coil', 'shift gear', 'autotomize', 'rock polish', 'agility',
        'light screen', 'reflect', 'safeguard', 'mist', 'aurora veil',
        'rest', 'recover', 'roost', 'synthesis', 'moonlight', 'soft-boiled', 'milk drink',
        'protect', 'detect', 'endure', 'spiky shield', 'baneful bunker',
        'toxic', 'will-o-wisp', 'thunder wave', 'hypnosis', 'sleep powder', 'stun spore',
        'confuse ray', 'swagger', 'supersonic', 'sweet kiss', 'sing', 'grass whistle',
        'scary face', 'string shot', 'cotton spore', 'growl', 'leer', 'tail whip', 'screech',
        'smokescreen', 'sand attack', 'flash', 'charm', 'fake tears', 'metal sound',
        'rain dance', 'sunny day', 'sandstorm', 'hail', 'attract', 'taunt', 'encore',
        'disable', 'torment', 'spite', 'wish', 'heal bell', 'aromatherapy',
        'venom drench', 'toxic spikes', 'spikes', 'stealth rock', 'sticky web'];
    
    if (!m.baseDamage || PLAYER_STATUS_MOVES.includes(moveName.toLowerCase())) {
        await processStatusMove(moveName, poke, window.currentBattleData?.enemy);
        return;
    }
    
    // Determine enemy's AC based on move category and dodge state
    const enemy = window.currentBattleData?.enemy || {};
    const enemyStats = enemy.stats || {};
    let enemyAC;
    let defenseType;
    
    if (window.enemyDodging) {
        // Enemy is dodging: use SPE-based AC, but hits deal 1.25x damage
        enemyAC = 8 + Math.floor(((enemyStats.SPE || 10) - 10) / 2) + getProficiencyForLevel(currentEncounter?.level || 5) / 2;
        defenseType = '🏃 Esquiva';
    } else if (moveCategory === 'physical') {
        enemyAC = 8 + Math.floor(((enemyStats.DEF || 10) - 10) / 2) + Math.floor(getProficiencyForLevel(currentEncounter?.level || 5) / 2);
        defenseType = '🛡️ DEF';
    } else {
        enemyAC = 8 + Math.floor(((enemyStats.SPD || 10) - 10) / 2) + Math.floor(getProficiencyForLevel(currentEncounter?.level || 5) / 2);
        defenseType = '✨ SPD';
    }
    enemyAC = Math.max(8, Math.floor(enemyAC));
    
    // Roll d20 for attack
    const attackRoll = Math.floor(Math.random() * 20) + 1;
    const isCrit = attackRoll === 20;
    const isMiss = attackRoll === 1;
    // Apply accuracy mod (from Smokescreen etc.)
    const accMod = window.playerAccuracyMod || 0;
    const totalAttack = attackRoll + moveMod + profBonus + accMod;
    
    const categoryLabel = moveCategory === 'physical' ? '⚔️ Físico' : '✨ Especial';
    const statLabel = moveCategory === 'physical' ? 'ATK' : 'SPA';
    addBattleLog(`▶️ <strong>${moveName}</strong> [${categoryLabel}] → d20(${attackRoll}) + ${statLabel}(${moveMod}) + Prof(${profBonus})${accMod ? ` + Acc(${accMod})` : ''} = <strong>${totalAttack}</strong> vs ${defenseType}(${enemyAC})${isCrit ? ' 💥 CRÍTICO!' : ''}${isMiss ? ' 💨 Falha!' : ''}`);
    animateDice(attackRoll, 'd20');
    
    if (isMiss) {
        addBattleLog(`❌ Falha crítica!`);
        socket.emit('battle_action', { action_by: 'player', action_type: 'attack', move_name: moveName, damage: 0, player_status_damage: window._playerPreTurnStatusDamage || 0, message: 'Nat 1 - Falha' });
    } else if (totalAttack >= enemyAC || isCrit) {
        // Auto-calculate damage with level-scaled dice
        const scaledDice = getScaledDice(m.baseDamage || '1d6', pokeLevel, m.higherLevels || '');
        const diceRoll = rollDamageFromString(scaledDice, pokeLevel);
        let damage = diceRoll + moveMod;
        if (isCrit) {
            const critExtra = rollDamageFromString(scaledDice, pokeLevel);
            damage = diceRoll + critExtra + moveMod;
        }
        
        // STAB check (uses scaled stab from pokemon data)
        const pokeTypes = (poke?.types || []).map(t => t.toLowerCase());
        const moveType = (typeof m.type === 'string' ? m.type : String(m.type || '')).toLowerCase();
        const stab = pokeTypes.includes(moveType) ? (poke?.stab || getStabForLevel(pokeLevel)) : 0;
        damage += stab;

        // Attacker ability bonus: Blaze/Torrent/Overgrow/Swarm (HP ≤ 1/3 → +1d6 same-type)
        const atkAbility = (poke?.ability?.name || poke?.ability || '').toLowerCase();
        const PINCH_ABILITIES = { blaze:'fire', torrent:'water', overgrow:'grass', swarm:'bug' };
        const pinchType = PINCH_ABILITIES[atkAbility];
        const pokeHp = window.currentBattleData?.playerPokemon?.currentHp ?? poke?.currentHp ?? poke?.maxHp;
        const pokeMaxHp = poke?.maxHp || 1;
        if (pinchType && moveType === pinchType && pokeHp <= pokeMaxHp / 3) {
            const bonus = Math.floor(Math.random() * 6) + 1;
            damage += bonus;
            addBattleLog(`🔥 <strong>${atkAbility.charAt(0).toUpperCase()+atkAbility.slice(1)}</strong> ativado! +${bonus} dano!`);
        }

        if (damage < 1) damage = 1;
        
        // Dodge penalty: if enemy was dodging and got hit, 1.25x damage
        if (window.enemyDodging) {
            damage = Math.floor(damage * 1.25);
            addBattleLog(`🏃 Acertou em esquiva! Dano ×1.25 → ${damage}`);
        }
        
        // Type effectiveness vs enemy
        // Move types are in PT (Fogo, Grama, etc.) but vulnerabilities are in EN (Fire, Grass, etc.)
        const typeMapPtToEn = {
            'fogo':'fire', 'água':'water', 'grama':'grass', 'elétrico':'electric',
            'gelo':'ice', 'lutador':'fighting', 'venenoso':'poison', 'terra':'ground',
            'voador':'flying', 'psíquico':'psychic', 'inseto':'bug', 'pedra':'rock',
            'fantasma':'ghost', 'dragão':'dragon', 'sombrio':'dark', 'aço':'steel',
            'fada':'fairy', 'normal':'normal'
        };
        const moveTypeEn = typeMapPtToEn[moveType] || moveType;
        
        const enemyForType = window.currentBattleData?.enemy || {}; 
        const enemyVulns = (enemyForType.vulnerabilities || []).map(t => t.toLowerCase());
        const enemyResists = (enemyForType.resistances || []).map(t => t.toLowerCase());
        const enemyImmunities = (enemyForType.immunities || []).map(t => t.toLowerCase());
        
        let effectiveness = 1;
        let effectLabel = '';
        if (enemyImmunities.includes(moveTypeEn)) {
            effectiveness = 0;
            effectLabel = '⛔ IMUNE (0x)';
        } else {
            if (enemyVulns.includes(moveTypeEn)) effectiveness *= 2;
            if (enemyResists.includes(moveTypeEn)) effectiveness *= 0.5;
        }
        
        damage = Math.floor(damage * effectiveness);
        if (effectiveness === 0) damage = 0;
        if (effectiveness > 1) effectLabel = `⚡ Super Efetivo (x${effectiveness})`;
        else if (effectiveness < 1 && effectiveness > 0) effectLabel = `🛡️ Não Efetivo (x${effectiveness})`;

        // Check enemy ability (client-side preview — server also validates)
        const _rawEnemyAbility = window.currentBattleData?.enemy?.ability;
        const enemyAbility = (typeof _rawEnemyAbility === 'string' ? _rawEnemyAbility : '').toLowerCase();
        if (damage > 0 && enemyAbility) {
            const abilityCheck = checkAbilityVsMove(enemyAbility, moveTypeEn, damage,
                window.currentBattleData?.enemy?.currentHp, window.currentBattleData?.enemy?.hp);
            if (abilityCheck.blocked) {
                damage = 0;
                addBattleLog(`🛡️ <strong>${enemyAbility}</strong>: ${abilityCheck.message}`);
            } else if (abilityCheck.modified_damage !== damage) {
                addBattleLog(`🛡️ <strong>${enemyAbility}</strong>: ${abilityCheck.message}`);
                damage = abilityCheck.modified_damage;
            }
        }

        const statUsed = moveCategory === 'physical' ? 'ATK' : 'SPA';
        addBattleLog(`✅ Acertou! (${totalAttack} vs AC ${enemyAC}) → ${scaledDice}(${diceRoll}) + ${statUsed}(${moveMod})${stab > 0 ? ` + STAB(${stab})` : ''}${isCrit ? ' ×2 CRIT' : ''}${window.enemyDodging ? ' ×1.25(esquiva)' : ''}${effectLabel ? ' ' + effectLabel : ''} = <strong>${damage} dano ${m.type||''}</strong>`);

        // Check for status effect (await so the result is ready before emitting)
        await checkMoveStatusEffect(moveName, attackRoll, damage);

        socket.emit('battle_action', {
            action_by: 'player', action_type: 'attack', move_name: moveName,
            move_type: moveTypeEn,
            damage: damage, message: `${totalAttack} vs AC ${enemyAC}${isCrit ? ' Crítico!' : ''}`,
            player_status_damage: window._playerPreTurnStatusDamage || 0,
            status_effect: window._lastStatusInflicted || null
        });
        window._lastStatusInflicted = null;
    } else {
        addBattleLog(`❌ Errou! (${totalAttack} < AC ${enemyAC})`);
        socket.emit('battle_action', { action_by: 'player', action_type: 'attack', move_name: moveName, damage: 0, player_status_damage: window._playerPreTurnStatusDamage || 0, message: `Errou (${totalAttack} vs AC ${enemyAC})` });
    }
}

function rollDamageFromString(diceStr, pokeLevel) {
    if (!diceStr) return 0;
    const match = diceStr.match(/(\d+)d(\d+)/);
    if (!match) return 0;
    const count = parseInt(match[1]);
    const sides = parseInt(match[2]);
    let total = 0;
    for (let i = 0; i < count; i++) total += Math.floor(Math.random() * sides) + 1;
    return total;
}

function getScaledDice(baseDamage, level, higherLevelsText) {
    // Scale damage dice based on Pokemon level (1-100)
    if (!baseDamage) return '1d6';
    const match = baseDamage.match(/(\d+)d(\d+)/);
    if (!match) return baseDamage;
    const count = parseInt(match[1]);
    const sides = parseInt(match[2]);
    
    // If higherLevels text exists, parse trainer-level thresholds and multiply by 5
    if (higherLevelsText) {
        const lvMatches = [...higherLevelsText.matchAll(/(\d+d\d+)\s+no\s+n[ií]vel\s+(\d+)/gi)];
        let bestDice = baseDamage;
        for (const m of lvMatches) {
            const pokeLv = parseInt(m[2]) * 5; // trainer lv → pokemon lv
            if (level >= pokeLv) bestDice = m[1];
        }
        return bestDice;
    }
    
    // Default scaling by pokemon level
    let multiplier = 1.0;
    if (level >= 80) multiplier = 3.0;
    else if (level >= 60) multiplier = 2.5;
    else if (level >= 40) multiplier = 2.0;
    else if (level >= 20) multiplier = 1.5;
    else if (level >= 10) multiplier = 1.25;
    
    const newCount = Math.max(count, Math.ceil(count * multiplier));
    return `${newCount}d${sides}`;
}

function getStabForLevel(level) {
    if (level >= 81) return 6;
    if (level >= 61) return 5;
    if (level >= 41) return 4;
    if (level >= 26) return 3;
    if (level >= 11) return 2;
    return 1;
}

function getProficiencyForLevel(level) {
    if (level >= 91) return 10;
    if (level >= 81) return 9;
    if (level >= 71) return 8;
    if (level >= 61) return 7;
    if (level >= 51) return 6;
    if (level >= 41) return 5;
    if (level >= 31) return 4;
    if (level >= 17) return 3;
    return 2;
}

function passTurn() {
    if (window.currentTurn !== 'player') return;
    addBattleLog(`⏭️ Turno passado.`);
    socket.emit('battle_action', { action_by: 'player', action_type: 'pass', move_name: 'Passar', damage: 0, player_status_damage: window._playerPreTurnStatusDamage || 0, message: 'Passou o turno' });
}

function throwPokeball() {
    // Validate ball exists in bag
    const ballType = document.getElementById('pokeball-select')?.value || 'pokeball';
    const ballItemNames = {
        pokeball:   ['Pokébola', 'Poke Ball', 'Pokeball'],
        greatball:  ['Great Ball', 'Bola Super', 'Super Ball', 'Super Bola'],
        ultraball:  ['Ultra Ball', 'Bola Ultra', 'Ultra Bola'],
        netball:    ['Net Ball', 'Net Bola'],
        healball:   ['Heal Ball', 'Cura Bola'],
        masterball: ['Master Ball', 'Bola Master']
    };
    const bagNames = (ballItemNames[ballType] || []).map(n => n.toLowerCase());
    const bagItem  = (window.bagItems || []).find(i => bagNames.includes((i.name || '').toLowerCase()));
    if (!bagItem || (bagItem.qty || 0) < 1) {
        alert(`Você não tem ${document.getElementById('pokeball-select')?.options[document.getElementById('pokeball-select')?.selectedIndex]?.text.replace(/\s*\(.*\)/, '') || 'esta Pokébola'} na bolsa!`);
        return;
    }

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
    const hasStatusAdvantage = enemyFainted || !!window.wildPokemonStatus;
    
    if (hasStatusAdvantage) {
        finalRoll = Math.max(roll1, roll2);
        advantageText = ` (Vantagem! ${roll1}, ${roll2} → ${finalRoll})`;
    }
    
    // Pokeball type bonus
    const ballNames = { pokeball: '🔴 Pokébola', greatball: '🔵 Super Bola', ultraball: '⚫ Ultra Bola', netball: '🟢 Net Bola', healball: '🩷 Cura Bola', masterball: '🟣 Master Ball' };
    const ballBonus = { pokeball: 0, greatball: 2, ultraball: 4, netball: 0, healball: 0, masterball: 999 };

    // Net Ball: +3 if enemy is Bug or Water
    let netBallBonus = 0;
    if (ballType === 'netball') {
        const enemyTypes = (window.currentBattleData?.enemy?.types || []).map(t => t.toLowerCase());
        if (enemyTypes.some(t => t === 'bug' || t === 'water')) {
            netBallBonus = 3;
            addBattleLog(`🟢 Net Bola: +3 bônus contra Bug/Water!`);
        }
    }

    const bonus = (ballBonus[ballType] || 0) + netBallBonus;
    const ballLabel = ballNames[ballType] || '🔴 Pokébola';

    const totalRoll = finalRoll + animalHandlingBonus + bonus;

    // Consume 1 ball from bag
    bagItem.qty -= 1;
    if (bagItem.qty <= 0) {
        window.bagItems = window.bagItems.filter(i => i !== bagItem);
    }
    saveBag();

    addBattleLog(`${ballLabel} <strong>arremessada!</strong>${enemyFainted ? ' (Pokémon desmaiado - CD reduzida)' : ''}${bonus > 0 ? ` [+${bonus} bônus]` : ''}`);

    // Master Ball: captura garantida + concede XP
    if (ballType === 'masterball') {
        addBattleLog(`✅ <strong>CAPTURADO!</strong> 🎉 (Master Ball — captura garantida!)`);
        window._masterBallCapture = true;
        setTimeout(() => endBattle('caught'), 1500);
        return;
    }

    // Regra dos 40%: pokébola quebra automaticamente se o poke tem >40% do HP máximo
    const wildMaxHp  = parseInt(document.getElementById('battle-enemy-hp-text-full').textContent.split('/')[1]) || 1;
    const hpPct      = currentHp / wildMaxHp;
    if (hpPct > 0.40) {
        addBattleLog(`💥 <strong>A Pokébola quebrou!</strong> O Pokémon selvagem ainda está com ${Math.round(hpPct*100)}% do HP — enfraquece-o abaixo de 40% primeiro!`);
        // Pokébola foi consumida mas não funcionou, selvagem foge
        setTimeout(() => {
            if (window._enemyTrapped) {
                addBattleLog(`🔒 ${window._enemyTrappedBy || 'Trapping move'} impediu a fuga do selvagem!`);
                // Don't end battle — wild is trapped, player keeps going
                window.currentTurn = 'player';
                updateTurnUI();
            } else {
                addBattleLog(`🏃 O Pokémon selvagem fugiu após a Pokébola falhar!`);
                endBattle('fled_after_capture');
            }
        }, 1500);
        return;
    }

    addBattleLog(`  CD de Captura: ${enemyFainted ? `5 + SR(${srVal})` : `10 + SR(${srVal}) + Nível(${pokeLevel}) + HP÷10(${hpComponent})`} = <strong>${captureDC}</strong>`);
    addBattleLog(`  Adestrar Animais: d20(${finalRoll})${advantageText} + SAB(${wisMod}) + Prof(${profBonus})${bonus > 0 ? ` + Bola(${bonus})` : ''} = <strong>${totalRoll}</strong>`);

    animateDice(finalRoll, 'd20');

    if (totalRoll >= captureDC) {
        addBattleLog(`✅ <strong>CAPTURADO!</strong> 🎉 (${totalRoll} ≥ ${captureDC})`);
        if (ballType === 'healball') {
            window._healBallCapture = true;
            addBattleLog(`🩷 Cura Bola: o Pokémon capturado será curado completamente!`);
        }
        setTimeout(() => endBattle('caught'), 1500);
    } else {
        addBattleLog(`❌ ${ballLabel} falhou! (${totalRoll} < ${captureDC})`);
        if (window._enemyTrapped) {
            addBattleLog(`🔒 ${window._enemyTrappedBy || 'Trapping move'} impediu a fuga! A batalha continua.`);
            window.currentTurn = 'wild';
            updateTurnUI();
            setTimeout(() => wildPokemonAutoAttack(), 1200);
        } else {
            addBattleLog(`🏃 <strong>O Pokémon selvagem fugiu!</strong> O encontro acabou.`);
            setTimeout(() => endBattle('fled_after_capture'), 2000);
        }
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

    // Sound feedback on battle end
    if (result === 'caught') playSound('catch');
    else if (result === 'fled' || result === 'fled_after_capture') playSound('run');
    else if (result === 'defeated') playSound('levelup');

    // Persist HP and status to team before clearing battle state
    const _activePoke = window.currentBattleData?.playerPokemon;
    if (_activePoke) {
        const _tIdx = playerTeam.findIndex(p =>
            (p.nickname || p.name) === (_activePoke.nickname || _activePoke.name) && p.level === _activePoke.level
        );
        if (_tIdx >= 0) {
            playerTeam[_tIdx].currentHp = Math.max(0, _activePoke.currentHp || 0);
            playerTeam[_tIdx].status = window.playerPokemonStatus || null;
        }
        saveTeam();
    }

    window.wildFainted = false;
    window.wildPokemonStatus = null;
    window.playerPokemonStatus = null;
    window._wildIsActing = false;
    window._processingPlayerStatus = false;
    window._playerFaintLogged = false;
    window._permadeathTriggered = false;
    const _endData = { result };
    if (result === 'defeated' && window.currentBattleData?.playerPokemon) {
        _endData.active_pokemon_name = window.currentBattleData.playerPokemon.nickname || window.currentBattleData.playerPokemon.name;
    }
    socket.emit('end_encounter', _endData);

    // XP só para vitória real: derrotou o selvagem OU capturou com Master Ball
    const earnedXP = result === 'defeated' || (result === 'caught' && window._masterBallCapture);
    if (earnedXP && currentEncounter && window.currentBattleData) {
        awardPokemonBattleXP();
    }
    window._masterBallCapture = false;
    if (result !== 'caught') window._healBallCapture = false;

    // If caught, add to team
    if (result === 'caught' && currentEncounter) {
        const pokemon = currentEncounter.pokemon;
        const trainerLevel = TRAINER_DATA.level || 1;
        let pokeLevel = currentEncounter.level;
        if (pokeLevel < trainerLevel - 2) pokeLevel = Math.max(1, trainerLevel - 2);
        // Primeiro Pokémon do treinador começa no mínimo nível 5
        if (playerTeam.length === 0 && pokeLevel < 5) pokeLevel = 5;

        // Register in pokedex
        registerPokedex(pokemon.number);

        if (playerTeam.length < 6) {
            if (confirm(`Adicionar ${pokemon.name} Nv.${pokeLevel} ao time?`)) {
                const capturedHp = window._healBallCapture ? pokemon.hp : Math.max(1, currentEncounter._capturedHp || Math.floor(pokemon.hp * 0.3));
                window._healBallCapture = false;
                playerTeam.push({
                    name: pokemon.name, nickname: '', number: pokemon.number,
                    types: pokemon.types, level: pokeLevel,
                    maxHp: pokemon.hp, currentHp: capturedHp, ac: pokemon.ac,
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
// MORTE PERMANENTE
// ============================================
window._permadeathTriggered = false;
window._playerFaintLogged = false;

async function triggerPermanentDeath() {
    const battleData  = window.currentBattleData;
    const deadPokemon = battleData?.playerPokemon;
    if (!deadPokemon) return;

    const name = deadPokemon.nickname || deadPokemon.name || 'Seu Pokémon';

    addBattleLog(`💀💔 <strong>${name} atingiu -30 HP e morreu permanentemente!</strong>`);
    addBattleLog(`😢 ${name} foi apagado do seu time para sempre.`);

    // Remove from team
    const idxToRemove = playerTeam.findIndex(p =>
        (p.nickname || p.name) === (deadPokemon.nickname || deadPokemon.name) &&
        p.level === deadPokemon.level
    );
    if (idxToRemove >= 0) {
        playerTeam.splice(idxToRemove, 1);
        await saveTeam();
        refreshTeamDisplay();
    }

    // Wait a beat then end battle
    setTimeout(() => {
        alert(`💀 ${name} morreu permanentemente e foi removido do seu time.`);
        endBattle('fainted');
    }, 2000);
}

// ============================================
// POKEDEX REGISTRATION
// ============================================
async function registerBattlePokedex() {
    const pokemon = window.currentBattleData?.enemy || currentEncounter?.pokemon;
    if (!pokemon) return;
    const result = await registerPokedex(pokemon.number);
    const msg = result?.already_registered ? `✓ ${pokemon.name} já estava na Pokédex` : `✓ ${pokemon.name} registrado! +10 XP`;
    addBattleLog(`📖 ${msg}`);
}

async function registerEncounterPokedex() {
    const pokemon = currentEncounter?.pokemon;
    if (!pokemon) return;
    const result = await registerPokedex(pokemon.number);
    const feedback = document.getElementById('pokedex-register-feedback');
    if (feedback) {
        feedback.textContent = result?.already_registered ? '✓ Já registrado' : `✓ ${pokemon.name} registrado! +10 XP`;
        feedback.style.display = 'inline';
        setTimeout(() => { feedback.style.display = 'none'; }, 3000);
    }
}

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
        if (!TRAINER_DATA.pokedex_seen) TRAINER_DATA.pokedex_seen = [];
        if (!TRAINER_DATA.pokedex_seen.includes(pokemonNumber)) TRAINER_DATA.pokedex_seen.push(pokemonNumber);
    }
    return result;
}

// Full Pokédex — all pokemon loaded locally, filter by search
let _allPokedexPokemon = [];

async function loadFullPokedex() {
    if (_allPokedexPokemon.length > 0) { renderPlayerPokedex(); return; }
    try {
        const res = await fetch('/api/pokemon/all');
        _allPokedexPokemon = await res.json();
        renderPlayerPokedex();
    } catch(e) { console.error('loadFullPokedex', e); }
}

function renderPlayerPokedex() {
    const search = (document.getElementById('player-pokedex-search')?.value || '').toLowerCase();
    const seen = TRAINER_DATA.pokedex_seen || [];
    const grid = document.getElementById('player-pokedex-results');
    if (!grid) return;

    let list = _allPokedexPokemon;
    if (search) {
        list = list.filter(p =>
            p.name.toLowerCase().includes(search) ||
            String(p.number).includes(search)
        );
    }

    grid.innerHTML = list.map(p => {
        const isSeen = seen.includes(p.number);
        const numStr = '#' + String(p.number).padStart(3, '0');
        if (isSeen) {
            return `<div class="pokedex-card pokedex-seen" onclick="showPokedexDetail(${p.number})" style="cursor:pointer;">
                <div class="pokedex-card-header">
                    <span class="pokedex-number">${numStr}</span>
                    <span class="seen-badge">✓</span>
                </div>
                <img src="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${p.number}.png"
                     style="width:56px;height:56px;object-fit:contain;" alt="${p.name}">
                <h4 style="margin:0.2rem 0 0;font-size:0.85rem;">${p.name}</h4>
                <div class="type-badges" style="margin-top:0.2rem;">${formatTypes(p.types)}</div>
            </div>`;
        } else {
            return `<div class="pokedex-card pokedex-locked" style="cursor:default;opacity:0.5;filter:grayscale(1);">
                <div class="pokedex-card-header">
                    <span class="pokedex-number">${numStr}</span>
                </div>
                <div style="width:56px;height:56px;background:var(--border);border-radius:50%;margin:0 auto;display:flex;align-items:center;justify-content:center;font-size:1.5rem;">?</div>
                <h4 style="margin:0.2rem 0 0;font-size:0.85rem;color:var(--muted)">???</h4>
            </div>`;
        }
    }).join('');
}

async function searchPlayerPokedex() {
    renderPlayerPokedex();
}

async function showPokedexDetail(number) {
    const res = await fetch(`/api/pokemon/${number}`);
    const p = await res.json();
    if (p.error) return;
    // Use existing master-style detail modal or create inline
    const grid = document.getElementById('player-pokedex-results');
    const existing = document.getElementById('player-poke-detail');
    if (existing) existing.remove();
    const modal = document.createElement('div');
    modal.id = 'player-poke-detail';
    modal.className = 'modal';
    modal.innerHTML = `<div class="modal-content modal-lg">
        <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:flex-start;">
            <div style="text-align:center;">
                <img src="${getPokemonSpriteUrl(p.number)}" style="width:96px;height:96px;object-fit:contain;">
                <div class="type-badges" style="margin-top:0.5rem;">${formatTypes(p.types||[])}</div>
            </div>
            <div style="flex:1;min-width:200px;">
                <h3 style="margin:0 0 0.25rem;">#${String(p.number).padStart(3,'0')} ${p.name}</h3>
                <p style="color:var(--muted);font-size:0.85rem;margin:0 0 0.5rem;">${p.description||''}</p>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.25rem;font-size:0.85rem;margin-bottom:0.5rem;">
                    <span>HP: <strong>${p.hp||'—'}</strong></span>
                    <span>AC: <strong>${p.ac||'—'}</strong></span>
                    <span>Vel: <strong>${p.speed||'—'}</strong></span>
                    <span>SR: <strong>${p.sr||'—'}</strong></span>
                </div>
                ${p.ability ? `<p style="font-size:0.85rem;"><strong>Habilidade:</strong> ${p.ability.name} — ${p.ability.description}</p>` : ''}
                ${(p.vulnerabilities||[]).length ? `<p style="font-size:0.8rem;color:#f44336"><strong>Vulnerável:</strong> ${p.vulnerabilities.join(', ')}</p>` : ''}
                ${(p.resistances||[]).length ? `<p style="font-size:0.8rem;color:#4caf50"><strong>Resistente:</strong> ${p.resistances.join(', ')}</p>` : ''}
                ${p.evolutionInfo ? `<p style="font-size:0.8rem;color:var(--muted)">${p.evolutionInfo}</p>` : ''}
            </div>
        </div>
    </div>`;
    document.body.appendChild(modal);
}

async function registerAndShow(number) {
    await registerPokedex(number);
    if (!TRAINER_DATA.pokedex_seen) TRAINER_DATA.pokedex_seen = [];
    if (!TRAINER_DATA.pokedex_seen.includes(number)) TRAINER_DATA.pokedex_seen.push(number);
    renderPlayerPokedex();
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="pokedex"]')?.addEventListener('click', loadFullPokedex);
});

// ============================================
// TEAM MANAGEMENT
// ============================================
function addPokemon(slot) {
    document.getElementById('poke-slot').value = slot;
    clearPokemonForm();
    // Primeiro Pokémon do treinador começa nível 5
    if (playerTeam.length === 0) {
        const lvInput = document.getElementById('poke-level');
        if (lvInput) lvInput.value = 5;
    }
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
    
    // Show stat points if available
    const statPoints = pokemon.statPointsAvailable || 0;
    const statSection = document.getElementById('poke-stat-points-section');
    if (statPoints > 0) {
        statSection.classList.remove('hidden');
        document.getElementById('poke-stat-points-available').textContent = statPoints;
    } else {
        statSection.classList.add('hidden');
    }
    
    // Show XP bar
    const totalXp = pokemon.totalXp || 0;
    const level = pokemon.level || 1;
    const xpForCurrent = Math.pow(level, 3);
    const xpForNext = Math.pow(level + 1, 3);
    const xpInLevel = totalXp - xpForCurrent;
    const xpNeeded = xpForNext - xpForCurrent;
    const pct = level >= 100 ? 100 : Math.min(100, Math.max(0, (xpInLevel / xpNeeded) * 100));
    document.getElementById('poke-xp-bar').style.width = `${pct}%`;
    document.getElementById('poke-xp-text').textContent = level >= 100 ? 'MAX' : `${totalXp} / ${xpForNext} XP (próx. nível)`;
    
    // Store current editing slot for stat distribution
    window._editingPokeSlot = slot;
    
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
    
    // Preserve existing XP/stat data if editing
    const existingPoke = (slot < playerTeam.length) ? playerTeam[slot] : {};
    
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
        types: [],
        // Preserve XP/Level data
        xp: existingPoke.xp || 0,
        totalXp: existingPoke.totalXp || 0,
        xpToNext: existingPoke.xpToNext || 0,
        statPointsAvailable: existingPoke.statPointsAvailable || 0,
        baseHp: existingPoke.baseHp || 0
    };
    // Auto-fill from API — get level-scaled + nature-adjusted stats
    try {
        const response = await fetch(`/api/pokemon?search=${encodeURIComponent(pokemon.name.toLowerCase())}`);
        const results = await response.json();
        if (results.length > 0) {
            const r = results[0];
            pokemon.types = r.types;
            pokemon.number = r.number;
            if (!pokemon.baseHp) pokemon.baseHp = r.hp;

            // Fetch scaled stats with nature applied
            try {
                const scaledRes = await fetch('/api/pokemon/stats', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ number: r.number, level: pokemon.level, nature: pokemon.nature || '' })
                });
                const scaled = await scaledRes.json();
                if (!scaled.error) {
                    pokemon.maxHp     = scaled.maxHp || scaled.hp || r.hp;
                    pokemon.currentHp = pokemon.currentHp || pokemon.maxHp;
                    pokemon.ac        = scaled.ac || r.ac;
                    // Overwrite stats with nature-scaled values (ATK/DEF/SPA/SPD/SPE)
                    pokemon.stats = Object.assign(pokemon.stats || {}, scaled.stats || {});
                    pokemon.proficiency = scaled.proficiency;
                    pokemon.stab        = scaled.stab;
                    // Store nature effect for display
                    pokemon.natureBoost = scaled.nature_boost || null;
                    pokemon.natureLower = scaled.nature_lower || null;
                }
            } catch(e2) {
                // Fallback: use raw base stats
                if (!pokemon.maxHp || pokemon.maxHp === 0) { pokemon.maxHp = r.hp; pokemon.currentHp = r.hp; }
                if (pokemon.ac === 10) pokemon.ac = r.ac;
            }
        }
    } catch(e) {}
    if (slot < playerTeam.length) playerTeam[slot] = pokemon;
    else playerTeam.push(pokemon);
    await saveTeam();
    closePokemonModal();
    refreshTeamDisplay();
}

function closePokemonModal() { hideElement('pokemon-edit-modal'); }

// ============================================
// BATTLE VFX & SOUNDS
// ============================================
let _audioCtx = null;
function getAudioCtx() {
    if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return _audioCtx;
}

function playSound(type) {
    try {
        const ctx = getAudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        const now = ctx.currentTime;

        if (type === 'hit') {
            osc.type = 'square';
            osc.frequency.setValueAtTime(220, now);
            osc.frequency.exponentialRampToValueAtTime(110, now + 0.12);
            gain.gain.setValueAtTime(0.18, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
            osc.start(now); osc.stop(now + 0.15);
        } else if (type === 'faint') {
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(300, now);
            osc.frequency.exponentialRampToValueAtTime(60, now + 0.6);
            gain.gain.setValueAtTime(0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.65);
            osc.start(now); osc.stop(now + 0.65);
        } else if (type === 'catch') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(440, now);
            osc.frequency.setValueAtTime(550, now + 0.12);
            osc.frequency.setValueAtTime(660, now + 0.25);
            gain.gain.setValueAtTime(0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
            osc.start(now); osc.stop(now + 0.4);
        } else if (type === 'levelup') {
            osc.type = 'sine';
            [392, 494, 587, 784].forEach((f, i) => osc.frequency.setValueAtTime(f, now + i * 0.1));
            gain.gain.setValueAtTime(0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
            osc.start(now); osc.stop(now + 0.5);
        } else if (type === 'run') {
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(600, now);
            osc.frequency.exponentialRampToValueAtTime(200, now + 0.25);
            gain.gain.setValueAtTime(0.12, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
            osc.start(now); osc.stop(now + 0.28);
        } else if (type === 'status') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(180, now);
            osc.frequency.setValueAtTime(160, now + 0.15);
            gain.gain.setValueAtTime(0.1, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
            osc.start(now); osc.stop(now + 0.3);
        }
    } catch(e) { /* audio not available */ }
}

// ── Battle panel switcher (menu / moves / extra) ──────────────
function showBattlePanel(panel) {
    const menu  = document.getElementById('poke-main-menu');
    const moves = document.getElementById('poke-moves-panel');
    const extra = document.getElementById('poke-extra-panel');
    const toggle = document.getElementById('poke-extras-toggle');
    if (!menu) return;
    menu.classList.add('hidden');
    if (moves) moves.classList.add('hidden');
    if (extra) extra.classList.add('hidden');
    if (panel === 'menu')  { menu.classList.remove('hidden'); }
    if (panel === 'moves') { if (moves) moves.classList.remove('hidden'); }
    if (panel === 'extra') { if (extra) extra.classList.remove('hidden'); }
    if (toggle) toggle.style.display = panel === 'extra' ? 'none' : '';
}

// ── Battle transition animation ───────────────────────────────
function playBattleTransition() {
    return new Promise(resolve => {
        const el = document.getElementById('battle-transition');
        if (!el) { resolve(); return; }
        el.classList.remove('hidden', 'phase-spin', 'phase-flash', 'phase-poke');

        // Phase 1 — spinning lines (200ms)
        setTimeout(() => el.classList.add('phase-spin'), 10);
        // Phase 2 — white flash (400ms)
        setTimeout(() => {
            el.classList.remove('phase-spin');
            el.classList.add('phase-flash');
        }, 220);
        // Phase 3 — pokeball (600ms)
        setTimeout(() => {
            el.classList.remove('phase-flash');
            el.classList.add('phase-poke');
        }, 440);
        // Done — hide overlay
        setTimeout(() => {
            el.classList.remove('phase-poke');
            el.classList.add('hidden');
            resolve();
        }, 900);
    });
}

function battleSpriteEnter(spriteId, side) {
    const el = document.getElementById(spriteId);
    if (!el) return;
    el.classList.remove('enter-left', 'enter-right', 'hit-flash', 'faint-anim');
    void el.offsetWidth; // reflow
    el.classList.add(side === 'enemy' ? 'enter-left' : 'enter-right');
    el.addEventListener('animationend', () => el.classList.remove('enter-left', 'enter-right'), { once: true });
}

function battleSpriteHit(spriteId) {
    const el = document.getElementById(spriteId);
    if (!el) return;
    el.classList.remove('hit-flash');
    void el.offsetWidth;
    el.classList.add('hit-flash');
    el.addEventListener('animationend', () => el.classList.remove('hit-flash'), { once: true });
}

function battleSpriteFaint(spriteId) {
    const el = document.getElementById(spriteId);
    if (!el) return;
    el.classList.add('faint-anim');
}

function hpBarShake(barContainerEl) {
    if (!barContainerEl) return;
    barContainerEl.classList.remove('hp-shake');
    void barContainerEl.offsetWidth;
    barContainerEl.classList.add('hp-shake');
    barContainerEl.addEventListener('animationend', () => barContainerEl.classList.remove('hp-shake'), { once: true });
}

function setHpBar(barId, current, max) {
    const el = document.getElementById(barId);
    if (!el) return;
    // Bar shows 0% when negative (dead), but HP text shows the real negative number
    const pct = max > 0 ? Math.max(0, Math.min(100, (current / max) * 100)) : 0;
    el.style.width = pct + '%';
    el.classList.remove('hp-mid', 'hp-low');
    if (current <= -30) el.classList.add('hp-low'); // permadeath zone — pulse red
    else if (current <= 0) el.classList.add('hp-low');
    else if (pct <= 20) el.classList.add('hp-low');
    else if (pct <= 50) el.classList.add('hp-mid');
}

async function saveTeam() {
    await fetch('/player/team', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team: playerTeam })
    });
}

async function pokemonCenter() {
    const btn = document.getElementById('pokemon-center-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Curando...'; }
    try {
        const res = await fetch('/player/pokemon-center', { method: 'POST' });
        if (!res.ok) { throw new Error(`HTTP ${res.status}: ${await res.text()}`); }
        const data = await res.json();
        if (data.ok) {
            playerTeam = data.team;
            refreshTeamDisplay();
            const msg = document.getElementById('pokemon-center-msg');
            if (msg) { msg.textContent = '✅ Todos os seus Pokémon foram curados!'; msg.style.color = 'var(--green)'; }
        }
    } catch(e) {
        console.error('Pokemon Center error:', e);
        const msg = document.getElementById('pokemon-center-msg');
        if (msg) { msg.textContent = `❌ Erro: ${e.message}`; msg.style.color = 'var(--red)'; }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🏥 Curar Equipe'; }
    }
}

const NATURE_MODIFIERS_JS = {
    'Adamant':{'ATK':1.1,'SPA':0.9},'Modest':{'SPA':1.1,'ATK':0.9},
    'Jolly':{'SPE':1.1,'SPA':0.9},'Timid':{'SPE':1.1,'ATK':0.9},
    'Bold':{'DEF':1.1,'ATK':0.9},'Impish':{'DEF':1.1,'SPA':0.9},
    'Calm':{'SPD':1.1,'ATK':0.9},'Careful':{'SPD':1.1,'SPA':0.9},
    'Brave':{'ATK':1.1,'SPE':0.9},'Quiet':{'SPA':1.1,'SPE':0.9},
    'Relaxed':{'DEF':1.1,'SPE':0.9},'Sassy':{'SPD':1.1,'SPE':0.9},
    'Lonely':{'ATK':1.1,'DEF':0.9},'Naughty':{'ATK':1.1,'SPD':0.9},
    'Mild':{'SPA':1.1,'DEF':0.9},'Rash':{'SPA':1.1,'SPD':0.9},
    'Lax':{'DEF':1.1,'SPD':0.9},'Gentle':{'SPD':1.1,'DEF':0.9},
    'Hasty':{'SPE':1.1,'DEF':0.9},'Naive':{'SPE':1.1,'SPD':0.9},
};

function getNatureLabel(poke) {
    const nature = poke.nature || '';
    if (!nature) return '';
    const mods = NATURE_MODIFIERS_JS[nature];
    if (!mods) return `<small style="color:var(--muted);">🌿 ${nature}</small>`;
    const boost = Object.entries(mods).find(([,v]) => v > 1);
    const lower = Object.entries(mods).find(([,v]) => v < 1);
    const boostStr = boost ? `<span style="color:#4caf50;">+${boost[0]}</span>` : '';
    const lowerStr = lower ? `<span style="color:#f44336;">-${lower[0]}</span>` : '';
    return `<small style="color:var(--muted);">🌿 ${nature} ${boostStr}${boostStr&&lowerStr?' / ':''}${lowerStr}</small>`;
}

function getLevelEvoIndicator(poke, idx) {
    const info = poke.evolutionInfo || '';
    if (!info) return '';
    const match = info.match(/evolve into ([A-Za-z\-\s]+?) at (?:trainer )?level (\d+)/i);
    if (!match) return '';
    const evoInto = match[1].trim();
    const evoLevel = parseInt(match[2]);
    const pokeEvoLevel = evoLevel * 5;
    const currentLevel = poke.level || 1;
    if (currentLevel < pokeEvoLevel) return '';
    return `<button class="btn btn-sm" style="background:var(--accent);color:#fff;animation:pvp-blink 1s infinite;" onclick="triggerLevelEvolve(${idx})" title="Nível ${currentLevel} ≥ ${pokeEvoLevel}">⬆️ Evoluir → ${evoInto}!</button>`;
}

async function triggerLevelEvolve(idx) {
    try {
        const res = await fetch('/player/level-evolve', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({slot: idx})
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        if (data.evolved) {
            playerTeam[idx] = data.pokemon;
            refreshTeamDisplay();
            alert(`✨ ${data.old_name} evoluiu para ${data.pokemon.name}!`);
        } else {
            alert(data.message || 'Não foi possível evoluir agora.');
        }
    } catch(e) { alert('Erro ao evoluir: ' + e.message); }
}

const TYPE_COLORS = {
    normal:'#a8a878',fire:'#f08030',water:'#6890f0',grass:'#78c850',electric:'#f8d030',
    ice:'#98d8d8',fighting:'#c03028',poison:'#a040a0',ground:'#e0c068',flying:'#a890f0',
    psychic:'#f85888',bug:'#a8b820',rock:'#b8a038',ghost:'#705898',dragon:'#7038f8',
    dark:'#705848',steel:'#b8b8d0',fairy:'#ee99ac'
};

function getPokemonSpriteUrl(poke, isShiny) {
    const num = typeof poke === 'number' ? poke : (poke?.number || 0);
    if (!num) return '';
    const padded = String(num).padStart(3, '0');
    const ext = num <= 649 ? 'gif' : 'png';
    return `/static/sprites/${padded}.${ext}`;
}

function getStatusIcon(condition) {
    const icons = { queimado:'🔥', envenenado:'🟣', badly_poisoned:'🟣', paralisado:'⚡', dormindo:'💤', congelado:'🧊', confuso:'💫' };
    return icons[condition] || '❓';
}

function hpBarClass(current, max) {
    const pct = max > 0 ? (current / max) * 100 : 0;
    if (pct <= 20) return 'hp-low';
    if (pct <= 50) return 'hp-mid';
    return '';
}

function refreshTeamDisplay() {
    const grid = document.getElementById('team-grid');
    grid.innerHTML = '';
    for (let i = 0; i < 6; i++) {
        const slot = document.createElement('div');
        slot.className = 'team-slot';
        if (i < playerTeam.length && playerTeam[i]) {
            const poke = playerTeam[i];
            const totalXp   = poke.totalXp || 0;
            const xpForNext = Math.pow((poke.level || 1) + 1, 3);
            const xpForCur  = Math.pow(poke.level || 1, 3);
            const xpPct     = poke.level >= 100 ? 100 : Math.min(100, ((totalXp - xpForCur) / (xpForNext - xpForCur)) * 100);
            const hasPoints = (poke.statPointsAvailable || 0) > 0;
            const type1     = (poke.types?.[0] || '').toLowerCase();
            const type2     = (poke.types?.[1] || '').toLowerCase();
            const col1      = TYPE_COLORS[type1] || '#3b4cca';
            const col2      = TYPE_COLORS[type2] || col1;
            const hpPct     = poke.maxHp > 0 ? Math.max(0, Math.min(100, (poke.currentHp / poke.maxHp) * 100)) : 0;
            const hpClass   = hpBarClass(poke.currentHp, poke.maxHp);
            const spriteUrl = getPokemonSpriteUrl(poke);
            const isShiny   = poke.isShiny || false;
            const isFainted = (poke.currentHp || 0) <= 0;
            const statusCond = poke.status?.condition || null;
            const statusIcon = statusCond ? getStatusIcon(statusCond) : '';

            // HP bar fill color based on percentage
            const hpFill = hpPct <= 20 ? '#e63946' : hpPct <= 50 ? '#f5a623' : col1;

            slot.innerHTML = `
                <div class="pkcard ${isFainted ? 'pkcard--fainted' : ''} ${isShiny ? 'pkcard--shiny' : ''}"
                     style="--c1:${col1};--c2:${col2};--hp-fill:${hpFill}">

                    <!-- Glowing top stripe -->
                    <div class="pkcard__stripe"></div>

                    <!-- Shiny sparkle overlay -->
                    ${isShiny ? '<div class="pkcard__shiny-overlay"></div>' : ''}

                    <!-- Sprite area -->
                    <div class="pkcard__sprite-wrap">
                        ${spriteUrl
                            ? `<img src="${spriteUrl}" class="pkcard__sprite ${isShiny ? 'pkcard__sprite--shiny' : ''}" onerror="this.style.display='none'" loading="lazy">`
                            : `<div class="pkcard__no-sprite">?</div>`}
                        ${isFainted ? '<div class="pkcard__faint-overlay">😵</div>' : ''}
                        ${statusCond ? `<div class="pkcard__status-float">${statusIcon}</div>` : ''}
                    </div>

                    <!-- Info -->
                    <div class="pkcard__info">
                        <div class="pkcard__nameline">
                            <span class="pkcard__name">${poke.nickname || poke.name}</span>
                            <span class="pkcard__level">Nv.${poke.level}</span>
                        </div>
                        <div class="type-badges pkcard__types">${formatTypes(poke.types || [])}</div>

                        <!-- HP bar -->
                        <div class="pkcard__hp-row">
                            <span class="pkcard__hp-label">HP</span>
                            <div class="pkcard__hp-track">
                                <div class="pkcard__hp-fill ${hpClass}" style="width:${hpPct}%"></div>
                            </div>
                            <span class="pkcard__hp-num">${poke.currentHp}/${poke.maxHp}</span>
                        </div>

                        <!-- XP bar -->
                        <div class="pkcard__xp-track">
                            <div class="pkcard__xp-fill" style="width:${xpPct}%"></div>
                        </div>
                        <div class="pkcard__xp-label">${poke.level >= 100 ? '✨ MAX' : `XP ${totalXp}/${xpForNext}`}</div>

                        <!-- Extras: AC, nature, stat points, evo -->
                        <div class="pkcard__meta">
                            <span>AC ${poke.ac || '?'}</span>
                            ${getNatureLabel(poke)}
                            ${hasPoints ? `<span style="color:var(--accent);">⬆️ ${poke.statPointsAvailable}pts</span>` : ''}
                        </div>
                        ${getLevelEvoIndicator(poke, i)}
                    </div>

                    <!-- Hover reveal: actions -->
                    <div class="pkcard__actions">
                        <button class="pkcard__btn" onclick="editPokemon(${i})">✏️ Editar</button>
                        <button class="pkcard__btn" onclick="openUseStoneModal(${i})" title="Pedra de evolução">💎</button>
                        ${(poke.battle_wins||0) >= 10
                            ? `<button class="pkcard__btn pkcard__btn--gold" onclick="friendshipEvolve(${i})" title="${poke.battle_wins} batalhas">💛 Evoluir</button>`
                            : `<span class="pkcard__btn pkcard__btn--muted" title="Batalhas vencidas">💛 ${poke.battle_wins||0}/10</span>`}
                        <button class="pkcard__btn pkcard__btn--danger" onclick="removePokemon(${i})">✕</button>
                    </div>
                </div>`;
        } else {
            slot.innerHTML = `
                <div class="pkcard pkcard--empty" onclick="addPokemon(${i})">
                    <span class="pkcard__add-icon">＋</span>
                    <span class="pkcard__add-label">Adicionar Pokémon</span>
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
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    set('poke-species', pokemon.name);
    const results = document.getElementById('poke-species-results');
    if (results) results.innerHTML = '';
    if (pokemon.stats) {
        set('poke-str', pokemon.stats.ATK || pokemon.stats.STR || 10);
        set('poke-dex', pokemon.stats.DEF || pokemon.stats.DEX || 10);
        set('poke-con', pokemon.stats.SPA || pokemon.stats.CON || 10);
        set('poke-int', pokemon.stats.SPD || pokemon.stats.INT || 10);
        set('poke-wis', pokemon.stats.SPE || pokemon.stats.WIS || 10);
        set('poke-cha', pokemon.stats.HP  || pokemon.stats.CHA  || 10);
    }
    set('poke-max-hp', pokemon.hp || 0);
    set('poke-current-hp', pokemon.hp || 0);
    set('poke-ac', pokemon.ac || 10);
    set('poke-hit-dice', pokemon.hitDice || '');
    set('poke-speed', pokemon.speed || '');
    if (pokemon.startingMoves) set('poke-moves', pokemon.startingMoves.join(', '));
    if (pokemon.ability)       set('poke-ability', pokemon.ability.name || '');
    if (pokemon.hiddenAbility) set('poke-hidden-ability', pokemon.hiddenAbility.name || '');
    if (pokemon.vulnerabilities) set('poke-vulnerabilities', pokemon.vulnerabilities.join(', '));
    if (pokemon.resistances)     set('poke-resistances', pokemon.resistances.join(', '));
    if (pokemon.savingThrows)    set('poke-saves', pokemon.savingThrows.join(', '));
}

// ============================================
// TRAINER DATA SAVE
// ============================================
async function saveBag() {
    try {
        await fetch('/player/trainer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bag: window.bagItems || [] })
        });
        renderBagGrid();
    } catch(e) {}
}

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
                'normal': '🌿 <strong>Normal:</strong> Pokémon variados, de metade do seu nível até +5. Shiny: 1%.',
                'dungeon': '🏰 <strong>Dungeon:</strong> Pokémon raros e evoluídos, -5 a +15 níveis. Shiny: 3%. ⚠️ Perigoso!',
                'night': '🌙 <strong>Noturno:</strong> O terror da noite! Pokémon +10 a +30 níveis acima. Shiny: 5%. ☠️ Extremamente perigoso!'
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
    // Trapping moves — player cannot switch
    if (window._playerTrapped) {
        addBattleLog(`🔒 Não pode trocar! ${window._playerTrappedBy || 'Trapping move'} está impedindo a troca!`);
        return;
    }
    
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
    setHpBar('battle-player-hp-bar-full', pHp, pMax);
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

    // Intimidate: if new Pokémon has Intimidate, reduce enemy ATK
    const newAbility = (newPoke.ability || '').toLowerCase();
    if (newAbility === 'intimidate') {
        window._wildIntimidateMod = (window._wildIntimidateMod || 0) - 2;
        addBattleLog(`😤 <strong>Intimidate!</strong> ${newPoke.nickname || newPoke.name} reduziu o ATK do inimigo em 2 estágios!`);
    }
    // Natural Cure: if previous poke had Natural Cure, clear its status
    const prevAbility = (window.currentBattleData?.playerPokemon?.ability || '').toLowerCase();
    if (prevAbility === 'natural cure' && window._playerStatus) {
        window._playerStatus = null;
        addBattleLog(`💚 <strong>Natural Cure</strong> curou o status ao trocar!`);
    }
    // Regenerator: heal 1/3 HP when switching out
    if (prevAbility === 'regenerator') {
        const prevPoke = window.currentBattleData.playerPokemon;
        const healAmt = Math.max(1, Math.floor((prevPoke.maxHp || prevPoke.hp || 20) / 3));
        const prevTeamSlot = playerTeam.findIndex(p => (p.name === prevPoke.name || p.nickname === prevPoke.nickname));
        if (prevTeamSlot >= 0) {
            playerTeam[prevTeamSlot].currentHp = Math.min(playerTeam[prevTeamSlot].maxHp, (playerTeam[prevTeamSlot].currentHp || 0) + healAmt);
            addBattleLog(`♻️ <strong>Regenerator!</strong> ${prevPoke.nickname || prevPoke.name} recuperou ${healAmt} HP!`);
            refreshTeamDisplay();
        }
    }

    // Reset faint flag so next battle_update doesn't re-trigger the faint message
    window._playerFaintLogged = false;

    // Switching uses the action - pass turn. Send new poke's HP so server updates battle_state.
    socket.emit('battle_action', {
        action_by: 'player', action_type: 'switch',
        move_name: `Trocou → ${newPoke.name}`, damage: 0, message: 'Troca de Pokémon',
        new_pokemon_hp: pHp, new_pokemon_max_hp: pMax
    });
    
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
// PVP ARENA SYSTEM (Full Battle UI)
// ============================================
window.pvpState = { inArena: false, battleId: null, youAre: null, battleData: null };

// Join arena when tab is clicked
document.addEventListener('DOMContentLoaded', () => {
    const pvpTab = document.querySelector('[data-tab="pvp"]');
    if (pvpTab) {
        pvpTab.addEventListener('click', () => {
            if (!window.pvpState.inArena) {
                socket.emit('pvp_join_arena', {});
                window.pvpState.inArena = true;
            }
            loadTransferTargets();
        });
    }
});

// Receive player list
socket.on('pvp_arena_players', (players) => {
    renderPvpPlayers(players);
});

socket.on('pvp_player_joined', () => {
    socket.emit('pvp_join_arena', {});
});

function renderPvpPlayers(players) {
    const container = document.getElementById('pvp-players-list');
    if (!container) return;
    if (players.length === 0) {
        container.innerHTML = '<p class="empty-state">Nenhum jogador disponível.</p>';
        return;
    }
    container.innerHTML = players.map(p => {
        const isSelf = (p.name === TRAINER_DATA.name);
        return `
            <div class="pvp-player-card ${isSelf ? 'is-self' : ''}">
                <span class="pvp-player-name">${p.name}</span>
                <span class="pvp-player-level">Nv.${p.level} | ${p.team_size} Pokémon</span>
                ${!isSelf ? `
                    <div style="display:flex;gap:0.3rem;margin-top:0.3rem;">
                        <button class="btn btn-sm btn-danger" onclick="sendPvpChallenge('${p.id}', '${p.name}', 'official')">⚔️ Oficial</button>
                        <button class="btn btn-sm btn-warning" onclick="sendPvpChallenge('${p.id}', '${p.name}', 'street')">🥊 Rua</button>
                    </div>
                ` : '<span style="color:var(--success);font-size:0.75rem;">Você</span>'}
            </div>
        `;
    }).join('');
}

function sendPvpChallenge(targetId, targetName, mode) {
    const team = playerTeam || [];
    if (team.length === 0) {
        alert('Você precisa ter pelo menos 1 Pokémon no time!');
        return;
    }
    let betMoney = 0;
    let betItems = [];
    if (mode === 'official') {
        const bet = prompt('Quanto quer apostar em ₽? (0 para nenhuma aposta)');
        if (bet === null) return;
        betMoney = parseInt(bet) || 0;
        if (betMoney > (TRAINER_DATA.money || 0)) {
            alert(`Você só tem ₽${TRAINER_DATA.money}!`);
            return;
        }
    }
    socket.emit('pvp_challenge', { target_id: targetId, mode, bet_money: betMoney, bet_items: betItems });
    addPvpLog(`⚔️ Desafio ${mode === 'official' ? 'Oficial' : 'de Rua'} enviado para ${targetName}!${betMoney > 0 ? ` Aposta: ₽${betMoney}` : ''}`);
}

// Receive challenge
socket.on('pvp_challenge_received', (data) => {
    const container = document.getElementById('pvp-challenges');
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    
    const modeLabel = data.mode === 'official' ? '⚔️ Oficial' : '🥊 Rua';
    container.innerHTML += `
        <div class="pvp-challenge-card" id="challenge-${data.challenger_id}">
            <div class="pvp-challenge-info">
                <strong>${modeLabel} — ${data.challenger_name}</strong> (Nv.${data.challenger_level}) te desafiou!
                ${data.bet_money > 0 ? `<span style="color:var(--accent);font-size:0.8rem;">Aposta: ₽${data.bet_money}</span>` : ''}
            </div>
            <div class="pvp-challenge-actions">
                <button class="btn btn-sm btn-success" onclick="acceptPvpChallenge('${data.challenger_id}', '${data.challenger_name}', '${data.mode}', ${data.bet_money})">✓ Aceitar</button>
                <button class="btn btn-sm btn-danger" onclick="declinePvpChallenge('${data.challenger_id}')">✕ Recusar</button>
            </div>
        </div>
    `;
    playNotificationSound();
});

function acceptPvpChallenge(challengerId, challengerName, mode, betMoney) {
    if (mode === 'official' && betMoney > 0) {
        if ((TRAINER_DATA.money || 0) < betMoney) {
            alert(`Você precisa de ₽${betMoney} para aceitar este desafio!`);
            return;
        }
    }
    socket.emit('pvp_accept', { challenger_id: challengerId, challenger_name: challengerName, mode, bet_money: betMoney });
    document.getElementById(`challenge-${challengerId}`)?.remove();
}

function declinePvpChallenge(challengerId) {
    socket.emit('pvp_decline', { challenger_id: challengerId });
    document.getElementById(`challenge-${challengerId}`)?.remove();
}

socket.on('pvp_challenge_declined', (data) => {
    addPvpLog(`❌ ${data.decliner_name} recusou seu desafio.`);
});

// ============================================
// PVP BATTLE - SELECTION PHASE
// ============================================
socket.on('pvp_battle_created', (data) => {
    window.pvpState.battleId = data.battle_id;
    window.pvpState.youAre = data.you_are;
    
    const area = document.getElementById('pvp-battle-area');
    const content = document.getElementById('pvp-battle-content');
    area.classList.remove('hidden');
    
    const modeLabel = data.mode === 'official' ? '⚔️ Batalha Oficial' : '🥊 Batalha de Rua';
    const team = data.your_team || [];
    
    content.innerHTML = `
        <div style="text-align:center;padding:1rem;">
            <h3>${modeLabel} vs ${data.opponent_name}</h3>
            <p style="color:var(--warning);margin:1rem 0;">🔒 Seleção Cega — Escolha seu primeiro Pokémon. Seu oponente não verá sua escolha até ambos confirmarem.</p>
            <div class="pvp-selection-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:0.75rem;margin:1rem 0;">
                ${team.map((p, i) => `
                    <div class="pvp-select-card" onclick="pvpSelectPokemon(${i})" id="pvp-select-${i}" 
                         style="background:var(--darker);border:2px solid var(--card-border);border-radius:var(--radius);padding:0.75rem;text-align:center;cursor:pointer;transition:all 0.2s;">
                        <img src="${getPokemonSpriteUrl(p.number || 0)}" width="48" height="48" style="image-rendering:pixelated;">
                        <div style="font-weight:bold;">${p.nickname || p.name}</div>
                        <div style="font-size:0.8rem;color:var(--text-muted);">Nv.${p.level} | HP:${p.currentHp || p.maxHp}/${p.maxHp}</div>
                        <div class="type-badges" style="justify-content:center;">${formatTypes(p.types || [])}</div>
                    </div>
                `).join('')}
            </div>
            <button class="btn btn-primary btn-lg" id="pvp-confirm-btn" onclick="pvpConfirmSelection()" disabled>
                Confirmar Pokémon Selecionado
            </button>
        </div>
    `;
    
    // Switch to PVP tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector('[data-tab="pvp"]').classList.add('active');
    document.getElementById('tab-pvp').classList.add('active');
});

window._pvpSelectedIdx = null;

function pvpSelectPokemon(idx) {
    // Deselect previous
    document.querySelectorAll('.pvp-select-card').forEach(c => c.style.borderColor = 'var(--card-border)');
    // Select this one
    document.getElementById(`pvp-select-${idx}`).style.borderColor = 'var(--accent)';
    window._pvpSelectedIdx = idx;
    document.getElementById('pvp-confirm-btn').disabled = false;
}

function pvpConfirmSelection() {
    if (window._pvpSelectedIdx === null) return;
    socket.emit('pvp_select_pokemon', {
        battle_id: window.pvpState.battleId,
        pokemon_idx: window._pvpSelectedIdx
    });
    document.getElementById('pvp-battle-content').innerHTML = `
        <div style="text-align:center;padding:2rem;">
            <h3>⏳ Aguardando oponente escolher...</h3>
            <p style="color:var(--text-muted);">Seu Pokémon foi selecionado. A batalha começará assim que o oponente confirmar.</p>
        </div>
    `;
}

socket.on('pvp_waiting', (data) => {
    // Already handled by pvpConfirmSelection
});

// ============================================
// PVP BATTLE - BATTLE PHASE (Real-time state updates)
// ============================================

// ── PVP Turn Countdown ──────────────────────────────────────
let _pvpTimerInterval = null;
let _pvpTimerSeconds  = 20;

function startPvpTimer() {
    clearPvpTimer();
    _pvpTimerSeconds = 20;
    _pvpTimerInterval = setInterval(() => {
        _pvpTimerSeconds--;
        const el = document.getElementById('pvp-turn-timer');
        if (!el) { clearPvpTimer(); return; }

        el.textContent = _pvpTimerSeconds;

        // Colour progression
        el.classList.remove('timer-green', 'timer-yellow', 'timer-red', 'timer-panic');
        if (_pvpTimerSeconds > 10)      el.classList.add('timer-green');
        else if (_pvpTimerSeconds > 5)  el.classList.add('timer-yellow');
        else                            el.classList.add('timer-red');

        // Panic effect in last 5 s
        if (_pvpTimerSeconds <= 5) el.classList.add('timer-panic');

        if (_pvpTimerSeconds <= 0) {
            clearPvpTimer();
            pvpPassTurn(); // auto-pass when time runs out
        }
    }, 1000);
}

function clearPvpTimer() {
    if (_pvpTimerInterval) { clearInterval(_pvpTimerInterval); _pvpTimerInterval = null; }
}
// ────────────────────────────────────────────────────────────

function renderPvpBattle(state) {
    const content = document.getElementById('pvp-battle-content');
    if (!content) return;
    
    const isMyTurn = state.turn === state.you_are;
    const myTeam = state.your_team || [];
    const myActive = myTeam[state.your_active_idx] || {};
    const opponent = state.opponent_active || {};
    const myHpPct = myActive.maxHp ? (myActive.currentHp / myActive.maxHp * 100) : 100;
    const oppHpPct = opponent.maxHp ? (opponent.currentHp / opponent.maxHp * 100) : 100;
    
    // Build moves
    const moves = myActive.moves || [];
    
    content.innerHTML = `
        <div class="battle-field-full">
            <!-- Opponent Side -->
            <div class="battle-side-full enemy-side">
                <h3>🔴 Oponente</h3>
                <div class="battle-pokemon-full">
                    <img src="${getPokemonSpriteUrl(opponent.number || 0)}" class="battle-sprite" id="pvp-opp-sprite">
                    <h4>${opponent.nickname || opponent.name || '???'} Nv.${opponent.level || '?'}</h4>
                    <div class="type-badges" style="justify-content:center;">${formatTypes(opponent.types || [])}</div>
                    <div class="hp-bar-container" id="pvp-opp-hpbar">
                        <div class="hp-bar enemy-hp ${hpBarClass(opponent.currentHp, opponent.maxHp)}" style="width:${oppHpPct}%"></div>
                    </div>
                    <span class="hp-text">${opponent.currentHp || '?'}/${opponent.maxHp || '?'} HP</span>
                    <div class="battle-stats-mini">
                        <span>AC: ${opponent.ac || '?'}</span>
                        <span>SPD: ${opponent.speed || '?'}</span>
                    </div>
                    ${opponent.stats ? `<div class="mini-stats" style="justify-content:center;margin-top:0.3rem;">${Object.entries(opponent.stats).map(([k,v]) => `<span>${k}:${v}</span>`).join('')}</div>` : ''}
                </div>
                <p style="text-align:center;font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem;">Pokémon restantes: ${state.opponent_alive_count || '?'}</p>
            </div>
            
            <!-- VS -->
            <div class="battle-vs">${isMyTurn ? '⚡' : '⏳'}</div>
            
            <!-- Your Side -->
            <div class="battle-side-full player-side">
                <h3>🟢 Seu Pokémon</h3>
                <div class="battle-pokemon-full">
                    <img src="${getPokemonSpriteUrl(myActive.number || 0)}" class="battle-sprite" id="pvp-my-sprite">
                    <h4>${myActive.nickname || myActive.name || '???'} Nv.${myActive.level || '?'}</h4>
                    <div class="type-badges" style="justify-content:center;">${formatTypes(myActive.types || [])}</div>
                    ${state.your_status ? `<div class="status-badge status-${state.your_status.condition}">${getStatusIcon(state.your_status.condition)} ${state.your_status.condition.toUpperCase()}</div>` : ''}
                    <div class="hp-bar-container" id="pvp-my-hpbar">
                        <div class="hp-bar player-hp ${hpBarClass(myActive.currentHp, myActive.maxHp)}" style="width:${myHpPct}%"></div>
                    </div>
                    <span class="hp-text">${myActive.currentHp || 0}/${myActive.maxHp || 0} HP</span>
                    <div class="battle-stats-mini">
                        <span>AC: ${myActive.ac || 10}</span>
                        <span>SPD: ${myActive.speed || '30ft'}</span>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Turn Indicator + Countdown -->
        <div style="text-align:center;margin:0.75rem 0;">
            <span class="turn-indicator" style="font-size:1rem;padding:0.5rem 1.5rem;">
                ${isMyTurn ? '🟢 SEU TURNO — Escolha uma ação!' : '🔴 Turno do Oponente — Aguarde...'}
                ${isMyTurn ? '<span id="pvp-turn-timer" class="timer-green">20</span>' : ''}
            </span>
            <span style="display:block;margin-top:0.3rem;font-size:0.8rem;color:var(--text-muted);">Round ${state.round || 1}</span>
        </div>
        
        <!-- Actions (only if my turn) -->
        <div style="text-align:center;margin:1rem 0;">
            <h4 style="color:var(--accent);margin-bottom:0.5rem;">Moves:</h4>
            <div class="battle-moves-list" style="justify-content:center;gap:0.5rem;">
                ${moves.map(m => `
                    <span class="move-btn selectable-move" style="${isMyTurn ? '' : 'opacity:0.4;pointer-events:none;'}"
                          onclick="pvpUseMove('${m.replace(/'/g, "\\'")}')">
                        ${m}
                    </span>
                `).join('')}
            </div>
        </div>
        
        <!-- Dice + Extra actions -->
        <div class="dice-section" style="margin:1rem 0;">
            <div class="dice-buttons">
                <button class="btn btn-dice" onclick="pvpRollDice(20)">d20</button>
                <button class="btn btn-dice" onclick="pvpRollDice(6)">d6</button>
                <button class="btn btn-dice" onclick="pvpRollDice(8)">d8</button>
                <button class="btn btn-dice" onclick="pvpRollDice(10)">d10</button>
                <button class="btn btn-dice" onclick="pvpRollDice(12)">d12</button>
            </div>
            <div id="pvp-dice-result" style="min-height:30px;margin-top:0.3rem;"></div>
        </div>
        
        <!-- Battle Log -->
        <div class="battle-log-full" id="pvp-battle-log" style="max-height:150px;">
            ${(state.log || []).map(l => renderPvpLogEntry(l, state.you_are)).join('')}
        </div>
        
        <!-- Action buttons -->
        <div class="battle-end-actions" style="margin-top:1rem;">
            ${isMyTurn ? `<button class="btn btn-secondary" onclick="pvpSwitchPokemon()">🔄 Trocar Pokémon</button>` : ''}
            ${isMyTurn ? `<button class="btn btn-secondary" onclick="pvpPassTurn()">⏭️ Passar Turno</button>` : ''}
            <button class="btn btn-danger" onclick="pvpForfeit()">🏳️ Desistir</button>
        </div>
    `;
    
    // Scroll log to bottom
    const log = document.getElementById('pvp-battle-log');
    if (log) log.scrollTop = log.scrollHeight;

    // Manage countdown
    if (isMyTurn) {
        startPvpTimer();
    } else {
        clearPvpTimer();
    }
}

function renderPvpLogEntry(entry, youAre) {
    if (entry.type === 'initiative') {
        return `<p>🎲 Iniciativa — P1: ${entry.player1_roll} | P2: ${entry.player2_roll} → ${entry.first === youAre ? 'Você' : 'Oponente'} começa!</p>`;
    }
    if (entry.type === 'attack') {
        const who = entry.attacker === youAre ? '🟢 Você' : '🔴 Oponente';
        return `<p>${who} usou <strong>${entry.move}</strong> → ${entry.damage} dano! ${entry.message || ''}</p>`;
    }
    if (entry.type === 'faint') {
        const who = entry.player === youAre ? '😵 Seu Pokémon' : '💀 Pokémon do oponente';
        return `<p><strong>${who} desmaiou!${entry.permadeath ? ' 💀 MORTE PERMANENTE!' : ''}</strong></p>`;
    }
    if (entry.type === 'status_applied') {
        const who = entry.player === youAre ? 'Seu Pokémon' : 'Pokémon do oponente';
        return `<p>${getStatusIcon(entry.condition)} <strong>${who}</strong> foi afetado por <strong>${entry.condition}</strong>!</p>`;
    }
    if (entry.type === 'status_damage') {
        const who = entry.player === youAre ? 'Seu Pokémon' : 'Pokémon do oponente';
        return `<p>${getStatusIcon(entry.condition)} <strong>${who}</strong> sofreu ${entry.damage} de dano por ${entry.condition}.</p>`;
    }
    if (entry.type === 'ability') {
        return `<p>✨ <em>${entry.message}</em></p>`;
    }
    return '';
}

async function pvpUseMove(moveName) {
    const state = window.pvpState.battleData;
    if (!state || state.turn !== state.you_are) { alert('Não é seu turno!'); return; }

    const myActive = state.your_team[state.your_active_idx] || {};
    const stats = myActive.stats || {};
    const level = myActive.level || 1;

    // Get move data from cache
    const m = MOVES_CACHE[moveName] || {};
    const moveType = (typeof m.type === 'string' ? m.type : String(m.type || '')).toLowerCase();

    // Calculate attack roll
    let moveMod = 0;
    const power = (m.power || 'FOR').toUpperCase();
    if (power.includes('FOR')) moveMod = Math.max(moveMod, Math.floor(((stats.STR||10) - 10) / 2));
    if (power.includes('DES')) moveMod = Math.max(moveMod, Math.floor(((stats.DEX||10) - 10) / 2));
    if (power.includes('INT')) moveMod = Math.max(moveMod, Math.floor(((stats.INT||10) - 10) / 2));
    if (power.includes('SAB')) moveMod = Math.max(moveMod, Math.floor(((stats.WIS||10) - 10) / 2));
    if (power.includes('CAR')) moveMod = Math.max(moveMod, Math.floor(((stats.CHA||10) - 10) / 2));
    if (power.includes('CON')) moveMod = Math.max(moveMod, Math.floor(((stats.CON||10) - 10) / 2));

    const profBonus = level >= 17 ? 6 : level >= 13 ? 5 : level >= 9 ? 4 : level >= 5 ? 3 : 2;
    const attackRoll = Math.floor(Math.random() * 20) + 1;
    const isCrit = attackRoll === 20;
    const totalAttack = attackRoll + moveMod + profBonus;

    const opponentAC = state.opponent_active?.ac || 13;

    let damage = 0;
    let message = '';

    if (attackRoll === 1) {
        message = `d20(1) Falha Crítica!`;
    } else if (totalAttack >= opponentAC || isCrit) {
        const diceRoll = rollDamageFromString(m.baseDamage || '1d6', level);
        damage = diceRoll + moveMod;
        if (isCrit) damage = diceRoll + rollDamageFromString(m.baseDamage || '1d6', level) + moveMod;

        // STAB
        const pokeTypes = (myActive.types || []).map(t => t.toLowerCase());
        const stabTable = [0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5];
        const stab = pokeTypes.includes(moveType) ? (stabTable[level] || 0) : 0;
        damage += stab;
        if (damage < 1) damage = 1;
        message = `d20(${attackRoll})+${moveMod}+${profBonus}=${totalAttack} vs AC${opponentAC} ✅ ${damage}dano${isCrit ? ' CRIT!' : ''}`;
    } else {
        message = `d20(${attackRoll})+${moveMod}+${profBonus}=${totalAttack} vs AC${opponentAC} ❌ Errou`;
    }

    // Check status effect from the move (await so it's ready before emit)
    await checkMoveStatusEffect(moveName, attackRoll, damage);
    const statusEffect = window._lastStatusInflicted || null;
    window._lastStatusInflicted = null;

    clearPvpTimer();
    socket.emit('pvp_attack', {
        battle_id: window.pvpState.battleId,
        move_name: moveName,
        move_type: moveType,
        damage: damage,
        message: message,
        status_effect: statusEffect
    });
}

function pvpRollDice(sides) {
    const result = Math.floor(Math.random() * sides) + 1;
    document.getElementById('pvp-dice-result').innerHTML = `<span class="dice-value">d${sides}: ${result}</span>${result === 20 ? ' 💥' : ''}${result === 1 ? ' 💨' : ''}`;
}

function pvpSwitchPokemon() {
    const state = window.pvpState.battleData;
    if (!state) return;
    
    const team = state.your_team || [];
    const used = state.your_used_pokemon || [];
    const mode = state.mode;
    
    let html = '<h3>🔄 Escolha um Pokémon</h3>';
    if (mode === 'official' || mode === 'tournament') {
        html += '<p style="color:var(--warning);font-size:0.8rem;">⚠️ Modo Oficial: Pokémon trocado voluntariamente fica bloqueado para esta batalha.</p>';
    }
    html += '<div style="display:flex;flex-direction:column;gap:0.5rem;margin-top:1rem;">';
    
    team.forEach((p, i) => {
        const isCurrent = i === state.your_active_idx;
        const isFainted = (p.currentHp || 0) <= 0;
        const isBlocked = (mode === 'official' || mode === 'tournament') && used.includes(i) && !isCurrent;
        const canSelect = !isCurrent && !isFainted && !isBlocked;
        
        html += `
            <div class="switch-option ${isCurrent ? 'current' : ''} ${isFainted ? 'fainted' : ''} ${isBlocked ? 'fainted' : ''}"
                 ${canSelect ? `onclick="pvpConfirmSwitch(${i})"` : ''} style="cursor:${canSelect ? 'pointer' : 'default'};">
                <strong>${p.nickname || p.name}</strong> Nv.${p.level} — HP: ${p.currentHp || 0}/${p.maxHp || 0}
                ${isCurrent ? '<em>(ativo)</em>' : ''}
                ${isFainted ? '<em>(desmaiado)</em>' : ''}
                ${isBlocked ? '<em>(bloqueado)</em>' : ''}
            </div>
        `;
    });
    html += '</div>';
    
    // Show in a modal-like overlay in the battle area
    const area = document.getElementById('pvp-battle-content');
    const originalHtml = area.innerHTML;
    area.innerHTML = html + `<button class="btn btn-secondary" style="margin-top:1rem;" onclick="renderPvpBattle(window.pvpState.battleData)">Cancelar</button>`;
}

function pvpConfirmSwitch(idx) {
    clearPvpTimer();
    socket.emit('pvp_switch', {
        battle_id: window.pvpState.battleId,
        pokemon_idx: idx
    });
}

function pvpPassTurn() {
    clearPvpTimer();
    socket.emit('pvp_pass_turn', { battle_id: window.pvpState.battleId });
}

function pvpForfeit() {
    if (!confirm('Desistir desta batalha? Você perderá automaticamente.')) return;
    socket.emit('pvp_forfeit', { battle_id: window.pvpState.battleId });
}

// Must switch (pokemon fainted)
socket.on('pvp_must_switch', (data) => {
    alert('😵 Seu Pokémon desmaiou! Escolha o próximo.');
    pvpSwitchPokemon();
});

// Permanent death in PVP
socket.on('pvp_pokemon_death', (data) => {
    const name = data.pokemon_name || '???';
    addPvpLog(`💀 ${name} atingiu -30 HP e morreu permanentemente!`);
    // Remove from local team display
    const idx = playerTeam.findIndex(p => (p.nickname || p.name) === name);
    if (idx >= 0) {
        playerTeam.splice(idx, 1);
        refreshTeamDisplay();
    }
    setTimeout(() => alert(`💀 ${name} morreu permanentemente e foi removido do seu time para sempre.`), 500);
});

// Battle ended
socket.on('pvp_battle_ended', (data) => {
    clearPvpTimer();
    const content = document.getElementById('pvp-battle-content');
    const isWinner = data.winner === window.pvpState.youAre;
    
    let rewardsHtml = '';
    if (isWinner && data.rewards) {
        rewardsHtml = '<div style="margin-top:1rem;background:var(--darker);padding:1rem;border-radius:var(--radius);">';
        rewardsHtml += '<h4 style="color:var(--accent);">💰 Recompensas:</h4>';
        if (data.rewards.money > 0) rewardsHtml += `<p>₽${data.rewards.money}</p>`;
        if (data.rewards.items && data.rewards.items.length > 0) {
            rewardsHtml += data.rewards.items.map(i => `<p>📦 ${i.qty}x ${i.name}</p>`).join('');
        }
        rewardsHtml += '</div>';
    } else if (!isWinner && data.lost) {
        rewardsHtml = '<div style="margin-top:1rem;background:var(--darker);padding:1rem;border-radius:var(--radius);border:1px solid var(--danger);">';
        rewardsHtml += '<h4 style="color:var(--danger);">💸 Perdas:</h4>';
        if (data.lost.money > 0) rewardsHtml += `<p>-₽${data.lost.money}</p>`;
        if (data.lost.items && data.lost.items.length > 0) {
            rewardsHtml += data.lost.items.map(i => `<p>📦 -${i.qty}x ${i.name}</p>`).join('');
        }
        rewardsHtml += '</div>';
    }
    
    if (content) {
        content.innerHTML = `
            <div style="text-align:center;padding:2rem;">
                <h2 style="color:${isWinner ? 'var(--success)' : 'var(--danger)'};">${isWinner ? '🏆 VITÓRIA!' : '💀 DERROTA'}</h2>
                <p>${isWinner ? `Você venceu ${data.loser_name}!` : `${data.winner_name} venceu.`}</p>
                <p style="color:var(--text-muted);">Modo: ${data.mode === 'official' ? '⚔️ Oficial' : '🥊 Rua'}</p>
                ${rewardsHtml}
                <button class="btn btn-primary" style="margin-top:1.5rem;" onclick="closePvpBattle()">Fechar</button>
            </div>
        `;
    }
    
    window.pvpState.battleId = null;
    window.pvpState.battleData = null;
});

socket.on('pvp_error', (data) => {
    alert('PVP Erro: ' + data.message);
});

function closePvpBattle() {
    document.getElementById('pvp-battle-area')?.classList.add('hidden');
    document.getElementById('pvp-battle-content').innerHTML = '';
}

function addPvpLog(msg) {
    const container = document.getElementById('pvp-challenges');
    if (!container) return;
    const p = document.createElement('p');
    p.style.cssText = 'color:var(--text-muted);font-size:0.85rem;margin-top:0.3rem;';
    p.innerHTML = msg;
    container.appendChild(p);
}

// Load moves for PVP on battle start
socket.on('pvp_battle_state', async (state) => {
    // Ensure moves are cached
    const myActive = (state.your_team || [])[state.your_active_idx];
    if (myActive && myActive.moves) {
        await loadMovesData(myActive.moves);
    }

    // VFX: detect HP changes vs previous state
    const prev = window.pvpState.battleData;
    if (prev && state.phase === 'battle') {
        const prevOpp = prev.opponent_active || {};
        const curOpp  = state.opponent_active || {};
        const prevMyActive = (prev.your_team || [])[prev.your_active_idx] || {};
        const curMyActive  = (state.your_team || [])[state.your_active_idx] || {};

        // Opponent took damage
        if (prevOpp.currentHp != null && curOpp.currentHp != null && curOpp.currentHp < prevOpp.currentHp) {
            const el = document.getElementById('pvp-opp-sprite');
            const bar = document.getElementById('pvp-opp-hpbar');
            if (el) battleSpriteHit(el);
            if (bar) hpBarShake(bar);
            if (curOpp.currentHp <= 0) { if (el) battleSpriteFaint(el); playSound('faint'); }
            else playSound('hit');
        }

        // My pokemon took damage
        if (prevMyActive.currentHp != null && curMyActive.currentHp != null && curMyActive.currentHp < prevMyActive.currentHp) {
            const el = document.getElementById('pvp-my-sprite');
            const bar = document.getElementById('pvp-my-hpbar');
            if (el) battleSpriteHit(el);
            if (bar) hpBarShake(bar);
            if (curMyActive.currentHp <= 0) { if (el) battleSpriteFaint(el); playSound('faint'); }
            else playSound('hit');
        }

        // Status applied this update
        const prevLogLen = (prev.log || []).length;
        const newLog = (state.log || []).slice(prevLogLen);
        if (newLog.some(e => e.type === 'status_applied' || e.type === 'status_damage')) {
            playSound('status');
        }
    }

    window.pvpState.battleData = state;
    renderPvpBattle(state);
});


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


// ============================================
// TOURNAMENT NOTIFICATIONS (Player side)
// ============================================
window.playerTournament = null;

socket.on('tournament_bracket_update', (data) => {
    window.playerTournament = data;
    renderPlayerBracket(data);
    // Show panel and switch to PVP tab if not already there
    const panel = document.getElementById('tournament-panel');
    if (panel) panel.classList.remove('hidden');
    if (data.status === 'finished') {
        const first = data.results?.first;
        const second = data.results?.second;
        let msg = `🏆 Campeonato "${data.name}" finalizado!`;
        if (first) msg += `\n🥇 1º: ${first.name}`;
        if (second) msg += `\n🥈 2º: ${second.name}`;
        alert(msg);
    }
});

function renderPlayerBracket(t) {
    const container = document.getElementById('tournament-bracket-player');
    const nameEl = document.getElementById('tournament-panel-name');
    if (!container || !t) return;
    if (nameEl) nameEl.textContent = t.name || '';

    const myId = window.CURRENT_USER_ID;
    const roundNames = { 1: 'Rodada 1', 2: 'Quartas', 3: 'Semifinal', 4: 'Final' };

    const rounds = {};
    (t.bracket || []).forEach(m => {
        if (!rounds[m.round]) rounds[m.round] = [];
        rounds[m.round].push(m);
    });

    let html = '<div style="display:flex;gap:1.5rem;overflow-x:auto;padding:0.75rem 0;">';
    for (const [roundNum, matches] of Object.entries(rounds).sort((a, b) => a[0] - b[0])) {
        html += `<div style="min-width:200px;">`;
        html += `<h5 style="color:var(--accent);margin-bottom:0.5rem;">${roundNames[roundNum] || 'Rodada ' + roundNum}</h5>`;
        matches.forEach(match => {
            const p1 = match.player1;
            const p2 = match.player2;
            const p1Name = p1 ? p1.name : 'BYE';
            const p2Name = p2 ? p2.name : 'BYE';
            const p1Won = match.winner && p1 && match.winner === p1.id;
            const p2Won = match.winner && p2 && match.winner === p2.id;
            const myMatch = myId && ((p1 && p1.id === myId) || (p2 && p2.id === myId));
            const borderColor = myMatch ? 'var(--accent)' : (match.winner ? 'var(--success)' : 'var(--card-border)');
            html += `
                <div style="background:var(--darker);border:2px solid ${borderColor};border-radius:var(--radius);padding:0.4rem 0.6rem;margin-bottom:0.5rem;">
                    <div style="padding:0.15rem 0;${p1Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        ${p1Won ? '🏆 ' : ''}${p1Name}
                    </div>
                    <div style="border-top:1px solid var(--card-border);margin:0.2rem 0;"></div>
                    <div style="padding:0.15rem 0;${p2Won ? 'color:var(--success);font-weight:bold;' : ''}">
                        ${p2Won ? '🏆 ' : ''}${p2Name}
                    </div>
                </div>`;
        });
        html += '</div>';
    }
    html += '</div>';

    if (t.status === 'finished' && t.results) {
        html += `<div style="text-align:center;padding:0.75rem;background:var(--card-bg);border:2px solid var(--accent);border-radius:var(--radius);margin-top:0.5rem;">
            <strong style="color:var(--accent);">🏆 Campeonato Finalizado!</strong>
            ${t.results.first ? `<div>🥇 ${t.results.first.name}</div>` : ''}
            ${t.results.second ? `<div>🥈 ${t.results.second.name}</div>` : ''}
        </div>`;
    }

    container.innerHTML = html;
}

// Load active tournament on page load
(async () => {
    try {
        const resp = await fetch('/api/tournament/active');
        const t = await resp.json();
        if (t && t.bracket) {
            window.playerTournament = t;
            const panel = document.getElementById('tournament-panel');
            if (panel) panel.classList.remove('hidden');
            renderPlayerBracket(t);
        }
    } catch(e) {}
})();

socket.on('tournament_prize', (data) => {
    let msg = `🏆 Parabéns! Você ficou em ${data.place === 'first' ? '1º' : data.place === 'second' ? '2º' : '3º'} lugar no ${data.tournament}!`;
    if (data.money > 0) msg += `\n💰 Prêmio: ₽${data.money}`;
    if (data.extra) msg += `\n🎁 Extra: ${data.extra}`;
    alert(msg);
    // Update local money
    TRAINER_DATA.money = (TRAINER_DATA.money || 0) + (data.money || 0);
    const moneyInput = document.getElementById('trainer-money');
    if (moneyInput) moneyInput.value = TRAINER_DATA.money;
});


// ============================================
// STATUS EFFECTS SYSTEM
// ============================================
window.statusEffectsData = null;
window.wildPokemonStatus = null;  // {condition: 'badly_poisoned', turns_active: 0}
window.playerPokemonStatus = null;
window._wildIsActing = false;
window._processingPlayerStatus = false;

// Load status effects data on page load
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch('/api/status-effects');
        window.statusEffectsData = await resp.json();
    } catch(e) { window.statusEffectsData = {conditions: {}, move_effects: {}}; }
});

// ── Trapping moves ────────────────────────────────────────────────────────────
// Moves that trap the ENEMY (wild cannot flee/switch)
const TRAPPING_MOVES_PLAYER = new Set([
    'mean look', 'block', 'spider web', 'thousand waves', 'spirit shackle',
    'wrap', 'bind', 'clamp', 'fire spin', 'magma storm', 'sand tomb',
    'whirlpool', 'infestation', 'thunder cage', 'snap trap'
]);
// Moves that trap the PLAYER (player cannot switch)
const TRAPPING_MOVES_ENEMY = new Set([
    'mean look', 'block', 'spider web', 'thousand waves',
    'wrap', 'bind', 'clamp', 'fire spin', 'magma storm', 'sand tomb',
    'whirlpool', 'infestation', 'thunder cage', 'snap trap', 'octolock'
]);

// ── Ability checks (mirrors abilities.py logic client-side) ─────────────────
const ABILITY_IMMUNITIES_JS = {
    'levitate':       ['ground'],
    'flash fire':     ['fire'],
    'water absorb':   ['water'],
    'volt absorb':    ['electric'],
    'motor drive':    ['electric'],
    'sap sipper':     ['grass'],
    'storm drain':    ['water'],
    'lightning rod':  ['electric'],
    'dry skin':       ['water'],
    'earth eater':    ['ground'],
    'well-baked body':['fire'],
};
const ABILITY_ABSORB_HEAL_JS = new Set(['water absorb','volt absorb','dry skin','storm drain','lightning rod','earth eater','well-baked body']);
const ABILITY_ABSORB_BOOST_JS = {
    'flash fire':  {type:'fire',    boost:'fire_boost'},
    'motor drive': {type:'electric',boost:'SPE'},
    'sap sipper':  {type:'grass',   boost:'ATK'},
};
const ABILITY_RESISTANCES_JS = {
    'thick fat':     {fire:0.5, ice:0.5},
    'heatproof':     {fire:0.5},
    'water bubble':  {fire:0.5},
    'purifying salt':{ghost:0.5},
};

function checkAbilityVsMove(ability, moveTypeEn, damage, currentHp, maxHp) {
    const result = {modified_damage: damage, heal: 0, blocked: false, boost: null, message: ''};
    if (!ability || damage <= 0) return result;
    ability = ability.toLowerCase();

    const immuneTypes = ABILITY_IMMUNITIES_JS[ability] || [];
    if (immuneTypes.includes(moveTypeEn)) {
        result.modified_damage = 0;
        result.blocked = true;
        if (ABILITY_ABSORB_HEAL_JS.has(ability)) {
            result.heal = Math.max(1, Math.floor((maxHp || 20) / 4));
            result.message = `${ability} absorveu o golpe! +${result.heal} HP`;
        } else {
            const boostInfo = ABILITY_ABSORB_BOOST_JS[ability];
            if (boostInfo && boostInfo.type === moveTypeEn) {
                result.boost = boostInfo.boost;
                result.message = `${ability} absorveu o golpe! ${boostInfo.boost} ↑`;
            } else {
                result.message = `${ability} tornou ${moveTypeEn} ineficaz!`;
            }
        }
        return result;
    }

    const resists = ABILITY_RESISTANCES_JS[ability] || {};
    if (resists[moveTypeEn] !== undefined) {
        result.modified_damage = Math.max(1, Math.floor(damage * resists[moveTypeEn]));
        result.message = `${ability} reduziu o dano (${moveTypeEn})!`;
    }

    // Sturdy: survive KO at full HP
    if (ability === 'sturdy' && currentHp >= maxHp && result.modified_damage >= currentHp) {
        result.modified_damage = currentHp - 1;
        result.message = 'Sturdy! Sobreviveu com 1 HP!';
    }

    return result;
}

// Handle ability_triggered event from server (e.g. NPC attack blocked by player ability)
socket.on('ability_triggered', (data) => {
    if (data.message) addBattleLog(`🛡️ <strong>Habilidade</strong>: ${data.message}`);
    if (data.heal) {
        const poke = playerTeam[0];
        if (poke) {
            poke.currentHp = Math.min(poke.maxHp, (poke.currentHp || 0) + data.heal);
            refreshTeamDisplay();
        }
    }
});

async function checkMoveStatusEffect(moveName, attackRoll, damage) {
    // Check if a move inflicts status after hitting.
    try {
        const resp = await fetch('/api/check-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'check_hit', move_name: moveName, attack_roll: attackRoll, damage })
        });
        const data = await resp.json();
        if (data.inflicted) {
            window.wildPokemonStatus = { condition: data.status, turns_active: 0 };
            window._lastStatusInflicted = data.status;
            addBattleLog(`${data.icon} <strong>${data.name}!</strong> O Pokémon selvagem ficou ${data.name.toLowerCase()}! (${data.description})`);
            updateStatusDisplay();
        }
    } catch(e) {}
}

async function processPlayerTurnStart() {
    // Process status effects at start of player turn.
    if (!window.playerPokemonStatus) return true;
    window._playerPreTurnStatusDamage = 0;
    
    try {
        const resp = await fetch('/api/check-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'turn_start',
                pokemon_status: window.playerPokemonStatus,
                max_hp: window.currentBattleData?.playerPokemon?.maxHp || 20,
                ability: window.currentBattleData?.playerPokemon?.ability?.name || window.currentBattleData?.playerPokemon?.ability || ''
            })
        });
        const data = await resp.json();
        
        data.messages.forEach(msg => addBattleLog(msg));
        
        if (data.ability_messages?.length) {
            data.ability_messages.forEach(m => addBattleLog(`✨ <em>${m}</em>`));
        }
        if (data.damage > 0) {
            window._playerPreTurnStatusDamage = data.damage;
            const hpText = document.getElementById('battle-player-hp-text-full').textContent;
            const hpMatch = hpText.match(/(\d+)\/(\d+)/);
            if (hpMatch) {
                const newHp = Math.max(0, parseInt(hpMatch[1]) - data.damage);
                const maxHp = parseInt(hpMatch[2]);
                document.getElementById('battle-player-hp-text-full').textContent = `${newHp}/${maxHp} HP`;
                setHpBar('battle-player-hp-bar-full', newHp, maxHp);
                battleSpriteHit('battle-player-sprite');
                hpBarShake(document.querySelector('.player-side .hp-bar-container'));
                playSound('status');
            }
        } else if (data.damage < 0) {
            // Poison Heal: heal instead of damage
            const healAmt = Math.abs(data.damage);
            const hpText = document.getElementById('battle-player-hp-text-full').textContent;
            const hpMatch = hpText.match(/(\d+)\/(\d+)/);
            if (hpMatch) {
                const newHp = Math.min(parseInt(hpMatch[2]), parseInt(hpMatch[1]) + healAmt);
                const maxHp = parseInt(hpMatch[2]);
                document.getElementById('battle-player-hp-text-full').textContent = `${newHp}/${maxHp} HP`;
                setHpBar('battle-player-hp-bar-full', newHp, maxHp);
            }
        }
        
        if (data.turns_active) window.playerPokemonStatus.turns_active = data.turns_active;
        if (data.status_removed) {
            window.playerPokemonStatus = null;
            updateStatusDisplay();
        }

        return data.can_act;
    } catch(e) { return true; }
}

async function processWildTurnStart() {
    // Process status effects at start of wild turn.
    if (!window.wildPokemonStatus) return true;
    
    try {
        const resp = await fetch('/api/check-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'turn_start',
                pokemon_status: window.wildPokemonStatus,
                max_hp: window.currentBattleData?.enemy?.hp || 20
            })
        });
        const data = await resp.json();
        
        data.messages.forEach(msg => addBattleLog(msg));
        
        if (data.damage > 0) {
            // Apply status damage locally to the PLAYER's HP bar
            const hpEl = document.getElementById('battle-player-hp-text-full');
            if (hpEl) {
                const match = hpEl.textContent.match(/(\d+)\s*\/\s*(\d+)/);
                if (match) {
                    const newHp = Math.max(0, parseInt(match[1]) - data.damage);
                    const maxHp = parseInt(match[2]);
                    hpEl.textContent = `${newHp}/${maxHp} HP`;
                    setHpBar('battle-player-hp-bar-full', newHp, maxHp);
                    // Keep in-memory HP in sync
                    if (window.currentBattleData?.playerPokemon) {
                        window.currentBattleData.playerPokemon.currentHp = newHp;
                        const ap = window.currentBattleData.playerPokemon;
                        const idx = playerTeam.findIndex(p => (p.nickname||p.name)===(ap.nickname||ap.name) && p.level===ap.level);
                        if (idx >= 0) playerTeam[idx].currentHp = newHp;
                    }
                }
            }
        }
        
        if (data.turns_active) window.wildPokemonStatus.turns_active = data.turns_active;
        if (data.status_removed) {
            window.wildPokemonStatus = null;
            updateStatusDisplay();
        }

        return data.can_act;
    } catch(e) { return true; }
}

function updateStatusDisplay() {
    // Show status icons near HP bars
    const enemyHpEl = document.getElementById('battle-enemy-hp-text-full');
    const playerHpEl = document.getElementById('battle-player-hp-text-full');
    
    // Remove old badges
    document.querySelectorAll('.status-badge-display').forEach(el => el.remove());
    
    if (window.wildPokemonStatus) {
        const cond = window.statusEffectsData?.conditions?.[window.wildPokemonStatus.condition];
        if (cond && enemyHpEl) {
            const badge = document.createElement('span');
            badge.className = 'status-badge-display';
            badge.style.cssText = `display:inline-block;background:${cond.color};color:white;padding:0.1rem 0.4rem;border-radius:4px;font-size:0.7rem;margin-left:0.5rem;`;
            badge.textContent = `${cond.icon} ${cond.name}`;
            enemyHpEl.parentElement.appendChild(badge);
        }
    }
    
    if (window.playerPokemonStatus) {
        const cond = window.statusEffectsData?.conditions?.[window.playerPokemonStatus.condition];
        if (cond && playerHpEl) {
            const badge = document.createElement('span');
            badge.className = 'status-badge-display';
            badge.style.cssText = `display:inline-block;background:${cond.color};color:white;padding:0.1rem 0.4rem;border-radius:4px;font-size:0.7rem;margin-left:0.5rem;`;
            badge.textContent = `${cond.icon} ${cond.name}`;
            playerHpEl.parentElement.appendChild(badge);
        }
    }
}

// Hook into turn change to process status effects
const _originalUpdateTurnUI = updateTurnUI;
updateTurnUI = async function() {
    _originalUpdateTurnUI();
    // Process PLAYER's status effects at the START of PLAYER's turn (before player acts)
    // This is a "pre-turn" step: status resolves, then the pokemon acts (or can't)
    if (window.currentTurn === 'player' && window.playerPokemonStatus && !window._processingPlayerStatus) {
        window._processingPlayerStatus = true;
        const canAct = await processPlayerTurnStart();
        window._processingPlayerStatus = false;
        if (!canAct) {
            addBattleLog('⏭️ Seu Pokémon não conseguiu agir por causa do status!');
            // Pass the turn (this will trigger server to switch to wild turn)
            socket.emit('battle_action', {
                action_by: 'player', action_type: 'pass',
                move_name: 'Status impediu', damage: 0,
                player_status_damage: window._playerPreTurnStatusDamage || 0,
                message: 'Não pôde agir'
            });
        }
    }
};

// When master applies status to player's pokemon (from battle_update)
const _originalBattleUpdate = socket._callbacks?.['$battle_update'];
socket.on('battle_update', (data) => {
    // Check if master applied a status effect
    if (data.status_effect && data.action_by === 'master') {
        window.playerPokemonStatus = { condition: data.status_effect, turns_active: 0 };
        const cond = window.statusEffectsData?.conditions?.[data.status_effect];
        if (cond) {
            addBattleLog(`${cond.icon} Seu Pokémon ficou <strong>${cond.name}</strong>! ${cond.description}`);
        }
        updateStatusDisplay();
    }
});

// Status reset is already handled inside endBattle above


// ============================================
// WILD POKEMON AUTO-ATTACK (AI)
// ============================================
async function wildPokemonAutoAttack() {
    if (!battleActive || !window.currentBattleData || window.wildFainted) return;
    if (window.currentTurn !== 'wild') return;
    // Prevent re-entry: if the wild is already acting, exit
    if (window._wildIsActing) return;
    window._wildIsActing = true;
    
    try {
        await _executeWildTurn();
    } finally {
        // Release the flag after a delay to prevent the battle_update response from re-triggering
        setTimeout(() => { window._wildIsActing = false; }, 600);
    }
}

async function _executeWildTurn() {
    const enemy = window.currentBattleData.enemy;
    const playerPoke = window.currentBattleData.playerPokemon;
    const wildLevel = currentEncounter?.level || enemy?.level || 5;
    const wildStats = enemy?.stats || {};
    
    // === PRE-TURN: Process wild pokemon's status (poison/burn damage, paralysis/sleep/freeze check) ===
    let wildPreTurnStatusDamage = 0;
    window._wildPreTurnStatusDamage = 0;
    if (window.wildPokemonStatus) {
        try {
            const resp = await fetch('/api/check-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: 'turn_start',
                    pokemon_status: window.wildPokemonStatus,
                    max_hp: enemy?.maxHp || enemy?.hp || 20
                })
            });
            const statusResult = await resp.json();
            statusResult.messages.forEach(msg => addBattleLog(`🔴 ${msg}`));
            
            if (statusResult.damage > 0) {
                wildPreTurnStatusDamage = statusResult.damage;
                window._wildPreTurnStatusDamage = statusResult.damage;
                // Apply status damage directly to wild HP display
                const maxHp = enemy?.maxHp || enemy?.hp || 20;
                const hpText = document.getElementById('battle-enemy-hp-text-full')?.textContent || '';
                const hpMatch = hpText.match(/(-?\d+)\s*\/\s*(\d+)/);
                const currentHp = hpMatch ? parseInt(hpMatch[1]) : maxHp;
                const newHp = Math.max(-30, currentHp - statusResult.damage);
                document.getElementById('battle-enemy-hp-text-full').textContent = `${newHp}/${maxHp} HP`;
                setHpBar('battle-enemy-hp-bar-full', newHp, maxHp);
                const condName = window.statusEffectsData?.conditions?.[window.wildPokemonStatus.condition]?.name || window.wildPokemonStatus.condition;
                addBattleLog(`🔴 Dano: ${condName} → ${statusResult.damage} de dano! (Dano de condição)`);
                // Check if wild fainted from status damage
                if (newHp <= 0) {
                    addBattleLog(`💀 Pokémon Selvagem desmaiou por ${condName}!`);
                    window.wildFainted = true;
                    window.currentTurn = 'player';
                    updateTurnUI();
                    // Sync status damage with server
                    socket.emit('battle_action', {
                        action_by: 'master', action_type: 'pass',
                        move_name: 'Desmaiou por status', damage: 0,
                        wild_status_damage: wildPreTurnStatusDamage,
                        message: 'Desmaiou por dano de condição'
                    });
                    return;
                }
            }
            if (statusResult.turns_active && window.wildPokemonStatus) window.wildPokemonStatus.turns_active = statusResult.turns_active;
            if (statusResult.status_removed) {
                window.wildPokemonStatus = null;
                updateStatusDisplay();
            }
            if (!statusResult.can_act) {
                addBattleLog(`🔴 Pokémon Selvagem não conseguiu agir!`);
                // Pass the turn to player without attacking, but sync status damage
                socket.emit('battle_action', {
                    action_by: 'master', action_type: 'pass',
                    move_name: 'Status impediu', damage: 0,
                    wild_status_damage: wildPreTurnStatusDamage,
                    message: 'Selvagem não pôde agir'
                });
                return;
            }
        } catch(e) { console.error('Wild status check failed:', e); }
    }
    
    // === MAIN TURN: Pick a move and attack ===
    let wildMoves = currentEncounter?.wild_moves || enemy?.startingMoves || ['Tackle'];
    // Filter out junk entries (single common words that are parts of move names, copyright text)
    const junkWords = ['down', 'up', 'out', 'off', 'in', 'on', 'by', 'to', 'the', 'a', 'an', 'or', 'and', 'is', 'not', 'this', 'of', 'for'];
    wildMoves = wildMoves.filter(m => m && m.length > 2 && !junkWords.includes(m.toLowerCase()) && !m.includes('©') && !m.toLowerCase().includes('unofficial') && !m.toLowerCase().includes('wizards') && !m.toLowerCase().includes('nintendo') && !m.toLowerCase().includes('portions'));
    if (wildMoves.length === 0) wildMoves = ['Tackle'];
    const moveName = wildMoves[Math.floor(Math.random() * wildMoves.length)];
    
    // Get move data from cache (load if needed)
    if (!MOVES_CACHE[moveName]) {
        try {
            const resp = await fetch('/api/moves/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ moves: [moveName] })
            });
            const data = await resp.json();
            Object.assign(MOVES_CACHE, data);
        } catch(e) {}
    }
    
    const moveData = MOVES_CACHE[moveName] || {};
    
    // If move not found in cache, skip it (bad data)
    if (!moveData.name && !moveData.baseDamage && !moveData.type) {
        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong> → Move ${moveName} não encontrado`);
        socket.emit('battle_action', {
            action_by: 'master', action_type: 'attack',
            move_name: moveName, damage: 0,
            wild_status_damage: wildPreTurnStatusDamage,
            message: `Move ${moveName} não encontrado`
        });
        return;
    }
    
    // NEW STAT SYSTEM: Physical (ATK) or Special (SPA)
    const moveCategory = moveData.category || 'physical';
    let moveMod = 0;
    if (moveCategory === 'physical') {
        // Apply Intimidate penalty to ATK modifier
        const intimidatePenalty = window._wildIntimidateMod || 0;
        const rawATK = (wildStats.ATK || wildStats.STR || 10) + intimidatePenalty * 2;
        moveMod = Math.floor((rawATK - 10) / 2);
    } else {
        moveMod = Math.floor(((wildStats.SPA || wildStats.INT || 10) - 10) / 2);
    }

    // Proficiency for wild (1-100 scale)
    const profBonus = getProficiencyForLevel(wildLevel);
    
    // Status/utility move - check by name first (some status moves have baseDamage in JSON for reduction purposes)
    const ALWAYS_STATUS_MOVES = ['harden', 'withdraw', 'iron defense', 'acid armor', 'barrier', 'cotton guard',
        'cosmic power', 'defend order', 'swords dance', 'bulk up', 'calm mind', 'dragon dance', 
        'nasty plot', 'quiver dance', 'shell smash', 'work up', 'curse', 'stockpile',
        'amnesia', 'double team', 'minimize', 'growth', 'meditate', 'sharpen',
        'belly drum', 'coil', 'shift gear', 'autotomize', 'rock polish', 'agility',
        'light screen', 'reflect', 'safeguard', 'mist', 'aurora veil',
        'rest', 'recover', 'roost', 'synthesis', 'moonlight', 'soft-boiled', 'milk drink',
        'protect', 'detect', 'endure', 'spiky shield', 'baneful bunker',
        'toxic', 'will-o-wisp', 'thunder wave', 'hypnosis', 'sleep powder', 'stun spore',
        'confuse ray', 'swagger', 'supersonic', 'sweet kiss', 'sing', 'grass whistle',
        'scary face', 'string shot', 'cotton spore', 'growl', 'leer', 'tail whip', 'screech',
        'smokescreen', 'sand attack', 'flash', 'charm', 'fake tears', 'metal sound',
        'rain dance', 'sunny day', 'sandstorm', 'hail', 'attract', 'taunt', 'encore',
        'disable', 'torment', 'spite', 'wish', 'heal bell', 'aromatherapy',
        'venom drench', 'toxic spikes', 'spikes', 'stealth rock', 'sticky web'];
    
    if (!moveData.baseDamage || ALWAYS_STATUS_MOVES.includes(moveName.toLowerCase())) {
        await processWildStatusMove(moveName);
        return;
    }
    
    // Determine player's AC based on move category and dodge
    const playerStats = playerPoke?.stats || {};
    let targetAC;
    let defLabel;
    if (window.playerDodging) {
        targetAC = 8 + Math.floor(((playerStats.SPE || 10) - 10) / 2) + Math.floor(getProficiencyForLevel(playerPoke?.level || 1) / 2);
        defLabel = '🏃 Esquiva';
    } else if (moveCategory === 'physical') {
        targetAC = 8 + Math.floor(((playerStats.DEF || 10) - 10) / 2) + Math.floor(getProficiencyForLevel(playerPoke?.level || 1) / 2);
        defLabel = '🛡️ DEF';
    } else {
        targetAC = 8 + Math.floor(((playerStats.SPD || 10) - 10) / 2) + Math.floor(getProficiencyForLevel(playerPoke?.level || 1) / 2);
        defLabel = '✨ SPD';
    }
    targetAC = Math.max(8, Math.floor(targetAC));
    
    // Wild accuracy mod (from player's Smokescreen etc.)
    const wildAccMod = window.wildAccuracyMod || 0;
    
    // Attack roll
    const attackRoll = Math.floor(Math.random() * 20) + 1;
    const isCrit = attackRoll === 20;
    const isMiss = attackRoll === 1;
    const totalAttack = attackRoll + moveMod + profBonus + wildAccMod;
    
    const categoryLabel = moveCategory === 'physical' ? '⚔️' : '✨';
    
    if (isMiss) {
        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong> ${categoryLabel} → d20(${attackRoll}) 💨 Falha Crítica!`);
        socket.emit('battle_action', {
            action_by: 'master', action_type: 'attack',
            move_name: moveName, damage: 0,
            wild_status_damage: wildPreTurnStatusDamage,
            message: 'Nat 1 - Falha'
        });
    } else if (totalAttack >= targetAC || isCrit) {
        // Calculate damage with scaling
        const scaledDice = getScaledDice(moveData.baseDamage || '1d6', wildLevel, moveData.higherLevels || '');
        let diceRoll = rollDamageFromString(scaledDice, wildLevel);
        let damage = diceRoll + moveMod;
        if (isCrit) {
            const critExtra = rollDamageFromString(scaledDice, wildLevel);
            damage = diceRoll + critExtra + moveMod;
        }
        
        // Dodge penalty: 1.25x if player was dodging
        if (window.playerDodging) {
            damage = Math.floor(damage * 1.25);
        }
        
        // STAB
        const wildTypes = (enemy?.types || []).map(t => t.toLowerCase());
        const moveType = (moveData.type || '').toLowerCase();
        const stab = wildTypes.includes(moveType) ? getStabForLevel(wildLevel) : 0;
        damage += stab;
        
        // Type effectiveness vs player pokemon (move types in PT, vulnerabilities in EN)
        const typeMapPtToEn2 = {
            'fogo':'fire', 'água':'water', 'grama':'grass', 'elétrico':'electric',
            'gelo':'ice', 'lutador':'fighting', 'venenoso':'poison', 'terra':'ground',
            'voador':'flying', 'psíquico':'psychic', 'inseto':'bug', 'pedra':'rock',
            'fantasma':'ghost', 'dragão':'dragon', 'sombrio':'dark', 'aço':'steel',
            'fada':'fairy', 'normal':'normal'
        };
        const wildMoveTypeEn = typeMapPtToEn2[moveType] || moveType;
        
        const pVulns = (playerPoke?.vulnerabilities || []).map(t => t.toLowerCase());
        const pResists = (playerPoke?.resistances || []).map(t => t.toLowerCase());
        const pImmunities = (playerPoke?.immunities || []).map(t => t.toLowerCase());
        
        let effectiveness = 1;
        let effectLabel = '';
        if (pImmunities.includes(wildMoveTypeEn)) {
            effectiveness = 0; effectLabel = '⛔ Imune';
        } else {
            if (pVulns.includes(wildMoveTypeEn)) effectiveness *= 2;
            if (pResists.includes(wildMoveTypeEn)) effectiveness *= 0.5;
        }
        damage = Math.floor(damage * effectiveness);
        if (effectiveness === 0) damage = 0;
        if (effectiveness > 1) effectLabel = `⚡ Super Efetivo (x${effectiveness})`;
        else if (effectiveness < 1 && effectiveness > 0) effectLabel = `🛡️ Não Efetivo (x${effectiveness})`;
        
        if (damage < 1 && effectiveness > 0) damage = 1;

        // Check player pokemon ability against wild move
        const playerAbility = (playerPoke?.ability || '').toLowerCase();
        if (damage > 0 && playerAbility) {
            const pAbCheck = checkAbilityVsMove(playerAbility, wildMoveTypeEn, damage,
                playerPoke.currentHp, playerPoke.maxHp);
            if (pAbCheck.blocked) {
                damage = 0;
                addBattleLog(`🛡️ <strong>${playerAbility}</strong>: ${pAbCheck.message}`);
                if (pAbCheck.heal) {
                    const slot = playerTeam.findIndex(p => p.name === playerPoke.name || p.nickname === playerPoke.nickname);
                    if (slot >= 0) {
                        playerTeam[slot].currentHp = Math.min(playerTeam[slot].maxHp, (playerTeam[slot].currentHp || 0) + pAbCheck.heal);
                        refreshTeamDisplay();
                    }
                }
            } else if (pAbCheck.modified_damage !== damage) {
                addBattleLog(`🛡️ <strong>${playerAbility}</strong>: ${pAbCheck.message}`);
                damage = pAbCheck.modified_damage;
            }
        }

        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong> ${categoryLabel} → d20(${attackRoll})+${moveMod}+${profBonus}${wildAccMod ? `+Acc(${wildAccMod})` : ''}=${totalAttack} vs ${defLabel}(${targetAC}) ✅ ${scaledDice}(${diceRoll})+MOD(${moveMod})${stab > 0 ? `+STAB(${stab})` : ''}${window.playerDodging ? ' ×1.25(esquiva)' : ''}${isCrit ? ' CRIT!' : ''}${effectLabel ? ' '+effectLabel : ''} = <strong>${damage} dano</strong>`);

        // Check if wild move inflicts status on player
        checkWildStatusOnHit(moveName, attackRoll, damage);

        socket.emit('battle_action', {
            action_by: 'master', action_type: 'attack',
            move_name: moveName, move_type: wildMoveTypeEn, damage: damage,
            wild_status_damage: wildPreTurnStatusDamage,
            status_effect: window._wildStatusApplied || null,
            message: `${totalAttack} vs AC ${targetAC}${isCrit ? ' Crítico!' : ''}`
        });
        window._wildStatusApplied = null;
    } else {
        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong> ${categoryLabel} → d20(${attackRoll})+${moveMod}+${profBonus}${wildAccMod ? `+Acc(${wildAccMod})` : ''}=${totalAttack} vs ${defLabel}(${targetAC}) ❌ Errou!${window.playerDodging ? ' (esquivou!)' : ''}`);
        socket.emit('battle_action', {
            action_by: 'master', action_type: 'attack',
            move_name: moveName, damage: 0,
            wild_status_damage: wildPreTurnStatusDamage,
            message: `Errou (${totalAttack} vs AC ${targetAC})`
        });
    }
}

function checkWildStatusMove(moveName) {
    // Pure status moves from wild pokemon applying to player
    const effectsData = window.statusEffectsData?.move_effects || {};
    const effect = effectsData[moveName];
    if (effect && effect.on === 'save_fail') {
        // Simple: 50% chance to apply (simplified save)
        if (Math.random() < 0.5) {
            const cond = window.statusEffectsData?.conditions?.[effect.status];
            window.playerPokemonStatus = { condition: effect.status, turns_active: 0 };
            if (cond) addBattleLog(`${cond.icon} Seu Pokémon ficou <strong>${cond.name}</strong>!`);
            updateStatusDisplay();
            return effect.status;
        }
        addBattleLog(`💪 Seu Pokémon resistiu ao efeito de ${moveName}!`);
    }
    return null;
}

function checkWildStatusOnHit(moveName, attackRoll, damage) {
    // Check if the wild's damaging move inflicts a status on hit
    const effectsData = window.statusEffectsData?.move_effects || {};
    const effect = effectsData[moveName];
    if (!effect || damage <= 0) return;
    
    let inflict = false;
    if (effect.on === 'hit') {
        inflict = Math.random() < effect.chance;
    } else if (effect.on === 'nat15plus' && attackRoll >= 15) {
        inflict = Math.random() < effect.chance;
    }
    
    if (inflict) {
        const cond = window.statusEffectsData?.conditions?.[effect.status];
        window.playerPokemonStatus = { condition: effect.status, turns_active: 0 };
        window._wildStatusApplied = effect.status;
        if (cond) addBattleLog(`${cond.icon} Seu Pokémon ficou <strong>${cond.name}</strong>! ${cond.description}`);
        updateStatusDisplay();
    }
}


// ============================================
// POKEMON XP & LEVEL UP SYSTEM
// ============================================
async function awardPokemonBattleXP() {
    // Award XP to the Pokemon that participated in the battle
    const battleData = window.currentBattleData;
    if (!battleData) return;
    
    const playerPoke = battleData.playerPokemon;
    const enemyLevel = currentEncounter?.level || 5;
    const enemySR = battleData.enemy?.sr || '1/2';
    
    // Calculate XP via server
    try {
        const resp = await fetch('/api/pokemon/battle-xp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                winner_level: playerPoke.level || 1,
                loser_level: enemyLevel,
                battle_type: 'wild'
            })
        });
        const data = await resp.json();
        const xpGained = data.xp_gained || 0;
        
        // Find this pokemon in the team and add XP
        const teamIdx = playerTeam.findIndex(p => 
            (p.nickname || p.name) === (playerPoke.nickname || playerPoke.name) && p.level === playerPoke.level
        );
        
        if (teamIdx >= 0) {
            const poke = playerTeam[teamIdx];
            poke.xp = (poke.xp || 0) + xpGained;
            poke.totalXp = (poke.totalXp || 0) + xpGained;
            
            // Check level up
            const leveledUp = checkPokemonLevelUp(poke);
            
            addBattleLog(`⭐ ${poke.nickname || poke.name} ganhou <strong>${xpGained} XP</strong>!${leveledUp ? ' 🎉 SUBIU DE NÍVEL!' : ''}`);
            
            if (leveledUp) {
                addBattleLog(`📈 ${poke.nickname || poke.name} agora é <strong>Nv.${poke.level}</strong>!`);
                // Save first so server sees the new level, then check evolution
                await saveTeam();
                const slotIdx = playerTeam.indexOf(poke);
                if (slotIdx >= 0) await checkServerEvolution(slotIdx);
            } else {
                // Save team
                await saveTeam();
            }
        }
    } catch(e) { console.error('XP award failed:', e); }
}

function checkPokemonLevelUp(poke) {
    // XP table matching server (per-level XP needed)
    const XP_TABLE = [5,7,9,11,14,17,21,25,29,35,42,50,60,72,86,102,121,142,166,192,221,254,289,327,369,413,461,511,565,623,683,747,815,886,961,1040,1123,1210,1301,1397,1498,1603,1718,1841,1973,2115,2267,2430,2604,2791,2991,3206,3436,3683,3948,4232,4536,4862,5212,5587,5989,6420,6882,7377,7908,8477,9087,9741,10442,11193,11998,12861,13786,14778,15842,16982,18204,19514,20919,22425,24039,25769,27624,29612,31744,34029,36479,39105,41920,44938,48173,51641,55359,59344,63616,68196,73106,78369,84011,90059];
    
    const currentLevel = poke.level || 1;
    if (currentLevel >= 100) return false;
    
    const totalXp = poke.totalXp || 0;
    // Calculate total XP needed to reach next level
    let xpNeededForCurrent = 0;
    for (let i = 0; i < currentLevel - 1 && i < XP_TABLE.length; i++) {
        xpNeededForCurrent += XP_TABLE[i];
    }
    const xpForNext = xpNeededForCurrent + XP_TABLE[currentLevel - 1];
    
    if (totalXp >= xpForNext) {
        const oldLevel = currentLevel;
        poke.level = currentLevel + 1;
        // Gain stat points on level up
        poke.statPointsAvailable = (poke.statPointsAvailable || 0) + 1;
        // Every 5 levels, gain extra stat point
        if (poke.level % 5 === 0) poke.statPointsAvailable += 1;
        // Recalculate HP for new level (HP stat bonus)
        const hpMod = Math.floor(((poke.stats?.HP || poke.stats?.CON || 10) - 10) / 2);
        poke.maxHp = (poke.baseHp || 20) + (hpMod * poke.level) + (poke.level * 2);
        poke.currentHp = poke.maxHp; // Full heal on level up

        playSound('levelup');
        // Notify dice upgrades for each move
        checkMoveDiceUpgrades(poke, oldLevel, poke.level);

        // Check for further level ups
        checkPokemonLevelUp(poke);
        return true;
    }
    
    // Update xp to next for display
    poke.xpToNext = xpForNext - totalXp;
    return false;
}

// When trainer receives XP from master (quests), distribute to Pokemon team
const _origXpHandler = socket._callbacks?.['$xp_update'];
socket.on('xp_update', async (data) => {
    // Distribute XP to pokemon team
    if (data.xp && playerTeam.length > 0) {
        // XP per pokemon = total XP gained / number of pokemon in team
        const xpPerPoke = Math.floor((data.xp - (TRAINER_DATA.xp || 0)) / playerTeam.length);
        if (xpPerPoke > 0) {
            let anyLevelUp = false;
            playerTeam.forEach(poke => {
                poke.xp = (poke.xp || 0) + xpPerPoke;
                poke.totalXp = (poke.totalXp || 0) + xpPerPoke;
                if (checkPokemonLevelUp(poke)) anyLevelUp = true;
            });
            if (anyLevelUp) {
                alert('🎉 Um ou mais Pokémon subiram de nível! Verifique o time.');
            }
            await saveTeam();
        }
        // Update trainer data
        TRAINER_DATA.xp = data.xp;
        TRAINER_DATA.level = data.level;
        TRAINER_DATA.xp_to_next = data.xp_to_next;
    }
});


// ============================================
// BATTLE ITEMS (Use items during battle)
// ============================================
const BATTLE_ITEMS = {
    'Potion': { type: 'heal', heal: 20, description: 'Cura 20 HP' },
    'Super Potion': { type: 'heal', heal: 50, description: 'Cura 50 HP' },
    'Hyper Potion': { type: 'heal', heal: 200, description: 'Cura 200 HP' },
    'Max Potion': { type: 'heal', heal: 9999, description: 'Cura todo HP' },
    'Full Restore': { type: 'full_restore', heal: 9999, description: 'Cura todo HP e remove status' },
    'Full Heal': { type: 'cure_status', description: 'Remove qualquer status' },
    'Antidote': { type: 'cure_specific', cures: ['badly_poisoned', 'badly_poisoned'], description: 'Cura veneno' },
    'Burn Heal': { type: 'cure_specific', cures: ['queimado'], description: 'Cura queimadura' },
    'Ice Heal': { type: 'cure_specific', cures: ['congelado'], description: 'Cura congelamento' },
    'Awakening': { type: 'cure_specific', cures: ['dormindo'], description: 'Acorda o Pokémon' },
    'Paralyze Heal': { type: 'cure_specific', cures: ['paralisado'], description: 'Cura paralisia' },
    'Revive': { type: 'revive', heal_pct: 0.5, description: 'Revive com 50% HP' },
    'Max Revive': { type: 'revive', heal_pct: 1.0, description: 'Revive com 100% HP' },
    'Rare Candy': { type: 'level_up', description: 'Sobe 1 nível' },
    'X Attack': { type: 'buff', stat: 'STR', value: 3, description: '+3 STR nesta batalha' },
    'X Defense': { type: 'buff', stat: 'AC', value: 2, description: '+2 AC nesta batalha' },
    'X Speed': { type: 'buff', stat: 'DEX', value: 3, description: '+3 DEX nesta batalha' },
    'X Sp. Atk': { type: 'buff', stat: 'INT', value: 3, description: '+3 INT nesta batalha' },
};

function openBattleItems() {
    if (window.currentTurn !== 'player' && !window.wildFainted) {
        alert('Não é seu turno!'); return;
    }
    
    const bag = window.bagItems || [];
    const usableItems = bag.filter(item => {
        const normalized = item.name.toLowerCase().replace(/\s+/g, ' ');
        return Object.keys(BATTLE_ITEMS).some(k => k.toLowerCase() === normalized);
    });
    
    if (usableItems.length === 0) {
        alert('Nenhum item utilizável em batalha na sua bolsa!');
        return;
    }
    
    let html = '<h3>🎒 Usar Item</h3><p style="color:var(--text-muted);font-size:0.8rem;">Usar um item gasta seu turno.</p>';
    html += '<div style="display:flex;flex-direction:column;gap:0.5rem;margin-top:1rem;">';
    
    usableItems.forEach(item => {
        const itemData = Object.entries(BATTLE_ITEMS).find(([k]) => k.toLowerCase() === item.name.toLowerCase().replace(/\s+/g, ' '));
        const info = itemData ? itemData[1] : {};
        html += `
            <div class="switch-option" onclick="useBattleItem('${item.name.replace(/'/g, "\\'")}')">
                ${item.file ? `<img src="/static/img/items/${item.file}" width="24" height="24" style="image-rendering:pixelated;vertical-align:middle;margin-right:0.5rem;">` : ''}
                <strong>${item.name}</strong> (x${item.qty}) — ${info.description || ''}
            </div>
        `;
    });
    html += '</div>';
    
    // Show in battle log area temporarily
    const log = document.getElementById('battle-log-full');
    const originalLog = log.innerHTML;
    log.innerHTML = html + `<button class="btn btn-secondary" style="margin-top:1rem;" onclick="document.getElementById('battle-log-full').innerHTML='${originalLog.replace(/'/g, "\\'")}'; ">Cancelar</button>`;
}

function useBattleItem(itemName) {
    const itemData = Object.entries(BATTLE_ITEMS).find(([k]) => k.toLowerCase() === itemName.toLowerCase().replace(/\s+/g, ' '));
    if (!itemData) return;
    const [, info] = itemData;
    const poke = window.currentBattleData?.playerPokemon;
    if (!poke) return;
    
    // Apply item effect
    if (info.type === 'heal') {
        const oldHp = poke.currentHp || 0;
        const maxHp = poke.maxHp || 20;
        poke.currentHp = Math.min(maxHp, oldHp + info.heal);
        const healed = poke.currentHp - oldHp;
        addBattleLog(`🧪 Usou <strong>${itemName}</strong>! ${poke.nickname || poke.name} recuperou ${healed} HP. (${poke.currentHp}/${maxHp})`);
        document.getElementById('battle-player-hp-text-full').textContent = `${poke.currentHp}/${maxHp} HP`;
        setHpBar('battle-player-hp-bar-full', poke.currentHp, maxHp);
    } else if (info.type === 'full_restore') {
        poke.currentHp = poke.maxHp || 20;
        window.playerPokemonStatus = null;
        updateStatusDisplay();
        addBattleLog(`🧪 Usou <strong>${itemName}</strong>! HP cheio + status curado!`);
        document.getElementById('battle-player-hp-text-full').textContent = `${poke.currentHp}/${poke.maxHp} HP`;
        setHpBar('battle-player-hp-bar-full', poke.currentHp, poke.maxHp);
    } else if (info.type === 'cure_status' || info.type === 'cure_specific') {
        if (window.playerPokemonStatus) {
            if (info.type === 'cure_status' || (info.cures && info.cures.includes(window.playerPokemonStatus.condition))) {
                addBattleLog(`🧪 Usou <strong>${itemName}</strong>! Status curado!`);
                window.playerPokemonStatus = null;
                updateStatusDisplay();
            } else {
                addBattleLog(`❌ ${itemName} não cura esta condição.`);
                return; // Don't consume
            }
        } else {
            addBattleLog(`❌ Seu Pokémon não tem nenhuma condição.`);
            return;
        }
    } else if (info.type === 'buff') {
        if (poke.stats && info.stat !== 'AC') {
            poke.stats[info.stat] = (poke.stats[info.stat] || 10) + info.value;
            addBattleLog(`🧪 Usou <strong>${itemName}</strong>! ${info.stat} +${info.value}!`);
        } else if (info.stat === 'AC') {
            poke.ac = (poke.ac || 13) + info.value;
            addBattleLog(`🧪 Usou <strong>${itemName}</strong>! AC +${info.value}! (AC agora: ${poke.ac})`);
        }
    }
    
    // Consume item from bag
    const bagIdx = window.bagItems.findIndex(i => i.name.toLowerCase() === itemName.toLowerCase());
    if (bagIdx >= 0) {
        window.bagItems[bagIdx].qty -= 1;
        if (window.bagItems[bagIdx].qty <= 0) window.bagItems.splice(bagIdx, 1);
    }
    
    // Using item costs the turn (emit pass)
    socket.emit('battle_action', {
        action_by: 'player', action_type: 'item',
        move_name: `Usou ${itemName}`, damage: 0,
        player_status_damage: window._playerPreTurnStatusDamage || 0,
        message: info.description
    });
    
    // Restore battle log view
    const log = document.getElementById('battle-log-full');
    if (log && !log.querySelector('.battle-end-actions')) {
        // Log is back to normal after battle_update processes
    }
}


// ============================================
// PROCESS STATUS MOVES (calls server for auto-detection)
// ============================================
async function processStatusMove(moveName, attackerPoke, targetPoke) {
    // Build attacker stats for the server
    const attackerStats = {
        level: attackerPoke?.level || 1,
        proficiency: attackerPoke?.proficiency || getProficiencyForLevel(attackerPoke?.level || 1),
        maxHp: attackerPoke?.maxHp || 20,
        STR: attackerPoke?.stats?.STR || 10,
        DEX: attackerPoke?.stats?.DEX || 10,
        CON: attackerPoke?.stats?.CON || 10,
        INT: attackerPoke?.stats?.INT || 10,
        WIS: attackerPoke?.stats?.WIS || 10,
        CHA: attackerPoke?.stats?.CHA || 10
    };
    const targetStats = {
        level: targetPoke?.level || currentEncounter?.level || 5,
        STR: targetPoke?.stats?.STR || 10,
        DEX: targetPoke?.stats?.DEX || 10,
        CON: targetPoke?.stats?.CON || 10,
        INT: targetPoke?.stats?.INT || 10,
        WIS: targetPoke?.stats?.WIS || 10,
        CHA: targetPoke?.stats?.CHA || 10
    };
    
    try {
        const resp = await fetch('/api/process-status-move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ move_name: moveName, attacker_stats: attackerStats, target_stats: targetStats })
        });
        const result = await resp.json();
        
        addBattleLog(`▶️ <strong>${moveName}</strong> → ${result.message}`);
        
        // Apply effects based on result
        if (result.status_applied) {
            window.wildPokemonStatus = { condition: result.status_applied, turns_active: 0 };
            const cond = window.statusEffectsData?.conditions?.[result.status_applied];
            if (cond) addBattleLog(`${cond.icon} Pokémon selvagem ficou <strong>${cond.name}</strong>!`);
            updateStatusDisplay();
        }
        
        if (result.stat_changes) {
            // Apply stat changes to target (enemy)
            for (const [stat, value] of Object.entries(result.stat_changes)) {
                if (stat === 'attack_roll') {
                    // Store accuracy debuff
                    window.wildAccuracyMod = (window.wildAccuracyMod || 0) + value;
                    addBattleLog(`🎯 Precisão do selvagem: ${value} (total: ${window.wildAccuracyMod})`);
                } else if (targetPoke?.stats && stat in targetPoke.stats) {
                    targetPoke.stats[stat] = (targetPoke.stats[stat] || 10) + value;
                    addBattleLog(`📊 ${stat} do selvagem: ${value > 0 ? '+' : ''}${value}`);
                } else if (stat === 'AC') {
                    if (targetPoke) targetPoke.ac = (targetPoke.ac || 13) + value;
                    addBattleLog(`🛡️ AC do selvagem: ${value > 0 ? '+' : ''}${value} (agora ${targetPoke?.ac})`);
                }
            }
        }
        
        if (result.effect_type === 'heal' && result.heal) {
            // Heal the attacker (player's pokemon)
            const poke = window.currentBattleData?.playerPokemon;
            if (poke) {
                const oldHp = poke.currentHp || 0;
                poke.currentHp = Math.min(poke.maxHp || 20, oldHp + result.heal);
                addBattleLog(`💚 Recuperou ${poke.currentHp - oldHp} HP! (${poke.currentHp}/${poke.maxHp})`);
                document.getElementById('battle-player-hp-text-full').textContent = `${poke.currentHp}/${poke.maxHp} HP`;
                setHpBar('battle-player-hp-bar-full', poke.currentHp, poke.maxHp);
            }
        }
        
        if (result.effect_type === 'buff' && result.stat_changes) {
            // Buff self (player's pokemon)
            const poke = window.currentBattleData?.playerPokemon;
            if (poke) {
                for (const [stat, value] of Object.entries(result.stat_changes)) {
                    if (stat === 'AC') {
                        poke.ac = (poke.ac || 13) + value;
                        addBattleLog(`🛡️ Sua AC: +${value} (agora ${poke.ac})`);
                    } else if (stat === 'STAB') {
                        poke.stab = (poke.stab || 1) + value;
                        addBattleLog(`⚡ Seu STAB: +${value}`);
                    } else if (poke.stats && stat in poke.stats) {
                        poke.stats[stat] = (poke.stats[stat] || 10) + value;
                        addBattleLog(`📊 Seu ${stat}: +${value} (agora ${poke.stats[stat]})`);
                    }
                }
            }
        }
        
        // Trapping moves (player traps the wild)
        if (TRAPPING_MOVES_PLAYER.has(moveName.toLowerCase())) {
            window._enemyTrapped = true;
            window._enemyTrappedBy = moveName;
            addBattleLog(`🔒 ${moveName} prendeu o Pokémon selvagem! Não pode fugir.`);
        }

        // Emit to server (costs turn)
        socket.emit('battle_action', {
            action_by: 'player', action_type: 'status',
            move_name: moveName, damage: 0,
            player_status_damage: window._playerPreTurnStatusDamage || 0,
            status_effect: result.status_applied || null,
            message: result.message
        });
        
    } catch(e) {
        addBattleLog(`▶️ <strong>${moveName}</strong> usado! (efeito de utilidade)`);
        socket.emit('battle_action', {
            action_by: 'player', action_type: 'status',
            move_name: moveName, damage: 0,
            player_status_damage: window._playerPreTurnStatusDamage || 0,
            message: 'Move de status'
        });
    }
}

// Same for wild pokemon using status moves
async function processWildStatusMove(moveName) {
    const enemy = window.currentBattleData?.enemy;
    const playerPoke = window.currentBattleData?.playerPokemon;
    const wildLevel = currentEncounter?.level || 5;
    
    const attackerStats = {
        level: wildLevel,
        proficiency: getProficiencyForLevel(wildLevel),
        maxHp: enemy?.maxHp || enemy?.hp || 20,
        STR: enemy?.stats?.STR || 10,
        DEX: enemy?.stats?.DEX || 10,
        CON: enemy?.stats?.CON || 10,
        INT: enemy?.stats?.INT || 10,
        WIS: enemy?.stats?.WIS || 10,
        CHA: enemy?.stats?.CHA || 10
    };
    const targetStats = {
        level: playerPoke?.level || 1,
        STR: playerPoke?.stats?.STR || 10,
        DEX: playerPoke?.stats?.DEX || 10,
        CON: playerPoke?.stats?.CON || 10,
        INT: playerPoke?.stats?.INT || 10,
        WIS: playerPoke?.stats?.WIS || 10,
        CHA: playerPoke?.stats?.CHA || 10
    };
    
    try {
        const resp = await fetch('/api/process-status-move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ move_name: moveName, attacker_stats: attackerStats, target_stats: targetStats })
        });
        const result = await resp.json();
        
        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong> → ${result.message}`);
        
        if (result.status_applied) {
            window.playerPokemonStatus = { condition: result.status_applied, turns_active: 0 };
            const cond = window.statusEffectsData?.conditions?.[result.status_applied];
            if (cond) addBattleLog(`${cond.icon} Seu Pokémon ficou <strong>${cond.name}</strong>!`);
            updateStatusDisplay();
        }
        
        if (result.stat_changes) {
            const poke = window.currentBattleData?.playerPokemon;
            for (const [stat, value] of Object.entries(result.stat_changes)) {
                if (stat === 'attack_roll') {
                    window.playerAccuracyMod = (window.playerAccuracyMod || 0) + value;
                    addBattleLog(`🎯 Sua precisão: ${value} (total: ${window.playerAccuracyMod})`);
                } else if (stat === 'AC' && poke) {
                    poke.ac = (poke.ac || 13) + value;
                    addBattleLog(`🛡️ Sua AC: ${value} (agora ${poke.ac})`);
                } else if (poke?.stats && stat in poke.stats) {
                    poke.stats[stat] = (poke.stats[stat] || 10) + value;
                    addBattleLog(`📊 Seu ${stat}: ${value}`);
                }
            }
        }
        
        if (result.effect_type === 'heal' && result.heal) {
            // Wild heals itself
            addBattleLog(`💚 Selvagem recuperou ${result.heal} HP!`);
            socket.emit('battle_action', {
                action_by: 'master', action_type: 'heal',
                move_name: moveName, heal: result.heal, damage: 0,
                wild_status_damage: window._wildPreTurnStatusDamage || 0,
                message: result.message
            });
            return;
        }
        
        // Trapping moves (wild traps the player)
        if (TRAPPING_MOVES_ENEMY.has(moveName.toLowerCase())) {
            window._playerTrapped = true;
            window._playerTrappedBy = moveName;
            addBattleLog(`🔒 ${moveName} prendeu seu Pokémon! Não pode trocar.`);
        }

        socket.emit('battle_action', {
            action_by: 'master', action_type: 'status',
            move_name: moveName, damage: 0,
            wild_status_damage: window._wildPreTurnStatusDamage || 0,
            status_effect: result.status_applied || null,
            message: result.message
        });
    } catch(e) {
        addBattleLog(`🔴 Selvagem usou <strong>${moveName}</strong>! (status)`);
        socket.emit('battle_action', {
            action_by: 'master', action_type: 'status',
            move_name: moveName, damage: 0,
            wild_status_damage: window._wildPreTurnStatusDamage || 0,
            message: 'Status move'
        });
    }
}


// ============================================
// STAT POINT DISTRIBUTION (Pokemon)
// ============================================
function distributeStat(stat) {
    const slot = window._editingPokeSlot;
    if (slot === undefined || slot === null) return;
    const poke = playerTeam[slot];
    if (!poke) return;
    
    const available = poke.statPointsAvailable || 0;
    if (available <= 0) {
        alert('Sem pontos disponíveis!');
        return;
    }
    
    // Apply +1 to the stat
    if (!poke.stats) poke.stats = {};
    poke.stats[stat] = (poke.stats[stat] || 10) + 1;
    poke.statPointsAvailable = available - 1;
    
    // If HP stat changed, recalculate max HP
    if (stat === 'HP') {
        const hpMod = Math.floor((poke.stats.HP - 10) / 2);
        const baseHp = poke.baseHp || 20;
        poke.maxHp = baseHp + (hpMod * poke.level) + (poke.level * 2);
        poke.currentHp = Math.min(poke.currentHp || poke.maxHp, poke.maxHp);
        document.getElementById('poke-max-hp').value = poke.maxHp;
        document.getElementById('poke-current-hp').value = poke.currentHp;
    }
    
    // Map new stat names to input IDs (inputs still use old IDs)
    const statToInput = { 'ATK': 'poke-str', 'DEF': 'poke-dex', 'SPA': 'poke-con', 'SPD': 'poke-int', 'SPE': 'poke-wis', 'HP': 'poke-cha' };
    const inputId = statToInput[stat];
    if (inputId) document.getElementById(inputId).value = poke.stats[stat];
    
    document.getElementById('poke-stat-points-available').textContent = poke.statPointsAvailable;
    
    if (poke.statPointsAvailable <= 0) {
        document.getElementById('poke-stat-points-section').classList.add('hidden');
    }
    
    // Auto-save
    saveTeam();
}

// ============================================
// TRAINER LEVEL UP REWARDS
// ============================================
// Trainer gains points per level based on Pokemon 5e rules:
// Each level: +1 to one attribute OR +1 proficiency
// Every 4 levels (4, 8, 12, 16, 20): +2 to attributes (Ability Score Improvement)
const TRAINER_LEVEL_REWARDS = {
    // Regular levels give 1 feature/choice, ASI levels give stat points
    4: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats (distribuir)' },
    8: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats' },
    12: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats' },
    16: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats' },
    19: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats' },
    20: { stat_points: 2, description: 'Melhoria de Atributo: +2 em stats (nível máximo!)' }
};

// Check if trainer has undistributed points on page load
document.addEventListener('DOMContentLoaded', () => {
    const trainerLevel = TRAINER_DATA.level || 1;
    const usedPoints = TRAINER_DATA.trainerStatPointsUsed || 0;
    
    // Calculate total points available at current level
    let totalPoints = 0;
    for (const [lv, reward] of Object.entries(TRAINER_LEVEL_REWARDS)) {
        if (parseInt(lv) <= trainerLevel) {
            totalPoints += reward.stat_points;
        }
    }
    
    const available = totalPoints - usedPoints;
    if (available > 0) {
        // Show notification
        const trainerSection = document.getElementById('tab-trainer');
        if (trainerSection) {
            const notice = document.createElement('div');
            notice.id = 'trainer-points-notice';
            notice.style.cssText = 'background:var(--accent);color:var(--dark);padding:0.75rem 1rem;border-radius:var(--radius);margin-bottom:1rem;font-weight:bold;text-align:center;';
            notice.innerHTML = `⬆️ Você tem <strong>${available}</strong> ponto(s) de atributo para distribuir! Clique nos + abaixo dos atributos.`;
            trainerSection.insertBefore(notice, trainerSection.firstChild.nextSibling);
            
            // Add +1 buttons to trainer attributes
            document.querySelectorAll('.attr-box').forEach(box => {
                const label = box.querySelector('label')?.textContent?.trim();
                const statMap = { 'FOR': 'str', 'DES': 'dex', 'CON': 'con', 'INT': 'int', 'SAB': 'wis', 'CAR': 'cha' };
                const statKey = statMap[label];
                if (statKey && !box.querySelector('.trainer-stat-btn')) {
                    const btn = document.createElement('button');
                    btn.className = 'btn btn-sm btn-success trainer-stat-btn';
                    btn.style.cssText = 'margin-top:0.3rem;width:100%;';
                    btn.textContent = '+1';
                    btn.onclick = () => distributeTrainerStat(statKey, label);
                    box.appendChild(btn);
                }
            });
        }
    }
});

function distributeTrainerStat(statKey, label) {
    const trainerLevel = TRAINER_DATA.level || 1;
    const usedPoints = TRAINER_DATA.trainerStatPointsUsed || 0;
    
    let totalPoints = 0;
    for (const [lv, reward] of Object.entries(TRAINER_LEVEL_REWARDS)) {
        if (parseInt(lv) <= trainerLevel) totalPoints += reward.stat_points;
    }
    
    const available = totalPoints - usedPoints;
    if (available <= 0) {
        alert('Sem pontos disponíveis!');
        return;
    }
    
    // Apply
    const input = document.getElementById(`trainer-${statKey}`);
    const current = parseInt(input.value) || 10;
    input.value = current + 1;
    TRAINER_DATA[statKey] = current + 1;
    TRAINER_DATA.trainerStatPointsUsed = usedPoints + 1;
    
    // Update modifier display
    updateModifiers();
    
    // Update notice
    const newAvailable = available - 1;
    const notice = document.getElementById('trainer-points-notice');
    if (newAvailable <= 0) {
        if (notice) notice.remove();
        document.querySelectorAll('.trainer-stat-btn').forEach(b => b.remove());
    } else {
        if (notice) notice.innerHTML = `⬆️ Você tem <strong>${newAvailable}</strong> ponto(s) de atributo para distribuir!`;
    }
    
    // Save
    saveTrainerData();
}


// ============================================
// DODGE SYSTEM
// ============================================
window.playerDodging = false;
window.enemyDodging = false;

function toggleDodge() {
    window.playerDodging = !window.playerDodging;
    const btn = document.getElementById('btn-dodge');
    if (window.playerDodging) {
        btn.textContent = '🏃 Esquiva: ON';
        btn.style.background = 'var(--accent)';
        btn.style.color = 'var(--dark)';
        addBattleLog('🏃 Modo Esquiva ATIVADO! AC usa SPE. Se acertado: ×1.25 dano.');
    } else {
        btn.textContent = '🏃 Esquiva: OFF';
        btn.style.background = '';
        btn.style.color = '';
        addBattleLog('🛡️ Modo Defesa normal. AC usa DEF/SPD.');
    }
}

// Wild pokemon randomly decides to dodge (30% chance for high SPE pokemon)
function wildDecideDodge() {
    const enemy = window.currentBattleData?.enemy;
    if (!enemy) return;
    const spe = enemy.stats?.SPE || 10;
    const def = enemy.stats?.DEF || 10;
    // Dodge if SPE is significantly higher than DEF
    if (spe > def + 3 && Math.random() < 0.35) {
        window.enemyDodging = true;
        addBattleLog('🏃 Pokémon selvagem está esquivando! (AC baseada em SPE, dano ×1.25 se acertar)');
    } else {
        window.enemyDodging = false;
    }
}


// ============================================
// STAT MIGRATION HELPER (convert old STR/DEX/CON/INT/WIS/CHA to ATK/DEF/SPA/SPD/SPE/HP)
// ============================================
function migrateStats(stats) {
    if (!stats) return { ATK: 10, DEF: 10, SPA: 10, SPD: 10, SPE: 10, HP: 10 };
    // If already has new format, return as-is
    if (stats.ATK !== undefined) return stats;
    // Convert from old format
    return {
        ATK: stats.STR || 10,
        DEF: stats.CON || 10,
        SPA: stats.INT || 10,
        SPD: stats.WIS || 10,
        SPE: stats.DEX || 10,
        HP: stats.CON || 10
    };
}

// ============================================================
// SPECIAL EVOLUTIONS (Stone / Friendship / Trade)
// ============================================================

// Evolution stones and trade items — for bag filtering
const EVOLUTION_STONES = new Set([
    'fire stone','water stone','thunder stone','leaf stone',
    'moon stone','sun stone','shiny stone','dusk stone',
    'dawn stone','ice stone',
    "king's rock",'metal coat','dragon scale','up-grade',
    'dubious disc','reaper cloth','protector','electirizer',
    'magmarizer','prism scale'
]);

function openUseStoneModal(pokemonIdx) {
    const poke = playerTeam[pokemonIdx];
    if (!poke) return;

    // Filter bag for evolution items
    const stoneItems = (window.bagItems || []).filter(item =>
        item.qty > 0 && EVOLUTION_STONES.has((item.name || '').toLowerCase())
    );

    if (!stoneItems.length) {
        alert('Você não tem pedras de evolução na bolsa.\nPedras: Fire Stone, Water Stone, Thunder Stone, Leaf Stone, Moon Stone, Sun Stone, Shiny Stone, Dusk Stone, Dawn Stone, Ice Stone — e itens de trade como Metal Coat, King\'s Rock, etc.');
        return;
    }

    const options = stoneItems.map((item, j) =>
        `<button class="btn btn-secondary" style="margin:0.25rem;" onclick="applyEvolutionStone(${pokemonIdx},'${item.name.replace(/'/g,"\\'")}')">
            ${item.name} (${item.qty}x)
        </button>`
    ).join('');

    // Simple inline modal using a floating div
    const existing = document.getElementById('stone-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'stone-modal';
    modal.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:var(--card-bg);border:2px solid var(--accent);border-radius:var(--radius);padding:1.5rem;min-width:280px;max-width:400px;box-shadow:0 8px 32px rgba(0,0,0,0.5)';
    modal.innerHTML = `
        <h3 style="margin-bottom:1rem;">💎 Usar Pedra em ${poke.nickname || poke.name}</h3>
        <p style="color:var(--muted);font-size:0.9rem;margin-bottom:1rem;">Escolha uma pedra da bolsa:</p>
        <div style="display:flex;flex-wrap:wrap;gap:0.25rem;">${options}</div>
        <div style="margin-top:1rem;text-align:right;">
            <button class="btn btn-sm btn-danger" onclick="document.getElementById('stone-modal').remove()">Fechar</button>
        </div>`;
    document.body.appendChild(modal);
}

async function applyEvolutionStone(pokemonIdx, itemName) {
    document.getElementById('stone-modal')?.remove();
    const poke = playerTeam[pokemonIdx];

    const res = await fetch('/player/use-stone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pokemon_idx: pokemonIdx, item_name: itemName })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
        showNotification(data.error || 'Não foi possível evoluir.', 'error');
        return;
    }

    // Update local team
    playerTeam[pokemonIdx] = data.pokemon;
    // Remove stone from bag
    const bagEntry = (window.bagItems || []).find(i => i.name?.toLowerCase() === itemName.toLowerCase());
    if (bagEntry) bagEntry.qty = Math.max(0, (bagEntry.qty || 1) - 1);

    playerTeam[pokemonIdx] = data.pokemon;
    await triggerEvolutionSequence({
        from: poke.nickname || poke.name, to: data.evolved_into,
        old_number: poke.number || 0, new_number: data.new_number || data.pokemon?.number || 0,
        new_moves: data.new_moves || []
    });
    refreshTeamDisplay();
}

async function friendshipEvolve(pokemonIdx) {
    const poke = playerTeam[pokemonIdx];
    if (!confirm(`Evoluir ${poke.nickname || poke.name} por amizade?\n(${poke.battle_wins || 0} batalhas vencidas)`)) return;

    const res = await fetch('/player/friendship-evolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pokemon_idx: pokemonIdx })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
        showNotification(data.error || 'Não foi possível evoluir.', 'error');
        return;
    }

    playerTeam[pokemonIdx] = data.pokemon;
    await triggerEvolutionSequence({
        from: poke.nickname || poke.name, to: data.evolved_into,
        old_number: poke.number || 0, new_number: data.pokemon?.number || 0,
        new_moves: data.new_moves || []
    });
    refreshTeamDisplay();
}

// Socket event when any pokemon evolves (for teammates to see in master panel)
socket.on('pokemon_evolved', (data) => {
    if (data.player_id === window.CURRENT_USER_ID) {
        // Already handled above via the HTTP response; just refresh team if needed
        fetch('/player/team-data').then(r => r.json()).then(team => {
            if (team && team.length) {
                playerTeam.length = 0;
                team.forEach(p => playerTeam.push(p));
                refreshTeamDisplay();
            }
        });
    }
});

// ============================================================
// EVOLUTION ANIMATION & MOVE DICE UPGRADE
// ============================================================

function triggerEvolutionSequence(evo) {
    return new Promise(resolve => {
        const oldSprite = getPokemonSpriteUrl(evo.old_number || 0);
        const newSprite  = getPokemonSpriteUrl(evo.new_number || 0);
        const newMovesHtml = (evo.new_moves && evo.new_moves.length)
            ? `<div style="margin-top:1rem;background:rgba(255,255,255,0.08);padding:0.75rem;border-radius:8px;">
                   <p style="color:#7fff00;margin:0 0 0.4rem;">🎯 Novos golpes disponíveis:</p>
                   <div style="display:flex;flex-wrap:wrap;gap:0.4rem;">
                       ${evo.new_moves.map(m => `<span style="background:#1a1a3e;border:1px solid #7fff00;padding:0.2rem 0.7rem;border-radius:4px;font-size:0.85rem;">${m}</span>`).join('')}
                   </div>
               </div>`
            : '';

        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:#000;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;transition:background 0.2s;';
        overlay.innerHTML = `
            <style>
                @keyframes evo-pulse { 0%,100%{filter:brightness(1)} 50%{filter:brightness(3) saturate(0)} }
                @keyframes evo-appear { from{opacity:0;transform:scale(0.5)} to{opacity:1;transform:scale(1)} }
            </style>
            <h2 id="evo-title" style="color:#ffd700;font-size:2rem;margin-bottom:1.5rem;text-shadow:0 0 20px #ffd700;">✨ EVOLUINDO! ✨</h2>
            <img id="evo-sprite" src="${oldSprite}" style="width:160px;height:160px;image-rendering:pixelated;animation:evo-pulse 1s infinite;">
            <p id="evo-subtext" style="margin:1rem;font-size:1.1rem;color:#aaa;">${evo.from} está evoluindo...</p>
            <div id="evo-details" style="display:none;max-width:480px;text-align:center;">${newMovesHtml}</div>
            <button id="evo-btn" style="display:none;margin-top:1.5rem;background:#ffd700;color:#000;border:none;padding:0.75rem 2.5rem;border-radius:8px;font-size:1rem;font-weight:bold;cursor:pointer;">✨ Incrível!</button>
        `;
        document.body.appendChild(overlay);

        // Phase 1: white flash after 1.4s
        setTimeout(() => {
            overlay.style.background = '#fff';
        }, 1400);

        // Phase 2: reveal new sprite after flash
        setTimeout(() => {
            overlay.style.background = '#000';
            const spriteEl = document.getElementById('evo-sprite');
            spriteEl.style.animation = 'evo-appear 0.6s ease forwards';
            spriteEl.src = newSprite;
            document.getElementById('evo-title').textContent = `✨ ${evo.from} evoluiu para ${evo.to}! ✨`;
            document.getElementById('evo-title').style.color = '#7fff00';
            document.getElementById('evo-title').style.textShadow = '0 0 20px #7fff00';
            document.getElementById('evo-subtext').textContent = '🎉 Parabéns!';
            document.getElementById('evo-subtext').style.color = '#ffd700';
            document.getElementById('evo-details').style.display = 'block';
            const btn = document.getElementById('evo-btn');
            btn.style.display = 'inline-block';
            btn.onclick = () => { overlay.remove(); resolve(); };
        }, 1700);
    });
}

function checkMoveDiceUpgrades(poke, oldLevel, newLevel) {
    const pokeName = poke.nickname || poke.name;
    for (const moveName of (poke.moves || [])) {
        const m = MOVES_CACHE[moveName];
        if (!m || !m.higherLevels) continue;
        const lvMatches = [...m.higherLevels.matchAll(/(\d+d\d+)\s+no\s+n[ií]vel\s+(\d+)/gi)];
        for (const lm of lvMatches) {
            const threshold = parseInt(lm[2]) * 5; // trainer lv → pokemon lv
            if (oldLevel < threshold && newLevel >= threshold) {
                const msg = `🎲 <strong>${pokeName}</strong> — <strong>${moveName}</strong> evoluiu para <strong>${lm[1]}</strong>!`;
                // Show in battle log if in battle, else notification
                if (document.getElementById('battle-log-full')) addBattleLog(msg);
                else showNotification(`${pokeName}: ${moveName} → ${lm[1]}`, 'success');
            }
        }
    }
}

async function checkServerEvolution(slotIdx) {
    try {
        const res  = await fetch('/player/level-evolve', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ slot: slotIdx })
        });
        const data = await res.json();
        if (!data.evolved) return;
        // Update local team
        playerTeam[slotIdx] = data.pokemon;
        await triggerEvolutionSequence({
            from: data.old_name, to: data.pokemon.name,
            old_number: data.old_number, new_number: data.new_number,
            new_moves: data.new_moves || []
        });
        refreshTeamDisplay();
    } catch(e) { console.error('Evolution check failed', e); }
}

// battle_wins tracking is already integrated into endBattle above

// ============================================================
// PC / BOX STORAGE
// ============================================================

let pcBoxData   = [];
let pcItemsData = [];

async function loadPC() {
    try {
        const [pcRes, itemsRes] = await Promise.all([fetch('/player/pc'), fetch('/player/pc/items')]);
        pcBoxData   = await pcRes.json();
        pcItemsData = await itemsRes.json();
        renderPC();
    } catch(e) { console.error('loadPC', e); }
}

function renderPC() {
    const team    = playerTeam;
    const box     = pcBoxData;
    const teamEl  = document.getElementById('pc-team-list');
    const boxEl   = document.getElementById('pc-box-list');
    const teamCnt = document.getElementById('pc-team-count');
    const boxCnt  = document.getElementById('pc-box-count');
    const emptyEl = document.getElementById('pc-box-empty');
    if (!teamEl || !boxEl) return;

    if (teamCnt) teamCnt.textContent = team.length;
    if (boxCnt)  boxCnt.textContent  = box.length;
    const itemsCntEl = document.getElementById('pc-items-count');
    if (itemsCntEl) itemsCntEl.textContent = pcItemsData.reduce((s, i) => s + (i.qty || 1), 0);

    teamEl.innerHTML = team.map((p, i) => pcPokemonCard(p, i, 'team')).join('');

    if (!box.length) {
        boxEl.innerHTML = '';
        if (emptyEl) emptyEl.style.display = 'block';
    } else {
        if (emptyEl) emptyEl.style.display = 'none';
        boxEl.innerHTML = box.map((p, i) => pcPokemonCard(p, i, 'box')).join('');
    }
}

function pcPokemonCard(p, idx, source) {
    const hpPct   = p.maxHp ? Math.round((p.currentHp / p.maxHp) * 100) : 100;
    const hpColor = hpPct > 50 ? '#4caf50' : hpPct > 20 ? '#ff9800' : '#f44336';
    const typeHtml = (p.types || []).map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('');
    const name    = p.nickname || p.name;

    const actionBtn = source === 'team'
        ? `<button class="btn btn-sm btn-secondary" onclick="pcDeposit(${idx})" ${playerTeam.length <= 1 ? 'disabled title="Último Pokémon!"' : ''}>→ PC</button>`
        : `<button class="btn btn-sm btn-primary" onclick="pcWithdraw(${idx})" ${playerTeam.length >= 6 ? 'disabled title="Time cheio!"' : ''}>← Time</button>`;

    const swapBtn = source === 'box' && playerTeam.length > 0
        ? `<button class="btn btn-sm btn-secondary" onclick="openSwapModal(${idx})" title="Trocar direto com um do time">⇄</button>`
        : '';

    return `<div style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0.75rem;background:var(--darker);border-radius:var(--radius);">
        <img src="${getPokemonSpriteUrl(p.number||0)}" style="width:40px;height:40px;object-fit:contain;">
        <div style="flex:1;min-width:0;">
            <div style="font-weight:bold;font-size:0.9rem;">${name} <span style="color:var(--muted);font-size:0.8rem;">Nv.${p.level}</span></div>
            <div style="display:flex;gap:0.25rem;flex-wrap:wrap;margin:0.1rem 0;">${typeHtml}</div>
            <div style="height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:2px;">
                <div style="width:${hpPct}%;height:100%;background:${hpColor};"></div>
            </div>
            <div style="font-size:0.75rem;color:var(--muted);">HP ${p.currentHp}/${p.maxHp}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:0.25rem;">${actionBtn}${swapBtn}</div>
    </div>`;
}

async function pcDeposit(teamIdx) {
    if (playerTeam.length <= 1) { showNotification('Não pode depositar o último Pokémon!', 'error'); return; }
    const res  = await fetch('/player/pc/deposit', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ team_idx: teamIdx })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }
    // Sync local state
    playerTeam.length = 0; data.team.forEach(p => playerTeam.push(p));
    pcBoxData = data.pc;
    renderPC();
    refreshTeamDisplay();
}

async function pcWithdraw(pcIdx) {
    if (playerTeam.length >= 6) { showNotification('Time cheio! Deposite um Pokémon primeiro.', 'error'); return; }
    const res  = await fetch('/player/pc/withdraw', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ pc_idx: pcIdx })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }
    playerTeam.length = 0; data.team.forEach(p => playerTeam.push(p));
    pcBoxData = data.pc;
    renderPC();
    refreshTeamDisplay();
}

function openSwapModal(pcIdx) {
    const existing = document.getElementById('swap-modal');
    if (existing) existing.remove();

    const pcPoke = pcBoxData[pcIdx];
    const options = playerTeam.map((p, i) => {
        const name = p.nickname || p.name;
        return `<button class="btn btn-secondary" style="margin:0.2rem;width:100%;text-align:left;"
                    onclick="pcSwap(${i},${pcIdx})">
                    ${name} Nv.${p.level} (HP ${p.currentHp}/${p.maxHp})
                </button>`;
    }).join('');

    const modal = document.createElement('div');
    modal.id = 'swap-modal';
    modal.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:var(--card-bg);border:2px solid var(--accent);border-radius:var(--radius);padding:1.5rem;min-width:280px;max-width:360px;box-shadow:0 8px 32px rgba(0,0,0,0.5)';
    modal.innerHTML = `
        <h3 style="margin-bottom:0.75rem;">⇄ Trocar com ${pcPoke.nickname||pcPoke.name}</h3>
        <p style="color:var(--muted);font-size:0.85rem;margin-bottom:0.75rem;">Escolha qual Pokémon do time sai:</p>
        <div>${options}</div>
        <div style="margin-top:1rem;text-align:right;">
            <button class="btn btn-sm btn-danger" onclick="document.getElementById('swap-modal').remove()">Cancelar</button>
        </div>`;
    document.body.appendChild(modal);
}

async function pcSwap(teamIdx, pcIdx) {
    document.getElementById('swap-modal')?.remove();
    const res  = await fetch('/player/pc/swap', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ team_idx: teamIdx, pc_idx: pcIdx })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }
    playerTeam.length = 0; data.team.forEach(p => playerTeam.push(p));
    pcBoxData = data.pc;
    renderPC();
    refreshTeamDisplay();
    showNotification('Pokémon trocado!', 'success');
}

// Load PC when tab is opened
document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="pc"]')?.addEventListener('click', loadPC);
});

// ============================================================
// PC — ITEM STORAGE
// ============================================================
let _currentPcView = 'pokemon';

function showPcView(view) {
    _currentPcView = view;
    document.getElementById('pc-view-pokemon').style.display = view === 'pokemon' ? '' : 'none';
    document.getElementById('pc-view-items').style.display   = view === 'items'   ? '' : 'none';
    document.getElementById('pc-view-pokemon-btn').className = view === 'pokemon' ? 'btn btn-primary' : 'btn btn-secondary';
    document.getElementById('pc-view-items-btn').className   = view === 'items'   ? 'btn btn-primary' : 'btn btn-secondary';
    if (view === 'items') renderPcItems();
}

function renderPcItems() {
    const bag     = TRAINER_DATA.bag || [];
    const bagEl   = document.getElementById('pc-bag-list');
    const itemsEl = document.getElementById('pc-items-list');
    const bagEmp  = document.getElementById('pc-bag-empty');
    const itmEmp  = document.getElementById('pc-items-empty');
    if (!bagEl || !itemsEl) return;

    const bagItems = bag.filter(b => b && typeof b === 'object' && b.name);
    bagEl.innerHTML = bagItems.map(item => `
        <div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.6rem;background:var(--darker);border-radius:var(--radius);">
            <span style="flex:1;font-size:0.9rem;">${item.name} <span style="color:var(--muted)">×${item.qty||1}</span></span>
            <input type="number" min="1" max="${item.qty||1}" value="1" id="bag-deposit-qty-${item.name.replace(/\s/g,'_')}" style="width:50px;font-size:0.8rem;padding:0.2rem;">
            <button class="btn btn-sm btn-secondary" onclick="pcDepositItem('${item.name.replace(/'/g,"\\'")}')">→ PC</button>
        </div>`).join('');
    if (bagEmp) bagEmp.style.display = bagItems.length ? 'none' : 'block';

    itemsEl.innerHTML = pcItemsData.map(item => `
        <div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.6rem;background:var(--darker);border-radius:var(--radius);">
            <span style="flex:1;font-size:0.9rem;">${item.name} <span style="color:var(--muted)">×${item.qty||1}</span></span>
            <input type="number" min="1" max="${item.qty||1}" value="1" id="pc-withdraw-qty-${item.name.replace(/\s/g,'_')}" style="width:50px;font-size:0.8rem;padding:0.2rem;">
            <button class="btn btn-sm btn-primary" onclick="pcWithdrawItem('${item.name.replace(/'/g,"\\'")}')">← Bolsa</button>
        </div>`).join('');
    if (itmEmp) itmEmp.style.display = pcItemsData.length ? 'none' : 'block';

    const total = pcItemsData.reduce((s, i) => s + (i.qty || 1), 0);
    const cntEl = document.getElementById('pc-items-count');
    if (cntEl) cntEl.textContent = total;
}

async function pcDepositItem(itemName) {
    const key = itemName.replace(/\s/g,'_');
    const qty = parseInt(document.getElementById(`bag-deposit-qty-${key}`)?.value || 1);
    const res  = await fetch('/player/pc/items/deposit', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ item_name: itemName, qty })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }
    TRAINER_DATA.bag = data.bag;
    pcItemsData = data.pc_items;
    renderPcItems();
    showNotification(`${qty}x ${itemName} depositado no PC.`, 'success');
}

async function pcWithdrawItem(itemName) {
    const key = itemName.replace(/\s/g,'_');
    const qty = parseInt(document.getElementById(`pc-withdraw-qty-${key}`)?.value || 1);
    const res  = await fetch('/player/pc/items/withdraw', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ item_name: itemName, qty })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }
    TRAINER_DATA.bag = data.bag;
    pcItemsData = data.pc_items;
    renderPcItems();
    showNotification(`${qty}x ${itemName} retirado do PC.`, 'success');
}

// ============================================================
// POKÉMART / SHOP
// ============================================================
let _shopCatalog = [];
let _shopFilter  = '';

async function loadShop() {
    if (_shopCatalog.length) { renderShop(); return; }
    try {
        const res = await fetch('/api/shop');
        _shopCatalog = await res.json();
        renderShop();
    } catch(e) { console.error('loadShop', e); }
}

function filterShop(cat) {
    _shopFilter = cat;
    renderShop();
}

function renderShop() {
    const moneyEl = document.getElementById('shop-money-display');
    if (moneyEl) moneyEl.textContent = (TRAINER_DATA.money || 0).toLocaleString('pt-BR');

    const list = _shopFilter ? _shopCatalog.filter(i => i.category === _shopFilter) : _shopCatalog;
    const grid = document.getElementById('shop-grid');
    if (!grid) return;

    const catLabels = { pokeball:'⚪ Pokébolas', medicine:'💊 Medicina', battle:'⚔️ Batalha', evo_stone:'💎 Pedra Evo', held:'📎 Segurado', special:'✨ Especial' };
    const catColors = { pokeball:'#e53935', medicine:'#4caf50', battle:'#ff9800', evo_stone:'#9c27b0', held:'#2196f3', special:'#ffb300' };

    grid.innerHTML = list.map(item => {
        const canAfford = (TRAINER_DATA.money || 0) >= item.price;
        const color = catColors[item.category] || 'var(--accent)';
        return `<div class="card" style="border-left:4px solid ${color};padding:0.75rem;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.3rem;">
                <strong style="font-size:0.95rem;">${item.name}</strong>
                <span style="color:${color};font-weight:bold;white-space:nowrap;">₽${item.price.toLocaleString('pt-BR')}</span>
            </div>
            <p style="color:var(--muted);font-size:0.8rem;margin:0 0 0.5rem;">${item.description}</p>
            <div style="display:flex;align-items:center;gap:0.4rem;">
                <input type="number" id="shop-qty-${item.id}" value="1" min="1" max="99"
                       style="width:55px;font-size:0.85rem;padding:0.25rem 0.4rem;">
                <button class="btn btn-sm ${canAfford ? 'btn-primary' : 'btn-secondary'}"
                        onclick="buyItem('${item.id}')" ${canAfford ? '' : 'style="opacity:0.5;"'}>
                    🛒 Comprar
                </button>
            </div>
        </div>`;
    }).join('');
}

async function buyItem(itemId) {
    const qty = parseInt(document.getElementById(`shop-qty-${itemId}`)?.value || 1);
    const item = _shopCatalog.find(i => i.id === itemId);
    if (!item) return;
    const total = item.price * qty;
    if (!confirm(`Comprar ${qty}x ${item.name} por ₽${total.toLocaleString('pt-BR')}?`)) return;

    const res  = await fetch('/api/shop/buy', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ item_id: itemId, qty })
    });
    const data = await res.json();
    if (data.error) { showNotification(data.error, 'error'); return; }

    TRAINER_DATA.money = data.money_left;
    // Sync bag
    const existing = (TRAINER_DATA.bag || []).find(b => b && b.name?.toLowerCase() === item.name.toLowerCase());
    if (existing) {
        existing.qty = (existing.qty || 1) + qty;
    } else {
        if (!TRAINER_DATA.bag) TRAINER_DATA.bag = [];
        TRAINER_DATA.bag.push({ name: item.name, qty, description: item.description });
    }
    renderShop();
    showNotification(`✅ ${qty}x ${item.name} comprado! Saldo: ₽${data.money_left.toLocaleString('pt-BR')}`, 'success');
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="shop"]')?.addEventListener('click', loadShop);
});

// ============================================================
// COUNTDOWN TIMER (turno do jogador nas batalhas)
// ============================================================
let _turnTimer = null;
let _turnSeconds = 0;
const TURN_LIMIT = 60;

function startTurnCountdown() {
    clearTurnCountdown();
    _turnSeconds = TURN_LIMIT;
    _updateCountdownUI();
    _turnTimer = setInterval(() => {
        _turnSeconds--;
        _updateCountdownUI();
        if (_turnSeconds <= 0) {
            clearTurnCountdown();
            if (battleActive && window.currentTurn === 'player' && !window.wildFainted) {
                addBattleLog(`⏰ <strong>Tempo esgotado! Turno passado automaticamente.</strong>`);
                passTurn();
            }
        }
    }, 1000);
}

function clearTurnCountdown() {
    if (_turnTimer) { clearInterval(_turnTimer); _turnTimer = null; }
    const el = document.getElementById('turn-countdown');
    if (el) el.textContent = '';
}

function _updateCountdownUI() {
    let el = document.getElementById('turn-countdown');
    if (!el) {
        const passBtn = document.getElementById('btn-pass-turn');
        if (passBtn) {
            el = document.createElement('span');
            el.id = 'turn-countdown';
            el.style.cssText = 'margin-left:0.75rem;font-size:0.9rem;font-weight:bold;';
            passBtn.parentNode.insertBefore(el, passBtn.nextSibling);
        }
    }
    if (el) {
        const color = _turnSeconds <= 10 ? '#f44336' : _turnSeconds <= 20 ? '#ff9800' : 'var(--text-muted)';
        el.style.color = color;
        el.textContent = `⏱ ${_turnSeconds}s`;
    }
}

// Countdown integrado diretamente em updateTurnUI acima

// ============================================================
// GYMS & LEAGUE
// ============================================================

let allGyms = [];
let leagueData = null;

async function loadGyms() {
    try {
        const res = await fetch('/api/gyms');
        allGyms = await res.json();
        renderGyms();
    } catch(e) { console.error('loadGyms', e); }
}

async function loadLeague() {
    try {
        const res = await fetch('/api/league');
        leagueData = await res.json();
        renderLeague();
    } catch(e) { console.error('loadLeague', e); }
}

function renderBadges() {
    const badges = TRAINER_DATA.badges || [];
    const el = document.getElementById('player-badges-display');
    if (!el) return;
    if (!badges.length) {
        el.innerHTML = '<em style="color:var(--muted)">Nenhuma insígnia ainda.</em>';
        return;
    }
    el.innerHTML = badges.map(b => {
        const gym = allGyms.find(g => g.badge_name === b);
        const icon = gym ? gym.badge_icon : '🏅';
        return `<span title="${b}" style="font-size:1.6rem;cursor:default">${icon}</span>
                <span style="font-size:0.8rem;color:var(--muted)">${b}</span>`;
    }).join('');
}

function renderGyms() {
    const el = document.getElementById('gyms-list');
    if (!el) return;
    if (!allGyms.length) {
        el.innerHTML = '<em style="color:var(--muted)">Nenhum ginásio configurado pelo Mestre ainda.</em>';
        renderBadges();
        return;
    }
    const badges = TRAINER_DATA.badges || [];
    const sorted = [...allGyms].sort((a, b) => (a.order || 0) - (b.order || 0));

    el.innerHTML = sorted.map(gym => {
        const conquered = badges.includes(gym.badge_name);
        const reqMet = (gym.required_badges || []).every(b => badges.includes(b));
        const locked = !reqMet && !conquered;

        let statusBadge = '';
        if (conquered)      statusBadge = '<span style="color:#4caf50;font-weight:bold">✅ Conquistado</span>';
        else if (locked)    statusBadge = '<span style="color:#f44336">🔒 Bloqueado</span>';
        else                statusBadge = '<span style="color:#ff9800">⚔️ Disponível</span>';

        const reqText = gym.required_badges?.length
            ? `<div style="font-size:0.8rem;color:var(--muted)">Requer: ${gym.required_badges.join(', ')}</div>` : '';

        const challengeBtn = (!conquered && !locked)
            ? `<button class="btn btn-sm btn-primary" onclick="challengeGym('${gym.id}')">⚔️ Desafiar</button>` : '';

        return `<div style="display:flex;align-items:center;gap:1rem;padding:0.75rem;background:var(--darker);border-radius:var(--radius);${locked?'opacity:0.6':''}">
            <span style="font-size:2rem">${gym.badge_icon || '🏅'}</span>
            <div style="flex:1">
                <div style="font-weight:bold">${gym.name}</div>
                <div style="font-size:0.85rem;color:var(--muted)">Líder: ${gym.leader_name} • Tipo: ${gym.type} • Insígnia: ${gym.badge_name}</div>
                ${reqText}
                ${gym.description ? `<div style="font-size:0.8rem;color:var(--muted)">${gym.description}</div>` : ''}
            </div>
            <div style="text-align:right">
                ${statusBadge}
                <div style="margin-top:0.25rem">${challengeBtn}</div>
            </div>
        </div>`;
    }).join('');

    renderBadges();
    checkLeagueUnlock();
}

function checkLeagueUnlock() {
    const badges = TRAINER_DATA.badges || [];
    const allBadges = allGyms.map(g => g.badge_name);
    const hasAll = allBadges.length > 0 && allBadges.every(b => badges.includes(b));
    const btn = document.getElementById('btn-league-start');
    const msg = document.getElementById('league-status-msg');
    if (btn) btn.classList.toggle('hidden', !hasAll);
    if (msg && hasAll) msg.textContent = 'Você tem todas as insígnias! Está pronto para desafiar a Liga.';
}

function renderLeague() {
    if (!leagueData) return;
    const slots = leagueData.slots || [];
    const run   = leagueData.my_run;
    const slotsEl = document.getElementById('league-slots-display');
    if (slotsEl) {
        if (!slots.length) {
            slotsEl.innerHTML = '<em style="color:var(--muted)">Liga não configurada ainda.</em>';
        } else {
            slotsEl.innerHTML = slots.map((s, i) => {
                const done = run && run.current_slot > i && run.status !== 'failed';
                const isCurrent = run && run.current_slot === i && run.status === 'in_progress';
                const label = s.is_champion ? '👑 Campeão' : `Elite ${i+1}`;
                return `<div style="padding:0.4rem 0.8rem;background:var(--darker);border-radius:var(--radius);font-size:0.85rem;${done?'border:1px solid #4caf50':''}${isCurrent?'border:1px solid #ff9800':''}">
                    ${done ? '✅' : isCurrent ? '⚔️' : '◻️'} ${label}: ${s.leader_name || s.title || `Membro ${i+1}`}
                </div>`;
            }).join('');
        }
    }

    const progress = document.getElementById('league-run-progress');
    const slotLabel = document.getElementById('league-run-slot-label');
    if (run && run.status === 'in_progress' && progress && slotLabel) {
        const cur = slots[run.current_slot];
        slotLabel.textContent = cur ? ` ${cur.title || cur.leader_name || `Membro ${run.current_slot+1}`}` : '';
        progress.classList.remove('hidden');
        document.getElementById('btn-league-start')?.classList.add('hidden');
    }
}

function challengeGym(gymId) {
    socket.emit('gym_challenge', { gym_id: gymId });
}

function startLeagueChallenge() {
    socket.emit('league_challenge_start', {});
}

// Socket handlers for gyms/league
socket.on('gyms_updated', data => {
    allGyms = data.gyms || [];
    renderGyms();
});

socket.on('gym_error', data => {
    showNotification(data.msg || 'Erro no ginásio', 'error');
});

socket.on('gym_challenge_sent', data => {
    showNotification(data.msg, 'info');
});

socket.on('gym_challenge_incoming', data => {
    if (confirm(`${data.challenger_name} quer desafiar seu ginásio "${data.gym_name}"!\nAceitar o desafio?`)) {
        socket.emit('gym_challenge_accept', { gym_id: data.gym_id, challenger_id: data.challenger_id });
    }
});

socket.on('badge_awarded', data => {
    if (!TRAINER_DATA.badges) TRAINER_DATA.badges = [];
    if (!TRAINER_DATA.badges.includes(data.badge)) {
        TRAINER_DATA.badges.push(data.badge);
    }
    renderGyms();
    showNotification(`🏅 Insígnia conquistada: ${data.icon} ${data.badge} (${data.gym_name})`, 'success');
    // Switch to gyms tab to show new badge
    document.querySelector('[data-tab="gyms"]')?.click();
});

socket.on('league_error', data => {
    showNotification(data.msg, 'error');
});

socket.on('league_run_started', data => {
    leagueData = { ...(leagueData || {}), slots: data.slots, my_run: data.run };
    renderLeague();
    showNotification('🌟 Tentativa na Liga iniciada! Boa sorte!', 'info');
});

socket.on('league_next_battle', data => {
    if (leagueData?.my_run) {
        leagueData.my_run.current_slot = data.slot;
    }
    renderLeague();
    const label = data.is_champion ? '👑 Campeão' : data.slot_title;
    showNotification(`✅ Vitória! Próxima batalha: ${label}`, 'success');
});

socket.on('league_victory', data => {
    if (leagueData?.my_run) leagueData.my_run.status = 'completed';
    renderLeague();
    showNotification('🏆🌟 CAMPEÃO DA LIGA! Você venceu todos os membros!', 'success');
    alert('🏆 PARABÉNS! Você se tornou o Campeão da Liga Pokémon!');
});

socket.on('league_failed', data => {
    if (leagueData?.my_run) leagueData.my_run.status = 'failed';
    renderLeague();
    showNotification(`💀 Derrota contra ${data.slot_title}. Tentativa encerrada.`, 'error');
    loadLeague();
});

// Load gyms/league when tab is opened
document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="gyms"]')?.addEventListener('click', () => {
        loadGyms();
        loadLeague();
    });
});

// Auto-migrate team stats on load
document.addEventListener('DOMContentLoaded', () => {
    let migrated = false;
    playerTeam.forEach(poke => {
        if (poke.stats && poke.stats.STR !== undefined && poke.stats.ATK === undefined) {
            poke.stats = migrateStats(poke.stats);
            migrated = true;
        }
    });
    if (migrated) {
        saveTeam();
        console.log('Stats migrados para novo formato (ATK/DEF/SPA/SPD/SPE/HP)');
    }
});
