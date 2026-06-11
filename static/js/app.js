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
    // Using PokeAPI sprites - shiny uses /shiny/ path
    if (shiny) {
        return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/${number}.png`;
    }
    return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${number}.png`;
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

    const colors = { success: '#4caf50', error: '#f44336', info: '#2196f3', warning: '#ff9800' };
    const toast = document.createElement('div');
    toast.style.cssText = `background:${colors[type]||'#2196f3'};color:#fff;padding:0.75rem 1.25rem;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.3);font-size:0.9rem;max-width:320px;pointer-events:auto;animation:slideIn 0.3s ease;`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.4s'; setTimeout(() => toast.remove(), 400); }, 3500);
}

// Notification sound (optional)
function playNotificationSound() {
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdH+Jj4+Nh3x0bHJ+iI+OjIZ9c2tufYiPjoyGfHJrcH6Ij46Mh3xya3B+iI+OjIZ8cmtwfoiPjoyGfHJrcH6Ij46Mhnxya3B+iI+OjIZ8');
        audio.volume = 0.3;
        audio.play();
    } catch(e) {}
}
