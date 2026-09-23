/**
 * This page's stylesheet, as the canvas draws it: setting rows inside cards,
 * and a sticky rail beside them.
 *
 * Every colour and every size is an `--ag-*` custom property the server
 * inlines — a hex written here is a colour the design system does not know
 * about, and it would be wrong in one of the two themes. Class names are all
 * `pf-`: a page owns its directory, so it owns its prefix too.
 */

export const CSS = `
.pf-head {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px;
  margin-bottom: 16px;
}
.pf-title { font-size: var(--ag-fs-2xl); font-weight: 600; margin: 0; }
.pf-savehint { font-size: var(--ag-fs-sm); color: var(--ag-text-faint); }

/* ------------------------------------------------------------- identity */
.pf-ident {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 18px 24px;
}
.pf-avatar {
  width: 52px; height: 52px; flex: 0 0 auto; border-radius: var(--ag-radius-pill);
  background: var(--ag-purple-900); border: 1px solid var(--ag-purple-800);
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: var(--ag-fs-lg); color: var(--ag-purple-400);
}
.pf-ident-t { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pf-ident-e {
  font-size: var(--ag-fs-lg); font-weight: 600; color: var(--ag-text-primary);
  overflow-wrap: anywhere;
}
.pf-ident-note { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }

/* ----------------------------------------------------------------- tabs */
.pf-tabs {
  display: flex; gap: 4px; flex-wrap: wrap; margin: 20px 0 16px;
  border-bottom: 1px solid var(--ag-border);
}
.pf-tab {
  appearance: none; background: none; border: none; cursor: pointer;
  font: inherit; font-size: var(--ag-fs-md); color: var(--ag-text-muted);
  padding: 9px 14px; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.pf-tab:hover { color: var(--ag-text-primary); }
.pf-tab-on { color: var(--ag-text-primary); border-bottom-color: var(--ag-purple-400); }
.pf-tab-n {
  margin-left: 7px; border-radius: var(--ag-radius-pill); padding: 1px 7px;
  background: var(--ag-surface-sunken); font-size: var(--ag-fs-2xs);
}

/* ------------------------------------------------- the body and its rail */
.pf-body { display: flex; align-items: flex-start; gap: 20px; }
.pf-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.pf-rail {
  flex: 0 0 320px; position: sticky; top: 1rem;
  display: flex; flex-direction: column; gap: 20px;
}

/* ---------------------------------------------------------------- cards */
.pf-card {
  background: var(--ag-surface-card); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); overflow: hidden;
}
.pf-cardhead {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
  padding: 16px 24px 14px;
}
.pf-cardtitle {
  font-size: var(--ag-fs-lg); font-weight: 600; line-height: 1.3;
  color: var(--ag-text-primary);
}
.pf-cardsub { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }
.pf-cardnote {
  border-radius: var(--ag-radius-pill); padding: 2px 9px;
  font-size: var(--ag-fs-xs); font-weight: 600;
  background: var(--ag-warn-fill); color: var(--ag-warn);
}
.pf-cardbody { padding: 0 24px 18px; display: flex; flex-direction: column; gap: 12px; }

/* --------------------------------------------------------- setting rows */
/* The divider is the row's own top border, inset like the canvas's rule. */
.pf-row { display: flex; gap: 20px; padding: 20px 24px; position: relative; }
.pf-row::before {
  content: ""; position: absolute; left: 24px; right: 24px; top: 0;
  height: 1px; background: var(--ag-border);
}
.pf-row-mid { align-items: center; }
/* Fixed label gutter, as in the canvas: the help text must not reflow with
   the viewport, and the control takes whatever is left. */
.pf-row-l { flex: 0 0 260px; display: flex; flex-direction: column; gap: 4px; }
.pf-row-lab { font-weight: 600; font-size: var(--ag-fs-md); }
.pf-row-help {
  font-size: var(--ag-fs-sm); line-height: 1.55; color: var(--ag-text-muted);
}
.pf-row-ctl { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 8px; }

/* -------------------------------------------------------------- controls */
.pf-select, .pf-input {
  font: inherit; font-size: var(--ag-fs-md); color: var(--ag-text-primary);
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-xs); padding: 7px 10px; max-width: 340px;
}
.pf-input-sm { padding: 4px 8px; font-size: var(--ag-fs-sm); max-width: 100%; }
.pf-input-wide { max-width: 100%; width: 100%; }
.pf-select:focus, .pf-input:focus { outline: 2px solid var(--ag-border-focus); }
.pf-chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.pf-chip {
  appearance: none; font: inherit; font-size: var(--ag-fs-sm); cursor: pointer;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  background: var(--ag-surface-page); color: var(--ag-text-secondary);
  padding: 5px 12px;
}
.pf-chip:hover { border-color: var(--ag-border-focus); color: var(--ag-text-primary); }
.pf-chip-on {
  background: var(--ag-purple-900); border-color: var(--ag-purple-800);
  color: var(--ag-text-primary);
}
/* Free text for the assistant. Resizes vertically only: a textarea a reader
   can drag wider than its card is a layout bug they caused themselves. */
.pf-notes {
  width: 100%; min-height: 90px; resize: vertical; font: inherit;
  font-size: var(--ag-fs-sm); padding: 8px 10px;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-sm);
  background: var(--ag-surface-page); color: var(--ag-text-primary);
}
.pf-notes:focus { outline: 2px solid var(--ag-border-focus); }
.pf-examples { list-style: none; margin: 8px 0; padding: 0; }
.pf-examples li {
  display: flex; gap: 8px; align-items: baseline; padding: 4px 0;
  font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
}
.pf-download {
  display: inline-block; font-size: var(--ag-fs-sm); text-decoration: none;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; color: var(--ag-text-primary);
  background: var(--ag-surface-page);
}
.pf-download:hover { border-color: var(--ag-border-focus); }
.pf-muted { color: var(--ag-text-muted); font-size: var(--ag-fs-sm); }
.pf-signout {
  margin-left: auto; align-self: center; white-space: nowrap;
  font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; text-decoration: none;
}
.pf-signout:hover { border-color: var(--ag-border-focus); color: var(--ag-text-primary); }
.pf-more { margin-top: 4px; }
.pf-more > summary {
  cursor: pointer; list-style: none; display: inline-block;
  border: 1px dashed var(--ag-border-focus); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
}
.pf-more > summary::-webkit-details-marker { display: none; }
.pf-more > div { margin-top: 10px; }
.pf-btn {
  appearance: none; font: inherit; font-size: var(--ag-fs-sm); cursor: pointer;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-xs);
  background: var(--ag-surface-sunken); color: var(--ag-text-primary);
  padding: 6px 12px;
}
.pf-btn:hover:enabled { border-color: var(--ag-border-focus); }
.pf-btn:disabled { opacity: 0.5; cursor: default; }
.pf-btn-p {
  background: var(--ag-purple-900); border-color: var(--ag-purple-800);
  color: var(--ag-text-primary);
}
/* The one control on this page that destroys something, coloured like it. */
.pf-btn-danger {
  background: var(--ag-loss-band); border-color: var(--ag-critical-fill);
  color: var(--ag-critical-fill); font-weight: 600;
}
/* A link the reader presses like a button — leaving the app is a navigation,
   so it stays an anchor with an href they can copy. */
.pf-linkbtn {
  align-self: flex-start; text-decoration: none;
  font-size: var(--ag-fs-sm); padding: 6px 12px;
  border: 1px solid var(--ag-purple-800); border-radius: var(--ag-radius-xs);
  background: var(--ag-purple-900); color: var(--ag-text-primary);
}
.pf-linkbtn:hover { border-color: var(--ag-border-focus); }
/* In a column that stretches its children, a button that should not. */
.pf-selfstart { align-self: flex-start; }
.pf-switch { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; }
.pf-switch input { width: 18px; height: 18px; accent-color: var(--ag-purple-400); }
.pf-switch span { font-size: var(--ag-fs-sm); color: var(--ag-text-secondary); }
.pf-err {
  font-size: var(--ag-fs-sm); line-height: 1.5; color: var(--ag-critical-fill);
}
.pf-busy { font-size: var(--ag-fs-sm); color: var(--ag-text-faint); }
.pf-warn { font-size: var(--ag-fs-sm); color: var(--ag-warn); }
.pf-hint { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); line-height: 1.55; }
.pf-badge {
  display: inline-block; border-radius: var(--ag-radius-pill); padding: 2px 10px;
  font-size: var(--ag-fs-xs); font-weight: 600;
  background: var(--ag-surface-sunken); color: var(--ag-success-fill);
}

/* ------------------------------------ what the jurisdiction decides, as facts */
.pf-rules {
  display: flex; flex-wrap: wrap; gap: 22px; margin-top: 4px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); padding: 12px 16px;
}
.pf-rule { display: flex; flex-direction: column; gap: 3px; }
.pf-rule-k { font-size: var(--ag-fs-xs); font-weight: 500; color: var(--ag-text-muted); }
.pf-rule-v { font-size: var(--ag-fs-md); font-weight: 600; color: var(--ag-text-primary); }

/* ------------------------------------------------------------- the rail */
.pf-sum { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px; }
.pf-sum-t { font-size: var(--ag-fs-lg); font-weight: 600; }
.pf-sum-row {
  display: flex; justify-content: space-between; gap: 12px; font-size: var(--ag-fs-md);
}
.pf-sum-row span { color: var(--ag-text-secondary); }
.pf-sum-row b { color: var(--ag-text-primary); font-weight: 600; text-align: right; }
.pf-sum-rule { height: 1px; background: var(--ag-border); }
.pf-sum-note { font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-muted); }

/* The persona, folded under the summary it is built from. Monospaced because
   it is a prompt and not prose: what the model reads, wrapped as it arrives. */
.pf-persona { margin-top: 14px; }
.pf-persona > summary {
  cursor: pointer; font-size: var(--ag-fs-sm); font-weight: 600;
  color: var(--ag-text-secondary);
}
.pf-persona > summary:hover { color: var(--ag-text-primary); }
.pf-persona > * { margin-top: 8px; }
.pf-persona-text {
  display: block; padding: 10px 12px; border-radius: var(--ag-radius-sm);
  background: var(--ag-surface-sunken); color: var(--ag-text-secondary);
  font-family: var(--ag-font-mono, ui-monospace, monospace);
  font-size: var(--ag-fs-sm); line-height: 1.6; white-space: pre-wrap;
}

.pf-prose { font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-secondary); }
.pf-prose p { margin: 0 0 8px; }
.pf-prose ul { margin: 0; padding-left: 18px; }
.pf-prose li { margin-bottom: 6px; }
.pf-prose code {
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
}

/* --------------------------------------------------------- the watchlist */
.pf-ticks { display: flex; flex-wrap: wrap; gap: 8px; }
.pf-tick {
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  background: var(--ag-surface-page); padding: 3px 11px;
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
  color: var(--ag-text-primary); text-decoration: none;
}
.pf-tick:hover { border-color: var(--ag-border-focus); }
.pf-res { display: flex; flex-direction: column; gap: 6px; }
.pf-resrow {
  display: flex; align-items: baseline; gap: 10px; width: 100%; text-align: left;
  padding: 8px 12px;
}
.pf-resrow-t {
  font-family: "Martian Mono", ui-monospace, monospace; font-weight: 600;
  font-size: var(--ag-fs-sm);
}
.pf-resrow-n {
  flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--ag-text-secondary);
}
.pf-resrow-k { font-size: var(--ag-fs-xs); color: var(--ag-text-faint); }
.pf-ghead {
  display: flex; align-items: center; gap: 10px; padding: 16px 0 6px;
}
.pf-gt { font-size: var(--ag-fs-md); font-weight: 600; }
.pf-gc {
  border-radius: var(--ag-radius-pill); padding: 1px 8px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  font-size: var(--ag-fs-xs); font-weight: 600; color: var(--ag-text-muted);
}
.pf-wrow {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 0; border-top: 1px solid var(--ag-border);
}
.pf-wsym {
  flex: 0 0 8.5rem; font-family: "Martian Mono", ui-monospace, monospace;
  font-size: var(--ag-fs-sm); font-weight: 600; color: var(--ag-text-primary);
  text-decoration: none; overflow: hidden; text-overflow: ellipsis;
}
.pf-wsym:hover { color: var(--ag-purple-400); }
.pf-wname { flex: 1 1 12rem; min-width: 8rem; }
.pf-wnum { flex: 0 0 7rem; }
.pf-star {
  appearance: none; background: none; border: none; cursor: pointer;
  font-size: var(--ag-fs-lg); line-height: 1; padding: 2px 4px;
  color: var(--ag-text-faint);
}
.pf-star-on { color: var(--ag-warn); }
.pf-wtags { flex: 1 1 100%; }
.pf-wtags > summary {
  cursor: pointer; list-style: none; font-size: var(--ag-fs-sm);
  color: var(--ag-text-muted);
}
.pf-wtags > summary::-webkit-details-marker { display: none; }
.pf-wtags > div { padding: 10px 0 4px; display: flex; flex-direction: column; gap: 8px; }
.pf-foot {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  padding-top: 14px; border-top: 1px solid var(--ag-border);
}

/* ------------------------------------------------- the deletion dialog */
/* A destructive control opens something before it can do anything, and what
   it opens is over the page rather than on it. */
.pf-modal {
  position: fixed; inset: 0; z-index: 40; padding: 1rem;
  display: flex; align-items: center; justify-content: center;
  background: var(--ag-surface-page-veil);
}
.pf-modal-card {
  width: 100%; max-width: 30rem; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 14px;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-md);
  background: var(--ag-surface-card); box-shadow: var(--ag-shadow-overlay);
}
.pf-modal-t { margin: 0; font-size: var(--ag-fs-xl); font-weight: 600; }
.pf-modal-confirm { display: flex; flex-direction: column; gap: 7px; }
.pf-modal-foot { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }

/* Phones: one column, no sticky rail, a narrower gutter. */
@media (max-width: 640px) {
  .pf-body { flex-direction: column; }
  .pf-rail { position: static; flex: 1 1 auto; width: 100%; }
  .pf-row { flex-direction: column; gap: 10px; padding: 14px 16px; }
  .pf-row::before { left: 16px; right: 16px; }
  .pf-row-l { flex: 1 1 auto; }
  .pf-cardhead { padding: 14px 16px 12px; }
  .pf-cardbody { padding: 0 16px 16px; }
  .pf-ident { padding: 14px 16px; }
  .pf-savehint { display: none; }
  .pf-wsym { flex: 1 1 100%; }
}
`;
