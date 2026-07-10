/* ============================================
   POKEMON 5E RPG - SHARED JS
   ============================================ */

// Socket.IO connection
const socket = io();

socket.on('connect', () => {
    console.log('Conectado ao servidor!');
});

socket.on('disconnect', () => {
    console.log('Desconectado do servidor');
});

// ============================================
// THEME SYSTEM - Real-time theme updates
// ============================================
socket.on('theme_changed', (settings) => {
    applyTheme(settings);
});

function applyTheme(settings) {
    if (settings.theme) {
        document.body.setAttribute('data-theme', settings.theme);
    }
    if (settings.background) {
        document.body.setAttribute('data-bg', settings.background);
    }
    if (settings.mesa_name) {
        const brand = document.querySelector('.nav-brand span:last-child');
        if (brand) brand.textContent = settings.mesa_name;
        document.title = document.title.replace(/^[^-]+ -/, settings.mesa_name + ' -');
    }
}

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        
        // Remove active from all tabs and contents
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        
        // Activate clicked tab
        tab.classList.add('active');
        document.getElementById(`tab-${tabId}`).classList.add('active');
    });
});

// Utility functions
function showElement(id) {
    document.getElementById(id).classList.remove('hidden');
}

function hideElement(id) {
    document.getElementById(id).classList.add('hidden');
}

function formatTypes(types) {
    return types.map(t => 
        `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`
    ).join('');
}

function getPokemonSpriteUrl(number, shiny = false) {
    // Sprites LOCAIS (sem CDN externa). Shiny: pacote da 1ª geração em
    // /static/sprites/shiny; números sem sprite shiny caem no normal.
    const SHINY_MISSING = [132, 144, 145, 146, 150, 151];
    const num = typeof number === 'number' ? number : (number?.number || parseInt(number) || 0);
    if (!num) return '';
    const padded = String(num).padStart(3, '0');
    if (shiny && num <= 151 && !SHINY_MISSING.includes(num)) {
        return `/static/sprites/shiny/${padded}.gif`;
    }
    const ext = num <= 649 ? 'gif' : 'png';
    return `/static/sprites/${padded}.${ext}`;
}

// ============================================
// FOCO DE EVOLUÇÃO — overlay fullscreen exibido em TODAS as telas da mesa
// (jogadores + mestre) quando qualquer Pokémon evolui. Disparado pelo evento
// socket 'evolution_focus'. Respeita shiny nos dois sprites.
// ============================================
function showEvolutionFocus(evo) {
    return new Promise(resolve => {
        const shiny = !!evo.shiny;
        const oldSprite = getPokemonSpriteUrl(evo.old_number || 0, shiny);
        const newSprite = getPokemonSpriteUrl(evo.new_number || 0, shiny);
        const displayFrom = evo.nickname || evo.from || evo.old_name || '';
        const displayTo = evo.to || evo.new_name || '';
        const isMine = typeof window.CURRENT_USER_ID !== 'undefined'
            && String(evo.player_id || '') === String(window.CURRENT_USER_ID);
        const ownerLine = (!isMine && evo.player_name)
            ? `<p style="margin:0 0 0.8rem;color:#9ad;font-size:1rem;">Pokémon de <strong>${evo.player_name}</strong></p>`
            : '';
        const newMovesHtml = (evo.new_moves && evo.new_moves.length)
            ? `<div style="margin-top:1rem;background:rgba(255,255,255,0.08);padding:0.75rem;border-radius:8px;">
                   <p style="color:#7fff00;margin:0 0 0.4rem;">🎯 Novos golpes disponíveis:</p>
                   <div style="display:flex;flex-wrap:wrap;gap:0.4rem;justify-content:center;">
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
            ${ownerLine}
            <h2 class="evo-title" style="color:#ffd700;font-size:2rem;margin-bottom:1.5rem;text-shadow:0 0 20px #ffd700;">✨ EVOLUINDO!${shiny ? ' 🌟' : ''} ✨</h2>
            <img class="evo-sprite" src="${oldSprite}" style="width:160px;height:160px;object-fit:contain;image-rendering:pixelated;animation:evo-pulse 1s infinite;">
            <p class="evo-subtext" style="margin:1rem;font-size:1.1rem;color:#aaa;">${displayFrom} está evoluindo...</p>
            <div class="evo-details" style="display:none;max-width:480px;text-align:center;">${newMovesHtml}</div>
            <button class="evo-btn" style="display:none;margin-top:1.5rem;background:#ffd700;color:#000;border:none;padding:0.75rem 2.5rem;border-radius:8px;font-size:1rem;font-weight:bold;cursor:pointer;">✨ Incrível!</button>
        `;
        document.body.appendChild(overlay);

        // Fase 1: flash branco
        setTimeout(() => { overlay.style.background = '#fff'; }, 1400);

        // Fase 2: revela o sprite novo
        setTimeout(() => {
            overlay.style.background = '#000';
            const spriteEl = overlay.querySelector('.evo-sprite');
            spriteEl.style.animation = 'evo-appear 0.6s ease forwards';
            spriteEl.src = newSprite;
            const title = overlay.querySelector('.evo-title');
            title.textContent = `✨ ${displayFrom} evoluiu para ${displayTo}!${shiny ? ' 🌟' : ''} ✨`;
            title.style.color = '#7fff00';
            title.style.textShadow = '0 0 20px #7fff00';
            const sub = overlay.querySelector('.evo-subtext');
            sub.textContent = '🎉 Parabéns!';
            sub.style.color = '#ffd700';
            overlay.querySelector('.evo-details').style.display = 'block';
            const btn = overlay.querySelector('.evo-btn');
            btn.style.display = 'inline-block';
            btn.onclick = () => { overlay.remove(); resolve(); };
            // auto-fecha depois de 12s (espectadores não precisam clicar)
            setTimeout(() => { if (overlay.parentNode) { overlay.remove(); resolve(); } }, 12000);
        }, 1700);
    });
}

// Fila: evoluções simultâneas (ex.: /master/xp em time inteiro) aparecem em
// sequência, nunca sobrepostas.
let _evoFocusQueue = Promise.resolve();
function queueEvolutionFocus(evo) {
    _evoFocusQueue = _evoFocusQueue.then(() => showEvolutionFocus(evo));
    return _evoFocusQueue;
}

// Close modal on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
    }
});

// ============================================
// TOAST NOTIFICATIONS
// ============================================
function showNotification(message, type = 'info') {
    const container = document.getElementById('notification-container') || (() => {
        const el = document.createElement('div');
        el.id = 'notification-container';
        el.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:99999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
        document.body.appendChild(el);
        return el;
    })();

    // Visual GBA: caixa de diálogo creme com borda semântica (classes em gba.css)
    const toast = document.createElement('div');
    toast.className = `gba-toast gba-toast-${['success','error','info','warning'].includes(type) ? type : 'info'}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.4s'; setTimeout(() => toast.remove(), 400); }, 3500);
}

// Notification sound (optional - only plays after user interaction)
function playNotificationSound() {
    // Skip if user hasn't interacted with page yet (browser policy)
}
