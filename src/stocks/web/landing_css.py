"""The landing page's stylesheet: base rules, the phone block, small-phone type."""

from __future__ import annotations

# Plain (non-f) string: it is full of CSS braces, and every value it needs is
# already a custom property. Tints the token set doesn't ship are derived with
# color-mix() off the same tokens rather than hard-coded rgba.
BASE_CSS = """
/* --- page --- */
.ag-l {
  background: var(--ag-surface-page);
  color: var(--ag-text-primary);
  font-family: 'Instrument Sans', sans-serif;
  font-variant-numeric: lining-nums;
  line-height: 1.5;
}
.ag-l * { box-sizing: border-box; }
.ag-l a { color: var(--ag-brand-accent); text-decoration: none; }
@media (hover: hover) { .ag-l a:hover { color: var(--ag-purple-400); } }
.ag-l h1, .ag-l h2, .ag-l h3 {
  font-family: 'Epilogue', sans-serif; margin: 0; letter-spacing: -0.015em;
}
.ag-l p { margin: 0; }
.ag-l-wrap { max-width: 1140px; margin: 0 auto; padding: 0 24px; }
.ag-l-num { font-family: 'Epilogue', sans-serif; font-weight: 700; }
.ag-l-mono { font-family: 'Martian Mono', monospace; }
.ag-l-up { color: var(--ag-landing-up); }
.ag-l-down { color: var(--ag-landing-down); }
.ag-l-band {
  background: var(--ag-surface-band);
  border-top: 1px solid var(--ag-surface-card);
}
.ag-l-rule { border-top: 1px solid var(--ag-surface-card); }

/* --- top bar --- */
.ag-l-bar {
  position: sticky; top: 0; z-index: 50;
  background: color-mix(in srgb, var(--ag-surface-page) 92%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--ag-border);
}
.ag-l-bar-in { height: 60px; display: flex; align-items: center; gap: 20px; }
.ag-l-brand { display: flex; align-items: center; gap: 10px; }
.ag-l-brand img { width: 28px; height: auto; }
.ag-l-brand span {
  font-family: 'Epilogue', sans-serif; font-weight: 700;
  font-size: var(--ag-fs-xl); letter-spacing: -0.01em;
}
.ag-l-spacer { flex: 1; }
.ag-l-lang {
  display: flex; align-items: center;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-sm);
  overflow: hidden;
}
.ag-l-lang a, .ag-l-lang span {
  padding: 5px 10px; font-size: var(--ag-fs-sm); font-weight: 500;
  color: var(--ag-text-muted); transition: all 50ms ease-in-out;
}
.ag-l-lang .on {
  font-weight: 600; background: var(--ag-surface-card);
  color: var(--ag-text-primary);
}
@media (hover: hover) { .ag-l-lang a:hover { color: var(--ag-text-primary); } }
.ag-l-gh { width: 16px; height: 16px; fill: currentColor; }
.ag-l-ghlink {
  display: flex; align-items: center; gap: 6px;
  font-size: var(--ag-fs-md); font-weight: 500; color: var(--ag-text-secondary);
}
@media (hover: hover) { .ag-l-ghlink:hover { color: var(--ag-text-primary); } }

/* --- skip link and touch targets --- */
/* First stop for a keyboard or screen-reader user: off-screen until focused,
   then pinned top-left above the sticky bar. */
.ag-l-skip {
  position: absolute; left: 12px; top: -100px; z-index: 100;
  padding: 10px 16px; border-radius: var(--ag-radius-sm);
  background: var(--ag-brand-cta); color: var(--ag-on-brand); font-weight: 600;
}
.ag-l-skip:focus { top: calc(8px + env(safe-area-inset-top, 0px)); }
html { scroll-padding-top: 72px; }
@media (pointer: coarse) {
  .ag-l-lang a, .ag-l-lang span, .ag-l-foot-lang a, .ag-l-foot-lang span {
    min-height: 44px; display: inline-flex; align-items: center;
  }
  .ag-l-cta, .ag-l-cta-ghost, .ag-l-cta-text { min-height: 44px; }
  .ag-l-foot-row a, .ag-l-jurswitch { padding: 12px 0; }
  .ag-l-q summary { padding: 6px 0; }
}
@media (prefers-reduced-motion: reduce) {
  .ag-l-lang a, .ag-l-lang span, .ag-l-cta, .ag-l-cta-ghost { transition: none; }
}

/* --- keyboard focus --- */
/* The default UA ring is near-invisible on this dark surface; keyboard users
   get an explicit high-contrast ring instead. :focus-visible only — mouse
   clicks stay ringless, as the UA heuristic intends. */
a:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 2px solid var(--ag-brand-cta); outline-offset: 2px;
}

/* --- buttons --- */
.ag-l-g { width: 17px; height: 17px; fill: var(--ag-brand-google-tile); }
.ag-l-cta {
  display: inline-flex; align-items: center; gap: 10px;
  font-size: var(--ag-fs-lg); font-weight: 600;
  color: var(--ag-on-brand); background: var(--ag-brand-cta);
  border: none; border-radius: var(--ag-radius-sm); padding: 13px 22px;
  cursor: pointer; transition: all 50ms ease-in-out;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--ag-brand-cta) 25%, transparent);
}
@media (hover: hover) {
  .ag-l-cta:hover { background: var(--ag-purple-700); color: var(--ag-on-brand); }
}
.ag-l-cta-ghost {
  display: inline-flex; align-items: center;
  font-size: var(--ag-fs-md); font-weight: 600; color: var(--ag-text-primary);
  background: transparent; border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-sm); padding: 8px 14px;
  transition: all 50ms ease-in-out; white-space: nowrap;
}
@media (hover: hover) {
  .ag-l-cta-ghost:hover {
    border-color: var(--ag-text-faint); color: var(--ag-text-primary);
  }
}
.ag-l-cta-text {
  font-size: var(--ag-fs-lg); font-weight: 600;
  color: var(--ag-brand-accent); padding: 13px 8px;
}
.ag-l-ctarow {
  display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
}
/* The fixed phone CTA bar. Hidden here, revealed by MOBILE_RULES. */
.ag-l-mbar { display: none; }

/* --- hero --- */
/* Every auto-fit grid here writes its minimum as min(Npx, 100%). A bare
   minmax(Npx, 1fr) track does not shrink below Npx, so in a container narrower
   than that — a phone — the row overflows to the right and the page clips
   it rather than scrolling. min(Npx, 100%) caps the minimum at the container itself. */
.ag-l-hero {
  padding-top: 72px; padding-bottom: 56px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(400px, 100%), 1fr));
  gap: 48px; align-items: center;
}
.ag-l-hero-copy { display: flex; flex-direction: column; gap: 20px; }
/* The "assistant built in" pill above the headline. Its own alpha tints are
   the chat tokens — same fill the assistant's own bubbles use downpage. */
.ag-l-badge {
  display: flex; align-items: center; gap: 8px; align-self: flex-start;
  background: var(--ag-cta-tint); border: 1px solid var(--ag-cta-tint-edge);
  border-radius: var(--ag-radius-pill); padding: 6px 14px;
}
.ag-l-badge i {
  width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
  background: var(--ag-brand-accent);
}
.ag-l-badge b {
  font-weight: 400; font-size: var(--ag-fs-2xs);
  letter-spacing: 0.06em; color: var(--ag-purple-400);
}
.ag-l-hero h1 {
  font-weight: 800; font-size: 46px; line-height: 1.08;
  letter-spacing: -0.02em; text-wrap: pretty;
}
.ag-l-lede {
  font-size: 17px; line-height: 1.55; color: var(--ag-text-secondary);
  max-width: 52ch; text-wrap: pretty;
}
.ag-l-trust {
  font-size: 12.5px; color: var(--ag-text-muted); line-height: 1.7;
}
.ag-l-card {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); padding: 20px;
  display: flex; flex-direction: column; gap: 16px;
  box-shadow: 0 24px 60px var(--ag-shadow-color-strong);
}
.ag-l-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.ag-l-kpi { display: flex; flex-direction: column; gap: 3px; }
.ag-l-kpi-l {
  font-size: 10.5px; font-weight: 500; color: var(--ag-text-muted);
  letter-spacing: 0.04em; text-transform: uppercase;
}
.ag-l-kpi-v { font-size: 19px; }
.ag-l-tbl {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--ag-border);
}
.ag-l-tr {
  display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 8px;
  padding: 7px 4px; font-size: var(--ag-fs-md);
  border-top: 1px solid var(--ag-surface-card);
}
.ag-l-th {
  display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 8px;
  padding: 8px 4px; font-size: 10.5px; font-weight: 500;
  color: var(--ag-text-faint); letter-spacing: 0.04em; text-transform: uppercase;
}
.ag-l-tr span + span, .ag-l-th span + span { text-align: right; }
.ag-l-tk { font-weight: 600; }
.ag-l-dim { color: var(--ag-text-secondary); }
.ag-l-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid var(--ag-border);
  padding-top: 14px;
}
.ag-l-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: var(--ag-fs-xs);
  color: var(--ag-text-muted);
}
.ag-l-legend span { display: flex; align-items: center; gap: 5px; }
.ag-l-sw { width: 14px; height: 2px; border-radius: 1px; }
.ag-l-sw-twr { background: var(--ag-brand-accent); }
.ag-l-sw-bm { background: var(--ag-landing-info); opacity: 0.7; }
.ag-l-chart svg { width: 100%; height: auto; display: block; }
.ag-l-axis {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--ag-text-faint);
}

/* --- broker strip --- */
.ag-l-brokers { padding-bottom: 64px; display: flex; flex-direction: column; gap: 16px; }
.ag-l-brokers-line {
  font-size: var(--ag-fs-md);
  font-weight: 500;
  color: var(--ag-text-muted);
  text-align: center;
}
.ag-l-brokergrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr));
  gap: 10px;
}
.ag-l-broker {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); padding: 14px 10px;
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  text-align: center;
}
.ag-l-broker.generic { border-style: dashed; }
.ag-l-broker b { font-family: 'Epilogue', sans-serif; font-weight: 700; font-size: 14px; }
.ag-l-broker.generic b { color: var(--ag-text-secondary); }
.ag-l-broker i { font-style: normal; font-size: 11px; color: var(--ag-text-muted); }

/* --- section headings --- */
.ag-l-sec {
  padding-top: 72px;
  padding-bottom: 72px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.ag-l-sec h2 { font-weight: 800; font-size: var(--ag-fs-3xl); }
.ag-l-head { display: flex; flex-direction: column; gap: 10px; max-width: 60ch; }
.ag-l-head p { font-size: var(--ag-fs-lg); color: var(--ag-text-secondary); }

/* --- the gap --- */
.ag-l-gaps { display: flex; flex-direction: column; gap: 14px; }
.ag-l-gap {
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); padding: 20px 22px;
}
.ag-l-gap div { display: flex; flex-direction: column; gap: 6px; }
.ag-l-gap b { font-size: var(--ag-fs-lg); font-weight: 600; }
.ag-l-gap p {
  font-size: var(--ag-fs-base);
  line-height: 1.55;
  color: var(--ag-text-secondary);
}
.ag-l-diagrams {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr));
  gap: 14px;
}
.ag-l-diagram {
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); padding: 20px;
  display: flex; flex-direction: column; gap: 14px;
}
.ag-l-eyebrow-sm { font-size: 11px; color: var(--ag-text-muted); letter-spacing: 0.06em; }
.ag-l-note { font-size: 12.5px; color: var(--ag-text-muted); }
.ag-l-lots { display: flex; gap: 8px; align-items: stretch; }
.ag-l-lot {
  border-radius: var(--ag-radius-xs); padding: 8px;
  display: flex; flex-direction: column; gap: 2px;
}
.ag-l-lot.sold {
  background: color-mix(in srgb, var(--ag-brand-cta) 18%, transparent);
  border: 1px solid var(--ag-brand-cta);
}
.ag-l-lot.held {
  background: var(--ag-surface-raised);
  border: 1px solid var(--ag-border);
}
.ag-l-lot b { font-size: var(--ag-fs-sm); font-weight: 600; }
.ag-l-lot.sold b { color: var(--ag-purple-400); }
.ag-l-lot.held b { color: var(--ag-text-muted); }
.ag-l-lot i { font-style: normal; font-size: 11px; }
.ag-l-lot.sold i { color: var(--ag-brand-accent); }
.ag-l-lot.held i { color: var(--ag-text-faint); }
.ag-l-lotpair {
  display: flex; border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-xs); overflow: hidden;
}
.ag-l-lotpair .ag-l-lot { border: none; border-radius: 0; }
.ag-l-lotpair .sold { border-right: 1px dashed var(--ag-brand-cta); }
.ag-l-tl { position: relative; height: 64px; }
.ag-l-tl-rail {
  position: absolute; left: 0; right: 0; top: 30px; height: 2px;
  background: var(--ag-border); border-radius: 1px;
}
.ag-l-tl-tick {
  position: absolute;
  top: 22px;
  width: 2px;
  height: 18px;
  background: var(--ag-brand-accent);
}
.ag-l-tl-tick.faint { background: var(--ag-text-faint); }
.ag-l-tl-lab {
  position: absolute; top: 0; transform: translateX(-50%); text-align: center;
  font-size: 9.5px; color: var(--ag-brand-accent); line-height: 1.35;
}
.ag-l-tl-lab.faint { color: var(--ag-text-faint); }
/* Weights and positions of the two diagrams: classes, not style attributes,
   so the page's CSP can refuse inline styles. */
.ag-l-f5 { flex: 5; }
.ag-l-f7 { flex: 7; }
.ag-l-f8 { flex: 8; }
.ag-l-f10 { flex: 10; }
.ag-l-f12 { flex: 12; }
.ag-l-at8 { left: 8%; }
.ag-l-at72 { left: 72%; }
.ag-l-at96 { left: 96%; }
.ag-l-compare { display: flex; gap: 10px; flex-wrap: wrap; }
.ag-l-compare div {
  flex: 1; min-width: 140px; border-radius: var(--ag-radius-sm);
  padding: 10px 12px; display: flex; flex-direction: column; gap: 2px;
}
.ag-l-compare .broker {
  background: var(--ag-surface-raised);
  border: 1px solid var(--ag-border);
}
.ag-l-compare .ours {
  background: color-mix(in srgb, var(--ag-brand-cta) 12%, transparent);
  border: 1px solid var(--ag-brand-cta);
}
.ag-l-compare small { font-size: var(--ag-fs-xs); color: var(--ag-text-muted); }
.ag-l-compare .ours small { color: var(--ag-purple-400); }
.ag-l-compare b { font-size: 17px; }
.ag-l-compare .broker b { color: var(--ag-text-secondary); }

/* --- how it works --- */
.ag-l-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
  gap: 16px;
}
.ag-l-step {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); padding: 24px;
  display: flex; flex-direction: column; gap: 16px;
}
.ag-l-step h3 {
  font-weight: 800; font-size: var(--ag-fs-lg); color: var(--ag-brand-accent);
}
.ag-l-step p {
  font-size: var(--ag-fs-base);
  line-height: 1.55;
  color: var(--ag-text-secondary);
}
.ag-l-gbtn {
  display: flex; align-items: center; justify-content: center; padding: 22px 0;
}
.ag-l-gbtn span {
  display: flex; align-items: center; gap: 10px;
  background: var(--ag-brand-google-tile); color: var(--ag-surface-card);
  font-size: var(--ag-fs-base); font-weight: 600;
  border-radius: var(--ag-radius-sm); padding: 11px 20px;
}
.ag-l-gbtn .ag-l-g { fill: var(--ag-info-deep); }
.ag-l-buckets { display: flex; flex-direction: column; gap: 6px; }
.ag-l-bucket {
  display: flex; justify-content: space-between; align-items: center;
  border-radius: 7px; padding: 7px 12px; font-size: 12.5px;
}
.ag-l-bucket b { font-weight: 600; }
.ag-l-bucket i { font-style: normal; font-size: var(--ag-fs-xs); }
.ag-l-bucket.ok {
  background: color-mix(in srgb, var(--ag-landing-up) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-up) 35%, transparent);
  color: var(--ag-landing-up);
}
.ag-l-bucket.warn {
  background: color-mix(in srgb, var(--ag-landing-warn) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-warn) 35%, transparent);
  color: var(--ag-landing-warn);
}
.ag-l-bucket.bad {
  background: color-mix(in srgb, var(--ag-landing-down) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-down) 35%, transparent);
  color: var(--ag-landing-down);
}
.ag-l-bucket.skip {
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  color: var(--ag-text-muted);
}
.ag-l-mini {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-sm);
  overflow: hidden;
}
.ag-l-mini-h {
  display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 6px;
  padding: 7px 12px; font-size: 11px; font-weight: 500;
  color: var(--ag-text-faint); text-transform: uppercase;
  letter-spacing: 0.04em; background: var(--ag-surface-page);
}
.ag-l-mini-r {
  display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 6px;
  padding: 6px 12px; font-size: 12.5px; border-top: 1px solid var(--ag-surface-card);
}
.ag-l-mini-h span + span, .ag-l-mini-r span + span { text-align: right; }

/* --- AI assistant --- */
/* The chat mock is the one place on the page that reproduces app chrome, so it
   borrows the app's own chat tokens (cta-tint for the user bubble, page tone
   for the assistant's) rather than inventing a second set. */
.ag-l-ai {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(400px, 100%), 1fr));
  gap: 16px; align-items: start;
}
.ag-l-chat {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); padding: 18px;
  display: flex; flex-direction: column; gap: 12px;
  box-shadow: var(--ag-shadow-overlay);
}
.ag-l-chat-h {
  display: flex; align-items: center; gap: 10px;
  padding-bottom: 12px; border-bottom: 1px solid var(--ag-border);
}
.ag-l-chat-h b { font-size: var(--ag-fs-md); font-weight: 600; }
.ag-l-avatar {
  width: 24px; height: 24px; flex-shrink: 0;
  border-radius: var(--ag-radius-nav);
  background: var(--ag-cta-tint); border: 1px solid var(--ag-brand-cta);
  display: flex; align-items: center; justify-content: center;
  font-family: 'Epilogue', sans-serif; font-weight: 800;
  font-size: var(--ag-fs-xs); color: var(--ag-purple-400);
}
.ag-l-chip {
  font-size: 11px; font-style: normal; color: var(--ag-text-muted);
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-xs);
  padding: 2px 6px;
}
.ag-l-ask {
  align-self: flex-end; max-width: 82%;
  background: var(--ag-brand-cta); color: var(--ag-on-brand);
  border-radius: var(--ag-radius-md) var(--ag-radius-md) 4px var(--ag-radius-md);
  padding: 10px 13px; font-size: 13.5px; line-height: 1.5;
}
.ag-l-said {
  max-width: 92%; background: var(--ag-surface-page);
  border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md) var(--ag-radius-md) var(--ag-radius-md) 4px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 10px;
}
.ag-l-said p { font-size: 13.5px; line-height: 1.55; text-wrap: pretty; }
.ag-l-said p b { color: var(--ag-text-primary); font-weight: 600; }
.ag-l-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.ag-l-action {
  display: flex; align-items: center; gap: 10px;
  background: var(--ag-cta-tint); border: 1px solid var(--ag-cta-tint-edge);
  border-radius: var(--ag-radius-nav); padding: 9px 12px;
}
.ag-l-action svg { width: 14px; height: 14px; flex-shrink: 0; }
.ag-l-action span { flex: 1; font-size: 12.5px; color: var(--ag-purple-400); }
.ag-l-composer {
  display: flex; align-items: center; gap: 8px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: 10px; padding: 9px 12px;
}
.ag-l-composer span {
  flex: 1; font-size: var(--ag-fs-md); color: var(--ag-text-faint);
}
.ag-l-aicards { display: flex; flex-direction: column; gap: 12px; }
.ag-l-aicards .ag-l-tile { padding: 20px; gap: 10px; border-radius: 14px; }
.ag-l-aicards h3 { font-weight: 700; font-size: 17px; }
.ag-l-aicards p {
  font-size: 13.5px; line-height: 1.55; color: var(--ag-text-secondary);
  text-wrap: pretty;
}
.ag-l-aicards p.ag-l-aside {
  font-size: var(--ag-fs-md); color: var(--ag-text-muted);
}
.ag-l-chips { display: flex; gap: 7px; flex-wrap: wrap; }
.ag-l-chips span {
  font-size: var(--ag-fs-sm); color: var(--ag-purple-400);
  background: var(--ag-cta-tint); border: 1px solid var(--ag-cta-tint-edge);
  border-radius: var(--ag-radius-nav); padding: 5px 10px;
}
.ag-l-models { display: flex; gap: 8px; flex-wrap: wrap; }
.ag-l-models span {
  font-family: 'Martian Mono', monospace; font-size: var(--ag-fs-2xs);
  color: var(--ag-text-secondary);
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-nav);
  padding: 5px 9px;
}
.ag-l-lenses {
  display: flex; flex-direction: column; gap: 14px;
  border-top: 1px solid var(--ag-border); padding-top: 28px;
}
.ag-l-lenses-h { display: flex; flex-direction: column; gap: 6px; max-width: 60ch; }
.ag-l-lenses-h h3 { font-weight: 700; font-size: 19px; }
.ag-l-lenses-h p {
  font-size: var(--ag-fs-base); line-height: 1.55;
  color: var(--ag-text-secondary);
}
.ag-l-lensgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr));
  gap: 8px;
}
.ag-l-lensgrid span {
  font-size: 12.5px; color: var(--ag-text-secondary);
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-sm); padding: 9px 12px;
}
.ag-l-ainotes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
  gap: 16px;
}
.ag-l-brandtile {
  background: var(--ag-surface-brand-band);
  border: 1px solid var(--ag-border-brand-band);
  border-radius: 14px; padding: 20px;
  display: flex; flex-direction: column; gap: 8px;
}
.ag-l-brandtile h3 { font-weight: 700; font-size: var(--ag-fs-lg); }
.ag-l-brandtile p {
  font-size: 13.5px; line-height: 1.55; color: var(--ag-text-secondary);
  text-wrap: pretty;
}

/* --- provenance band --- */
.ag-l-prov {
  background: var(--ag-surface-brand-band);
  border-top: 1px solid var(--ag-border-brand-band);
  border-bottom: 1px solid var(--ag-border-brand-band);
}
.ag-l-prov-in {
  padding-top: 64px;
  padding-bottom: 64px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.ag-l-prov h2 { font-weight: 800; font-size: var(--ag-fs-3xl); max-width: 24ch; }
.ag-l-provrow { display: flex; gap: 12px; flex-wrap: wrap; }
.ag-l-provcard {
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: 10px; padding: 14px 18px;
  display: flex; flex-direction: column; gap: 6px; min-width: 150px;
}
.ag-l-provcard-h { display: flex; align-items: center; gap: 8px; }
.ag-l-provcard-h span { font-size: var(--ag-fs-xs); color: var(--ag-text-muted); }
.ag-l-provcard b { font-size: 20px; }
.ag-l-provcard small { font-size: 10.5px; color: var(--ag-text-faint); }
.ag-l-tag {
  font-family: 'Martian Mono', monospace; font-size: 8.5px; font-weight: 500;
  border-radius: var(--ag-radius-xs); padding: 2px 6px; letter-spacing: 0.05em;
}
.ag-l-tag.fact {
  color: var(--ag-landing-up);
  background: color-mix(in srgb, var(--ag-landing-up) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-up) 35%, transparent);
}
.ag-l-tag.consensus, .ag-l-tag.source {
  color: var(--ag-landing-info);
  background: color-mix(in srgb, var(--ag-landing-info) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-info) 35%, transparent);
}
.ag-l-tag.derived {
  color: var(--ag-purple-400);
  background: color-mix(in srgb, var(--ag-brand-accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-brand-accent) 40%, transparent);
}
.ag-l-na { color: var(--ag-text-faint); }
.ag-l-prov p {
  font-size: var(--ag-fs-lg); line-height: 1.6; color: var(--ag-text-secondary);
  max-width: 78ch; text-wrap: pretty;
}
.ag-l-prov p b { font-weight: 600; }
.ag-l-prov p b.fact { color: var(--ag-landing-up); }
.ag-l-prov p b.consensus { color: var(--ag-landing-info); }
.ag-l-prov p b.derived { color: var(--ag-purple-400); }

/* --- feature bento --- */
.ag-l-bento-lg {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr));
  gap: 16px;
}
.ag-l-bento-sm {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr));
  gap: 16px;
}
.ag-l-tile {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); display: flex; flex-direction: column;
}
.ag-l-bento-lg .ag-l-tile { padding: 26px; gap: 12px; }
.ag-l-bento-sm .ag-l-tile { padding: 22px; gap: 8px; }
.ag-l-bento-lg h3 { font-weight: 700; font-size: 19px; }
.ag-l-bento-sm h3 { font-weight: 700; font-size: var(--ag-fs-lg); }
.ag-l-bento-lg p {
  font-size: var(--ag-fs-base);
  line-height: 1.6;
  color: var(--ag-text-secondary);
  text-wrap: pretty;
}
.ag-l-bento-sm p {
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ag-text-secondary);
  text-wrap: pretty;
}
.ag-l-pills { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.ag-l-pill {
  font-family: 'Martian Mono', monospace; font-size: 11px;
  color: var(--ag-brand-accent);
  background: color-mix(in srgb, var(--ag-brand-cta) 12%, transparent);
  border-radius: var(--ag-radius-xs); padding: 5px 9px;
}

/* --- depth blocks --- */
.ag-l-depth {
  padding-top: 72px; padding-bottom: 72px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr));
  gap: 48px; align-items: center;
}
.ag-l-depth-copy { display: flex; flex-direction: column; gap: 14px; }
.ag-l-eyebrow {
  font-family: 'Martian Mono', monospace; font-size: var(--ag-fs-xs);
  color: var(--ag-brand-accent); letter-spacing: 0.1em;
}
.ag-l-depth h2 { font-weight: 800; font-size: 30px; text-wrap: pretty; }
.ag-l-depth-copy p {
  font-size: var(--ag-fs-lg);
  line-height: 1.6;
  color: var(--ag-text-secondary);
  text-wrap: pretty;
}
.ag-l-flat {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); padding: 24px;
  display: flex; flex-direction: column; gap: 18px;
}
.ag-l-flat.sunken { background: var(--ag-surface-page); gap: 14px; }
.ag-l-legs { display: flex; flex-direction: column; gap: 10px; }
.ag-l-leg { display: flex; align-items: center; gap: 12px; font-size: var(--ag-fs-xs); }
.ag-l-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ag-brand-accent);
}
.ag-l-leg span { color: var(--ag-text-secondary); flex: 1; }
/* The dot is a span too, so the rule above claimed it: flex-basis 0 plus grow
   stretched the 8px dot into a 185px bar. Needs the extra specificity —
   source order does not decide this one. */
.ag-l-leg .ag-l-dot { flex: none; }
.ag-l-leg b { color: var(--ag-brand-accent); font-weight: 400; }
.ag-l-legjoin {
  margin-left: 3.5px;
  border-left: 1px dashed var(--ag-border);
  height: 14px;
}
.ag-l-split {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  border-top: 1px solid var(--ag-border);
  padding-top: 16px;
}
.ag-l-split div {
  flex: 1;
  min-width: 150px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ag-l-split small { font-size: var(--ag-fs-xs); color: var(--ag-text-muted); }
.ag-l-split .ours small { color: var(--ag-purple-400); }
.ag-l-split b { font-size: 20px; }
.ag-l-split .broker b { color: var(--ag-text-secondary); }
.ag-l-irpf { display: flex; flex-direction: column; }
.ag-l-irpf-r {
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 9px 0; border-bottom: 1px solid var(--ag-surface-card);
  font-size: 13.5px;
}
.ag-l-irpf-r:last-child { border-bottom: none; }
.ag-l-irpf-r span { color: var(--ag-text-secondary); }
.ag-l-irpf-r.total span { color: var(--ag-text-primary); font-weight: 600; }
.ag-l-irpf-r b { font-family: 'Epilogue', sans-serif; font-weight: 600; }
.ag-l-irpf-r.total b { font-weight: 700; }
.ag-l-warnrow span {
  color: var(--ag-landing-warn); display: flex; align-items: center; gap: 7px;
}
.ag-l-warnicon { width: 13px; height: 13px; flex-shrink: 0; }
.ag-l-struck { color: var(--ag-text-muted); text-decoration: line-through; }
.ag-l-disclaimer {
  background: color-mix(in srgb, var(--ag-landing-warn) 7%, transparent);
  border: 1px solid color-mix(in srgb, var(--ag-landing-warn) 30%, transparent);
  border-radius: 10px; padding: 12px 16px;
  font-size: var(--ag-fs-md); line-height: 1.55; color: var(--ag-text-secondary);
}
/* The "filing in the other country?" link under the tax panel — the reader
   who needs it is the one the page is arguing the wrong rules at. */
.ag-l-jurswitch {
  align-self: start; font-size: var(--ag-fs-sm); font-weight: 600;
  color: var(--ag-landing-info); text-decoration: none;
  border-bottom: 1px solid currentColor;
}
@media (hover: hover) { .ag-l-jurswitch:hover { color: var(--ag-text-primary); } }

/* --- trust --- */
.ag-l-trustgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
  gap: 16px;
}
.ag-l-trustitem {
  display: flex; flex-direction: column; gap: 6px;
  border-top: 2px solid var(--ag-brand-cta); padding-top: 14px;
}
.ag-l-trustitem b { font-size: var(--ag-fs-lg); font-weight: 600; }
.ag-l-trustitem span {
  font-size: var(--ag-fs-base);
  line-height: 1.55;
  color: var(--ag-text-secondary);
}

/* --- FAQ --- */
.ag-l-faq {
  max-width: 800px;
  margin: 0 auto;
  padding: 72px 24px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.ag-l-faq h2 { font-weight: 800; font-size: var(--ag-fs-2xl); }
.ag-l-qs { display: flex; flex-direction: column; gap: 8px; }
.ag-l-q {
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border);
  border-radius: 10px; padding: 14px 18px;
}
.ag-l-q summary { font-size: var(--ag-fs-lg); font-weight: 600; cursor: pointer; }
.ag-l-q p {
  margin: 10px 0 2px;
  font-size: var(--ag-fs-base);
  line-height: 1.55;
  color: var(--ag-text-secondary);
}

/* --- final CTA + footer --- */
.ag-l-final {
  padding-top: 88px; padding-bottom: 88px;
  display: flex; flex-direction: column; gap: 24px;
  align-items: center; text-align: center;
}
.ag-l-final h2 {
  font-weight: 800;
  font-size: 38px;
  letter-spacing: -0.02em;
  max-width: 24ch;
  text-wrap: pretty;
}
.ag-l-foot {
  padding-top: 32px;
  padding-bottom: 40px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.ag-l-foot-row { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.ag-l-foot-row img { width: 22px; height: auto; }
.ag-l-foot-row .ag-l-brand span { font-size: var(--ag-fs-lg); }
.ag-l-foot a { font-size: var(--ag-fs-md); color: var(--ag-text-muted); }
@media (hover: hover) { .ag-l-foot a:hover { color: var(--ag-text-secondary); } }
.ag-l-foot-lang {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ag-fs-md);
  color: var(--ag-text-muted);
}
.ag-l-foot-lang .on { font-weight: 600; color: var(--ag-text-secondary); }
.ag-l-fine {
  font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-faint);
  max-width: 90ch;
}

/* --- tablet / narrow desktop: the two-column blocks stack --- */
/* The wide layouts are auto-fit grids, which collapse on their own — but they
   collapse at whatever width their minmax() implies, and .ag-l-depth is built
   panel-first in section B. Pin the single column at one breakpoint so the
   stacking width and the reading order are both explicit. */
@media (max-width: 900px) {
  .ag-l-hero {
    grid-template-columns: 1fr;
    padding-top: 56px; padding-bottom: 44px; gap: 32px;
  }
  .ag-l-hero h1 { font-size: 38px; }
  .ag-l-depth {
    grid-template-columns: 1fr;
    padding-top: 56px; padding-bottom: 56px; gap: 32px;
  }
  .ag-l-depth .ag-l-depth-copy { order: -1; }  /* heading above its mock */
  .ag-l-sec { padding-top: 56px; padding-bottom: 56px; }
  .ag-l-prov-in { padding-top: 52px; padding-bottom: 52px; }
  .ag-l-diagrams, .ag-l-bento-lg, .ag-l-ai { grid-template-columns: 1fr; }
  .ag-l-final { padding-top: 64px; padding-bottom: 64px; }
  .ag-l-final h2 { font-size: 32px; }
}
"""


