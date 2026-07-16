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

    // Restaura o sprite para um novo encontro (limpa transform/opacity do GSAP).
    FX.resetSprite = function (el) {
        if (!el) return;
        const gs = g();
        if (gs) gs.set(el, { clearProps: 'all' });
        else { el.style.opacity = ''; el.style.transform = ''; }
    };

    window.FX = FX;
})();
