// ============================================================
// Camada de FX opcional com GSAP (vendorizado em js/vendor/gsap.min.js).
// PILOTO: melhora só a batalha (dreno de HP + sequência de captura).
// Degrada sem quebrar — se o GSAP não carregar OU o usuário pedir menos
// movimento (prefers-reduced-motion), tudo vira no-op / aplicação instantânea.
// Estética 8-bit: durações curtas e easing em degraus (steps).
// ============================================================
(function () {
    const FX = {};
    function g() { return window.gsap || null; }
    let _reduced = false;
    try {
        _reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) {}

    FX.enabled = function () { return !!g() && !_reduced; };

    // Barra de HP: dreno/enchimento suave com "degraus" (cara de 8-bit).
    // Sem GSAP → define a largura direto (comportamento antigo).
    FX.tweenWidth = function (el, pct) {
        if (!el) return;
        const gs = g();
        if (!FX.enabled() || !gs) { el.style.width = pct + '%'; return; }
        gs.to(el, { width: pct + '%', duration: 0.45, ease: 'steps(15)', overwrite: 'auto' });
    };

    // Captura — SUCESSO: o selvagem treme e é "absorvido" (encolhe + some).
    FX.captureAbsorb = function (el) {
        const gs = g();
        if (!el) return;
        if (!FX.enabled() || !gs) { el.style.opacity = '0'; return; }
        gs.killTweensOf(el);
        gs.timeline()
          .to(el, { x: -5, duration: 0.06, repeat: 7, yoyo: true, ease: 'steps(1)' })
          .set(el, { x: 0 })
          .to(el, { scale: 0.12, opacity: 0, rotation: 6, duration: 0.4,
                    ease: 'back.in(2)', transformOrigin: '50% 60%' });
    };

    // Captura — FALHA (bola quebrou): só um tremor curto.
    FX.captureWobble = function (el) {
        const gs = g();
        if (!el || !FX.enabled() || !gs) return;
        gs.killTweensOf(el);
        gs.timeline()
          .to(el, { x: -4, duration: 0.05, repeat: 5, yoyo: true, ease: 'steps(1)' })
          .set(el, { x: 0 });
    };

    // Callout central estilo VS ("SUPER EFETIVO!", "CAPTURADO!"...): punch-in
    // com fade — decorativo, some sozinho. kind: danger|success|gold|muted.
    FX.callout = function (text, kind, hostEl) {
        if (_reduced || !text) return;
        const host = hostEl || document.querySelector('.poke-scene')
                            || document.getElementById('battle-area');
        if (!host) return;
        // hosts fora da arena 1v1 (PvP, grupo) podem ser static — o callout
        // é position:absolute e precisa de um pai posicionado
        try {
            if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
        } catch (e) {}
        let el = document.getElementById('fx-callout');
        if (!el) {
            el = document.createElement('div');
            el.id = 'fx-callout';
            host.appendChild(el);
        } else if (el.parentElement !== host) {
            host.appendChild(el);
        }
        el.textContent = text;
        el.setAttribute('data-kind', kind || 'gold');
        const gs = g();
        if (gs) {
            gs.killTweensOf(el);
            // re-centra a CADA chamada com xPercent/yPercent (percentuais do
            // PRÓPRIO elemento, recalculados pro texto novo) e zera x/y px —
            // sem isso o GSAP cacheava o translate(-50%,-50%) do CSS em px do
            // primeiro texto e desalinhava os callouts seguintes (C2).
            gs.set(el, { xPercent: -50, yPercent: -50, x: 0, y: 0 });
            gs.timeline()
              .fromTo(el, { opacity: 0, scale: 1.6 },
                          { opacity: 1, scale: 1, duration: 0.16, ease: 'steps(4)' })
              .to(el, { opacity: 0, y: -12, duration: 0.3, ease: 'power1.in', delay: 0.85 })
              .set(el, { y: 0 });
        } else {
            // fallback sem GSAP: cancela o timer anterior (C6 — um timer
            // velho escondia o callout novo quase na hora)
            if (FX._calloutTimer) clearTimeout(FX._calloutTimer);
            el.style.opacity = '1';
            FX._calloutTimer = setTimeout(() => { el.style.opacity = '0'; }, 1000);
        }
    };

    // Restaura o sprite para um novo encontro (limpa transform/opacity do GSAP).
    FX.resetSprite = function (el) {
        if (!el) return;
        const gs = g();
        if (gs) gs.set(el, { clearProps: 'all' });
        else { el.style.opacity = ''; el.style.transform = ''; }
    };

    // ── Pacote de FX de batalha (todas as batalhas: 1v1, PvP, grupo) ──

    // Barra de HP com "pedaço vermelho": ao levar dano, a barra cai rápido e
    // deixa um rastro vermelho do HP perdido, que é "comido" logo depois
    // (estilo jogo de luta). fill = o preenchimento; from/to em % (0-100).
    FX.hpHit = function (fill, fromPct, toPct) {
        if (!fill) return;
        const gs = g();
        if (!FX.enabled() || !gs) { fill.style.width = toPct + '%'; return; }
        const box = fill.parentElement;
        if (!box) { FX.tweenWidth(fill, toPct); return; }
        if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
        let ghost = box.querySelector('.fx-hp-ghost');
        if (!ghost) {
            ghost = document.createElement('div');
            ghost.className = 'fx-hp-ghost';
            ghost.style.cssText = 'position:absolute;left:0;top:0;height:100%;' +
                'background:#ff5252;border-radius:inherit;pointer-events:none;';
            box.insertBefore(ghost, box.firstChild);
        }
        fill.style.position = 'relative';   // fica NA FRENTE do rastro
        fill.style.transition = 'none';     // transition CSS brigaria com o tween
        gs.killTweensOf([fill, ghost]);
        gs.set(fill, { width: fromPct + '%' });
        gs.set(ghost, { width: fromPct + '%', opacity: 1 });
        gs.timeline()
          .fromTo(fill, { filter: 'brightness(2.4)' },
                        { filter: 'brightness(1)', duration: 0.18, ease: 'steps(3)' }, 0)
          .to(fill, { width: toPct + '%', duration: 0.22, ease: 'steps(8)' }, 0.05)
          .to(ghost, { width: toPct + '%', duration: 0.4, ease: 'steps(12)' }, 0.4)
          .to(ghost, { opacity: 0, duration: 0.12 }, '>-0.05');
    };

    // Tremor de impacto: serve para sprite OU card inteiro (batalha em grupo).
    FX.hitShake = function (el, strong) {
        const gs = g();
        if (!el || !FX.enabled() || !gs) return;
        gs.killTweensOf(el);
        gs.timeline()
          .fromTo(el, { filter: 'brightness(2.2)' },
                      { filter: 'brightness(1)', duration: 0.25, ease: 'steps(3)' }, 0)
          .to(el, { x: strong ? -6 : -4, duration: 0.05,
                    repeat: strong ? 7 : 5, yoyo: true, ease: 'steps(1)' }, 0)
          .set(el, { x: 0 });
    };

    // Número flutuante de dano/cura sobre um elemento (sprite ou card).
    // kind: 'dmg' (vermelho), 'heal' (verde), 'crit' (dourado, maior).
    FX.damagePop = function (host, text, kind) {
        if (!host || _reduced || !text) return;
        const r = host.getBoundingClientRect();
        if (!r.width) return;
        const el = document.createElement('div');
        el.textContent = text;
        const color = kind === 'heal' ? '#66bb6a' : kind === 'crit' ? '#ffcb05' : '#ff5252';
        el.style.cssText = 'position:fixed;z-index:10000;pointer-events:none;' +
            `left:${r.left + r.width / 2}px;top:${r.top + r.height * 0.25}px;` +
            'transform:translate(-50%,-50%);font-weight:900;' +
            `font-size:${kind === 'crit' ? '1.5rem' : '1.15rem'};color:${color};` +
            'text-shadow:1px 1px 0 #000,-1px 1px 0 #000,1px -1px 0 #000,-1px -1px 0 #000;';
        document.body.appendChild(el);
        const gs = g();
        if (gs) {
            gs.timeline({ onComplete: () => el.remove() })
              .fromTo(el, { y: 0, opacity: 0, scale: 1.4 },
                          { opacity: 1, scale: 1, duration: 0.12, ease: 'steps(3)' })
              .to(el, { y: -26, duration: 0.55, ease: 'steps(10)' }, 0.1)
              .to(el, { opacity: 0, duration: 0.2 }, '>-0.15');
        } else {
            setTimeout(() => el.remove(), 700);
        }
    };

    // Desmaio: o sprite/card cai e apaga em degraus.
    FX.faintDrop = function (el) {
        const gs = g();
        if (!el) return;
        if (!FX.enabled() || !gs) { el.style.opacity = '0.35'; return; }
        gs.killTweensOf(el);
        gs.to(el, { y: 10, opacity: 0.3, filter: 'grayscale(1) brightness(0.6)',
                    duration: 0.45, ease: 'steps(6)' });
    };

    // Entrada de Pokémon (troca, reposição, reforço do vilão): flash branco
    // + cresce "saindo da bola".
    FX.sendOut = function (el) {
        const gs = g();
        if (!el) return;
        if (!FX.enabled() || !gs) { FX.resetSprite(el); return; }
        gs.killTweensOf(el);
        gs.set(el, { clearProps: 'all' });
        gs.timeline()
          .fromTo(el, { scale: 0.2, opacity: 0, filter: 'brightness(3)' },
                      { scale: 1.08, opacity: 1, duration: 0.3, ease: 'steps(5)' })
          .to(el, { scale: 1, filter: 'brightness(1)', duration: 0.15, ease: 'steps(3)' });
    };

    // Transição de aba: o conteúdo novo entra fluido (fade + sobe).
    FX.tabIn = function (el) {
        const gs = g();
        if (!el || !FX.enabled() || !gs) return;
        gs.killTweensOf(el);
        gs.fromTo(el, { opacity: 0, y: 12 },
                      { opacity: 1, y: 0, duration: 0.25, ease: 'power2.out',
                        clearProps: 'transform,opacity' });
    };

    // 🎲 DADÃO DE MESA: rolagem gigante no centro da tela, para todos verem.
    // d = {player_name, emoji, label, roll, sides, bonus, total, cd, success,
    //      nat1, nat20, manual}. Cicla números rápido e "cai" no resultado.
    FX.diceRoll = function (d) {
        if (!d || typeof d.total !== 'number') return;
        let ov = document.getElementById('fx-dice-overlay');
        if (ov) ov.remove();   // rolagem nova substitui a anterior
        ov = document.createElement('div');
        ov.id = 'fx-dice-overlay';
        ov.style.cssText = 'position:fixed;inset:0;z-index:10001;display:flex;' +
            'flex-direction:column;align-items:center;justify-content:center;' +
            'background:rgba(5,8,16,0.78);pointer-events:none;';
        const color = d.nat20 ? '#ffcb05' : d.nat1 ? '#e53935'
            : d.success === true ? '#66bb6a' : d.success === false ? '#e53935' : '#ffcb05';
        const sub = [];
        if (typeof d.bonus === 'number' && d.bonus !== 0 && !d.manual) {
            sub.push(`d${d.sides || 20}(${d.roll}) ${d.bonus >= 0 ? '+' : '−'}${Math.abs(d.bonus)} = ${d.total}`);
        }
        if (d.cd != null) sub.push(`vs CD ${d.cd}`);
        const verdict = d.nat20 ? '🌟 NATURAL 20!' : d.nat1 ? '💀 NATURAL 1!'
            : d.success === true ? '✅ SUCESSO' : d.success === false ? '❌ FALHOU' : '';
        ov.innerHTML = `
            <div style="font-weight:800;font-size:1rem;color:#e8ecf6;text-shadow:0 2px 8px #000;">
                ${d.player_name || ''} · ${d.emoji || '🎲'} ${d.label || 'Rolagem'}${d.manual ? ' <small style="opacity:0.7;">(dado físico)</small>' : ''}</div>
            <div id="fx-dice-cube" style="width:130px;height:130px;margin:0.9rem 0;display:flex;
                align-items:center;justify-content:center;border-radius:26px;
                background:linear-gradient(145deg,#1c2438,#0b101e);
                border:4px solid ${color};box-shadow:0 0 42px ${color}66,inset 0 2px 10px rgba(255,255,255,0.08);
                font-size:3.4rem;font-weight:900;color:${color};
                font-family:ui-monospace,monospace;">?</div>
            <div id="fx-dice-verdict" style="font-weight:900;font-size:1.25rem;color:${color};
                text-shadow:0 2px 8px #000;opacity:0;">${verdict}</div>
            <div style="font-size:0.85rem;color:#9aa5bf;margin-top:0.2rem;">${sub.join(' · ')}</div>`;
        document.body.appendChild(ov);
        const cube = ov.querySelector('#fx-dice-cube');
        const verd = ov.querySelector('#fx-dice-verdict');
        const done = () => { if (ov.parentElement) {
            const gs2 = g();
            if (gs2) gs2.to(ov, { opacity: 0, duration: 0.3, onComplete: () => ov.remove() });
            else ov.remove();
        } };
        const gs = g();
        if (!FX.enabled() || !gs) {
            cube.textContent = String(d.roll ?? d.total);
            verd.style.opacity = '1';
            setTimeout(done, 1600);
            return;
        }
        // cicla números aleatórios, desacelerando, e cai no resultado
        const sides = Math.max(2, d.sides || 20);
        const state = { p: 0 };
        gs.timeline()
          .fromTo(ov, { opacity: 0 }, { opacity: 1, duration: 0.15 })
          .fromTo(cube, { scale: 0.4, rotation: -18 },
                        { scale: 1, rotation: 0, duration: 0.3, ease: 'back.out(2)' }, 0)
          .to(state, { p: 1, duration: 1.0, ease: 'power2.out',
                       onUpdate: () => {
                           cube.textContent = String(1 + Math.floor(Math.random() * sides));
                       } })
          .add(() => { cube.textContent = String(d.roll ?? d.total); })
          .fromTo(cube, { scale: 1.35 }, { scale: 1, duration: 0.25, ease: 'back.out(3)' })
          .to(cube, { x: -5, duration: 0.05, repeat: 5, yoyo: true, ease: 'steps(1)' }, '<')
          .set(cube, { x: 0 })
          .to(verd, { opacity: 1, y: -4, duration: 0.2 })
          .add(done, '+=1.4');
    };

    // Entrada em cascata (stagger) — usada nos cards do carrossel de Pokémon.
    FX.staggerIn = function (els) {
        const gs = g();
        if (!els || !els.length || !FX.enabled() || !gs) return;
        gs.fromTo(els, { opacity: 0, x: 14 },
                       { opacity: 1, x: 0, duration: 0.2, ease: 'power2.out',
                         stagger: 0.045, clearProps: 'transform,opacity' });
    };

    window.FX = FX;
})();
