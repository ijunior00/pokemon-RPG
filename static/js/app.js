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
