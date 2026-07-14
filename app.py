"""
Pokemon 5e RPG - Aplicação Web Principal
Sistema de gerenciamento de mesa para Pokemon 5e com tempo real.
"""
import os
import json
import math
import random
import secrets
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import pvp_battle as pvp
import group_battle as gb
import status_effects as effects
import pokemon_scaling as scaling
import abilities as ab
import migrations
import trainer_attrs

# ============================================================
# APP SETUP
# ============================================================
import time as _time
from collections import defaultdict

app = Flask(__name__)
# SECRET_KEY assina os cookies de sessão. SEM um valor forte, qualquer um
# forja a sessão de outro usuário (inclusive mestre). Em produção o Render
# injeta um valor via env (render.yaml). Só caímos num aleatório efêmero
# em dev/local — nunca numa constante commitada no repositório.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB (upload de avatar)
app.config['REMEMBER_COOKIE_DURATION'] = 2592000  # 30 dias

# ── Endurecimento de sessão (anti roubo de cookie / CSRF) ──
# SameSite=Lax: navegador NÃO manda o cookie em POST vindo de outro site —
# fecha a classe inteira de CSRF nos endpoints JSON sem precisar de token.
# Secure só em produção (Render = HTTPS); em dev local http continuaria sem cookie.
_ON_RENDER = bool(os.environ.get('RENDER'))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_ON_RENDER,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_SECURE=_ON_RENDER,
)

# Código de fundador (opcional): se definido no ambiente, criar conta de
# MESTRE exige o código — barra os bots que acham o formulário público.
# Sem a env, vale só a fila de aprovação do super-admin (como antes).
MASTER_SIGNUP_CODE = (os.environ.get('MASTER_SIGNUP_CODE') or '').strip()

# Atrás do proxy do Render, request.remote_addr é o IP do proxy (igual p/ todos).
# ProxyFix faz o Flask ler o IP real do cliente em X-Forwarded-For, para o
# rate-limit por IP não penalizar jogadores que compartilham o proxy.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize database
db.init_db()

# Headers de segurança em TODA resposta (defesa em profundidade):
# clickjacking, sniffing de MIME, vazamento de referrer e HSTS em produção.
@app.after_request
def _security_headers(resp):
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy',
                            'camera=(), microphone=(), geolocation=()')
    if _ON_RENDER:
        resp.headers.setdefault('Strict-Transport-Security',
                                'max-age=31536000; includeSubDomains')
    return resp


# ============================================================
# RATE LIMITING (simple in-memory, resets on restart)
# ============================================================
_rate_store: dict = defaultdict(list)  # ip -> [timestamps]

# Bloqueio POR CONTA no login (independente do IP — pega ataque distribuído
# de força bruta contra um usuário específico): 5 falhas → 10 min de espera.
_login_fails: dict = defaultdict(list)  # username_lower -> [timestamps de falha]
LOGIN_LOCK_MAX = 5
LOGIN_LOCK_WINDOW = 600

def _rate_limit(max_calls: int, window_seconds: int, bucket: str = '') -> bool:
    """Return True (blocked) if IP exceeds max_calls in window_seconds.
    `bucket` isola contadores por AÇÃO (login/registro/caçada não competem
    pelo mesmo limite) — sem ele, muitas ações legítimas de um IP se somavam."""
    ip = (request.remote_addr or 'unknown') + ('|' + bucket if bucket else '')
    now = _time.time()
    calls = [t for t in _rate_store[ip] if now - t < window_seconds]
    calls.append(now)
    _rate_store[ip] = calls
    return len(calls) > max_calls

# ============================================================
# DATA LOADING (static data from JSON files)
# ============================================================
DATA_DIR = os.path.join(os.path.dirname(__file__), 'server', 'data')
POKEMON_FILE = os.path.join(DATA_DIR, 'pokemon.json')
ROUTES_FILE = os.path.join(DATA_DIR, 'routes.json')

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Load Pokemon database
POKEMON_DB = load_json(POKEMON_FILE)
POKEMON_BY_NUMBER = {p['number']: p for p in POKEMON_DB}
POKEMON_BY_NAME = {p['name'].lower(): p for p in POKEMON_DB}
POKEMON_BY_TYPE = {}
for p in POKEMON_DB:
    for t in p.get('types', []):
        POKEMON_BY_TYPE.setdefault(t.lower(), []).append(p)

# Load routes
ROUTES_DATA = load_json(ROUTES_FILE)

# Load moves database
MOVES_FILE = os.path.join(DATA_DIR, 'moves.json')
MOVES_DB = load_json(MOVES_FILE)
MOVES_BY_NAME = {k.lower(): v for k, v in MOVES_DB.items()}

# Dados canônicos (PokeAPI): power/accuracy/priority reais por move.
# Indexados pelo NOME LOCAL minúsculo para lookup direto no combate.
CANONICAL_FILE = os.path.join(DATA_DIR, 'canonical_moves.json')
_CANONICAL_RAW = load_json(CANONICAL_FILE)
_CANON_MANUAL = {'vise grip': 'vice-grip'}   # espelha a tool de build

def _canon_ident(name):
    """'King's Shield' → 'kings-shield' (regra do identifier do PokeAPI)."""
    n = (name or '').lower().replace("'", '').replace('’', '')
    n = n.replace('.', '').replace(' ', '-')
    while '--' in n:
        n = n.replace('--', '-')
    return _CANON_MANUAL.get((name or '').lower(), n)

CANON_BY_LOCAL_NAME = {}
for _mn in MOVES_DB:
    _c = _CANONICAL_RAW.get(_canon_ident(_mn))
    if _c:
        CANON_BY_LOCAL_NAME[_mn.lower()] = _c

def canon_move(move_name):
    """Registro canônico (power/accuracy/priority) de um move local, ou {}."""
    return (CANON_BY_LOCAL_NAME.get((move_name or '').lower())
            or _CANONICAL_RAW.get(_canon_ident(move_name)) or {})

# Validação ruidosa no startup: o sistema v2 depende dos datasets novos
assert _CANONICAL_RAW, 'canonical_moves.json ausente — rode tools/build_canonical_moves.py'
_no_bs = [p['name'] for p in POKEMON_DB if not p.get('base_stats')]
assert not _no_bs, f'{len(_no_bs)} espécies sem base_stats — rode tools/build_pokemon_stats.py: {_no_bs[:5]}'
for _p in POKEMON_DB:
    assert all(1 <= v <= 255 for v in _p['base_stats'].values()), \
        f"base_stats fora de 1-255: {_p['name']}"

import battle_math as bm_core

# ============================================================
# BATTLE HELPERS — server-side damage calculation
# ============================================================
import re as _re

def _prof_for_level(level):
    if level >= 91: return 10
    if level >= 81: return 9
    if level >= 71: return 8
    if level >= 61: return 7
    if level >= 51: return 6
    if level >= 41: return 5
    if level >= 31: return 4
    if level >= 17: return 3
    return 2

def _stab_for_level(level):
    if level >= 81: return 6
    if level >= 61: return 5
    if level >= 41: return 4
    if level >= 26: return 3
    if level >= 11: return 2
    return 1

def _roll_dice(dice_str):
    m = _re.match(r'(\d+)d(\d+)', str(dice_str))
    if not m: return 0
    count, sides = int(m.group(1)), int(m.group(2))
    return sum(random.randint(1, sides) for _ in range(count))

def _dice_bonus_for_level(level):
    """Bônus ADITIVO de dados por faixa de nível — encurta batalhas médias/altas
    sem tocar no início (Nv<15 sem bônus, evita swing precoce) nem em HP."""
    if level >= 70: return 3
    if level >= 40: return 2
    if level >= 15: return 1
    return 0

def _get_scaled_dice(base_damage, level, higher_levels=''):
    if not base_damage: return '1d6'
    m = _re.match(r'(\d+)d(\d+)', str(base_damage))
    if not m: return str(base_damage)
    count, sides = int(m.group(1)), int(m.group(2))
    if higher_levels:
        matches = _re.findall(r'(\d+d\d+)\s+no\s+n[ií]vel\s+(\d+)', higher_levels, _re.IGNORECASE)
        best = base_damage
        for dice_str, trainer_lv in matches:
            if level >= int(trainer_lv) * 5:
                best = dice_str
        # Os degraus do texto são esparsos (níveis 25/50/85 de Pokémon) — sem o
        # bônus aditivo o dado ficava PARADO por 20-30 níveis (ex.: 2d6 do 25 ao
        # 49) e o dano não acompanhava o HP. Soma o mesmo bônus por faixa do
        # caminho sem higherLevels (15+→+1, 40+→+2, 70+→+3 dados).
        bm = _re.match(r'(\d+)d(\d+)', str(best))
        if bm:
            return f'{int(bm.group(1)) + _dice_bonus_for_level(level)}d{bm.group(2)}'
        return best
    if level >= 80: mult = 3.0
    elif level >= 60: mult = 2.5
    elif level >= 40: mult = 2.0
    elif level >= 20: mult = 1.5
    elif level >= 10: mult = 1.25
    else: mult = 1.0
    # ceil para casar com o cliente (getScaledDice usa Math.ceil) + bônus aditivo
    new_count = max(count, math.ceil(count * mult)) + _dice_bonus_for_level(level)
    return f'{new_count}d{sides}'

_TYPE_MAP_PT = {
    'fogo':'fire','água':'water','grama':'grass','elétrico':'electric',
    'gelo':'ice','lutador':'fighting','venenoso':'poison','terra':'ground',
    'voador':'flying','psíquico':'psychic','inseto':'bug','pedra':'rock',
    'fantasma':'ghost','dragão':'dragon','sombrio':'dark','aço':'steel',
    'fada':'fairy','normal':'normal'
}

# ============================================================
# DUAS CURVAS DE MODIFICADOR (correção de balanceamento)
# ------------------------------------------------------------
# Antes: o mesmo mod = (stat-10)//2 era usado tanto pra ACERTAR
# quanto pro DANO. Em Pokémon de stat alto (ex: Snorlax DEF 20),
# isso deixava ataques de Pokémon de stat alto quase sempre
# acertando contra Pokémon comuns, e quase nunca acertando
# Pokémon de defesa também alta — dependendo de qual lado tinha
# o extremo, o resultado virava "sempre acerta" ou "nunca acerta".
#
# Agora: mod_dano (sem teto) continua sendo usado pra DANO e CA.
# mod_precisao (com teto) é usado SÓ na rolagem de acerto (d20).
# Combinado com a regra "nat 1 sempre erra, nat 20 sempre acerta"
# (já presente via is_nat1/is_crit), isso trava a chance de acerto
# entre 5% e 95% em qualquer combinação de stats do banco atual
# (6 a 30), sem precisar mudar nenhum stat salvo.
# ============================================================
def _mod_dano(stat):
    return (stat - 10) // 2

def _mod_precisao(stat, teto=4):
    raw = (stat - 10) // 4
    return max(-2, min(teto, raw))


def _type_lists(poke):
    """(vulnerabilities, resistances, immunities) em lowercase, com fallback
    nos dados-base da espécie quando o dict do pokémon não traz as listas.

    Pokémon salvos pela ficha do jogador frequentemente vêm sem 'immunities'
    (o formulário só tem vulnerabilidades) — sem o fallback, Ghost tomava
    dano de move Normal em PvP porque a lista chegava vazia no servidor."""
    if not isinstance(poke, dict):
        return [], [], []
    base = POKEMON_BY_NAME.get((poke.get('name') or '').lower()) or {}
    def pick(field):
        vals = poke.get(field)
        if not vals:  # None ou lista vazia → usa a espécie
            vals = base.get(field) or []
        return [t.lower() for t in vals]
    return pick('vulnerabilities'), pick('resistances'), pick('immunities')


# Moves "imprevisíveis" que executam OUTRO move de dano (Metronome sorteia
# qualquer um; os demais copiam/imitam — homebrew: também sorteiam).
VARIABLE_DAMAGE_MOVES = {
    'metronome': '🎶', 'mirror move': '🪞', 'copycat': '🐒', 'assist': '🤝',
    'me first': '⚡', 'mimic': '🎭', 'sketch': '✏️',
}


def _resolve_metronome(move_name):
    """Resolve um move imprevisível em um move de DANO aleatório do banco.

    Retorna (nome_final, label): label é "emoji Original → Sorteado" para o
    log quando o move era imprevisível, ou None se não era."""
    key = (move_name or '').lower()
    emoji = VARIABLE_DAMAGE_MOVES.get(key)
    if not emoji:
        return move_name, None
    pool = [n for n, md in MOVES_DB.items()
            if md.get('baseDamage') and md.get('category') in ('physical', 'special')]
    pick = random.choice(pool) if pool else 'Tackle'
    return pick, f'{emoji} {move_name} → {pick}'


# Guard de re-entrância do battle_action (por player_id) contra duplo-clique /
# duas abas. Sob gevent (cooperativo) o check+add do set é atômico.
_BATTLE_BUSY = set()
# Idem para escrita de economia (compra/venda) — impede double-spend do MESMO
# jogador em requisições paralelas (read-modify-write de dinheiro).
_ECON_BUSY = set()


def _v3_side_state(poke):
    """Estado v3 do lado (vive no dict do Pokémon em batalha — morre com ela):
    cooldowns por move, último golpe, streak (adaptação) e momentum."""
    st = poke.setdefault('_v3', {})
    st.setdefault('cooldowns', {})
    st.setdefault('last_move', None)
    st.setdefault('streak', 0)
    st.setdefault('momentum', 0)
    return st


def _v3_cooldown_left(poke, move_name):
    """Rodadas restantes de cooldown de um move (0 = livre)."""
    st = poke.get('_v3') or {}
    return int((st.get('cooldowns') or {}).get((move_name or '').lower(), 0))


def _v3_sem_opcao(poke, moves=None):
    """True se NENHUM golpe do moveset está utilizável — todos em recarga
    (golpes de cura contam a recarga-bucket compartilhada). É o gatilho da
    RODADA DE FÔLEGO: como recargas só caem quando o Pokémon age, um moveset
    de poucos golpes fortes podia travar para sempre."""
    mvs = [m for m in (moves or (poke or {}).get('moves') or []) if m]
    if not mvs:
        return False
    cds = ((poke or {}).get('_v3') or {}).get('cooldowns') or {}
    bucket = int(cds.get(effects.HEAL_SUSTAIN_KEY, 0))
    for m in mvs:
        if _v3_cooldown_left(poke, m) > 0:
            continue
        if bucket > 0:
            md = MOVES_BY_NAME.get(m.lower()) or MOVES_DB.get(m) or {}
            det = effects.auto_detect_move_effect(md) if _is_status_move(md) else None
            if det and det.get('type') in ('heal_self', 'drain_stat_heal'):
                continue
        return False   # há golpe livre — sem fôlego, ação bloqueada normal
    return True


def _v3_folego(poke, nome=''):
    """RODADA DE FÔLEGO: sem golpes disponíveis, a ação vira descanso — o
    turno passa e TODAS as recargas caem 1. Retorna a mensagem para o log."""
    st = _v3_side_state(poke)
    cds = st.setdefault('cooldowns', {})
    for k in list(cds):
        cds[k] -= 1
        if cds[k] <= 0:
            del cds[k]
    return (f'😮‍💨 {nome or (poke or {}).get("name", "Pokémon")} está sem golpes '
            f'disponíveis e recupera o fôlego — recargas −1!')


def _v3_register_use(st, move_lower, power, drain=0):
    """Registra o uso de um golpe: decrementa cooldowns (1 ação = 1 rodada do
    lado), atualiza momentum (+1 se variou, zera se repetiu; 1º golpe = 0) e
    streak (adaptação: 3ª repetição consecutiva → defensor +2). Retorna
    (momentum_deste_ataque, adapt_bonus_contra_este_ataque).
    `drain` (canônico > 0) entra na recarga de sustain (v3_move_cooldown)."""
    cds = st['cooldowns']
    for k in list(cds):
        cds[k] -= 1
        if cds[k] <= 0:
            del cds[k]
    # F5: atacar expira a própria proteção (valia só a rodada) e quebra a
    # corrente de Protects consecutivos
    st.pop('protected', None)
    st['protect_chain'] = 0
    if st['last_move'] == move_lower:
        st['streak'] += 1
        st['momentum'] = 0
    elif st['last_move'] is None:
        st['streak'] = 1
        st['momentum'] = 0
    else:
        st['streak'] = 1
        st['momentum'] = min(bm_core.V3_MOMENTUM_MAX, st['momentum'] + 1)
    st['last_move'] = move_lower
    adapt = 2 if st['streak'] >= 3 else 0
    cd = bm_core.v3_move_cooldown(power, drain) if power else 0
    if cd:
        cds[move_lower] = cd
    return st['momentum'], adapt


# ── Casos especiais da auditoria de moves (tabela do tester, jul/2026) ──
V3_RAMPAGE_MOVES = ('outrage', 'thrash', 'petal dance')      # usa → fica confuso
V3_CRASH_MOVES = ('jump kick', 'high jump kick')             # errou → se machuca
V3_SELF_KO_MOVES = ('explosion', 'self-destruct', 'self destruct')
# golpes cujo stat_change canônico NEGATIVO é no PRÓPRIO usuário (recuo)
V3_SELF_DEBUFF_MOVES = ('overheat', 'psycho boost', 'superpower', 'close combat',
                        'draco meteor', 'leaf storm', 'hammer arm', 'v-create',
                        'fleur cannon', 'dragon ascent', 'ice hammer',
                        'clanging scales', 'hyperspace fury', 'armor cannon')


def _v3_new_battle(pokes):
    """Batalha NOVA: zera o estado por-batalha (heal_uses, _weather) —
    fonte única em status_effects.new_battle_reset (PvP/grupo também usam)."""
    effects.new_battle_reset(pokes)


def _v3_reset_battle_flow(poke):
    """Troca de Pokémon: momentum e adaptação zeram; cooldowns FICAM
    (trocar não zera cooldown — regra do doc). Carga e invulnerabilidade
    (Fly/Dig) também se perdem ao sair de campo."""
    st = poke.get('_v3')
    if isinstance(st, dict):
        st['momentum'] = 0
        st['streak'] = 0
        st['last_move'] = None
        st.pop('charging', None)
        st.pop('invulnerable', None)


def _calc_attack_core(attacker_poke, defender_poke, move_name, attack_roll=None,
                      attacker_status=None, defender_status=None,
                      atk_hp=None, atk_max_hp=None, def_hp=None,
                      momentum=None, adapt_bonus=None, field=None):
    """Núcleo ÚNICO do cálculo de ataque (SISTEMA v3 — d100/ACC).

    Camadas: Precisão (d100 vs ACC efetivo) → Dano (Componente + nível +
    dados da Tabela Mestra + Momentum) → Resistência (d100 do defensor vs TN
    Efetiva → cheio/metade/anulação). Doc: docs/sistema-combate-d100.md.
    `attack_roll` é o d100 do atacante (None = servidor rola).
    `field` é o estado de campo da batalha: {'weather','terrain',...} (F5).
    Retorna {'hit','damage','message','attack_roll','move_type_en','is_crit',
    'log','outcome','cooldown','recoil','drain_heal'}.
    """
    move_name, metronome_became = _resolve_metronome(move_name)
    move = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name) or {}
    level = int(attacker_poke.get('level') or 1)
    def_level = int(defender_poke.get('level') or level)
    category = move.get('category', 'physical')

    # Move de status NUNCA rola ataque nem causa dano — roteado pelo motor
    # de efeitos (effects.process_status_move). Guarda defensiva.
    if _is_status_move(move):
        return {'hit': False, 'damage': 0, 'is_status': True,
                'message': 'Move de status — sem dano',
                'attack_roll': 0, 'move_type_en': '', 'log': ''}

    canon = canon_move(move_name)
    power = canon.get('power') or bm_core.VARIABLE_POWER.get(move_name.lower())
    accuracy = canon.get('accuracy')
    canon_drain = int(canon.get('drain') or 0)   # >0 = dreno (sustain → recarga)

    # ── F5: clima/terreno da batalha ajustam ACC e dados ──
    fld = field or {}
    weather = fld.get('weather')
    terrain = fld.get('terrain')
    # habilidades com gate de clima (Solar Power) leem o clima do próprio dict
    if isinstance(attacker_poke, dict):
        attacker_poke['_weather'] = weather
    if isinstance(defender_poke, dict):
        defender_poke['_weather'] = weather
    accuracy = bm_core.v3_weather_acc(weather, move_name, accuracy)
    certeiro = accuracy is None   # Aerial Ace, Swift... conectam sempre

    move_type_raw = (move.get('type') or '').lower()
    move_type_en = _TYPE_MAP_PT.get(move_type_raw, move_type_raw)
    met = f'<strong>{metronome_became}</strong>! ' if metronome_became else ''

    # ── Cooldown / Momentum / Adaptação (estado por lado, vive na batalha) ──
    st = _v3_side_state(attacker_poke)
    ml = move_name.lower()
    _cd_left = int(st['cooldowns'].get(ml, 0))
    if _cd_left > 0:
        return {'hit': False, 'damage': 0, 'blocked': True, 'cooldown_left': _cd_left,
                'message': f'⏳ {move_name} em cooldown ({_cd_left} rodada(s))',
                'attack_roll': 0, 'move_type_en': move_type_en,
                'log': f'⏳ <strong>{move_name}</strong> está em cooldown '
                       f'({_cd_left} rodada(s) restante(s)) — escolha outro golpe!'}

    # ── F5: golpes de PREPARO (carga: Solar Beam...; semi-invulnerável:
    # Fly/Dig/Dive...) gastam 1 rodada; Solar Beam no Sol dispara direto ──
    charging_released = False
    if bm_core.v3_needs_charge(ml, weather):
        if st.get('charging') != ml:
            st['charging'] = ml
            inv_state = bm_core.v3_semi_invuln_state(ml)
            if inv_state:
                st['invulnerable'] = inv_state   # fica fora de alcance na rodada
                aname = attacker_poke.get('nickname') or attacker_poke.get('name', 'O atacante')
                return {'hit': True, 'damage': 0, 'charging': True,
                        'message': f'{met}{aname} está {inv_state} — ataca na próxima rodada!',
                        'attack_roll': 0, 'move_type_en': move_type_en, 'cooldown': 0,
                        'log': f'{met}🕳️ <strong>{aname}</strong> usou {move_name} e está '
                               f'<strong>{inv_state}</strong> — invulnerável até atacar!'}
            return {'hit': True, 'damage': 0, 'charging': True,
                    'message': f'{met}{move_name} está carregando energia...',
                    'attack_roll': 0, 'move_type_en': move_type_en, 'cooldown': 0,
                    'log': f'{met}🔆 <strong>{move_name}</strong> carrega energia — '
                           f'dispara na próxima rodada!'}
        st.pop('charging', None)
        st.pop('invulnerable', None)   # sai da invulnerabilidade ao atacar
        charging_released = True
    elif st.get('charging'):
        st.pop('charging', None)       # trocou de golpe — perde a carga
        st.pop('invulnerable', None)

    _mom, _adapt = _v3_register_use(st, ml, power, canon_drain)
    if momentum is None:
        momentum = _mom
    if adapt_bonus is None:
        adapt_bonus = _adapt

    # ── F5: Protect/Detect do DEFENSOR bloqueia o golpe da rodada ──
    dst = defender_poke.get('_v3') if isinstance(defender_poke.get('_v3'), dict) else None
    if dst and dst.get('protected'):
        dst['protected'] = False   # a proteção é consumida pelo golpe
        dname = defender_poke.get('nickname') or defender_poke.get('name', 'O alvo')
        return {'hit': False, 'damage': 0, 'protected': True,
                'message': f'{met}{dname} se protegeu!',
                'attack_roll': 0, 'move_type_en': move_type_en,
                'cooldown': bm_core.v3_move_cooldown(power, canon_drain) if power else 0,
                'log': f'{met}🛡️ <strong>{dname}</strong> se PROTEGEU — o golpe foi bloqueado!'}

    # ── F5: Psychic Terrain bloqueia golpes de PRIORIDADE (+1 ou mais)
    # contra alvos no terreno (voadores/Levitate não tocam o chão) ──
    move_priority = int(canon.get('priority') or 0)
    if terrain == 'psychic' and move_priority > 0:
        d_types = [str(t).lower() for t in (defender_poke.get('types') or [])]
        d_levitates = ab.normalize_ability(defender_poke.get('ability')) == 'levitate'
        if 'flying' not in d_types and not d_levitates:
            return {'hit': False, 'damage': 0,
                    'message': f'{met}O Psychic Terrain bloqueou o golpe de prioridade!',
                    'attack_roll': 0, 'move_type_en': move_type_en,
                    'cooldown': bm_core.v3_move_cooldown(power, canon_drain) if power else 0,
                    'log': f'{met}🔮 <strong>Psychic Terrain</strong> protege o alvo '
                           f'contra golpes de prioridade — {move_name} falhou!'}

    # ── Alvo INVULNERÁVEL (usou Fly/Dig/Dive...): o golpe falha, exceto as
    # interações canônicas (Earthquake acerta quem cavou, Thunder quem voou).
    # Vale para TODOS os golpes — certeiro ignora evasão, não isto. ──
    d_invuln = (dst or {}).get('invulnerable')
    if d_invuln and not bm_core.v3_pierces_invuln(d_invuln, ml):
        dname = defender_poke.get('nickname') or defender_poke.get('name', 'O alvo')
        return {'hit': False, 'damage': 0,
                'message': f'{met}{dname} está {d_invuln} — fora de alcance!',
                'attack_roll': 0, 'move_type_en': move_type_en,
                'cooldown': bm_core.v3_move_cooldown(power, canon_drain) if power else 0,
                'log': f'{met}🕳️ <strong>{dname}</strong> está {d_invuln} — '
                       f'{move_name} não alcança!'}

    # ── IMUNIDADE DE TIPO — checada ANTES da precisão (ordem da spec):
    # nem ACC 100 nem certeiro atravessam imunidade natural. ──
    vulns, resists, immunities = _type_lists(defender_poke)
    eff = 1.0
    if move_type_en in immunities:
        eff = 0.0
    else:
        if move_type_en in vulns:   eff *= 2
        if move_type_en in resists: eff *= 0.5
    if eff == 0:
        return {'hit': True, 'damage': 0, 'is_crit': False,
                'message': f'{met}O alvo é IMUNE (0x)',
                'attack_roll': 0, 'move_type_en': move_type_en,
                'outcome': 'immune', 'cooldown': bm_core.v3_move_cooldown(power, canon_drain) if power else 0,
                'log': f'{met}⛔ IMUNE (0x) — {move_name} não afeta o alvo = <strong>0 dano</strong>'}

    # ── Camada 1: PRECISÃO (d100 vs ACC efetivo; certeiro conecta sempre) ──
    # estágios legados 'attack_roll'/'AC' viram estágios de Precisão/Evasão
    acc_stages = effects.attack_roll_bonus(attacker_poke)
    eva_stages = effects.ac_bonus(defender_poke)
    acc_eff = bm_core.v3_acc_effective(accuracy, acc_stages, eva_stages)
    d100 = int(attack_roll) if attack_roll is not None else random.randint(1, 100)
    acc_label = 'certeiro' if certeiro else f'ACC {acc_eff}%'

    if not bm_core.v3_connects(d100, acc_eff):
        # Crash (Jump Kick/High Jump Kick): errar machuca o usuário —
        # reutiliza o canal de recoil dos handlers (aplicado mesmo no miss)
        crash = 0
        if ml in V3_CRASH_MOVES:
            crash = max(1, int(atk_max_hp or 20) // 8)
        return {'hit': False, 'damage': 0, 'recoil': crash,
                'message': f'{met}Errou (d100 {d100} > {acc_eff})'
                           + (f' e se machucou (-{crash} HP)!' if crash else ''),
                'attack_roll': d100, 'move_type_en': move_type_en,
                'log': f'{met}❌ d100({d100}) > {acc_eff} ({acc_label}) → Errou!'
                       + (f' 💥 Errou o chute e caiu: <strong>-{crash} HP</strong>!' if crash else '')}

    # ── Crítico (d100 próprio: 5% + 10 p.p./estágio; fura a defesa) ──
    _crit_stages = bm_core.crit_stage_for(
        move_name, attacker_poke.get('ability'),
        bool(attacker_poke.get('focus_energy')))
    is_crit = random.randint(1, 100) <= bm_core.v3_crit_chance(_crit_stages)
    if ab.ability_forces_crit(attacker_poke, defender_poke):
        is_crit = True
    if ab.ability_prevents_crit(defender_poke.get('ability')):
        is_crit = False
    sniper = ab.normalize_ability(attacker_poke.get('ability')) == 'sniper'

    # ── Preparação da Resistência (defensor) ──
    def_key = 'SPD' if category == 'special' else 'DEF'
    def_stat = effects.effective_stat(defender_poke, def_key, include_stages=False)
    def_stages = effects.stat_stage(defender_poke, def_key)
    def_spe = effects.effective_stat(defender_poke, 'SPE', include_stages=False)
    atk_spe = effects.effective_stat(attacker_poke, 'SPE', include_stages=False)
    # F5: Areia protege Pedra (especial) / Granizo protege Gelo (físico)
    weather_resist = bm_core.v3_weather_resist_bonus(
        weather, defender_poke.get('types'), category)
    # F5: prioridade quebra a regra da Speed nos desempates (doc §7):
    # golpe de prioridade age "antes" → o atacante conta como mais rápido
    if move_priority > 0:
        defender_faster_tie = False
    elif move_priority < 0:
        defender_faster_tie = True
    else:
        defender_faster_tie = def_spe > atk_spe

    def _resist(gross, pw):
        """Camada 3: Resistência do defensor (d100) → (dano_final, linha de log)."""
        d100_def = random.randint(1, 100)
        total = bm_core.v3_resistance_total(
            d100_def, def_stat, def_level, def_stages,
            crit=is_crit, extra=adapt_bonus + weather_resist,
            crit_zeroes_defense=sniper)
        tn = bm_core.v3_tn(pw, level)
        outcome = bm_core.v3_resist_outcome(total, tn, defender_faster=defender_faster_tie)
        final = bm_core.v3_apply_outcome(gross, outcome)
        tag = {'full': '💥 dano CHEIO', 'half': '🛡️ resistiu (metade)',
               'negate': '💨 ANULOU'}[outcome]
        line = (f' · resistência d100({d100_def})+{total - d100_def} = {total} vs TN {tn}'
                f'{" (adaptação +10)" if adapt_bonus else ""}'
                f'{" (clima +10)" if weather_resist else ""} → {tag}')
        return final, outcome, line

    if not power:
        fixed = bm_core.FIXED_DAMAGE_FORMULAS.get(move_name.lower())
        if fixed is not None:
            gross = max(1, int(fixed(level, def_hp)))
            dmg, outcome, rline = _resist(gross, 40)   # dano fixo resiste como POW fraco
            return {'hit': True, 'damage': dmg, 'is_crit': is_crit,
                    'message': f'{met}d100({d100}) conecta — dano fixo {gross}',
                    'attack_roll': d100, 'move_type_en': move_type_en,
                    'outcome': outcome, 'cooldown': 0,
                    'log': f'{met}✅ d100({d100}) ({acc_label}) → FIXO {gross}{rline}'
                           f' = <strong>{dmg} dano</strong>'}
        # sem Power e sem fórmula fixa (Counter, Mirror Coat...) → mestre adjudica
        return {'hit': True, 'damage': 0,
                'message': f'{met}Conectou (d100 {d100}) — dano variável (mestre adjudica)',
                'attack_roll': d100, 'move_type_en': move_type_en, 'is_crit': is_crit,
                'log': f'{met}✅ d100({d100}) conecta — dano variável, mestre adjudica.'}

    # ── Camada 2: DANO BRUTO = Componente + ⌊nível/10⌋ + dados + Momentum ──
    atk_key = 'SPA' if category == 'special' else 'ATK'
    atk_stat = effects.effective_stat(attacker_poke, atk_key, include_stages=False)
    atk_stages = effects.stat_stage(attacker_poke, atk_key)
    component = bm_core.v3_status_component(atk_stat, atk_stages)

    # Queimado corta o Componente físico pela metade (Guts ignora)
    burned = (category == 'physical'
              and (attacker_status or {}).get('condition') == 'queimado'
              and ab.normalize_ability(attacker_poke.get('ability')) != 'guts')
    if burned:
        component = max(1, component // 2)

    # STAB: +1 dado a partir do Nv25 (antes: +2 fixo). Blaze/Torrent/Overgrow/
    # Swarm com HP ≤ 25%: +1 dado extra do tipo.
    poke_types = [t.lower() for t in (attacker_poke.get('types') or [])]
    stab = move_type_raw in poke_types or move_type_en in poke_types
    field_delta = 0
    if stab and ab.stab_multiplier(attacker_poke.get('ability'), move_type_en,
                                   atk_hp, atk_max_hp) > 1:
        field_delta += 1
    # F5: clima e terreno somam/tiram dados por tipo (Sol: Fogo+1/Água−1...)
    w_delta = bm_core.v3_weather_dice_delta(weather, move_type_en)
    t_delta = bm_core.v3_terrain_dice_delta(terrain, move_type_en, ml)
    field_delta += w_delta + t_delta

    # Efetividade de tipo → ±dados (a IMUNIDADE já foi checada antes da
    # precisão — ordem da spec; aqui eff é sempre > 0)
    n_dice, sides, halve = bm_core.v3_build_dice(
        power, level, stab=stab,
        effectiveness=eff, field_delta=field_delta)
    dice_total = sum(random.randint(1, sides) for _ in range(n_dice))
    # F5: MULTI-HIT (Double Kick, Rock Blast...): 1 ACC, 1 Componente e
    # 1 Resistência; cada hit EXTRA rola só os dados-base do degrau (doc §17)
    hits = bm_core.v3_multi_hits(ml) or 1
    if hits > 1:
        base_n, base_sides = bm_core.v3_dice_base(power)
        dice_total += sum(random.randint(1, base_sides)
                          for _ in range(base_n * (hits - 1)))
    stab_flat = bm_core.v3_stab_flat(stab, level)
    gross = bm_core.v3_gross_damage(component, level, dice_total,
                                    momentum=momentum, halve_dice=halve,
                                    flat=stab_flat)

    # Habilidades de dano do atacante (Iron Fist, Technician, Tinted Lens...)
    abil_dmg_mult = ab.ability_damage_mult(
        attacker_poke, move_name, move_type_en, category, power,
        is_crit=is_crit, effectiveness=eff, attacker_types=attacker_poke.get('types'))
    if abil_dmg_mult != 1.0:
        gross = max(1, int(gross * abil_dmg_mult))

    # Sinergia de veneno: Venoshock dobra contra alvo envenenado
    venoshock_x2 = False
    if (move_name.lower() == 'venoshock'
            and (defender_status or {}).get('condition') == 'badly_poisoned'):
        gross *= 2
        venoshock_x2 = True

    # ── Camada 3: RESISTÊNCIA do defensor ──
    dmg, outcome, rline = _resist(gross, power)

    # ── ACC ∞: redutor de balanceamento ×0,90 no dano FINAL (após a
    # Resistência) — compensa a confiabilidade do golpe certeiro ──
    if certeiro and dmg > 0:
        dmg = bm_core.v3_certeiro_mult(dmg)

    # ── F5: recoil (⌊dano÷3⌋) e dreno (⌊dano÷2⌋) — o handler aplica no HP ──
    recoil = bm_core.v3_recoil(dmg, canon_drain)
    drain_heal = bm_core.v3_drain_heal(dmg, canon_drain)

    # ── Efeito secundário de ESTÁGIO (canônico): Icy Wind/Rock Tomb reduzem
    # SPE, Crunch DEF, Ancient Power sobe tudo no usuário... Positivo → no
    # usuário; negativo → no alvo (exceto recuos tipo Overheat, no usuário).
    # Aplicado direto nos dicts vivos — vale nos 3 modos sem handler. ──
    sc_label = ''
    _sc = canon.get('stat_changes') or []
    _sc_chance = int(canon.get('stat_chance') or 0)
    if dmg > 0 and _sc and _sc_chance and random.randint(1, 100) <= _sc_chance:
        delta = {c['stat']: int(c['change']) for c in _sc if c.get('stat')}
        if delta:
            to_self = (all(v > 0 for v in delta.values())
                       or ml in V3_SELF_DEBUFF_MOVES)
            effects.apply_stat_changes(attacker_poke if to_self else defender_poke,
                                       delta)
            _who = 'em si' if to_self else 'no alvo'
            sc_label = ' 📊 ' + ', '.join(f'{k} {v:+d}' for k, v in delta.items()) \
                       + f' ({_who})'

    # ── Rampage (Outrage/Thrash/Petal Dance): o preço canônico — o PRÓPRIO
    # usuário fica confuso após o ataque (handler aplica) ──
    self_status = None
    if dmg > 0 and ml in V3_RAMPAGE_MOVES:
        self_status = 'confuso'

    # ── Explosion/Self-Destruct: o usuário DESMAIA ao usar (handler zera HP) ──
    self_ko = ml in V3_SELF_KO_MOVES

    # ── Rapid Spin: limpa semente/prisão do próprio usuário ao acertar ──
    spin_label = ''
    if (ml == 'rapid spin' and dmg > 0 and isinstance(attacker_status, dict)
            and attacker_status.get('condition') in ('seeded', 'trapped')):
        attacker_status.clear()   # mesmo dict do battle_state/poke → some
        spin_label = ' 🌀 girou e se livrou da semente/prisão!'

    eff_label = ''
    if eff > 1:   eff_label = f' ⚡ Super Efetivo (+{bm_core.v3_effectiveness_dice_delta(eff)} dado)'
    elif eff < 1: eff_label = f' 🛡️ Não Efetivo ({bm_core.v3_effectiveness_dice_delta(eff)} dado)'

    field_label = ''
    if w_delta or t_delta:
        parts = []
        if w_delta: parts.append(f'clima {w_delta:+d}d')
        if t_delta: parts.append(f'terreno {t_delta:+d}d')
        field_label = f' 🌦️ {" ".join(parts)}'

    log = (f'{met}{"🔆 " if charging_released else ""}✅ d100({d100}) ({acc_label})'
           f'{" 🎯 CRIT fura defesa!" if is_crit else ""}'
           f'{f" ✊ {hits} hits!" if hits > 1 else ""}'
           f' → {n_dice}d{sides}{f"+{hits - 1}×hit" if hits > 1 else ""}({dice_total})'
           f' + comp {component} + nv {bm_core.v3_level_bonus(level)}'
           f'{f" + STAB {stab_flat}" if stab_flat else (" +1d STAB" if stab and level >= bm_core.V3_STAB_DIE_LEVEL else "")}'
           f'{f" + momentum {momentum}" if momentum else ""}'
           f'{" ×½ (queimado)" if burned else ""}'
           f'{" ☠️×2 (alvo envenenado)" if venoshock_x2 else ""}'
           f'{eff_label}{field_label} = bruto {gross}{rline}'
           f'{" · 🎯 ×0,9 (certeiro)" if certeiro and dmg > 0 else ""}'
           f' = <strong>{dmg} dano {move.get("type", "")}</strong>'
           f'{f" · 💢 recoil {recoil}" if recoil else ""}'
           f'{f" · 💚 drena {drain_heal}" if drain_heal else ""}'
           f'{sc_label}{spin_label}'
           f'{" · 💫 fica CONFUSO pela fúria!" if self_status else ""}'
           f'{" · 💥 o usuário DESMAIA com a explosão!" if self_ko else ""}')

    return {'hit': True, 'damage': dmg,
            'message': f'{met}d100({d100}) vs {acc_label}{" Crítico!" if is_crit else ""}{eff_label}',
            'attack_roll': d100, 'move_type_en': move_type_en,
            'is_crit': is_crit, 'log': log, 'outcome': outcome,
            'recoil': recoil, 'drain_heal': drain_heal,
            'self_status': self_status, 'self_ko': self_ko,
            'cooldown': bm_core.v3_move_cooldown(power, canon_drain)}


def _field_of(container):
    """Estado de CAMPO da batalha (clima/terreno, F5) — vive no battle_state
    (selvagem) ou no dict da batalha (PvP/grupo). Cria se não existe."""
    if not isinstance(container, dict):
        return {}
    fld = container.setdefault('field', {})
    fld.setdefault('weather', None)
    fld.setdefault('weather_left', 0)
    fld.setdefault('terrain', None)
    fld.setdefault('terrain_left', 0)
    return fld


def _field_apply(container, kind, value, duration):
    """Grava clima/terreno no campo. value None = limpa o campo (Defog)."""
    fld = _field_of(container)
    if value is None:
        fld.update(weather=None, weather_left=0, terrain=None, terrain_left=0)
        return fld
    if kind == 'terrain':
        fld['terrain'], fld['terrain_left'] = value, int(duration or bm_core.V3_FIELD_ROUNDS)
    else:
        fld['weather'], fld['weather_left'] = value, int(duration or bm_core.V3_FIELD_ROUNDS)
    return fld


def _field_tick(container):
    """Fim de rodada: decrementa as durações; devolve mensagens de expiração."""
    fld = _field_of(container)
    msgs = []
    if fld.get('weather'):
        fld['weather_left'] = int(fld.get('weather_left') or 0) - 1
        if fld['weather_left'] <= 0:
            msgs.append(f"🌤️ O clima ({fld['weather']}) se dissipou.")
            fld['weather'], fld['weather_left'] = None, 0
    if fld.get('terrain'):
        fld['terrain_left'] = int(fld.get('terrain_left') or 0) - 1
        if fld['terrain_left'] <= 0:
            msgs.append(f"🍃 O terreno ({fld['terrain']}) se desfez.")
            fld['terrain'], fld['terrain_left'] = None, 0
    return msgs


def _field_chip(container, poke, max_hp, label):
    """Dano/cura de campo por rodada para um lado: (delta_hp, msg|None).
    Delta negativo = dano de clima; positivo = cura de Grassy Terrain.
    Habilidades imunes a dano indireto/clima são respeitadas."""
    fld = _field_of(container)
    delta, msg = 0, None
    chip = bm_core.v3_weather_chip(fld.get('weather'), max_hp, (poke or {}).get('types'))
    if chip and not ab.ability_blocks_weather_damage(poke):
        delta -= chip
        icon = '🌪️' if fld.get('weather') == 'sandstorm' else '❄️'
        msg = f'{icon} {label} sofre {chip} de dano do clima!'
    # Solar Power: o SpA ×1,5 sob Sol custa ⌊HP/8⌋ por rodada (canon)
    if fld.get('weather') == 'sun' and ab.get_ability_key(poke) == 'solar power':
        solar_cost = max(1, int(max_hp or 1) // 8)
        delta -= solar_cost
        msg = f'☀️ Solar Power: {label} sacrifica {solar_cost} HP pelo poder do Sol!'
    heal = bm_core.v3_terrain_heal(fld.get('terrain'), max_hp)
    if heal and delta == 0:
        delta += heal
        msg = f'🌿 {label} recupera {heal} HP do Grassy Terrain!'
    return delta, msg


def _calc_player_attack(encounter, move_name, attack_roll=None):
    """Ataque do JOGADOR contra o selvagem (estado vive no battle_state)."""
    bs = encounter.get('battle_state') or {}
    return _calc_attack_core(
        encounter.get('player_pokemon') or {}, encounter.get('pokemon') or {},
        move_name, attack_roll,
        attacker_status=bs.get('player_status'),
        defender_status=bs.get('wild_status'),
        atk_hp=bs.get('player_hp_current'), atk_max_hp=bs.get('player_hp_max'),
        def_hp=bs.get('wild_hp_current'), field=_field_of(bs))


def _calc_wild_attack(encounter, move_name, attack_roll=None):
    """Ataque do SELVAGEM contra o jogador — recalculado no servidor para o
    turno do selvagem no modo AUTO (senão o cliente do jogador podia mandar
    o inimigo bater de graça)."""
    bs = encounter.get('battle_state') or {}
    wpoke = encounter.get('pokemon') or {}
    # v3: se o golpe escolhido (pelo cliente) está em cooldown, o servidor
    # substitui pelo primeiro disponível do moveset — o selvagem não perde turno
    if _v3_cooldown_left(wpoke, move_name) > 0:
        pool = encounter.get('wild_moves') or wpoke.get('moves') or ['Tackle']
        avail = [m for m in pool if _v3_cooldown_left(wpoke, m) <= 0]
        move_name = (avail or ['Tackle'])[0]
    return _calc_attack_core(
        wpoke, encounter.get('player_pokemon') or {},
        move_name, attack_roll,
        attacker_status=bs.get('wild_status'),
        defender_status=bs.get('player_status'),
        atk_hp=bs.get('wild_hp_current'), atk_max_hp=bs.get('wild_hp_max'),
        def_hp=bs.get('player_hp_current'), field=_field_of(bs))


def _calc_pvp_attack(attacker_poke, defender_poke, move_name, attack_roll=None,
                     field=None):
    """Ataque em PvP/NPC/grupo (estado vive nos dicts dos Pokémon; o campo
    clima/terreno vive no dict da batalha — o caller passa)."""
    return _calc_attack_core(
        attacker_poke, defender_poke, move_name, attack_roll,
        attacker_status=attacker_poke.get('status'),
        defender_status=defender_poke.get('status'),
        atk_hp=attacker_poke.get('currentHp'), atk_max_hp=attacker_poke.get('maxHp'),
        def_hp=defender_poke.get('currentHp'), field=field)

# ============================================================
# XP TABLE (trainer levels 1-20)
# ============================================================
XP_TABLE = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500,
            5500, 6600, 7800, 9100, 10500, 12000, 13600, 15300, 17100, 19000]

def _apply_xp(trainer: dict, xp_amount: int) -> dict:
    """Add xp_amount to trainer, recalculate level. Returns info dict."""
    trainer['xp'] = trainer.get('xp', 0) + xp_amount
    current_xp = trainer['xp']
    new_level = 1
    for i, threshold in enumerate(XP_TABLE):
        if current_xp >= threshold:
            new_level = i + 1
    old_level = trainer.get('level', 1)
    # nunca REBAIXA: se o mestre subiu o nível à mão (sem XP correspondente),
    # um ganho pequeno de XP não pode fazer o nível cair pela tabela.
    new_level = max(new_level, old_level)
    trainer['level'] = new_level
    trainer['xp_to_next'] = XP_TABLE[min(new_level, len(XP_TABLE) - 1)] if new_level < len(XP_TABLE) else 99999
    return {'new_level': new_level, 'old_level': old_level, 'leveled_up': new_level > old_level}

# ============================================================
# CALENDÁRIO DO JOGO + CAÇADAS DIÁRIAS
# Meses de 30 dias, 12 meses. Só o mestre avança o dia.
# ============================================================
DEFAULT_CALENDAR = {'day': 1, 'month': 1, 'year': 1}
MAX_HUNTS_PER_DAY = 6
# Modos de caçada válidos. O teste de caçada é MANUAL: o jogador rola o d20
# (virtual ou físico) e o mestre decide liberar a caçada. Não há mais CD
# automática — o mestre libera a "Caçada Aleatória" pelo painel.
HUNT_MODES = ('normal', 'dungeon', 'dungeon_night', 'night')
# Quanto cada modo AUMENTA o nível sobre a faixa base da rota (a noite sobe
# mesmo em dungeon). O nível do selvagem vem da FAIXA DA ROTA (progressão de
# Kanto), não do nível do jogador — só há um leve empurrão se o jogador supera
# muito a rota (para a rota não ficar trivial no fim do jogo).
HUNT_LEVEL_DELTA = {'normal': 0, 'dungeon': 5, 'night': 10, 'dungeon_night': 15}
# Moveset dos SELVAGENS (regra da mesa): nunca nascem com golpes de TM e só
# têm esta chance de carregar golpes de OVO (egg) — o resto é o moveset normal
# por nível da espécie. NPCs de treinador seguem regras próprias (têm TM).
WILD_EGG_MOVE_CHANCE = 0.20


def _get_calendar(state):
    """Calendário da mesa com default retrocompatível."""
    cal = state.get('calendar') or {}
    return {'day': int(cal.get('day', 1)), 'month': int(cal.get('month', 1)),
            'year': int(cal.get('year', 1))}


def _day_key(cal):
    return f"Y{cal['year']}-M{cal['month']}-D{cal['day']}"


def _cal_abs(day, month, year):
    """Dia absoluto desde 1/1/ano1 (p/ calcular 'faltam N dias')."""
    return (int(year) - 1) * 360 + (int(month) - 1) * 30 + (int(day) - 1)


def _advance_one_day(cal):
    cal['day'] += 1
    if cal['day'] > 30:
        cal['day'] = 1
        cal['month'] += 1
    if cal['month'] > 12:
        cal['month'] = 1
        cal['year'] += 1
    return cal


def _trainer_prof(level):
    """Proficiência do TREINADOR (nível 1-20) — espelha o cliente."""
    level = int(level or 1)
    if level >= 17: return 6
    if level >= 13: return 5
    if level >= 9: return 4
    if level >= 5: return 3
    return 2


def _hunt_entry(state, player_id):
    """Entrada de caçadas do jogador com reset lazy na virada do dia."""
    cal = _get_calendar(state)
    dkey = _day_key(cal)
    entry = (state.get('hunts') or {}).get(player_id)
    if not entry or entry.get('day_key') != dkey:
        entry = {'day_key': dkey, 'used': 0, 'bonus': 0}
    return entry, dkey


def _events_with_days_until(state):
    cal = _get_calendar(state)
    today = _cal_abs(cal['day'], cal['month'], cal['year'])
    events = []
    for evt in state.get('calendar_events') or []:
        e = dict(evt)
        e['days_until'] = _cal_abs(evt.get('day', 1), evt.get('month', 1),
                                   evt.get('year', 1)) - today
        events.append(e)
    events.sort(key=lambda e: e['days_until'])
    return events


# Load mega stones database
MEGA_FILE = os.path.join(DATA_DIR, 'mega_stones.json')
MEGA_DB = load_json(MEGA_FILE)
MEGA_BY_POKEMON = {}
for stone_name, stone_data in MEGA_DB.items():
    pokemon_name = stone_data.get('pokemon', '')
    MEGA_BY_POKEMON.setdefault(pokemon_name.lower(), []).append(stone_data)

# ============================================================
# USER MODEL
# ============================================================
class User(UserMixin):
    def __init__(self, id, username, password_hash, role='player', trainer_data=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role  # 'master' or 'player'
        self.trainer_data = trainer_data or {}

# Users/game state now handled by database.py module
import database as _db_raw

def _tid():
    """Return table_id for current user (request context required)."""
    try:
        if current_user.is_authenticated:
            users = _db_raw.get_users()
            u = users.get(current_user.id, {})
            return u.get('table_id') or 'default'
    except Exception:
        pass
    return 'default'

class _TableScopedDB:
    """Proxy that injects current table_id into every db call."""
    def get_game_state(self): return _db_raw.get_game_state(_tid())
    def save_game_state(self, s): return _db_raw.save_game_state(s, _tid())
    def get_site_settings(self): return _db_raw.get_site_settings(_tid())
    def save_site_settings(self, s): return _db_raw.save_site_settings(s, _tid())
    def get_gyms(self): return _db_raw.get_gyms(_tid())
    def save_gyms(self, g): return _db_raw.save_gyms(g, _tid())
    def get_league(self): return _db_raw.get_league(_tid())
    def save_league(self, l): return _db_raw.save_league(l, _tid())
    def get_npcs(self): return _db_raw.get_npcs(_tid())
    def save_npc(self, n): return _db_raw.save_npc(n, _tid())
    def delete_npc(self, nid): return _db_raw.delete_npc(nid, _tid())
    def get_users(self): return _db_raw.get_users()
    def save_users(self, u): return _db_raw.save_users(u)
    def save_user(self, uid, u): return _db_raw.save_user(uid, u)
    def get_users_in_table(self): return _db_raw.get_users_in_table(_tid())
    def __getattr__(self, name): return getattr(_db_raw, name)

db = _TableScopedDB()
get_users = _db_raw.get_users
save_users = _db_raw.save_users

def get_game_state():
    return _db_raw.get_game_state(_tid())

def save_game_state(state):
    _db_raw.save_game_state(state, _tid())

@login_manager.user_loader
def load_user(user_id):
    users = get_users()
    if user_id in users:
        u = users[user_id]
        return User(user_id, u['username'], u['password_hash'], u['role'], u.get('trainer_data'))
    return None


# ============================================================
# APROVAÇÃO DE CONTAS DE MESTRE (super-admin: lusmar)
# ============================================================
# Só o super-admin (lusmar) pode criar mesas livremente. Qualquer OUTRO
# cadastro de mestre entra como PENDENTE (sem mesa, sem login) até o
# super-admin aprovar. Jogadores continuam entrando por código de convite.
# As flags ficam em trainer_data['_account'] (schema de users é fixo).
SUPER_ADMIN_USERNAME = (os.environ.get('SUPER_ADMIN_USERNAME') or 'lusmar').strip().lower()


def _account_meta(u):
    return (u.get('trainer_data') or {}).get('_account') or {}


def _is_super_admin(u):
    """True se o dict de usuário é o super-admin. Definido pelo NOME (lusmar)
    + papel mestre — assim uma conta lusmar que já exista no banco vira
    super-admin sem precisar de migração/flag."""
    return (u.get('role') == 'master'
            and u.get('username', '').strip().lower() == SUPER_ADMIN_USERNAME)


def _super_admin_exists(users):
    return any(_is_super_admin(u) for u in users.values())


def _master_approved(u):
    """Mestre pode logar? Pendentes = não. Mestres antigos (sem a flag) são
    tratados como aprovados (grandfather) para não quebrar mesas existentes."""
    if u.get('role') != 'master':
        return True
    meta = _account_meta(u)
    if 'approved' not in meta:
        return True   # conta anterior ao sistema de aprovação
    return meta.get('approved') is True

# ============================================================
# CONTEXT PROCESSOR - inject site settings into all templates
# ============================================================
@app.context_processor
def inject_site_settings():
    return {'site_settings': db.get_site_settings()}

# Versão dos assets = maior mtime dos JS/CSS. Muda a cada deploy → força o
# navegador a baixar JS/CSS novos (cache-busting), evitando o bug de
# "atualizei mas o site continua com o comportamento antigo".
_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

def _compute_asset_version():
    latest = 0.0
    for sub in ('js', 'css'):
        d = os.path.join(_STATIC_DIR, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            try:
                latest = max(latest, os.path.getmtime(os.path.join(d, fn)))
            except OSError:
                pass
    return str(int(latest))

ASSET_VERSION = _compute_asset_version()

@app.context_processor
def inject_asset_version():
    return {'asset_version': ASSET_VERSION}

# ============================================================
# ROUTES (AUTH)
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'master':
            return redirect(url_for('master_dashboard'))
        return redirect(url_for('player_dashboard'))
    return redirect(url_for('login'))

@app.route('/health')
def health_check():
    """Health check endpoint for Render and monitoring tools."""
    try:
        conn = db.get_conn()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    status = 'ok' if db_ok else 'degraded'
    return jsonify({'status': status, 'db': db_ok}), 200 if db_ok else 503


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Rate limit: max 10 login attempts per IP per minute
        if _rate_limit(10, 60, bucket='login'):
            flash('Muitas tentativas de login. Aguarde um momento.', 'error')
            return render_template('login.html')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Bloqueio POR CONTA: 5 falhas em 10 min trancam o usuário-alvo,
        # mesmo que o atacante troque de IP (força bruta distribuída)
        uname_key = username.lower()
        _now = _time.time()
        _login_fails[uname_key] = [t for t in _login_fails[uname_key]
                                   if _now - t < LOGIN_LOCK_WINDOW]
        if len(_login_fails[uname_key]) >= LOGIN_LOCK_MAX:
            flash('Conta temporariamente bloqueada por excesso de tentativas. '
                  'Tente de novo em ~10 minutos.', 'error')
            return render_template('login.html')

        users = get_users()
        for uid, u in users.items():
            if u['username'].lower() == username.lower():
                if check_password_hash(u['password_hash'], password):
                    # Mestre pendente de aprovação não pode entrar
                    if not _master_approved(u):
                        flash('Sua conta de Mestre está aguardando aprovação do '
                              'administrador. Você será avisado quando for liberada.', 'error')
                        return render_template('login.html')
                    _login_fails.pop(uname_key, None)
                    user = User(uid, u['username'], u['password_hash'], u['role'], u.get('trainer_data'))
                    remember = request.form.get('remember') == '1'
                    login_user(user, remember=remember)
                    return redirect(url_for('index'))
        _login_fails[uname_key].append(_now)
        flash('Usuário ou senha incorretos', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Throttle: no máx. 8 cadastros por IP por minuto (anti-flood de contas)
        if _rate_limit(8, 60, bucket='register'):
            flash('Muitos cadastros em pouco tempo. Aguarde um momento.', 'error')
            return render_template('register.html')
        # Honeypot: campo invisível que humano nenhum preenche. Bot que
        # preencher recebe um "sucesso" falso e NADA é criado (não damos a
        # dica de que foi detectado).
        if request.form.get('website'):
            flash('Cadastro enviado! Aguarde a liberação.', 'success')
            return redirect(url_for('login'))

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'player')

        if not username or not password:
            flash('Preencha todos os campos', 'error')
            return render_template('register.html')
        if not _re.fullmatch(r'[A-Za-z0-9_]{3,20}', username):
            flash('Nome de usuário: 3 a 20 caracteres, só letras, números e _.', 'error')
            return render_template('register.html')
        if len(password) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'error')
            return render_template('register.html')

        # Código de fundador: se configurado (MASTER_SIGNUP_CODE), criar
        # conta de mestre exige o código — bots/curiosos param aqui.
        if (role == 'master' and MASTER_SIGNUP_CODE
                and username.lower() != SUPER_ADMIN_USERNAME):
            if (request.form.get('master_code') or '').strip() != MASTER_SIGNUP_CODE:
                flash('Código de fundador inválido. Contas de Mestre exigem o '
                      'código fornecido pelo administrador da mesa.', 'error')
                return render_template('register.html')

        users = get_users()
        # Check if username exists
        for u in users.values():
            if u['username'].lower() == username.lower():
                flash('Usuário já existe', 'error')
                return render_template('register.html')
        
        # Players need an invite code to join a table
        invite_code = request.form.get('invite_code', '').strip()
        table_id = None

        if role == 'player':
            if not invite_code:
                flash('Jogadores precisam de um código de convite para entrar em uma mesa.', 'error')
                return render_template('register.html')
            table = _db_raw.get_table_by_invite(invite_code.upper())
            if not table:
                flash('Código de convite inválido.', 'error')
                return render_template('register.html')
            table_id = table['id']

        # Aprovação de mestre: só o super-admin (lusmar) cria mesa direto;
        # os demais mestres entram PENDENTES. Decide isto antes de gravar.
        account_meta = {}
        is_bootstrap_admin = False
        if role == 'master':
            if username.lower() == SUPER_ADMIN_USERNAME:
                if _super_admin_exists(users):
                    flash('Este nome de administrador já está em uso.', 'error')
                    return render_template('register.html')
                is_bootstrap_admin = True
                account_meta = {'approved': True, 'super_admin': True}
            else:
                # mestre comum: pendente, sem mesa, até o super-admin aprovar
                account_meta = {'approved': False, 'super_admin': False,
                                'requested_at': datetime.utcnow().isoformat() + 'Z'}
                table_id = None

        uid = secrets.token_hex(8)
        users[uid] = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
            'table_id': table_id,
            'trainer_data': {
                'name': username,
                'level': 1,
                'xp': 0,
                'xp_to_next': 100,
                'team': [],
                'bag': [],
                'badges': [],
                'visited_routes': [],
                'notes': '',
                **({'_account': account_meta} if account_meta else {})
            }
        }
        save_users(users)

        # Mestre APROVADO (super-admin no bootstrap) ganha mesa imediatamente
        if role == 'master' and is_bootstrap_admin:
            new_table_id = secrets.token_hex(6)
            invite = secrets.token_hex(3).upper()
            _db_raw.create_table(new_table_id, f"Mesa de {username}", uid, invite)
            users[uid]['table_id'] = new_table_id
            save_users(users)
            flash(f'Conta de administrador criada! Código de convite da sua mesa: {invite}', 'success')
        elif role == 'master':
            flash('Conta de Mestre criada e enviada para aprovação do administrador. '
                  'Você poderá entrar assim que for aprovada.', 'success')
        else:
            flash('Conta criada com sucesso!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ============================================================
# MASTER ROUTES
# ============================================================
@app.route('/master')
@login_required
def master_dashboard():
    if current_user.role != 'master':
        return redirect(url_for('player_dashboard'))
    tid = _tid()
    users = _db_raw.get_users()
    # Only show players from this master's table
    players = {uid: u for uid, u in users.items() if u['role'] == 'player' and u.get('table_id') == tid}
    game_state = get_game_state()
    table = _db_raw.get_table(tid)
    is_super_admin = _is_super_admin(users.get(current_user.id, {}))
    return render_template('master.html',
                         players=players,
                         game_state=game_state,
                         routes=ROUTES_DATA,
                         current_table=table,
                         is_super_admin=is_super_admin)


def _require_super_admin():
    """Retorna o dict do usuário logado se for super-admin, senão None."""
    if not current_user.is_authenticated:
        return None
    u = get_users().get(current_user.id)
    return u if u and _is_super_admin(u) else None


@app.route('/admin/pending-masters', methods=['GET'])
@login_required
def admin_pending_masters():
    """Lista os cadastros de mestre aguardando aprovação (só super-admin)."""
    if not _require_super_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    pending = [{'id': uid, 'username': u['username'],
                'requested_at': _account_meta(u).get('requested_at', '')}
               for uid, u in users.items()
               if u.get('role') == 'master' and _account_meta(u).get('approved') is False]
    pending.sort(key=lambda p: p['requested_at'])
    return jsonify({'pending': pending})


@app.route('/admin/masters/<uid>/approve', methods=['POST'])
@login_required
def admin_approve_master(uid):
    """Super-admin aprova um mestre: cria a mesa dele e libera o login."""
    if not _require_super_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    u = users.get(uid)
    if not u or u.get('role') != 'master':
        return jsonify({'error': 'Cadastro não encontrado'}), 404
    meta = _account_meta(u)
    if meta.get('approved') is not False:
        return jsonify({'error': 'Este cadastro não está pendente'}), 400
    # cria a mesa do novo mestre (mesmo fluxo do registro antigo)
    new_table_id = secrets.token_hex(6)
    invite = secrets.token_hex(3).upper()
    _db_raw.create_table(new_table_id, f"Mesa de {u['username']}", uid, invite)
    u['table_id'] = new_table_id
    td = u.setdefault('trainer_data', {})
    acc = td.setdefault('_account', {})
    acc['approved'] = True
    acc['approved_by'] = current_user.username
    acc['approved_at'] = datetime.utcnow().isoformat() + 'Z'
    users[uid] = u
    save_users(users)
    return jsonify({'ok': True, 'username': u['username'], 'invite': invite})


@app.route('/admin/masters/<uid>/reject', methods=['POST'])
@login_required
def admin_reject_master(uid):
    """Super-admin rejeita (remove) um cadastro de mestre pendente."""
    if not _require_super_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    u = users.get(uid)
    if not u or u.get('role') != 'master' or _account_meta(u).get('approved') is not False:
        return jsonify({'error': 'Cadastro pendente não encontrado'}), 404
    _db_raw.delete_user(uid)
    return jsonify({'ok': True})


@app.route('/master/table', methods=['GET'])
@login_required
def master_table_info():
    """Returns current table info (name, invite code) for the master."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    table = _db_raw.get_table(_tid())
    if not table:
        return jsonify({'error': 'Mesa não encontrada'}), 404
    return jsonify(table)


@app.route('/master/table/rename', methods=['POST'])
@login_required
def master_rename_table():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nome inválido'}), 400
    conn = _db_raw.get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE tables SET name = %s WHERE id = %s', (name, _tid()))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True, 'name': name})


@app.route('/master/table/new-invite', methods=['POST'])
@login_required
def master_new_invite():
    """Generate a new invite code for the current table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    new_code = secrets.token_hex(3).upper()
    conn = _db_raw.get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE tables SET invite_code = %s WHERE id = %s', (new_code, _tid()))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True, 'invite_code': new_code})


@app.route('/master/table/players', methods=['GET'])
@login_required
def master_table_players():
    """List players in this table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = _db_raw.get_users()
    tid = _tid()
    players = [{'id': uid, 'username': u['username']}
               for uid, u in users.items() if u['role'] == 'player' and u.get('table_id') == tid]
    return jsonify(players)


@app.route('/master/table/kick/<player_id>', methods=['POST'])
@login_required
def master_kick_player(player_id):
    """Remove a player from this table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = _db_raw.get_users()
    tid = _tid()
    u = users.get(player_id)
    if not u or u.get('table_id') != tid:
        return jsonify({'error': 'Jogador não encontrado nesta mesa'}), 404
    _db_raw.set_user_table(player_id, None)
    return jsonify({'ok': True})

# ── Player transfer system ──────────────────────────────────
# Flow:
# 1. Player requests transfer: POST /player/request-transfer {invite_code}
# 2. Destination master sees pending request in their mesa tab
# 3. Master approves: POST /master/table/approve-transfer {request_id, keep_progress}
#    keep_progress=true → keep trainer_data as-is
#    keep_progress=false → reset trainer_data to fresh player

PENDING_TRANSFERS = {}  # {request_id: {player_id, from_table, to_table, username, trainer_data}}

@app.route('/player/request-transfer', methods=['POST'])
@login_required
def player_request_transfer():
    """Player requests to move to another table via invite code."""
    data = request.json or {}
    invite_code = (data.get('invite_code') or '').strip().upper()
    if not invite_code:
        return jsonify({'error': 'Código inválido'}), 400
    target_table = _db_raw.get_table_by_invite(invite_code)
    if not target_table:
        return jsonify({'error': 'Código de convite não encontrado'}), 404
    current_tid = _tid()
    if target_table['id'] == current_tid:
        return jsonify({'error': 'Você já está nesta mesa'}), 400

    users = _db_raw.get_users()
    user = users.get(current_user.id, {})
    req_id = secrets.token_hex(6)
    PENDING_TRANSFERS[req_id] = {
        'request_id': req_id,
        'player_id': current_user.id,
        'username': current_user.username,
        'from_table': current_tid,
        'to_table': target_table['id'],
        'trainer_data': user.get('trainer_data', {})
    }
    # Notify destination master
    socketio.emit('transfer_request', PENDING_TRANSFERS[req_id],
                  room=f'master_{target_table["id"]}')
    return jsonify({'ok': True, 'message': f'Solicitação enviada ao mestre da mesa "{target_table["name"]}"'})


@app.route('/master/table/approve-transfer', methods=['POST'])
@login_required
def master_approve_transfer():
    """Master approves or rejects a player transfer."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    req_id = data.get('request_id')
    keep_progress = bool(data.get('keep_progress', True))
    approved = bool(data.get('approved', True))
    req = PENDING_TRANSFERS.pop(req_id, None)
    if not req:
        return jsonify({'error': 'Solicitação não encontrada ou expirada'}), 404
    if req['to_table'] != _tid():
        return jsonify({'error': 'Solicitação não pertence a esta mesa'}), 403

    if not approved:
        socketio.emit('transfer_result', {'approved': False,
            'message': 'Sua solicitação de transferência foi recusada pelo mestre.'},
            room=req['player_id'])
        return jsonify({'ok': True, 'approved': False})

    users = _db_raw.get_users()
    user = users.get(req['player_id'])
    if not user:
        return jsonify({'error': 'Jogador não encontrado'}), 404

    if not keep_progress:
        # Reset to fresh trainer
        user['trainer_data'] = {
            'name': user['username'],
            'level': 1, 'xp': 0, 'xp_to_next': 100,
            'team': [], 'bag': [], 'badges': [], 'visited_routes': [], 'notes': ''
        }
    user['table_id'] = req['to_table']
    _db_raw.save_user(req['player_id'], user)

    socketio.emit('transfer_result', {
        'approved': True,
        'keep_progress': keep_progress,
        'message': 'Transferência aprovada! Faça logout e login novamente para entrar na nova mesa.'
    }, room=req['player_id'])
    return jsonify({'ok': True, 'approved': True, 'keep_progress': keep_progress})


@app.route('/master/table/pending-transfers', methods=['GET'])
@login_required
def master_pending_transfers():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tid = _tid()
    pending = [r for r in PENDING_TRANSFERS.values() if r['to_table'] == tid]
    return jsonify(pending)


# ── Map system ───────────────────────────────────────────────
import os as _os

MAPS_STATIC_DIR = _os.path.join(_os.path.dirname(__file__), 'static', 'maps')

BUNDLED_MAPS = [
    {'id': 'galar', 'name': 'Galar', 'file': 'galar_map.png'},
    {'id': 'galarian', 'name': 'Galar (detalhe)', 'file': 'galarian_map.png'},
    {'id': 'kalos', 'name': 'Kalos', 'file': 'kalos_map.png'},
    {'id': 'alola', 'name': 'Alola (geral)', 'file': 'alola_map_geral.jpg'},
    {'id': 'alola_mele', 'name': 'Alola – Melemele', 'file': 'alola_map_melemele_island.png'},
    {'id': 'alola_akala', 'name': 'Alola – Akala', 'file': 'alola_map_akala_island.png'},
    {'id': 'alola_ula', 'name': "Alola – Ula'Ula", 'file': 'alola_map_ula_ula_island.png'},
    {'id': 'alola_poni', 'name': 'Alola – Poni', 'file': 'alola_map_poni_island.png'},
    {'id': 'paldea', 'name': 'Paldea', 'file': 'pokemon_paldea_map.jpg'},
    {'id': 'geral', 'name': 'Mapa Geral', 'file': 'mapa_geral.png'},
    {'id': 'geral_nomes', 'name': 'Mapa Geral (nomes)', 'file': 'mapa_atualizado_com_nomes.jpg'},
]

# Add exterior maps dynamically
_ext_dir = _os.path.join(MAPS_STATIC_DIR, 'exteriores')
if _os.path.isdir(_ext_dir):
    for _f in sorted(_os.listdir(_ext_dir)):
        if _f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            _name = _f.rsplit('.', 1)[0].replace('_', ' ').title()
            BUNDLED_MAPS.append({'id': f'ext_{_f}', 'name': f'Exterior – {_name}', 'file': f'exteriores/{_f}'})


@app.route('/api/maps', methods=['GET'])
@login_required
def api_maps():
    """List available bundled maps."""
    return jsonify(BUNDLED_MAPS)


@app.route('/master/table/set-map', methods=['POST'])
@login_required
def master_set_map():
    """Set the active map for this table. Broadcasts to all players."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    map_id = data.get('map_id')
    map_file = data.get('map_file')
    map_name = data.get('map_name', '')

    settings = db.get_site_settings()
    settings['active_map'] = {'id': map_id, 'file': map_file, 'name': map_name}
    db.save_site_settings(settings)

    socketio.emit('map_changed', {'map_file': map_file, 'map_name': map_name},
                  room=f'players_{_tid()}')
    return jsonify({'ok': True})


@app.route('/master/quests', methods=['POST'])
@login_required
def add_quest():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    game_state = get_game_state()
    # Parse objectives — accept either list of strings or list of {text, done}
    raw_objectives = data.get('objectives', [])
    objectives = []
    for obj in raw_objectives:
        if isinstance(obj, str):
            objectives.append({'text': obj, 'done': False})
        elif isinstance(obj, dict):
            objectives.append({'text': obj.get('text', ''), 'done': bool(obj.get('done', False))})

    quest = {
        'id': secrets.token_hex(4),
        'title': data.get('title', ''),
        'city': data.get('city', ''),
        'description': data.get('description', ''),
        'category': data.get('category', 'main'),   # 'main' | 'side' | 'urgent'
        'assigned_to': data.get('assigned_to', []),
        'xp_reward': int(data.get('xp_reward', 0)),
        'money_reward': int(data.get('money_reward', 0)),
        'item_rewards': data.get('item_rewards', []),  # [{name, qty, file}]
        'repeatable_per_player': bool(data.get('repeatable_per_player', False)),
        'objectives': objectives,
        'completed': False,
        'completions': {},   # {player_id: True} for repeatable_per_player quests
        'player_notes': {}   # {player_id: note_text}
    }
    game_state['quests'].append(quest)
    save_game_state(game_state)
    socketio.emit('new_quest', quest, room=f'players_{_tid()}')
    return jsonify(quest)

@app.route('/master/quests/<quest_id>/complete', methods=['POST'])
@login_required
def complete_quest(quest_id):
    """Mark a quest as complete and award XP/money/items to assigned players.

    Body (optional): { "player_id": "..." }  — for repeatable_per_player quests,
    completes only for that specific player. If omitted, completes globally.
    """
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    target_player = data.get('player_id')   # optional: complete for one player only
    game_state = get_game_state()
    # SÓ jogadores DESTA mesa podem ser premiados — antes usava get_users()
    # global e uma quest sem assigned_to premiava jogadores de OUTRAS mesas.
    users = get_users()
    table_players = {uid for uid, u in db.get_users_in_table().items()
                     if u.get('role') == 'player'}
    if target_player and target_player not in table_players:
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    XP_TABLE = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500,
                5500, 6600, 7800, 9100, 10500, 12000, 13600, 15300, 17100, 19000]

    for quest in game_state['quests']:
        if quest['id'] != quest_id:
            continue

        per_player = quest.get('repeatable_per_player', False)

        # Determine which players to reward
        if target_player:
            players_to_reward = [target_player]
        else:
            assigned = quest.get('assigned_to', [])
            # sem atribuição = todos os jogadores DESTA mesa (não os globais)
            players_to_reward = [p for p in assigned if p in table_players] \
                if assigned else list(table_players)

        # Check already completed:
        # - With target_player: use per-player completion tracking so each player
        #   can receive rewards independently without blocking others.
        # - Without target_player: global completion flag (original behavior).
        if target_player:
            completions = quest.setdefault('completions', {})
            if completions.get(target_player):
                return jsonify({'error': 'Quest já completada para este jogador'}), 400
        elif not per_player and quest.get('rewards_paid'):
            # usa rewards_paid (não 'completed'): objetivos marcados pelo jogador
            # deixam 'completed'=True mas ainda NÃO pagaram — o mestre paga aqui
            return jsonify({'error': 'Recompensa desta quest já foi entregue'}), 400

        # For per-player repeatable quests, filter out those who already completed
        if per_player and not target_player:
            completions = quest.setdefault('completions', {})
            players_to_reward = [p for p in players_to_reward if not completions.get(p)]
            if not players_to_reward:
                return jsonify({'error': 'Todos os jogadores já completaram esta quest'}), 400

        xp_reward    = quest.get('xp_reward', 0)
        money_reward = quest.get('money_reward', 0)
        item_rewards = quest.get('item_rewards', [])

        rewarded = []
        for player_id in players_to_reward:
            if player_id not in users:
                continue
            trainer = users[player_id].get('trainer_data', {})

            # XP
            if xp_reward > 0:
                lv_info = _apply_xp(trainer, xp_reward)
                socketio.emit('xp_update', {
                    'player_id': player_id, 'xp': trainer['xp'],
                    'level': trainer['level'], 'xp_to_next': trainer['xp_to_next'],
                    'leveled_up': lv_info['leveled_up']
                }, room=player_id)

            # Money
            if money_reward > 0:
                trainer['money'] = trainer.get('money', 0) + money_reward

            # Items
            for reward_item in item_rewards:
                if not reward_item.get('name'):
                    continue
                bag = trainer.setdefault('bag', [])
                existing = next((i for i in bag if i.get('name') == reward_item['name']), None)
                if existing:
                    existing['qty'] = existing.get('qty', 1) + int(reward_item.get('qty', 1))
                else:
                    bag.append({'name': reward_item['name'],
                                'qty': int(reward_item.get('qty', 1)),
                                'file': reward_item.get('file', '')})

            users[player_id]['trainer_data'] = trainer

            # Notify player
            socketio.emit('quest_completed', {
                'quest_id': quest_id,
                'xp_reward': xp_reward,
                'money_reward': money_reward,
                'item_rewards': item_rewards
            }, room=player_id)

            if per_player or target_player:
                quest.setdefault('completions', {})[player_id] = True

            rewarded.append(player_id)

        # Marca conclusão global + recompensa ENTREGUE (só sem alvo específico)
        if not per_player and not target_player:
            quest['completed'] = True
            quest['rewards_paid'] = True

        save_users(users)
        save_game_state(game_state)

        # Notify master panel
        socketio.emit('quest_updated', quest, room=f'master_{_tid()}')
        return jsonify({'success': True, 'rewarded': rewarded})

    return jsonify({'error': 'Quest not found'}), 404


@app.route('/master/quests/<quest_id>', methods=['PUT'])
@login_required
def update_quest(quest_id):
    """Update quest details (title, description, objectives, etc.)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] == quest_id:
            if 'title'       in data: quest['title']       = data['title']
            if 'city'        in data: quest['city']        = data['city']
            if 'description' in data: quest['description'] = data['description']
            if 'category'    in data: quest['category']    = data['category']
            if 'xp_reward'   in data: quest['xp_reward']   = int(data['xp_reward'])
            if 'money_reward' in data: quest['money_reward'] = int(data['money_reward'])
            if 'item_rewards' in data: quest['item_rewards'] = data['item_rewards']
            if 'repeatable_per_player' in data: quest['repeatable_per_player'] = bool(data['repeatable_per_player'])
            if 'objectives'  in data:
                raw = data['objectives']
                quest['objectives'] = [
                    {'text': o if isinstance(o, str) else o.get('text', ''),
                     'done': False if isinstance(o, str) else bool(o.get('done', False))}
                    for o in raw
                ]
            save_game_state(game_state)
            socketio.emit('quest_updated', quest, room=f'players_{_tid()}')
            return jsonify(quest)
    return jsonify({'error': 'Quest not found'}), 404


@app.route('/master/quests/<quest_id>', methods=['DELETE'])
@login_required
def delete_quest(quest_id):
    """Delete a quest entirely."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    game_state = get_game_state()
    before = len(game_state['quests'])
    game_state['quests'] = [q for q in game_state['quests'] if q['id'] != quest_id]
    if len(game_state['quests']) == before:
        return jsonify({'error': 'Quest not found'}), 404
    save_game_state(game_state)
    socketio.emit('quest_deleted', {'quest_id': quest_id}, room=f'players_{_tid()}')
    socketio.emit('quest_deleted', {'quest_id': quest_id}, room=f'master_{_tid()}')
    return jsonify({'success': True})


# ============================================================
# CALENDÁRIO — rotas
# ============================================================
@app.route('/api/calendar', methods=['GET'])
@login_required
def api_calendar():
    """Data atual + eventos com dias restantes (qualquer usuário logado)."""
    state = get_game_state()
    return jsonify({'calendar': _get_calendar(state),
                    'events': _events_with_days_until(state)})


@app.route('/api/hunts/status', methods=['GET'])
@login_required
def api_hunts_status():
    """Contador de caçadas do jogador (reset lazy, sem persistir)."""
    state = get_game_state()
    entry, dkey = _hunt_entry(state, str(current_user.id))
    return jsonify({'used': entry['used'],
                    'limit': MAX_HUNTS_PER_DAY + int(entry.get('bonus', 0)),
                    'calendar': _get_calendar(state), 'day_key': dkey})


@app.route('/player/use-energy-drink', methods=['POST'])
@login_required
def use_energy_drink():
    """Consome um Energy Drink da bolsa e concede +1 caçada extra hoje."""
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])
    item = next((b for b in bag if isinstance(b, dict)
                 and (b.get('name', '') or '').lower() in ENERGY_DRINK_NAMES), None)
    if not item or (item.get('qty') or 0) < 1:
        return jsonify({'error': 'Você não tem Energy Drink na bolsa!'}), 400

    # consome 1
    item['qty'] -= 1
    if item['qty'] <= 0:
        trainer['bag'] = [b for b in bag if b is not item]
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    # +1 caçada (bonus) no dia atual
    pid = str(current_user.id)
    state = get_game_state()
    entry, dkey = _hunt_entry(state, pid)
    entry['bonus'] = int(entry.get('bonus', 0)) + 1
    hunts = state.get('hunts') or {}
    hunts[pid] = entry
    state['hunts'] = hunts
    save_game_state(state)

    limit = MAX_HUNTS_PER_DAY + entry['bonus']
    socketio.emit('hunts_update', {'used': entry['used'], 'limit': limit}, room=pid)
    return jsonify({'ok': True, 'used': entry['used'], 'limit': limit,
                    'message': '🥤 Energy Drink! +1 caçada. Ânimo recuperado!'})


@app.route('/master/hunts', methods=['POST'])
@login_required
def master_hunts():
    """Mestre reseta ou concede caçadas extras a um jogador."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = str(data.get('player_id', ''))
    action = data.get('action', 'reset')
    if not player_id:
        return jsonify({'error': 'player_id obrigatório'}), 400

    state = get_game_state()
    entry, dkey = _hunt_entry(state, player_id)
    if action == 'grant':
        entry['bonus'] = int(entry.get('bonus', 0)) + max(1, int(data.get('amount', 1)))
    else:
        entry['used'] = 0
    hunts = state.get('hunts') or {}
    hunts[player_id] = entry
    state['hunts'] = hunts
    save_game_state(state)

    limit = MAX_HUNTS_PER_DAY + int(entry.get('bonus', 0))
    socketio.emit('hunts_update', {'used': entry['used'], 'limit': limit},
                  room=player_id)
    return jsonify({'ok': True, 'used': entry['used'], 'limit': limit})


def _process_npcs_for_day(dkey):
    """Progressão autônoma dos NPCs num dia de jogo. Retorna log p/ o mestre."""
    log = []
    for npc in db.get_npcs():
        # Economia do dia (para TODO NPC, mesmo sem progressão de nível):
        # ganha um dinheiro pelo dia de trabalho e às vezes compra um item.
        _npc_ensure_economy(npc)
        earned = random.randint(100, 400)
        npc['money'] = int(npc.get('money') or 0) + earned
        econ_msg = f'💰 Ganhou ₽{earned} no dia.'
        if npc['money'] >= 1500 and random.random() < 0.30:
            affordable = [i for i in SHOP_CATALOG
                          if i.get('category') in ('pokeball', 'medicine')
                          and i['price'] <= min(1500, npc['money'] // 2)]
            if affordable:
                item = random.choice(affordable)
                npc['money'] -= item['price']
                _bag_add(npc.setdefault('bag', []), item['name'], 1,
                         item.get('description', ''))
                econ_msg += f" 🛍️ Comprou 1x {item['name']} (₽{item['price']})."
        npc.setdefault('diary', []).append({'day_key': dkey, 'message': econ_msg})

        if not npc.get('progression_enabled'):
            npc['diary'] = npc['diary'][-60:]
            db.save_npc(npc)
            continue
        rate = npc.get('growth_rate', 'normal')
        roll = random.randint(1, 20)
        diary = npc.setdefault('diary', [])

        if roll < 10:
            diary.append({'day_key': dkey,
                          'message': f'Treinou mas não avançou (d20={roll} vs CD 10).'})
        else:
            gained = 0
            if rate == 'fast':
                gained = 2
            elif rate == 'slow':
                npc['growth_points'] = npc.get('growth_points', 0) + 1
                if npc['growth_points'] >= 2:
                    npc['growth_points'] -= 2
                    gained = 1
            else:
                gained = 1

            evo_msgs = []
            if gained:
                for i, p in enumerate(npc.get('team', [])):
                    if p.get('level', 1) >= 100:
                        continue
                    p['level'] = min(100, int(p.get('level', 1)) + gained)
                    base = POKEMON_BY_NAME.get((p.get('name') or '').lower())
                    if base:
                        scaled = scaling.calculate_pokemon_stats(base, p['level'], p.get('nature'))
                        p.update({'stats': scaled['stats'], 'maxHp': scaled['maxHp'],
                                  'currentHp': scaled['maxHp'], 'hp': scaled['hp'],
                                  'ac': scaled['ac'],
                                  'proficiency': scaled['proficiency'], 'stab': scaled['stab'],
                                  'phys_ac': scaled['phys_ac'], 'spec_ac': scaled['spec_ac']})
                    evolved, evo_name = check_and_evolve_pokemon(
                        p, trainer_level=max(1, -(-p['level'] // 5)))
                    if evolved:
                        evo_msgs.append(f"{p.get('name')} evoluiu para {evo_name}!")
                        npc['team'][i] = evolved

            if gained:
                msg = f'Treino com sucesso (d20={roll}): time +{gained} nível(is).'
            else:
                msg = f'Treino com sucesso (d20={roll}); progresso lento acumulando.'
            if evo_msgs:
                msg += ' 🎉 ' + ' '.join(evo_msgs)
            diary.append({'day_key': dkey, 'message': msg})

        npc['diary'] = diary[-60:]
        db.save_npc(npc)
        log.append({'npc_id': npc['id'], 'name': npc.get('name', '?'),
                    'message': npc['diary'][-1]['message']})
    return log


@app.route('/master/calendar/advance', methods=['POST'])
@login_required
def master_calendar_advance():
    """Avança N dias: processa NPCs e eventos dia a dia, reseta caçadas."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    days = max(1, min(30, int((request.json or {}).get('days', 1))))

    state = get_game_state()
    cal = _get_calendar(state)
    npc_log = []
    for _ in range(days):
        cal = _advance_one_day(cal)
        npc_log.extend([dict(e, day_key=_day_key(cal)) for e in _process_npcs_for_day(_day_key(cal))])

    state['calendar'] = cal
    state['hunts'] = {}   # novo dia → contadores zerados
    save_game_state(state)

    events = _events_with_days_until(state)
    events_triggered = []
    tid = _tid()
    for e in events:
        if e['days_until'] == 0:
            socketio.emit('calendar_event_today', {'event': e}, room=f'players_{tid}')
            events_triggered.append(e)
        elif 0 < e['days_until'] <= int(e.get('notify_days_before', 3)):
            socketio.emit('calendar_event_soon',
                          {'event': e, 'days_until': e['days_until']},
                          room=f'players_{tid}')

    payload = {'calendar': cal, 'events': events}
    socketio.emit('calendar_update', payload, room=f'players_{tid}')
    socketio.emit('calendar_update', payload, room=f'master_{tid}')
    socketio.emit('hunts_update', {'used': 0, 'limit': MAX_HUNTS_PER_DAY},
                  room=f'players_{tid}')
    if npc_log:
        socketio.emit('npc_diary_update', {'npc_log': npc_log}, room=f'master_{tid}')

    return jsonify({'calendar': cal, 'npc_log': npc_log,
                    'events_triggered': events_triggered})


@app.route('/master/calendar/set', methods=['POST'])
@login_required
def master_calendar_set():
    """Define a data diretamente (correção manual — não processa NPCs)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    try:
        cal = {'day': int(data.get('day', 1)), 'month': int(data.get('month', 1)),
               'year': int(data.get('year', 1))}
    except (TypeError, ValueError):
        return jsonify({'error': 'Data inválida'}), 400
    if not (1 <= cal['day'] <= 30 and 1 <= cal['month'] <= 12 and cal['year'] >= 1):
        return jsonify({'error': 'Data inválida (dia 1-30, mês 1-12, ano ≥1)'}), 400

    state = get_game_state()
    state['calendar'] = cal
    state['hunts'] = {}
    save_game_state(state)

    payload = {'calendar': cal, 'events': _events_with_days_until(state)}
    tid = _tid()
    socketio.emit('calendar_update', payload, room=f'players_{tid}')
    socketio.emit('calendar_update', payload, room=f'master_{tid}')
    return jsonify(payload)


@app.route('/master/calendar/events', methods=['POST'])
@login_required
def create_calendar_event():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    try:
        evt = {
            'id': secrets.token_hex(4),
            'title': (data.get('title') or '').strip(),
            'city': (data.get('city') or '').strip(),
            'description': (data.get('description') or '').strip(),
            'day': int(data.get('day', 1)),
            'month': int(data.get('month', 1)),
            'year': int(data.get('year', 1)),
            'notify_days_before': max(0, int(data.get('notify_days_before', 3))),
        }
    except (TypeError, ValueError):
        return jsonify({'error': 'Dados inválidos'}), 400
    if not evt['title']:
        return jsonify({'error': 'Título obrigatório'}), 400
    if not (1 <= evt['day'] <= 30 and 1 <= evt['month'] <= 12 and evt['year'] >= 1):
        return jsonify({'error': 'Data inválida (dia 1-30, mês 1-12, ano ≥1)'}), 400

    state = get_game_state()
    events = state.get('calendar_events') or []
    events.append(evt)
    state['calendar_events'] = events
    save_game_state(state)

    socketio.emit('calendar_event_new', evt, room=f'players_{_tid()}')
    return jsonify(evt)


@app.route('/master/calendar/events/<event_id>', methods=['PUT'])
@login_required
def update_calendar_event(event_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    state = get_game_state()
    for evt in state.get('calendar_events') or []:
        if evt['id'] == event_id:
            for field in ('title', 'city', 'description'):
                if field in data:
                    evt[field] = (data.get(field) or '').strip()
            for field in ('day', 'month', 'year', 'notify_days_before'):
                if field in data:
                    try:
                        evt[field] = int(data[field])
                    except (TypeError, ValueError):
                        pass
            save_game_state(state)
            socketio.emit('calendar_event_updated', evt, room=f'players_{_tid()}')
            return jsonify(evt)
    return jsonify({'error': 'Evento não encontrado'}), 404


@app.route('/master/calendar/events/<event_id>', methods=['DELETE'])
@login_required
def delete_calendar_event(event_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    state = get_game_state()
    events = state.get('calendar_events') or []
    state['calendar_events'] = [e for e in events if e['id'] != event_id]
    save_game_state(state)
    socketio.emit('calendar_event_deleted', {'id': event_id}, room=f'players_{_tid()}')
    return jsonify({'ok': True})


@app.route('/api/game-state', methods=['GET'])
@login_required
def api_game_state():
    """Return current game state (quests, etc.) for master UI refresh."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(get_game_state())


@app.route('/quests/<quest_id>/objectives/<int:obj_idx>/toggle', methods=['POST'])
@login_required
def toggle_objective(quest_id, obj_idx):
    """Toggle an objective's done state. Auto-completes quest if all done."""
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] != quest_id:
            continue
        # Só o mestre ou um jogador ATRIBUÍDO alterna objetivos. Antes, quest
        # sem assigned_to podia ser alternada por qualquer jogador (griefing).
        assigned = quest.get('assigned_to', [])
        if current_user.role != 'master' and current_user.id not in assigned:
            return jsonify({'error': 'Forbidden'}), 403
        objectives = quest.get('objectives', [])
        if obj_idx < 0 or obj_idx >= len(objectives):
            return jsonify({'error': 'Invalid objective index'}), 400
        objectives[obj_idx]['done'] = not objectives[obj_idx]['done']
        quest['objectives'] = objectives

        # Objetivos completos = quest "pronta", mas a RECOMPENSA é entregue só
        # quando o mestre clica em Completar (rewards_paid). Sem isto, marcar
        # os objetivos travava o pagamento (completed=True bloqueava o botão).
        auto_completed = False
        if objectives and all(o['done'] for o in objectives) and not quest['completed']:
            quest['completed'] = True
            auto_completed = True

        save_game_state(game_state)
        socketio.emit('quest_updated', quest, room=f'players_{_tid()}')
        socketio.emit('quest_updated', quest, room=f'master_{_tid()}')
        return jsonify({'quest': quest, 'auto_completed': auto_completed})
    return jsonify({'error': 'Quest not found'}), 404


@app.route('/quests/<quest_id>/notes', methods=['POST'])
@login_required
def save_quest_notes(quest_id):
    """Save player notes on a quest."""
    data = request.json or {}
    note = data.get('note', '')
    game_state = get_game_state()
    for quest in game_state['quests']:
        if quest['id'] == quest_id:
            if 'player_notes' not in quest:
                quest['player_notes'] = {}
            quest['player_notes'][current_user.id] = note
            save_game_state(game_state)
            return jsonify({'success': True})
    return jsonify({'error': 'Quest not found'}), 404


def _player_in_master_table(player_id, users, master_tid):
    """Return True if player_id belongs to the master's table."""
    u = users.get(player_id, {})
    return u.get('table_id') == master_tid


@app.route('/master/players/<player_id>')
@login_required
def master_view_player(player_id):
    """Master full view of a player's data (no password hash)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player not found'}), 404
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    u = users[player_id]
    trainer_attrs.migrate_trainer(u.get('trainer_data', {}) or {})
    # Never expose password hashes to the client
    return jsonify({
        'username': u['username'],
        'role': u['role'],
        'table_id': u.get('table_id'),
        'trainer_data': u.get('trainer_data', {})
    })

@app.route('/master/players/<player_id>/edit', methods=['POST'])
@login_required
def master_edit_player(player_id):
    """Master can edit ANY field of a player's trainer data (table-scoped)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player not found'}), 404
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403

    data = request.json or {}
    trainer = users[player_id].get('trainer_data', {})

    for key, value in data.items():
        trainer[key] = value

    # o mestre pode editar, mas mantém os INVARIANTES do sistema: atributos
    # 1-20, perícias no teto, dinheiro/nível não-negativos — senão um valor
    # absurdo (ex.: determinacao=99999) corrompe rolagens de perícia e HP.
    trainer_attrs.migrate_trainer(trainer)
    for k in trainer_attrs.ATTRIBUTES:
        try:
            trainer[k] = max(1, min(20, int(trainer.get(k, 10) or 10)))
        except (TypeError, ValueError):
            trainer[k] = 10
    trainer_attrs.clamp_profs(trainer)
    for num_key in ('money', 'level', 'xp', 'hp_max', 'hp_current', 'pokeslots'):
        if num_key in trainer:
            try:
                trainer[num_key] = max(0, int(trainer[num_key]))
            except (TypeError, ValueError):
                trainer.pop(num_key, None)

    users[player_id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'success': True, 'trainer_data': trainer})

@app.route('/master/players/<player_id>/reset-password', methods=['POST'])
@login_required
def master_reset_password(player_id):
    """Master resets a player's password (table-scoped)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    new_password = (request.json or {}).get('password', '').strip()
    if not new_password or len(new_password) < 4:
        return jsonify({'error': 'Senha deve ter pelo menos 4 caracteres'}), 400
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player não encontrado'}), 404
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    users[player_id]['password_hash'] = generate_password_hash(new_password)
    save_users(users)
    return jsonify({'success': True, 'username': users[player_id]['username']})

@app.route('/master/players/<player_id>/delete', methods=['POST'])
@login_required
def master_delete_player(player_id):
    """Master APAGA a conta de um jogador da SUA mesa (permanente).

    Trava de segurança: só jogadores (nunca mestres) e só da própria mesa;
    exige confirmação do nome de usuário no corpo (evita clique acidental)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    target = users.get(player_id)
    if not target:
        return jsonify({'error': 'Conta não encontrada'}), 404
    # nunca deletar outra conta de mestre por esta rota (nem a si mesmo)
    if target.get('role') == 'master' or player_id == str(current_user.id):
        return jsonify({'error': 'Só é possível deletar contas de jogador desta mesa'}), 403
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    # confirmação: o cliente reenvia o username exato do alvo
    confirm = ((request.json or {}).get('confirm_username') or '').strip()
    if confirm != target.get('username'):
        return jsonify({'error': 'Confirmação do nome de usuário não confere'}), 400

    username = target.get('username')
    # solta qualquer estado volátil escopado à mesa (encontro/pedidos)
    try:
        get_game_state().get('active_encounters', {}).pop(player_id, None)
    except Exception:
        pass
    _db_raw.delete_user(player_id)
    socketio.emit('player_left', {'player_id': player_id, 'username': username},
                  room=f'master_{_tid()}')
    return jsonify({'success': True, 'username': username})

@app.route('/master/players/<player_id>/team', methods=['POST'])
@login_required
def master_edit_team(player_id):
    """Master can edit a player's Pokemon team directly (table-scoped)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if player_id not in users:
        return jsonify({'error': 'Player not found'}), 404
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    data = request.json
    users[player_id]['trainer_data']['team'] = data.get('team', [])
    save_users(users)
    return jsonify({'success': True})

# ============================================================
# MASTER — BATTLE OVERSIGHT & CONTROLS
# ============================================================

@app.route('/master/battles/active', methods=['GET'])
@login_required
def master_active_battles():
    """Return all active wild encounters + PVP battles for this table."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tid = _tid()
    game_state = get_game_state()
    encounters = game_state.get('active_encounters', {})

    # Active PVP battles that involve players from this table
    users = get_users()
    table_player_ids = {uid for uid, u in users.items()
                        if u.get('table_id') == tid and u['role'] == 'player'}

    pvp_summary = []
    for bid, battle in ACTIVE_PVP.items():
        p1_id = battle.get('player1', {}).get('id', '')
        p2_id = battle.get('player2', {}).get('id', '')
        if p1_id in table_player_ids or p2_id in table_player_ids:
            pvp_summary.append({
                'battle_id': bid,
                'mode': battle.get('mode'),
                'phase': battle.get('phase'),
                'round': battle.get('round'),
                'winner': battle.get('winner'),
                'player1': p1_id,
                'player2': p2_id,
                'p1_hp': (battle['player1']['team'][battle['player1']['active_idx']].get('currentHp')
                          if battle['player1'].get('active_idx') is not None
                          and battle['player1'].get('team') else None),
                'p2_hp': (battle['player2']['team'][battle['player2']['active_idx']].get('currentHp')
                          if battle['player2'].get('active_idx') is not None
                          and battle['player2'].get('team') else None),
            })

    # Batalhas em grupo ativas da mesa (rehidrata o monitor após reload)
    group_summary = [gb.state_view(b) for b in ACTIVE_GROUP_BATTLES.values()
                     if b.get('table_id') == tid]

    return jsonify({
        'wild_encounters': encounters,
        'pvp_battles': pvp_summary,
        'group_battles': group_summary
    })


@app.route('/master/battles/encounter/<player_id>/force-end', methods=['POST'])
@login_required
def master_force_end_encounter(player_id):
    """Master force-ends a wild encounter for a player."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    data = request.json or {}
    result = data.get('result', 'fled')
    game_state = get_game_state()
    if player_id in game_state.get('active_encounters', {}):
        del game_state['active_encounters'][player_id]
        save_game_state(game_state)
    socketio.emit('encounter_ended', {'player_id': player_id, 'result': result, 'forced_by_master': True},
                  room=player_id)
    socketio.emit('encounter_ended', {'player_id': player_id, 'result': result, 'forced_by_master': True},
                  room=f'master_{_tid()}')
    _spectate('wild', {'id': f'wild_{player_id}', 'players': [player_id],
                       'finished': True, 'result': result})
    return jsonify({'ok': True})


@app.route('/master/battles/encounter/<player_id>/set-hp', methods=['POST'])
@login_required
def master_set_encounter_hp(player_id):
    """Master adjusts HP of player or wild pokemon in active encounter."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    data = request.json or {}
    side = data.get('side', 'wild')   # 'wild' or 'player'
    new_hp = int(data.get('hp', 0))
    game_state = get_game_state()
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter:
        return jsonify({'error': 'Encontro não encontrado'}), 404
    if side == 'wild':
        encounter['battle_state']['wild_hp_current'] = new_hp
        encounter['pokemon']['hp'] = new_hp
    else:
        encounter['battle_state']['player_hp_current'] = new_hp
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    socketio.emit('battle_update', {
        'player_id': player_id,
        'action_by': 'master',
        'action_type': 'hp_edit',
        'battle_state': encounter['battle_state'],
        'message': f'Mestre ajustou HP ({side}): {new_hp}'
    }, room=player_id)
    socketio.emit('battle_update', {
        'player_id': player_id,
        'action_by': 'master',
        'action_type': 'hp_edit',
        'battle_state': encounter['battle_state'],
        'message': f'HP ajustado ({side}): {new_hp}'
    }, room=f'master_{_tid()}')
    return jsonify({'ok': True, 'battle_state': encounter['battle_state']})


@app.route('/master/battles/pvp/<battle_id>/force-end', methods=['POST'])
@login_required
def master_force_end_pvp(battle_id):
    """Master force-ends a PVP battle, declaring a winner or a draw."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    battle = ACTIVE_PVP.get(battle_id)
    if not battle:
        return jsonify({'error': 'Batalha não encontrada'}), 404
    data = request.json or {}
    winner_key = data.get('winner')   # 'player1', 'player2', or None for draw
    battle['phase'] = 'finished'
    battle['winner'] = winner_key
    p1_id = battle['player1']['id']
    p2_id = battle['player2']['id']
    socketio.emit('pvp_battle_state',
                  pvp.get_battle_state_for_player(battle, 'player1'), room=p1_id)
    socketio.emit('pvp_battle_state',
                  pvp.get_battle_state_for_player(battle, 'player2'), room=p2_id)
    if winner_key:
        handle_pvp_victory(battle)
    else:
        ACTIVE_PVP.pop(battle_id, None)
    return jsonify({'ok': True, 'winner': winner_key})


# ============================================================
# NPC MANAGEMENT
# ============================================================

# ── Economia dos NPCs: bolsa + dinheiro ──────────────────────────────────
# Todo NPC começa a jornada com ₽3000 e itens básicos; ganha dinheiro com o
# passar dos dias e às vezes compra itens. Em batalha de rua, o que ele tem
# entra no espólio de verdade (antes o loot vinha/ia para o VAZIO).
NPC_START_MONEY = 3000
NPC_START_BAG = (
    {'name': 'Pokébola', 'qty': 5, 'description': 'Pokébola padrão. DC captura base.'},
    {'name': 'Poção', 'qty': 3, 'description': 'Restaura 2d4+2 HP de um Pokémon.'},
    {'name': 'Super Poção', 'qty': 1, 'description': 'Restaura 4d4+4 HP de um Pokémon.'},
)


def _npc_ensure_economy(npc):
    """Garante money/bag no NPC (migra NPCs antigos). Idempotente."""
    changed = False
    if not isinstance(npc.get('money'), int):
        npc['money'] = NPC_START_MONEY
        changed = True
    if not isinstance(npc.get('bag'), list):
        npc['bag'] = [dict(i) for i in NPC_START_BAG]
        changed = True
    return changed


def _bag_add(bag, name, qty, description=''):
    """Soma qty de um item na bolsa (cria a entrada se não existe)."""
    for bi in bag:
        if isinstance(bi, dict) and (bi.get('name') or '').lower() == name.lower():
            bi['qty'] = int(bi.get('qty') or 0) + qty
            return bag
    bag.append({'name': name, 'qty': qty, 'description': description})
    return bag


@app.route('/master/npcs', methods=['GET'])
@login_required
def list_npcs():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    npcs = db.get_npcs()
    for npc in npcs:
        changed = _mig(npc.get('team', []))
        changed = _npc_ensure_economy(npc) or changed
        if changed:
            db.save_npc(npc)
    return jsonify(npcs)

@app.route('/master/npcs', methods=['POST'])
@login_required
def create_npc():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    npc = {
        'id': secrets.token_hex(4),
        'name': data.get('name', ''),
        'npc_class': data.get('npc_class', ''),
        'level': data.get('level', 10),
        'team': data.get('team', []),
        'notes': data.get('notes', ''),
        'growth_rate': data.get('growth_rate', 'normal'),
        'progression_enabled': bool(data.get('progression_enabled', False)),
        'diary': []
    }
    _npc_ensure_economy(npc)
    db.save_npc(npc)
    return jsonify(npc)

@app.route('/master/npcs/<npc_id>', methods=['PUT'])
@login_required
def update_npc(npc_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    npcs = db.get_npcs()
    npc  = next((n for n in npcs if n['id'] == npc_id), None)
    if not npc:
        return jsonify({'error': 'NPC not found'}), 404
    # 'diary' fica de fora de propósito: é gerenciado pelo servidor
    for field in ['name', 'npc_class', 'level', 'role', 'specialty', 'money',
                  'team', 'notes', 'growth_rate', 'progression_enabled']:
        if field in data:
            npc[field] = data[field]
    db.save_npc(npc)
    socketio.emit('npcs_update', {'npcs': db.get_npcs()}, room=f'master_{_tid()}')
    return jsonify(npc)


@app.route('/master/npcs/<npc_id>', methods=['DELETE'])
@login_required
def delete_npc(npc_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    db.delete_npc(npc_id)
    return jsonify({'success': True})

@app.route('/master/npcs/generate', methods=['POST'])
@login_required
def generate_npc():
    """Auto-generate an NPC with themed team based on class/type."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    npc_class = data.get('npc_class', 'Trainer')
    level = _int_arg(data, 'level', 10, lo=1, hi=100)
    team_size = int(data.get('team_size', 3))
    preferred_types = data.get('types', [])  # e.g. ['fire', 'fighting']
    
    # NPC name generation
    first_names = [
        'Akira', 'Brock', 'Cynthia', 'Drake', 'Elesa', 'Flint', 'Gardenia', 
        'Hau', 'Iris', 'Jasmine', 'Koga', 'Lance', 'Misty', 'Norman',
        'Olivia', 'Phoebe', 'Quinn', 'Raihan', 'Sabrina', 'Tate',
        'Uri', 'Volkner', 'Wallace', 'Xerxes', 'Yuki', 'Zinnia',
        'Bruno', 'Clair', 'Diantha', 'Erika', 'Fantina', 'Guzma',
        'Hex', 'Ilima', 'Jupiter', 'Karen', 'Lorelei', 'Marlon',
        'Nessa', 'Opal', 'Piers', 'Roxie', 'Skyla', 'Thorton',
        'Wulfric', 'Allister', 'Bea', 'Gordie', 'Melony', 'Leon'
    ]
    
    titles = {
        'Gym Leader': 'Líder ',
        'Elite Four': 'Elite ',
        'Champion': 'Campeão(ã) ',
        'Trainer': '',
        'Ranger': 'Ranger ',
        'Rocket': 'Rocket ',
        'Ace': 'Ás ',
        'Breeder': 'Criador(a) ',
        'Youngster': 'Jovem ',
        'Hiker': 'Montanhista ',
        'Swimmer': 'Nadador(a) ',
        'Psychic': 'Médium ',
        'Bug Catcher': 'Caça-insetos ',
        'Fisherman': 'Pescador ',
        'Beauty': '',
        'Scientist': 'Cientista ',
        'Blackbelt': 'Faixa Preta '
    }
    
    name_prefix = titles.get(npc_class, '')
    name = name_prefix + random.choice(first_names)
    
    # Determine types for team
    class_type_map = {
        'Gym Leader': preferred_types,
        'Elite Four': preferred_types,
        'Champion': [],  # mixed
        'Trainer': [],
        'Ranger': ['grass', 'bug', 'normal'],
        'Rocket': ['poison', 'dark', 'ghost'],
        'Ace': [],
        'Breeder': ['normal', 'fairy'],
        'Youngster': ['normal', 'bug'],
        'Hiker': ['rock', 'ground', 'fighting'],
        'Swimmer': ['water'],
        'Psychic': ['psychic', 'ghost'],
        'Bug Catcher': ['bug'],
        'Fisherman': ['water'],
        'Scientist': ['electric', 'steel', 'psychic'],
        'Blackbelt': ['fighting']
    }
    
    types_to_use = preferred_types if preferred_types else class_type_map.get(npc_class, [])
    
    # Build team
    team = []
    candidates = []
    
    if types_to_use:
        for t in types_to_use:
            candidates.extend(POKEMON_BY_TYPE.get(t.lower(), []))
        # Remove duplicates
        seen = set()
        unique = []
        for c in candidates:
            if c['number'] not in seen:
                seen.add(c['number'])
                unique.append(c)
        candidates = unique
    else:
        candidates = POKEMON_DB[:]

    # Mesa limitada à 1ª geração (≤151)
    candidates = [p for p in candidates if p.get('number', 999) <= 151]

    # Filter by level appropriateness
    level_filtered = [p for p in candidates if p.get('minLevel', 1) <= level]
    if not level_filtered:
        level_filtered = candidates[:50]
    
    # Prefer evolved pokemon for higher levels
    if level >= 15:
        evolved = [p for p in level_filtered if '/' in p.get('evolutionStage', '1/1') and int(p['evolutionStage'].split('/')[0]) >= 2]
        if len(evolved) >= team_size:
            level_filtered = evolved
    
    # Pick random team
    pick_count = min(team_size, len(level_filtered))
    chosen_pokemon = random.sample(level_filtered, pick_count) if pick_count > 0 else []
    
    for poke in chosen_pokemon:
        # Calculate pokemon level (around NPC level ±2)
        poke_level = max(poke.get('minLevel', 1), level + random.randint(-2, 1))

        # Build moveset (levelMoves keys são escala de treinador → ×5)
        move_pool = list(poke.get('startingMoves', []))
        if poke.get('levelMoves'):
            for lv, moves in poke['levelMoves'].items():
                if int(lv) * 5 <= poke_level:
                    move_pool.extend(moves)
        move_pool = [m for m in move_pool if len(m) > 2 and '©' not in m and 'unofficial' not in m.lower() and 'wizards' not in m.lower() and 'nintendo' not in m.lower() and 'portions' not in m.lower() and len(m) < 30]
        move_pool = list(dict.fromkeys(move_pool))
        move_pool = [m for m in move_pool if m.lower() in MOVES_BY_NAME or m in MOVES_DB]
        moves = move_pool[-4:] if len(move_pool) > 4 else (move_pool if move_pool else ['Tackle'])
        # mesma garantia dos selvagens: ≥1 golpe de dano sem recarga
        moves = _ensure_filler_move(moves, move_pool)

        # Stats escalados pelo nível (igual aos encontros selvagens)
        scaled = scaling.calculate_pokemon_stats(poke, poke_level)
        team.append({
            'name': poke['name'],
            'number': poke['number'],
            'level': poke_level,
            'types': poke.get('types', []),
            'hp': scaled['hp'],
            'maxHp': scaled['maxHp'],
            'currentHp': scaled['hp'],
            'ac': scaled['ac'],
            'stats': scaled['stats'],
            'proficiency': scaled['proficiency'],
            'stab': scaled['stab'],
            'moves': moves,
            'speed': poke.get('speed', '30ft'),
            'ability': poke.get('ability', {}).get('name', '') if poke.get('ability') else '',
            'vulnerabilities': poke.get('vulnerabilities', []),
            'resistances': poke.get('resistances', []),
            'immunities': poke.get('immunities', []),
            'sv': migrations.STATS_VERSION
        })
    
    # Create NPC
    npc = {
        'id': secrets.token_hex(4),
        'name': name,
        'npc_class': npc_class + (' - ' + '/'.join(t.title() for t in types_to_use) if types_to_use else ''),
        'level': level,
        'team': team,
        'notes': f'Gerado automaticamente. {team_size} Pokémon.',
        'generated': True,
        'growth_rate': data.get('growth_rate', 'normal'),
        'progression_enabled': bool(data.get('progression_enabled', False)),
        'diary': []
    }
    _npc_ensure_economy(npc)   # ₽3000 + itens básicos de início de jornada
    db.save_npc(npc)
    return jsonify(npc)


# ── 🎁 Presentes do Mestre: Pokémon, itens e dinheiro ───────────────────────
def _build_gift_pokemon(base, level, is_shiny=False, nickname=''):
    """Monta um Pokémon de time a partir da espécie (mesmo formato dos
    gerados para NPCs/encontros), para o mestre presentear em quest/torneio."""
    level = max(1, min(100, int(level or 5)))
    move_pool = list(base.get('startingMoves', []))
    for lv, moves in (base.get('levelMoves') or {}).items():
        if int(lv) * 5 <= level:
            move_pool.extend(moves)
    move_pool = list(dict.fromkeys(
        m for m in move_pool if m.lower() in MOVES_BY_NAME or m in MOVES_DB))
    moves = _ensure_filler_move(move_pool[-4:] if move_pool else ['Tackle'], move_pool)
    scaled = scaling.calculate_pokemon_stats(base, level, is_shiny=is_shiny)
    poke = {
        'name': base['name'],
        'number': base['number'],
        'level': level,
        'types': base.get('types', []),
        'hp': scaled['hp'], 'maxHp': scaled['maxHp'], 'currentHp': scaled['hp'],
        'ac': scaled['ac'], 'stats': scaled['stats'],
        'proficiency': scaled['proficiency'], 'stab': scaled['stab'],
        'moves': moves,
        'speed': base.get('speed', '30ft'),
        'ability': (base.get('ability') or {}).get('name', '') if base.get('ability') else '',
        'vulnerabilities': base.get('vulnerabilities', []),
        'resistances': base.get('resistances', []),
        'immunities': base.get('immunities', []),
        'evolutionInfo': base.get('evolutionInfo', ''),
        'is_shiny': bool(is_shiny),
        'xp': 0, 'totalXp': 0, 'battle_wins': 0,
        'sv': migrations.STATS_VERSION,
    }
    if nickname:
        poke['nickname'] = str(nickname)[:30]
    return poke


@app.route('/master/give-pokemon', methods=['POST'])
@login_required
def master_give_pokemon():
    """Mestre dá um Pokémon ESPECÍFICO a um jogador (quest, campeonato,
    presente de NPC...). Vai pro time se houver vaga, senão pro PC."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = str(data.get('player_id') or '')
    species = (data.get('species') or '').strip()

    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    base = POKEMON_BY_NAME.get(species.lower())
    if not base and str(species).isdigit():
        base = next((p for p in POKEMON_DB if int(p.get('number', 0)) == int(species)), None)
    if not base:
        return jsonify({'error': f'Espécie não encontrada: {species}'}), 404

    poke = _build_gift_pokemon(base, data.get('level', 5),
                               is_shiny=bool(data.get('shiny')),
                               nickname=data.get('nickname') or '')
    trainer = users[player_id].get('trainer_data', {})
    team = trainer.get('team', [])
    if len(team) < 6:
        team.append(poke)
        trainer['team'] = team
        destino = 'time'
    else:
        pc = trainer.get('pc', [])
        pc.append(poke)
        trainer['pc'] = pc
        destino = 'PC (time cheio)'
    users[player_id]['trainer_data'] = trainer
    save_users(users)
    _grant_encounter(player_id, base['number'])   # registra na pokédex

    note = str(data.get('note') or '')[:120]
    socketio.emit('gift_received', {
        'kind': 'pokemon',
        'pokemon': {'name': poke['name'], 'nickname': poke.get('nickname'),
                    'level': poke['level'], 'is_shiny': poke['is_shiny'],
                    'number': poke['number']},
        'destination': destino, 'note': note,
        'from': data.get('from') or 'O Mestre',
    }, room=player_id)
    return jsonify({'ok': True, 'pokemon': poke, 'destination': destino})


@app.route('/master/give-item', methods=['POST'])
@login_required
def master_give_item():
    """Mestre dá itens e/ou dinheiro a um jogador (recompensa de quest,
    presente de NPC...). Item pode ser do catálogo ou de história (nome livre)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = str(data.get('player_id') or '')
    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403

    item_name = (data.get('item_name') or '').strip()[:60]
    qty = max(0, min(999, int(data.get('qty') or 0)))
    money = max(0, min(1_000_000, int(data.get('money') or 0)))
    if not (item_name and qty) and not money:
        return jsonify({'error': 'Informe um item (com quantidade) e/ou dinheiro'}), 400

    trainer = users[player_id].get('trainer_data', {})
    given = {}
    if item_name and qty:
        catalog = next((i for i in SHOP_CATALOG
                        if i['name'].lower() == item_name.lower()
                        or i['id'] == item_name.lower()), None)
        name = catalog['name'] if catalog else item_name
        desc = catalog.get('description', '') if catalog else str(data.get('description') or '')[:120]
        _bag_add(trainer.setdefault('bag', []), name, qty, desc)
        given['item'] = {'name': name, 'qty': qty}
    if money:
        trainer['money'] = int(trainer.get('money') or 0) + money
        given['money'] = money
    users[player_id]['trainer_data'] = trainer
    save_users(users)

    socketio.emit('gift_received', {
        'kind': 'item', **given,
        'note': str(data.get('note') or '')[:120],
        'from': data.get('from') or 'O Mestre',
        'bag': trainer.get('bag'), 'total_money': trainer.get('money'),
    }, room=player_id)
    return jsonify({'ok': True, **given, 'money_total': trainer.get('money')})


def _carry_evolution_potential(old_poke, evolved, evolved_base):
    """Custom EVs: ao evoluir, preserva os campos de Potencial e ROLA o bônus
    permanente (1d6 ao chegar no estágio 2, 1d8 no 3) dos estágios cruzados."""
    from_cur, _ = bm_core.parse_evolution_stage(
        old_poke.get('evolutionStage')
        or (POKEMON_BY_NAME.get((old_poke.get('name') or '').lower()) or {}).get('evolutionStage'))
    to_cur, _ = bm_core.parse_evolution_stage(evolved_base.get('evolutionStage'))
    evolved['potential_evo_bonus'] = int(old_poke.get('potential_evo_bonus') or 0) \
        + migrations.roll_evolution_bonus(from_cur, to_cur)
    evolved['potential_special'] = old_poke.get('potential_special', 0)
    evolved['training_bonus'] = old_poke.get('training_bonus', 0)
    evolved['pp'] = migrations.PP_VERSION
    return evolved


def build_evolved_pokemon(pokemon, evolved_base):
    """Monta o dict do Pokémon evoluído a partir da espécie-alvo, preservando
    os dados do jogador (shiny, nickname, nature, moves, item, XP, treino,
    potencial). Builder ÚNICO usado por nível, pedra e recompensas de batalha
    — mantém imunidades/phys_ac/spec_ac consistentes em todos os caminhos."""
    current_level = pokemon.get('level', 1)
    scaled = scaling.calculate_pokemon_stats(evolved_base, current_level, pokemon.get('nature'),
                                             is_shiny=pokemon.get('is_shiny', False),
                                             training=pokemon.get('training'))
    evolved = {
        'name': evolved_base['name'],
        'number': evolved_base['number'],
        'types': evolved_base.get('types', pokemon.get('types', [])),
        'level': current_level,
        'hp': scaled['hp'],
        'maxHp': scaled['maxHp'],
        'currentHp': min(pokemon.get('currentHp', scaled['hp']), scaled['hp']),
        'ac': scaled['ac'],
        'stats': scaled['stats'],
        'proficiency': scaled['proficiency'],
        'stab': scaled['stab'],
        'speed': evolved_base.get('speed', pokemon.get('speed', '30ft')),
        'ability': evolved_base.get('ability', {}).get('name', '') if evolved_base.get('ability') else pokemon.get('ability', ''),
        'vulnerabilities': evolved_base.get('vulnerabilities', []),
        'resistances': evolved_base.get('resistances', []),
        'immunities': evolved_base.get('immunities', []),
        'phys_ac': scaled.get('phys_ac'),
        'spec_ac': scaled.get('spec_ac'),
        'evolutionInfo': evolved_base.get('evolutionInfo', ''),
        'evolutionStage': evolved_base.get('evolutionStage', ''),
        # Preserve player-specific fields
        'is_shiny': pokemon.get('is_shiny', False),
        'training': pokemon.get('training'),
        'sv': migrations.STATS_VERSION,
        'nickname': pokemon.get('nickname', ''),
        'nature': pokemon.get('nature', ''),
        'moves': pokemon.get('moves', []),
        'heldItem': pokemon.get('heldItem', ''),
        'notes': pokemon.get('notes', ''),
        'xp': pokemon.get('xp', 0),
        'totalXp': pokemon.get('totalXp', 0),
        'battle_wins': pokemon.get('battle_wins', 0),
        'statPointsAvailable': pokemon.get('statPointsAvailable', 0),
    }
    _carry_evolution_potential(pokemon, evolved, evolved_base)
    return evolved


def _evolution_new_moves(pokemon, evolved_base):
    """Golpes novos que a forma evoluída traz (startingMoves que o Pokémon
    ainda não conhece e existem no banco de moves)."""
    return [m for m in (evolved_base.get('startingMoves') or [])
            if m not in (pokemon.get('moves') or [])
            and m.lower() in MOVES_BY_NAME]


def _emit_evolution_focus(player_id, player_name, slot, old_pokemon, evolved, new_moves, source):
    """Broadcast do evento de evolução para a MESA INTEIRA (jogadores +
    mestre): todas as telas focam na animação do Pokémon evoluindo."""
    payload = {
        'player_id': str(player_id),
        'player_name': player_name or '',
        'slot': slot,
        'old_name': old_pokemon.get('name', ''),
        'new_name': evolved.get('name', ''),
        'old_number': old_pokemon.get('number', 0),
        'new_number': evolved.get('number', 0),
        'nickname': evolved.get('nickname', ''),
        'shiny': bool(evolved.get('is_shiny')),
        'new_moves': new_moves or [],
        'source': source,
    }
    socketio.emit('evolution_focus', payload, room=f'players_{_tid()}')
    socketio.emit('evolution_focus', payload, room=f'master_{_tid()}')


def check_and_evolve_pokemon(pokemon, trainer_level=None):
    """Checa evolução por nível do POKÉMON: o 'level N' do evolutionInfo
    (escala 5e) vira N×5 na escala canon e é comparado com o nível do
    próprio Pokémon. O parâmetro trainer_level é aceito por
    compatibilidade e ignorado.
    Returns (evolved_pokemon_data, evolved_name) or (None, None)."""
    info = pokemon.get('evolutionInfo', '') or ''
    if not info:
        # Fall back to base Pokémon data in case team entry predates evolutionInfo field
        base = POKEMON_BY_NAME.get((pokemon.get('name') or '').lower())
        info = (base or {}).get('evolutionInfo', '') or ''
    if not info:
        return None, None

    evolved_name, evo_level = scaling.parse_level_evolution(info)
    if not evolved_name:
        return None, None

    if pokemon.get('level', 1) < evo_level:
        return None, None

    _key = evolved_name.lower()
    evolved_base = POKEMON_BY_NAME.get(scaling.EVO_TARGET_ALIASES.get(_key, _key))
    if not evolved_base:
        return None, None

    evolved = build_evolved_pokemon(pokemon, evolved_base)
    return evolved, evolved_base['name']


@app.route('/master/xp', methods=['POST'])
@login_required
def give_xp():
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    player_id = data.get('player_id')
    xp_amount = int(data.get('xp', 0))

    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    if player_id in users:
        trainer = users[player_id].get('trainer_data', {})
        lv_info = _apply_xp(trainer, xp_amount)
        new_level = lv_info['new_level']
        old_level = lv_info['old_level']

        # Auto-level Pokemon (trainer level - 2, min 1) and check evolution
        evolutions = []
        for i, pokemon in enumerate(trainer.get('team', [])):
            if pokemon.get('level', 1) < new_level - 2:
                pokemon['level'] = max(1, new_level - 2)
                # Recalculate stats for the new level
                base_poke = POKEMON_BY_NAME.get((pokemon.get('name') or '').lower())
                if base_poke:
                    scaled = scaling.calculate_pokemon_stats(base_poke, pokemon['level'], pokemon.get('nature'),
                                                             is_shiny=pokemon.get('is_shiny', False),
                                                             training=pokemon.get('training'))
                    old_ratio = pokemon.get('currentHp', scaled['hp']) / max(1, pokemon.get('maxHp', scaled['hp']))
                    pokemon['stats'] = scaled['stats']
                    pokemon['maxHp'] = scaled['hp']
                    pokemon['currentHp'] = max(1, int(scaled['hp'] * old_ratio))
                    pokemon['proficiency'] = scaled['proficiency']
                    pokemon['stab'] = scaled['stab']
                    pokemon['phys_ac'] = scaled['phys_ac']
                    pokemon['spec_ac'] = scaled['spec_ac']
            evolved, evolved_name = check_and_evolve_pokemon(pokemon)
            if evolved:
                old_name = pokemon.get('name', '')
                old_number = pokemon.get('number', 0)
                evolved_base_data = POKEMON_BY_NAME.get(evolved_name.lower(), {})
                new_moves = _evolution_new_moves(pokemon, evolved_base_data)
                trainer['team'][i] = evolved
                evolutions.append({
                    'from': old_name, 'to': evolved_name, 'slot': i,
                    'old_number': old_number, 'new_number': evolved.get('number', 0),
                    'new_moves': new_moves,
                    '_old_pokemon': pokemon, '_evolved': evolved,
                })

        users[player_id]['trainer_data'] = trainer
        save_users(users)

        # Foco de evolução para a mesa inteira (todas as telas)
        for ev in evolutions:
            _emit_evolution_focus(player_id, users[player_id].get('username', ''),
                                  ev['slot'], ev.pop('_old_pokemon'), ev.pop('_evolved'),
                                  ev['new_moves'], 'level')

        # Emit XP update to specific player
        socketio.emit('xp_update', {
            'player_id': player_id,
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level,
            'evolutions': evolutions
        }, room=player_id)
        
        # Also notify master
        socketio.emit('xp_update', {
            'player_id': player_id,
            'username': users[player_id]['username'],
            'xp': trainer['xp'],
            'level': trainer['level'],
            'xp_to_next': trainer['xp_to_next'],
            'leveled_up': new_level > old_level
        }, room=f'master_{_tid()}')
        
        return jsonify({'success': True, 'level': new_level, 'xp': trainer['xp']})
    return jsonify({'error': 'Player not found'}), 404

@app.route('/master/player-team/<player_id>', methods=['GET'])
@login_required
def master_get_player_team(player_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    team = users[player_id].get('trainer_data', {}).get('team', [])
    return jsonify({'team': [{'name': p.get('name'), 'level': p.get('level', 1)} for p in team]})

@app.route('/master/pokemon-xp', methods=['POST'])
@login_required
def give_pokemon_xp():
    """Master gives XP directly to a specific Pokémon on a player's team."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = data.get('player_id')
    pokemon_idx = data.get('pokemon_idx')
    xp_amount = int(data.get('xp', 0))

    if not player_id or pokemon_idx is None or xp_amount <= 0:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403

    trainer = users[player_id].get('trainer_data', {})
    team = trainer.get('team', [])
    if pokemon_idx < 0 or pokemon_idx >= len(team):
        return jsonify({'error': 'Pokémon inválido'}), 400

    pokemon = team[pokemon_idx]
    old_level = pokemon.get('level', 1)
    # Mesma tabela de XP usada pelo cliente (totalXp acumulado)
    pokemon['xp'] = pokemon.get('xp', 0) + xp_amount
    pokemon['totalXp'] = pokemon.get('totalXp', 0) + xp_amount
    new_level = max(old_level, scaling.level_from_xp(pokemon['totalXp']))
    pokemon['level'] = new_level

    leveled_up = new_level > old_level
    if leveled_up:
        base_poke = POKEMON_BY_NAME.get((pokemon.get('name') or '').lower())
        if base_poke:
            scaled = scaling.calculate_pokemon_stats(base_poke, new_level, pokemon.get('nature'),
                                                     is_shiny=pokemon.get('is_shiny', False),
                                                     training=pokemon.get('training'))
            old_ratio = pokemon.get('currentHp', scaled['hp']) / max(1, pokemon.get('maxHp', scaled['hp']))
            pokemon['stats'] = scaled['stats']
            pokemon['maxHp'] = scaled['hp']
            pokemon['currentHp'] = max(1, int(scaled['hp'] * old_ratio))
            pokemon['proficiency'] = scaled['proficiency']
            pokemon['stab'] = scaled['stab']
            pokemon['phys_ac'] = scaled['phys_ac']
            pokemon['spec_ac'] = scaled['spec_ac']

    # Check evolution (nível do próprio Pokémon)
    evolved, evolved_name = check_and_evolve_pokemon(pokemon)
    evolution = None
    if evolved:
        old_name = pokemon.get('name', '')
        old_number = pokemon.get('number', 0)
        trainer['team'][pokemon_idx] = evolved
        evolution = {
            'from': old_name, 'to': evolved_name, 'slot': pokemon_idx,
            'old_number': old_number, 'new_number': evolved.get('number', 0)
        }
    else:
        trainer['team'][pokemon_idx] = pokemon

    users[player_id]['trainer_data'] = trainer
    save_users(users)

    if evolved:
        evolved_base_data = POKEMON_BY_NAME.get(evolved_name.lower(), {})
        _emit_evolution_focus(player_id, users[player_id].get('username', ''),
                              pokemon_idx, pokemon, evolved,
                              _evolution_new_moves(pokemon, evolved_base_data), 'level')

    socketio.emit('pokemon_xp_update', {
        'pokemon_idx': pokemon_idx,
        'pokemon_name': pokemon.get('name'),
        'level': new_level,
        'xp': pokemon.get('xp', 0),
        'leveled_up': leveled_up,
        'evolution': evolution
    }, room=player_id)

    return jsonify({
        'success': True,
        'pokemon_name': pokemon.get('name'),
        'level': new_level,
        'xp': pokemon.get('xp', 0),
        'leveled_up': leveled_up,
        'evolution': evolution
    })


@app.route('/master/pokemon-points', methods=['POST'])
@login_required
def give_pokemon_points():
    """Mestre concede/remove pontos Custom EVs a UM Pokémon do time do jogador:
    Pontos de Potencial (potential_special) ou de Treinamento (training_bonus),
    conforme a flexibilidade do sistema (captura, ginásio, evento...)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = data.get('player_id')
    pokemon_idx = data.get('pokemon_idx')
    kind = (data.get('kind') or 'potential').strip()   # 'potential' | 'training'
    try:
        amount = int(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Quantidade inválida'}), 400

    if not player_id or pokemon_idx is None or amount == 0:
        return jsonify({'error': 'Parâmetros inválidos'}), 400
    if kind not in ('potential', 'training'):
        return jsonify({'error': 'Tipo inválido'}), 400

    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    trainer = users[player_id].get('trainer_data', {})
    team = trainer.get('team', [])
    _mig(team)
    if pokemon_idx < 0 or pokemon_idx >= len(team):
        return jsonify({'error': 'Pokémon inválido'}), 400

    poke = team[pokemon_idx]
    field = 'potential_special' if kind == 'potential' else 'training_bonus'
    poke[field] = max(0, int(poke.get(field) or 0) + amount)   # nunca negativo
    base = POKEMON_BY_NAME.get((poke.get('name') or '').lower()) \
        or POKEMON_BY_NUMBER.get(poke.get('number'))
    # saldo derivado do novo orçamento (a distribuição atual continua válida)
    budget = migrations.budget_for(poke, base)
    poke['statPointsAvailable'] = max(0, budget - bm_core.training_spent(poke.get('training') or {}))
    users[player_id]['trainer_data'] = trainer
    save_users(users)

    socketio.emit('pokemon_points_update', {
        'pokemon_idx': pokemon_idx, 'pokemon_name': poke.get('name'),
        'kind': kind, 'amount': amount,
        'statPointsAvailable': poke['statPointsAvailable'],
    }, room=player_id)
    return jsonify({'success': True, 'field': field, 'value': poke[field],
                    'statPointsAvailable': poke['statPointsAvailable']})

# ============================================================
# SITE SETTINGS API
# ============================================================
@app.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    """Get current site settings (available to all users)."""
    return jsonify(db.get_site_settings())

@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    """Update site settings (master only). Broadcasts to all connected users."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    settings = db.get_site_settings()
    allowed_fields = ['theme', 'background', 'custom_banner', 'mesa_name']
    for field in allowed_fields:
        if field in data:
            settings[field] = data[field]
    db.save_site_settings(settings)
    # Broadcast theme change to ALL connected users in real-time
    socketio.emit('theme_changed', settings)
    return jsonify(settings)

# ============================================================
# POKEMON API
# ============================================================
@app.route('/api/pokemon')
@login_required
def api_pokemon_list():
    """List all pokemon with optional filters."""
    type_filter = request.args.get('type', '').lower()
    level_min = int(request.args.get('level_min', 0))
    level_max = int(request.args.get('level_max', 100))
    search = request.args.get('search', '').lower()
    
    results = POKEMON_DB
    if type_filter:
        results = [p for p in results if type_filter in [t.lower() for t in p.get('types', [])]]
    if level_min > 0:
        results = [p for p in results if p.get('minLevel', 0) >= level_min]
    if level_max < 100:
        results = [p for p in results if p.get('minLevel', 0) <= level_max]
    if search:
        results = [p for p in results if search in p['name'].lower() or search == str(p['number'])]
    
    limit = int(request.args.get('limit', 50))
    return jsonify(results[:limit])

@app.route('/api/pokemon/all')
@login_required
def api_pokemon_all():
    """Return slim list of ALL pokemon for the Pokedex (number, name, types only)."""
    return jsonify([{'number': p['number'], 'name': p['name'], 'types': p.get('types', [])} for p in POKEMON_DB])

@app.route('/api/pokemon/<int:number>')
@login_required
def api_pokemon_detail(number):
    """Get a specific Pokemon by number."""
    pokemon = POKEMON_BY_NUMBER.get(number)
    if pokemon:
        return jsonify(pokemon)
    return jsonify({'error': 'Pokemon not found'}), 404

# TM número → move (lista Gen 7/USUM, usada pelo Pokémon 5e)
TM_MOVES = {
    1: 'Work Up', 2: 'Dragon Claw', 3: 'Psyshock', 4: 'Calm Mind', 5: 'Roar',
    6: 'Toxic', 7: 'Hail', 8: 'Bulk Up', 9: 'Venoshock', 10: 'Hidden Power',
    11: 'Sunny Day', 12: 'Taunt', 13: 'Ice Beam', 14: 'Blizzard', 15: 'Hyper Beam',
    16: 'Light Screen', 17: 'Protect', 18: 'Rain Dance', 19: 'Roost', 20: 'Safeguard',
    21: 'Frustration', 22: 'Solar Beam', 23: 'Smack Down', 24: 'Thunderbolt', 25: 'Thunder',
    26: 'Earthquake', 27: 'Return', 28: 'Leech Life', 29: 'Psychic', 30: 'Shadow Ball',
    31: 'Brick Break', 32: 'Double Team', 33: 'Reflect', 34: 'Sludge Wave', 35: 'Flamethrower',
    36: 'Sludge Bomb', 37: 'Sandstorm', 38: 'Fire Blast', 39: 'Rock Tomb', 40: 'Aerial Ace',
    41: 'Torment', 42: 'Facade', 43: 'Flame Charge', 44: 'Rest', 45: 'Attract',
    46: 'Thief', 47: 'Low Sweep', 48: 'Round', 49: 'Echoed Voice', 50: 'Overheat',
    51: 'Steel Wing', 52: 'Focus Blast', 53: 'Energy Ball', 54: 'False Swipe', 55: 'Scald',
    56: 'Fling', 57: 'Charge Beam', 58: 'Sky Drop', 59: 'Brutal Swing', 60: 'Quash',
    61: 'Will-O-Wisp', 62: 'Acrobatics', 63: 'Embargo', 64: 'Explosion', 65: 'Shadow Claw',
    66: 'Payback', 67: 'Smart Strike', 68: 'Giga Impact', 69: 'Rock Polish', 70: 'Aurora Veil',
    71: 'Stone Edge', 72: 'Volt Switch', 73: 'Thunder Wave', 74: 'Gyro Ball', 75: 'Swords Dance',
    76: 'Fly', 77: 'Psych Up', 78: 'Bulldoze', 79: 'Frost Breath', 80: 'Rock Slide',
    81: 'X-Scissor', 82: 'Dragon Tail', 83: 'Infestation', 84: 'Poison Jab', 85: 'Dream Eater',
    86: 'Grass Knot', 87: 'Swagger', 88: 'Sleep Talk', 89: 'U-turn', 90: 'Substitute',
    91: 'Flash Cannon', 92: 'Trick Room', 93: 'Wild Charge', 94: 'Surf', 95: 'Snarl',
    96: 'Nature Power', 97: 'Dark Pulse', 98: 'Waterfall', 99: 'Dazzling Gleam', 100: 'Confide',
}


def _clean_move_list(moves):
    """Filtra entradas inválidas e mantém só moves que existem no banco."""
    out = []
    for m in moves or []:
        if not m or not isinstance(m, str) or len(m) <= 2 or len(m) >= 30:
            continue
        low = m.lower()
        if '©' in m or m.isdigit() or any(j in low for j in ('unofficial', 'wizards', 'nintendo', 'portions')):
            continue
        if low in MOVES_BY_NAME or m in MOVES_DB:
            out.append(m)
    return list(dict.fromkeys(out))


@app.route('/api/pokemon/<int:number>/learnset')
@login_required
def api_pokemon_learnset(number):
    """Learnset limpo da espécie para os dropdowns de seleção de moves.

    levelMoves usa escala de nível de treinador (1-20) nos dados originais —
    aqui é convertido para nível de Pokémon (×5).
    """
    pokemon = POKEMON_BY_NUMBER.get(number)
    if not pokemon:
        return jsonify({'error': 'Pokemon not found'}), 404

    starting = _clean_move_list(pokemon.get('startingMoves'))
    level_moves = {}
    for lv, moves in (pokemon.get('levelMoves') or {}).items():
        cleaned = _clean_move_list(moves)
        if cleaned:
            try:
                level_moves[str(int(lv) * 5)] = cleaned
            except (TypeError, ValueError):
                continue
    # tmMoves vem como números de TM → resolve para nomes
    tm_names = [TM_MOVES.get(n) for n in (pokemon.get('tmMoves') or [])
                if isinstance(n, int)]
    tm = _clean_move_list([m for m in tm_names if m])
    egg = _clean_move_list(pokemon.get('eggMoves'))

    all_moves = list(dict.fromkeys(
        starting + [m for ms in level_moves.values() for m in ms] + tm + egg))

    # Habilidades da espécie (para os dropdowns da ficha)
    abilities = [
        {'name': a.get('name'), 'description': a.get('description', '')}
        for a in (pokemon.get('abilities') or []) if a.get('name')
    ]
    hidden = pokemon.get('hiddenAbility') or None
    if hidden and not hidden.get('name'):
        hidden = None

    return jsonify({
        'number': number,
        'name': pokemon.get('name'),
        'starting': starting,
        'level': level_moves,
        'tm': tm,
        'egg': egg,
        'all': all_moves,
        'abilities': abilities,
        'hidden_ability': hidden,
        'senses': pokemon.get('senses', '')
    })


def _move_with_canon(name, move):
    """Move local + power/accuracy/priority/drain canônicos (sistema v2)."""
    canon = canon_move(name)
    out = dict(move)
    out['power_num'] = canon.get('power')
    out['accuracy'] = canon.get('accuracy')
    out['priority'] = canon.get('priority', 0)
    out['drain'] = canon.get('drain', 0)   # >0 = dreno → recarga de sustain
    return out


def _canon_power(m):
    """POW canônico de um move (0 se status/desconhecido)."""
    try:
        return int(canon_move(m).get('power') or 0) or \
            int(bm_core.VARIABLE_POWER.get(m.lower(), 0))
    except (TypeError, ValueError):
        return 0


def _move_sem_recarga(m):
    """True se é golpe de dano SEM recarga alguma: POW ≤ 65 (Tabela Mestra)
    E sem dreno (Absorb/Mega Drain têm POW baixo mas recarga de sustain)."""
    p = _canon_power(m)
    if p <= 0:
        return False
    try:
        drain = int(canon_move(m).get('drain') or 0)
    except (TypeError, ValueError):
        drain = 0
    return bm_core.v3_move_cooldown(p, drain) == 0


def _ensure_filler_move(moves, move_pool):
    """Garante ≥1 golpe de dano sem recarga no moveset (Tabela Mestra: recarga
    a partir do degrau 70-80) — senão a IA fica sem ação nas rodadas de
    espera. Usado pelos geradores de selvagem, NPC e presente."""
    moves = [m for m in (moves or []) if m]
    if any(_move_sem_recarga(m) for m in moves):
        return moves[:4] if moves else ['Tackle']
    filler = next((m for m in sorted(move_pool or [], key=_canon_power)
                   if _move_sem_recarga(m)), 'Tackle')
    return ([filler] + [m for m in moves if m != filler])[:4]


@app.route('/api/moves')
@login_required
def api_moves():
    """Get move data. Query by name."""
    name = request.args.get('name', '').strip()
    if name:
        move = MOVES_BY_NAME.get(name.lower()) or MOVES_DB.get(name)
        if move:
            return jsonify(_move_with_canon(name, move))
        # Fuzzy search
        results = [_move_with_canon(k, v) for k, v in MOVES_DB.items() if name.lower() in k.lower()]
        if results:
            return jsonify(results[:10])
    return jsonify({}), 404

@app.route('/api/moves/batch', methods=['POST'])
@login_required
def api_moves_batch():
    """Get multiple moves at once."""
    data = request.json
    move_names = data.get('moves', [])
    results = {}
    for name in move_names:
        move = MOVES_BY_NAME.get(name.lower()) or MOVES_DB.get(name)
        if move:
            results[name] = _move_with_canon(name, move)
    return jsonify(results)

@app.route('/api/mega/<pokemon_name>')
@login_required
def api_mega(pokemon_name):
    """Get mega evolution data for a pokemon."""
    megas = MEGA_BY_POKEMON.get(pokemon_name.lower(), [])
    if megas:
        return jsonify(megas)
    return jsonify([]), 404

@app.route('/api/mega')
@login_required
def api_mega_all():
    """Get all mega stones."""
    return jsonify(MEGA_DB)

def _build_random_encounter(route_id, hunt_mode, player_level, is_ambush=False):
    """Gera um encontro selvagem aleatório (puro, sem gate nem estado).

    O teste de caçada é MANUAL: o jogador rola o d20 e o mestre libera a
    "Caçada Aleatória" pelo painel. Este helper apenas monta o encontro.

    Level scale: Pokemon 1-100. O nível do encontro vem da FAIXA da rota
    (progressão de Kanto: Rota 1 = 3-10, Viridian Forest = 8-18, …), não do
    nível do jogador. O modo de caça empurra a faixa para cima (HUNT_LEVEL_DELTA)
    e o jogador só dá um leve empurrão quando supera o topo da faixa.
    Modos (delta sobre a faixa da rota / raridade / shiny):
    - normal: +0. Comuns. Shiny 1%.
    - dungeon: +5. Raros/evoluídos. Shiny 3%.
    - dungeon_night: +15. Evoluídos fortes. Shiny 4%.
    - night: +10. Extremamente perigoso. Shiny 5%.

    Retorna o dict do encontro, ou None se não houver Pokémon para a rota.
    """
    if hunt_mode not in HUNT_MODES:
        hunt_mode = 'normal'
    player_level = max(1, min(100, int(player_level or 5)))

    route = ROUTES_DATA.get(route_id, {})
    route_types = route.get('types', ['Normal'])
    # Faixa de nível da ROTA já em nível de Pokémon (1-100) — progressão de
    # Kanto (Rota 1 = 3-10, Viridian Forest = 8-18, … Cerulean Cave 50-80).
    raw_range = route.get('level_range', [3, 12])
    band_lo, band_hi = int(raw_range[0]), min(100, int(raw_range[1]))
    # Modo de caçada empurra a faixa para cima (noite sobe mesmo em dungeon).
    _delta = HUNT_LEVEL_DELTA.get(hunt_mode, 0)
    band_lo, band_hi = band_lo + _delta, min(100, band_hi + _delta)
    # Leve influência do jogador: se ele supera o topo da faixa, empurra 1/3
    # do excesso (rota não fica trivial no endgame, mas mantém a banda).
    if player_level > band_hi:
        _nudge = (player_level - band_hi) // 3
        band_lo, band_hi = band_lo + _nudge, min(100, band_hi + _nudge)
    band_lo = max(1, min(band_lo, band_hi))

    # Dungeon/night use dungeon types (stronger/rarer)
    if hunt_mode in ('dungeon', 'night', 'dungeon_night'):
        route_types = route.get('dungeon_types', route_types)

    # Mesa limitada à 1ª GERAÇÃO (até #151)
    GEN1_MAX = 151

    # If route has an explicit pokemon list, use it (route-specific encounters)
    route_pokemon_names = route.get('pokemon', [])
    if route_pokemon_names:
        # Resolve names to data entries (try exact match, then case-insensitive)
        candidates = []
        for pname in route_pokemon_names:
            entry = POKEMON_BY_NAME.get(pname.lower())
            if entry and entry['number'] <= GEN1_MAX:
                candidates.append(entry)
        # Fallback to type pool if nothing matched
        if not candidates:
            route_pokemon_names = []

    if not route_pokemon_names:
        # Type-based pool, filtered to Gen 1-3
        candidates = []
        for ptype in route_types:
            for p in POKEMON_BY_TYPE.get(ptype.lower(), []):
                if p['number'] <= GEN1_MAX:
                    candidates.append(p)

    # Remove duplicates
    seen_nums = set()
    unique_candidates = []
    for c in candidates:
        if c['number'] not in seen_nums:
            seen_nums.add(c['number'])
            unique_candidates.append(c)
    candidates = unique_candidates

    if not candidates:
        # Last resort: all Gen 1-3 Normal-type
        candidates = [p for p in POKEMON_BY_TYPE.get('normal', []) if p['number'] <= GEN1_MAX]
    
    # A faixa da rota (já ajustada por modo/jogador) manda no nível.
    min_lv, max_lv = band_lo, band_hi

    # Filtra espécies que não aparecem tão cedo: minLevel (escala de treinador
    # 1-20) × 5 = nível mínimo de Pokémon da espécie (Charizard 10→50 fica fora
    # da Rota 1). Isso mantém evoluídos fortes longe das rotas iniciais.
    filtered = [p for p in candidates if (p.get('minLevel', 1) * 5) <= max_lv]

    if not filtered:
        filtered = sorted(candidates, key=lambda p: abs((p.get('minLevel', 1) * 5) - max_lv))[:10]
    
    if not filtered:
        return jsonify({'error': 'No pokemon available for this route'}), 404
    
    # Rarity weights - dungeon/night favors evolved/rare
    weights = []
    for p in filtered:
        stage = p.get('evolutionStage', '1/1')
        stage_num = int(stage.split('/')[0]) if '/' in stage else 1
        sr_str = p.get('sr', '1/2')
        if '/' in str(sr_str):
            sr_val = int(str(sr_str).split('/')[0]) / int(str(sr_str).split('/')[1])
        else:
            sr_val = float(sr_str)
        
        if hunt_mode == 'night':
            # Night: heavily favors evolved/high-SR
            weight = max(1, sr_val * 4 + stage_num * 3)
        elif hunt_mode == 'dungeon_night':
            # Dungeon perigosa: quase tão pesada quanto a noite
            weight = max(1, sr_val * 3 + stage_num * 3)
        elif hunt_mode == 'dungeon':
            # Dungeon: favors evolved
            weight = max(1, sr_val * 2 + stage_num * 2)
        else:
            # Normal: common first-stage pokemon more likely
            weight = 10 if stage_num == 1 else (3 if stage_num == 2 else 1)
            if sr_val <= 0.5: weight *= 3
            elif sr_val <= 2: weight *= 2
        
        weights.append(max(1, weight))
    
    chosen = random.choices(filtered, weights=weights, k=1)[0]
    
    # Nível do encontro = faixa da rota (band_lo..band_hi já traz o delta de
    # caça/dungeon/noite e o leve empurrão do jogador calculados acima). A
    # progressão vem da rota (Kanto), não do nível do jogador.
    encounter_level = random.randint(band_lo, band_hi)
    # Piso da espécie: base mons (minLevel 1) não têm piso; evoluídos exigem
    # nível mínimo ((minLevel-1)×5), mas nunca acima do topo da faixa da rota.
    _floor = min(band_hi, max(1, (chosen.get('minLevel', 1) - 1) * 5))
    encounter_level = max(_floor, encounter_level)
    # Emboscada (nat 1 no teste de Sobrevivência): encontro perigoso
    if is_ambush:
        encounter_level += random.randint(5, 10)
    encounter_level = min(100, encounter_level)
    
    # Shiny chance by mode
    shiny_chances = {'normal': 0.01, 'dungeon': 0.03, 'dungeon_night': 0.04, 'night': 0.05}
    is_shiny = random.random() < shiny_chances.get(hunt_mode, 0.01)
    
    # Moveset do SELVAGEN: base = golpes iniciais + por nível (≤ nível do
    # encontro). Regra da mesa: NÃO nascem com golpes de TM, e só têm
    # WILD_EGG_MOVE_CHANCE (~20%) de carregar golpes de OVO no set — o resto é
    # o moveset normal por nível.
    move_pool = list(chosen.get('startingMoves', []))
    if chosen.get('levelMoves'):
        for lv, moves in chosen['levelMoves'].items():
            # levelMoves keys are trainer-level scale, multiply by 5
            if int(lv) * 5 <= encounter_level:
                move_pool.extend(moves)
    # Egg moves: só entram no pool numa fração dos encontros (senão, nunca)
    if chosen.get('eggMoves') and random.random() < WILD_EGG_MOVE_CHANCE:
        move_pool.extend(chosen['eggMoves'])

    move_pool = [m for m in move_pool if len(m) > 2 and not m.startswith('©') and not m.isdigit() and 'unofficial' not in m.lower() and 'wizards' not in m.lower() and 'nintendo' not in m.lower() and 'portions' not in m.lower() and '©' not in m and len(m) < 30]
    move_pool = list(dict.fromkeys(move_pool))

    # Validate moves against database - only keep moves that actually exist
    move_pool = [m for m in move_pool if m.lower() in MOVES_BY_NAME or m in MOVES_DB]

    # Moveset do selvagem: 2 PRINCIPAIS sorteados entre os TOP-4 golpes
    # ofensivos disponíveis (qualidade garantida + variedade por encontro —
    # antes eram SEMPRE os 2 mais fortes, todo encontro igual) + 2
    # SECUNDÁRIOS aleatórios (cobertura, suporte, status).
    def _mv_power(m):
        try:
            return int(canon_move(m).get('power') or 0) or \
                int(bm_core.VARIABLE_POWER.get(m.lower(), 0))
        except (TypeError, ValueError):
            return 0
    offensive = sorted((m for m in move_pool if _mv_power(m) > 0),
                       key=_mv_power, reverse=True)
    top = offensive[:4]
    random.shuffle(top)
    fixed = top[:2]
    # secundários = todo o resto (ofensivos extras + status/suporte), embaralhado
    secondary_pool = [m for m in move_pool if m not in fixed]
    random.shuffle(secondary_pool)
    wild_moves = list(fixed)
    for m in secondary_pool:
        if len(wild_moves) >= 4:
            break
        if m not in wild_moves:
            wild_moves.append(m)
    # garantia mínima: sempre ter ao menos 1 golpe de dano
    if not any(_mv_power(m) > 0 for m in wild_moves):
        wild_moves = (['Tackle'] + wild_moves)[:4]
    if not wild_moves:
        wild_moves = ['Tackle']
    # garantia de RECARGA: ≥1 golpe de dano sem recarga (drenos contam como
    # COM recarga mesmo abaixo de POW 50 — recarga de sustain)
    wild_moves = _ensure_filler_move(wild_moves, move_pool)
    
    # Calculate scaled stats for the wild pokemon.
    # Shiny: +35% nos atributos BASE antes do escalonamento (SHINY_MULT em
    # pokemon_scaling) — HP/CA/iniciativa/dano derivam dos atributos já
    # acrescidos. Substitui o antigo boost pós-cálculo (+20% stats, +2 CA).
    scaled = scaling.calculate_pokemon_stats(chosen, encounter_level, is_shiny=is_shiny)

    # Build pokemon data with scaled stats
    pokemon_data = dict(chosen)
    pokemon_data['hp'] = scaled['hp']
    pokemon_data['maxHp'] = scaled['maxHp']
    pokemon_data['ac'] = scaled['ac']
    pokemon_data['stats'] = scaled['stats']
    pokemon_data['proficiency'] = scaled['proficiency']
    pokemon_data['stab'] = scaled['stab']
    pokemon_data['is_shiny'] = is_shiny
    # postura defensiva escolhida pela IA (melhor stat líquido ÷ taxa)
    pokemon_data['defense_mode'] = _ai_defense_mode(pokemon_data)

    return {
        'pokemon': pokemon_data,
        'level': encounter_level,
        'wild_moves': wild_moves,
        'is_shiny': is_shiny,
        'hunt_mode': hunt_mode,
        'route_id': route_id,
        'found': True,
        'ambush': is_ambush,
    }


@app.route('/api/hunt/roll', methods=['POST'])
@login_required
def api_hunt_roll():
    """Teste de caçada MANUAL: o jogador rola o d20 (virtual ou físico).

    Consome 1 das caçadas do dia (6 + bônus de Energy Drink) e envia o
    resultado ao mestre, que decide liberar a caçada pela 'Caçada Aleatória'.
    NÃO gera encontro — só a rolagem."""
    if _rate_limit(15, 60):
        return jsonify({'error': 'Muitas rolagens em pouco tempo. Aguarde um momento.'}), 429
    data = request.json or {}
    pid = str(current_user.id)
    state = get_game_state()
    entry, dkey = _hunt_entry(state, pid)
    limit = MAX_HUNTS_PER_DAY + int(entry.get('bonus', 0))
    if entry['used'] >= limit:
        return jsonify({
            'error': 'Você está muito cansado(a) para continuar caçando! '
                     'Descanse até o mestre avançar o dia (ou tome um Energy Drink).',
            'used': entry['used'], 'limit': limit
        }), 403

    trainer = get_users().get(pid, {}).get('trainer_data', {})
    trainer_attrs.migrate_trainer(trainer)
    # Caçada = 🧭 Exploração (Agilidade): rastrear/encontrar Pokémon
    skill_mod, proficient = trainer_attrs.skill_modifier(trainer, 'Exploração')

    # Rolagem física (o jogador digita o valor do d20 real) ou virtual
    manual = data.get('manual_roll')
    is_manual = False
    if manual is not None:
        try:
            roll = max(1, min(20, int(manual)))
            is_manual = True
        except (TypeError, ValueError):
            roll = random.randint(1, 20)
    else:
        roll = random.randint(1, 20)
    total = roll + skill_mod

    # Consome a tentativa e salva
    entry['used'] += 1
    hunts = state.get('hunts') or {}
    hunts[pid] = entry
    state['hunts'] = hunts
    save_game_state(state)

    roll_info = {
        'player_id': pid, 'player_name': current_user.username,
        'roll': roll, 'skill': 'Exploração', 'skill_mod': skill_mod,
        'proficient': proficient, 'total': total,
        'manual': is_manual, 'used': entry['used'], 'limit': limit,
        'day_key': dkey,
    }
    # Avisa o mestre (caixa de rolagens) e atualiza o contador do jogador
    socketio.emit('hunt_roll', roll_info, room=f'master_{_tid()}')
    socketio.emit('hunts_update', {'used': entry['used'], 'limit': limit}, room=pid)
    return jsonify({'ok': True, **roll_info})


@app.route('/api/skill/roll', methods=['POST'])
@login_required
def api_skill_roll():
    """Teste de PERÍCIA do treinador: d20 (virtual ou físico) + mod do
    atributo (Sorte usa METADE do mod de Determinação) + proficiência se
    tiver. Resultado vai para a caixa de rolagens do mestre."""
    if _rate_limit(20, 60):
        return jsonify({'error': 'Muitas rolagens em pouco tempo. Aguarde um momento.'}), 429
    data = request.json or {}
    skill = data.get('skill', '')
    if skill not in trainer_attrs.SKILLS:
        return jsonify({'error': f'Perícia desconhecida: {skill}'}), 400

    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    if trainer_attrs.migrate_trainer(trainer):
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)

    bonus, proficient = trainer_attrs.skill_modifier(trainer, skill)
    manual = data.get('manual_roll')
    is_manual = False
    if manual is not None:
        try:
            roll = max(1, min(20, int(manual)))
            is_manual = True
        except (TypeError, ValueError):
            roll = random.randint(1, 20)
    else:
        roll = random.randint(1, 20)
    total = roll + bonus

    attr_key, emoji, _desc = trainer_attrs.SKILLS[skill]
    attr_emoji, attr_name = trainer_attrs.ATTRIBUTES[attr_key]
    roll_info = {
        'player_id': str(current_user.id), 'player_name': current_user.username,
        'skill': skill, 'skill_emoji': emoji,
        'attribute': attr_name, 'attribute_emoji': attr_emoji,
        'roll': roll, 'bonus': bonus, 'proficient': proficient,
        'total': total, 'manual': is_manual,
        'nat1': roll == 1, 'nat20': roll == 20,
        'half_mod': skill == 'Sorte',
    }
    socketio.emit('skill_roll', roll_info, room=f'master_{_tid()}')
    return jsonify({'ok': True, **roll_info})


@app.route('/api/roll', methods=['POST'])
@login_required
def api_free_roll():
    """Rolagem MANUAL de mesa (fora do sistema automatizado): dado puro
    (d4-d100), atributo ou perícia — com uma nota ('pra quê'), virtual ou dado
    físico. Vai para a Caixa de Rolagens do mestre. Se vier uma CD, marca
    sucesso/falha."""
    if _rate_limit(30, 60):
        return jsonify({'error': 'Muitas rolagens em pouco tempo. Aguarde.'}), 429
    data = request.json or {}
    kind = (data.get('kind') or 'die').strip()
    note = str(data.get('note') or '')[:120]

    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    if trainer_attrs.migrate_trainer(trainer):
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)

    manual = data.get('manual_roll')

    def _do_roll(sides):
        if manual is not None:
            try:
                return max(1, min(int(sides), int(manual))), True
            except (TypeError, ValueError):
                pass
        return random.randint(1, int(sides)), False

    emoji, label, bonus, proficient, sides = '🎲', '', 0, False, 20
    if kind == 'die':
        try:
            sides = max(2, min(100, int(data.get('die', 20))))
        except (TypeError, ValueError):
            sides = 20
        roll, is_manual = _do_roll(sides)
        total = roll
        label = f'd{sides}'
    elif kind == 'attr':
        attr = (data.get('attr') or '').strip()
        if attr not in trainer_attrs.ATTRIBUTES:
            return jsonify({'error': 'Atributo inválido'}), 400
        emoji, label = trainer_attrs.ATTRIBUTES[attr]
        bonus = trainer_attrs.attr_mod(trainer, attr)
        roll, is_manual = _do_roll(20)
        total = roll + bonus
    elif kind == 'skill':
        skill = (data.get('skill') or '').strip()
        if skill not in trainer_attrs.SKILLS:
            return jsonify({'error': 'Perícia inválida'}), 400
        bonus, proficient = trainer_attrs.skill_modifier(trainer, skill)
        emoji, label = trainer_attrs.SKILLS[skill][1], skill
        roll, is_manual = _do_roll(20)
        total = roll + bonus
    else:
        return jsonify({'error': 'Tipo de rolagem inválido'}), 400

    cd, success = data.get('cd'), None
    try:
        if cd not in (None, ''):
            cd = int(cd)
            success = total >= cd
        else:
            cd = None
    except (TypeError, ValueError):
        cd = None

    roll_info = {
        'player_id': str(current_user.id), 'player_name': current_user.username,
        'kind': kind, 'label': label, 'emoji': emoji,
        'roll': roll, 'sides': sides, 'bonus': bonus, 'proficient': proficient,
        'total': total, 'manual': is_manual, 'note': note,
        'cd': cd, 'success': success,
        'nat1': sides == 20 and roll == 1, 'nat20': sides == 20 and roll == 20,
    }
    socketio.emit('free_roll', roll_info, room=f'master_{_tid()}')
    return jsonify({'ok': True, **roll_info})


@app.route('/master/request-roll', methods=['POST'])
@login_required
def master_request_roll():
    """Mestre pede um teste a um jogador (atributo/perícia/dado) com um motivo e
    CD opcional. O jogador recebe um aviso com botão de rolar (usa a própria
    ficha)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = data.get('player_id')
    kind = (data.get('kind') or 'attr').strip()
    target = (data.get('target') or '').strip()
    note = str(data.get('note') or '')[:120]

    users = get_users()
    if not _player_in_master_table(player_id, users, _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    if kind == 'attr' and target not in trainer_attrs.ATTRIBUTES:
        return jsonify({'error': 'Atributo inválido'}), 400
    if kind == 'skill' and target not in trainer_attrs.SKILLS:
        return jsonify({'error': 'Perícia inválida'}), 400
    if kind == 'die':
        try:
            target = str(max(2, min(100, int(target or 20))))
        except (TypeError, ValueError):
            target = '20'
    cd = data.get('cd')
    try:
        cd = int(cd) if cd not in (None, '') else None
    except (TypeError, ValueError):
        cd = None

    socketio.emit('roll_request', {
        'kind': kind, 'target': target, 'note': note, 'cd': cd,
        'master': current_user.username,
    }, room=str(player_id))
    return jsonify({'ok': True})


@app.route('/api/skill/list')
@login_required
def api_skill_list():
    """Definição das perícias + bônus calculados do treinador logado."""
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    trainer_attrs.migrate_trainer(trainer)
    out = []
    for skill, (attr_key, emoji, desc) in trainer_attrs.SKILLS.items():
        bonus, proficient = trainer_attrs.skill_modifier(trainer, skill)
        out.append({
            'skill': skill, 'emoji': emoji, 'description': desc,
            'attribute': attr_key,
            'attribute_label': ' '.join(trainer_attrs.ATTRIBUTES[attr_key]),
            'bonus': bonus, 'proficient': proficient,
            'half_mod': skill == 'Sorte',
        })
    return jsonify({
        'skills': out,
        'prof_bonus': trainer_attrs.proficiency_bonus(trainer.get('level', 1)),
        'max_profs': trainer_attrs.max_proficiencies(trainer.get('level', 1)),
        'used_profs': len(trainer.get('skill_profs') or []),
    })


def _grant_encounter(player_id, number):
    """Registra que o MESTRE liberou um encontro para o jogador (por espécie).
    O start_encounter só é aceito se casar com este 'vale' — impede o jogador
    de iniciar batalhas selvagens à vontade (fora do teto/gate de caçadas)."""
    try:
        num = int(number)
    except (TypeError, ValueError):
        return
    gs = get_game_state()
    pend = gs.setdefault('pending_encounters', {})
    pend[str(player_id)] = num
    save_game_state(gs)


@app.route('/master/hunt/random', methods=['POST'])
@login_required
def master_hunt_random():
    """Mestre libera uma CAÇADA ALEATÓRIA para um jogador selecionado.

    Respeita o horário (dia/noite) e o terreno (dungeon / dungeon perigosa)
    via hunt_mode. Gera um encontro e envia ao jogador pelo fluxo
    forced_encounter (mesmo socket do encontro manual)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_id = str(data.get('player_id', ''))
    if not player_id:
        return jsonify({'error': 'player_id obrigatório'}), 400
    if not _player_in_master_table(player_id, get_users(), _tid()):
        return jsonify({'error': 'Jogador não pertence a esta mesa'}), 403
    hunt_mode = data.get('hunt_mode', 'normal')
    if hunt_mode not in HUNT_MODES:
        hunt_mode = 'normal'
    route_id = data.get('route_id') or next(iter(ROUTES_DATA.keys()), None)
    is_ambush = bool(data.get('is_ambush'))

    # Nível do encontro baseado no time real do jogador-alvo
    trainer = get_users().get(player_id, {}).get('trainer_data', {})
    team_levels = [int(p.get('level', 1) or 1) for p in trainer.get('team', [])]
    player_level = max(team_levels) if team_levels else int(data.get('player_level', 5))

    enc = _build_random_encounter(route_id, hunt_mode, player_level, is_ambush)
    if not enc:
        return jsonify({'error': 'Nenhum Pokémon disponível para esta rota'}), 404

    # Envia ao jogador pelo mesmo canal do encontro manual
    payload = {
        'type': 'forced_encounter', 'player_id': player_id,
        'pokemon': enc['pokemon'], 'level': enc['level'],
        'is_shiny': enc['is_shiny'], 'is_mega': False,
        'wild_moves': enc['wild_moves'], 'route_id': enc['route_id'],
        'ambush': enc.get('ambush', False), 'hunt_mode': enc['hunt_mode'],
        'random_hunt': True,
    }
    _grant_encounter(player_id, (enc.get('pokemon') or {}).get('number'))
    socketio.emit('master_action', payload, room=player_id)
    return jsonify({'ok': True, 'encounter': enc})


# ============================================================
# BATALHA EM DUPLA (caçada em grupo) — 2v1 / 2v2
# ============================================================
ACTIVE_GROUP_BATTLES = {}  # battle_id -> battle (em memória, como o PvP)


def _group_active_pokemon(player_id):
    """Pokémon ativo (primeiro vivo) do jogador para a batalha em grupo."""
    trainer = get_users().get(str(player_id), {}).get('trainer_data', {})
    team = trainer.get('team', [])
    _enrich_team(team)
    for p in team:
        if p and gb._poke_hp(p) > 0:
            return trainer.get('name') or trainer.get('trainer_name', ''), p
    return (trainer.get('name', ''), team[0]) if team else ('', None)


def _spectate(kind, payload, table_id=None):
    """Modo ESPECTADOR: transmite um snapshot compacto da batalha para todos
    os jogadores da mesa (sala players_{tid}). O cliente filtra as batalhas
    em que o próprio jogador participa (ele já tem a UI completa)."""
    tid = table_id or _tid()
    socketio.emit('spectate_update', dict(payload, kind=kind), room=f'players_{tid}')


def _spectate_wild(player_id, encounter, last='', finished=False):
    """Snapshot de batalha SELVAGEM para os espectadores da mesa."""
    bs = (encounter or {}).get('battle_state') or {}
    pp = (encounter or {}).get('player_pokemon') or {}
    wp = (encounter or {}).get('pokemon') or {}
    _spectate('wild', {
        'id': f'wild_{player_id}',
        'players': [str(player_id)],
        'trainer': (encounter or {}).get('player_name', 'Treinador'),
        'ally': {'name': pp.get('nickname') or pp.get('name', '?'),
                 'level': pp.get('level', '?'),
                 'hp': max(0, int(bs.get('player_hp_current') or 0)),
                 'max_hp': int(bs.get('player_hp_max') or 0)},
        'wild': {'name': wp.get('name', '?'), 'level': (encounter or {}).get('level', '?'),
                 'hp': max(0, int(bs.get('wild_hp_current') or 0)),
                 'max_hp': int(bs.get('wild_hp_max') or 0),
                 'is_shiny': bool((encounter or {}).get('is_shiny'))},
        'round': bs.get('round', 0),
        'last': last,
        'finished': finished,
    })


def _group_broadcast(battle, event='group_battle_update'):
    view = gb.state_view(battle)
    # o cliente precisa saber se os selvagens jogam sozinhos (AUTO) ou se é
    # o Mestre quem joga por eles — sem isso o jogador só vê "aguarde"
    st = _db_raw.get_game_state(battle['table_id'])
    view['wild_auto'] = bool(st.get('wild_auto_mode', True))
    for pid in battle['player_ids']:
        socketio.emit(event, view, room=pid)
    socketio.emit(event, view, room=f"master_{battle['table_id']}")
    _spectate('group', {'id': battle['id'], 'players': [str(p) for p in battle['player_ids']],
                        'view': view, 'finished': battle['phase'] == 'finished'},
              table_id=battle['table_id'])


def _group_apply_status_move(battle, actor_cid, target_cid, move_name, move_data):
    """Move de STATUS na batalha em dupla — sem dano; aplica efeito e avança."""
    actor = battle['combatants'][actor_cid]
    target = battle['combatants'][target_cid]
    result = effects.process_status_move(
        move_data or {'name': move_name},
        dict(actor['pokemon'].get('stats', {}), level=actor['pokemon'].get('level', 1),
             proficiency=actor['pokemon'].get('proficiency',
                                              _prof_for_level(actor['pokemon'].get('level', 1))),
             maxHp=actor['maxHp'], currentHp=max(0, actor['hp']),
             types=actor['pokemon'].get('types'),
             ability=actor['pokemon'].get('ability'),   # Rest × Insomnia
             _v3=_v3_side_state(actor['pokemon'])),   # Protect: corrente/flag no dict real
        dict(target['pokemon'].get('stats', {}), level=target['pokemon'].get('level', 1),
             currentHp=max(0, target['hp']),
             ATK_eff=effects.effective_stat(target['pokemon'], 'ATK')))
    # custo pago pelo próprio usuário (Curse fantasma: ⌊HPmáx/2⌋, nunca desmaia)
    if result.get('self_damage') and result.get('effect_type') != 'fixed_damage':
        actor['hp'] = max(1, actor['hp'] - int(result['self_damage']))
    # v3: cura instantânea em recarga — não consome o turno do JOGADOR (ele
    # escolhe outro golpe). Selvagem bloqueado AVANÇA o turno: a IA re-escolhe
    # no próximo round; sem isso o loop de turnos automáticos travava a
    # batalha com o selvagem preso como combatente atual. Aliado SEM NENHUM
    # golpe disponível ganha a rodada de fôlego (turno passa, recargas −1).
    if result.get('blocked'):
        battle['log'].append({'type': 'info',
                              'message': f"⏳ {actor['name']}: {result.get('message', move_name + ' em recarga')}"})
        if actor.get('side') == 'wild':
            gb.advance_turn(battle)
        elif _v3_sem_opcao(actor['pokemon'], actor['moves']):
            battle['log'].append({'type': 'info',
                                  'message': _v3_folego(actor['pokemon'], actor['name'])})
            gb.advance_turn(battle)
        return
    # F5: clima/terreno de campo (Rain Dance, Grassy Terrain...)
    if result.get('effect_type') == 'field':
        _field_apply(battle, result.get('field_kind'), result.get('field_value'),
                     result.get('duration'))
        battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                              'message': f"{actor['name']} usou {move_name} — {result.get('message','')}"})
        gb.advance_turn(battle)
        return
    # Dano fixo (Night Shade/Pain Split/OHKO...): ignora CA — heal cura o
    # atacante, self_damage o fere; dano via gb.apply_damage (log + turno)
    if result.get('effect_type') == 'fixed_damage' and (result.get('damage') or result.get('self_damage')):
        if result.get('heal'):
            actor['hp'] = min(actor['maxHp'], actor['hp'] + result['heal'])
            actor['pokemon']['currentHp'] = actor['hp']
        if result.get('self_damage'):
            actor['hp'] = max(0, actor['hp'] - result['self_damage'])
            actor['pokemon']['currentHp'] = actor['hp']
        if result.get('damage'):
            gb.apply_damage(battle, actor_cid, target_cid, result['damage'],
                            move_name, result.get('message', ''))
        else:
            battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                                  'message': f"{actor['name']} usou {move_name} — {result.get('message','')}"})
            gb.advance_turn(battle)
        return
    # Haze: anula os buffs/debuffs de TODOS os combatentes
    if result.get('effect_type') == 'reset_stages':
        for c in battle['combatants'].values():
            effects.reset_stat_stages(c.get('pokemon') or {})
        battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                              'message': f"{actor['name']} usou {move_name} — {result.get('message','')}"})
        gb.advance_turn(battle)
        return
    # Operações sobre stages (copy/swap/invert)
    if result.get('effect_type') == 'stage_op':
        op = result.get('op')
        a_st = dict(effects.init_stat_stages(), **(actor['pokemon'].get('stat_stages') or {}))
        t_st = dict(effects.init_stat_stages(), **(target['pokemon'].get('stat_stages') or {}))
        if op == 'copy':
            actor['pokemon']['stat_stages'] = dict(t_st)
        elif op == 'swap':
            actor['pokemon']['stat_stages'], target['pokemon']['stat_stages'] = t_st, a_st
        elif op == 'invert':
            target['pokemon']['stat_stages'] = {k: -v for k, v in t_st.items()}
        battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                              'message': f"{actor['name']} usou {move_name} — {result.get('message','')}"})
        gb.advance_turn(battle)
        return
    # Teleport falha em batalha em grupo com treinadores (canon)
    if result.get('effect_type') == 'flee':
        battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                              'message': f"{actor['name']} usou {move_name} — ...mas não funcionou!"})
        gb.advance_turn(battle)
        return
    if result.get('status_applied') and not effects.type_blocks_status(
            (target.get('pokemon') or {}).get('types'), result['status_applied']):
        target['status'] = {'condition': result['status_applied'], 'turns_active': 0}
    if result.get('heal'):
        actor['hp'] = min(actor['maxHp'], actor['hp'] + result['heal'])
        actor['pokemon']['currentHp'] = actor['hp']
    # Rest: o PRÓPRIO usuário adormece (troca o status atual — cura e dorme)
    if result.get('self_status'):
        actor['status'] = {'condition': result['self_status'], 'turns_active': 0}
    # Stat stages no dict pokemon do combatente (o cálculo copia esse dict)
    if result.get('stat_changes'):
        tgt = target if result.get('effect_type') == 'debuff' else actor
        effects.apply_stat_changes(tgt['pokemon'], result['stat_changes'])
    battle['log'].append({'type': 'status_move', 'actor': actor_cid,
                          'message': f"{actor['name']} usou {move_name} — {result.get('message','')}"})
    gb.advance_turn(battle)


def _group_apply_recoil_drain(battle, combatant, calc):
    """F5: aplica recoil/dreno do golpe no HP do combatente. Recoil deixa em
    1 HP no mínimo (não nocauteia o usuário). Retorna sufixo p/ a mensagem."""
    suffix = ''
    recoil = int(calc.get('recoil') or 0)
    heal = int(calc.get('drain_heal') or 0)
    if recoil:
        combatant['hp'] = max(1, combatant['hp'] - recoil)
        combatant['pokemon']['currentHp'] = combatant['hp']
        suffix += f' 💢 Recoil: {recoil} de dano em si!'
    if heal and combatant['hp'] > 0:
        combatant['hp'] = min(combatant['maxHp'], combatant['hp'] + heal)
        combatant['pokemon']['currentHp'] = combatant['hp']
        suffix += f' 💚 Drenou {heal} HP!'
    # Rampage: usuário fica confuso; Explosion: usuário desmaia
    if calc.get('self_status'):
        pk = combatant.get('pokemon') or {}
        if not pk.get('status') and not effects.type_blocks_status(
                pk.get('types'), calc['self_status']):
            pk['status'] = {'condition': calc['self_status'], 'turns_active': 0}
            suffix += ' 💫 ficou confuso pela fúria!'
    if calc.get('self_ko'):
        combatant['hp'] = 0
        combatant['pokemon']['currentHp'] = 0
        combatant['fainted'] = True
        suffix += ' 💥 desmaiou com o próprio golpe!'
    return suffix


def _group_field_round_hook(battle):
    """F5: uma vez por rodada — chip de clima (areia/granizo), cura de Grassy
    Terrain, tick do 🌱 Leech Seed e decremento das durações do campo."""
    rnd = int(battle.get('round') or 0)
    if rnd <= int(battle.get('_field_round_done') or 0):
        return
    battle['_field_round_done'] = rnd
    # 🌱 Leech Seed: portador perde seed_drain (⌊HPmáx/16⌋); um oponente vivo cura o mesmo
    for c in battle['combatants'].values():
        if c.get('fainted') or c['hp'] <= 0:
            continue
        if ((c.get('pokemon') or {}).get('status') or {}).get('condition') != 'seeded':
            continue
        seed_dmg = effects.seed_drain(c.get('maxHp'))
        c['hp'] = max(1, c['hp'] - seed_dmg)
        c['pokemon']['currentHp'] = c['hp']
        other_side = 'wild' if c['side'] == 'ally' else 'ally'
        for o in battle['combatants'].values():
            if o['side'] == other_side and not o.get('fainted') and o['hp'] > 0:
                o['hp'] = min(o['maxHp'], o['hp'] + seed_dmg)
                o['pokemon']['currentHp'] = o['hp']
                battle['log'].append({'type': 'field', 'message':
                    f"🌱 {c['name']} perde {seed_dmg} HP pra semente — "
                    f"{o['name']} recupera {seed_dmg}!"})
                break
    fld = _field_of(battle)
    if not (fld.get('weather') or fld.get('terrain')):
        return
    for c in battle['combatants'].values():
        if c.get('fainted') or c['hp'] <= 0:
            continue
        delta, msg = _field_chip(battle, c.get('pokemon'), c['maxHp'], c['name'])
        if delta:
            # chip nunca nocauteia (deixa em 1 HP) — o golpe é que decide
            c['hp'] = max(1, min(c['maxHp'], c['hp'] + delta))
            c['pokemon']['currentHp'] = c['hp']
        if msg:
            battle['log'].append({'type': 'field', 'message': msg})
    for m in _field_tick(battle):
        battle['log'].append({'type': 'field', 'message': m})


def _group_run_wild_turns(battle):
    """Executa as jogadas automáticas dos selvagens enquanto for a vez deles."""
    guard = 0
    while (battle['phase'] == 'active' and guard < 12):
        cur = gb.current_combatant(battle)
        if not cur or cur['side'] != 'wild':
            break
        guard += 1
        target_cid = gb.choose_wild_target(battle, cur['cid'])
        if not target_cid:
            break
        target = battle['combatants'][target_cid]
        wild_poke = dict(cur['pokemon'])
        wild_poke['currentHp'] = cur['hp']
        wild_poke['maxHp'] = cur['maxHp']
        wild_poke['moves'] = cur['moves']
        wild_poke['level'] = cur.get('level') or wild_poke.get('level', 1)
        _v3_side_state(cur['pokemon'])
        wild_poke['_v3'] = cur['pokemon']['_v3']   # estado v3 persiste entre turnos
        tgt_poke = dict(target['pokemon'])
        tgt_poke['currentHp'] = target['hp']
        move_name, move_data, is_status = _npc_pick_move(wild_poke, tgt_poke)
        if is_status and move_name.lower() not in VARIABLE_DAMAGE_MOVES:
            _group_apply_status_move(battle, cur['cid'], target_cid, move_name, move_data)
            continue
        calc = _calc_pvp_attack(wild_poke, tgt_poke, move_name,
                                field=_field_of(battle))
        msg = f"{cur['name']} usou {move_name} em {target['name']} — {calc.get('message','')}"
        msg += _group_apply_recoil_drain(battle, cur, calc)
        gb.apply_damage(battle, cur['cid'], target_cid, calc.get('damage', 0),
                        move_name, msg, hit=calc.get('hit', True))


@app.route('/master/group-hunt', methods=['POST'])
@login_required
def master_group_hunt():
    """Mestre inicia uma BATALHA EM DUPLA (caçada em grupo).

    body: {player_ids:[2], hunt_mode, route_id, wild_count:1|2}
    2v1 (wild_count=1) gera 1 selvagem mais forte; 2v2 gera 2 selvagens.
    """
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json or {}
    player_ids = [str(p) for p in (data.get('player_ids') or []) if p]
    player_ids = list(dict.fromkeys(player_ids))  # únicos, mantém ordem
    if len(player_ids) < 2:
        return jsonify({'error': 'Selecione 2 jogadores para a batalha em dupla'}), 400
    player_ids = player_ids[:2]
    hunt_mode = data.get('hunt_mode', 'normal')
    if hunt_mode not in HUNT_MODES:
        hunt_mode = 'normal'
    route_id = data.get('route_id') or next(iter(ROUTES_DATA.keys()), None)
    wild_count = 2 if int(data.get('wild_count', 1)) == 2 else 1

    # Aliados: Pokémon ativo de cada jogador
    allies = []
    for pid in player_ids:
        name, poke = _group_active_pokemon(pid)
        if not poke:
            return jsonify({'error': f'Jogador {pid} não tem Pokémon disponível'}), 400
        _mig([poke])
        _stamp_tatica([poke], get_users().get(pid, {}).get('trainer_data'))
        allies.append({'player_id': pid, 'name': name or 'Treinador', 'pokemon': poke})

    # Nível-base do encontro = maior nível entre os ativos dos dois jogadores
    base_level = max(int(a['pokemon'].get('level', 1) or 1) for a in allies)

    wilds = []
    for i in range(wild_count):
        enc = _build_random_encounter(route_id, hunt_mode, base_level)
        if not enc:
            return jsonify({'error': 'Nenhum Pokémon disponível para esta rota'}), 404
        poke = dict(enc['pokemon'])
        level = enc['level']
        if wild_count == 1:
            # 2v1: selvagem mais forte para equilibrar contra a dupla.
            # is_shiny=False: os stats do dict JÁ vêm com o bônus shiny do
            # _build_random_encounter — sem a trava, o ×1.35 aplicaria 2 vezes.
            level = min(100, level + random.randint(3, 8))
            scaled = scaling.calculate_pokemon_stats(poke, level, is_shiny=False)
            poke.update({'hp': int(scaled['hp'] * 1.3), 'maxHp': int(scaled['maxHp'] * 1.3),
                         'ac': scaled['ac'], 'stats': scaled['stats'],
                         'proficiency': scaled['proficiency'], 'stab': scaled['stab']})
        poke['level'] = level
        poke.setdefault('defense_mode', _ai_defense_mode(poke))
        wilds.append({'pokemon': poke, 'level': level, 'moves': enc['wild_moves']})

    battle = gb.build_battle(allies, wilds, hunt_mode, route_id, _tid())
    ACTIVE_GROUP_BATTLES[battle['id']] = battle

    # Se começar com selvagem e AUTO ligado, roda as jogadas dos selvagens
    if _wild_auto_mode():
        _group_run_wild_turns(battle)

    _group_broadcast(battle, 'group_battle_start')
    return jsonify({'ok': True, 'battle': gb.state_view(battle)})


@socketio.on('group_battle_action')
def handle_group_battle_action(data):
    """Um jogador ataca no seu turno da batalha em dupla."""
    if not current_user.is_authenticated:
        return
    battle = ACTIVE_GROUP_BATTLES.get(data.get('battle_id'))
    if not battle or battle['phase'] != 'active':
        return
    cur = gb.current_combatant(battle)
    if not cur or cur['side'] != 'ally':
        return
    # Só o dono do combatente atual pode agir (mestre pode agir por qualquer aliado)
    if current_user.role != 'master' and str(current_user.id) != cur['player_id']:
        return
    # Pokémon desmaiado NÃO age (guarda extra do ator; a ordem já pula caídos)
    if cur.get('fainted') or int(cur.get('hp') or 0) <= 0:
        emit('group_battle_error', {'message': '💀 Este Pokémon desmaiou — não pode agir.'})
        return

    target_cid = data.get('target_cid')
    target = battle['combatants'].get(target_cid)
    if not target or target['side'] != 'wild' or target['fainted']:
        # alvo inválido → mira o primeiro selvagem vivo
        alive = gb.alive_cids(battle, 'wild')
        if not alive:
            return
        target_cid = alive[0]
        target = battle['combatants'][target_cid]

    move_name = data.get('move_name') or (cur['moves'][0] if cur['moves'] else 'Tackle')
    move_data = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name)
    if _is_status_move(move_data) and move_name.lower() not in VARIABLE_DAMAGE_MOVES:
        # Move de status: sem dano, aplica efeito no alvo/atacante
        _group_apply_status_move(battle, cur['cid'], target_cid, move_name, move_data)
    else:
        _v3_side_state(cur['pokemon'])   # garante o estado ANTES da cópia rasa
        att_poke = dict(cur['pokemon'])   # cópia compartilha o dict _v3 (persistência)
        att_poke['currentHp'] = cur['hp']; att_poke['maxHp'] = cur['maxHp']
        att_poke['moves'] = cur['moves']
        tgt_poke = dict(target['pokemon']); tgt_poke['currentHp'] = target['hp']
        calc = _calc_pvp_attack(att_poke, tgt_poke, move_name, None,
                                field=_field_of(battle))   # v3: servidor rola o d100
        if calc.get('blocked'):
            if _v3_sem_opcao(cur['pokemon'], cur['moves']):
                # RODADA DE FÔLEGO: nada disponível — descansa, turno passa
                battle['log'].append({'type': 'info',
                                      'message': _v3_folego(cur['pokemon'], cur['name'])})
                gb.advance_turn(battle)
                # segue para o pós-fluxo comum (selvagens + broadcast)
            else:
                emit('group_battle_error', {'message': calc.get('message')})
                return
        else:
            msg = f"{cur['name']} usou {move_name} em {target['name']} — {calc.get('message','')}"
            msg += _group_apply_recoil_drain(battle, cur, calc)
            gb.apply_damage(battle, cur['cid'], target_cid, calc.get('damage', 0),
                            move_name, msg, hit=calc.get('hit', True))

    # Turnos automáticos dos selvagens (se AUTO ligado)
    if _wild_auto_mode():
        _group_run_wild_turns(battle)

    _group_field_round_hook(battle)   # F5: chip/cura + duração do campo
    if battle['phase'] == 'finished':
        _group_broadcast(battle, 'group_battle_end')
        ACTIVE_GROUP_BATTLES.pop(battle['id'], None)
    else:
        _group_broadcast(battle)


@socketio.on('group_wild_turn')
def handle_group_wild_turn(data):
    """Mestre avança manualmente as jogadas dos selvagens (AUTO desligado)."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    battle = ACTIVE_GROUP_BATTLES.get(data.get('battle_id'))
    if not battle or battle['phase'] != 'active':
        return
    cur = gb.current_combatant(battle)
    if not cur or cur['side'] != 'wild':
        return
    _group_run_wild_turns(battle)
    _group_field_round_hook(battle)   # F5: chip/cura + duração do campo
    if battle['phase'] == 'finished':
        _group_broadcast(battle, 'group_battle_end')
        ACTIVE_GROUP_BATTLES.pop(battle['id'], None)
    else:
        _group_broadcast(battle)


# ============================================================
# PLAYER ROUTES
# ============================================================
@app.route('/player')
@login_required
def player_dashboard():
    if current_user.role == 'master':
        return redirect(url_for('master_dashboard'))
    users = get_users()
    trainer_data = users.get(current_user.id, {}).get('trainer_data', {})
    _enrich_team(trainer_data.get('team', []))
    # migra os atributos do treinador (D&D → 6 novos) na primeira carga
    if trainer_attrs.migrate_trainer(trainer_data):
        users[current_user.id]['trainer_data'] = trainer_data
        save_users(users)
    game_state = get_game_state()
    # Filter quests for this player
    my_quests = [q for q in game_state.get('quests', [])
                 if current_user.id in q.get('assigned_to', []) or not q.get('assigned_to')]
    return render_template('player.html',
                         trainer=trainer_data,
                         quests=my_quests,
                         routes=ROUTES_DATA,
                         current_user_id=current_user.id)

@app.route('/player/pc', methods=['GET'])
@login_required
def get_pc():
    """Get player's PC box."""
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    if _mig(trainer.get('pc', [])):
        save_users(users)
    return jsonify(trainer.get('pc', []))


@app.route('/player/pc/capture', methods=['POST'])
@login_required
def pc_store_capture():
    """Captura com o TIME CHEIO: o Pokémon vai direto para o PC em vez de
    sumir no limbo. Mesma sanitização de captura nova do update_team:
    espécie precisa existir, nível clampado, stats SEMPRE recalculados no
    servidor (o cliente não é autoridade sobre nada além de nível/moves)."""
    if _rate_limit(10, 60, bucket='pc_capture'):
        return jsonify({'error': 'Muitas capturas em pouco tempo.'}), 429
    data = request.json or {}
    p = data.get('pokemon') or {}

    # SEGURANÇA: só se pode capturar o SELVAGEM do encontro ATIVO do jogador —
    # espécie, nível e shiny vêm do encounter (servidor), não do payload.
    # Sem isto, dava para mandar Mewtwo Nv100 direto pro PC via devtools.
    gs_cap = get_game_state()
    enc_cap = (gs_cap.get('active_encounters') or {}).get(str(current_user.id))
    if not enc_cap:
        return jsonify({'error': 'Nenhum encontro ativo para capturar.'}), 400
    wild_cap = enc_cap.get('pokemon') or {}
    base = POKEMON_BY_NUMBER.get(wild_cap.get('number')) \
        or POKEMON_BY_NAME.get((wild_cap.get('name') or '').lower())
    if not base or not base.get('base_stats'):
        return jsonify({'error': 'Espécie do encontro inválida'}), 400
    # o selvagem precisa estar enfraquecido/desmaiado (não se captura em HP cheio)
    _bs_cap = enc_cap.get('battle_state') or {}
    _wc, _wm = int(_bs_cap.get('wild_hp_current') or 1), int(_bs_cap.get('wild_hp_max') or 1)
    if _wc > 0 and _wc > _wm // 2:
        return jsonify({'error': 'O Pokémon precisa estar enfraquecido para ser capturado.'}), 400

    level = max(1, min(100, int(enc_cap.get('level') or wild_cap.get('level') or 1)))
    p = dict(p, is_shiny=bool(enc_cap.get('is_shiny')))   # shiny é do encontro
    moves = [m for m in (p.get('moves') or [])
             if isinstance(m, str) and (m.lower() in MOVES_BY_NAME or m in MOVES_DB)][:4]
    is_shiny = bool(p.get('is_shiny'))
    scaled = scaling.calculate_pokemon_stats(base, level, is_shiny=is_shiny)
    poke = {
        'name': base['name'], 'number': base['number'],
        'nickname': str(p.get('nickname') or '')[:30],
        'types': base.get('types', []), 'level': level,
        'moves': moves or list(base.get('startingMoves', []))[:4] or ['Tackle'],
        'ability': (base.get('ability') or {}).get('name', '') if base.get('ability') else '',
        'speed': base.get('speed', '30ft'),
        'vulnerabilities': base.get('vulnerabilities', []),
        'resistances': base.get('resistances', []),
        'immunities': base.get('immunities', []),
        'evolutionInfo': base.get('evolutionInfo', ''),
        'is_shiny': is_shiny,
        'stats': scaled['stats'], 'maxHp': scaled['maxHp'], 'hp': scaled['maxHp'],
        'xp': 0, 'totalXp': 0, 'battle_wins': 0,
        'sv': migrations.STATS_VERSION, 'training': {},
    }
    try:
        cur = int(p.get('currentHp') or scaled['maxHp'])
    except (TypeError, ValueError):
        cur = scaled['maxHp']
    poke['currentHp'] = max(1, min(scaled['maxHp'], cur))
    migrations.migrate_pokemon_pp(poke, POKEMON_BY_NAME, POKEMON_BY_NUMBER)

    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    pc = trainer.get('pc', [])
    pc.append(poke)
    trainer['pc'] = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'pc_size': len(pc), 'pokemon': poke})


# ══════════════ CAPTURA (autoridade 100% do servidor) ══════════════
# Bolas aceitas: ball_type (cliente) → nomes possíveis na bolsa + bônus no teste
CAPTURE_BALLS = {
    'pokeball':   {'names': ['pokébola', 'pokebola', 'poke ball', 'pokeball'],
                   'bonus': 0, 'label': '🔴 Pokébola'},
    'greatball':  {'names': ['super bola', 'great ball', 'bola super', 'super ball'],
                   'bonus': 2, 'label': '🔵 Super Bola'},
    'ultraball':  {'names': ['ultra bola', 'ultra ball', 'bola ultra'],
                   'bonus': 4, 'label': '⚫ Ultra Bola'},
    'netball':    {'names': ['net bola', 'net ball'],
                   'bonus': 0, 'label': '🟢 Net Bola'},
    'healball':   {'names': ['cura bola', 'heal ball'],
                   'bonus': 0, 'label': '🩷 Cura Bola'},
    'masterball': {'names': ['master ball', 'bola master'],
                   'bonus': 999, 'label': '🟣 Master Ball'},
}
# Bônus FIXO no teste d20 por status (regra da mesa): sono/congelamento pesam
# mais; paralisia/queimadura/veneno/confusão pesam menos.
CAPTURE_STATUS_BONUS = {'dormindo': 6, 'congelado': 6,
                        'paralisado': 3, 'queimado': 3,
                        'envenenado': 3, 'confuso': 3}
# Status que AFROUXAM o teto de HP (dá para tentar em HP mais alto).
CAPTURE_RELAX_STATUS = {'dormindo', 'congelado'}
CAPTURE_HP_GATE = 0.40           # sem status: só ≤40% do HP
CAPTURE_HP_GATE_RELAXED = 0.65   # dormindo/congelado: até 65%


def _find_ball_in_bag(bag, ball_type):
    names = set(CAPTURE_BALLS.get(ball_type, {}).get('names', []))
    for it in (bag or []):
        if isinstance(it, dict) and (it.get('name') or '').strip().lower() in names:
            return it
    return None


def _sr_int(sr):
    try:
        s = str(sr or '1/2')
        if '/' in s:
            a, b = s.split('/')[:2]
            return int(a) // max(1, int(b))
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _build_captured_pokemon(enc, base, level, cur_hp, heal_full=False):
    """Monta o Pokémon capturado a partir do ENCONTRO ATIVO (autoridade do
    servidor): mesmos MOVES com que lutou, atributos recalculados da espécie
    (idênticos aos do selvagem), HP enfraquecido preservado, e shiny/ability/
    postura do selvagem — 'cada detalhe de quando lutou'."""
    wild = enc.get('pokemon') or {}
    level = max(1, min(100, int(level)))
    is_shiny = bool(enc.get('is_shiny'))
    scaled = scaling.calculate_pokemon_stats(base, level, is_shiny=is_shiny)
    raw_moves = enc.get('wild_moves') or wild.get('moves') or []
    moves = [m for m in raw_moves
             if isinstance(m, str) and (m.lower() in MOVES_BY_NAME or m in MOVES_DB)][:4]
    if not moves:
        moves = list(base.get('startingMoves') or [])[:4] or ['Tackle']
    ab = wild.get('ability')
    ability = ab.get('name', '') if isinstance(ab, dict) else (ab or '')
    if not ability and isinstance(base.get('ability'), dict):
        ability = base['ability'].get('name', '')
    poke = {
        'name': base['name'], 'number': base['number'], 'nickname': '',
        'types': base.get('types', []), 'level': level,
        'moves': moves, 'ability': ability,
        'speed': base.get('speed', '30ft'),
        'vulnerabilities': base.get('vulnerabilities', []),
        'resistances': base.get('resistances', []),
        'immunities': base.get('immunities', []),
        'evolutionInfo': base.get('evolutionInfo', ''),
        'evolutionStage': base.get('evolutionStage', ''),
        'is_shiny': is_shiny,
        'stats': scaled['stats'], 'maxHp': scaled['maxHp'], 'hp': scaled['maxHp'],
        'defense_mode': int(wild.get('defense_mode') or 1),
        'xp': 0, 'totalXp': 0, 'battle_wins': 0,
        'sv': migrations.STATS_VERSION, 'training': {}, 'uid': secrets.token_hex(6),
    }
    if heal_full:
        poke['currentHp'] = scaled['maxHp']
    else:
        try:
            _c = int(cur_hp)
        except (TypeError, ValueError):
            _c = scaled['maxHp']
        poke['currentHp'] = max(1, min(scaled['maxHp'], _c))
    migrations.migrate_pokemon_pp(poke, POKEMON_BY_NAME, POKEMON_BY_NUMBER)
    return poke


@app.route('/player/capture', methods=['POST'])
@login_required
def player_capture():
    """Arremesso de Pokébola — RESOLUÇÃO 100% NO SERVIDOR (à prova de forja).

    Lê o selvagem do ENCONTRO ATIVO (espécie/nível/shiny/moves/HP/status são
    do servidor, nunca do cliente). Regras da mesa:
    - só ≤40% do HP; se estiver DORMINDO/CONGELADO, até 65% (o sono afrouxa);
    - status dá BÔNUS FIXO no teste (sono/congelamento +6, demais +3);
    - o capturado vai para o TIME com os mesmos moves/atributos com que lutou;
      time cheio → PC. Bola consumida da bolsa a cada arremesso.
    """
    if _rate_limit(15, 60, bucket='capture'):
        return jsonify({'error': 'Muitas tentativas de captura em pouco tempo.'}), 429
    data = request.json or {}
    ball_type = str(data.get('ball_type') or 'pokeball').strip().lower()
    if ball_type not in CAPTURE_BALLS:
        ball_type = 'pokeball'
    trapped = bool(data.get('trapped'))
    pid = str(current_user.id)

    gs = get_game_state()
    enc = (gs.get('active_encounters') or {}).get(pid)
    if not enc:
        return jsonify({'error': 'Nenhum encontro ativo para capturar.'}), 400
    wild = enc.get('pokemon') or {}
    base = POKEMON_BY_NUMBER.get(wild.get('number')) \
        or POKEMON_BY_NAME.get((wild.get('name') or '').lower())
    if not base or not base.get('base_stats'):
        return jsonify({'error': 'Espécie do encontro inválida'}), 400

    bs = enc.get('battle_state') or {}
    wild_max = max(1, int(bs.get('wild_hp_max') or wild.get('maxHp') or wild.get('hp') or 1))
    _wc_raw = bs.get('wild_hp_current')
    wild_cur = int(_wc_raw if _wc_raw is not None else wild_max)
    wild_cur = max(0, min(wild_max, wild_cur))
    hp_pct = wild_cur / wild_max
    fainted = wild_cur <= 0
    status = (bs.get('wild_status') or '').strip().lower() or None

    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {}) or {}
    trainer_attrs.migrate_trainer(trainer)
    bag = trainer.get('bag', []) or []
    ball = _find_ball_in_bag(bag, ball_type)
    ball_label = CAPTURE_BALLS[ball_type]['label']
    if not ball or int(ball.get('qty') or 0) < 1:
        return jsonify({'error': f'Você não tem {ball_label} na bolsa.'}), 400

    # consome 1 bola SEMPRE que arremessa
    ball['qty'] = int(ball['qty']) - 1
    trainer['bag'] = [i for i in bag if i is not ball] if ball['qty'] <= 0 else bag
    log = [f'{ball_label} arremessada!']

    def _persist(remove_enc, poke=None):
        if remove_enc:
            # persiste o HP/status de batalha do Pokémon ATIVO do jogador antes
            # de fechar o encontro (o cliente não pode salvar o time aqui — isso
            # apagaria o recém-capturado). Fonte = battle_state do servidor.
            try:
                _idx = enc.get('player_pokemon_idx')
                _team = trainer.get('team', []) or []
                if isinstance(_idx, int) and 0 <= _idx < len(_team):
                    _php = bs.get('player_hp_current')
                    if _php is not None:
                        _pm = int(_team[_idx].get('maxHp') or _team[_idx].get('hp') or 1)
                        _team[_idx]['currentHp'] = max(0, min(_pm, int(_php)))
                    _pst = bs.get('player_status')
                    if _pst:
                        _team[_idx]['status'] = _pst
                    else:
                        _team[_idx].pop('status', None)
            except (TypeError, ValueError, KeyError):
                pass
            (gs.get('active_encounters') or {}).pop(pid, None)
            save_game_state(gs)
            socketio.emit('encounter_ended',
                          {'player_id': current_user.id, 'result': 'capture'},
                          room=f'master_{_tid()}')
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)
        if poke is not None:
            socketio.emit('team_update',
                          {'player_id': current_user.id, 'team': trainer.get('team', [])},
                          room=f'master_{_tid()}')

    def _place(poke):
        """Time se tiver espaço, senão PC. Retorna ('team'|'pc', tamanho)."""
        team = trainer.get('team', []) or []
        if len(team) < 6:
            team.append(poke); trainer['team'] = team
            return 'team', len(team)
        pc = trainer.get('pc', []) or []
        pc.append(poke); trainer['pc'] = pc
        return 'pc', len(pc)

    sr = _sr_int(wild.get('sr') or base.get('sr'))
    level = max(1, min(100, int(enc.get('level') or wild.get('level') or 1)))
    heal_full = (ball_type == 'healball')

    # ── Master Ball: captura garantida (ignora teto e teste) ──
    if ball_type == 'masterball':
        team_now = trainer.get('team', []) or []
        cap_level = level
        if len(team_now) < 6 and not team_now and cap_level < 5:
            cap_level = 5
        poke = _build_captured_pokemon(enc, base, cap_level, wild_cur, heal_full)
        dest, size = _place(poke)
        _persist(True, poke)
        log.append('✅ CAPTURADO! (Master Ball — captura garantida!)')
        return jsonify({'ok': True, 'result': 'caught', 'log': log, 'ball': ball_type,
                        'status': status, 'wild_hp_pct': round(hp_pct, 3),
                        'encounter_over': True, 'captured': poke, 'destination': dest,
                        'team_size': len(trainer.get('team', [])),
                        'pc_size': len(trainer.get('pc', [])),
                        'dice': None, 'bag': trainer.get('bag', [])})

    # ── Teto de HP: sem status ≤40%; dormindo/congelado ≤65% ──
    gate = CAPTURE_HP_GATE_RELAXED if status in CAPTURE_RELAX_STATUS else CAPTURE_HP_GATE
    if not fainted and hp_pct > gate:
        pct = round(hp_pct * 100)
        log.append(f'💥 A Pokébola quebrou! O selvagem ainda tem {pct}% do HP '
                   f'(teto de {round(gate*100)}%). Enfraqueça-o mais!')
        over = not trapped
        if over:
            log.append('🏃 O Pokémon selvagem fugiu após a Pokébola falhar!')
        _persist(over)
        return jsonify({'ok': True, 'result': 'broke', 'log': log, 'ball': ball_type,
                        'status': status, 'wild_hp_pct': round(hp_pct, 3),
                        'encounter_over': over, 'captured': None, 'destination': None,
                        'dice': None, 'bag': trainer.get('bag', [])})

    # ── Teste de captura (d20) ──
    if fainted:
        dc = max(5, 5 + sr)
    else:
        dc = 10 + sr + level + (wild_cur // 10)
    r1, r2 = random.randint(1, 20), random.randint(1, 20)
    advantage = fainted   # desmaiado = vantagem; status agora dá bônus FIXO
    roll = max(r1, r2) if advantage else r1
    afinidade_bonus = trainer_attrs.skill_modifier(trainer, 'Afinidade')[0]
    ball_bonus = CAPTURE_BALLS[ball_type]['bonus']
    if ball_type == 'netball':
        wtypes = [str(t).lower() for t in (wild.get('types') or base.get('types') or [])]
        if any(t in ('bug', 'water') for t in wtypes):
            ball_bonus += 3
            log.append('🟢 Net Bola: +3 contra Bug/Water!')
    status_bonus = CAPTURE_STATUS_BONUS.get(status, 0) if status else 0
    total = roll + afinidade_bonus + ball_bonus + status_bonus
    dice = {'roll': roll, 'rolls': [r1, r2], 'advantage': advantage, 'dc': dc,
            'total': total, 'afinidade': afinidade_bonus, 'ball_bonus': ball_bonus,
            'status_bonus': status_bonus}

    if status_bonus:
        log.append(f'💤 {status.capitalize()}: +{status_bonus} no teste de captura!')
    log.append(f'CD de Captura: {dc} · d20({roll}{"↑" if advantage else ""})'
               f' + Afinidade({afinidade_bonus:+d})'
               + (f' + Bola(+{ball_bonus})' if ball_bonus else '')
               + (f' + Status(+{status_bonus})' if status_bonus else '')
               + f' = {total}')

    if total >= dc:
        team_now = trainer.get('team', []) or []
        cap_level = level
        if len(team_now) < 6 and not team_now and cap_level < 5:
            cap_level = 5
        poke = _build_captured_pokemon(enc, base, cap_level, wild_cur, heal_full)
        dest, size = _place(poke)
        _persist(True, poke)
        log.append(f'✅ CAPTURADO! 🎉 ({total} ≥ {dc})')
        if heal_full:
            log.append('🩷 Cura Bola: o Pokémon foi curado completamente!')
        if dest == 'pc':
            log.append(f'📦 Time cheio — guardado no PC! ({size} no PC)')
        return jsonify({'ok': True, 'result': 'caught', 'log': log, 'ball': ball_type,
                        'status': status, 'wild_hp_pct': round(hp_pct, 3),
                        'encounter_over': True, 'captured': poke, 'destination': dest,
                        'team_size': len(trainer.get('team', [])),
                        'pc_size': len(trainer.get('pc', [])),
                        'dice': dice, 'bag': trainer.get('bag', [])})

    # falhou o teste
    log.append(f'❌ {ball_label} falhou! ({total} < {dc})')
    over = not trapped
    if over:
        log.append('🏃 O Pokémon selvagem fugiu!')
    _persist(over)
    return jsonify({'ok': True, 'result': 'failed', 'log': log, 'ball': ball_type,
                    'status': status, 'wild_hp_pct': round(hp_pct, 3),
                    'encounter_over': over, 'captured': None, 'destination': None,
                    'dice': dice, 'bag': trainer.get('bag', [])})


@app.route('/player/pc/deposit', methods=['POST'])
@login_required
def pc_deposit():
    """Move a Pokémon from team to PC."""
    data = request.json or {}
    idx  = _int_arg(data, 'team_idx', -1)   # índice não-int não crasha (QA LOOP 4)

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])

    if idx < 0 or idx >= len(team):
        return jsonify({'error': 'Índice inválido'}), 400
    if len(team) <= 1:
        return jsonify({'error': 'Você não pode depositar seu último Pokémon!'}), 400

    poke = team.pop(idx)
    pc   = trainer.get('pc', [])
    pc.append(poke)
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/pc/withdraw', methods=['POST'])
@login_required
def pc_withdraw():
    """Move a Pokémon from PC to team."""
    data = request.json or {}
    idx  = _int_arg(data, 'pc_idx', -1)   # índice não-int não crasha (QA LOOP 4)

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    pc      = trainer.get('pc', [])

    if idx < 0 or idx >= len(pc):
        return jsonify({'error': 'Índice inválido'}), 400
    if len(team) >= 6:
        return jsonify({'error': 'Time cheio! Deposite um Pokémon primeiro.'}), 400

    poke = pc.pop(idx)
    team.append(poke)
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/pc/swap', methods=['POST'])
@login_required
def pc_swap():
    """Swap a team Pokémon directly with a PC Pokémon."""
    data     = request.json or {}
    if data.get('team_idx') is None or data.get('pc_idx') is None:
        return jsonify({'error': 'Parâmetros inválidos'}), 400
    team_idx = _int_arg(data, 'team_idx', -1)   # índice não-int não crasha (QA LOOP 4)
    pc_idx   = _int_arg(data, 'pc_idx', -1)

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    pc      = trainer.get('pc', [])

    if team_idx < 0 or team_idx >= len(team) or pc_idx < 0 or pc_idx >= len(pc):
        return jsonify({'error': 'Índice fora dos limites'}), 400

    team[team_idx], pc[pc_idx] = pc[pc_idx], team[team_idx]
    trainer['team'] = team
    trainer['pc']   = pc
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'team': team, 'pc': pc})


@app.route('/player/use-stone', methods=['POST'])
@login_required
def use_evolution_stone():
    """Player uses an evolution stone/item on a team Pokémon."""
    data = request.json or {}
    pokemon_idx = data.get('pokemon_idx')
    item_name   = (data.get('item_name') or '').strip()

    if pokemon_idx is None or not item_name:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])
    bag     = trainer.get('bag', [])

    if pokemon_idx < 0 or pokemon_idx >= len(team):
        return jsonify({'error': 'Pokémon inválido'}), 400

    pokemon = team[pokemon_idx]

    # Check item is in bag
    bag_item = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if not bag_item or (bag_item.get('qty') or 0) < 1:
        return jsonify({'error': f'Você não tem {item_name} na bolsa!'}), 400

    # Check evolution — endpoint de pedra só avalia a PEDRA (nunca passa
    # moves/battle_wins, senão condição de outro tipo consumiria o item)
    evolved_name, ok = scaling.get_special_evolution(
        pokemon['name'],
        stone_used=item_name
    )
    if not ok or not evolved_name:
        return jsonify({'error': f'{pokemon["name"]} não evolui com {item_name}.'}), 400

    evolved_base = POKEMON_BY_NAME.get(evolved_name.lower())
    if not evolved_base:
        return jsonify({'error': f'Pokémon evoluído "{evolved_name}" não encontrado no banco.'}), 404

    evolved = build_evolved_pokemon(pokemon, evolved_base)
    team[pokemon_idx] = evolved

    # Consume item from bag
    bag_item['qty'] = (bag_item.get('qty') or 1) - 1
    if bag_item['qty'] <= 0:
        bag.remove(bag_item)
    trainer['team'] = team
    trainer['bag']  = bag
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    stone_new_moves = _evolution_new_moves(pokemon, evolved_base)
    _emit_evolution_focus(current_user.id, current_user.username, pokemon_idx,
                          pokemon, evolved, stone_new_moves, 'stone')

    return jsonify({
        'ok': True, 'evolved_into': evolved['name'], 'pokemon': evolved,
        'old_number': pokemon.get('number', 0), 'new_number': evolved.get('number', 0),
        'new_moves': stone_new_moves
    })


@app.route('/player/pokemon-center', methods=['POST'])
@login_required
def pokemon_center():
    """Heal all Pokémon to full HP and clear all status conditions."""
    # Não pode curar o time no MEIO de uma batalha (era cura grátis a cada
    # turno de um encontro/PvP em andamento).
    _pid = str(current_user.id)
    if (get_game_state().get('active_encounters') or {}).get(_pid):
        return jsonify({'error': 'Não pode usar o Centro Pokémon durante uma batalha.'}), 400
    if any(_pid in (b.get('player1', {}).get('id'), b.get('player2', {}).get('id'))
           and b.get('phase') == 'battle' for b in ACTIVE_PVP.values()):
        return jsonify({'error': 'Não pode usar o Centro Pokémon durante um PvP.'}), 400

    users = get_users()
    trainer = users[current_user.id].get('trainer_data', {})
    team = trainer.get('team', [])

    for poke in team:
        poke['currentHp'] = poke.get('maxHp', poke.get('hp', 20))
        poke.pop('status', None)

    trainer['team'] = team
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    socketio.emit('team_update', {
        'player_id': current_user.id,
        'team': team
    }, room=f'master_{_tid()}')

    return jsonify({'ok': True, 'team': team})


@app.route('/player/level-evolve', methods=['POST'])
@login_required
def level_evolve():
    """Manually trigger a level-based evolution check for a team slot."""
    data = request.json or {}
    if data.get('slot') is None:
        return jsonify({'error': 'Slot inválido'}), 400
    slot = _int_arg(data, 'slot', -1)   # slot não-int não crasha (QA LOOP 5)

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    team    = trainer.get('team', [])

    if slot < 0 or slot >= len(team):
        return jsonify({'error': 'Slot inválido'}), 400

    pokemon = team[slot]
    old_name = pokemon.get('name', '')
    evolved, evolved_name = check_and_evolve_pokemon(pokemon)

    if not evolved:
        return jsonify({'evolved': False, 'message': f'{old_name} não atingiu o nível necessário para evoluir ainda.'})

    evolved_base_data = POKEMON_BY_NAME.get(evolved_name.lower(), {})
    new_moves = _evolution_new_moves(pokemon, evolved_base_data)

    team[slot] = evolved
    trainer['team'] = team
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    _emit_evolution_focus(current_user.id, current_user.username, slot,
                          pokemon, evolved, new_moves, 'level')

    return jsonify({
        'evolved': True, 'old_name': old_name, 'pokemon': evolved,
        'old_number': pokemon.get('number', 0),
        'new_number': evolved.get('number', 0),
        'new_moves': new_moves
    })


def _mig(pokes):
    """Migra dicts de Pokémon v1→v2 in-place (idempotente). Retorna changed."""
    return migrations.ensure_v2(pokes, POKEMON_BY_NAME, POKEMON_BY_NUMBER)


def _sanitize_training(tr, budget):
    """Devolve uma distribuição de treino VÁLIDA sob a economia Custom EVs:
    respeita o orçamento (custo progressivo n(n+1)/2) e o anti-min-max (stat
    em múltiplo de 5 sem par cai ao múltiplo). Nunca rejeita — clampa — para
    que o save normal do time (level-up, captura) não quebre."""
    stats = bm_core.TRAINING_STATS
    t = {k: max(0, int((tr or {}).get(k, 0) or 0)) for k in stats}
    # 1) orçamento: reduz o stat de maior valor (maior custo marginal) até caber
    guard = 0
    while bm_core.training_spent(t) > budget and guard < 100000:
        k = max(stats, key=lambda s: t[s])
        if t[k] <= 0:
            break
        t[k] -= 1
        guard += 1
    # 2) anti-min-max: stat acima de um múltiplo de 5 sem par cai ao múltiplo
    changed = True
    while changed:
        changed = False
        for k in stats:
            v = t[k]
            m = 5 * ((v - 1) // 5) if v > 0 else 0
            if m > 0 and not any(o != k and t[o] >= m for o in stats):
                t[k] = m
                changed = True
    return t


def _stamp_tatica(team, trainer):
    """Iniciativa: Pokémon de TREINADOR ganham +mod(♟️ Tática)//2 no d20 —
    a decisão mais inteligente sai na frente. Selvagens/NPCs não têm
    treinador humano → bônus 0 (nada estampado)."""
    if not isinstance(trainer, dict) or not trainer:
        return 0
    trainer_attrs.migrate_trainer(trainer)
    bonus = trainer_attrs.attr_mod(trainer, 'tatica') // 2
    for p in (team or []):
        if isinstance(p, dict):
            p['trainer_init_bonus'] = bonus
    return bonus


def _enrich_team(team):
    """Fill in missing evolutionInfo / type matchups from base pokemon data."""
    _mig(team)
    for poke in team:
        if not poke:
            continue
        base = POKEMON_BY_NAME.get((poke.get('name') or '').lower())
        if not base:
            continue
        if not poke.get('evolutionInfo'):
            poke['evolutionInfo'] = base.get('evolutionInfo', '')
        if not poke.get('evolutionStage'):
            poke['evolutionStage'] = base.get('evolutionStage', '')
        # A ficha não preenche as listas de tipo — sem elas, imunidades
        # (Ghost×Normal etc.) não valem na batalha selvagem do cliente.
        for field in ('vulnerabilities', 'resistances', 'immunities'):
            if not poke.get(field):
                poke[field] = base.get(field, [])
    return team

@app.route('/player/team-data')
@login_required
def get_team_data():
    """Return the current player's team (for live refresh after evolution)."""
    users = get_users()
    team = users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
    return jsonify(_enrich_team(team))

@app.route('/player/team', methods=['POST'])
@login_required
def update_team():
    """Update player's Pokemon team."""
    data = request.json
    users = get_users()
    if current_user.id in users:
        team = data.get('team', [])
        # Snapshot do treino ENVIADO pelo cliente ANTES de qualquer migração:
        # `_mig` roda migrate_pokemon_pp, que ZERA `training` de Pokémon sem o
        # selo `pp` (legado / pp perdido). Sem este snapshot, um save logo após
        # o Centro Pokémon apagava os EVs recém-distribuídos.
        _incoming_trainings = [
            dict(p.get('training') or {}) if isinstance(p, dict) else {}
            for p in team
        ]
        _incoming_by_id = {id(p): _incoming_trainings[i]
                           for i, p in enumerate(team) if isinstance(p, dict)}
        _mig(team)
        # Estado ANTERIOR do time (autoridade sobre nível/shiny): impede o
        # cliente de saltar para Nv.100 ou ligar shiny de graça. Casa por
        # (número, apelido); Pokémon novo (captura) não casa e é tratado à parte.
        # Cada chave guarda uma LISTA (FIFO): dois Pokémon da mesma espécie SEM
        # apelido não colidem — cada incoming consome um prev distinto (senão o
        # shiny de um vazava para o outro / era ligado de graça).
        prev_team = users[current_user.id].get('trainer_data', {}).get('team', [])
        prev_by_key, prev_by_num, prev_by_uid = {}, {}, {}
        for pp in prev_team:
            if isinstance(pp, dict):
                prev_by_key.setdefault(
                    (pp.get('number'), (pp.get('nickname') or '')), []).append(pp)
                prev_by_num.setdefault(pp.get('number'), []).append(pp)
                if pp.get('uid'):
                    prev_by_uid[pp['uid']] = pp
        _consumed = set()   # id() dos prev já casados (uid e FIFO não colidem)

        def _take_prev(pp_):
            _consumed.add(id(pp_))
            return pp_

        def _pop_fifo(lst):
            while lst:
                cand = lst.pop(0)
                if id(cand) not in _consumed:
                    return _take_prev(cand)
            return None
        clean_team = []
        for p in team:
            if not isinstance(p, dict):
                continue
            # ESPÉCIE precisa existir no Pokédex — senão o cliente forjaria
            # stats de uma espécie inventada (o bloco de recálculo é pulado)
            base = POKEMON_BY_NAME.get((p.get('name') or '').lower()) \
                or POKEMON_BY_NUMBER.get(p.get('number'))
            if not base or not base.get('base_stats'):
                continue   # espécie desconhecida → descarta (anti-forja)
            # Identidade ESTÁVEL: 1º por uid (sobrevive a apelido/evolução);
            # 2º pela chave legada (número, apelido); 3º só pelo número —
            # sem o fallback, RENOMEAR um Pokémon descartava o `pp` e a
            # migração re-rodava ZERANDO o treino (Custom EVs) do nada.
            prev = None
            _uid = p.get('uid')
            if _uid and _uid in prev_by_uid and id(prev_by_uid[_uid]) not in _consumed:
                prev = _take_prev(prev_by_uid[_uid])
            if prev is None:
                prev = _pop_fifo(prev_by_key.get(
                    (p.get('number'), (p.get('nickname') or '')), []))
            if prev is None:
                prev = _pop_fifo(prev_by_num.get(p.get('number'), []))
            # uid é AUTORIDADE DO SERVIDOR: herda do prev ou ganha um novo
            # (uid desconhecido vindo do cliente é descartado)
            p['uid'] = (prev or {}).get('uid') or secrets.token_hex(6)
            level = max(1, min(100, int(p.get('level') or 1)))
            if prev is not None:
                # Pokémon já existente: nível só sobe (e no máx. +5 por save,
                # pois level-up é incremental) e o shiny não muda pelo cliente
                prev_level = max(1, min(100, int(prev.get('level') or 1)))
                level = max(prev_level, min(level, prev_level + 5))
                p['is_shiny'] = bool(prev.get('is_shiny'))
            else:
                # Pokémon novo (captura): shiny é o do encontro; nível limitado
                p['is_shiny'] = bool(p.get('is_shiny'))
                # Primeiro Pokémon do treinador nunca nasce abaixo do Nv.5
                # (regra da mesa — garantida no servidor, não só no cliente).
                if not prev_team and level < 5:
                    level = 5
            p['level'] = level

            # Campos de Potencial são AUTORIDADE DO SERVIDOR (bônus de evolução
            # rolado, bônus do mestre) — o cliente não pode forjá-los.
            for f in ('potential_evo_bonus', 'potential_special', 'training_bonus', 'pp'):
                if prev is not None and f in prev:
                    p[f] = prev[f]
                else:
                    p.pop(f, None)
            # treino ENVIADO pelo cliente (snapshot pré-migração, lá do topo).
            _incoming_training = _incoming_by_id.get(id(p), p.get('training') or {})
            migrations.migrate_pokemon_pp(p, POKEMON_BY_NAME, POKEMON_BY_NUMBER)

            # evolutionStage é AUTORIDADE DA ESPÉCIE. A ficha (savePokemon) salva
            # SEM esse campo; sem ele o painel de Custom EVs do cliente recalcula
            # o orçamento como se fosse estágio final (1/1) e mostra pontos-
            # fantasma que "reaparecem" a cada volta ao Centro. Carimba do dataset.
            p['evolutionStage'] = base.get('evolutionStage') or p.get('evolutionStage') or ''
            if base.get('evolutionInfo') and not p.get('evolutionInfo'):
                p['evolutionInfo'] = base.get('evolutionInfo')

            # Distribuição Custom EVs: custo progressivo n(n+1)/2 + anti-min-max.
            # Sempre parte do treino que o cliente enviou (clampado ao orçamento);
            # a migração já fez o backup do formato antigo em training_old_v2.
            budget = migrations.budget_for(p, base)
            p['training'] = _sanitize_training(_incoming_training, budget)
            p['statPointsAvailable'] = max(0, budget - bm_core.training_spent(p['training']))
            # stats são DERIVADOS (espécie+nível+natureza+shiny+treino):
            # recalcula no save — o cliente nunca é autoridade sobre stats
            scaled = scaling.calculate_pokemon_stats(
                base, level, p.get('nature') or None,
                is_shiny=bool(p.get('is_shiny')), training=p['training'])
            p['stats'] = scaled['stats']
            p['maxHp'] = scaled['maxHp']
            p['hp'] = scaled['maxHp']
            cur = p.get('currentHp')
            if not isinstance(cur, (int, float)):
                p['currentHp'] = scaled['maxHp']
            elif cur > scaled['maxHp']:
                p['currentHp'] = scaled['maxHp']
            # chaves D&D aposentadas não voltam mais para o save
            for legacy in ('hitDice', 'savingThrows', 'ac'):
                p.pop(legacy, None)
            clean_team.append(p)
        users[current_user.id]['trainer_data']['team'] = clean_team
        save_users(users)
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/player/trainer', methods=['POST'])
@login_required
def update_trainer():
    """Update trainer data."""
    data = request.json
    users = get_users()
    if current_user.id in users:
        trainer = users[current_user.id]['trainer_data']
        # MIGRA ANTES de aplicar o payload: fixa av=2 e promove os atributos
        # LEGADO (str/dex/...) já SALVOS para os 6 novos. Sem isto, um jogador
        # com ficha ainda não migrada (todo recém-criado no 1º POST) forjava
        # os legado no payload e o migrate os promovia a 20, driblando o
        # point-buy (Tática→iniciativa, Influência→preço da loja). QA LOOP 2.
        trainer_attrs.migrate_trainer(trainer)
        # Campos que o jogador PODE editar na própria ficha. money, badges,
        # pokeslots, max_sr e pokedex_seen saíram daqui de propósito: mudam
        # só por fluxos do servidor (loja, quest, PvP, ginásio, Pokédex) —
        # senão o jogador se dava dinheiro/insígnias infinitos.
        # 'path' saiu daqui: o Caminho do Treinador é gerenciado por /player/path
        # (permanente, com gate de nível) — não é campo livre.
        # str/dex/con/int/wis/cha (legado D&D) SAÍRAM: são mortos após a
        # migração e eram o vetor do exploit de point-buy acima.
        allowed_fields = ['name', 'visited_routes', 'notes',
                         'race', 'background', 'specializations',
                         'skill_profs',
                         'hp_max', 'hp_current', 'proficiencies',
                         'avatar', 'trainerStatPointsUsed']
        for field in allowed_fields:
            if field in data:
                trainer[field] = data[field]
        # Atributos do treinador via POINT-BUY (base 10, teto 16, 20 pontos).
        # Se o jogador enviou qualquer um dos 6, valida o conjunto inteiro e
        # rejeita a ficha toda se estourar o orçamento — impede forjar 20 em
        # tudo. (Bônus do mestre são aplicados por /master/edit-player.)
        if any(k in data for k in trainer_attrs.ATTRIBUTES):
            trainer_attrs.migrate_trainer(trainer)
            incoming = {k: data.get(k, trainer.get(k, trainer_attrs.POINT_BUY_BASE))
                        for k in trainer_attrs.ATTRIBUTES}
            ok, cleaned, err = trainer_attrs.validate_point_buy(incoming)
            if not ok:
                return jsonify({'error': err}), 400
            for k, v in cleaned.items():
                trainer[k] = v
        # A bolsa o jogador gerencia (usar poção/bola), mas sanitiza para não
        # forjar itens: quantidades inteiras 0-999; sem entradas malformadas.
        if isinstance(data.get('bag'), list):
            clean_bag = []
            for it in data['bag']:
                if not isinstance(it, dict) or not it.get('name'):
                    continue
                try:
                    qty = max(0, min(999, int(it.get('qty', 1))))
                except (TypeError, ValueError):
                    qty = 1
                if qty <= 0:
                    continue
                clean_bag.append({'name': str(it['name'])[:60], 'qty': qty,
                                  'description': str(it.get('description', ''))[:200]})
            trainer['bag'] = clean_bag
        # atributos novos: valida 1-20; perícias: teto por nível
        trainer_attrs.migrate_trainer(trainer)
        for key in trainer_attrs.ATTRIBUTES:
            try:
                trainer[key] = max(1, min(20, int(trainer.get(key, 10) or 10)))
            except (TypeError, ValueError):
                trainer[key] = 10
        trainer_attrs.clamp_profs(trainer)
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404


@app.route('/player/path', methods=['GET', 'POST'])
@login_required
def player_path():
    """Caminho do Treinador: GET devolve o estado; POST escolhe o caminho (nv 2,
    permanente) ou uma habilidade de marco (nv 3/6/10, 1 de 3)."""
    users = get_users()
    if current_user.id not in users:
        return jsonify({'error': 'User not found'}), 404
    trainer = users[current_user.id].setdefault('trainer_data', {})
    trainer_attrs.migrate_trainer(trainer)

    if request.method == 'GET':
        return jsonify(trainer_attrs.path_state(trainer))

    data = request.json or {}
    action = data.get('action')
    if action == 'choose_path':
        ok, err = trainer_attrs.choose_path(trainer, data.get('path'))
    elif action == 'choose_ability':
        ok, err = trainer_attrs.choose_path_ability(
            trainer, data.get('milestone'), data.get('ability_id'))
    else:
        return jsonify({'error': 'Ação inválida'}), 400
    if not ok:
        return jsonify({'error': err}), 400
    save_users(users)
    return jsonify(dict(trainer_attrs.path_state(trainer), success=True))


@app.route('/player/avatar', methods=['POST'])
@login_required
def upload_avatar():
    """Upload player avatar image."""
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    # Validate extension
    allowed_ext = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        return jsonify({'error': 'Tipo de arquivo inválido. Use PNG, JPG, GIF ou WebP.'}), 400
    # Validate magic bytes (first 12 bytes) to prevent content-type spoofing
    header = file.read(12)
    file.seek(0)
    magic_map = {
        b'\x89PNG': '.png',
        b'\xff\xd8\xff': '.jpg',
        b'GIF8': '.gif',
        b'RIFF': '.webp',
    }
    detected = None
    for magic, detected_ext in magic_map.items():
        if header[:len(magic)] == magic:
            detected = detected_ext
            break
    # JPEG also accepted as .jpeg
    if detected == '.jpg' and ext == '.jpeg':
        detected = '.jpeg'
    if detected is None and ext not in ('.jpg', '.jpeg'):
        return jsonify({'error': 'Conteúdo do arquivo não corresponde à extensão.'}), 400

    # Use absolute path so it works regardless of CWD
    avatar_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'avatars')
    os.makedirs(avatar_dir, exist_ok=True)
    filename = f"{current_user.id}{ext}"
    filepath = os.path.join(avatar_dir, filename)
    file.save(filepath)
    # Update trainer data with avatar path
    users = get_users()
    if current_user.id in users:
        users[current_user.id]['trainer_data']['avatar'] = f"/static/uploads/avatars/{filename}"
        save_users(users)
    return jsonify({'success': True, 'avatar_url': f"/static/uploads/avatars/{filename}"})

# ============================================================
# SHOP / POKÉMART
# ============================================================
SHOP_CATALOG = [
    # Pokébolas
    {'id': 'poke-ball',   'name': 'Pokébola',    'category': 'pokeball', 'price': 200,   'description': 'Pokébola padrão. DC captura base.'},
    {'id': 'great-ball',  'name': 'Super Bola',  'category': 'pokeball', 'price': 600,   'description': '+2 no teste de captura.'},
    {'id': 'ultra-ball',  'name': 'Ultra Bola',  'category': 'pokeball', 'price': 1200,  'description': '+4 no teste de captura.'},
    {'id': 'master-ball', 'name': 'Master Ball', 'category': 'pokeball', 'price': 99999, 'description': 'Captura garantida. Muito raro.'},
    {'id': 'heal-ball',   'name': 'Cura Bola',   'category': 'pokeball', 'price': 300,   'description': 'Cura o Pokémon capturado.'},
    {'id': 'net-ball',    'name': 'Net Bola',     'category': 'pokeball', 'price': 1000,  'description': '+3 em Bug e Water.'},
    # Poções
    {'id': 'potion',        'name': 'Poção',         'category': 'medicine', 'price': 300,  'description': 'Restaura 2d4+2 HP de um Pokémon.'},
    {'id': 'super-potion',  'name': 'Super Poção',   'category': 'medicine', 'price': 700,  'description': 'Restaura 4d4+4 HP de um Pokémon.'},
    {'id': 'hyper-potion',  'name': 'Hiper Poção',   'category': 'medicine', 'price': 1500, 'description': 'Restaura 6d4+12 HP de um Pokémon.'},
    {'id': 'max-potion',    'name': 'Poção Máxima',  'category': 'medicine', 'price': 2500, 'description': 'Restaura todos os HP de um Pokémon.'},
    {'id': 'full-restore',  'name': 'Restauração',   'category': 'medicine', 'price': 3000, 'description': 'Restaura HP e cura condição de status.'},
    {'id': 'antidote',      'name': 'Antídoto',      'category': 'medicine', 'price': 100,  'description': 'Cura envenenamento.'},
    {'id': 'burn-heal',     'name': 'Cura Queimadura','category':'medicine', 'price': 250,  'description': 'Cura queimadura.'},
    {'id': 'ice-heal',      'name': 'Cura Gelo',     'category': 'medicine', 'price': 250,  'description': 'Cura congelamento.'},
    {'id': 'awakening',     'name': 'Despertar',     'category': 'medicine', 'price': 250,  'description': 'Acorda um Pokémon dormindo.'},
    {'id': 'paralyze-heal', 'name': 'Cura Paralisia','category': 'medicine', 'price': 200,  'description': 'Cura paralisia.'},
    {'id': 'full-heal',     'name': 'Cura Total',    'category': 'medicine', 'price': 600,  'description': 'Cura qualquer condição de status.'},
    {'id': 'revive',        'name': 'Reviver',       'category': 'medicine', 'price': 1500, 'description': 'Revive Pokémon desmaiado com metade do HP.'},
    {'id': 'max-revive',    'name': 'Reviver Máx',   'category': 'medicine', 'price': 4000, 'description': 'Revive Pokémon com HP máximo.'},
    {'id': 'ether',         'name': 'Éter',          'category': 'medicine', 'price': 1200, 'description': 'Restaura PP de um golpe (+1 uso).'},
    # Batalha
    {'id': 'x-attack',   'name': 'X Ataque',    'category': 'battle', 'price': 500,  'description': '+2 ATK por 1 batalha.'},
    {'id': 'x-defense',  'name': 'X Defesa',    'category': 'battle', 'price': 550,  'description': '+2 AC por 1 batalha.'},
    {'id': 'x-speed',    'name': 'X Velocidade','category': 'battle', 'price': 350,  'description': '+2 SPE por 1 batalha.'},
    {'id': 'x-sp-atk',   'name': 'X At. Esp.',  'category': 'battle', 'price': 500,  'description': '+2 SPA por 1 batalha.'},
    {'id': 'dire-hit',   'name': 'Acerto Certo','category': 'battle', 'price': 650,  'description': 'Aumenta críticos por 1 batalha.'},
    # Itens de evolução
    {'id': 'fire-stone',    'name': 'Pedra Fogo',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'water-stone',   'name': 'Pedra Água',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'thunder-stone', 'name': 'Pedra Trovão',  'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'leaf-stone',    'name': 'Pedra Folha',   'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'moon-stone',    'name': 'Pedra Lua',     'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'sun-stone',     'name': 'Pedra Solar',   'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'shiny-stone',   'name': 'Pedra Brilhante','category':'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'dusk-stone',    'name': 'Pedra Crepúsculo','category':'evo_stone','price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'dawn-stone',    'name': 'Pedra Aurora',  'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    {'id': 'ice-stone',     'name': 'Pedra Gelo',    'category': 'evo_stone', 'price': 3000, 'description': 'Usada para certas evoluções.'},
    # Itens segurados
    {'id': 'leftovers',   'name': 'Restos',       'category': 'held', 'price': 4000, 'description': 'Cura 1d4 HP no início de cada turno.'},
    {'id': 'choice-band', 'name': 'Faixa Seleção','category': 'held', 'price': 5000, 'description': '+1d6 ATK, mas só pode usar 1 golpe.'},
    {'id': 'life-orb',    'name': 'Orbe Vida',    'category': 'held', 'price': 5000, 'description': '+30% dano, -10% HP por uso.'},
    {'id': 'rocky-helmet','name': 'Capacete Pedra','category':'held', 'price': 3000, 'description': 'Quem ataca corpo a corpo perde 1d6 HP.'},
    # Raros/Especiais
    {'id': 'rare-candy',  'name': 'Bala Rara',    'category': 'special', 'price': 2000, 'description': 'Aumenta 1 nível do Pokémon.'},
    {'id': 'repel',       'name': 'Repelente',    'category': 'special', 'price': 350,  'description': 'Evita encontros por 1 hora.'},
    {'id': 'super-repel', 'name': 'Super Repelente','category':'special','price': 500,  'description': 'Evita encontros por 2 horas.'},
    {'id': 'energy-drink','name': 'Energy Drink', 'category': 'special', 'price': 750,  'description': 'Recupera o ânimo: +1 caçada extra no dia. Consumível.'},
]

# Itens que dão +1 caçada quando consumidos (nome em minúsculas)
ENERGY_DRINK_NAMES = {'energy drink'}

@app.route('/api/shop')
@login_required
def api_shop():
    """Return the shop catalog. Master can hide items via game_state."""
    game_state = get_game_state()
    hidden_items = set(game_state.get('shop_hidden_items', []))
    catalog = [item for item in SHOP_CATALOG if item['id'] not in hidden_items]
    return jsonify(catalog)

def _int_arg(data, key, default=1, lo=None, hi=None):
    """Inteiro robusto vindo do payload: qty/amount/level malformados
    (string, null, float) NÃO derrubam a request com 500 — caem no default
    e são clampados. QA LOOP 2."""
    try:
        v = int((data or {}).get(key, default))
    except (TypeError, ValueError):
        v = int(default)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v

def _influence_value(trainer):
    """👑 Influência (Diplomacia) manda nos preços da loja — herda o valor
    do CAR antigo pela migração automática."""
    trainer_attrs.migrate_trainer(trainer)
    try:
        base = int(trainer.get('influencia', 10) or 10)
    except (TypeError, ValueError):
        base = 10
    # bônus do Caminho (👑 Inspirador → Palavra Certa = +1 Influência)
    _, attr_bonus = trainer_attrs.path_bonuses(trainer)
    return base + attr_bonus.get('influencia', 0)


def _cha_modifier(influencia: int):
    """Returns (buy_multiplier, sell_multiplier) based on trainer Influência.
    10 = normal prices. Each point above/below 10 = -2% buy / +3% sell.
    Capped at ±20% buy and ±30% sell."""
    delta = max(-9, min(10, influencia - 10))  # clamp to [-9, 10]
    buy_mult  = max(0.80, 1.0 - delta * 0.02)   # 20 → 0.80, 1 → 1.18
    sell_mult = min(0.70, 0.50 + delta * 0.02)  # 20 → 0.70, 1 → 0.32
    return round(buy_mult, 4), round(sell_mult, 4)

@app.route('/api/shop/buy', methods=['POST'])
@login_required
def api_shop_buy():
    """Buy an item. Deducts money (modified by CHA) and adds to player bag."""
    if current_user.role == 'master':
        return jsonify({'error': 'Mestre não pode comprar itens'}), 403
    data = request.json or {}
    item_id = data.get('item_id')
    qty = _int_arg(data, 'qty', 1, lo=1)

    item = next((i for i in SHOP_CATALOG if i['id'] == item_id), None)
    if not item:
        return jsonify({'error': 'Item não encontrado'}), 404

    # Guard anti double-spend (duplo-clique): read-modify-write de dinheiro
    # protegido por um flag síncrono (atômico sob gevent).
    if current_user.id in _ECON_BUSY:
        return jsonify({'error': 'Operação em andamento, tente de novo.'}), 429
    _ECON_BUSY.add(current_user.id)
    try:
        users = get_users()
        trainer = users.get(current_user.id, {}).get('trainer_data', {})
        cha = _influence_value(trainer)
        buy_mult, _ = _cha_modifier(cha)
        unit_price = max(1, int(item['price'] * buy_mult))
        total_cost = unit_price * qty

        money = trainer.get('money', 0)
        if money < total_cost:
            return jsonify({'error': f'Sem dinheiro suficiente! Precisa de ₽{total_cost}, tem ₽{money}'}), 400

        trainer['money'] = money - total_cost
        bag = trainer.get('bag', [])
        existing = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item['name'].lower()), None)
        if existing:
            existing['qty'] = existing.get('qty', 1) + qty
        else:
            bag.append({'name': item['name'], 'qty': qty, 'description': item['description']})
        trainer['bag'] = bag
        users[current_user.id]['trainer_data'] = trainer
        save_users(users)
        return jsonify({'success': True, 'money_left': trainer['money'], 'item': item,
                        'qty': qty, 'unit_price': unit_price, 'cha_bonus': cha != 10})
    finally:
        _ECON_BUSY.discard(current_user.id)

@app.route('/api/shop/sell', methods=['POST'])
@login_required
def api_shop_sell():
    """Sell an item from the player's bag. Price affected by CHA stat."""
    if current_user.role == 'master':
        return jsonify({'error': 'Mestre não pode vender itens'}), 403
    data = request.json or {}
    item_name = (data.get('item_name') or '').strip()
    qty = _int_arg(data, 'qty', 1, lo=1)

    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])

    bag_item = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if not bag_item or (bag_item.get('qty') or 0) < qty:
        return jsonify({'error': f'Você não tem {qty}x {item_name} na bolsa'}), 400

    # Find base price from catalog — item fora do catálogo (item de história/
    # quest) NÃO é vendável (senão rendia um preço fixo de ~200 do nada).
    catalog_item = next((i for i in SHOP_CATALOG if i['name'].lower() == item_name.lower()), None)
    if not catalog_item:
        return jsonify({'error': 'Este item não pode ser vendido na loja.'}), 400

    cha = _influence_value(trainer)
    _, sell_mult = _cha_modifier(cha)
    unit_price = max(1, int(catalog_item['price'] * sell_mult))
    total_earned = unit_price * qty

    # Remove from bag
    bag_item['qty'] = bag_item.get('qty', qty) - qty
    if bag_item['qty'] <= 0:
        bag.remove(bag_item)

    trainer['bag'] = bag
    trainer['money'] = trainer.get('money', 0) + total_earned
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)

    return jsonify({
        'success': True,
        'item_name': item_name,
        'qty': qty,
        'unit_price': unit_price,
        'total_earned': total_earned,
        'money': trainer['money'],
        'cha': cha,
        'cha_bonus': cha != 10
    })

@app.route('/api/shop/sell-price', methods=['POST'])
@login_required
def api_shop_sell_price():
    """Preview sell price for an item based on player CHA."""
    data = request.json or {}
    item_name = (data.get('item_name') or '').strip()
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    cha = _influence_value(trainer)
    _, sell_mult = _cha_modifier(cha)
    catalog_item = next((i for i in SHOP_CATALOG if i['name'].lower() == item_name.lower()), None)
    base_price = catalog_item['price'] if catalog_item else 0
    unit_price = max(1, int(base_price * sell_mult)) if base_price else 0
    return jsonify({'unit_price': unit_price, 'cha': cha, 'sell_mult': round(sell_mult * 100)})

@app.route('/player/pc/items', methods=['GET'])
@login_required
def get_pc_items():
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    return jsonify(trainer.get('pc_items', []))

@app.route('/player/pc/items/deposit', methods=['POST'])
@login_required
def pc_deposit_item():
    """Move item(s) from bag to PC item storage."""
    data = request.json or {}
    item_name = (data.get('item_name') or '').strip()
    qty = _int_arg(data, 'qty', 1, lo=1)
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])
    pc_items = trainer.get('pc_items', [])

    bag_item = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if not bag_item or bag_item.get('qty', 0) < qty:
        return jsonify({'error': f'Não tem {qty}x {item_name} na bolsa'}), 400

    if sum(i.get('qty', 1) for i in pc_items) + qty > 10000:
        return jsonify({'error': 'PC de itens cheio! (limite 10.000)'}), 400

    bag_item['qty'] = bag_item.get('qty', qty) - qty
    if bag_item['qty'] <= 0:
        bag.remove(bag_item)

    pc_existing = next((b for b in pc_items if b.get('name', '').lower() == item_name.lower()), None)
    if pc_existing:
        pc_existing['qty'] = pc_existing.get('qty', 1) + qty
    else:
        pc_items.append({'name': bag_item.get('name', item_name), 'qty': qty, 'description': bag_item.get('description', '')})

    trainer['bag'] = bag
    trainer['pc_items'] = pc_items
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'bag': bag, 'pc_items': pc_items})

@app.route('/player/pc/items/withdraw', methods=['POST'])
@login_required
def pc_withdraw_item():
    """Move item(s) from PC storage to bag."""
    data = request.json or {}
    item_name = (data.get('item_name') or '').strip()
    qty = _int_arg(data, 'qty', 1, lo=1)
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    bag = trainer.get('bag', [])
    pc_items = trainer.get('pc_items', [])

    pc_item = next((b for b in pc_items if b.get('name', '').lower() == item_name.lower()), None)
    if not pc_item or pc_item.get('qty', 0) < qty:
        return jsonify({'error': f'Não tem {qty}x {item_name} no PC'}), 400

    pc_item['qty'] = pc_item.get('qty', qty) - qty
    if pc_item['qty'] <= 0:
        pc_items.remove(pc_item)

    bag_existing = next((b for b in bag if isinstance(b, dict) and b.get('name', '').lower() == item_name.lower()), None)
    if bag_existing:
        bag_existing['qty'] = bag_existing.get('qty', 1) + qty
    else:
        bag.append({'name': pc_item.get('name', item_name), 'qty': qty, 'description': pc_item.get('description', '')})

    trainer['bag'] = bag
    trainer['pc_items'] = pc_items
    users[current_user.id]['trainer_data'] = trainer
    save_users(users)
    return jsonify({'ok': True, 'bag': bag, 'pc_items': pc_items})

@app.route('/api/items')
@login_required
def api_items_list():
    """List available item sprites for the bag system."""
    items_dir = os.path.join('static', 'img', 'items')
    if not os.path.exists(items_dir):
        return jsonify([])
    items = []
    for f in os.listdir(items_dir):
        if f.endswith('.png') and not f.startswith('Bag_'):
            name = f.replace('.png', '').replace('-', ' ').title()
            items.append({'name': name, 'file': f})
    items.sort(key=lambda x: x['name'])
    return jsonify(items)

@app.route('/api/status-effects')
@login_required
def api_status_effects():
    """Get status effects data for the battle system."""
    return jsonify({
        'conditions': {k: {'name': v['name'], 'icon': v['icon'], 'color': v['color'], 'description': v['description']} 
                       for k, v in effects.STATUS_CONDITIONS.items()},
        'move_effects': {k: {'status': v['status'], 'chance': v.get('chance', None), 'on': v['on']}
                         for k, v in effects.MOVE_STATUS_EFFECTS.items()}
    })


@app.route('/api/abilities')
@login_required
def api_abilities():
    """Descrições de TODAS as habilidades conhecidas (para a ficha)."""
    return jsonify({'descriptions': ab.ABILITY_DESCRIPTIONS})

@app.route('/api/pokemon/stats', methods=['POST'])
@login_required
def api_pokemon_scaled_stats():
    """Calculate Pokemon stats at a specific level."""
    data = request.json
    pokemon_number = data.get('number')
    level = _int_arg(data, 'level', 1, lo=1, hi=100)
    
    nature = data.get('nature', '')
    name   = data.get('name', '')

    base_pokemon = POKEMON_BY_NUMBER.get(pokemon_number)
    if not base_pokemon and name:
        base_pokemon = POKEMON_BY_NAME.get(name.lower())
    if not base_pokemon:
        return jsonify({'error': 'Pokemon not found'}), 404

    # Shiny: +35% nos atributos base antes do escalonamento
    training = data.get('training') if isinstance(data.get('training'), dict) else None
    stats = scaling.calculate_pokemon_stats(base_pokemon, level, nature or None,
                                            is_shiny=bool(data.get('is_shiny')),
                                            training=training)

    # Stats de HISTÓRIA (encontro manual do mestre): porcentagem por stat
    # aplicada DEPOIS do escalonamento — boss com 300% de HP, lendário
    # enfraquecido a 50% etc. Clamp 10%-500%. SÓ o mestre pode usar (o
    # endpoint é stateless e não vaza para captura, mas por higiene um
    # jogador não deveria nem inflar a própria pré-visualização).
    raw_mods = data.get('stat_mods') if current_user.role == 'master' else None
    if isinstance(raw_mods, dict) and raw_mods:
        applied = {}
        for k, pct in raw_mods.items():
            try:
                pct = max(10, min(500, int(pct)))
            except (TypeError, ValueError):
                continue
            if pct == 100:
                continue
            kk = str(k).upper()
            if kk == 'HP':
                stats['maxHp'] = max(1, stats['maxHp'] * pct // 100)
                stats['hp'] = stats['maxHp']
                if 'HP' in stats.get('stats', {}):
                    stats['stats']['HP'] = max(1, stats['stats']['HP'] * pct // 100)
            elif kk in stats.get('stats', {}):
                stats['stats'][kk] = max(1, stats['stats'][kk] * pct // 100)
            else:
                continue
            applied[kk] = pct
        if applied:
            stats['stat_mods'] = applied
    stats['growth_rate'] = scaling.get_growth_rate(base_pokemon)
    stats['xp_to_next'] = scaling.xp_to_next_level(level, stats['growth_rate'])
    # Include which stat was boosted/lowered for UI display
    nature_mods = scaling.NATURE_MODIFIERS.get(nature, {})
    stats['nature_boost']  = next((s for s, m in nature_mods.items() if m > 1), None)
    stats['nature_lower']  = next((s for s, m in nature_mods.items() if m < 1), None)
    return jsonify(stats)

@app.route('/api/pokemon/battle-xp', methods=['POST'])
@login_required
def api_battle_xp():
    """Calculate XP reward for a battle result.
    Formula: loser_level x multiplier (2=wild, 3=official, 4=street, 5=gym)"""
    data = request.json
    winner_level = int(data.get('winner_level', 1))
    loser_level = int(data.get('loser_level', 1))
    battle_type = data.get('battle_type', 'wild')  # wild, official, street, gym_leader
    
    xp = scaling.battle_xp_reward(winner_level, loser_level, battle_type)
    xp_to_next = scaling.xp_to_next_level(winner_level)
    return jsonify({'xp_gained': xp, 'xp_to_next': xp_to_next})

@app.route('/api/pokemon/level-check', methods=['POST'])
@login_required  
def api_level_check():
    """Check if trainer can control a Pokemon at given level."""
    data = request.json
    trainer_level = int(data.get('trainer_level', 1))
    pokemon_level = int(data.get('pokemon_level', 1))
    
    can_control = scaling.can_control_pokemon(trainer_level, pokemon_level)
    max_level = scaling.max_pokemon_level(trainer_level)
    return jsonify({
        'can_control': can_control,
        'max_pokemon_level': max_level,
        'trainer_level': trainer_level
    })

@app.route('/api/pokemon/damage-dice', methods=['POST'])
@login_required
def api_damage_dice():
    """Get scaled damage dice for a move at a Pokemon level."""
    data = request.json
    base_damage = data.get('base_damage', '1d6')
    level = _int_arg(data, 'level', 1, lo=1, hi=100)
    higher_levels = data.get('higher_levels', '')
    
    scaled = scaling.get_scaled_damage_dice(base_damage, level, higher_levels)
    return jsonify({'scaled_dice': scaled, 'base_dice': base_damage, 'level': level})

@app.route('/api/check-status', methods=['POST'])
@login_required
def api_check_status():
    """Check if a move inflicts status and process turn-start effects.
    Used by the battle frontend for real-time status processing."""
    data = request.json
    action = data.get('action')  # 'check_hit' or 'turn_start'
    
    if action == 'check_hit':
        move_name = data.get('move_name', '')
        attack_roll = int(data.get('attack_roll', 10))
        damage_dealt = int(data.get('damage', 0))
        status_key, inflicted = effects.check_status_on_hit(move_name, attack_roll, damage_dealt)
        if inflicted:
            condition = effects.STATUS_CONDITIONS.get(status_key, {})
            return jsonify({
                'inflicted': True,
                'status': status_key,
                'name': condition.get('name', ''),
                'icon': condition.get('icon', ''),
                'description': condition.get('description', '')
            })
        return jsonify({'inflicted': False})
    
    elif action == 'turn_start':
        pokemon_status = data.get('pokemon_status')  # {condition: 'badly_poisoned', turns_active: 2}
        max_hp = int(data.get('max_hp', 20))
        ability = (data.get('ability', '') or '').strip().lower()

        can_act, damage, messages, removed = effects.process_turn_start(pokemon_status, max_hp)

        # Passive ability overrides
        passive = ab.get_passive(ability) if ability else None
        ability_msgs = []

        if passive == 'no_indirect' and damage > 0:
            damage = 0
            ability_msgs.append(f'✨ Magia Guarda: dano de status bloqueado!')

        elif passive == 'heal_poison' and pokemon_status and pokemon_status.get('condition') == 'badly_poisoned':
            # Instead of taking damage, heal that amount
            heal = damage
            damage = -heal  # negative = heal signal
            ability_msgs.append(f'💚 Cura Venenosa: recuperou {heal} HP do veneno!')

        elif passive == 'speed_up_turn':
            ability_msgs.append('⚡ Impulso: SPE aumentou!')


        if pokemon_status and not removed:
            # Shed Skin: 33% chance to cure status
            if passive == 'shed_skin_passive' or ability == 'shed skin':
                import random as _r
                if _r.random() < 0.33:
                    removed = True
                    ability_msgs.append('🐍 Muda de Pele: status curado!')

        if ability_msgs:
            messages = messages + ability_msgs

        return jsonify({
            'can_act': can_act,
            'damage': damage,
            'messages': messages,
            'status_removed': removed,
            'turns_active': pokemon_status.get('turns_active', 1) if pokemon_status else 1,
            'ability_messages': ability_msgs,
        })
    
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/process-status-move', methods=['POST'])
@login_required
def api_process_status_move():
    """Process a status move - auto-detects effect from move description.
    Handles ALL status moves by parsing their descriptions."""
    data = request.json
    move_name = data.get('move_name', '')
    attacker_stats = data.get('attacker_stats', {})
    target_stats = data.get('target_stats', {})
    side = data.get('side', 'player')   # 'player' | 'wild' (quem usa o move)

    # Get move data from database
    move_data = MOVES_DB.get(move_name) or MOVES_BY_NAME.get(move_name.lower())
    if not move_data:
        return jsonify({'success': False, 'message': f'Move {move_name} não encontrado'})

    # PREVIEW puro (mutate=False): calcula o efeito para o cliente exibir, mas
    # NÃO muta o estado nem persiste. A aplicação autoritativa (recarga, cura,
    # status, self_damage) acontece só no handler de socket `battle_action`
    # (senão a ação era processada 2× — cooldowns caíam em dobro). O _v3 real
    # entra só para o preview da recarga refletir o cooldown atual.
    game_state = get_game_state()
    encounter = (game_state.get('active_encounters') or {}).get(str(current_user.id))
    side_poke = None
    if encounter:
        side_poke = (encounter.get('pokemon') if side == 'wild'
                     else encounter.get('player_pokemon'))
    if isinstance(side_poke, dict):
        attacker_stats = dict(attacker_stats, _v3=_v3_side_state(side_poke),
                              types=side_poke.get('types'),
                              ability=side_poke.get('ability'))   # Rest × Insomnia
    result = effects.process_status_move(move_data, attacker_stats, target_stats,
                                         mutate=False)
    return jsonify(result)

@app.route('/player/pokedex/register', methods=['POST'])
@login_required
def register_pokedex():
    """Register a Pokemon in the player's Pokedex and award XP."""
    data = request.json
    pokemon_number = data.get('pokemon_number')
    # Só números de Pokémon REAIS dão XP — senão o jogador farmava XP infinito
    # registrando números inventados (cada um "novo" valia +10 XP).
    try:
        pokemon_number = int(pokemon_number)
    except (TypeError, ValueError):
        return jsonify({'error': 'Número inválido'}), 400
    if pokemon_number not in POKEMON_BY_NUMBER:
        return jsonify({'error': 'Pokémon inexistente'}), 400

    users = get_users()
    if current_user.id in users:
        trainer = users[current_user.id]['trainer_data']
        pokedex_seen = trainer.get('pokedex_seen', [])

        if pokemon_number not in pokedex_seen:
            pokedex_seen.append(pokemon_number)
            trainer['pokedex_seen'] = pokedex_seen
            
            # Award 10 XP per new Pokemon registered
            xp_reward = 10
            lv_info = _apply_xp(trainer, xp_reward)

            users[current_user.id]['trainer_data'] = trainer
            save_users(users)

            socketio.emit('xp_update', {
                'player_id': current_user.id,
                'xp': trainer['xp'],
                'level': trainer['level'],
                'xp_to_next': trainer['xp_to_next'],
                'leveled_up': lv_info['leveled_up']
            }, room=current_user.id)
            
            return jsonify({'success': True, 'xp_gained': xp_reward, 'total_seen': len(pokedex_seen)})
        
        return jsonify({'success': True, 'already_registered': True, 'total_seen': len(pokedex_seen)})
    return jsonify({'error': 'User not found'}), 404

# ============================================================
# SOCKET.IO EVENTS
# ============================================================
# Auto-mode agora é POR MESA (guardado no game_state), não global —
# um mestre não afeta mais as batalhas das outras mesas.
def _wild_auto_mode(state=None):
    st = state if state is not None else get_game_state()
    return st.get('wild_auto_mode', True)

@socketio.on('set_auto_mode')
def handle_set_auto_mode(data):
    if current_user.is_authenticated and current_user.role == 'master':
        state = get_game_state()
        state['wild_auto_mode'] = bool(data.get('enabled', True))
        save_game_state(state)
        # Avisa a mesa inteira — vale imediatamente em batalhas em andamento
        payload = {'enabled': state['wild_auto_mode']}
        emit('auto_mode_changed', payload, room=f'players_{_tid()}')
        emit('auto_mode_changed', payload, room=f'master_{_tid()}')
        print(f"[AUTO MODE] mesa={_tid()} {'ON' if state['wild_auto_mode'] else 'OFF'}")

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        tid = _tid()
        join_room(current_user.id)
        if current_user.role == 'master':
            join_room(f'master_{tid}')
        else:
            join_room(f'players_{tid}')
        print(f"[CONNECTED] {current_user.username} ({current_user.role}) table={tid}")

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        leave_room(current_user.id)
        print(f"[DISCONNECTED] {current_user.username}")

@socketio.on('start_encounter')
def handle_encounter(data):
    """Player starts a wild encounter - notify master with full battle data."""
    if current_user.is_authenticated:
        # GATE: o jogador só inicia um encontro que o MESTRE liberou (por
        # espécie). Sem isto, dava para emitir start_encounter à vontade,
        # ignorando o teto de caçadas e a aprovação do mestre.
        _gs = get_game_state()
        _pend = (_gs.get('pending_encounters') or {})
        _granted = _pend.get(str(current_user.id))
        _inc_num = (data.get('pokemon') or {}).get('number')
        try:
            _inc_num = int(_inc_num)
        except (TypeError, ValueError):
            _inc_num = None
        if _granted is None or _inc_num != int(_granted):
            emit('encounter_denied', {
                'message': 'Aguarde o Mestre liberar um encontro (Caçada Aleatória).'
            }, room=str(current_user.id))
            return
        # consome o vale (um encontro por liberação)
        _pend.pop(str(current_user.id), None)
        _gs['pending_encounters'] = _pend
        save_game_state(_gs)

        users = get_users()
        trainer = users.get(current_user.id, {}).get('trainer_data', {})
        team = trainer.get('team', [])

        # Find the player's active pokemon
        player_pokemon_idx = data.get('player_pokemon_idx', 0)
        if _mig(team):
            users[current_user.id]['trainer_data']['team'] = team
            save_users(users)
        _stamp_tatica(team, trainer)
        _v3_new_battle(team)
        player_pokemon = team[player_pokemon_idx] if player_pokemon_idx < len(team) else None

        # Pokémon desmaiado NÃO inicia batalha — devolve o vale de encontro
        # (a liberação do mestre não é queimada pela tentativa inválida).
        _hp0 = player_pokemon.get('currentHp') if player_pokemon else None
        if player_pokemon and isinstance(_hp0, (int, float)) and _hp0 <= 0:
            _gs2 = get_game_state()
            _gs2.setdefault('pending_encounters', {})[str(current_user.id)] = _granted
            save_game_state(_gs2)
            emit('encounter_denied', {
                'message': '💀 Pokémon desmaiado — cure ou escolha outro para iniciar o encontro.'
            }, room=str(current_user.id))
            return

        encounter_data = {
            'player_id': current_user.id,
            'player_name': current_user.username,
            'pokemon': data.get('pokemon'),
            'level': data.get('level'),
            'is_shiny': data.get('is_shiny', False),
            'route_id': data.get('route_id'),
            'wild_moves': data.get('wild_moves', []),
            'player_pokemon': player_pokemon,
            'player_pokemon_idx': player_pokemon_idx if player_pokemon else None,
            'player_pokemon_name': data.get('player_pokemon'),
            'battle_state': {
                'turn': None,  # 'player' or 'wild'
                'round': 0,
                'wild_hp_current': data.get('pokemon', {}).get('hp', 20),
                'wild_hp_max': data.get('pokemon', {}).get('hp', 20),
                'player_hp_current': player_pokemon.get('currentHp', 20) if player_pokemon else 20,
                'player_hp_max': player_pokemon.get('maxHp', 20) if player_pokemon else 20,
                'wild_status': None,
                'player_status': None,
                'wild_defense_mode': int((data.get('pokemon') or {}).get('defense_mode') or 1),
                'player_defense_mode': 1,
                'initiative_rolled': False
            }
        }
        # Save to game state — use str key so JSON roundtrip doesn't change it
        pid = str(current_user.id)
        encounter_data['player_id'] = pid
        game_state = get_game_state()
        game_state['active_encounters'][pid] = encounter_data
        save_game_state(game_state)

        # Notify master
        emit('encounter_started', encounter_data, room=f'master_{_tid()}')
        _spectate_wild(pid, encounter_data, last='⚔️ Encontro iniciado!')

        # Auto-roll initiative if AUTO mode is ON (por mesa)
        if _wild_auto_mode(game_state):
            _auto_roll_initiative(pid, game_state)

@socketio.on('roll_initiative')
def handle_initiative(data):
    """Roll initiative for battle - determines who goes first.
    Can be triggered by master OR player (auto mode)."""
    if not current_user.is_authenticated:
        return
    
    # Determine player_id: if master triggers, use data; if player triggers, use own id
    if current_user.role == 'master':
        player_id = str(data.get('player_id', ''))
    else:
        player_id = str(current_user.id)

    if not player_id:
        player_id = str(current_user.id)

    game_state = get_game_state()
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter:
        return
    
    # Don't re-roll if already rolled
    if encounter.get('battle_state', {}).get('initiative_rolled'):
        return
    
    wild_pokemon = encounter['pokemon']
    player_pokemon = encounter.get('player_pokemon') or {}
    
    # Iniciativa v3.1: d100 + SPE_eff + Tática×5; upset ≥96 vs ≤5; desempate por SPE
    wild_spe = effects.effective_stat(wild_pokemon, 'SPE')
    player_spe = effects.effective_stat(player_pokemon, 'SPE') if player_pokemon else 10
    player_extra = int((player_pokemon or {}).get('trainer_init_bonus') or 0)
    wild_mod = bm_core.initiative_bonus(wild_spe)
    # mod exibido = o que soma de verdade no total (Tática entra ×INIT_EXTRA_STEP)
    player_mod = (bm_core.initiative_bonus(player_spe)
                  + bm_core.INIT_EXTRA_STEP * player_extra)

    nat_player = random.randint(1, 100)
    nat_wild = random.randint(1, 100)
    winner, player_init, wild_init, init_upset = bm_core.initiative_winner(
        nat_player, nat_wild, player_spe, wild_spe, extra_a=player_extra)

    first_turn = 'player' if winner == 'a' else 'wild'
    
    encounter['battle_state']['initiative_rolled'] = True
    encounter['battle_state']['turn'] = first_turn
    encounter['battle_state']['round'] = 1
    encounter['battle_state']['wild_initiative'] = wild_init
    encounter['battle_state']['player_initiative'] = player_init
    
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    
    # Check on-enter abilities for both combatants
    on_enter_msgs = []
    wild_ability = wild_pokemon.get('ability', '') or ''
    player_ability = player_pokemon.get('ability', '') or ''
    wild_name = wild_pokemon.get('name', 'Selvagem')
    player_name = player_pokemon.get('nickname') or player_pokemon.get('name', 'Pokémon')

    for ability_str, poke_name in [(wild_ability, wild_name), (player_ability, player_name)]:
        entry = ab.check_on_enter(ability_str, poke_name)
        if entry:
            on_enter_msgs.append(entry['message'])
            # Apply Intimidate: lower opponent ATK (stored in battle_state for client)
            if entry.get('stat') == 'ATK' and entry.get('mod', 0) < 0:
                if poke_name == wild_name:
                    encounter['battle_state']['player_atk_mod'] = encounter['battle_state'].get('player_atk_mod', 0) + entry['mod']
                else:
                    encounter['battle_state']['wild_atk_mod'] = encounter['battle_state'].get('wild_atk_mod', 0) + entry['mod']
            # Weather abilities set the field (Drought/Drizzle/Sand Stream...)
            if entry.get('weather'):
                encounter['battle_state']['weather'] = entry['weather']
                _field_apply(encounter['battle_state'], 'weather',
                             entry['weather'], bm_core.V3_FIELD_ROUNDS)

    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)

    result = {
        'player_id': player_id,
        'wild_initiative': wild_init,
        'wild_mod': wild_mod,
        'player_initiative': player_init,
        'player_mod': player_mod,
        'first_turn': first_turn,
        'upset': init_upset,
        'on_enter_abilities': on_enter_msgs,
        'weather': encounter['battle_state'].get('weather'),
        'wild_auto': _wild_auto_mode(game_state),
    }

    emit('initiative_result', result, room=f'master_{_tid()}')
    emit('initiative_result', result, room=player_id)

def _ai_defense_mode(poke):
    """Melhor postura líquida p/ IA: maior média dos denominadores ÷ taxa."""
    stats = (poke.get('stats') or {}) if isinstance(poke, dict) else {}
    best_mode, best_net = 1, 0.0
    for mode, info in bm_core.DEFENSE_MODES.items():
        phys = stats.get(info['physical'], 10) or 10
        spec = stats.get(info['special'], 10) or 10
        net = ((phys + spec) / 2.0) / info['tax']
        if net > best_net:
            best_net, best_mode = net, mode
    return best_mode


@socketio.on('set_defense_mode')
def handle_set_defense_mode(data):
    """Troca a POSTURA DEFENSIVA do Pokémon ativo (não gasta a ação).

    Só no PRÓPRIO turno; persiste até trocar de novo; reseta na troca de
    Pokémon. payload: {battle_type: 'wild'|'pvp'|'group', battle_id?, mode: 1|2|3}
    """
    if not current_user.is_authenticated:
        return
    mode = int(data.get('mode') or 1)
    if mode not in bm_core.DEFENSE_MODES:
        return
    btype = data.get('battle_type', 'wild')
    label = bm_core.DEFENSE_MODES[mode]['label']

    if btype == 'wild':
        game_state = get_game_state()
        pid = str(current_user.id)
        encounter = game_state.get('active_encounters', {}).get(pid)
        if not encounter:
            return
        bs = encounter.get('battle_state') or {}
        if bs.get('turn') and bs.get('turn') != 'player':
            emit('pvp_error', {'message': 'Só pode mudar a postura no seu turno!'})
            return
        ppoke = encounter.get('player_pokemon') or {}
        ppoke['defense_mode'] = mode
        bs['player_defense_mode'] = mode
        encounter['battle_state'] = bs
        game_state['active_encounters'][pid] = encounter
        save_game_state(game_state)
        payload = {'side': 'player', 'mode': mode, 'label': label}
        emit('defense_mode_set', payload, room=pid)
        emit('defense_mode_set', dict(payload, player_id=pid), room=f'master_{_tid()}')

    elif btype == 'pvp':
        battle = ACTIVE_PVP.get(data.get('battle_id'))
        if not battle or battle['phase'] != 'battle':
            return
        player_key = _pvp_my_key(battle)
        if not player_key:
            return
        if battle['turn'] != player_key:
            emit('pvp_error', {'message': 'Só pode mudar a postura no seu turno!'})
            return
        side = battle[player_key]
        poke = side['team'][side['active_idx']]
        poke['defense_mode'] = mode
        battle['log'].append({'type': 'info',
                              'message': f"{poke.get('nickname') or poke.get('name','?')} assumiu a postura {label}!"})
        _broadcast_pvp_state(battle)

    elif btype == 'group':
        battle = ACTIVE_GROUP_BATTLES.get(data.get('battle_id'))
        if not battle or battle.get('phase') != 'active':
            return
        cur = gb.current_combatant(battle)
        if not cur or cur.get('player_id') != str(current_user.id):
            emit('pvp_error', {'message': 'Só pode mudar a postura no seu turno!'})
            return
        cur['pokemon']['defense_mode'] = mode
        battle['log'].append({'type': 'info',
                              'message': f"{cur['name']} assumiu a postura {label}!"})
        _group_broadcast(battle)


@socketio.on('battle_action')
def handle_battle_action(data):
    """Handle a battle action (attack, status move, etc.)."""
    if not current_user.is_authenticated:
        return
    action_by = data.get('action_by')  # 'player' or 'master' (for wild pokemon)
    # Security: non-masters can only act for themselves. No modo AUTO o
    # navegador do JOGADOR conduz o turno do selvagem (action_by='master')
    # — permitido, mas o dano é RECALCULADO no servidor abaixo, então o
    # cliente não consegue mandar o selvagem bater de graça (dano 0).
    if current_user.role != 'master':
        player_id = str(current_user.id)
    else:
        player_id = str(data.get('player_id', current_user.id))
        if not _player_in_master_table(player_id, get_users(), _tid()):
            return
    # Guard de re-entrância (duplo-clique / duas abas): sob gevent o check+add é
    # atômico (sem yield), então a 2ª ação concorrente do MESMO encontro é
    # descartada — fecha o lost-update (dois battle_action lendo o mesmo turno
    # e sobrescrevendo o HP/turno um do outro).
    if player_id in _BATTLE_BUSY:
        return
    _BATTLE_BUSY.add(player_id)
    try:
        action_type = data.get('action_type')  # 'attack', 'status', 'item'
        move_name = data.get('move_name', '')
        move_type = data.get('move_type', '')   # e.g. 'fire', 'ground'
        damage = data.get('damage', 0)
        heal = data.get('heal', 0)
        status_effect = data.get('status_effect', None)
        message = data.get('message', '')
        # Pre-turn status damage (applied before this action, doesn't switch turn)
        wild_status_damage = data.get('wild_status_damage', 0)
        player_status_damage = data.get('player_status_damage', 0)
        
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        battle_state = encounter['battle_state']

        # Batalha iniciada ANTES da migração v2 (stats na escala antiga):
        # encerra com aviso — snapshot v1 não é migrável com segurança.
        ppk = encounter.get('player_pokemon') or {}
        if ppk and ppk.get('sv') != migrations.STATS_VERSION:
            del game_state['active_encounters'][player_id]
            save_game_state(game_state)
            emit('battle_ended_by_update', {
                'message': '⚙️ Batalha reiniciada pela atualização do sistema de stats. Inicie um novo encontro.'
            }, room=player_id)
            return

        # Validate turn ownership — ignore out-of-turn actions to prevent race conditions.
        # 'apply_status' events never switch turn so they are always allowed.
        if action_type != 'apply_status':
            expected = 'player' if action_by == 'player' else 'wild'
            if battle_state.get('turn') and battle_state['turn'] != expected:
                return

        # Pokémon desmaiado NÃO age (HP ≤ 0): fecha o "último golpe" depois
        # de ser zerado (o cliente às vezes ainda mostrava o turno antigo).
        if action_type in ('attack', 'status'):
            if action_by == 'player' and int(battle_state.get('player_hp_current') or 0) <= 0:
                emit('action_blocked', {
                    'message': '💀 Seu Pokémon desmaiou — troque de Pokémon ou encerre.'})
                return
            if action_by == 'master' and int(battle_state.get('wild_hp_current') or 0) <= 0:
                return

        # Modo MANUAL (auto OFF): o turno do selvagem pertence ao MESTRE.
        # O cliente do jogador dispara o auto-attack por conta própria — aqui
        # o servidor descarta essa ação para o mestre poder conduzir.
        if (action_type != 'apply_status' and action_by == 'master'
                and current_user.role != 'master'
                and not _wild_auto_mode(game_state)):
            emit('action_blocked', {
                'manual_wild': True,
                'message': '🎭 Modo manual: aguarde o Mestre jogar o turno do selvagem.'})
            return

        action_log = None
        server_calc = None  # populated when server recalculates attack

        # ITEM X (X Attack/Defense/Speed/Sp.Atk...): aplica um ESTÁGIO real no
        # Pokémon do jogador, server-autoritativo. Consome o item da bolsa no
        # servidor (a bolsa do cliente não é fonte de verdade) e passa o turno.
        if action_type == 'use_item' and action_by == 'player':
            _xmap = {'x attack': ('ATK', '⚔️ Ataque'), 'x defense': ('DEF', '🛡️ Defesa'),
                     'x speed': ('SPE', '💨 Velocidade'), 'x sp. atk': ('SPA', '✨ Atq. Esp.'),
                     'x sp. def': ('SPD', '🔮 Def. Esp.'), 'x accuracy': ('attack_roll', '🎯 Precisão')}
            _iname = str(data.get('item_name') or '')
            _xk = _xmap.get(_iname.lower())
            _users_x = get_users()
            _bag_x = _users_x.get(current_user.id, {}).get('trainer_data', {}).get('bag', [])
            _slot = next((it for it in _bag_x
                          if str(it.get('name', '')).lower() == _iname.lower()
                          and int(it.get('qty', 0)) > 0), None)
            if not _xk or not _slot:
                emit('action_blocked', {'message': f'{_iname} indisponível.'})
                return
            _slot['qty'] = int(_slot['qty']) - 1
            _users_x[current_user.id]['trainer_data']['bag'] = [
                it for it in _bag_x if int(it.get('qty', 0)) > 0]
            save_users(_users_x)
            ppoke_x = encounter.get('player_pokemon') or {}
            effects.apply_stat_changes(ppoke_x, {_xk[0]: 1})
            battle_state['player_stat_stages'] = ppoke_x.get('stat_stages')
            action_log = f'🧪 <strong>{_iname}</strong> — {_xk[1]} +1 estágio!'
            message = action_log
            server_calc = {'is_item': True, 'log': action_log}
            # cai no fluxo comum: troca de turno + broadcast abaixo

        # Efeitos de status são DERIVADOS no servidor (não confiar no payload):
        # zera heal/status/reset_stages/stage_op forjados; o motor abaixo
        # preenche os valores reais. (Fecha cura/status/Haze forjados.)
        srv_reset_stages = False
        srv_stage_op = None
        if action_type == 'status' and action_by == 'player':
            heal = 0
            status_effect = None
            damage = 0   # dano de status vem só do motor (fixed_damage), nunca do payload

        # Server-side damage calculation for player attacks — prevents client from
        # reporting arbitrary damage values against wild Pokémon. Move de status
        # emitido direto (action_type='status') também passa pelo motor.
        if action_type in ('attack', 'status') and action_by == 'player' and move_name:
            # v3: o servidor rola o d100 (rolagem do cliente não é aceita —
            # senão dava para mandar sempre 1 e nunca errar)
            server_calc = _calc_player_attack(encounter, move_name, None)
            if server_calc.get('blocked'):
                ppoke_f = encounter.get('player_pokemon') or {}
                if _v3_sem_opcao(ppoke_f):
                    # RODADA DE FÔLEGO: nada disponível — descansa, turno passa
                    message = action_log = _v3_folego(ppoke_f)
                    damage, heal, status_effect = 0, 0, None
                    server_calc = {'hit': False, 'is_status': False,
                                   'damage': 0, 'log': message}
                else:
                    # golpe em cooldown: NÃO consome o turno — escolha outro
                    emit('action_blocked', {'message': server_calc.get('message'),
                                            'move_name': move_name,
                                            'cooldown_left': server_calc.get('cooldown_left')})
                    return
            damage = server_calc.get('damage', 0)
            move_type = server_calc.get('move_type_en', move_type)
            # Backstop: move de status nunca causa dano no selvagem. Processa
            # o efeito pelo motor e aplica no selvagem (sem dano).
            if server_calc.get('is_status'):
                damage = 0
                move_data = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name)
                ppoke = encounter.get('player_pokemon') or {}
                wpoke = encounter.get('pokemon') or {}
                sres = effects.process_status_move(
                    move_data or {'name': move_name},
                    dict(ppoke.get('stats', {}), level=ppoke.get('level', 1),
                         proficiency=ppoke.get('proficiency', _prof_for_level(ppoke.get('level', 1))),
                         maxHp=ppoke.get('maxHp', 20), types=ppoke.get('types'),
                         ability=ppoke.get('ability'),   # Rest × Insomnia
                         _v3=_v3_side_state(ppoke)),   # Protect: corrente/flag no dict real
                    dict(wpoke.get('stats', {}), level=wpoke.get('level', encounter.get('level', 5)),
                         ATK_eff=effects.effective_stat(wpoke, 'ATK')))
                # v3: cura instantânea em recarga — não consome o turno
                # (a menos que NADA esteja disponível → rodada de fôlego)
                if sres.get('blocked'):
                    ppoke_f = encounter.get('player_pokemon') or {}
                    if _v3_sem_opcao(ppoke_f):
                        sres = {'success': True, 'effect_type': 'utility',
                                'message': _v3_folego(ppoke_f)}
                    else:
                        emit('action_blocked', {'message': sres.get('message'),
                                                'move_name': move_name,
                                                'cooldown_left': sres.get('cooldown_left')})
                        return
                # custo pago pelo próprio usuário (Curse fantasma: ⌊HPmáx/2⌋)
                if sres.get('self_damage'):
                    battle_state['player_hp_current'] = max(
                        1, battle_state['player_hp_current'] - int(sres['self_damage']))
                action_log = sres.get('message', '')
                message = sres.get('message', message)
                # Dano fixo (Night Shade/Seismic Toss/Final Gambit/Pain Split):
                # o servidor DERIVA o dano (o payload não é mais confiado) e o
                # fluxo normal abaixo aplica no selvagem.
                if sres.get('effect_type') in ('fixed_damage', 'pain_split') and sres.get('damage'):
                    damage = int(sres['damage'])
                # F5: clima/terreno de campo (Rain Dance, Grassy Terrain...)
                if sres.get('effect_type') == 'field':
                    _field_apply(battle_state, sres.get('field_kind'),
                                 sres.get('field_value'), sres.get('duration'))
                if (sres.get('status_applied') and not status_effect
                        and not battle_state.get('wild_status')
                        and not effects.type_blocks_status(
                            wpoke.get('types'), sres['status_applied'])):
                    status_effect = {'condition': sres['status_applied'], 'turns_active': 0}
                if sres.get('heal'):
                    battle_state['player_hp_current'] = min(
                        battle_state['player_hp_max'],
                        battle_state['player_hp_current'] + sres['heal'])
                # Rest: o PRÓPRIO usuário adormece (troca o status atual)
                if sres.get('self_status'):
                    battle_state['player_status'] = {
                        'condition': sres['self_status'], 'turns_active': 0}
                # Stat stages: debuff no selvagem, buff no próprio Pokémon.
                # Aplicados nos dicts do encounter (persistem) e espelhados no
                # battle_state para o broadcast e o ataque selvagem no cliente.
                if sres.get('stat_changes'):
                    tgt = wpoke if sres.get('effect_type') == 'debuff' else ppoke
                    effects.apply_stat_changes(tgt, sres['stat_changes'])
                    battle_state['wild_stat_stages'] = wpoke.get('stat_stages')
                    battle_state['player_stat_stages'] = ppoke.get('stat_stages')
                # Haze / Psych Up etc. DERIVADOS do motor (não do payload)
                if sres.get('effect_type') == 'reset_stages':
                    srv_reset_stages = True
                elif sres.get('effect_type') == 'stage_op':
                    srv_stage_op = sres.get('op')
            elif not server_calc.get('hit', True):
                damage = 0
            # On-hit status (Ember→queimado, Thunderbolt→paralisado etc.)
            # rolado no servidor para valer também em batalhas selvagens.
            elif damage > 0 and not status_effect and not battle_state.get('wild_status'):
                skey, inflicted = effects.check_status_on_hit(
                    move_name, server_calc.get('attack_roll', 10), damage,
                    defender=encounter.get('pokemon'))
                if inflicted:
                    status_effect = {'condition': skey, 'turns_active': 0}
                    cond = effects.STATUS_CONDITIONS.get(skey, {})
                    server_calc['status_inflicted'] = skey
                    server_calc['log'] = (server_calc.get('log', '') +
                        f" {cond.get('icon','')} Selvagem ficou <strong>{cond.get('name', skey)}</strong>!")
            # F5: recoil (fere o usuário, nunca nocauteia) e dreno (cura)
            if server_calc.get('recoil'):
                battle_state['player_hp_current'] = max(
                    1, battle_state['player_hp_current'] - int(server_calc['recoil']))
            if server_calc.get('drain_heal'):
                battle_state['player_hp_current'] = min(
                    battle_state['player_hp_max'],
                    battle_state['player_hp_current'] + int(server_calc['drain_heal']))
            # Rampage (Outrage...): o próprio usuário fica confuso
            if server_calc.get('self_status') and not battle_state.get('player_status'):
                battle_state['player_status'] = {
                    'condition': server_calc['self_status'], 'turns_active': 0}
            # Explosion/Self-Destruct: o usuário desmaia
            if server_calc.get('self_ko'):
                battle_state['player_hp_current'] = 0

        # Turno do SELVAGEM: recalculado SEMPRE no servidor (motor v3) — tanto
        # no modo AUTO (cliente do jogador conduz) quanto no manual (mestre
        # escolhe o golpe). Cliente nenhum é autoridade sobre o dano.
        if action_type == 'attack' and action_by == 'master' and move_name:
            wild_calc = _calc_wild_attack(encounter, move_name, None)   # v3: servidor rola o d100
            if wild_calc.get('is_status') and current_user.role == 'master':
                # Mestre escolheu um golpe de STATUS do selvagem: processa no
                # motor (espelho do backstop do ataque do jogador acima).
                damage = 0
                move_data = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name)
                ppoke = encounter.get('player_pokemon') or {}
                wpoke = encounter.get('pokemon') or {}
                sres = effects.process_status_move(
                    move_data or {'name': move_name},
                    dict(wpoke.get('stats', {}), level=wpoke.get('level', encounter.get('level', 5)),
                         maxHp=battle_state.get('wild_hp_max', 20), types=wpoke.get('types'),
                         ability=wpoke.get('ability'),   # Rest × Insomnia
                         _v3=_v3_side_state(wpoke)),
                    dict(ppoke.get('stats', {}), level=ppoke.get('level', 1),
                         ATK_eff=effects.effective_stat(ppoke, 'ATK')))
                # v3: cura do selvagem em recarga — avisa o mestre, turno fica
                # (a menos que NADA esteja disponível → rodada de fôlego)
                if sres.get('blocked'):
                    if _v3_sem_opcao(wpoke, encounter.get('wild_moves')):
                        sres = {'success': True, 'effect_type': 'utility',
                                'message': _v3_folego(wpoke, wpoke.get('name', 'Selvagem'))}
                    else:
                        emit('action_blocked', {'message': sres.get('message'),
                                                'move_name': move_name,
                                                'cooldown_left': sres.get('cooldown_left')})
                        return
                # custo pago pelo próprio selvagem (Curse fantasma)
                if sres.get('self_damage'):
                    battle_state['wild_hp_current'] = max(
                        1, battle_state['wild_hp_current'] - int(sres['self_damage']))
                action_log = sres.get('message', '')
                message = sres.get('message', message)
                server_calc = {'is_status': True, 'log': action_log, 'message': message}
                if sres.get('effect_type') == 'field':
                    _field_apply(battle_state, sres.get('field_kind'),
                                 sres.get('field_value'), sres.get('duration'))
                if (sres.get('status_applied')
                        and not battle_state.get('player_status')
                        and not effects.type_blocks_status(
                            ppoke.get('types'), sres['status_applied'])):
                    battle_state['player_status'] = {
                        'condition': sres['status_applied'], 'turns_active': 0}
                if sres.get('heal'):
                    battle_state['wild_hp_current'] = min(
                        battle_state['wild_hp_max'],
                        battle_state['wild_hp_current'] + sres['heal'])
                # Rest: o PRÓPRIO selvagem adormece (troca o status atual)
                if sres.get('self_status'):
                    battle_state['wild_status'] = {
                        'condition': sres['self_status'], 'turns_active': 0}
                if sres.get('stat_changes'):
                    tgt = ppoke if sres.get('effect_type') == 'debuff' else wpoke
                    effects.apply_stat_changes(tgt, sres['stat_changes'])
                    battle_state['wild_stat_stages'] = wpoke.get('stat_stages')
                    battle_state['player_stat_stages'] = ppoke.get('stat_stages')
            elif not wild_calc.get('is_status'):
                damage = wild_calc.get('damage', 0)
                move_type = wild_calc.get('move_type_en', move_type)
                server_calc = wild_calc
                # F5: recoil/dreno do golpe do selvagem
                if wild_calc.get('recoil'):
                    battle_state['wild_hp_current'] = max(
                        1, battle_state['wild_hp_current'] - int(wild_calc['recoil']))
                if wild_calc.get('drain_heal'):
                    battle_state['wild_hp_current'] = min(
                        battle_state['wild_hp_max'],
                        battle_state['wild_hp_current'] + int(wild_calc['drain_heal']))
                if wild_calc.get('self_status') and not battle_state.get('wild_status'):
                    battle_state['wild_status'] = {
                        'condition': wild_calc['self_status'], 'turns_active': 0}
                if wild_calc.get('self_ko'):
                    battle_state['wild_hp_current'] = 0

        if server_calc:
            action_log = server_calc.get('log')
            message = server_calc.get('message', message)

        # Dano de status pré-turno (não conta como ação). O cliente manda o
        # valor, mas o servidor NÃO confia: só aplica se o alvo tem status e
        # clampa a no máx. 1/4 do HP máximo por tick (veneno/queimadura tickam
        # ~1/8-1/16) — sem isto o cliente mandava 9999 e one-shotava o selvagem.
        PERMADEATH_FLOOR = -30
        def _safe_status_dmg(raw, has_status, max_hp):
            if not has_status or raw <= 0:
                return 0
            return min(int(raw), max(1, int(max_hp or 20) // 4))
        wild_status_damage = _safe_status_dmg(
            wild_status_damage, battle_state.get('wild_status'), battle_state.get('wild_hp_max'))
        player_status_damage = _safe_status_dmg(
            player_status_damage, battle_state.get('player_status'), battle_state.get('player_hp_max'))
        if wild_status_damage > 0:
            battle_state['wild_hp_current'] = max(PERMADEATH_FLOOR, battle_state['wild_hp_current'] - wild_status_damage)
        if player_status_damage > 0:
            battle_state['player_hp_current'] = max(PERMADEATH_FLOOR, battle_state['player_hp_current'] - player_status_damage)

        # Check defender ability before applying damage
        ability_result = None
        if damage > 0 and move_type and action_type == 'attack':
            if action_by == 'player':
                # Player attacks wild — check wild's ability
                wild_ability = encounter.get('pokemon', {}).get('ability', '') or ''
                if wild_ability:
                    ability_result = ab.check_defender_ability(
                        wild_ability, move_type, damage,
                        battle_state['wild_hp_current'], battle_state['wild_hp_max']
                    )
                    if ability_result['triggered']:
                        damage = ability_result['modified_damage']
                        if ability_result['heal']:
                            battle_state['wild_hp_current'] = min(battle_state['wild_hp_max'], battle_state['wild_hp_current'] + ability_result['heal'])
            elif action_by == 'master':
                # Wild/NPC attacks player — check player pokemon's ability
                users = get_users()
                trainer = users.get(player_id, {}).get('trainer_data', {})
                team = trainer.get('team', [])
                player_poke = team[0] if team else {}
                player_ability = player_poke.get('ability', '') or ''
                if player_ability:
                    ability_result = ab.check_defender_ability(
                        player_ability, move_type, damage,
                        battle_state['player_hp_current'], battle_state['player_hp_max']
                    )
                    if ability_result['triggered']:
                        damage = ability_result['modified_damage']
                        if ability_result['heal']:
                            battle_state['player_hp_current'] = min(battle_state['player_hp_max'], battle_state['player_hp_current'] + ability_result['heal'])

        # Handle switch: HP do novo Pokémon vem do TIME REAL (servidor), nunca
        # do payload — senão o cliente forjava HP infinito na troca.
        if action_type == 'switch' and action_by == 'player':
            _sw_users = get_users()
            _sw_team = _sw_users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
            # Persiste o HP de batalha do Pokémon que SAI no time armazenado.
            # Durante a batalha selvagem o dano vive só no battle_state (o
            # currentHp do time nunca é decrementado aqui), então sem isto a
            # troca lia o currentHp ARMAZENADO — cheio — e curava de graça ao
            # voltar (pivotar out→in restaurava HP sem item). Espelha a
            # mecânica real: o HP persiste através da troca.
            _out = encounter.get('player_pokemon') or {}
            _out_idx = encounter.get('player_pokemon_idx')
            if not (isinstance(_out_idx, int) and 0 <= _out_idx < len(_sw_team)):
                _ouid = _out.get('uid')
                _out_idx = next((i for i, pp in enumerate(_sw_team)
                                 if isinstance(pp, dict) and _ouid and pp.get('uid') == _ouid), None)
            if isinstance(_out_idx, int) and 0 <= _out_idx < len(_sw_team) \
                    and isinstance(_sw_team[_out_idx], dict):
                _out_hp = battle_state.get('player_hp_current')
                if isinstance(_out_hp, (int, float)):
                    _out_max = int(_sw_team[_out_idx].get('maxHp') or 20)
                    _sw_team[_out_idx]['currentHp'] = max(0, min(_out_max, int(_out_hp)))
            try:
                _sw_idx = int(data.get('new_index'))
            except (TypeError, ValueError):
                _sw_idx = -1
            _sw_poke = _sw_team[_sw_idx] if 0 <= _sw_idx < len(_sw_team) else None
            if isinstance(_sw_poke, dict):
                new_max_hp = int(_sw_poke.get('maxHp') or 20)
                cur = _sw_poke.get('currentHp')
                new_hp = int(cur) if isinstance(cur, (int, float)) else new_max_hp
                new_hp = max(0, min(new_max_hp, new_hp))
                if new_hp > 0:
                    battle_state['player_hp_current'] = new_hp
                    battle_state['player_hp_max'] = new_max_hp
                    encounter['player_pokemon'] = _sw_poke
                    encounter['player_pokemon_idx'] = _sw_idx
            # grava o HP do Pokémon que saiu (e a troca de ativo) no save real
            _sw_users[current_user.id]['trainer_data']['team'] = _sw_team
            save_users(_sw_users)
            # trocar de pokémon zera os buffs/debuffs acumulados do lado do jogador
            ppoke_sw = encounter.get('player_pokemon')
            # sair de campo remove semente/prisão (Leech Seed/Bind)
            if (battle_state.get('player_status') or {}).get('condition') in ('seeded', 'trapped'):
                battle_state['player_status'] = None
            if isinstance(ppoke_sw, dict):
                effects.reset_stat_stages(ppoke_sw)
                ppoke_sw['defense_mode'] = 1   # postura reseta na troca
            battle_state['player_stat_stages'] = None
            battle_state['player_defense_mode'] = 1

        # Apply damage — allow negative down to -30 for permadeath detection
        PERMADEATH_FLOOR = -30
        if action_by == 'player' and damage > 0:
            battle_state['wild_hp_current'] = max(PERMADEATH_FLOOR, battle_state['wild_hp_current'] - damage)
        elif action_by == 'master' and damage > 0:
            battle_state['player_hp_current'] = max(PERMADEATH_FLOOR, battle_state['player_hp_current'] - damage)

        # Status on-hit do SELVAGEM no jogador (Poison Sting→veneno, Ember→queimadura...)
        # rolado no SERVIDOR (fonte canônica de 224 moves), não só no cliente. Antes,
        # o veneno de golpes selvagens dependia de o cliente ter carregado
        # window.statusEffectsData (~40 moves); se a busca falhasse, nenhum status
        # do selvagem funcionava. O guard 'not player_status' evita empilhar com o
        # cliente. Só sobrescreve se o cliente ainda não aplicou nada.
        if (action_type == 'attack' and action_by == 'master' and damage > 0
                and move_name and not status_effect and not battle_state.get('player_status')):
            skey, inflicted = effects.check_status_on_hit(
                move_name, int(data.get('attack_roll', 10) or 10), damage,
                defender=encounter.get('player_pokemon'))
            if inflicted:
                status_effect = {'condition': skey, 'turns_active': 0}

        # Habilidades de contato (Static, Rough Skin, Flame Body...) —
        # o defensor reage a golpes físicos que causaram dano.
        contact_trigger = None
        if damage > 0 and action_type == 'attack' and move_name:
            move_cat = (MOVES_BY_NAME.get(move_name.lower()) or {}).get('category', 'physical')
            if move_cat == 'physical':
                wild_poke = encounter.get('pokemon', {})
                p_poke = encounter.get('player_pokemon') or {}
                if action_by == 'player':
                    # selvagem defendeu → atacante (jogador) sofre a reação
                    wild_lv = int(wild_poke.get('level') or encounter.get('level') or 5)
                    res = ab.check_contact_ability(wild_poke.get('ability'), _prof_for_level(wild_lv))
                    # imunidade do atacante (tipo/habilidade) anula a reação de status
                    if res and res.get('status') and effects.contact_status_blocked(p_poke, res['status']):
                        res = None
                    if res:
                        contact_trigger = res
                        if res['damage']:
                            battle_state['player_hp_current'] = max(
                                PERMADEATH_FLOOR, battle_state['player_hp_current'] - res['damage'])
                        if res['status'] and not battle_state.get('player_status'):
                            battle_state['player_status'] = {'condition': res['status'], 'turns_active': 0}
                    # Habilidade do ATACANTE (jogador): Poison Touch etc. envenenam o selvagem
                    ares = ab.check_attacker_contact_ability(p_poke.get('ability'))
                    if (ares and ares.get('status') and not battle_state.get('wild_status')
                            and not effects.contact_status_blocked(wild_poke, ares['status'])):
                        battle_state['wild_status'] = {'condition': ares['status'], 'turns_active': 0}
                        contact_trigger = contact_trigger or ares
                else:
                    # pokémon do jogador defendeu → selvagem sofre a reação
                    res = ab.check_contact_ability(p_poke.get('ability'), p_poke.get('proficiency') or 2)
                    # imunidade do atacante (tipo/habilidade) anula a reação de status
                    if res and res.get('status') and effects.contact_status_blocked(wild_poke, res['status']):
                        res = None
                    if res:
                        contact_trigger = res
                        if res['damage']:
                            battle_state['wild_hp_current'] = max(
                                PERMADEATH_FLOOR, battle_state['wild_hp_current'] - res['damage'])
                        if res['status'] and not battle_state.get('wild_status'):
                            battle_state['wild_status'] = {'condition': res['status'], 'turns_active': 0}
                    # Habilidade do ATACANTE (selvagem): Poison Touch etc. envenenam o jogador
                    ares = ab.check_attacker_contact_ability(wild_poke.get('ability'))
                    if (ares and ares.get('status') and not battle_state.get('player_status')
                            and not effects.contact_status_blocked(p_poke, ares['status'])):
                        battle_state['player_status'] = {'condition': ares['status'], 'turns_active': 0}
                        contact_trigger = contact_trigger or ares

        # Apply healing
        if action_by == 'player' and heal > 0:
            battle_state['player_hp_current'] = min(battle_state['player_hp_max'], battle_state['player_hp_current'] + heal)
        elif action_by == 'master' and heal > 0:
            battle_state['wild_hp_current'] = min(battle_state['wild_hp_max'], battle_state['wild_hp_current'] + heal)
        
        # Apply status (store as dict so process_turn_start can read .get('condition'))
        if status_effect:
            status_dict = status_effect if isinstance(status_effect, dict) else {'condition': status_effect, 'turns_active': 0}
            if action_by == 'player':
                if not battle_state.get('wild_status'):
                    battle_state['wild_status'] = status_dict
            else:
                if not battle_state.get('player_status'):
                    battle_state['player_status'] = status_dict

        # Haze: anula os buffs/debuffs dos DOIS lados. A fonte é o MOTOR
        # (srv_reset_stages), não o payload — exceto no caminho legado do
        # mestre (action_by='master'), que ainda declara o efeito.
        if srv_reset_stages or (action_by == 'master' and data.get('reset_stages')):
            effects.reset_stat_stages(encounter.get('pokemon') or {})
            effects.reset_stat_stages(encounter.get('player_pokemon') or {})
            battle_state['wild_stat_stages'] = None
            battle_state['player_stat_stages'] = None

        # Psych Up/Heart Swap/Topsy-Turvy — derivado do motor (payload só no
        # caminho legado do mestre)
        stage_op = srv_stage_op or (data.get('stage_op') if action_by == 'master' else None)
        if stage_op in ('copy', 'swap', 'invert'):
            wp = encounter.get('pokemon') or {}
            pp = encounter.get('player_pokemon') or {}
            actor, other = (pp, wp) if action_by == 'player' else (wp, pp)
            a_st = dict(effects.init_stat_stages(), **(actor.get('stat_stages') or {}))
            o_st = dict(effects.init_stat_stages(), **(other.get('stat_stages') or {}))
            if stage_op == 'copy':
                actor['stat_stages'] = dict(o_st)
            elif stage_op == 'swap':
                actor['stat_stages'], other['stat_stages'] = o_st, a_st
            elif stage_op == 'invert':
                other['stat_stages'] = {k: -v for k, v in o_st.items()}
            battle_state['wild_stat_stages'] = wp.get('stat_stages')
            battle_state['player_stat_stages'] = pp.get('stat_stages')
        
        # Switch turn
        battle_state['turn'] = 'wild' if battle_state['turn'] == 'player' else 'player'
        field_events = []
        if battle_state['turn'] == 'player':
            battle_state['round'] += 1
            # 🌱 Leech Seed: o portador perde seed_drain (⌊HPmáx/16⌋) e o OUTRO lado cura
            # o mesmo tanto (dreno canônico por rodada; nunca nocauteia)
            for holder_st, h_hp, h_max, o_hp, o_max, h_label, o_label in (
                    (battle_state.get('player_status'), 'player_hp_current',
                     'player_hp_max', 'wild_hp_current', 'wild_hp_max',
                     'Seu Pokémon', 'o selvagem'),
                    (battle_state.get('wild_status'), 'wild_hp_current',
                     'wild_hp_max', 'player_hp_current', 'player_hp_max',
                     'O selvagem', 'seu Pokémon')):
                if (holder_st or {}).get('condition') != 'seeded':
                    continue
                if int(battle_state.get(h_hp) or 0) <= 0:
                    continue
                seed_dmg = effects.seed_drain(battle_state.get(h_max))
                battle_state[h_hp] = max(1, int(battle_state[h_hp]) - seed_dmg)
                if int(battle_state.get(o_hp) or 0) > 0:
                    battle_state[o_hp] = min(int(battle_state.get(o_max) or 1),
                                             int(battle_state[o_hp]) + seed_dmg)
                field_events.append(f'🌱 {h_label} perde {seed_dmg} HP pra semente '
                                    f'— {o_label} recupera {seed_dmg}!')
            # F5: fim da rodada — chip de clima, cura de terreno e durações
            fld = _field_of(battle_state)
            if fld.get('weather') or fld.get('terrain'):
                for side, poke, hp_key, max_key, label in (
                        ('player', encounter.get('player_pokemon'), 'player_hp_current',
                         'player_hp_max', 'Seu Pokémon'),
                        ('wild', encounter.get('pokemon'), 'wild_hp_current',
                         'wild_hp_max', 'O selvagem')):
                    if int(battle_state.get(hp_key) or 0) <= 0:
                        continue
                    delta, fmsg = _field_chip(battle_state, poke,
                                              battle_state.get(max_key), label)
                    if delta:
                        # chip nunca nocauteia (deixa em 1 HP)
                        battle_state[hp_key] = max(1, min(
                            int(battle_state.get(max_key) or 1),
                            int(battle_state[hp_key]) + delta))
                    if fmsg:
                        field_events.append(fmsg)
                field_events.extend(_field_tick(battle_state))

        encounter['battle_state'] = battle_state
        game_state['active_encounters'][player_id] = encounter
        save_game_state(game_state)
        
        # Build action result
        action_result = {
            'player_id': player_id,
            'action_by': action_by,
            'action_type': action_type,
            'move_name': move_name,
            'damage': damage,
            'heal': heal,
            'status_effect': status_effect,
            'message': message,
            'battle_state': battle_state,
            'ability_trigger': ability_result if (ability_result and ability_result.get('triggered')) else None,
            'contact_trigger': contact_trigger,
            'action_log': action_log,
            'server_calc': server_calc,  # full server-side calc details for client log
            'field_events': field_events,   # F5: chip de clima/cura/expiração
            'field': _field_of(battle_state),
            'wild_auto': _wild_auto_mode(game_state),
        }
        
        # Notify both sides
        emit('battle_update', action_result, room=f'master_{_tid()}')
        emit('battle_update', action_result, room=player_id)
        _spectate_wild(player_id, encounter,
                       last=(f'{move_name}: {message}' if move_name else message) or '…')
        
        # Wild auto-attack is handled client-side (player.js wildPokemonAutoAttack) to support
        # status damage, move variety, and status moves. Server-side auto-attack removed to
        # prevent race condition: server used stale encounter state and overwrote correct HP.
    finally:
        _BATTLE_BUSY.discard(player_id)

def _auto_roll_initiative(player_id, game_state):
    """Auto-roll initiative when AUTO mode is ON."""
    encounter = game_state.get('active_encounters', {}).get(player_id)
    if not encounter or encounter.get('battle_state', {}).get('initiative_rolled'):
        return
    
    wild_pokemon = encounter['pokemon']
    player_pokemon = encounter.get('player_pokemon') or {}
    
    wild_spe = effects.effective_stat(wild_pokemon, 'SPE')
    player_spe = effects.effective_stat(player_pokemon, 'SPE') if player_pokemon else 10
    player_extra = int((player_pokemon or {}).get('trainer_init_bonus') or 0)
    wild_mod = bm_core.initiative_bonus(wild_spe)
    # mod exibido = o que soma de verdade no total (Tática entra ×INIT_EXTRA_STEP)
    player_mod = (bm_core.initiative_bonus(player_spe)
                  + bm_core.INIT_EXTRA_STEP * player_extra)

    winner, player_init, wild_init, init_upset = bm_core.initiative_winner(
        random.randint(1, 100), random.randint(1, 100),
        player_spe, wild_spe, extra_a=player_extra)
    first_turn = 'player' if winner == 'a' else 'wild'

    encounter['battle_state']['initiative_rolled'] = True
    encounter['battle_state']['turn'] = first_turn
    encounter['battle_state']['round'] = 1
    encounter['battle_state']['wild_initiative'] = wild_init
    encounter['battle_state']['player_initiative'] = player_init
    
    game_state['active_encounters'][player_id] = encounter
    save_game_state(game_state)
    
    result = {
        'player_id': player_id,
        'wild_initiative': wild_init,
        'wild_mod': wild_mod,
        'player_initiative': player_init,
        'player_mod': player_mod,
        'first_turn': first_turn,
        'upset': init_upset,
        'on_enter_abilities': [],
        'weather': None,
        'wild_auto': True,   # esta função só roda no modo AUTO
    }

    socketio.emit('initiative_result', result, room=f'master_{_tid()}')
    socketio.emit('initiative_result', result, room=player_id)
    
    # Wild auto-attack when wild goes first is handled client-side via initiative_result handler.

@socketio.on('apply_wild_status')
def handle_apply_wild_status(data):
    """DEPRECADO por segurança: o status on-hit no selvagem já é rolado no
    SERVIDOR (accuracy/tipo) dentro de battle_action. Aceitar status cru do
    cliente aqui deixava congelar/paralisar o selvagem 100% do tempo. No-op."""
    return

@socketio.on('status_resolved')
def handle_status_resolved(data):
    """Client reports a status condition expired — clear it from server battle_state."""
    if not current_user.is_authenticated:
        return
    player_id = str(current_user.id)
    target = data.get('target')  # 'player' or 'wild'
    game_state = get_game_state()
    encounter = game_state['active_encounters'].get(player_id)
    if not encounter:
        return
    battle_state = encounter['battle_state']
    key = 'player_status' if target == 'player' else 'wild_status' if target == 'wild' else None
    if not key:
        return
    # SEGURANÇA: o cliente só remove condições de auto-remoção NATURAL — sono/
    # confusão (max_turns cumprido) ou sono/congelado (wake/thaw rolados pelo
    # servidor em process_turn_start). Veneno/queimadura/paralisia são
    # PERMANENTES até cura e NÃO podem ser zeradas pelo cliente (era o exploit:
    # limpar o próprio debuff de graça a cada turno).
    cur_status = battle_state.get(key)
    if not cur_status:
        return
    cond = effects.STATUS_CONDITIONS.get((cur_status or {}).get('condition'), {})
    max_turns = cond.get('max_turns')
    turns = int((cur_status or {}).get('turns_active') or 0)
    natural = cond.get('wake_check') or cond.get('thaw_check')
    if natural or (max_turns is not None and turns >= int(max_turns)):
        battle_state[key] = None
        encounter['battle_state'] = battle_state
        game_state['active_encounters'][player_id] = encounter
        save_game_state(game_state)

def apply_battle_rewards(player_id, encounter, active_pokemon_name=None):
    """Recompensas de vitória contra selvagem, 100% no SERVIDOR: XP
    (tabela oficial), level-up com recálculo de stats, battle_wins por
    ÍNDICE do slot e evolução por nível — tudo num único save.
    Retorna dict com o resultado ou None se não há o que premiar."""
    users = get_users()
    trainer = users.get(player_id, {}).get('trainer_data', {})
    team = trainer.get('team', [])
    if not team:
        return None

    # Slot autoritativo: o que o servidor guardou no encontro (start/switch);
    # fallback para clientes antigos: casa por nome/nickname.
    slot = encounter.get('player_pokemon_idx')
    if not isinstance(slot, int) or not (0 <= slot < len(team)):
        name = ((encounter.get('player_pokemon') or {}).get('name')
                or encounter.get('player_pokemon_name') or active_pokemon_name)
        slot = next((i for i, p in enumerate(team)
                     if p.get('name') == name or p.get('nickname') == name), None)
    if slot is None:
        return None

    poke = team[slot]
    wild_level = int(encounter.get('level')
                     or (encounter.get('pokemon') or {}).get('level') or 1)
    old_level = int(poke.get('level', 1))
    xp_gained = scaling.battle_xp_reward(old_level, wild_level, 'wild')

    poke['xp'] = poke.get('xp', 0) + xp_gained
    poke['totalXp'] = poke.get('totalXp', 0) + xp_gained
    new_level = max(old_level, scaling.level_from_xp(poke['totalXp']))
    poke['level'] = new_level
    leveled_up = new_level > old_level
    if leveled_up:
        base_poke = POKEMON_BY_NAME.get((poke.get('name') or '').lower())
        if base_poke:
            scaled = scaling.calculate_pokemon_stats(base_poke, new_level, poke.get('nature'),
                                                     is_shiny=poke.get('is_shiny', False),
                                                     training=poke.get('training'))
            old_ratio = poke.get('currentHp', scaled['hp']) / max(1, poke.get('maxHp', scaled['hp']))
            poke['stats'] = scaled['stats']
            poke['maxHp'] = scaled['hp']
            poke['currentHp'] = max(1, int(scaled['hp'] * old_ratio))
            poke['proficiency'] = scaled['proficiency']
            poke['stab'] = scaled['stab']
            poke['phys_ac'] = scaled['phys_ac']
            poke['spec_ac'] = scaled['spec_ac']

    poke['battle_wins'] = poke.get('battle_wins', 0) + 1

    evolution = None
    evolved, evolved_name = check_and_evolve_pokemon(poke)
    if evolved:
        evolved_base = POKEMON_BY_NAME.get(evolved_name.lower(), {})
        new_moves = _evolution_new_moves(poke, evolved_base)
        team[slot] = evolved
        evolution = {'old_pokemon': poke, 'evolved': evolved, 'new_moves': new_moves}

    users[player_id]['trainer_data'] = trainer
    save_users(users)

    return {
        'slot': slot,
        'xp_gained': xp_gained,
        'new_level': new_level,
        'leveled_up': leveled_up,
        'evolution': evolution,
        'pokemon': team[slot],
        'player_name': users.get(player_id, {}).get('username', ''),
    }


@socketio.on('end_encounter')
def handle_end_encounter(data):
    """End an encounter."""
    if current_user.is_authenticated:
        game_state = get_game_state()
        # jogador só encerra o PRÓPRIO encontro; mestre precisa que o alvo
        # seja da mesa dele (evita forjar player_id de outra pessoa/mesa)
        if current_user.role == 'master':
            player_id = str(data.get('player_id', current_user.id))
            if not _player_in_master_table(player_id, get_users(), _tid()):
                return
        else:
            player_id = str(current_user.id)
        result = data.get('result', '')

        # Vitória contra selvagem: XP/level-up/evolução server-side.
        # Exige encontro ativo (sem encontro = sem prêmio; evita farm forjado).
        rewards = None
        encounter = game_state.get('active_encounters', {}).get(player_id)
        if result == 'defeated' and encounter:
            rewards = apply_battle_rewards(player_id, encounter,
                                           data.get('active_pokemon_name'))

        if player_id in game_state['active_encounters']:
            del game_state['active_encounters'][player_id]
            save_game_state(game_state)
        emit('encounter_ended', {'player_id': player_id, 'result': result}, room=f'master_{_tid()}')
        emit('encounter_ended', {'player_id': player_id, 'result': result}, room=player_id)
        _spectate('wild', {'id': f'wild_{player_id}', 'players': [player_id],
                           'finished': True, 'result': result})

        if rewards:
            socketio.emit('battle_rewards', {
                'player_id': player_id,
                'slot': rewards['slot'],
                'xp_gained': rewards['xp_gained'],
                'new_level': rewards['new_level'],
                'leveled_up': rewards['leveled_up'],
                'evolved': bool(rewards['evolution']),
                'pokemon': rewards['pokemon'],
            }, room=player_id)
            if rewards['evolution']:
                ev = rewards['evolution']
                _emit_evolution_focus(player_id, rewards['player_name'],
                                      rewards['slot'], ev['old_pokemon'],
                                      ev['evolved'], ev['new_moves'], 'battle')

@socketio.on('master_action')
def handle_master_action(data):
    """Master sends an action to a player (e.g., battle command, mega wild)."""
    if current_user.is_authenticated and current_user.role == 'master':
        target_player = data.get('player_id')
        # encontro manual → registra o 'vale' para liberar o start_encounter
        if data.get('type') == 'forced_encounter' and target_player:
            if _player_in_master_table(str(target_player), get_users(), _tid()):
                _grant_encounter(target_player, (data.get('pokemon') or {}).get('number'))
        emit('master_action', data, room=target_player)

@socketio.on('mega_evolve')
def handle_mega_evolve(data):
    """Handle mega evolution in battle."""
    if current_user.is_authenticated:
        side = data.get('side', 'player')  # 'player' or 'wild'
        # Só o mestre mega-evolui o SELVAGEM ou age no encontro de outro
        # jogador; jogador só mega-evolui no próprio encontro (o lado
        # 'player'). Sem isto, qualquer um forjava player_id/side e mexia
        # na batalha alheia.
        if current_user.role == 'master':
            player_id = str(data.get('player_id', current_user.id))
            if not _player_in_master_table(player_id, get_users(), _tid()):
                return
        else:
            if side == 'wild':
                return
            player_id = str(current_user.id)
        stone_name = data.get('stone_name', '')

        stone_data = MEGA_DB.get(stone_name, {})
        if not stone_data:
            return
        
        game_state = get_game_state()
        encounter = game_state['active_encounters'].get(player_id)
        if not encounter:
            return
        
        bonuses = stone_data.get('bonuses', {})
        
        result = {
            'player_id': player_id,
            'side': side,
            'stone_name': stone_name,
            'mega_name': stone_data.get('megaName', ''),
            'ability': stone_data.get('ability', ''),
            'new_types': stone_data.get('newTypes'),
            'bonuses': bonuses
        }
        
        emit('mega_evolved', result, room=f'master_{_tid()}')
        emit('mega_evolved', result, room=player_id)

# ============================================================
# PVP ARENA
# ============================================================
# In-memory PVP battles (active battles stored here for speed)
ACTIVE_PVP = {}  # battle_id -> battle state
ACTIVE_TOURNAMENTS = {}  # tournament_id -> tournament state

@socketio.on('pvp_join_arena')
def handle_pvp_join(data):
    """Player enters the PVP arena."""
    if current_user.is_authenticated:
        join_room('pvp_arena')
        tid = _tid()
        players_list = []
        for uid, u in _db_raw.get_users_in_table(tid).items():
            if u['role'] == 'player':
                trainer = u.get('trainer_data', {})
                players_list.append({
                    'id': uid,
                    'name': trainer.get('name', u['username']),
                    'level': trainer.get('level', 1),
                    'team_size': len(trainer.get('team', []))
                })
        # NPCs da mesa com time também podem ser desafiados
        for npc in db.get_npcs():
            if npc.get('team'):
                players_list.append({
                    'id': npc['id'],
                    'name': npc.get('name', 'NPC'),
                    'level': npc.get('level', 1),
                    'team_size': len(npc['team']),
                    'is_npc': True,
                    'npc_class': npc.get('npc_class', '')
                })
        emit('pvp_arena_players', players_list)
        emit('pvp_player_joined', {
            'id': current_user.id,
            'name': current_user.username
        }, room='pvp_arena', include_self=False)

@socketio.on('master_pvp_challenge')
@login_required
def handle_master_pvp_challenge(data):
    """Master sends an NPC to challenge a player (or battle another NPC)."""
    if current_user.role != 'master':
        return
    npc_id    = data.get('npc_id')
    target_id = data.get('target_id')
    mode      = data.get('mode', 'official')

    npcs  = db.get_npcs()
    npc   = next((n for n in npcs if n['id'] == npc_id), None)
    if not npc:
        emit('master_error', {'msg': 'NPC não encontrado'})
        return

    users = get_users()
    target_is_npc = target_id not in users
    if target_is_npc:
        target_npc = next((n for n in npcs if n['id'] == target_id), None)
        if not target_npc:
            emit('master_error', {'msg': 'Alvo não encontrado'})
            return
        target_team = target_npc.get('team', [])
        target_name = target_npc.get('name', target_id)
    else:
        target_trainer = users[target_id].get('trainer_data', {})
        target_team    = target_trainer.get('team', [])
        target_name    = target_trainer.get('name', users[target_id]['username'])

    battle = pvp.create_pvp_battle(mode, npc_id, target_id)
    battle['extra'] = {'initiated_by_master': True}
    _mig(npc.get('team', []))
    pvp.set_team(battle, 'player1', npc.get('team', []))
    _mig(target_team)
    if not target_is_npc:
        _stamp_tatica(target_team, target_trainer)
    pvp.set_team(battle, 'player2', target_team)
    battle['player1']['is_npc'] = True
    if npc.get('team'):
        pvp.select_pokemon(battle, 'player1', 0)
    if target_is_npc:
        battle['player2']['is_npc'] = True
        if target_team:
            pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle
    _emit_pvp_to_master(battle, 'created')

    if not target_is_npc:
        socketio.emit('pvp_battle_created', {
            'battle_id':     battle['id'],
            'opponent_name': npc.get('name', 'NPC'),
            'mode':          mode,
            'your_team':     target_team,
            'you_are':       'player2',
            'phase':         'selection'
        }, room=target_id)

    emit('master_pvp_created', {'battle_id': battle['id'], 'npc': npc.get('name'), 'target': target_name})


@socketio.on('pvp_challenge')
def handle_pvp_challenge(data):
    """Send a PVP challenge with mode and optional bet."""
    if current_user.is_authenticated:
        target_id = data.get('target_id')
        mode = data.get('mode', 'street')  # official, street
        bet_money = int(data.get('bet_money', 0))
        bet_items = data.get('bet_items', [])

        # Alvo é um NPC? Cria a batalha na hora (NPC sempre aceita)
        npc = next((n for n in db.get_npcs() if n['id'] == target_id), None)
        if npc:
            if not npc.get('team'):
                emit('pvp_error', {'message': 'Este NPC não tem time para batalhar.'})
                return
            users = get_users()
            my_team = users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
            if not my_team:
                emit('pvp_error', {'message': 'Você precisa de pelo menos 1 Pokémon no time!'})
                return

            battle = pvp.create_pvp_battle(mode, current_user.id, npc['id'])
            _mig(my_team)
            _stamp_tatica(my_team, users.get(current_user.id, {}).get('trainer_data'))
            pvp.set_team(battle, 'player1', my_team)
            _mig(npc.get('team', []))
            pvp.set_team(battle, 'player2', npc.get('team', []))
            battle['player2']['is_npc'] = True
            ACTIVE_PVP[battle['id']] = battle

            emit('pvp_battle_created', {
                'battle_id': battle['id'],
                'opponent_name': npc.get('name', 'NPC'),
                'mode': mode,
                'your_team': my_team,
                'you_are': 'player1',
                'phase': 'selection'
            }, room=current_user.id)
            _emit_pvp_to_master(battle, 'created')
            emit('pvp_challenge_sent', {
                'challenger': current_user.username,
                'target_id': target_id,
                'mode': mode,
                'is_npc': True
            }, room=f'master_{_tid()}')
            return

        emit('pvp_challenge_received', {
            'challenger_id': current_user.id,
            'challenger_name': current_user.username,
            'challenger_level': current_user.trainer_data.get('level', 1) if current_user.trainer_data else 1,
            'mode': mode,
            'bet_money': bet_money,
            'bet_items': bet_items
        }, room=target_id)
        emit('pvp_challenge_sent', {
            'challenger': current_user.username,
            'target_id': target_id,
            'mode': mode
        }, room=f'master_{_tid()}')

@socketio.on('pvp_accept')
def handle_pvp_accept(data):
    """Accept a PVP challenge - create battle."""
    if current_user.is_authenticated:
        challenger_id = data.get('challenger_id')
        mode = data.get('mode', 'street')
        bet_money = int(data.get('bet_money', 0))
        bet_items = data.get('bet_items', [])
        
        # Create battle
        bets = {
            'player1': {'money': bet_money, 'items': bet_items},
            'player2': {'money': bet_money, 'items': bet_items}
        }
        battle = pvp.create_pvp_battle(mode, challenger_id, current_user.id, bets)
        
        # Set teams from trainer data
        users = get_users()
        p1_team = users.get(challenger_id, {}).get('trainer_data', {}).get('team', [])
        p2_team = users.get(current_user.id, {}).get('trainer_data', {}).get('team', [])
        _mig(p1_team)
        _stamp_tatica(p1_team, users.get(challenger_id, {}).get('trainer_data'))
        pvp.set_team(battle, 'player1', p1_team)
        _mig(p2_team)
        _stamp_tatica(p2_team, users.get(current_user.id, {}).get('trainer_data'))
        pvp.set_team(battle, 'player2', p2_team)
        
        ACTIVE_PVP[battle['id']] = battle
        
        # Notify both - send to selection phase
        emit('pvp_battle_created', {
            'battle_id': battle['id'],
            'mode': mode,
            'opponent_name': current_user.username,
            'your_team': p1_team,
            'you_are': 'player1',
            'phase': 'selection'
        }, room=challenger_id)
        emit('pvp_battle_created', {
            'battle_id': battle['id'],
            'mode': mode,
            'opponent_name': data.get('challenger_name', '???'),
            'your_team': p2_team,
            'you_are': 'player2',
            'phase': 'selection'
        }, room=current_user.id)
        emit('pvp_battle_started', {
            'battle_id': battle['id'],
            'player1': data.get('challenger_name', '???'),
            'player2': current_user.username,
            'mode': mode
        }, room=f'master_{_tid()}')

@socketio.on('pvp_decline')
def handle_pvp_decline(data):
    if current_user.is_authenticated:
        emit('pvp_challenge_declined', {
            'decliner_name': current_user.username
        }, room=data.get('challenger_id'))

@socketio.on('pvp_select_pokemon')
def handle_pvp_select(data):
    """Player selects starting pokemon (blind selection)."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        pokemon_idx = int(data.get('pokemon_idx', 0))
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        
        # Determine which player this is
        player_key = 'player1' if battle['player1']['id'] == current_user.id else 'player2'
        
        success, result = pvp.select_pokemon(battle, player_key, pokemon_idx)

        # If the opponent is an NPC and hasn't selected yet, auto-select for them
        opponent_key = 'player2' if player_key == 'player1' else 'player1'
        if result == 'waiting_opponent' and battle[opponent_key].get('is_npc'):
            opp = battle[opponent_key]
            opp_team = opp.get('team') or []
            if not opp_team:
                # NPC has no team — create a minimal fallback so battle can proceed
                opp_team = [{'name': 'Rattata', 'number': 19, 'level': 5,
                              'currentHp': 20, 'maxHp': 20, 'ac': 11,
                              'types': ['Normal'], 'moves': ['Tackle'], 'stats': {}}]
                opp['team'] = opp_team
            # Force mark NPC ready directly if select_pokemon fails (e.g. index out of range)
            if not opp.get('ready'):
                s2, result = pvp.select_pokemon(battle, opponent_key, 0)
                if not s2:
                    # Manually mark ready as last resort
                    opp['active_idx'] = 0
                    opp['ready'] = True
                    opp['used_pokemon'] = [0]
                    if battle['player1']['ready'] and battle['player2']['ready']:
                        import random as _r
                        battle['phase'] = 'battle'
                        battle['round'] = 1
                        # mesma regra do caminho normal: d100 + SPE_eff (fonte única)
                        _p1 = battle['player1']['team'][battle['player1'].get('active_idx', 0)]
                        _p2 = battle['player2']['team'][battle['player2'].get('active_idx', 0)]
                        _w, _, _, _ = bm_core.initiative_winner(
                            _r.randint(1, 100), _r.randint(1, 100),
                            effects.effective_stat(_p1, 'SPE'),
                            effects.effective_stat(_p2, 'SPE'))
                        battle['turn'] = 'player1' if _w == 'a' else 'player2'
                        result = 'battle_start'

        if result == 'battle_start':
            # Send state to human player(s) only; skip NPC rooms
            p1_is_npc = battle['player1'].get('is_npc', False)
            p2_is_npc = battle['player2'].get('is_npc', False)
            p1_state = pvp.get_battle_state_for_player(battle, 'player1')
            p2_state = pvp.get_battle_state_for_player(battle, 'player2')
            if not p1_is_npc:
                emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
            if not p2_is_npc:
                emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
            _emit_pvp_to_master(battle, 'battle_started')
            # If it's the NPC's turn first, trigger their turn immediately
            first_turn_key = battle.get('turn')
            if first_turn_key and battle[first_turn_key].get('is_npc'):
                handle_npc_turn(battle, first_turn_key)
        elif result == 'waiting_opponent':
            emit('pvp_waiting', {'message': 'Aguardando oponente escolher Pokémon...'})

def _pvp_my_key(battle):
    """player_key do current_user SE ele for participante da batalha, senão
    None. Impede um terceiro de agir/encerrar batalha alheia (griefing)."""
    if not battle:
        return None
    me = current_user.id
    if battle.get('player1', {}).get('id') == me:
        return 'player1'
    if battle.get('player2', {}).get('id') == me:
        return 'player2'
    return None


@socketio.on('pvp_attack')
def handle_pvp_attack(data):
    """Player attacks in PVP battle."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        move_name = data.get('move_name', '')
        damage = int(data.get('damage', 0))
        move_type = (data.get('move_type', '') or '').lower()
        status_effect = data.get('status_effect')
        message = data.get('message', '')

        battle = ACTIVE_PVP.get(battle_id)
        if not battle or battle['phase'] != 'battle':
            return

        player_key = _pvp_my_key(battle)
        if not player_key:
            return   # não é participante desta batalha
        defender_key = 'player2' if player_key == 'player1' else 'player1'

        # Validate it's this player's turn
        if battle['turn'] != player_key:
            emit('pvp_error', {'message': 'Não é seu turno!'})
            return

        # Server-side damage calculation (ignore client damage)
        attacker = battle[player_key]
        defender = battle[defender_key]
        att_poke = attacker['team'][attacker['active_idx']]
        def_poke = defender['team'][defender['active_idx']]

        # Pokémon desmaiado NÃO age: fecha o "último golpe" depois de zerado
        # (o cliente às vezes ainda estava com o turno antigo na tela).
        if pvp._poke_hp(att_poke) <= 0:
            emit('pvp_error', {'message': '💀 Seu Pokémon desmaiou — troque de Pokémon.'})
            return
        # Defensor com ativo desmaiado está aguardando troca — atacar o
        # "corpo" empurraria o HP até -30 (morte permanente indevida).
        if pvp._poke_hp(def_poke) <= 0:
            emit('pvp_error', {'message': 'Oponente está trocando de Pokémon — aguarde.'})
            return
        calc = _calc_pvp_attack(att_poke, def_poke, move_name, None,
                                field=_field_of(battle))   # v3: servidor rola o d100
        if calc.get('blocked'):
            if _v3_sem_opcao(att_poke):
                # RODADA DE FÔLEGO: nada disponível — descansa, turno passa
                battle['log'].append({'type': 'info',
                                      'message': _v3_folego(att_poke)})
                pvp.advance_turn(battle)
                _broadcast_pvp_state(battle)
                next_key = battle['turn']
                if battle['phase'] == 'battle' and battle[next_key].get('is_npc'):
                    handle_npc_turn(battle, next_key)
                return
            # golpe em cooldown: não consome o turno — escolha outro
            emit('pvp_error', {'message': calc.get('message')})
            return
        damage   = calc['damage']
        message  = calc['message']
        move_type = calc.get('move_type_en', move_type)
        # F5: recoil (nunca nocauteia o usuário) e dreno
        if calc.get('recoil'):
            att_poke['currentHp'] = max(1, att_poke.get('currentHp', 1) - int(calc['recoil']))
            battle['log'].append({'type': 'info',
                                  'message': f"💢 Recoil: {calc['recoil']} de dano em si!"})
        if calc.get('drain_heal'):
            att_poke['currentHp'] = min(att_poke.get('maxHp', 20),
                                        att_poke.get('currentHp', 0) + int(calc['drain_heal']))
            battle['log'].append({'type': 'info',
                                  'message': f"💚 Drenou {calc['drain_heal']} HP!"})
        # Rampage: o usuário fica confuso; Explosion: o usuário desmaia
        if calc.get('self_status'):
            pvp.apply_status(battle, player_key, {'condition': calc['self_status']})
        if calc.get('self_ko'):
            att_poke['currentHp'] = 0
            battle['log'].append({'type': 'faint', 'player': player_key,
                                  'permadeath': False})

        # Process attacker's own status damage before acting
        status_dmg, status_info, can_act, status_msgs = pvp.process_turn_status(battle, player_key)
        for m in status_msgs:
            battle['log'].append({'type': 'info', 'message': m})
        if status_dmg > 0:
            battle['log'].append({'type': 'status_damage', 'player': player_key,
                                  'damage': status_dmg, 'status': status_info})

        att_active = battle[player_key]['team'][battle[player_key]['active_idx']]
        if att_active.get('currentHp', 0) <= 0 or not can_act:
            # Desmaiou pelo status ou não pode agir (sono/paralisia/congelado)
            if att_active.get('currentHp', 0) <= 0:
                battle['log'].append({'type': 'faint', 'player': player_key, 'permadeath': False})
                # Se era o ÚLTIMO pokémon vivo, a batalha ACABA aqui — sem
                # isso a fase ficava travada em 'battle' para sempre quando o
                # golpe de misericórdia vinha do próprio veneno/queimadura.
                if not any(pvp._poke_hp(p) > 0 for p in battle[player_key]['team']):
                    battle['phase'] = 'finished'
                    battle['winner'] = defender_key
                    _broadcast_pvp_state(battle, 'status_faint_end')
                    handle_pvp_victory(battle)
                    return
            pvp.advance_turn(battle)
            _broadcast_pvp_state(battle, 'status_skip')
            next_key = battle['turn']
            if battle['phase'] == 'battle' and battle[next_key].get('is_npc'):
                handle_npc_turn(battle, next_key)
            return

        # ── Move de STATUS: nunca causa dano — roteia pelo motor de efeitos ──
        # (exceto Metronome: vira um move de DANO aleatório, resolvido no calc)
        move_data = MOVES_BY_NAME.get(move_name.lower()) or MOVES_DB.get(move_name)
        if _is_status_move(move_data) and move_name.lower() not in VARIABLE_DAMAGE_MOVES:
            _process_pvp_status_move(battle, player_key, move_name, move_data)
            next_key = battle['turn']
            if battle['phase'] == 'battle' and battle[next_key].get('is_npc'):
                handle_npc_turn(battle, next_key)
            return

        ability_trigger = None

        # Check defender ability
        if damage > 0 and move_type:
            defender = battle[defender_key]
            def_active = defender['team'][defender['active_idx']]
            def_ability = (def_active.get('ability') or '').lower()
            if def_ability:
                ar = ab.check_defender_ability(
                    def_ability, move_type, damage,
                    max(0, def_active.get('currentHp', 0)), def_active.get('maxHp', 20)
                )
                if ar['triggered']:
                    damage = ar['modified_damage']
                    if ar['heal']:
                        def_active['currentHp'] = min(def_active.get('maxHp', 20),
                                                      def_active.get('currentHp', 0) + ar['heal'])
                    ability_trigger = ar

        # Apply damage
        result = pvp.apply_damage(battle, player_key, damage, move_name, message)

        # Habilidade de contato do defensor (Static, Rough Skin...)
        if damage > 0 and (MOVES_BY_NAME.get(move_name.lower()) or {}).get('category', 'physical') == 'physical':
            cres = ab.check_contact_ability(def_poke.get('ability'), def_poke.get('proficiency') or 2)
            # imunidade do atacante (tipo/habilidade) anula a reação de status
            if cres and cres.get('status') and effects.contact_status_blocked(att_poke, cres['status']):
                cres = None
            if cres:
                if cres['damage']:
                    att_poke['currentHp'] = max(-999, att_poke.get('currentHp', 0) - cres['damage'])
                if cres['status'] and not att_poke.get('status'):
                    att_poke['status'] = {'condition': cres['status'], 'turns_active': 0}
                battle['log'].append({'type': 'ability', 'message': cres['message']})
            # Habilidade do ATACANTE (Poison Touch...) envenena o defensor no contato
            ares = ab.check_attacker_contact_ability(att_poke.get('ability'))
            if (ares and ares.get('status') and not def_poke.get('status')
                    and not effects.contact_status_blocked(def_poke, ares['status'])):
                def_poke['status'] = {'condition': ares['status'], 'turns_active': 0}
                battle['log'].append({'type': 'ability', 'message': ares['message']})

        # Apply status effect to defender if move has one
        status_applied = False
        if status_effect and result not in ('battle_end',):
            status_applied = pvp.apply_status(battle, defender_key, status_effect)
        
        # Auto-check move status effects if client didn't send one
        if not status_applied and damage > 0 and move_name and result not in ('battle_end',):
            skey, inflicted = effects.check_status_on_hit(
                move_name, int(data.get('attack_roll') or 15), damage, defender=def_poke)
            if inflicted:
                auto_status = {'condition': skey}
                status_applied = pvp.apply_status(battle, defender_key, auto_status)
                if status_applied:
                    status_effect = auto_status

        # Handle permanent death before sending state
        _handle_pvp_permadeath(battle)

        # Attach extra info to battle log for client display
        if ability_trigger:
            battle['log'].append({'type': 'ability', 'message': ability_trigger.get('message', '')})
        if status_applied:
            battle['log'].append({'type': 'status_applied', 'player': defender_key,
                                  'status': status_effect})

        # Send updated state to both players
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'attack')

        if result == 'battle_end':
            handle_pvp_victory(battle)
        elif result == 'must_switch':
            # Notify defender they must switch
            defender_key = 'player2' if player_key == 'player1' else 'player1'
            defender_id = battle[defender_key]['id']
            emit('pvp_must_switch', {
                'battle_id': battle_id,
                'message': 'Seu Pokémon desmaiou! Escolha o próximo.'
            }, room=defender_id)
            # If defender is NPC, auto-switch
            if battle[defender_key].get('is_npc'):
                npc_next = pvp.npc_choose_pokemon(battle, defender_key)
                if npc_next is not None:
                    pvp.switch_pokemon(battle, defender_key, npc_next)
                    # Send updated state
                    p1_state = pvp.get_battle_state_for_player(battle, 'player1')
                    p2_state = pvp.get_battle_state_for_player(battle, 'player2')
                    emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
                    emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        
        # If next turn is NPC, auto-attack
        next_player_key = battle['turn']
        if battle['phase'] == 'battle' and battle[next_player_key].get('is_npc'):
            handle_npc_turn(battle, next_player_key)

@socketio.on('pvp_switch')
def handle_pvp_switch(data):
    """Player switches pokemon in PVP."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        new_idx = int(data.get('pokemon_idx', 0))
        
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return

        player_key = _pvp_my_key(battle)
        if not player_key:
            return

        # Troca voluntária só no seu turno; forçada (ativo desmaiado) sempre pode
        side = battle[player_key]
        active = side['team'][side['active_idx']] if side.get('active_idx') is not None else None
        forced = active is not None and pvp._poke_hp(active) <= 0
        if battle['turn'] != player_key and not forced:
            emit('pvp_error', {'message': 'Não é seu turno para trocar!'})
            return

        success, msg = pvp.switch_pokemon(battle, player_key, new_idx)

        if not success:
            emit('pvp_error', {'message': msg})
            return
        
        # Send updated state
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'switch')

        # If next turn is NPC
        if battle['phase'] == 'battle' and battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])

@socketio.on('pvp_pass_turn')
def handle_pvp_pass(data):
    """Player passes turn."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        player_key = _pvp_my_key(battle)
        if not player_key:
            return
        if battle['turn'] != player_key:
            return
        pvp.advance_turn(battle)
        p1_state = pvp.get_battle_state_for_player(battle, 'player1')
        p2_state = pvp.get_battle_state_for_player(battle, 'player2')
        emit('pvp_battle_state', p1_state, room=battle['player1']['id'])
        emit('pvp_battle_state', p2_state, room=battle['player2']['id'])
        _emit_pvp_to_master(battle, 'pass')

        if battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'])

@socketio.on('tournament_start_match')
def handle_tournament_start_match(data):
    """Master initiates a tournament match — creates an official PVP battle between participants."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    tourney_id = data.get('tournament_id')
    match_id   = data.get('match_id')
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return

    match = next((m for m in tournament['bracket'] if m['id'] == match_id), None)
    if not match or match['winner'] or not match['player1'] or not match['player2']:
        return

    p1 = match['player1']
    p2 = match['player2']

    users = get_users()
    battle = pvp.create_pvp_battle('tournament', p1['id'], p2['id'])
    battle['tournament_id']   = tourney_id
    battle['tournament_match_id'] = match_id

    # Load teams (NPC participants store team directly on participant dict)
    p1_team = p1.get('team') or users.get(p1['id'], {}).get('trainer_data', {}).get('team', [])
    p2_team = p2.get('team') or users.get(p2['id'], {}).get('trainer_data', {}).get('team', [])
    _mig(p1_team)
    _stamp_tatica(p1_team, users.get(p1['id'], {}).get('trainer_data'))
    pvp.set_team(battle, 'player1', p1_team)
    _mig(p2_team)
    _stamp_tatica(p2_team, users.get(p2['id'], {}).get('trainer_data'))
    pvp.set_team(battle, 'player2', p2_team)

    # Mark NPC players
    if p1.get('is_npc'):
        battle['player1']['is_npc'] = True
    if p2.get('is_npc'):
        battle['player2']['is_npc'] = True

    ACTIVE_PVP[battle['id']] = battle
    match['battle_id'] = battle['id']

    # Notify human players
    for side, participant in [('player1', p1), ('player2', p2)]:
        if not participant.get('is_npc'):
            opponent = p2 if side == 'player1' else p1
            my_team  = p1_team if side == 'player1' else p2_team
            socketio.emit('pvp_battle_created', {
                'battle_id': battle['id'],
                'mode': 'tournament',
                'opponent_name': opponent['name'],
                'your_team': my_team,
                'you_are': side,
                'phase': 'selection',
                'tournament_name': tournament['name']
            }, room=participant['id'])

    # If both are NPCs, auto-resolve immediately
    if p1.get('is_npc') and p2.get('is_npc'):
        winner_key = random.choice(['player1', 'player2'])
        battle['winner'] = winner_key
        battle['phase']  = 'finished'
        handle_pvp_victory(battle)
    elif p1.get('is_npc'):
        # Auto-select for NPC player1 then wait for human p2
        if p1_team:
            pvp.select_pokemon(battle, 'player1', 0)
            battle['player1']['is_npc'] = True
    elif p2.get('is_npc'):
        if p2_team:
            pvp.select_pokemon(battle, 'player2', 0)
            battle['player2']['is_npc'] = True

    socketio.emit('tournament_match_started', {
        'match_id': match_id,
        'battle_id': battle['id'],
        'p1_name': p1['name'],
        'p2_name': p2['name']
    }, room=f'master_{_tid()}')


@socketio.on('pvp_forfeit')
def handle_pvp_forfeit(data):
    """Player forfeits the battle."""
    if current_user.is_authenticated:
        battle_id = data.get('battle_id')
        battle = ACTIVE_PVP.get(battle_id)
        if not battle:
            return
        player_key = _pvp_my_key(battle)
        if not player_key:
            return   # só um participante pode desistir da própria batalha
        winner_key = 'player2' if player_key == 'player1' else 'player1'
        battle['phase'] = 'finished'
        battle['winner'] = winner_key
        handle_pvp_victory(battle)


def _handle_pvp_permadeath(battle):
    """Check for and process permanent Pokémon death in PVP (HP <= -10)."""
    pd = battle.pop('last_permadeath', None)
    if not pd:
        return
    dead_player_id = pd['player_id']
    dead_poke_name = pd['pokemon_name']
    users = get_users()
    user = users.get(dead_player_id)
    if user:
        team = user.get('trainer_data', {}).get('team', [])
        original_len = len(team)
        team = [p for p in team if (p.get('nickname') or p.get('name')) != dead_poke_name]
        if len(team) < original_len:
            user['trainer_data']['team'] = team
            save_users(users)
    socketio.emit('pvp_pokemon_death', {
        'pokemon_name': dead_poke_name,
        'message': f'💀 {dead_poke_name} atingiu -30 HP e morreu permanentemente!'
    }, room=dead_player_id)
    socketio.emit('pvp_master_permadeath', {
        'player_id': dead_player_id,
        'pokemon': dead_poke_name
    }, room=f'master_{_tid()}')


@socketio.on('master_force_npc_select')
def handle_master_force_npc_select(data):
    """Master forces an NPC to select their starting pokemon."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    battle_id = data.get('battle_id')
    player_key = data.get('player_key')
    battle = ACTIVE_PVP.get(battle_id)
    if not battle or battle['phase'] != 'selection':
        emit('master_error', {'msg': 'Batalha não está em fase de seleção.'})
        return
    team = battle[player_key].get('team', [])
    if not team:
        emit('master_error', {'msg': 'NPC não tem equipe.'})
        return
    success, result = pvp.select_pokemon(battle, player_key, 0)
    if result == 'battle_start':
        opponent_key = 'player2' if player_key == 'player1' else 'player1'
        opp_is_npc = battle[opponent_key].get('is_npc', False)
        if not opp_is_npc:
            state = pvp.get_battle_state_for_player(battle, opponent_key)
            socketio.emit('pvp_battle_state', state, room=battle[opponent_key]['id'])
        _emit_pvp_to_master(battle, 'battle_started')
        if battle[battle['turn']].get('is_npc'):
            handle_npc_turn(battle, battle['turn'], forced=True)
    else:
        _emit_pvp_to_master(battle, 'update')
    emit('master_force_npc_result', {'message': f'✅ NPC selecionou Pokémon!'})


@socketio.on('master_force_npc_action')
def handle_master_force_npc(data):
    """Master forces an NPC (or frozen player) to take an action."""
    if not current_user.is_authenticated or current_user.role != 'master':
        return
    battle_id = data.get('battle_id')
    player_key = data.get('player_key')
    battle = ACTIVE_PVP.get(battle_id)
    if not battle or battle['phase'] != 'battle':
        emit('master_error', {'msg': 'Batalha inativa ou não encontrada.'})
        return
    if player_key not in ('player1', 'player2'):
        return
    handle_npc_turn(battle, player_key, forced=True)
    emit('master_force_npc_result', {'message': f'⚡ Ação forçada para {player_key}!'})


def _emit_pvp_to_master(battle, event='update'):
    """Broadcast current PVP battle state to master room."""
    p1 = battle.get('player1', {})
    p2 = battle.get('player2', {})
    p1_active = (p1.get('team') or [{}])[p1.get('active_idx') or 0] if p1.get('team') else {}
    p2_active = (p2.get('team') or [{}])[p2.get('active_idx') or 0] if p2.get('team') else {}
    users = get_users()
    npcs = db.get_npcs()
    npc_map = {n['id']: n['name'] for n in npcs}
    p1_name = users.get(p1.get('id'), {}).get('username') or npc_map.get(p1.get('id'), p1.get('id', '?'))
    p2_name = users.get(p2.get('id'), {}).get('username') or npc_map.get(p2.get('id'), p2.get('id', '?'))
    payload = {
        'event':       event,
        'battle_id':   battle.get('id'),
        'mode':        battle.get('mode', 'official'),
        'phase':       battle.get('phase', 'selection'),
        'round':       battle.get('round', 0),
        'turn':        battle.get('turn'),
        'winner':      battle.get('winner'),
        'extra':       battle.get('extra', {}),
        'p1_id':       p1.get('id'), 'p1_name': p1_name,
        'p1_is_npc':   p1.get('is_npc', False),
        'p1_hp':       max(0, p1_active.get('currentHp', 0)) if isinstance(p1_active.get('currentHp'), (int, float)) else '?',
        'p1_maxhp':    p1_active.get('maxHp', '?'),
        'p1_pokemon':  p1_active.get('nickname') or p1_active.get('name', '?'),
        'p2_id':       p2.get('id'), 'p2_name': p2_name,
        'p2_is_npc':   p2.get('is_npc', False),
        'p2_hp':       max(0, p2_active.get('currentHp', 0)) if isinstance(p2_active.get('currentHp'), (int, float)) else '?',
        'p2_maxhp':    p2_active.get('maxHp', '?'),
        'p2_pokemon':  p2_active.get('nickname') or p2_active.get('name', '?'),
    }
    socketio.emit('pvp_master_update', payload, room=f'master_{_tid()}')
    # espectadores da mesa acompanham a batalha (só na fase de luta)
    if battle.get('phase') in ('battle', 'finished'):
        _spectate('pvp', dict(payload,
                              id=battle.get('id'),
                              players=[str(p1.get('id')), str(p2.get('id'))],
                              finished=battle.get('phase') == 'finished'))


def _pvp_field_round_hook(battle):
    """F5: uma vez por rodada PvP — chip de clima, cura de Grassy Terrain,
    tick do 🌱 Leech Seed e durações do campo (idempotente por rodada)."""
    rnd = int(battle.get('round') or 0)
    if rnd <= int(battle.get('_field_round_done') or 0):
        return
    battle['_field_round_done'] = rnd
    # 🌱 Leech Seed: portador perde seed_drain (⌊HPmáx/16⌋), o lado oposto cura o mesmo
    for key, other in (('player1', 'player2'), ('player2', 'player1')):
        side = battle[key]
        poke = side['team'][side['active_idx']]
        if (poke.get('status') or {}).get('condition') != 'seeded':
            continue
        if pvp._poke_hp(poke) <= 0:
            continue
        seed_dmg = effects.seed_drain(poke.get('maxHp'))
        poke['currentHp'] = max(1, int(poke.get('currentHp') or 1) - seed_dmg)
        o_side = battle[other]
        o_poke = o_side['team'][o_side['active_idx']]
        if pvp._poke_hp(o_poke) > 0:
            o_poke['currentHp'] = min(int(o_poke.get('maxHp') or 1),
                                      int(o_poke.get('currentHp') or 0) + seed_dmg)
        battle['log'].append({'type': 'field', 'message':
            f'🌱 {poke.get("nickname") or poke.get("name", "?")} perde {seed_dmg} HP '
            f'pra semente — {o_poke.get("nickname") or o_poke.get("name", "?")} '
            f'recupera {seed_dmg}!'})
    fld = _field_of(battle)
    if not (fld.get('weather') or fld.get('terrain')):
        return
    for key in ('player1', 'player2'):
        side = battle[key]
        poke = side['team'][side['active_idx']]
        if pvp._poke_hp(poke) <= 0:
            continue
        delta, msg = _field_chip(battle, poke, poke.get('maxHp'),
                                 poke.get('nickname') or poke.get('name', key))
        if delta:
            # chip nunca nocauteia (deixa em 1 HP) — o golpe é que decide
            poke['currentHp'] = max(1, min(int(poke.get('maxHp') or 1),
                                           int(poke.get('currentHp') or 0) + delta))
        if msg:
            battle['log'].append({'type': 'field', 'message': msg})
    for m in _field_tick(battle):
        battle['log'].append({'type': 'field', 'message': m})


def _broadcast_pvp_state(battle, event='update'):
    """Envia o estado atual da batalha PVP para os dois lados e para o mestre."""
    if battle.get('phase') == 'battle':
        _pvp_field_round_hook(battle)   # F5: campo tica a cada rodada nova
    for key in ('player1', 'player2'):
        if not battle[key].get('is_npc'):
            state = pvp.get_battle_state_for_player(battle, key)
            socketio.emit('pvp_battle_state', state, room=battle[key]['id'])
    _emit_pvp_to_master(battle, event)


def _is_status_move(move_data):
    """True se o move não causa dano direto (categoria status ou sem baseDamage)."""
    return (move_data.get('category') == 'status') or not move_data.get('baseDamage')


def _npc_pick_move(attacker_poke, defender_poke, defender_has_status=False):
    """IA de escolha de move para NPCs e selvagens.

    Pontua cada move conhecido e sorteia com pesos:
    - Moves super efetivos e com STAB valem mais;
    - Moves em que o alvo é imune quase nunca são usados;
    - Moves de status entram quando o alvo ainda não tem condição;
    - Cura ganha prioridade quando o HP está abaixo de 35%.
    Returns (move_name, move_data, is_status).
    """
    moves = [m for m in (attacker_poke.get('moves') or []) if m] or ['Tackle']
    # F5: se está carregando um golpe (Solar Beam...), dispara ele — trocar
    # de golpe desperdiçaria a rodada de carga
    _charging = (attacker_poke.get('_v3') or {}).get('charging')
    if _charging:
        for m in moves:
            if m.lower() == _charging:
                md = MOVES_BY_NAME.get(m.lower()) or MOVES_DB.get(m) or {}
                return m, md, False
    def_vulns, def_resists, def_immune = _type_lists(defender_poke)
    atk_types   = [t.lower() for t in (attacker_poke.get('types') or [])]

    max_hp = attacker_poke.get('maxHp', 20) or 20
    hp_ratio = max(0, attacker_poke.get('currentHp', max_hp)) / max_hp

    scored = []
    for name in moves:
        # v3: golpes em cooldown ficam fora da escolha da IA
        if _v3_cooldown_left(attacker_poke, name) > 0:
            continue
        md = MOVES_BY_NAME.get(name.lower()) or MOVES_DB.get(name) or {}
        if not md:
            continue
        mtype_raw = (md.get('type') or '').lower()
        mtype = _TYPE_MAP_PT.get(mtype_raw, mtype_raw)

        if _is_status_move(md):
            detected = effects.auto_detect_move_effect(md)
            # a recarga de cura vive num BUCKET compartilhado ('__heal_self__'),
            # não no nome do golpe — sem este filtro a IA insistia num heal
            # bloqueado e o loop de turnos automáticos não avançava
            if (detected and detected.get('type') in ('heal_self', 'drain_stat_heal')
                    and int(((attacker_poke.get('_v3') or {}).get('cooldowns') or {})
                            .get(effects.HEAL_SUSTAIN_KEY, 0)) > 0):
                continue
            if not detected:
                score = 2
            elif detected['type'] in ('heal_self', 'drain_stat_heal'):
                score = 60 if hp_ratio < 0.35 else 1
            elif detected['type'] == 'inflict_status':
                score = 0 if defender_has_status else 22
            elif detected['type'] == 'debuff_target':
                score = 8
            elif detected['type'] == 'buff_self':
                score = 8
            elif detected['type'] == 'fixed_damage':
                score = 18   # dano garantido (ignora CA) — quase tão bom quanto atacar
            else:
                score = 3
        else:
            score = 20
            if mtype in def_immune:
                score = 1
            elif mtype in def_vulns:
                score = 45
            elif mtype in def_resists:
                score = 8
            if mtype in atk_types:
                score += 6  # STAB
        scored.append((max(1, score), name, md))

    if not scored:
        return 'Tackle', MOVES_BY_NAME.get('tackle', {}), False

    total = sum(s for s, _, _ in scored)
    r = random.uniform(0, total)
    acc = 0
    for score, name, md in scored:
        acc += score
        if r <= acc:
            return name, md, _is_status_move(md)
    score, name, md = scored[-1]
    return name, md, _is_status_move(md)


def _process_pvp_status_move(battle, attacker_key, move_name, move_data):
    """Resolve um move de STATUS em batalha PvP (qualquer lado, humano ou NPC).

    Processa pelo motor de efeitos (save vs CD do move), aplica condição/
    debuff no defensor ou buff/cura no atacante, registra no log, avança o
    turno e faz o broadcast. NUNCA causa dano."""
    defender_key = 'player2' if attacker_key == 'player1' else 'player1'
    att_side = battle[attacker_key]
    att_poke = att_side['team'][att_side['active_idx']]
    def_side = battle[defender_key]
    def_poke = def_side['team'][def_side['active_idx']]

    result = effects.process_status_move(
        move_data or {'name': move_name},
        dict(att_poke.get('stats', {}), level=att_poke.get('level', 1),
             proficiency=att_poke.get('proficiency', _prof_for_level(att_poke.get('level', 1))),
             maxHp=att_poke.get('maxHp', 20), types=att_poke.get('types'),
             currentHp=max(0, pvp._poke_hp(att_poke)),
             ability=att_poke.get('ability'),   # Rest × Insomnia
             _v3=_v3_side_state(att_poke)),   # Protect: corrente/flag no dict real
        dict(def_poke.get('stats', {}), level=def_poke.get('level', 1),
             currentHp=max(0, pvp._poke_hp(def_poke)),
             ATK_eff=effects.effective_stat(def_poke, 'ATK')))

    # custo pago pelo próprio usuário (Curse fantasma: ⌊HPmáx/2⌋, nunca desmaia)
    if result.get('self_damage') and result.get('effect_type') != 'fixed_damage':
        att_poke['currentHp'] = max(1, pvp._poke_hp(att_poke) - int(result['self_damage']))

    # v3: cura instantânea em recarga — humano NÃO consome o turno (escolhe
    # outro golpe); NPC (IA) perde a ação e o turno avança (hesitou).
    if result.get('blocked'):
        if battle[attacker_key].get('is_npc'):
            battle['log'].append({'type': 'info',
                                  'message': f'⏳ {move_name} em recarga — o NPC hesitou!'})
            pvp.advance_turn(battle)
            _broadcast_pvp_state(battle)
        elif _v3_sem_opcao(att_poke):
            # RODADA DE FÔLEGO (humano): nada disponível — descansa, turno passa
            battle['log'].append({'type': 'info', 'message': _v3_folego(att_poke)})
            pvp.advance_turn(battle)
            _broadcast_pvp_state(battle)
        else:
            socketio.emit('pvp_error', {
                'battle_id': battle['id'],
                'message': f'⏳ {result.get("message", move_name + " em recarga")}'
            }, room=battle[attacker_key]['id'])
        return result

    # Teleport em batalha de treinador falha (canon gens 1-7) — mensagem clara.
    if result.get('effect_type') == 'flee':
        battle['log'].append({'type': 'status_move', 'attacker': attacker_key,
                              'move': move_name,
                              'message': f'{move_name}! ...mas não funciona em batalha de treinador!'})
        pvp.advance_turn(battle)
        _broadcast_pvp_state(battle)
        return result

    battle['log'].append({'type': 'status_move', 'attacker': attacker_key,
                          'move': move_name, 'message': result.get('message', '')})

    # F5: clima/terreno de campo (Rain Dance, Grassy Terrain...)
    if result.get('effect_type') == 'field':
        _field_apply(battle, result.get('field_kind'), result.get('field_value'),
                     result.get('duration'))
        pvp.advance_turn(battle)
        _broadcast_pvp_state(battle)
        return result

    # Dano fixo (Night Shade/Pain Split/OHKO/Final Gambit...): ignora CA.
    # heal cura o atacante (Pain Split); self_damage fere o atacante (Final
    # Gambit/Perish Song). Dano no defensor via apply_damage (trata desmaio).
    if result.get('effect_type') == 'fixed_damage' and (result.get('damage') or result.get('self_damage')):
        if result.get('heal'):
            att_poke['currentHp'] = min(att_poke.get('maxHp', 20),
                                        max(0, att_poke.get('currentHp', 0)) + result['heal'])
        if result.get('self_damage'):
            att_poke['currentHp'] = max(0, att_poke.get('currentHp', 0) - result['self_damage'])
            if att_poke['currentHp'] <= 0:
                battle['log'].append({'type': 'faint', 'player': attacker_key, 'permadeath': False})
        if result.get('damage'):
            dmg_result = pvp.apply_damage(battle, attacker_key, result['damage'],
                                          move_name, result.get('message', ''))
        else:
            dmg_result = 'continue'
            pvp.advance_turn(battle)
        _handle_pvp_permadeath(battle)
        _broadcast_pvp_state(battle)
        if dmg_result == 'battle_end':
            handle_pvp_victory(battle)
        elif dmg_result == 'must_switch':
            if not battle[defender_key].get('is_npc'):
                socketio.emit('pvp_must_switch', {
                    'battle_id': battle['id'],
                    'message': 'Seu Pokémon desmaiou! Escolha o próximo.'
                }, room=battle[defender_key]['id'])
            else:
                npc_next = pvp.npc_choose_pokemon(battle, defender_key)
                if npc_next is not None:
                    pvp.switch_pokemon(battle, defender_key, npc_next)
                    _broadcast_pvp_state(battle)
        return result

    # Haze: anula os buffs/debuffs acumulados dos DOIS lados
    if result.get('effect_type') == 'reset_stages':
        effects.reset_stat_stages(att_poke)
        effects.reset_stat_stages(def_poke)
        pvp.advance_turn(battle)
        _broadcast_pvp_state(battle)
        return result

    # Operações sobre stages: copy (Psych Up/Transform), swap (Heart Swap),
    # invert (Topsy-Turvy)
    if result.get('effect_type') == 'stage_op':
        op = result.get('op')
        a_st = dict(effects.init_stat_stages(), **(att_poke.get('stat_stages') or {}))
        d_st = dict(effects.init_stat_stages(), **(def_poke.get('stat_stages') or {}))
        if op == 'copy':
            att_poke['stat_stages'] = dict(d_st)
        elif op == 'swap':
            att_poke['stat_stages'], def_poke['stat_stages'] = d_st, a_st
        elif op == 'invert':
            def_poke['stat_stages'] = {k: -v for k, v in d_st.items()}
        pvp.advance_turn(battle)
        _broadcast_pvp_state(battle)
        return result

    if result.get('status_applied'):
        applied = pvp.apply_status(battle, defender_key,
                                   {'condition': result['status_applied']})
        if applied:
            battle['log'].append({'type': 'status_applied', 'player': defender_key,
                                  'status': {'condition': result['status_applied']}})
    if result.get('heal'):
        att_poke['currentHp'] = min(att_poke.get('maxHp', 20),
                                    max(0, att_poke.get('currentHp', 0)) + result['heal'])
    # Rest: o PRÓPRIO usuário adormece (troca o status atual — cura e dorme)
    if result.get('self_status'):
        att_poke['status'] = {'condition': result['self_status'], 'turns_active': 0}
    # Stat stages: debuff no defensor, buff no atacante (persistem no dict do time)
    if result.get('stat_changes'):
        tgt = def_poke if result.get('effect_type') == 'debuff' else att_poke
        effects.apply_stat_changes(tgt, result['stat_changes'])
    pvp.advance_turn(battle)
    _broadcast_pvp_state(battle)
    return result


def handle_npc_turn(battle, npc_key, forced=False):
    """Handle NPC's automatic turn (status próprio, escolha de move, ação).
    forced=True: disparado pelo MESTRE (Forçar Ação) — ignora o modo manual."""
    # Modo MANUAL (auto OFF): a IA do NPC não joga sozinha — o mestre conduz
    # pelo "Forçar Ação" (master_force_npc_action).
    if not forced and not _wild_auto_mode():
        battle['log'].append({'type': 'info',
                              'message': '🎭 Modo manual: NPC aguardando o Mestre (Forçar Ação).'})
        _broadcast_pvp_state(battle)
        socketio.emit('npc_awaiting_master', {
            'battle_id': battle.get('id'), 'npc_key': npc_key,
            'message': '🤖 NPC aguardando ação do Mestre (modo manual).'
        }, room=f'master_{_tid()}')
        return

    defender_key = 'player2' if npc_key == 'player1' else 'player1'

    npc_side  = battle[npc_key]
    npc_poke  = npc_side['team'][npc_side['active_idx']]
    npc_poke.setdefault('defense_mode', _ai_defense_mode(npc_poke))
    def_poke  = battle[defender_key]['team'][battle[defender_key]['active_idx']]

    # Status do próprio NPC no início do turno (dano de veneno/queimadura,
    # sono/congelado/paralisia podem impedir a ação)
    status_dmg, status_info, can_act, status_msgs = pvp.process_turn_status(battle, npc_key)
    if status_dmg > 0:
        battle['log'].append({'type': 'status_damage', 'player': npc_key,
                              'damage': status_dmg, 'status': status_info})
    for m in status_msgs:
        battle['log'].append({'type': 'info', 'message': m})

    if npc_poke.get('currentHp', 0) <= 0:
        # NPC desmaiou pelo próprio status
        battle['log'].append({'type': 'faint', 'player': npc_key, 'permadeath': False})
        npc_next = pvp.npc_choose_pokemon(battle, npc_key)
        if npc_next is not None:
            pvp.switch_pokemon(battle, npc_key, npc_next)
        else:
            battle['phase'] = 'finished'
            battle['winner'] = defender_key
        _broadcast_pvp_state(battle)
        if battle['phase'] == 'finished':
            handle_pvp_victory(battle)
        return

    if not can_act:
        pvp.advance_turn(battle)
        _broadcast_pvp_state(battle)
        return

    if pvp._poke_hp(def_poke) <= 0:
        # Defensor desmaiado aguardando troca — NPC não ataca o corpo.
        # Re-notifica o humano (destrava o cliente e o Forçar Ação do mestre)
        # em vez de retornar em silêncio (era a causa do stall).
        if not battle[defender_key].get('is_npc'):
            socketio.emit('pvp_must_switch', {
                'battle_id': battle['id'],
                'message': 'Seu Pokémon desmaiou! Escolha o próximo.'
            }, room=battle[defender_key]['id'])
        _broadcast_pvp_state(battle)
        return

    move, move_data, is_status = _npc_pick_move(npc_poke, def_poke,
                                                defender_has_status=bool(def_poke.get('status')))

    if is_status and move.lower() not in VARIABLE_DAMAGE_MOVES:
        _process_pvp_status_move(battle, npc_key, move, move_data)
        return

    calc     = _calc_pvp_attack(npc_poke, def_poke, move, field=_field_of(battle))
    damage   = calc['damage']
    move_type = calc.get('move_type_en', '')
    # F5: recoil (nunca nocauteia o usuário) e dreno do golpe do NPC
    if calc.get('recoil'):
        npc_poke['currentHp'] = max(1, npc_poke.get('currentHp', 1) - int(calc['recoil']))
        battle['log'].append({'type': 'info',
                              'message': f"💢 Recoil: {calc['recoil']} de dano em si!"})
    if calc.get('drain_heal'):
        npc_poke['currentHp'] = min(npc_poke.get('maxHp', 20),
                                    npc_poke.get('currentHp', 0) + int(calc['drain_heal']))
        battle['log'].append({'type': 'info',
                              'message': f"💚 Drenou {calc['drain_heal']} HP!"})
    if calc.get('self_status'):
        pvp.apply_status(battle, npc_key, {'condition': calc['self_status']})
    if calc.get('self_ko'):
        npc_poke['currentHp'] = 0
        battle['log'].append({'type': 'faint', 'player': npc_key, 'permadeath': False})

    # Check defender ability
    if damage > 0 and move_type and not battle[defender_key].get('is_npc'):
        def_ability = (def_poke.get('ability') or '').lower()
        if def_ability:
            ab_result = ab.check_defender_ability(
                def_ability, move_type, damage,
                def_poke.get('currentHp', 999), def_poke.get('maxHp', 999)
            )
            if ab_result['triggered']:
                damage = ab_result['modified_damage']
                if ab_result['heal']:
                    def_poke['currentHp'] = min(
                        def_poke.get('maxHp', 999),
                        def_poke.get('currentHp', 0) + ab_result['heal']
                    )
                defender_id = battle[defender_key]['id']
                socketio.emit('ability_triggered', {
                    'message': ab_result['message'], 'blocked': ab_result['blocked'],
                    'heal': ab_result['heal'], 'boost': ab_result['boost'],
                }, room=defender_id)

    # On-hit status do move do NPC (Ember→queimado etc.)
    if damage > 0 and not def_poke.get('status'):
        skey, inflicted = effects.check_status_on_hit(move, 15, damage, defender=def_poke)
        if inflicted:
            if pvp.apply_status(battle, defender_key, {'condition': skey}):
                battle['log'].append({'type': 'status_applied', 'player': defender_key,
                                      'status': {'condition': skey}})

    result = pvp.apply_damage(battle, npc_key, damage, move, calc['message'])

    # Habilidade de contato do defensor reage ao golpe físico do NPC
    if damage > 0 and (MOVES_BY_NAME.get(move.lower()) or {}).get('category', 'physical') == 'physical':
        cres = ab.check_contact_ability(def_poke.get('ability'), def_poke.get('proficiency') or 2)
        # imunidade do atacante (tipo/habilidade) anula a reação de status
        if cres and cres.get('status') and effects.contact_status_blocked(npc_poke, cres['status']):
            cres = None
        if cres:
            if cres['damage']:
                npc_poke['currentHp'] = max(-999, npc_poke.get('currentHp', 0) - cres['damage'])
            if cres['status'] and not npc_poke.get('status'):
                npc_poke['status'] = {'condition': cres['status'], 'turns_active': 0}
            battle['log'].append({'type': 'ability', 'message': cres['message']})
        # Habilidade do ATACANTE (NPC com Poison Touch...) envenena o defensor
        ares = ab.check_attacker_contact_ability(npc_poke.get('ability'))
        if (ares and ares.get('status') and not def_poke.get('status')
                and not effects.contact_status_blocked(def_poke, ares['status'])):
            def_poke['status'] = {'condition': ares['status'], 'turns_active': 0}
            battle['log'].append({'type': 'ability', 'message': ares['message']})

    # permadeath causada pelo NPC (HP ≤ -30) precisa ser processada aqui —
    # senão o Pokémon morto permanente não saía do time do jogador.
    _handle_pvp_permadeath(battle)

    _broadcast_pvp_state(battle, 'npc_attack')

    if result == 'battle_end':
        handle_pvp_victory(battle)
    elif result == 'must_switch':
        if battle[defender_key].get('is_npc'):
            npc_next = pvp.npc_choose_pokemon(battle, defender_key)
            if npc_next is not None:
                pvp.switch_pokemon(battle, defender_key, npc_next)
        else:
            # Defensor HUMANO nocauteado pelo NPC: avisa que precisa trocar
            # (a troca forçada é aceita fora do turno em handle_pvp_switch)
            socketio.emit('pvp_must_switch', {
                'battle_id': battle['id'],
                'message': 'Seu Pokémon desmaiou! Escolha o próximo.'
            }, room=battle[defender_key]['id'])


def handle_pvp_victory(battle):
    """Handle battle end - distribute rewards."""
    # Idempotência: forfeit + ataque fatal simultâneos chamavam isto 2× →
    # prêmio/aposta/avanço de bracket em dobro. Uma liquidação só.
    if battle.get('settled'):
        return
    battle['settled'] = True
    winner_key = battle['winner']
    loser_key = 'player2' if winner_key == 'player1' else 'player1'
    winner_id = battle[winner_key]['id']
    loser_id = battle[loser_key]['id']
    mode = battle['mode']

    users = get_users()
    npcs = db.get_npcs()

    def _party_sheet(pid):
        """Ficha econômica (money/bag/team) do lado: jogador OU NPC.
        NPC devolve o próprio dict do registro — mutações valem de verdade
        (antes, dinheiro perdido para NPC ia para o VAZIO e NPC derrotado
        não soltava espólio nenhum)."""
        if pid in users:
            return users[pid].get('trainer_data', {}), 'user'
        npc = next((n for n in npcs if n['id'] == pid), None)
        if npc is not None:
            _npc_ensure_economy(npc)
            return npc, 'npc'
        return {}, 'ghost'

    winner_trainer, winner_kind = _party_sheet(winner_id)
    loser_trainer, loser_kind = _party_sheet(loser_id)

    rewards = {'money': 0, 'items': []}
    
    if mode == 'official' or mode == 'tournament':
        # A aposta é TRANSFERIDA do perdedor (não cunhada): o vencedor recebe
        # no máximo o que o perdedor REALMENTE tem — sem isso, apostas do
        # cliente criavam dinheiro/itens do nada (o perdedor não perdia nada).
        loser_bet = battle['bets'].get(loser_key, {})
        bet_money = max(0, int(loser_bet.get('money', 0) or 0))
        moved_money = min(bet_money, max(0, int(loser_trainer.get('money', 0) or 0)))
        loser_trainer['money'] = max(0, loser_trainer.get('money', 0) - moved_money)
        winner_trainer['money'] = winner_trainer.get('money', 0) + moved_money

        moved_items = []
        loser_bag = loser_trainer.get('bag', [])
        for item in (loser_bet.get('items', []) or []):
            name = (item.get('name') or '').lower()
            want = max(0, int(item.get('qty', 1) or 1))
            if not name or want <= 0:
                continue
            # só move o que o perdedor tem de fato na bolsa
            for bi in loser_bag:
                if isinstance(bi, dict) and bi.get('name', '').lower() == name:
                    take = min(want, int(bi.get('qty', 0) or 0))
                    if take <= 0:
                        break
                    bi['qty'] = int(bi.get('qty', 0)) - take
                    moved_items.append({'name': bi.get('name'), 'qty': take,
                                        'description': bi.get('description', '')})
                    break
        loser_trainer['bag'] = [b for b in loser_bag
                                if not (isinstance(b, dict) and int(b.get('qty', 0) or 0) <= 0)]
        winner_bag = winner_trainer.get('bag', [])
        for item in moved_items:
            for bi in winner_bag:
                if isinstance(bi, dict) and bi.get('name', '').lower() == item['name'].lower():
                    bi['qty'] = bi.get('qty', 1) + item['qty']
                    break
            else:
                winner_bag.append(dict(item))
        winner_trainer['bag'] = winner_bag

        rewards = {'money': moved_money, 'items': moved_items}
    
    elif mode == 'street':
        # Winner steals 25% money + 2 random items
        stolen_money, stolen_items = pvp.calculate_street_loot(loser_trainer)
        
        loser_trainer['money'] = max(0, loser_trainer.get('money', 0) - stolen_money)
        winner_trainer['money'] = winner_trainer.get('money', 0) + stolen_money
        
        # Remove stolen items from loser
        loser_bag = loser_trainer.get('bag', [])
        for si in stolen_items:
            for i, bi in enumerate(loser_bag):
                if isinstance(bi, dict) and bi.get('name', '').lower() == si['name'].lower():
                    bi['qty'] = bi.get('qty', 1) - 1
                    if bi['qty'] <= 0:
                        loser_bag.pop(i)
                    break
        loser_trainer['bag'] = loser_bag
        
        # Add to winner
        winner_bag = winner_trainer.get('bag', [])
        for si in stolen_items:
            added = False
            for bi in winner_bag:
                if isinstance(bi, dict) and bi.get('name', '').lower() == si['name'].lower():
                    bi['qty'] = bi.get('qty', 1) + 1
                    added = True
                    break
            if not added:
                winner_bag.append(si)
        winner_trainer['bag'] = winner_bag
        
        rewards = {'money': stolen_money, 'items': stolen_items}
    
    # Increment battle_wins on winner's active Pokémon
    winner_team = winner_trainer.get('team', [])
    winner_active_idx = battle.get(winner_key, {}).get('active_idx')
    if winner_active_idx is not None and winner_active_idx < len(winner_team):
        winner_team[winner_active_idx]['battle_wins'] = winner_team[winner_active_idx].get('battle_wins', 0) + 1
    winner_trainer['team'] = winner_team

    # Save — cada lado no seu armazenamento (jogador em users, NPC em npcs)
    if winner_kind == 'user':
        users[winner_id]['trainer_data'] = winner_trainer
    elif winner_kind == 'npc':
        db.save_npc(winner_trainer)
    if loser_kind == 'user':
        users[loser_id]['trainer_data'] = loser_trainer
    elif loser_kind == 'npc':
        db.save_npc(loser_trainer)
    save_users(users)
    
    # Notify players (NPC usa o nome do registro; jogador, o username)
    winner_name = (users.get(winner_id, {}).get('username')
                   or (winner_trainer.get('name') if winner_kind == 'npc' else None) or '???')
    loser_name = (users.get(loser_id, {}).get('username')
                  or (loser_trainer.get('name') if loser_kind == 'npc' else None) or '???')
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner': winner_key,
        'winner_name': winner_name,
        'loser_name': loser_name,
        'mode': mode,
        'rewards': rewards
    }, room=winner_id)
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner': winner_key,
        'winner_name': winner_name,
        'loser_name': loser_name,
        'mode': mode,
        'lost': rewards
    }, room=loser_id)
    socketio.emit('pvp_battle_ended', {
        'battle_id': battle['id'],
        'winner_name': winner_name,
        'mode': mode
    }, room=f'master_{_tid()}')
    
    _emit_pvp_to_master(battle, 'battle_ended')

    # Auto-report tournament result
    tourney_id  = battle.get('tournament_id')
    match_id_bt = battle.get('tournament_match_id')
    if tourney_id and match_id_bt:
        tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
        if tournament:
            winner_participant_id = battle[winner_key]['id']
            _apply_tournament_match_result(tournament, tourney_id, match_id_bt, winner_participant_id)

    # Cleanup
    if battle['id'] in ACTIVE_PVP:
        del ACTIVE_PVP[battle['id']]

# ============================================================
# PLAYER-TO-PLAYER TRANSFERS (Money & Items)
# ============================================================
@app.route('/player/transfer', methods=['POST'])
@login_required
def transfer_assets():
    """Transfer money and/or items from current player to another player."""
    data = request.json
    target_id = data.get('target_id')
    # quantidades NEGATIVAS forjavam duplicação (perdedor virava 1-(-100)=101x)
    # e drenavam o alvo — pisos em 0.
    money_amount = max(0, int(data.get('money', 0) or 0))
    items_to_send = data.get('items', [])  # list of {name, qty, file}

    if not target_id or target_id == current_user.id:
        return jsonify({'error': 'Alvo inválido'}), 400

    users = get_users()
    sender = users.get(current_user.id)
    receiver = users.get(target_id)

    if not sender or not receiver:
        return jsonify({'error': 'Player not found'}), 404
    # só transfere para jogador da MESMA mesa
    if sender.get('table_id') != receiver.get('table_id'):
        return jsonify({'error': 'Jogador não pertence à sua mesa'}), 403
    
    sender_trainer = sender.get('trainer_data', {})
    receiver_trainer = receiver.get('trainer_data', {})
    
    # Validate money
    if money_amount > 0:
        sender_money = sender_trainer.get('money', 0)
        if sender_money < money_amount:
            return jsonify({'error': f'Dinheiro insuficiente. Você tem ₽{sender_money}'}), 400
        sender_trainer['money'] = sender_money - money_amount
        receiver_trainer['money'] = receiver_trainer.get('money', 0) + money_amount
    
    # Validate and transfer items
    sender_bag = sender_trainer.get('bag', [])
    receiver_bag = receiver_trainer.get('bag', [])
    
    for item in items_to_send:
        item_name = item.get('name', '')
        item_qty = max(1, int(item.get('qty', 1) or 1))   # nunca ≤ 0
        item_file = item.get('file', '')

        # Find item in sender's bag
        found = False
        for i, bag_item in enumerate(sender_bag):
            bag_name = bag_item.get('name', '') if isinstance(bag_item, dict) else bag_item
            if bag_name.lower() == item_name.lower():
                bag_qty = bag_item.get('qty', 1) if isinstance(bag_item, dict) else 1
                if bag_qty < item_qty:
                    return jsonify({'error': f'Quantidade insuficiente de {item_name}'}), 400
                # Remove from sender
                if bag_qty == item_qty:
                    sender_bag.pop(i)
                else:
                    sender_bag[i]['qty'] = bag_qty - item_qty
                found = True
                break
        
        if not found:
            return jsonify({'error': f'Item {item_name} não encontrado na sua bolsa'}), 400
        
        # Add to receiver
        added = False
        for bag_item in receiver_bag:
            if isinstance(bag_item, dict) and bag_item.get('name', '').lower() == item_name.lower():
                bag_item['qty'] = bag_item.get('qty', 1) + item_qty
                added = True
                break
        if not added:
            receiver_bag.append({'name': item_name, 'qty': item_qty, 'file': item_file})
    
    sender_trainer['bag'] = sender_bag
    receiver_trainer['bag'] = receiver_bag
    users[current_user.id]['trainer_data'] = sender_trainer
    users[target_id]['trainer_data'] = receiver_trainer
    save_users(users)
    
    # Notify both players in real-time
    transfer_msg = []
    if money_amount > 0:
        transfer_msg.append(f'₽{money_amount}')
    if items_to_send:
        transfer_msg.append(', '.join([f"{i['qty']}x {i['name']}" for i in items_to_send]))
    
    socketio.emit('transfer_received', {
        'from': current_user.username,
        'message': ' + '.join(transfer_msg),
        'money': money_amount,
        'items': items_to_send
    }, room=target_id)
    
    return jsonify({
        'success': True,
        'new_money': sender_trainer['money'],
        'message': f'Transferido {" + ".join(transfer_msg)} para {receiver["username"]}'
    })

@app.route('/api/players')
@login_required
def api_players_list():
    """List all players (for transfers/PVP)."""
    users = get_users()
    players = []
    for uid, u in users.items():
        if u['role'] == 'player' and uid != current_user.id:
            trainer = u.get('trainer_data', {})
            players.append({
                'id': uid,
                'name': trainer.get('name', u['username']),
                'username': u['username'],
                'level': trainer.get('level', 1)
            })
    return jsonify(players)

# ============================================================
# TOURNAMENT MANAGEMENT
# ============================================================
@app.route('/master/tournament', methods=['POST'])
@login_required
def create_tournament_route():
    """Create a new tournament."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    name = data.get('name', 'Campeonato')
    max_participants = int(data.get('max_participants', 16))
    prizes = {
        'first': {'money': int(data.get('prize_1_money', 0)), 'extra': data.get('prize_extra', '')},
        'second': {'money': int(data.get('prize_2_money', 0))},
        'third': {'money': int(data.get('prize_3_money', 0))},
        'places': int(data.get('prize_places', 3))
    }
    tournament = pvp.create_tournament(name, prizes, max_participants)
    ACTIVE_TOURNAMENTS[tournament['id']] = tournament
    return jsonify(tournament)

@app.route('/master/tournament/<tourney_id>/participants', methods=['POST'])
@login_required
def add_tournament_participant(tourney_id):
    """Add a participant (player or NPC) to tournament."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404
    if tournament['status'] != 'registration':
        return jsonify({'error': 'Tournament already started'}), 400
    
    data = request.json
    participant_type = data.get('type', 'player')  # 'player' or 'npc'
    
    if participant_type == 'player':
        player_id = data.get('player_id')
        users = get_users()
        if player_id not in users:
            return jsonify({'error': 'Player not found'}), 404
        user = users[player_id]
        trainer = user.get('trainer_data', {})
        participant = {
            'id': player_id,
            'name': trainer.get('name', user['username']),
            'is_npc': False,
            'team': trainer.get('team', [])
        }
    else:
        npc_id = data.get('npc_id')
        npcs = db.get_npcs()
        npc = next((n for n in npcs if n.get('id') == npc_id), None)
        if not npc:
            return jsonify({'error': 'NPC not found'}), 404
        participant = {
            'id': f"npc_{npc['id']}",
            'name': npc['name'],
            'is_npc': True,
            'team': npc.get('team', [])
        }
    
    # Check if already registered
    if any(p['id'] == participant['id'] for p in tournament['participants']):
        return jsonify({'error': 'Já registrado'}), 400
    
    if len(tournament['participants']) >= tournament['max_participants']:
        return jsonify({'error': 'Campeonato lotado'}), 400
    
    tournament['participants'].append(participant)
    return jsonify({'success': True, 'participants': tournament['participants']})

@app.route('/master/tournament/<tourney_id>/start', methods=['POST'])
@login_required
def start_tournament_route(tourney_id):
    """Start the tournament - generate bracket."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404
    if len(tournament['participants']) < 2:
        return jsonify({'error': 'Mínimo 2 participantes'}), 400
    
    bracket = pvp.generate_bracket(tournament)

    payload = {
        'tournament_id': tourney_id,
        'name': tournament['name'],
        'bracket': bracket,
        'status': tournament['status'],
        'current_round': tournament['current_round'],
        'participants_count': len(tournament['participants'])
    }
    socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
    socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')

    return jsonify({'success': True, 'bracket': bracket})

@app.route('/master/tournament/<tourney_id>/bracket')
@login_required
def get_tournament_bracket(tourney_id):
    """Get current bracket state."""
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(tournament)

@app.route('/api/natures')
@login_required
def api_natures():
    """List all natures with their stat modifiers."""
    return jsonify(scaling.NATURE_MODIFIERS)

@app.route('/api/tournament/active')
@login_required
def get_active_tournament():
    """Get the current active tournament (for players to poll on load)."""
    for t in ACTIVE_TOURNAMENTS.values():
        if t['status'] in ('in_progress', 'registration'):
            return jsonify(t)
    return jsonify(None)

def _apply_tournament_match_result(tournament, tourney_id, match_id, winner_id):
    """Core logic: record match winner, advance bracket, emit updates. Returns status string."""
    for match in tournament['bracket']:
        if match['id'] == match_id:
            if match['winner']:
                return 'already_decided'
            match['winner'] = winner_id
            break

    current_round = tournament['current_round']
    round_matches = [m for m in tournament['bracket'] if m['round'] == current_round]
    all_decided = all(m['winner'] is not None for m in round_matches)

    if not all_decided:
        socketio.emit('tournament_bracket_update', {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': current_round
        }, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': current_round
        }, room=f'master_{_tid()}')
        return 'round_in_progress'

    # Round complete — compute winners list
    winners = []
    for m in round_matches:
        wp = m['player1'] if m['player1'] and m['player1']['id'] == m['winner'] else m['player2']
        if wp:
            winners.append(wp)

    if len(winners) <= 1:
        tournament['status'] = 'finished'
        tournament['results'] = {
            'first': winners[0] if winners else None,
            'second': None,
            'third': None
        }
        final_match = round_matches[0] if round_matches else None
        if final_match:
            loser = final_match['player1'] if final_match['player1'] and final_match['player1']['id'] != final_match['winner'] else final_match['player2']
            tournament['results']['second'] = loser
        award_tournament_prizes(tournament)

        payload = {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': 'finished',
            'current_round': tournament['current_round'],
            'results': tournament['results']
        }
        socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')
        return 'finished'
    else:
        next_round = current_round + 1
        for i in range(0, len(winners), 2):
            new_match = {
                'id': f"match_{secrets.token_hex(3)}",
                'round': next_round,
                'player1': winners[i],
                'player2': winners[i + 1] if i + 1 < len(winners) else None,
                'winner': None,
                'battle_id': None
            }
            if new_match['player2'] is None:
                new_match['winner'] = new_match['player1']['id']
            tournament['bracket'].append(new_match)
        tournament['current_round'] = next_round

        payload = {
            'tournament_id': tourney_id,
            'name': tournament['name'],
            'bracket': tournament['bracket'],
            'status': tournament['status'],
            'current_round': next_round
        }
        socketio.emit('tournament_bracket_update', payload, room=f'players_{_tid()}')
        socketio.emit('tournament_bracket_update', payload, room=f'master_{_tid()}')
        return 'next_round'


@app.route('/master/tournament/<tourney_id>/match/<match_id>/result', methods=['POST'])
@login_required
def set_match_result(tourney_id, match_id):
    """Set the winner of a tournament match (manual override by master)."""
    if current_user.role != 'master':
        return jsonify({'error': 'Unauthorized'}), 403
    tournament = ACTIVE_TOURNAMENTS.get(tourney_id)
    if not tournament:
        return jsonify({'error': 'Tournament not found'}), 404

    data = request.json
    winner_id = data.get('winner_id')
    status = _apply_tournament_match_result(tournament, tourney_id, match_id, winner_id)

    if status == 'finished':
        return jsonify({'success': True, 'status': 'finished', 'results': tournament['results']})
    return jsonify({'success': True, 'bracket': tournament['bracket']})


def award_tournament_prizes(tournament):
    """Award prizes to tournament winners."""
    prizes = tournament.get('prizes', {})
    results = tournament.get('results', {})
    users = get_users()
    
    placements = [('first', results.get('first')), ('second', results.get('second')), ('third', results.get('third'))]
    max_places = prizes.get('places', 3)
    
    for i, (place, participant) in enumerate(placements):
        if i >= max_places or not participant or participant.get('is_npc'):
            continue
        player_id = participant['id']
        if player_id in users:
            trainer = users[player_id].get('trainer_data', {})
            prize_money = prizes.get(place, {}).get('money', 0)
            if prize_money > 0:
                trainer['money'] = trainer.get('money', 0) + prize_money
            users[player_id]['trainer_data'] = trainer
            
            socketio.emit('tournament_prize', {
                'tournament': tournament['name'],
                'place': place,
                'money': prize_money,
                'extra': prizes.get('first', {}).get('extra', '') if place == 'first' else ''
            }, room=player_id)
    
    save_users(users)

# ============================================================
# GYMS
# ============================================================

@app.route('/api/gyms')
@login_required
def api_get_gyms():
    gyms = db.get_gyms()
    # Attach conquered status per player
    if current_user.role == 'player':
        trainer = get_users().get(current_user.id, {}).get('trainer_data', {})
        badges = trainer.get('badges', [])
        for g in gyms:
            g['conquered'] = g['badge_name'] in badges
    return jsonify(gyms)


@app.route('/api/gyms', methods=['POST'])
@login_required
def api_create_gym():
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    data = request.json or {}
    required = ['name', 'badge_name', 'type', 'leader_name']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'Campo obrigatório: {f}'}), 400

    gyms = db.get_gyms()
    gym_id = f"gym_{secrets.token_hex(4)}"
    gym = {
        'id': gym_id,
        'name': data['name'],
        'badge_name': data['badge_name'],
        'badge_icon': data.get('badge_icon', '🏅'),
        'type': data['type'],
        'leader_name': data['leader_name'],
        'leader_npc_id': data.get('leader_npc_id'),
        'leader_player_id': data.get('leader_player_id'),
        'required_badges': data.get('required_badges', []),
        'level_cap': int(data.get('level_cap', 5)),
        'order': len(gyms) + 1,
        'description': data.get('description', ''),
        'active_battles': {}
    }
    gyms.append(gym)
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify(gym), 201


@app.route('/api/gyms/<gym_id>', methods=['PUT'])
@login_required
def api_update_gym(gym_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return jsonify({'error': 'Ginásio não encontrado'}), 404
    data = request.json or {}
    for field in ['name', 'badge_name', 'badge_icon', 'type', 'leader_name',
                  'leader_npc_id', 'leader_player_id', 'required_badges',
                  'level_cap', 'order', 'description']:
        if field in data:
            gym[field] = data[field]
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify(gym)


@app.route('/api/gyms/<gym_id>', methods=['DELETE'])
@login_required
def api_delete_gym(gym_id):
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    gyms = db.get_gyms()
    gyms = [g for g in gyms if g['id'] != gym_id]
    db.save_gyms(gyms)
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'players_{_tid()}')
    socketio.emit('gyms_updated', {'gyms': gyms}, room=f'master_{_tid()}')
    return jsonify({'ok': True})


@socketio.on('gym_challenge')
@login_required
def handle_gym_challenge(data):
    """Player challenges a gym. Creates an official PVP battle vs leader."""
    gym_id = data.get('gym_id')
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        emit('gym_error', {'msg': 'Ginásio não encontrado'})
        return

    # Check badge requirements
    users = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    badges = trainer.get('badges', [])
    for req in gym.get('required_badges', []):
        if req not in badges:
            emit('gym_error', {'msg': f'Você precisa da insígnia "{req}" antes de desafiar este ginásio.'})
            return

    # Check if already conquered
    if gym['badge_name'] in badges:
        emit('gym_error', {'msg': 'Você já conquistou esta insígnia!'})
        return

    # Determine leader
    leader_npc_id   = gym.get('leader_npc_id')
    leader_player_id = gym.get('leader_player_id')

    if leader_player_id and leader_player_id in users:
        # Human leader — send challenge invite
        battle_id = f"gym_{gym_id}_{secrets.token_hex(4)}"
        pending = {
            'battle_id': battle_id,
            'gym_id': gym_id,
            'gym_name': gym['name'],
            'challenger_id': current_user.id,
            'challenger_name': trainer.get('name', current_user.username)
        }
        socketio.emit('gym_challenge_incoming', pending, room=leader_player_id)
        emit('gym_challenge_sent', {'msg': f'Desafio enviado para {gym["leader_name"]}!'})
        return

    # NPC leader
    npcs = db.get_npcs()
    npc = next((n for n in npcs if n['id'] == leader_npc_id), None) if leader_npc_id else None

    if not npc:
        npc = {'id': f'npc_leader_{gym_id}', 'name': gym['leader_name'], 'team': [], 'is_npc': True}

    battle = pvp.create_pvp_battle('official', current_user.id, npc['id'])
    battle['gym_id']    = gym_id
    battle['gym_badge'] = gym['badge_name']
    battle['gym_icon']  = gym.get('badge_icon', '🏅')
    battle['extra']     = {'gym_id': gym_id, 'gym_badge': gym['badge_name'], 'gym_icon': gym.get('badge_icon', '🏅')}
    _mig(trainer.get('team', []))
    _stamp_tatica(trainer.get('team', []), trainer)
    pvp.set_team(battle, 'player1', trainer.get('team', []))
    _mig(npc.get('team', []))
    pvp.set_team(battle, 'player2', npc.get('team', []))
    battle['player2']['is_npc'] = True
    if npc.get('team'):
        pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle

    emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': gym['leader_name'],
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    })


@socketio.on('gym_challenge_accept')
@login_required
def handle_gym_challenge_accept(data):
    """Human leader accepts a gym challenge."""
    gym_id       = data.get('gym_id')
    challenger_id = data.get('challenger_id')
    gyms = db.get_gyms()
    gym = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return

    users = get_users()
    challenger_trainer = users.get(challenger_id, {}).get('trainer_data', {})
    leader_trainer     = users.get(current_user.id, {}).get('trainer_data', {})

    battle = pvp.create_pvp_battle('official', challenger_id, current_user.id)
    battle['extra'] = {'gym_id': gym_id, 'gym_badge': gym['badge_name'], 'gym_icon': gym.get('badge_icon', '🏅')}
    pvp.set_team(battle, 'player1', challenger_trainer.get('team', []))
    pvp.set_team(battle, 'player2', leader_trainer.get('team', []))
    ACTIVE_PVP[battle['id']] = battle

    challenger_name = challenger_trainer.get('name', users[challenger_id]['username'])
    leader_name_str = leader_trainer.get('name', current_user.username)
    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': gym['leader_name'],
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     challenger_trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    }, room=challenger_id)
    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': challenger_name,
        'mode':          'official',
        'gym_id':        gym_id,
        'gym_name':      gym['name'],
        'your_team':     leader_trainer.get('team', []),
        'you_are':       'player2',
        'phase':         'selection'
    }, room=current_user.id)


def _award_gym_badge(winner_id, gym_id):
    """Called after gym battle is won. Awards badge and XP multiplier."""
    gyms = db.get_gyms()
    gym  = next((g for g in gyms if g['id'] == gym_id), None)
    if not gym:
        return

    users = get_users()
    if winner_id not in users:
        return

    trainer = users[winner_id].get('trainer_data', {})
    badges  = trainer.get('badges', [])
    badge   = gym['badge_name']

    if badge not in badges:
        badges.append(badge)
        trainer['badges'] = badges
        users[winner_id]['trainer_data'] = trainer
        save_users(users)

        socketio.emit('badge_awarded', {
            'gym_id':    gym_id,
            'gym_name':  gym['name'],
            'badge':     badge,
            'icon':      gym.get('badge_icon', '🏅'),
            'badges_total': len(badges)
        }, room=winner_id)

        socketio.emit('master_action', {
            'type': 'badge_awarded',
            'player': trainer.get('name', users[winner_id]['username']),
            'badge': badge,
            'gym': gym['name']
        }, room=f'master_{_tid()}')


# ============================================================
# LEAGUE
# ============================================================

@app.route('/api/league')
@login_required
def api_get_league():
    league = db.get_league()
    if current_user.role == 'player':
        run = league.get('active_runs', {}).get(current_user.id)
        return jsonify({'slots': league.get('slots', []), 'my_run': run})
    return jsonify(league)


@app.route('/api/league/slots', methods=['POST'])
@login_required
def api_save_league_slots():
    if current_user.role != 'master':
        return jsonify({'error': 'Acesso negado'}), 403
    data = request.json or {}
    league = db.get_league()
    league['slots'] = data.get('slots', [])
    db.save_league(league)
    socketio.emit('league_updated', {'slots': league['slots']}, room=f'players_{_tid()}')
    socketio.emit('league_updated', {'slots': league['slots']}, room=f'master_{_tid()}')
    return jsonify({'ok': True})


@socketio.on('league_challenge_start')
@login_required
def handle_league_start(data):
    """Player starts a League run. Must have all required badges."""
    league = db.get_league()
    slots  = league.get('slots', [])
    if not slots:
        emit('league_error', {'msg': 'A Liga ainda não foi configurada pelo Mestre.'})
        return

    users   = get_users()
    trainer = users.get(current_user.id, {}).get('trainer_data', {})
    badges  = trainer.get('badges', [])

    # Check all gym badges that have "required_for_league" or just all gym badges
    gyms = db.get_gyms()
    gym_badges = [g['badge_name'] for g in gyms]
    missing = [b for b in gym_badges if b not in badges]
    if missing:
        emit('league_error', {'msg': f'Você ainda precisa das insígnias: {", ".join(missing)}'})
        return

    # Check if already has an active run
    active_runs = league.get('active_runs', {})
    if current_user.id in active_runs and active_runs[current_user.id].get('status') == 'in_progress':
        emit('league_error', {'msg': 'Você já tem uma tentativa em andamento!'})
        return

    run = {
        'player_id':   current_user.id,
        'player_name': trainer.get('name', current_user.username),
        'current_slot': 0,
        'status':       'in_progress',
        'battle_id':    None
    }
    active_runs[current_user.id] = run
    league['active_runs'] = active_runs
    db.save_league(league)
    emit('league_run_started', {'run': run, 'slots': slots})
    _start_league_battle(current_user.id, 0)


def _start_league_battle(player_id, slot_index):
    """Creates a battle between the player and the current league slot opponent."""
    league = db.get_league()
    slots  = league.get('slots', [])
    if slot_index >= len(slots):
        return

    slot = slots[slot_index]
    users = get_users()
    trainer = users.get(player_id, {}).get('trainer_data', {})

    leader_player_id = slot.get('leader_player_id')
    leader_npc_id    = slot.get('leader_npc_id')

    if leader_player_id and leader_player_id in users:
        leader_trainer = users[leader_player_id].get('trainer_data', {})
        leader_team    = leader_trainer.get('team', [])
        leader_name    = leader_trainer.get('name', users[leader_player_id]['username'])
        is_npc_battle  = False
        opponent_id    = leader_player_id
    else:
        npcs = db.get_npcs()
        npc  = next((n for n in npcs if n['id'] == leader_npc_id), None) if leader_npc_id else None
        if not npc:
            npc = {'id': f'npc_league_{slot_index}', 'name': slot.get('leader_name', f'Elite {slot_index+1}'), 'team': [], 'is_npc': True}
        leader_team   = npc.get('team', [])
        leader_name   = npc.get('name', slot.get('leader_name', f'Membro da Liga {slot_index+1}'))
        is_npc_battle = True
        opponent_id   = npc['id']

    battle = pvp.create_pvp_battle('official', player_id, opponent_id)
    battle['extra'] = {
        'league_slot':  slot_index,
        'league_total': len(slots),
        'slot_title':   slot.get('title', f'Membro {slot_index+1}'),
        'is_champion':  slot.get('is_champion', False)
    }
    _mig(trainer.get('team', []))
    pvp.set_team(battle, 'player1', trainer.get('team', []))
    pvp.set_team(battle, 'player2', leader_team)
    if is_npc_battle:
        battle['player2']['is_npc'] = True
        if leader_team:
            pvp.select_pokemon(battle, 'player2', 0)

    ACTIVE_PVP[battle['id']] = battle

    # Store battle_id in run
    league['active_runs'][player_id]['battle_id'] = battle['id']
    db.save_league(league)

    socketio.emit('pvp_battle_created', {
        'battle_id':     battle['id'],
        'opponent_name': leader_name,
        'mode':          'official',
        'league_slot':   slot_index,
        'slot_title':    slot.get('title', f'Membro {slot_index+1}'),
        'is_champion':   slot.get('is_champion', False),
        'your_team':     trainer.get('team', []),
        'you_are':       'player1',
        'phase':         'selection'
    }, room=player_id)

    if not is_npc_battle:
        socketio.emit('pvp_battle_created', {
            'battle_id':     battle['id'],
            'opponent_name': trainer.get('name', users[player_id]['username']),
            'mode':          'official',
            'league_slot':   slot_index,
            'your_team':     leader_team,
            'you_are':       'player2',
            'phase':         'selection'
        }, room=opponent_id)


# Patch handle_pvp_victory to handle gym and league battles
_original_handle_pvp_victory = handle_pvp_victory  # noqa: F821


def _extended_handle_pvp_victory(battle):
    """Wraps the original pvp victory handler to also process gym/league results."""
    extra = battle.get('extra', {})
    winner_key = battle.get('winner', 'player1')
    winner_id  = battle.get(winner_key, {}).get('id') if winner_key in battle else None

    player1_id = battle.get('player1', {}).get('id')

    # Gym battle
    if extra.get('gym_id'):
        # Only award if the challenger (player1) won
        if winner_id == player1_id:
            _award_gym_badge(winner_id, extra['gym_id'])

    # League battle
    league_slot = extra.get('league_slot')
    if league_slot is not None:
        player_id = player1_id
        league    = db.get_league()
        run       = league.get('active_runs', {}).get(player_id)
        if run and run.get('status') == 'in_progress':
            slots = league.get('slots', [])
            if winner_id == player_id:
                next_slot = league_slot + 1
                if next_slot >= len(slots):
                    # Champion defeated — league cleared!
                    run['status']       = 'completed'
                    run['current_slot'] = next_slot
                    league['active_runs'][player_id] = run
                    db.save_league(league)
                    socketio.emit('league_completed', {
                        'player_name': run['player_name']
                    }, room=f'players_{_tid()}')
                    socketio.emit('league_completed', {
                        'player_name': run['player_name']
                    }, room=f'master_{_tid()}')
                    socketio.emit('league_victory', {
                        'slots_total': len(slots)
                    }, room=player_id)
                else:
                    run['current_slot'] = next_slot
                    run['battle_id']    = None
                    league['active_runs'][player_id] = run
                    db.save_league(league)
                    socketio.emit('league_next_battle', {
                        'slot': next_slot,
                        'slot_title': slots[next_slot].get('title', f'Membro {next_slot+1}'),
                        'is_champion': slots[next_slot].get('is_champion', False),
                        'total': len(slots)
                    }, room=player_id)
                    _start_league_battle(player_id, next_slot)
            else:
                # Player lost — reset run
                run['status'] = 'failed'
                league['active_runs'][player_id] = run
                db.save_league(league)
                socketio.emit('league_failed', {
                    'slot': league_slot,
                    'slot_title': extra.get('slot_title', '')
                }, room=player_id)

    _original_handle_pvp_victory(battle)


# Replace the global reference used by socket handlers
handle_pvp_victory = _extended_handle_pvp_victory  # noqa: F811

# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    # Create default master account if no users exist
    users = get_users()
    if not users:
        master_id = secrets.token_hex(8)
        users[master_id] = {
            'username': 'mestre',
            'password_hash': generate_password_hash('mestre123'),
            'role': 'master',
            'trainer_data': {}
        }
        save_users(users)
        print("=== Conta do Mestre criada ===")
        print("Usuario: mestre")
        print("Senha: mestre123")
        print("==============================")
    
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('RENDER') is None  # debug only locally
    
    print(f"\n🎮 Pokemon 5e RPG - Servidor iniciado!")
    print(f"Acesse: http://localhost:{port}\n")
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
else:
    # When imported by gunicorn, still create default user
    users = get_users()
    if not users:
        master_id = secrets.token_hex(8)
        users[master_id] = {
            'username': 'mestre',
            'password_hash': generate_password_hash('mestre123'),
            'role': 'master',
            'trainer_data': {}
        }
        save_users(users)
