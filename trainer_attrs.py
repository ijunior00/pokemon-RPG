# trainer_attrs.py — os 6 ATRIBUTOS DO TREINADOR (substituem FOR/DES/CON/
# INT/SAB/CAR do D&D) + 13 perícias, com migração automática de fichas
# antigas.
#
# Escala: 1-20 com modificador (valor - 10) // 2, como o jogador já conhece.
# Sorte é DERIVADA: teste = d20 + mod(Determinação)//2 + proficiência (se
# tiver) — Determinação continua o atributo principal e Sorte fica rara.
ATTRS_VERSION = 2

# chave interna -> (emoji, nome exibido)
ATTRIBUTES = {
    'vinculo':      ('❤️', 'Vínculo'),
    'tatica':       ('♟️', 'Tática'),
    'conhecimento': ('📖', 'Conhecimento'),
    'agilidade':    ('🏃', 'Agilidade'),
    'influencia':   ('👑', 'Influência'),
    'determinacao': ('🔥', 'Determinação'),
}

# Migração: preserva o investimento das fichas antigas.
# SAB (captura/adestrar) → Vínculo, que segue mandando na captura;
# CAR (loja)             → Influência, que segue mandando na loja.
LEGACY_MAP = {
    'wis': 'vinculo',
    'str': 'tatica',
    'int': 'conhecimento',
    'dex': 'agilidade',
    'cha': 'influencia',
    'con': 'determinacao',
}

# perícia -> (atributo, emoji, descrição curta)
SKILLS = {
    'Afinidade':   ('vinculo', '💞', 'Captura, obediência, confiança e humor da equipe'),
    'Ressonância': ('vinculo', '🔮', 'Mega Evolução, Z-Moves, evoluções por amizade e Anima'),
    'Análise':     ('tatica', '🔍', 'Ler o oponente: habilidades, fraquezas e padrões'),
    'Comando':     ('tatica', '📢', 'Coordenar em combate: combos, trocas e ritmo'),
    'Pesquisa':    ('conhecimento', '📚', 'Espécies, tipos, habitats, ruínas, lendas'),
    'Cuidados':    ('conhecimento', '🩹', 'Medicina Pokémon, status negativos e itens médicos'),
    'Atletismo':   ('agilidade', '💪', 'Corrida, natação, escalada, saltos, resistência'),
    'Exploração':  ('agilidade', '🧭', 'Rastreamento, navegação, furtividade, sobrevivência'),
    'Diplomacia':  ('influencia', '🤝', 'Persuasão, acordos, mediação com NPCs'),
    'Presença':    ('influencia', '✨', 'Liderança, intimidação, inspiração, competições'),
    'Coragem':     ('determinacao', '🦁', 'Medo, confrontos perigosos, eventos da Anima'),
    'Resiliência': ('determinacao', '🛡️', 'Dor, pressão, fadiga e recuperação psicológica'),
    'Sorte':       ('determinacao', '🍀', 'O acaso decide: usa METADE do mod de Determinação'),
}

# Perícias com proficiência: 2 de graça + 1 extra nos níveis 5/9/13/17
BASE_PROFS = 2
EXTRA_PROF_LEVELS = (5, 9, 13, 17)

# Distribuição de pontos dos atributos (point-buy do treinador):
# todos começam em 10; 20 pontos livres; teto 16 por atributo; 1 ponto = +1.
POINT_BUY_BASE = 10
POINT_BUY_MAX = 16
POINT_BUY_BUDGET = 20


def points_spent(trainer):
    """Quantos pontos de point-buy o treinador já gastou (Σ máx(0, attr-10))."""
    total = 0
    for key in ATTRIBUTES:
        try:
            total += max(0, int(trainer.get(key, POINT_BUY_BASE) or POINT_BUY_BASE) - POINT_BUY_BASE)
        except (TypeError, ValueError):
            pass
    return total


def validate_point_buy(incoming):
    """Valida um dict {attr: valor} contra as regras do point-buy do jogador.
    Retorna (ok, valores_limpos, erro). Cada atributo é clampado a 10-16 e a
    soma dos pontos gastos não pode passar de 20."""
    cleaned = {}
    for key in ATTRIBUTES:
        raw = incoming.get(key, POINT_BUY_BASE)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            v = POINT_BUY_BASE
        if v < POINT_BUY_BASE or v > POINT_BUY_MAX:
            return False, None, (
                f'{ATTRIBUTES[key][1]} deve ficar entre {POINT_BUY_BASE} e {POINT_BUY_MAX}.')
        cleaned[key] = v
    spent = sum(v - POINT_BUY_BASE for v in cleaned.values())
    if spent > POINT_BUY_BUDGET:
        return False, None, (
            f'Você usou {spent} pontos, mas só tem {POINT_BUY_BUDGET}.')
    return True, cleaned, None


def mod(value):
    """Modificador D&D clássico: 10 → +0, 18 → +4."""
    try:
        return (int(value) - 10) // 2
    except (TypeError, ValueError):
        return 0


def proficiency_bonus(level):
    level = int(level or 1)
    return 6 if level >= 17 else 5 if level >= 13 else 4 if level >= 9 \
        else 3 if level >= 5 else 2


def max_proficiencies(level):
    level = int(level or 1)
    return BASE_PROFS + sum(1 for lv in EXTRA_PROF_LEVELS if level >= lv)


def skill_modifier(trainer, skill):
    """Bônus total da perícia: mod do atributo (½ para Sorte) + proficiência
    se o treinador for proficiente nela."""
    if skill not in SKILLS:
        return 0, False
    attr_key = SKILLS[skill][0]
    m = mod(trainer.get(attr_key, 10))
    if skill == 'Sorte':
        # metade do modificador, arredondado para baixo (regra escolhida)
        m = m // 2 if m >= 0 else -((-m + 1) // 2)
    proficient = skill in (trainer.get('skill_profs') or [])
    bonus = m + (proficiency_bonus(trainer.get('level', 1)) if proficient else 0)
    return bonus, proficient


def clamp_profs(trainer):
    """Limita a lista de proficiências ao teto do nível (server-side)."""
    profs = [s for s in (trainer.get('skill_profs') or []) if s in SKILLS]
    limit = max_proficiencies(trainer.get('level', 1))
    trainer['skill_profs'] = profs[:limit]
    return trainer['skill_profs']


def migrate_trainer(trainer):
    """Converte a ficha antiga (str/dex/con/int/wis/cha) para os 6 atributos
    novos, in-place e idempotente (flag av=2). Retorna True se mudou."""
    if not isinstance(trainer, dict) or trainer.get('av') == ATTRS_VERSION:
        return False
    for old_key, new_key in LEGACY_MAP.items():
        if new_key not in trainer:
            try:
                trainer[new_key] = max(1, min(20, int(trainer.get(old_key, 10) or 10)))
            except (TypeError, ValueError):
                trainer[new_key] = 10
    trainer.setdefault('skill_profs', [])
    clamp_profs(trainer)
    trainer['av'] = ATTRS_VERSION
    return True
