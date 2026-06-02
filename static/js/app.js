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

function getPokemonSpriteUrl(number) {
    // Using PokeAPI sprites
    return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${number}.png`;
}

// Close modal on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
    }
});

// Notification sound (optional)
function playNotificationSound() {
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdH+Jj4+Nh3x0bHJ+iI+OjIZ9c2tufYiPjoyGfHJrcH6Ij46Mh3xya3B+iI+OjIZ8cmtwfoiPjoyGfHJrcH6Ij46Mhnxya3B+iI+OjIZ8');
        audio.volume = 0.3;
        audio.play();
    } catch(e) {}
}
