// Recording overlay: visible cursor, click ripple, highlight ring, step badge, blur masks.
// Lives in the browser top layer (popover) so it stays above modal dialogs, and renders
// its text through CSS ::after so Playwright text locators never match it.
(() => {
  if (window.__rv) return;
  const ACCENT = window.__RV_ACCENT || '#FFD100';
  const BG = window.__RV_BG || '#121114';
  const css = `
  #rv-root{position:fixed;inset:0;width:100vw;height:100vh;margin:0;padding:0;border:0;background:transparent;
    overflow:visible;pointer-events:none;z-index:2147483647;font-family:'Instrument Sans',system-ui,sans-serif}
  #rv-cursor{position:fixed;left:0;top:0;width:28px;height:28px;transform:translate(-4px,-3px);display:none;
    filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));transition:transform .08s}
  #rv-cursor.down{transform:translate(-4px,-3px) scale(.86)}
  .rv-ripple{position:fixed;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;border:3px solid ${ACCENT};
    animation:rvRip .6s ease-out forwards}
  @keyframes rvRip{to{transform:scale(3.4);opacity:0}}
  .rv-ring{position:fixed;border:3px solid ${ACCENT};border-radius:12px;box-shadow:0 0 0 6px rgba(255,209,0,.22);
    animation:rvPulse 1.3s ease-in-out infinite, rvIn .3s ease-out}
  @keyframes rvPulse{50%{box-shadow:0 0 0 13px rgba(255,209,0,.07)}}
  @keyframes rvIn{from{opacity:0;transform:scale(1.12)}}
  .rv-spot{position:fixed;border-radius:14px;box-shadow:0 0 0 200vmax rgba(18,17,20,.42);transition:all .45s ease}
  .rv-blur{position:fixed;backdrop-filter:blur(9px);-webkit-backdrop-filter:blur(9px);background:rgba(255,255,255,.18);border-radius:6px}
  #rv-badge{position:fixed;right:28px;top:22px;background:${BG};color:#fff;border-radius:999px;padding:9px 18px 9px 9px;
    display:flex;align-items:center;gap:12px;font-size:17px;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.25);
    opacity:0;transform:translateY(-10px);transition:opacity .35s,transform .35s}
  #rv-badge.on{opacity:1;transform:none}
  #rv-badge b{background:${ACCENT};color:${BG};border-radius:999px;padding:4px 12px;font-size:15px}
  #rv-root [data-t]::after{content:attr(data-t)}`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
  const root = document.createElement('div');
  root.id = 'rv-root';
  root.setAttribute('popover', 'manual');
  document.body.appendChild(root);
  const top = () => { try { root.hidePopover(); root.showPopover(); } catch (e) { /* no popover support */ } };
  top();
  const cur = document.createElement('div');
  cur.id = 'rv-cursor';
  cur.innerHTML = `<svg viewBox="0 0 24 24" width="28" height="28"><path d="M4 2l15 10.5-6.6 1.3 3.9 7.2-3 1.6-3.9-7.3L4 20z"
    fill="#fff" stroke="${BG}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  root.appendChild(cur);
  const badge = document.createElement('div');
  badge.id = 'rv-badge';
  root.appendChild(badge);
  addEventListener('mousemove', (e) => {
    cur.style.display = 'block';
    cur.style.left = e.clientX + 'px';
    cur.style.top = e.clientY + 'px';
  }, true);
  addEventListener('mousedown', (e) => {
    cur.classList.add('down');
    const r = document.createElement('div');
    r.className = 'rv-ripple';
    r.style.left = e.clientX + 'px';
    r.style.top = e.clientY + 'px';
    root.appendChild(r);
    setTimeout(() => r.remove(), 700);
  }, true);
  addEventListener('mouseup', () => cur.classList.remove('down'), true);
  const place = (el, r, pad) => {
    el.style.left = r.x - pad + 'px';
    el.style.top = r.y - pad + 'px';
    el.style.width = r.width + pad * 2 + 'px';
    el.style.height = r.height + pad * 2 + 'px';
  };
  window.__rv = {
    top,
    ring(r, pad = 6) {
      top();
      window.__rv.clearRing();
      const el = document.createElement('div');
      el.className = 'rv-ring';
      place(el, r, pad);
      root.appendChild(el);
    },
    clearRing() { root.querySelectorAll('.rv-ring').forEach((e) => e.remove()); },
    spotlight(r, pad = 10) {
      top();
      let el = root.querySelector('.rv-spot');
      if (!el) { el = document.createElement('div'); el.className = 'rv-spot'; root.prepend(el); }
      place(el, r, pad);
    },
    clearSpotlight() { root.querySelectorAll('.rv-spot').forEach((e) => e.remove()); },
    blur(rects) {
      top();
      root.querySelectorAll('.rv-blur').forEach((e) => e.remove());
      for (const r of rects) {
        const el = document.createElement('div');
        el.className = 'rv-blur';
        place(el, r, 2);
        root.appendChild(el);
      }
    },
    badge(n, text) {
      top();
      badge.innerHTML = n ? `<b data-t="${n}"></b><span data-t="${text}"></span>` : `<span data-t="${text}"></span>`;
      badge.classList.add('on');
    },
    hideBadge() { badge.classList.remove('on'); },
    hideCursor(h) { cur.style.visibility = h ? 'hidden' : ''; },
  };
})();