# --------------------------------------------------------------- mobile rules
# Phone layout. Kept as bare rules rather than a media block because it is
# applied two ways (see _mobile_css()): by viewport width, and again by the
# User-Agent check for phones whose CSS viewport is wider than the breakpoint.
#
# What actually changes on a ~360px screen, beyond narrower gutters:
#   * the header CTA moves to a fixed bottom bar, so it is one thumb-tap away
#     from anywhere on a very long page;
#   * the positions mock drops its € value column — four numeric columns wrap
#     inside their own cells at this width, and the P/L pair is the point;
#   * the FIFO lot strip stacks, and the FX timeline stops being a timeline
#     (its absolutely-placed labels overlap and overrun the right edge);
#   * every two-up flex pair (compare, split) becomes one column.
MOBILE_RULES = """
.ag-l { padding-bottom: 84px; }  /* clears the fixed CTA bar */
.ag-l-wrap { padding: 0 16px; }
.ag-l h1, .ag-l h2, .ag-l h3 { overflow-wrap: break-word; }

/* --- top bar: brand and language only --- */
.ag-l-bar-in { height: 54px; gap: 12px; }
.ag-l-brand img { width: 24px; }
.ag-l-brand span { font-size: var(--ag-fs-lg); }
.ag-l-ghlink, .ag-l-bar .ag-l-cta-ghost { display: none; }
.ag-l-lang a, .ag-l-lang span { padding: 8px 12px; }  /* 36px tap target */

/* --- fixed CTA bar --- */
.ag-l-mbar {
  display: block; position: fixed; left: 0; right: 0; bottom: 0; z-index: 60;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0px));
  background: color-mix(in srgb, var(--ag-surface-page) 94%, transparent);
  backdrop-filter: blur(10px);
  border-top: 1px solid var(--ag-border);
}
.ag-l-mbar .ag-l-cta {
  width: 100%; justify-content: center; box-shadow: none; padding: 12px 18px;
}
/* Out of the way while a real CTA is on screen — the hero's and the closing
   one are both full-width buttons with the same label, so an unconditional
   bar would sit directly under its own twin at the top and the bottom of the
   page. The class is JS-applied (_BAR_JS); with no JS the bar just stays up. */
.ag-l.cta-visible .ag-l-mbar {
  transform: translateY(105%); pointer-events: none;
}
.ag-l-mbar { transition: transform 160ms ease-out; }
@media (prefers-reduced-motion: reduce) {
  .ag-l-mbar { transition: none; }
}

/* --- hero --- */
.ag-l-hero { padding-top: 32px; padding-bottom: 32px; gap: 28px; }
.ag-l-hero h1 { font-size: 31px; }
.ag-l-lede { font-size: 15.5px; }
.ag-l-ctarow { flex-direction: column; align-items: stretch; gap: 6px; }
.ag-l-ctarow .ag-l-cta { width: 100%; justify-content: center; }
.ag-l-cta-text { text-align: center; padding: 10px 8px; }
.ag-l-trust { font-size: 12px; }
.ag-l-card {
  padding: 16px; gap: 14px;
  box-shadow: 0 12px 30px var(--ag-shadow-color-strong);
}
.ag-l-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 10px; }
.ag-l-kpi-v { font-size: 17px; }
.ag-l-th, .ag-l-tr { grid-template-columns: 1.2fr 1fr 0.9fr; }
.ag-l-th span:nth-child(2), .ag-l-tr span:nth-child(2) { display: none; }
.ag-l-tr { font-size: 12.5px; }

/* --- broker strip --- */
.ag-l-brokers { padding-bottom: 44px; }
.ag-l-brokergrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

/* --- sections --- */
.ag-l-sec { padding-top: 44px; padding-bottom: 44px; gap: 24px; }
.ag-l-sec h2 { font-size: var(--ag-fs-2xl); }
.ag-l-head p { font-size: var(--ag-fs-base); }
.ag-l-gap { grid-template-columns: 1fr; padding: 16px 18px; gap: 12px; }
.ag-l-diagrams, .ag-l-steps, .ag-l-bento-lg, .ag-l-bento-sm,
.ag-l-trustgrid, .ag-l-ai, .ag-l-ainotes { grid-template-columns: 1fr; }
.ag-l-step { padding: 20px; }
.ag-l-diagram { padding: 16px; }

/* --- FIFO lots stack --- */
.ag-l-lots { flex-direction: column; }
.ag-l-lots > * { flex: none !important; }  /* beats the .ag-l-f* flex weights */

/* --- FX timeline becomes a list --- */
.ag-l-tl { height: auto; display: flex; flex-direction: column; gap: 8px; }
.ag-l-tl-rail, .ag-l-tl-tick { display: none; }
.ag-l-tl-lab {
  position: static; transform: none; text-align: left; font-size: 10.5px;
  padding-left: 10px; border-left: 2px solid var(--ag-brand-accent);
}
.ag-l-tl-lab.faint { border-left-color: var(--ag-text-faint); }

/* --- two-up pairs --- */
.ag-l-compare, .ag-l-split { flex-direction: column; }
.ag-l-compare div, .ag-l-split div { min-width: 0; }

/* --- provenance --- */
.ag-l-prov-in { padding-top: 44px; padding-bottom: 44px; gap: 20px; }
.ag-l-prov h2 { font-size: var(--ag-fs-2xl); }
.ag-l-prov p { font-size: var(--ag-fs-base); }
.ag-l-provrow { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ag-l-provcard { min-width: 0; padding: 12px 14px; }
.ag-l-provcard-h { flex-wrap: wrap; }  /* the tag drops below a long label */
.ag-l-provcard b { font-size: 17px; }

/* --- depth blocks --- */
.ag-l-depth { padding-top: 44px; padding-bottom: 44px; gap: 24px; }
.ag-l-depth h2 { font-size: 25px; }
.ag-l-depth-copy p { font-size: var(--ag-fs-base); }
.ag-l-flat { padding: 16px; gap: 14px; }
.ag-l-leg { gap: 8px; flex-wrap: wrap; }
.ag-l-leg b { width: 100%; padding-left: 20px; }  /* rate drops to its own line */
.ag-l-irpf-r { font-size: 12.5px; }

/* --- bento --- */
.ag-l-bento-lg .ag-l-tile { padding: 20px; }
.ag-l-bento-sm .ag-l-tile { padding: 18px; }
.ag-l-bento-lg h3 { font-size: 17px; }

/* --- AI assistant --- */
/* The bubbles give up their inset (a 82%-wide bubble inside a 328px column is
   four words a line), and the lens grid keeps two columns: the labels are two
   or three words, so one column would be a 17-row list. */
.ag-l-chat { padding: 14px; }
.ag-l-ask, .ag-l-said { max-width: 100%; }
.ag-l-aicards .ag-l-tile { padding: 18px; }
.ag-l-aicards h3, .ag-l-lenses-h h3 { font-size: var(--ag-fs-lg); }
.ag-l-lenses { padding-top: 20px; }
.ag-l-lensgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ag-l-lensgrid span { padding: 8px 10px; font-size: 12px; }
.ag-l-brandtile { padding: 18px; }
.ag-l-badge { padding: 5px 12px; }

/* --- FAQ --- */
.ag-l-faq { padding: 44px 16px; gap: 20px; }
.ag-l-faq h2 { font-size: var(--ag-fs-2xl); }
.ag-l-q { padding: 12px 14px; }
.ag-l-q summary { font-size: var(--ag-fs-base); }

/* --- final CTA and footer --- */
.ag-l-final { padding-top: 56px; padding-bottom: 56px; gap: 18px; }
.ag-l-final h2 { font-size: 27px; }
.ag-l-final .ag-l-ctarow { width: 100%; }
.ag-l-foot { padding-top: 24px; padding-bottom: 28px; gap: 14px; }
.ag-l-foot-row { gap: 14px; }
.ag-l-fine { font-size: var(--ag-fs-xs); }
"""

# Small phones (iPhone SE and the like) — type only, the layout above holds.
# Emitted after the mobile block every time, so it wins on source order.
TINY_CSS = """
@media (max-width: 380px) {
  .ag-l-hero h1 { font-size: 28px; }
  .ag-l-depth h2 { font-size: 23px; }
  .ag-l-final h2 { font-size: 24px; }
  .ag-l-kpi-v { font-size: 16px; }
  .ag-l-tr { font-size: 12px; }
  .ag-l-provcard b { font-size: 16px; }
}
"""

CSS = (
    "<style>"
    + BASE_CSS
    + "@media (max-width: 640px) {"
    + MOBILE_RULES
    + "}"
    + TINY_CSS
    + "</style>"
)
