import{A as e,B as t,D as n,F as r,H as i,I as a,L as o,R as s,S as c,U as l,V as u,k as d,n as f,o as p,t as m,z as h}from"./app.js";import{t as g}from"./tickers.js";var _=l(i(),1);function v(e,t){return e instanceof s?e.detail:t}var y=3e3;function b(n){let{reload:r}=e(),[i,a]=(0,_.useState)(null),[o,s]=(0,_.useState)(null),[c,l]=(0,_.useState)(!1),[d,f]=(0,_.useState)(!1),[p,m]=(0,_.useState)(null),[g,b]=(0,_.useState)(null),x=(0,_.useCallback)(e=>e instanceof h?(r(),null):{kind:`failed`,error:v(e,n)},[r,n]);(0,_.useEffect)(()=>{let e=!0;return t(`/notify/telegram`).then(t=>e&&a(t),t=>{e&&b(x(t))}),()=>{e=!1}},[x]);let[S,C]=(0,_.useState)(()=>typeof document>`u`||!document.hidden);return(0,_.useEffect)(()=>{let e=()=>C(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,_.useEffect)(()=>{if(!o||!S)return;if(Date.now()>=o.deadline){s(null),l(!0);return}let e=!0,n=window.setInterval(()=>{if(Date.now()>=o.deadline){s(null),l(!0);return}t(`/notify/telegram`).then(t=>{e&&(f(!1),a(t),t.linked&&s(null))},()=>e&&f(!0))},y);return()=>{e=!1,window.clearInterval(n)}},[o,S]),{state:i,pending:o,expired:c,stalled:d,busy:p,note:g,connect:(0,_.useCallback)(()=>{m(`connect`),b(null),l(!1),u(`POST`,`/notify/telegram`).then(e=>{m(null),s({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{m(null),b(x(e))})},[x]),test:(0,_.useCallback)(()=>{m(`test`),b(null),u(`POST`,`/notify/telegram/test`).then(e=>{m(null),a(e),b({kind:`test_sent`})},e=>{if(m(null),e instanceof h){r();return}b({kind:`test_failed`,error:v(e,n)})})},[r,n]),unlink:(0,_.useCallback)(()=>{m(`unlink`),b(null),u(`DELETE`,`/notify/telegram`).then(e=>{m(null),a(e),s(null),l(!1),b({kind:`unlinked`})},e=>{m(null),b(x(e))})},[x])}}var x=a();function S({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,x.jsx)(x.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,x.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,x.jsx)(`code`,{children:e.slice(1,-1)},t):(0,x.jsx)(_.Fragment,{children:e},t))})}function C({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,x.jsx)(`ul`,{children:r.map((e,t)=>(0,x.jsx)(`li`,{children:(0,x.jsx)(S,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,x.jsx)(`p`,{children:(0,x.jsx)(S,{text:a})},t))}),i(-1),(0,x.jsx)(`div`,{className:t??`pf-prose`,children:n})}function w({title:e,sub:t,note:n,children:r}){return(0,x.jsxs)(`section`,{className:`pf-card`,children:[e!==void 0&&(0,x.jsxs)(`div`,{className:`pf-cardhead`,children:[(0,x.jsx)(`span`,{className:`pf-cardtitle`,children:e}),t&&(0,x.jsx)(`span`,{className:`pf-cardsub`,children:t}),n&&(0,x.jsx)(`span`,{className:`pf-cardnote`,children:n})]}),r]})}function T({label:e,help:t,middle:n,children:r}){return(0,x.jsxs)(`div`,{className:n?`pf-row pf-row-mid`:`pf-row`,children:[(0,x.jsxs)(`div`,{className:`pf-row-l`,children:[(0,x.jsx)(`span`,{className:`pf-row-lab`,children:e}),t&&(0,x.jsx)(`span`,{className:`pf-row-help`,children:(0,x.jsx)(S,{text:t})})]}),(0,x.jsx)(`div`,{className:`pf-row-ctl`,children:r})]})}function E({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,x.jsx)(`select`,{className:`pf-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,x.jsx)(`option`,{value:e,children:n(e)},e))})}function D({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,x.jsx)(`div`,{className:`pf-chips`,children:t.map(t=>(0,x.jsx)(`button`,{type:`button`,className:t===e?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function O({checked:e,onToggle:t,label:n,disabled:r}){return(0,x.jsx)(`label`,{className:`pf-switch`,children:(0,x.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function k({message:e}){return e?(0,x.jsx)(`p`,{className:`pf-err`,role:`alert`,children:e}):null}function A({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,x.jsx)(`div`,{className:`pf-chips`,children:t.map(e=>{let t=a.has(e);return(0,x.jsx)(`button`,{type:`button`,className:t?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function j({prefs:e,saving:t,failure:n,save:i}){let a=r(),o=b(a(`common.offline`)),s=e=>n?.field===e?n.message:null,c=o.state?o.state.linked:e.telegram_linked,l=o.state?.configured??(e.telegram_linked?!0:null);return(0,x.jsxs)(`div`,{className:`pf-body`,children:[(0,x.jsxs)(`div`,{className:`pf-main`,children:[(0,x.jsxs)(w,{title:a(`profile.notify_channel_title`),sub:a(`profile.notify_channel_sub`),children:[(0,x.jsxs)(`div`,{className:`pf-cardbody`,children:[l===null&&!o.note&&(0,x.jsx)(`p`,{className:`pf-busy`,children:a(`common.loading`)}),l===!1&&(0,x.jsx)(`p`,{className:`pf-hint`,children:a(`profile.tg_not_configured`)}),l===!0&&c&&(0,x.jsxs)(`span`,{className:`pf-chips`,children:[(0,x.jsx)(`span`,{className:`pf-badge`,children:a(`profile.notify_connected`)}),(0,x.jsx)(`span`,{className:`pf-hint`,children:a(`profile.tg_linked_as`,{handle:o.state?.username?`@${o.state.username}`:``}).trim()})]}),l===!0&&!c&&!o.pending&&(0,x.jsxs)(`span`,{className:`pf-chips`,children:[(0,x.jsx)(`button`,{type:`button`,className:`pf-btn pf-btn-p`,disabled:o.busy===`connect`,onClick:o.connect,children:a(`profile.tg_connect`)}),o.expired&&(0,x.jsx)(`span`,{className:`pf-warn`,children:a(`profile.tg_expired`)})]}),l===!0&&!c&&o.pending&&(0,x.jsxs)(x.Fragment,{children:[(0,x.jsx)(`a`,{className:`pf-linkbtn`,href:o.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:a(`profile.tg_open`)}),(0,x.jsx)(`p`,{className:`pf-hint`,children:(0,x.jsx)(S,{text:a(`profile.tg_manual`,{bot:o.pending.bot,code:o.pending.code})})}),(0,x.jsx)(`p`,{className:`pf-busy`,children:o.stalled?a(`profile.tg_poll_error`):a(`profile.tg_waiting`)})]}),o.note?.kind===`failed`&&(0,x.jsx)(k,{message:o.note.error}),o.note?.kind===`unlinked`&&(0,x.jsx)(`p`,{className:`pf-hint`,children:a(`profile.tg_unlinked`)})]}),l===!0&&c&&(0,x.jsxs)(x.Fragment,{children:[(0,x.jsxs)(T,{label:a(`profile.notify_test_row`),help:a(`profile.notify_test_help`),middle:!0,children:[(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:o.busy===`test`,onClick:o.test,children:a(`profile.tg_test`)}),o.note?.kind===`test_sent`&&(0,x.jsx)(`p`,{className:`pf-hint`,children:a(`profile.tg_test_sent`)}),o.note?.kind===`test_failed`&&(0,x.jsx)(k,{message:a(`profile.tg_test_failed`,{error:o.note.error})})]}),(0,x.jsx)(T,{label:a(`profile.notify_unlink_row`),help:a(`profile.notify_unlink_help`),middle:!0,children:(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:o.busy===`unlink`,onClick:o.unlink,children:a(`profile.tg_unlink`)})})]})]}),l===!0&&c&&(0,x.jsxs)(w,{title:a(`profile.notify_what_title`),sub:a(`profile.notify_what_sub`),children:[(0,x.jsxs)(T,{label:a(`profile.notify_digest`),help:a(`profile.notify_digest_help`),middle:!0,children:[(0,x.jsx)(O,{label:a(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>i(`notify_digest`,e)}),(0,x.jsx)(k,{message:s(`notify_digest`)})]}),(0,x.jsxs)(T,{label:a(`profile.notify_weekly`),help:a(`profile.notify_weekly_help`),middle:!0,children:[(0,x.jsx)(O,{label:a(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>i(`notify_weekly`,e)}),(0,x.jsx)(k,{message:s(`notify_weekly`)})]}),(0,x.jsxs)(T,{label:a(`profile.notify_alerts`),help:a(`profile.notify_alerts_help`),middle:!0,children:[(0,x.jsx)(O,{label:a(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>i(`notify_alerts`,e)}),(0,x.jsx)(k,{message:s(`notify_alerts`)})]})]})]}),(0,x.jsx)(`aside`,{className:`pf-rail`,children:(0,x.jsx)(w,{children:(0,x.jsxs)(`div`,{className:`pf-sum`,children:[(0,x.jsx)(`b`,{className:`pf-sum-t`,children:a(`profile.notify_caption`)}),(0,x.jsx)(C,{text:a(`profile.tg_how_body`)})]})})})]})}function ee(){let e=o(async()=>{let[e,n]=await Promise.all([t(`/profile-options`),t(`/profile`)]);return{options:e,profile:n}},[]);return(0,x.jsx)(m,{query:e,skeleton:(0,x.jsx)(f,{rows:8}),children:e=>(0,x.jsx)(M,{options:e.options,stored:e.profile})})}function M({options:e,stored:t}){let n=r(),[i,a]=(0,_.useState)(t),[o,s]=(0,_.useState)(null),[c,l]=(0,_.useState)(null);function d(e,r){a(e),s(r),l(null),u(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>a(e)).catch(e=>{a(t),l(v(e,n(`common.offline`)))}).finally(()=>s(null))}let f=e=>t=>n(`profile.iv_${e}_${t}`);return(0,x.jsxs)(`div`,{className:`pf-body`,children:[(0,x.jsxs)(`div`,{className:`pf-main`,children:[(0,x.jsxs)(w,{title:n(`profile.iv_how_title`),sub:n(`profile.iv_how_sub`),children:[(0,x.jsx)(T,{label:n(`profile.iv_risk`),help:n(`profile.iv_risk_help`),children:(0,x.jsx)(E,{label:n(`profile.iv_risk`),value:i.risk,options:e.risk,labelOf:f(`risk`),disabled:o===`risk`,onPick:e=>e!==i.risk&&d({...i,risk:e},`risk`)})}),(0,x.jsx)(T,{label:n(`profile.iv_horizon`),help:n(`profile.iv_horizon_help`),children:(0,x.jsx)(E,{label:n(`profile.iv_horizon`),value:i.horizon,options:e.horizon,labelOf:f(`horizon`),disabled:o===`horizon`,onPick:e=>e!==i.horizon&&d({...i,horizon:e},`horizon`)})})]}),(0,x.jsxs)(w,{title:n(`profile.iv_what_title`),sub:n(`profile.iv_what_sub`),children:[(0,x.jsx)(T,{label:n(`profile.iv_focus`),help:n(`profile.iv_focus_help`),children:(0,x.jsx)(A,{values:i.focus,options:e.focus,labelOf:f(`focus`),disabled:o===`focus`,onToggle:(e,t)=>d({...i,focus:t?[...i.focus,e]:i.focus.filter(t=>t!==e)},`focus`)})}),(0,x.jsx)(T,{label:n(`profile.iv_constraints`),help:n(`profile.iv_constraints_help`),children:(0,x.jsx)(A,{values:i.constraints,options:e.constraints,labelOf:f(`constraints`),disabled:o===`constraints`,onToggle:(e,t)=>d({...i,constraints:t?[...i.constraints,e]:i.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,x.jsxs)(w,{title:n(`profile.iv_notes_title`),sub:n(`profile.iv_caption`),children:[(0,x.jsx)(T,{label:n(`profile.iv_notes`),help:n(`profile.iv_notes_help`),children:(0,x.jsx)(F,{value:i.notes,placeholder:n(`profile.iv_notes_ph`),label:n(`profile.iv_notes`),disabled:o===`notes`,onCommit:e=>e!==i.notes&&d({...i,notes:e},`notes`)})}),(0,x.jsx)(k,{message:c})]})]}),(0,x.jsx)(`aside`,{className:`pf-rail`,children:(0,x.jsxs)(w,{children:[(0,x.jsxs)(`div`,{className:`pf-sum`,children:[(0,x.jsx)(`span`,{className:`pf-sum-t`,children:n(`profile.iv_sum_title`)}),(0,x.jsx)(P,{label:n(`profile.iv_risk`),value:n(`profile.iv_risk_${i.risk}`)}),(0,x.jsx)(P,{label:n(`profile.iv_horizon`),value:n(`profile.iv_horizon_${i.horizon}`)}),(0,x.jsx)(P,{label:n(`profile.iv_focus`),value:N(i.focus,f(`focus`),n(`profile.iv_sum_none`))}),(0,x.jsx)(P,{label:n(`profile.iv_constraints`),value:N(i.constraints,f(`constraints`),n(`profile.iv_sum_none`))}),(0,x.jsx)(`div`,{className:`pf-sum-rule`}),(0,x.jsx)(`span`,{className:`pf-sum-note`,children:n(`profile.iv_privacy`)})]}),i.persona?(0,x.jsxs)(`details`,{className:`pf-persona`,children:[(0,x.jsx)(`summary`,{children:n(`profile.iv_persona_open`)}),(0,x.jsx)(`p`,{className:`pf-sum-note`,children:n(`profile.iv_persona_help`)}),(0,x.jsx)(`code`,{className:`pf-persona-text`,children:i.persona})]}):null]})})]})}function N(e,t,n){return e.length?e.map(t).join(`, `):n}function P({label:e,value:t}){return(0,x.jsxs)(`div`,{className:`pf-sum-row`,children:[(0,x.jsx)(`span`,{children:e}),(0,x.jsx)(`b`,{children:t})]})}function F({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,_.useState)(e);return(0,_.useEffect)(()=>o(e),[e]),(0,x.jsx)(`textarea`,{className:`pf-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}var te=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],I=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ne={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function L(e){let t=ne[e];return t&&t!==e?`${t} ${e}`:e}var R={en:`English`,es:`Español`},z=[0,.08,.09];function B(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function re(e,t){if(t)return B(e,t)??B(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return B(e,n.length>1&&n[1]?.length===2?n[1]:``)??B(e,e.default)}function V(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function H({email:e,onClose:t}){let n=r(),[i,a]=(0,_.useState)(``),[o,c]=(0,_.useState)(!1),[l,d]=(0,_.useState)(null),f=V(i,e);return(0,_.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!o&&t()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[t,o]),(0,x.jsx)(`div`,{className:`pf-modal`,onClick:e=>{e.target===e.currentTarget&&!o&&t()},children:(0,x.jsxs)(`div`,{className:`pf-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":n(`profile.delete_title`),children:[(0,x.jsx)(`h2`,{className:`pf-modal-t`,children:n(`profile.delete_title`)}),(0,x.jsx)(C,{text:n(`profile.delete_body`)}),(0,x.jsxs)(`label`,{className:`pf-modal-confirm`,children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:n(`profile.delete_confirm`)}),(0,x.jsx)(`input`,{className:`pf-input pf-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:i,disabled:o,onChange:e=>a(e.target.value)})]}),(0,x.jsx)(k,{message:l}),(0,x.jsxs)(`div`,{className:`pf-modal-foot`,children:[(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:o,onClick:t,children:n(`common.cancel`)}),(0,x.jsx)(`button`,{type:`button`,className:`pf-btn pf-btn-danger`,disabled:!f||o,onClick:()=>{c(!0),d(null),u(`DELETE`,`/account`,{confirm:i.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;window.location.assign(n)},e=>{if(c(!1),e instanceof h){window.location.assign(`/auth/logout`);return}d(e instanceof s&&e.status===422?e.detail:e instanceof s?n(`profile.delete_failed`):n(`common.offline`))})},children:n(`profile.delete_button`)})]})]})})}function U(){let e=r(),t=n(),[i,a]=(0,_.useState)(!1);return(0,x.jsxs)(T,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,onClick:()=>a(!0),children:e(`profile.delete_open`)}),i&&(0,x.jsx)(H,{email:t.email??``,onClose:()=>a(!1)})]})}function W(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function G(){let e=r(),{setParams:n}=c(),i=o(()=>t(`/onboarding`),[]),a=i.state===`loaded`?W(i.data.setup):null;return(0,x.jsx)(w,{children:(0,x.jsxs)(`div`,{className:`pf-sum`,children:[(0,x.jsx)(`span`,{className:`pf-sum-t`,children:e(`tour.launch`)}),(0,x.jsx)(`span`,{className:`pf-sum-note`,children:e(`tour.launch_caption`)}),(0,x.jsx)(`button`,{type:`button`,className:`pf-btn pf-btn-p pf-selfstart`,onClick:()=>{n({tour:`1`})},children:e(`tour.launch_start`)}),a&&(0,x.jsxs)(`div`,{className:`pf-prog`,role:`progressbar`,"aria-label":e(`home.setup_progress`,{done:a[0],total:a[1]}),"aria-valuemin":0,"aria-valuemax":a[1],"aria-valuenow":a[0],children:[(0,x.jsx)(`div`,{className:`pf-prog-track`,children:(0,x.jsx)(`div`,{className:`pf-prog-fill`,style:{width:`${Math.round(a[0]/a[1]*100)}%`}})}),(0,x.jsxs)(`span`,{className:`pf-prog-n`,children:[a[0],`/`,a[1]]})]})]})})}var K=`auto`;function q({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,_.useState)(String(e)),[u,d]=(0,_.useState)(e);return u!==e&&(d(e),l(String(e))),(0,x.jsxs)(`span`,{className:`pf-chips`,children:[(0,x.jsx)(`input`,{className:`pf-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,x.jsx)(`span`,{className:`pf-hint`,children:o})]})}function J({prefs:e,saving:n,failure:i,save:a,owner:s}){let c=r(),l=o(()=>t(`/import/last`),[]),u=o(()=>t(`/portfolio/transactions`,{limit:1}),[]),d=[K,...Object.keys(R)],f=e=>e===K?c(`profile.lang_auto`):R[e]??e,p=I.includes(e.currency)?[...I]:[...I,e.currency],m=te.filter(e=>!p.includes(e)),h=o(()=>t(`/jurisdictions`),[]),g=h.state===`loaded`?h.data:null,_=[K,...(g?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===K)return`🌐 ${c(`profile.tax_residence_auto`)}`;let t=g?.jurisdictions.find(t=>t.code===e),n=c(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=g?re(g,e.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?c(`profile.tax_year_calendar`):c(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,S=y?c(`profile.tax_match_${y.matching}`):``,C=e=>i?.field===e?i.message:null;return(0,x.jsxs)(`div`,{className:`pf-body`,children:[(0,x.jsxs)(`div`,{className:`pf-main`,children:[(0,x.jsxs)(w,{title:c(`profile.ui_section`),sub:c(`profile.ui_section_sub`),children:[(0,x.jsxs)(T,{label:c(`profile.language`),help:c(`profile.language_caption`),children:[(0,x.jsx)(E,{label:c(`profile.language`),value:e.language??K,options:d,labelOf:f,disabled:n===`language`,onPick:t=>{let n=t===K?null:t;n!==e.language&&a(`language`,n)}}),(0,x.jsx)(k,{message:C(`language`)})]}),(0,x.jsxs)(T,{label:c(`profile.display_currency`),help:c(`profile.currency_caption`),children:[(0,x.jsx)(D,{value:e.currency,options:p,labelOf:L,disabled:n===`currency`,onPick:t=>t!==e.currency&&a(`currency`,t)}),m.length>0&&(0,x.jsxs)(`details`,{className:`pf-more`,children:[(0,x.jsx)(`summary`,{children:c(`profile.currency_more`,{n:m.length})}),(0,x.jsx)(`div`,{children:(0,x.jsx)(D,{value:e.currency,options:m,labelOf:L,disabled:n===`currency`,onPick:t=>t!==e.currency&&a(`currency`,t)})})]}),m.length>0&&(0,x.jsx)(`span`,{className:`pf-morehint`,children:m.join(` · `)}),(0,x.jsx)(k,{message:C(`currency`)})]})]}),(0,x.jsxs)(w,{title:c(`profile.tax_section`),note:c(`profile.tax_legal_note`),children:[(0,x.jsxs)(T,{label:c(`profile.tax_residence`),help:c(`profile.tax_residence_caption`),children:[(0,x.jsx)(E,{label:c(`profile.tax_residence`),value:e.tax_residence??K,options:_,labelOf:v,disabled:n===`tax_residence`,onPick:t=>{let n=t===K?null:t;n!==e.tax_residence&&a(`tax_residence`,n)}}),(0,x.jsx)(k,{message:C(`tax_residence`)}),y?(0,x.jsxs)(`div`,{className:`pf-rules`,children:[(0,x.jsxs)(`div`,{className:`pf-rule`,children:[(0,x.jsx)(`span`,{className:`pf-rule-k`,children:c(`profile.tax_rule_cost`)}),(0,x.jsxs)(`span`,{className:`pf-rule-v`,children:[y.currency,` · `,c(`profile.tax_rule_fx`)]})]}),(0,x.jsxs)(`div`,{className:`pf-rule`,children:[(0,x.jsx)(`span`,{className:`pf-rule-k`,children:c(`profile.tax_rule_matching`)}),(0,x.jsx)(`span`,{className:`pf-rule-v`,children:S})]}),(0,x.jsxs)(`div`,{className:`pf-rule`,children:[(0,x.jsx)(`span`,{className:`pf-rule-k`,children:c(`profile.tax_rule_year`)}),(0,x.jsx)(`span`,{className:`pf-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(t=>{let r=y.code.toLowerCase();return t===`filing_status`?(0,x.jsxs)(T,{label:c(`profile.tax_filing_status`),help:c(`profile.tax_filing_status_caption_${r}`),children:[(0,x.jsx)(E,{label:c(`profile.tax_filing_status`),value:y.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>c(`profile.tax_status_${e}`),disabled:n===`tax_filing_status`,onPick:e=>a(`tax_filing_status`,e)}),(0,x.jsx)(k,{message:C(`tax_filing_status`)})]},t):t===`church_tax_rate`?(0,x.jsxs)(T,{label:c(`profile.tax_church`),help:c(`profile.tax_church_caption`),children:[(0,x.jsx)(E,{label:c(`profile.tax_church`),value:String(z.includes(e.tax_church_rate)?e.tax_church_rate:0),options:z.map(String),labelOf:e=>c(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:n===`tax_church_rate`,onPick:e=>a(`tax_church_rate`,Number(e))}),(0,x.jsx)(k,{message:C(`tax_church_rate`)})]},t):t===`other_income`?(0,x.jsxs)(T,{label:c(`profile.tax_other_income`),help:c(`profile.tax_other_income_caption_${r}`),children:[(0,x.jsx)(q,{label:c(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:n===`tax_other_income`,onCommit:e=>a(`tax_other_income`,e)}),(0,x.jsx)(k,{message:C(`tax_other_income`)})]},t):t===`subnational_rate`?(0,x.jsxs)(T,{label:c(`profile.tax_subnational`),help:c(`profile.tax_subnational_caption`),children:[(0,x.jsx)(q,{label:c(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:n===`tax_subnational_rate`,onCommit:e=>a(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,x.jsx)(k,{message:C(`tax_subnational_rate`)})]},t):(0,x.jsxs)(T,{label:c(`profile.tax_niit`),help:c(`profile.tax_niit_caption`),middle:!0,children:[(0,x.jsx)(O,{label:c(`profile.tax_niit`),checked:e.tax_niit,disabled:n===`tax_niit`,onToggle:e=>a(`tax_niit`,e)}),(0,x.jsx)(k,{message:C(`tax_niit`)})]},t)})]}),(0,x.jsxs)(w,{title:c(`profile.data_section`),children:[(0,x.jsx)(T,{label:c(`profile.export_title`),help:c(`profile.export_help`),children:u.state===`loaded`&&u.data.total>0?(0,x.jsx)(`a`,{className:`pf-download`,href:`/api/v1/portfolio/transactions.csv`,children:c(`profile.export_button`)}):(0,x.jsx)(`span`,{className:`pf-muted`,children:c(`profile.export_none`)})}),s===!1&&(0,x.jsx)(U,{})]})]}),(0,x.jsxs)(`aside`,{className:`pf-rail`,children:[(0,x.jsx)(G,{}),(0,x.jsx)(w,{children:(0,x.jsxs)(`div`,{className:`pf-sum`,children:[(0,x.jsx)(`span`,{className:`pf-sum-t`,children:c(`profile.summary_title`)}),(0,x.jsxs)(`div`,{className:`pf-sum-row`,children:[(0,x.jsx)(`span`,{children:c(`profile.language`)}),(0,x.jsx)(`b`,{children:(f(e.language??K).split(`(`)[0]??``).trim()})]}),(0,x.jsxs)(`div`,{className:`pf-sum-row`,children:[(0,x.jsx)(`span`,{children:c(`profile.display_currency`)}),(0,x.jsx)(`b`,{children:e.currency})]}),(0,x.jsxs)(`div`,{className:`pf-sum-row`,children:[(0,x.jsx)(`span`,{children:c(`profile.tax_section`)}),(0,x.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(c(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${S}`:c(`common.loading`)})]}),(0,x.jsxs)(`div`,{className:`pf-sum-row`,children:[(0,x.jsx)(`span`,{children:c(`profile.summary_last_import`)}),(0,x.jsx)(`b`,{children:l.state===`loaded`?l.data.imported_at?.slice(0,10)??c(`profile.summary_never`):c(`common.loading`)})]}),(0,x.jsx)(`div`,{className:`pf-sum-rule`}),(0,x.jsx)(`span`,{className:`pf-sum-note`,children:c(`profile.summary_note`)})]})})]})]})}var Y=new Set([`currency`,`language`]);function ie(t){let n=e(),[r,i]=(0,_.useState)(n.prefs),[a,o]=(0,_.useState)(null),[s,c]=(0,_.useState)(null);return{prefs:r,saving:a,failure:s,save:(0,_.useCallback)((e,r)=>{o(e),c(null),u(`PATCH`,`/prefs`,{[e]:r}).then(t=>{o(null),i(t),Y.has(e)&&n.reload()},r=>{if(o(null),r instanceof h){n.reload();return}c({field:e,message:v(r,t)})})},[n,t])}}var ae=`
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
.pf-avatar img {
  width: 100%; height: 100%; border-radius: var(--ag-radius-pill); object-fit: cover;
}
.pf-ident-n {
  font-size: var(--ag-fs-lg); font-weight: 600; color: var(--ag-text-primary);
  overflow-wrap: anywhere;
}
.pf-ident-n + .pf-ident-e {
  font-size: var(--ag-fs-sm); font-weight: 400; color: var(--ag-text-secondary);
}
/* Where the files live, and what that scope means: the right-hand column of
   the card, beside the way out. */
.pf-ident-r {
  margin-left: auto; display: flex; flex-direction: column; gap: 6px;
  align-items: flex-end; min-width: 0;
}
.pf-folder {
  display: inline-flex; align-items: center; gap: 8px;
  max-width: min(420px, 100%);
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-sm); padding: 6px 10px;
  font-family: var(--ag-font-mono, ui-monospace, monospace); font-size: var(--ag-fs-xs);
  color: var(--ag-text-secondary);
}
/* text-overflow needs a block, not the flex chip itself. */
.pf-folder-p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pf-morehint {
  display: block; margin-top: 8px;
  font-size: var(--ag-fs-sm); color: var(--ag-text-faint);
}
/* The setup progress under the tour button: capabilities on, of all of them. */
.pf-prog { display: flex; align-items: center; gap: 8px; }
.pf-prog-track {
  flex: 1; height: 4px; border-radius: var(--ag-radius-pill);
  background: var(--ag-purple-800); overflow: hidden;
}
.pf-prog-fill { height: 100%; background: var(--ag-purple-400); }
.pf-prog-n {
  font-family: var(--ag-font-mono, ui-monospace, monospace); font-size: var(--ag-fs-2xs);
  font-weight: 500; color: var(--ag-purple-400);
}

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
   the viewport, and the control takes whatever is left — until what is left
   is too little to draw a control in, where the row stacks (see the
   container queries at the bottom). */
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
  border-radius: var(--ag-radius-xs); padding: 7px 10px;
  max-width: min(340px, 100%);
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
  display: inline-block; align-self: flex-start; white-space: nowrap; font-size: var(--ag-fs-sm); text-decoration: none;
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
/* The same for a lone button as a row's control: a Delete bar the width of
   the card reads as a banner, not a button. */
.pf-row-ctl > .pf-btn { align-self: flex-start; }
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
/* A basis, so a narrow box wraps a whole fact onto the next line instead of
   squeezing all three until every word sits on a line of its own. */
.pf-rule { display: flex; flex-direction: column; gap: 3px; flex: 1 1 9rem; min-width: 0; }
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
.pf-wnum { flex: 0 1 6.5rem; min-width: 5rem; text-align: right; }
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

/* Laid out by the room the page has, not the viewport's: \`.ag-main\` is the
   \`ag-main\` size container, and a viewport query cannot see the chat drawer
   — at 1440px with the drawer open wide the page gets ~480px while
   \`@media\` still believes it is on a desktop.

   First the rail goes: a 320px column beside the cards is what leaves a
   setting row too little room to draw its control in. It follows the cards
   instead of floating beside them, and stops being sticky — a sticky block
   under the content would only cover it. */
@container ag-main (max-width: 60rem) {
  .pf-body { flex-direction: column; align-items: stretch; }
  .pf-rail { position: static; flex: 1 1 auto; width: 100%; }
}

/* Then the rows stack — control under its label, as the Streamlit page lays
   them — with a narrower gutter, down to a phone or a page beside the
   drawer. */
@container ag-main (max-width: 44rem) {
  .pf-row { flex-direction: column; gap: 10px; padding: 14px 16px; }
  .pf-row-mid { align-items: stretch; }
  .pf-row::before { left: 16px; right: 16px; }
  .pf-row-l { flex: 1 1 auto; }
  .pf-cardhead { padding: 14px 16px 12px; }
  .pf-cardbody { padding: 0 16px 16px; }
  .pf-ident { padding: 14px 16px; }
  .pf-ident-r { margin-left: 0; align-items: flex-start; width: 100%; }
  .pf-savehint { display: none; }
  /* The symbol takes the rest of the star's line, so the star is not left on
     a line of its own above it. */
  .pf-wsym { flex: 1 1 calc(100% - 3rem); }
}
`,oe={analyze:`raw`},X=2;function se({listed:e,tags:n,onAdd:i,busy:a,failure:o}){let s=r(),[c,l]=(0,_.useState)(``),[u,d]=(0,_.useState)([]),[f,p]=(0,_.useState)(``),[m,h]=(0,_.useState)(!1),[g,v]=(0,_.useState)(null),[y,b]=(0,_.useState)(null),S=c.trim();(0,_.useEffect)(()=>{if(S.length<X){v(null);return}let e=!0,n=window.setTimeout(()=>{t(`/search`,{q:S,limit:8}).then(t=>e&&(v(t.matches),b(null)),()=>e&&(v([]),b(s(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(n)}},[S]);let C=e=>{i({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...u.length?{tags:u}:{}}),l(``),v(null)},T=[...new Set([...n,...u])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,x.jsx)(w,{title:s(`watchlist.add_title`),sub:s(`watchlist.add_sub`),children:(0,x.jsxs)(`div`,{className:`pf-cardbody`,children:[(0,x.jsx)(`input`,{className:`pf-input pf-input-wide`,type:`search`,"aria-label":s(`watchlist.add_title`),placeholder:s(`watchlist.add_placeholder`),value:c,onChange:e=>l(e.target.value)}),(0,x.jsxs)(`div`,{className:`pf-chips`,children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:s(`watchlist.add_groups`)}),T.map(e=>(0,x.jsx)(`button`,{type:`button`,className:u.includes(e)?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":u.includes(e),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm`,"aria-label":s(`watchlist.add_groups`),placeholder:s(`watchlist.add_groups_ph`),value:f,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(d(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,x.jsx)(`span`,{className:`pf-hint`,children:s(`watchlist.add_groups_help`)}),(0,x.jsxs)(`label`,{className:`pf-switch`,children:[(0,x.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,x.jsx)(`span`,{children:s(`watchlist.add_fav`)})]}),(0,x.jsx)(k,{message:o??y}),S.length<X?(0,x.jsx)(`p`,{className:`pf-hint`,children:s(`watchlist.add_hint`)}):g===null?(0,x.jsx)(`p`,{className:`pf-hint`,children:s(`common.loading`)}):g.length===0?(0,x.jsx)(`p`,{className:`pf-hint`,children:s(`watchlist.add_none`)}):(0,x.jsx)(`div`,{className:`pf-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),r=oe[t.kind]??t.kind;return(0,x.jsxs)(`button`,{type:`button`,className:`pf-btn pf-resrow`,disabled:n||a,title:s(n?`watchlist.add_listed`:`watchlist.kind_${r}`),onClick:()=>C(t),children:[(0,x.jsx)(`span`,{className:`pf-resrow-t`,children:t.ticker}),(0,x.jsx)(`span`,{className:`pf-resrow-n`,children:t.name}),(0,x.jsx)(`span`,{className:`pf-resrow-k`,children:n?s(`watchlist.add_listed`):(t.exchange??``)||s(`watchlist.kind_${r}`)})]},t.ticker)})})]})})}var Z=e=>e?String(e):``;function ce(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var le=[`tags`,`favorites`,`flat`];function ue(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function de(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function fe({entry:e,tags:t,busy:n,onEdit:i,onRemove:a}){let o=r(),[s,c]=(0,_.useState)(e.name),[l,u]=(0,_.useState)(e.name),[d,f]=(0,_.useState)(``),[p,m]=(0,_.useState)(Z(e.shares)),[h,v]=(0,_.useState)(Z(e.cost)),[y,b]=(0,_.useState)([e.shares,e.cost]);l!==e.name&&(u(e.name),c(e.name)),(y[0]!==e.shares||y[1]!==e.cost)&&(b([e.shares,e.cost]),m(Z(e.shares)),v(Z(e.cost)));let S=(t,n)=>{let r=ce(n,e[t]);if(r===void 0){t===`shares`?m(Z(e.shares)):v(Z(e.cost));return}i(e.ticker,{[t]:r})},C=t=>i(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),w=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,x.jsxs)(`div`,{className:`pf-wrow`,children:[(0,x.jsx)(`button`,{type:`button`,className:e.favorite?`pf-star pf-star-on`:`pf-star`,"aria-label":o(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>i(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,x.jsx)(g,{ticker:e.ticker,className:`pf-wsym`,children:e.ticker}),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm pf-wname`,"aria-label":o(`watchlist.col_name`),value:s,disabled:n,onChange:e=>c(e.target.value),onBlur:()=>s!==e.name&&i(e.ticker,{name:s}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm pf-wnum`,"aria-label":o(`watchlist.col_shares`),placeholder:o(`watchlist.col_shares`),inputMode:`decimal`,value:p,disabled:n,onChange:e=>m(e.target.value),onBlur:()=>S(`shares`,p),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm pf-wnum`,"aria-label":o(`watchlist.col_cost`),placeholder:o(`watchlist.col_cost`),title:o(`watchlist.col_cost_help`),inputMode:`decimal`,value:h,disabled:n,onChange:e=>v(e.target.value),onBlur:()=>S(`cost`,h),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:n,onClick:()=>a(e.ticker),children:o(`watchlist.act_remove`)}),(0,x.jsxs)(`details`,{className:`pf-wtags`,children:[(0,x.jsxs)(`summary`,{children:[o(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,x.jsxs)(`div`,{children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:o(`watchlist.col_tags_help`)}),(0,x.jsxs)(`div`,{className:`pf-chips`,children:[w.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,x.jsx)(`button`,{type:`button`,className:r?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":r,disabled:n,onClick:()=>C(t),children:t},t)}),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm`,"aria-label":o(`watchlist.col_tags`),placeholder:o(`watchlist.add_groups_ph`),value:d,disabled:n,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(f(``),C(t))}})]})]})]})]})}function pe({section:e,busy:t,onRename:n,onDissolve:i}){let a=r(),[o,s]=(0,_.useState)(e.tag??``);return(0,x.jsxs)(`div`,{className:`pf-ghead`,children:[(0,x.jsx)(`span`,{className:`pf-gt`,children:e.label}),(0,x.jsx)(`span`,{className:`pf-gc`,children:e.rows.length}),e.tag!==null&&(0,x.jsxs)(`details`,{className:`pf-more`,children:[(0,x.jsx)(`summary`,{children:a(`watchlist.group_manage`)}),(0,x.jsxs)(`div`,{className:`pf-chips`,children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:a(`watchlist.group_manage_help`)}),(0,x.jsx)(`input`,{className:`pf-input pf-input-sm`,"aria-label":a(`watchlist.group_rename`),value:o,disabled:t,onChange:e=>s(e.target.value)}),(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:t||!o.trim()||o.trim()===e.tag,onClick:()=>n(e.tag,o.trim()),children:a(`watchlist.group_rename_apply`)}),(0,x.jsx)(`button`,{type:`button`,className:`pf-btn`,disabled:t,title:a(`watchlist.group_delete_help`),onClick:()=>i(e.tag),children:a(`watchlist.group_delete`)})]})]})]})}function me({entries:e,reload:t}){let n=r(),[i,a]=(0,_.useState)(!1),[o,s]=(0,_.useState)(null),[c,l]=(0,_.useState)(``),[d,f]=(0,_.useState)([]),[p,m]=(0,_.useState)(`tags`),g=(e,r=`list`)=>{a(!0),s(null),e.then(()=>{a(!1),t()},e=>{if(a(!1),e instanceof h){t();return}s({where:r,message:v(e,n(`common.offline`))})})},y=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),b=new Set(e.map(e=>e.ticker.toUpperCase())),S=new Set(d.map(e=>e.toLowerCase())),T=e.filter(e=>de(e,c)&&(!S.size||e.tags.some(e=>S.has(e.toLowerCase()))));return(0,x.jsxs)(x.Fragment,{children:[(0,x.jsx)(se,{listed:b,tags:y,busy:i,failure:o?.where===`add`?o.message:null,onAdd:e=>g(u(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,x.jsx)(w,{title:n(`profile.empty_watchlist_title`),children:(0,x.jsx)(`div`,{className:`pf-cardbody`,children:(0,x.jsx)(`p`,{className:`pf-hint`,children:n(`profile.empty_watchlist_body`)})})}):(0,x.jsx)(w,{title:n(`watchlist.list_title`),sub:n(`watchlist.list_sub`),children:(0,x.jsxs)(`div`,{className:`pf-cardbody`,children:[(0,x.jsxs)(`div`,{className:`pf-chips`,children:[(0,x.jsx)(`input`,{className:`pf-input pf-input-sm`,type:`search`,"aria-label":n(`watchlist.filter`),placeholder:n(`watchlist.filter_ph`),value:c,onChange:e=>l(e.target.value)}),le.map(e=>(0,x.jsx)(`button`,{type:`button`,className:e===p?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":e===p,onClick:()=>m(e),children:n(`watchlist.group_${e}`)},e))]}),y.length>0&&(0,x.jsxs)(`div`,{className:`pf-chips`,children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:n(`watchlist.tag_filter`)}),y.map(e=>(0,x.jsx)(`button`,{type:`button`,className:S.has(e.toLowerCase())?`pf-chip pf-chip-on`:`pf-chip`,"aria-pressed":S.has(e.toLowerCase()),onClick:()=>f(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,x.jsx)(k,{message:o?.where===`list`?o.message:null}),T.length===0?(0,x.jsx)(`p`,{className:`pf-hint`,children:n(`watchlist.no_match`)}):ue(T,p,n(`watchlist.g_untagged`),{all:n(`watchlist.g_all`),favorites:n(`watchlist.g_favorites`),rest:n(`watchlist.g_rest`)}).map(e=>(0,x.jsxs)(`div`,{children:[(0,x.jsx)(pe,{section:e,busy:i,onRename:(e,t)=>g(u(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>g(u(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,x.jsx)(fe,{entry:t,tags:y,busy:i,onEdit:(e,t)=>g(u(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>g(u(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,x.jsxs)(`div`,{className:`pf-foot`,children:[(0,x.jsx)(`span`,{className:`pf-hint`,children:n(`watchlist.count`,{n:e.length})}),(0,x.jsxs)(`details`,{className:`pf-more`,children:[(0,x.jsx)(`summary`,{children:n(`watchlist.how_open`)}),(0,x.jsx)(`div`,{children:(0,x.jsx)(C,{text:n(`watchlist.how`)})})]})]})]})})]})}function he({onAdded:e}){let n=r(),[i,a]=(0,_.useState)(0),s=o(()=>t(`/watchlist/suggestions`),[i]),[c,l]=(0,_.useState)(!1),[d,f]=(0,_.useState)(null);if(s.state!==`loaded`||s.data.suggestions.length===0)return null;let p=s.data.suggestions;function m(){l(!0),f(null),p.reduce((e,t)=>e.then(()=>u(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{a(e=>e+1),e()}).catch(e=>f(v(e,n(`common.offline`)))).finally(()=>l(!1))}return(0,x.jsxs)(w,{title:n(`profile.focus_suggest_title`),children:[(0,x.jsx)(C,{text:n(`profile.focus_suggest_help`)}),(0,x.jsx)(`ul`,{className:`pf-examples`,children:p.map(e=>(0,x.jsxs)(`li`,{children:[(0,x.jsx)(g,{ticker:e.ticker,className:`pf-wsym`}),(0,x.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,x.jsx)(`button`,{type:`button`,className:`pf-linkbtn`,disabled:c,onClick:m,children:n(`profile.focus_suggest_add`,{n:p.length})}),(0,x.jsx)(k,{message:d})]})}function ge({query:e}){return(0,x.jsx)(`div`,{className:`pf-main`,children:(0,x.jsx)(m,{query:e,children:(e,t)=>(0,x.jsxs)(x.Fragment,{children:[(0,x.jsx)(me,{entries:e.entries,reload:t}),(0,x.jsx)(he,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function _e(){return d()?(0,x.jsx)(p,{text:`common.sign_in`}):(0,x.jsx)(ve,{})}function ve(){let e=r(),i=n(),{params:a,setParams:s}=c(),l=ie(e(`common.offline`)),u=o(()=>t(`/me`),[]),d=u.state===`loaded`?u.data:null,f=o(()=>t(`/watchlist`),[]),p=f.state===`loaded`?f.data.entries.length:0,[m,h]=(0,_.useState)(!1),g=d?.name?.trim()||``,v=a.get(`tab`)??``,y=Q.some(e=>e.id===v)?v:`prefs`,b=i.email??``;return(0,x.jsxs)(x.Fragment,{children:[(0,x.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:ae}),(0,x.jsxs)(`header`,{className:`pf-head`,children:[(0,x.jsx)(`h1`,{className:`pf-title`,children:e(`nav.profile`)}),(0,x.jsx)(`span`,{className:`pf-savehint`,children:e(`profile.saves_instantly`)})]}),(0,x.jsx)(w,{children:(0,x.jsxs)(`div`,{className:`pf-ident`,children:[(0,x.jsx)(`div`,{className:`pf-avatar`,"aria-hidden":`true`,children:d?.picture&&!m?(0,x.jsx)(`img`,{src:d.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>h(!0)}):$(b,g)}),(0,x.jsxs)(`div`,{className:`pf-ident-t`,children:[g&&g!==b&&(0,x.jsx)(`span`,{className:`pf-ident-n`,children:g}),(0,x.jsx)(`span`,{className:`pf-ident-e`,children:b})]}),(0,x.jsxs)(`div`,{className:`pf-ident-r`,children:[d?.data_dir&&(0,x.jsx)(`span`,{className:`pf-folder`,title:d.data_dir_full??d.data_dir,children:(0,x.jsx)(`span`,{className:`pf-folder-p`,children:d.data_dir})}),(0,x.jsx)(`span`,{className:`pf-ident-note`,children:e(`profile.account_scope`)})]}),(0,x.jsx)(`a`,{className:`pf-signout`,href:`/auth/logout`,children:e(`common.log_out`)})]})}),(0,x.jsx)(`div`,{className:`pf-tabs`,role:`tablist`,"aria-label":e(`nav.profile`),children:Q.map(t=>(0,x.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":t.id===y,className:t.id===y?`pf-tab pf-tab-on`:`pf-tab`,onClick:()=>s({tab:t.id}),children:[e(t.label),t.id===`watch`&&p>0&&(0,x.jsx)(`span`,{className:`pf-tab-n`,children:p})]},t.id))}),y===`prefs`&&(0,x.jsx)(J,{...l,owner:u.state===`loaded`?!!d?.owner:null}),y===`iv`&&(0,x.jsx)(ee,{}),y===`watch`&&(0,x.jsx)(ge,{query:f}),y===`notify`&&(0,x.jsx)(j,{...l})]})}export{_e as default,$ as initials};