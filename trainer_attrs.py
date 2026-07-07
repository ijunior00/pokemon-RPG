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
    se o treinador for proficiente + bônus do Caminho do Treinador."""
    if skill not in SKILLS:
        return 0, False
    attr_key = SKILLS[skill][0]
    skill_bonus, attr_bonus = path_bonuses(trainer)
    m = mod(trainer.get(attr_key, 10)) + attr_bonus.get(attr_key, 0)
    if skill == 'Sorte':
        # metade do modificador, arredondado para baixo (regra escolhida)
        m = m // 2 if m >= 0 else -((-m + 1) // 2)
    proficient = skill in (trainer.get('skill_profs') or [])
    bonus = (m + (proficiency_bonus(trainer.get('level', 1)) if proficient else 0)
             + skill_bonus.get(skill, 0))
    return bonus, proficient


def attr_mod(trainer, attr_key):
    """Modificador de um atributo INCLUINDO o bônus do Caminho (usado onde o
    atributo age direto: loja=Influência, iniciativa=Tática)."""
    _, attr_bonus = path_bonuses(trainer)
    return mod(trainer.get(attr_key, 10)) + attr_bonus.get(attr_key, 0)


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


# ═══════════════════════════════════════════════════════════════════════════
# CAMINHO DO TREINADOR — 4 caminhos, marcos nos níveis 3/6/10 (escolhe 1 de 3)
# ═══════════════════════════════════════════════════════════════════════════
PATH_UNLOCK_LEVEL = 2         # o caminho é escolhido ao atingir o nível 2
MILESTONE_LEVELS = (3, 6, 10)  # níveis que desbloqueiam uma habilidade

# bônus: ('skill', <perícia>) | ('attr', <atributo>) | None (só narrativo).
# Só o marco de nível 3 concede bônus mecânico; 6 e 10 são talentos narrativos.
TRAINER_PATHS = {
    'estrategista': {
        'name': 'Estrategista', 'emoji': '♟️',
        'motto': 'A vitória começa antes do primeiro turno.',
        'desc': 'Especialista em planejamento, leitura de combate e decisões inteligentes.',
        'milestones': {
            3: [
                {'id': 'observador_nato', 'name': 'Observador Nato', 'bonus': ('skill', 'Análise'),
                 'desc': 'Ao encontrar um Pokémon/NPC importante, descubra automaticamente uma informação relevante (Mestre). Bônus: +1 Análise.'},
                {'id': 'mapa_mental', 'name': 'Mapa Mental', 'bonus': ('skill', 'Exploração'),
                 'desc': 'Você nunca se perde em locais já explorados e sempre refaz caminhos conhecidos. Bônus: +1 Exploração.'},
                {'id': 'planejamento', 'name': 'Planejamento', 'bonus': ('skill', 'Comando'),
                 'desc': 'Após um Descanso Longo, escolha um objetivo: você e um aliado têm vantagem no primeiro teste relacionado. Bônus: +1 Comando.'},
            ],
            6: [
                {'id': 'perfil_completo', 'name': 'Perfil Completo', 'bonus': None,
                 'desc': 'Após capturar ou enfrentar um Pokémon, identifique todas as informações conhecidas dele.'},
                {'id': 'improvisador', 'name': 'Improvisador', 'bonus': None,
                 'desc': 'Use itens comuns para soluções criativas em aventuras (aprovação do Mestre).'},
                {'id': 'analista_campo', 'name': 'Analista de Campo', 'bonus': None,
                 'desc': 'Antes de um combate, descubra uma característica importante do terreno.'},
            ],
            10: [
                {'id': 'mestre_estrategia', 'name': 'Mestre da Estratégia', 'bonus': None,
                 'desc': 'Uma vez por sessão, faça ao Mestre uma pergunta estratégica e receba resposta verdadeira.'},
                {'id': 'genio_tatico', 'name': 'Gênio Tático', 'bonus': None,
                 'desc': 'Antes do combate, reorganize a ordem de iniciativa da sua equipe.'},
                {'id': 'xadrez_vivo', 'name': 'Xadrez Vivo', 'bonus': None,
                 'desc': 'Após observar um treinador, descubra sua equipe principal ou estratégia predominante.'},
            ],
        },
    },
    'guardiao': {
        'name': 'Guardião', 'emoji': '❤️',
        'motto': 'O maior poder nasce da confiança.',
        'desc': 'Especialista em Vínculo, recuperação e cuidado dos Pokémon.',
        'milestones': {
            3: [
                {'id': 'empatia', 'name': 'Empatia', 'bonus': ('skill', 'Afinidade'),
                 'desc': 'Compreenda facilmente emoções e intenções de Pokémon. Bônus: +1 Afinidade.'},
                {'id': 'cuidados_especiais', 'name': 'Cuidados Especiais', 'bonus': ('skill', 'Cuidados'),
                 'desc': 'Pokémon recuperam mais HP durante descansos. Bônus: +1 Cuidados.'},
                {'id': 'treinador_paciente', 'name': 'Treinador Paciente', 'bonus': ('attr', 'vinculo'),
                 'desc': 'Facilidade para criar confiança, acalmar e domesticar Pokémon. Bônus: +1 Vínculo.'},
            ],
            6: [
                {'id': 'rotina_perfeita', 'name': 'Rotina Perfeita', 'bonus': None,
                 'desc': 'Após um Descanso Longo, conceda um pequeno benefício temporário a um Pokémon.'},
                {'id': 'parceiros_fieis', 'name': 'Parceiros Fiéis', 'bonus': None,
                 'desc': 'Seus Pokémon sofrem menos com medo, hesitação e desobediência.'},
                {'id': 'reabilitacao', 'name': 'Reabilitação', 'bonus': None,
                 'desc': 'Durante um descanso, remova uma condição persistente de um Pokémon.'},
            ],
            10: [
                {'id': 'elo_absoluto', 'name': 'Elo Absoluto', 'bonus': None,
                 'desc': 'Compartilhe pensamentos simples com um Pokémon durante uma cena.'},
                {'id': 'espirito_protetor', 'name': 'Espírito Protetor', 'bonus': None,
                 'desc': 'Uma vez por sessão, impeça uma consequência grave quando um Pokémon aliado cair.'},
                {'id': 'confianca_inabalavel', 'name': 'Confiança Inabalável', 'bonus': None,
                 'desc': 'Pokémon com alto Vínculo nunca falham testes de obediência.'},
            ],
        },
    },
    'naturalista': {
        'name': 'Naturalista', 'emoji': '🌿',
        'motto': 'Quem entende a natureza nunca caminha sozinho.',
        'desc': 'Especialista em sobrevivência, pesquisa e exploração.',
        'milestones': {
            3: [
                {'id': 'rastreador', 'name': 'Rastreador', 'bonus': ('skill', 'Exploração'),
                 'desc': 'Siga rastros e pegadas com facilidade. Bônus: +1 Exploração.'},
                {'id': 'botanico', 'name': 'Botânico', 'bonus': ('skill', 'Pesquisa'),
                 'desc': 'Encontre recursos naturais com maior frequência. Bônus: +1 Pesquisa.'},
                {'id': 'instinto_selvagem', 'name': 'Instinto Selvagem', 'bonus': ('skill', 'Atletismo'),
                 'desc': 'Você dificilmente é surpreendido por Pokémon selvagens. Bônus: +1 Atletismo.'},
            ],
            6: [
                {'id': 'especialista_biomas', 'name': 'Especialista em Biomas', 'bonus': None,
                 'desc': 'Descubra recursos raros com mais facilidade em ambientes naturais.'},
                {'id': 'cacador_pegadas', 'name': 'Caçador de Pegadas', 'bonus': None,
                 'desc': 'Identifique automaticamente quais espécies passaram por uma região.'},
                {'id': 'acampamento_perfeito', 'name': 'Acampamento Perfeito', 'bonus': None,
                 'desc': 'Descansos recuperam mais recursos e oferecem melhores condições para a equipe.'},
            ],
            10: [
                {'id': 'mestre_natureza', 'name': 'Mestre da Natureza', 'bonus': None,
                 'desc': 'Pokémon selvagens raramente atacam sem demonstrar intenções antes.'},
                {'id': 'filho_floresta', 'name': 'Filho da Floresta', 'bonus': None,
                 'desc': 'Uma vez por sessão, encontre exatamente o recurso natural necessário.'},
                {'id': 'explorador_lendario', 'name': 'Explorador Lendário', 'bonus': None,
                 'desc': 'Ao entrar em um novo bioma, descubra automaticamente um segredo importante (Mestre).'},
            ],
        },
    },
    'inspirador': {
        'name': 'Inspirador', 'emoji': '👑',
        'motto': 'Grandes treinadores inspiram antes mesmo de batalhar.',
        'desc': 'Especialista em liderança, reputação e influência.',
        'milestones': {
            3: [
                {'id': 'boa_impressao', 'name': 'Boa Impressão', 'bonus': ('skill', 'Diplomacia'),
                 'desc': 'Suas primeiras interações sociais causam impressão muito positiva. Bônus: +1 Diplomacia.'},
                {'id': 'lider_nato', 'name': 'Líder Nato', 'bonus': ('skill', 'Presença'),
                 'desc': 'Sua liderança inspira aliados naturalmente. Bônus: +1 Presença.'},
                {'id': 'palavra_certa', 'name': 'Palavra Certa', 'bonus': ('attr', 'influencia'),
                 'desc': 'Convencer pessoas torna-se significativamente mais fácil. Bônus: +1 Influência.'},
            ],
            6: [
                {'id': 'rede_contatos', 'name': 'Rede de Contatos', 'bonus': None,
                 'desc': 'Ao chegar a uma cidade importante, conheça um NPC útil para a aventura.'},
                {'id': 'negociador', 'name': 'Negociador', 'bonus': None,
                 'desc': 'Obtenha melhores preços, contratos e acordos comerciais.'},
                {'id': 'inspiracao', 'name': 'Inspiração', 'bonus': None,
                 'desc': 'Uma vez por Descanso Longo, permita que um aliado repita um teste recém-falhado.'},
            ],
            10: [
                {'id': 'lenda_viva', 'name': 'Lenda Viva', 'bonus': None,
                 'desc': 'Sua reputação abre portas, facilita negociações e cria novas oportunidades.'},
                {'id': 'simbolo', 'name': 'Símbolo', 'bonus': None,
                 'desc': 'Sua presença fortalece o moral de aliados e Pokémon próximos.'},
                {'id': 'voz_inspira', 'name': 'Voz que Inspira', 'bonus': None,
                 'desc': 'Uma vez por sessão, todos os aliados repetem um teste de perícia feito naquela cena.'},
            ],
        },
    },
}


def _path_abilities_index(path_id):
    """{ability_id: (milestone_level, ability_dict)} do caminho."""
    out = {}
    p = TRAINER_PATHS.get(path_id)
    if not p:
        return out
    for lvl, opts in p['milestones'].items():
        for a in opts:
            out[a['id']] = (lvl, a)
    return out


def path_choices(trainer):
    """{ '3': ability_id, '6': ..., '10': ... } escolhidos pelo treinador."""
    ch = trainer.get('path_abilities')
    return ch if isinstance(ch, dict) else {}


def path_bonuses(trainer):
    """(skill_bonuses, attr_bonuses) somados dos talentos JÁ escolhidos."""
    sb, ab = {}, {}
    if not isinstance(trainer, dict):
        return sb, ab
    idx = _path_abilities_index(trainer.get('path'))
    for aid in path_choices(trainer).values():
        info = idx.get(aid)
        if not info:
            continue
        bonus = info[1].get('bonus')
        if not bonus:
            continue
        kind, target = bonus
        if kind == 'skill':
            sb[target] = sb.get(target, 0) + 1
        elif kind == 'attr':
            ab[target] = ab.get(target, 0) + 1
    return sb, ab


def path_state(trainer):
    """Estado do Caminho para a UI: caminho atual, escolhas, marcos
    desbloqueados e pendentes."""
    level = int(trainer.get('level', 1) or 1)
    path_id = trainer.get('path') if trainer.get('path') in TRAINER_PATHS else None
    choices = path_choices(trainer)
    milestones = []
    if path_id:
        for lvl in MILESTONE_LEVELS:
            milestones.append({
                'level': lvl,
                'unlocked': level >= lvl,
                'chosen': choices.get(str(lvl)),
                'options': TRAINER_PATHS[path_id]['milestones'][lvl],
            })
    return {
        'unlocked': level >= PATH_UNLOCK_LEVEL,
        'path': path_id,
        'choices': choices,
        'milestones': milestones,
        'paths_catalog': {k: {'name': v['name'], 'emoji': v['emoji'],
                              'motto': v['motto'], 'desc': v['desc']}
                          for k, v in TRAINER_PATHS.items()},
    }


def choose_path(trainer, path_id, allow_change=False):
    """Escolhe o caminho (nível ≥ 2, permanente salvo allow_change do Mestre).
    Retorna (ok, erro)."""
    if path_id not in TRAINER_PATHS:
        return False, 'Caminho inválido.'
    if int(trainer.get('level', 1) or 1) < PATH_UNLOCK_LEVEL:
        return False, f'O Caminho é escolhido ao atingir o nível {PATH_UNLOCK_LEVEL}.'
    if trainer.get('path') in TRAINER_PATHS and not allow_change:
        return False, 'Seu Caminho já foi escolhido (permanente — peça ao Mestre para mudar).'
    if trainer.get('path') != path_id:
        trainer['path'] = path_id
        trainer['path_abilities'] = {}   # troca de caminho zera as escolhas
    return True, None


def choose_path_ability(trainer, milestone, ability_id, allow_change=False):
    """Escolhe UMA habilidade de um marco (nível 3/6/10). Retorna (ok, erro)."""
    path_id = trainer.get('path')
    if path_id not in TRAINER_PATHS:
        return False, 'Escolha um Caminho primeiro.'
    try:
        milestone = int(milestone)
    except (TypeError, ValueError):
        return False, 'Marco inválido.'
    if milestone not in MILESTONE_LEVELS:
        return False, 'Marco inválido.'
    if int(trainer.get('level', 1) or 1) < milestone:
        return False, f'Este talento desbloqueia no nível {milestone}.'
    options = TRAINER_PATHS[path_id]['milestones'][milestone]
    if ability_id not in {a['id'] for a in options}:
        return False, 'Habilidade não pertence a este Caminho/marco.'
    choices = trainer.setdefault('path_abilities', {})
    if not isinstance(choices, dict):
        choices = trainer['path_abilities'] = {}
    if str(milestone) in choices and not allow_change:
        return False, 'Você já escolheu o talento deste marco (permanente).'
    choices[str(milestone)] = ability_id
    return True, None
