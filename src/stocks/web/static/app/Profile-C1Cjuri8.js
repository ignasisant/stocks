import{At as e,Ct as t,Dt as n,Et as r,Mt as i,Ot as a,Pt as o,Tt as s,_ as c,_t as l,d as u,ht as d,kt as f,o as p,r as m,s as h,st as g,t as _,vt as v,wt as y}from"./app-BpzLHRmM.js";var b=o(i(),1);function x(e,t){return e instanceof n?e.detail:t}var S=3e3;function C(t){let{reload:n}=v(),[r,i]=(0,b.useState)(null),[o,s]=(0,b.useState)(null),[c,l]=(0,b.useState)(!1),[u,d]=(0,b.useState)(!1),[p,m]=(0,b.useState)(null),[h,g]=(0,b.useState)(null),_=(0,b.useCallback)(e=>e instanceof a?(n(),null):{kind:`failed`,error:x(e,t)},[n,t]);(0,b.useEffect)(()=>{let e=!0;return f(`/notify/telegram`).then(t=>e&&i(t),t=>{e&&g(_(t))}),()=>{e=!1}},[_]);let[y,C]=(0,b.useState)(()=>typeof document>`u`||!document.hidden);return(0,b.useEffect)(()=>{let e=()=>C(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,b.useEffect)(()=>{if(!o||!y)return;if(Date.now()>=o.deadline){s(null),l(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=o.deadline){s(null),l(!0);return}f(`/notify/telegram`).then(t=>{e&&(d(!1),i(t),t.linked&&s(null))},()=>e&&d(!0))},S);return()=>{e=!1,window.clearInterval(t)}},[o,y]),{state:r,pending:o,expired:c,stalled:u,busy:p,note:h,connect:(0,b.useCallback)(()=>{m(`connect`),g(null),l(!1),e(`POST`,`/notify/telegram`).then(e=>{m(null),s({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{m(null),g(_(e))})},[_]),test:(0,b.useCallback)(()=>{m(`test`),g(null),e(`POST`,`/notify/telegram/test`).then(e=>{m(null),i(e),g({kind:`test_sent`})},e=>{if(m(null),e instanceof a){n();return}g({kind:`test_failed`,error:x(e,t)})})},[n,t]),unlink:(0,b.useCallback)(()=>{m(`unlink`),g(null),e(`DELETE`,`/notify/telegram`).then(e=>{m(null),i(e),s(null),l(!1),g({kind:`unlinked`})},e=>{m(null),g(_(e))})},[_])}}var w=s();function T({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,w.jsx)(w.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,w.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,w.jsx)(`code`,{children:e.slice(1,-1)},t):(0,w.jsx)(b.Fragment,{children:e},t))})}function E({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,w.jsx)(`ul`,{children:r.map((e,t)=>(0,w.jsx)(`li`,{children:(0,w.jsx)(T,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,w.jsx)(`p`,{children:(0,w.jsx)(T,{text:a})},t))}),i(-1),(0,w.jsx)(`div`,{className:t??`pr-prose`,children:n})}function D({title:e,sub:t,note:n,children:r}){return(0,w.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,w.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,w.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,w.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,w.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function O({label:e,help:t,middle:n,children:r}){return(0,w.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,w.jsxs)(`div`,{className:`pr-row-l`,children:[(0,w.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,w.jsx)(`span`,{className:`pr-row-help`,children:(0,w.jsx)(T,{text:t})})]}),(0,w.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function k({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,w.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,w.jsx)(`option`,{value:e,children:n(e)},e))})}function A({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,w.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,w.jsx)(u,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function j({checked:e,onToggle:t,label:n,disabled:r}){return(0,w.jsx)(`label`,{className:`pr-switch`,children:(0,w.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function M({message:e}){return e?(0,w.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function N({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,w.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,w.jsx)(u,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ee({prefs:e,saving:t,failure:n,save:r}){let i=y(),a=C(i(`common.offline`)),o=e=>n?.field===e?n.message:null,s=a.state?a.state.linked:e.telegram_linked,c=a.state?.configured??(e.telegram_linked?!0:null);return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[c===null&&!a.note&&(0,w.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),c===!1&&(0,w.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),c===!0&&s&&(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:a.state?.username?`@${a.state.username}`:``}).trim()})]}),c===!0&&!s&&!a.pending&&(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:a.busy===`connect`,onClick:a.connect,children:i(`profile.tg_connect`)}),a.expired&&(0,w.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),c===!0&&!s&&a.pending&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(`a`,{className:`pr-linkbtn`,href:a.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,w.jsx)(`p`,{className:`pr-hint`,children:(0,w.jsx)(T,{text:i(`profile.tg_manual`,{bot:a.pending.bot,code:a.pending.code})})}),(0,w.jsx)(`p`,{className:`pr-busy`,children:a.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),a.note?.kind===`failed`&&(0,w.jsx)(M,{message:a.note.error}),a.note?.kind===`unlinked`&&(0,w.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),c===!0&&s&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsxs)(O,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`test`,onClick:a.test,children:i(`profile.tg_test`)}),a.note?.kind===`test_sent`&&(0,w.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),a.note?.kind===`test_failed`&&(0,w.jsx)(M,{message:i(`profile.tg_test_failed`,{error:a.note.error})})]}),(0,w.jsx)(O,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`unlink`,onClick:a.unlink,children:i(`profile.tg_unlink`)})})]})]}),c===!0&&s&&(0,w.jsxs)(D,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,w.jsxs)(O,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,w.jsx)(j,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,w.jsx)(M,{message:o(`notify_digest`)})]}),(0,w.jsxs)(O,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,w.jsx)(j,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,w.jsx)(M,{message:o(`notify_weekly`)})]}),(0,w.jsxs)(O,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,w.jsx)(j,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,w.jsx)(M,{message:o(`notify_alerts`)})]})]})]}),(0,w.jsx)(`aside`,{className:`pr-rail`,children:(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,w.jsx)(E,{text:i(`profile.tg_how_body`)})]})})})]})}function te(){let e=r(async()=>{let[e,t]=await Promise.all([f(`/profile-options`),f(`/profile`)]);return{options:e,profile:t}},[]);return(0,w.jsx)(_,{query:e,skeleton:(0,w.jsx)(m,{rows:8}),children:e=>(0,w.jsx)(ne,{options:e.options,stored:e.profile})})}function ne({options:t,stored:n}){let r=y(),[i,a]=(0,b.useState)(n),[o,s]=(0,b.useState)(null),[c,l]=(0,b.useState)(null);function u(t,i){a(t),s(i),l(null),e(`PUT`,`/profile`,{risk:t.risk,horizon:t.horizon,focus:t.focus,constraints:t.constraints,notes:t.notes}).then(e=>a(e)).catch(e=>{a(n),l(x(e,r(`common.offline`)))}).finally(()=>s(null))}let d=e=>t=>r(`profile.iv_${e}_${t}`);return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:r(`profile.iv_how_title`),sub:r(`profile.iv_how_sub`),children:[(0,w.jsx)(O,{label:r(`profile.iv_risk`),help:r(`profile.iv_risk_help`),children:(0,w.jsx)(k,{label:r(`profile.iv_risk`),value:i.risk,options:t.risk,labelOf:d(`risk`),disabled:o===`risk`,onPick:e=>e!==i.risk&&u({...i,risk:e},`risk`)})}),(0,w.jsx)(O,{label:r(`profile.iv_horizon`),help:r(`profile.iv_horizon_help`),children:(0,w.jsx)(k,{label:r(`profile.iv_horizon`),value:i.horizon,options:t.horizon,labelOf:d(`horizon`),disabled:o===`horizon`,onPick:e=>e!==i.horizon&&u({...i,horizon:e},`horizon`)})})]}),(0,w.jsxs)(D,{title:r(`profile.iv_what_title`),sub:r(`profile.iv_what_sub`),children:[(0,w.jsx)(O,{label:r(`profile.iv_focus`),help:r(`profile.iv_focus_help`),children:(0,w.jsx)(N,{values:i.focus,options:t.focus,labelOf:d(`focus`),disabled:o===`focus`,onToggle:(e,t)=>u({...i,focus:t?[...i.focus,e]:i.focus.filter(t=>t!==e)},`focus`)})}),(0,w.jsx)(O,{label:r(`profile.iv_constraints`),help:r(`profile.iv_constraints_help`),children:(0,w.jsx)(N,{values:i.constraints,options:t.constraints,labelOf:d(`constraints`),disabled:o===`constraints`,onToggle:(e,t)=>u({...i,constraints:t?[...i.constraints,e]:i.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,w.jsxs)(D,{title:r(`profile.iv_notes_title`),sub:r(`profile.iv_caption`),children:[(0,w.jsx)(O,{label:r(`profile.iv_notes`),help:r(`profile.iv_notes_help`),children:(0,w.jsx)(re,{value:i.notes,placeholder:r(`profile.iv_notes_ph`),label:r(`profile.iv_notes`),disabled:o===`notes`,onCommit:e=>e!==i.notes&&u({...i,notes:e},`notes`)})}),(0,w.jsx)(M,{message:c})]})]}),(0,w.jsx)(`aside`,{className:`pr-rail`,children:(0,w.jsxs)(D,{children:[(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:r(`profile.iv_sum_title`)}),(0,w.jsx)(F,{label:r(`profile.iv_risk`),value:r(`profile.iv_risk_${i.risk}`)}),(0,w.jsx)(F,{label:r(`profile.iv_horizon`),value:r(`profile.iv_horizon_${i.horizon}`)}),(0,w.jsx)(F,{label:r(`profile.iv_focus`),value:P(i.focus,d(`focus`),r(`profile.iv_sum_none`))}),(0,w.jsx)(F,{label:r(`profile.iv_constraints`),value:P(i.constraints,d(`constraints`),r(`profile.iv_sum_none`))}),(0,w.jsx)(`div`,{className:`pr-sum-rule`}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:r(`profile.iv_privacy`)})]}),i.persona?(0,w.jsxs)(`details`,{className:`pr-persona`,children:[(0,w.jsx)(`summary`,{children:r(`profile.iv_persona_open`)}),(0,w.jsx)(`p`,{className:`pr-sum-note`,children:r(`profile.iv_persona_help`)}),(0,w.jsx)(`code`,{className:`pr-persona-text`,children:i.persona})]}):null]})})]})}function P(e,t,n){return e.length?e.map(t).join(`, `):n}function F({label:e,value:t}){return(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:e}),(0,w.jsx)(`b`,{children:t})]})}function re({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,b.useState)(e);return(0,b.useEffect)(()=>o(e),[e]),(0,w.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}var ie=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],I=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ae={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function L(e){let t=ae[e];return t&&t!==e?`${t} ${e}`:e}var R={en:`English`,es:`Español`},oe={en:`🇬🇧`,es:`🇪🇸`},z=[0,.08,.09];function B(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function se(e,t){if(t)return B(e,t)??B(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return B(e,n.length>1&&n[1]?.length===2?n[1]:``)??B(e,e.default)}function V(e){return`claude mcp add --transport http topstocks ${e}`}function H(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function U({text:e,label:t}){let n=y(),[r,i]=(0,b.useState)(!1);return(0,b.useEffect)(()=>{if(!r)return;let e=setTimeout(()=>i(!1),2e3);return()=>clearTimeout(e)},[r]),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":t,onClick:()=>void navigator.clipboard?.writeText(e).then(()=>i(!0),()=>void 0),children:n(r?`profile.connector_copied`:`profile.connector_copy`)})}function W({connection:r,onGone:i}){let o=y(),s=t(),[c,l]=(0,b.useState)(!1),[u,d]=(0,b.useState)(null),f=()=>{l(!0),d(null),e(`DELETE`,`/connections/${encodeURIComponent(r.id)}`).then(i,e=>{if(l(!1),e instanceof a){window.location.assign(`/auth/logout`);return}if(e instanceof n&&e.status===404){i();return}d(e instanceof n?o(`profile.connector_revoke_failed`):o(`common.offline`))})},m=H(r.used,s);return(0,w.jsxs)(`li`,{className:`pr-conn`,children:[(0,w.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,w.jsxs)(`span`,{className:`pr-conn-name`,children:[r.client_name,!r.verified&&(0,w.jsx)(p,{title:o(`profile.connector_unverified_help`),children:o(`profile.connector_unverified`)}),r.can_write&&(0,w.jsx)(p,{title:o(`profile.connector_can_edit_help`),children:o(`profile.connector_can_edit`)})]}),(0,w.jsx)(`span`,{className:`pr-conn-meta`,children:o(`profile.connector_returns_to`,{host:r.redirect_host})}),(0,w.jsxs)(`span`,{className:`pr-conn-meta`,children:[o(`profile.connector_since`,{date:H(r.created,s)??``}),` · `,m?o(`profile.connector_used`,{date:m}):o(`profile.connector_never_used`)]}),(0,w.jsx)(M,{message:u})]}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:f,children:o(`profile.connector_revoke`)})]})}function G(){let e=r(()=>f(`/connections`),[]),[t,n]=(0,b.useState)(new Set);return e.state===`loaded`?(0,w.jsx)(K,{url:e.data.url,connections:e.data.connections.filter(e=>!t.has(e.id)),onGone:e=>n(t=>new Set(t).add(e))}):null}function K({url:e,connections:t,onGone:n}){let r=y();return!e&&t.length===0?null:(0,w.jsxs)(D,{title:r(`profile.connector_title`),sub:r(`profile.connector_sub`),children:[e&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(O,{label:r(`profile.connector_url`),help:r(`profile.connector_url_help`),children:(0,w.jsxs)(`div`,{className:`pr-copyline`,children:[(0,w.jsx)(`code`,{className:`pr-code`,children:e}),(0,w.jsx)(U,{text:e,label:r(`profile.connector_copy_url`)})]})}),(0,w.jsxs)(O,{label:r(`profile.connector_how`),children:[(0,w.jsx)(E,{text:r(`profile.connector_how_app`)}),(0,w.jsx)(`span`,{className:`pr-hint`,children:r(`profile.connector_how_code`)}),(0,w.jsxs)(`div`,{className:`pr-copyline`,children:[(0,w.jsx)(`code`,{className:`pr-code`,children:V(e)}),(0,w.jsx)(U,{text:V(e),label:r(`profile.connector_copy_command`)})]})]})]}),(0,w.jsx)(O,{label:r(`profile.connector_list`),help:r(`profile.connector_logout_note`),children:t.length===0?(0,w.jsx)(`span`,{className:`pr-muted`,children:r(`profile.connector_none`)}):(0,w.jsx)(`ul`,{className:`pr-conns`,children:t.map(e=>(0,w.jsx)(W,{connection:e,onGone:()=>n(e.id)},e.id))})})]})}function ce(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function le({email:t,onClose:r}){let i=y(),[o,s]=(0,b.useState)(``),[c,l]=(0,b.useState)(!1),[u,d]=(0,b.useState)(null),f=ce(o,t);return(0,b.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!c&&r()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[r,c]),(0,w.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!c&&r()},children:(0,w.jsxs)(`div`,{className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":i(`profile.delete_title`),children:[(0,w.jsx)(`h2`,{className:`pr-modal-t`,children:i(`profile.delete_title`)}),(0,w.jsx)(E,{text:i(`profile.delete_body`)}),(0,w.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`profile.delete_confirm`)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:t,value:o,disabled:c,onChange:e=>s(e.target.value)})]}),(0,w.jsx)(M,{message:u}),(0,w.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:r,children:i(`common.cancel`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!f||c,onClick:()=>{l(!0),d(null),e(`DELETE`,`/account`,{confirm:o.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;window.location.assign(n)},e=>{if(l(!1),e instanceof a){window.location.assign(`/auth/logout`);return}d(e instanceof n&&e.status===422?e.detail:e instanceof n?i(`profile.delete_failed`):i(`common.offline`))})},children:i(`profile.delete_button`)})]})]})})}function ue(){let e=y(),t=d(),[n,r]=(0,b.useState)(!1);return(0,w.jsxs)(O,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>r(!0),children:e(`profile.delete_open`)}),n&&(0,w.jsx)(le,{email:t.email??``,onClose:()=>r(!1)})]})}function de(){let e=y(),{setParams:t}=g(),n=r(()=>f(`/chat/memories`),[]),i=n.state===`loaded`?n.data:null;return(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:e(`profile.memory_title`)}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:e(`profile.memory_caption`)}),i&&(0,w.jsx)(`span`,{className:`pr-sum-note`,children:i.enabled?e(`profile.memory_count`,{n:i.memories.length,max:i.max}):e(`profile.memory_off`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>t({chat:`memory`}),children:e(`profile.memory_open`)})]})})}function fe(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function pe(){let e=y(),{setParams:t}=g(),n=r(()=>f(`/onboarding`),[]),i=n.state===`loaded`?fe(n.data.setup):null;return(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:e(`tour.launch`)}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:e(`tour.launch_caption`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{t({tour:`1`})},children:e(`tour.launch_start`)}),i&&(0,w.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":e(`home.setup_progress`,{done:i[0],total:i[1]}),"aria-valuemin":0,"aria-valuemax":i[1],"aria-valuenow":i[0],children:[(0,w.jsx)(`div`,{className:`pr-prog-track`,children:(0,w.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(i[0]/i[1]*100)}%`}})}),(0,w.jsxs)(`span`,{className:`pr-prog-n`,children:[i[0],`/`,i[1]]})]})]})})}var q=`auto`;function J({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,b.useState)(String(e)),[u,d]=(0,b.useState)(e);return u!==e&&(d(e),l(String(e))),(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,w.jsx)(`span`,{className:`pr-hint`,children:o})]})}function me({prefs:e,saving:t,failure:n,save:i,owner:a}){let o=y(),s=r(()=>f(`/import/last`),[]),c=r(()=>f(`/portfolio/transactions`,{limit:1}),[]),l=[q,...Object.keys(R)],u=e=>e===q?`🌐 ${o(`profile.lang_auto`)}`:`${oe[e]??``} ${R[e]??e}`.trim(),d=I.includes(e.currency)?[...I]:[...I,e.currency],p=ie.filter(e=>!d.includes(e)),m=r(()=>f(`/jurisdictions`),[]),h=m.state===`loaded`?m.data:null,g=[q,...(h?.jurisdictions??[]).map(e=>e.code)],_=e=>{if(e===q)return`🌐 ${o(`profile.tax_residence_auto`)}`;let t=h?.jurisdictions.find(t=>t.code===e),n=o(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},v=h?se(h,e.tax_residence):null,b=v?v.year_start[0]===1&&v.year_start[1]===1?o(`profile.tax_year_calendar`):o(`profile.tax_year_from`,{day:v.year_start[1],month:v.year_start[0]}):``,x=v?o(`profile.tax_match_${v.matching}`):``,S=e=>n?.field===e?n.message:null;return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:o(`profile.ui_section`),sub:o(`profile.ui_section_sub`),children:[(0,w.jsxs)(O,{label:o(`profile.language`),help:o(`profile.language_caption`),children:[(0,w.jsx)(k,{label:o(`profile.language`),value:e.language??q,options:l,labelOf:u,disabled:t===`language`,onPick:t=>{let n=t===q?null:t;n!==e.language&&i(`language`,n)}}),(0,w.jsx)(M,{message:S(`language`)})]}),(0,w.jsxs)(O,{label:o(`profile.display_currency`),help:o(`profile.currency_caption`),children:[(0,w.jsx)(A,{value:e.currency,options:d,labelOf:L,disabled:t===`currency`,onPick:t=>t!==e.currency&&i(`currency`,t)}),p.length>0&&(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:o(`profile.currency_more`,{n:p.length})}),(0,w.jsx)(`div`,{children:(0,w.jsx)(A,{value:e.currency,options:p,labelOf:L,disabled:t===`currency`,onPick:t=>t!==e.currency&&i(`currency`,t)})})]}),p.length>0&&(0,w.jsx)(`span`,{className:`pr-morehint`,children:p.join(` · `)}),(0,w.jsx)(M,{message:S(`currency`)})]})]}),(0,w.jsxs)(D,{title:o(`profile.tax_section`),note:o(`profile.tax_legal_note`),children:[(0,w.jsxs)(O,{label:o(`profile.tax_residence`),help:o(`profile.tax_residence_caption`),children:[(0,w.jsx)(k,{label:o(`profile.tax_residence`),value:e.tax_residence??q,options:g,labelOf:_,disabled:t===`tax_residence`,onPick:t=>{let n=t===q?null:t;n!==e.tax_residence&&i(`tax_residence`,n)}}),(0,w.jsx)(M,{message:S(`tax_residence`)}),v?(0,w.jsxs)(`div`,{className:`pr-rules`,children:[(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_cost`)}),(0,w.jsxs)(`span`,{className:`pr-rule-v`,children:[v.currency,` · `,o(`profile.tax_rule_fx`)]})]}),(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_matching`)}),(0,w.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_year`)}),(0,w.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(v?.settings_fields??[]).map(n=>{let r=v.code.toLowerCase();return n===`filing_status`?(0,w.jsxs)(O,{label:o(`profile.tax_filing_status`),help:o(`profile.tax_filing_status_caption_${r}`),children:[(0,w.jsx)(k,{label:o(`profile.tax_filing_status`),value:v.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:v.filing_statuses[0]??`single`,options:v.filing_statuses,labelOf:e=>o(`profile.tax_status_${e}`),disabled:t===`tax_filing_status`,onPick:e=>i(`tax_filing_status`,e)}),(0,w.jsx)(M,{message:S(`tax_filing_status`)})]},n):n===`church_tax_rate`?(0,w.jsxs)(O,{label:o(`profile.tax_church`),help:o(`profile.tax_church_caption`),children:[(0,w.jsx)(k,{label:o(`profile.tax_church`),value:String(z.includes(e.tax_church_rate)?e.tax_church_rate:0),options:z.map(String),labelOf:e=>o(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:t===`tax_church_rate`,onPick:e=>i(`tax_church_rate`,Number(e))}),(0,w.jsx)(M,{message:S(`tax_church_rate`)})]},n):n===`other_income`?(0,w.jsxs)(O,{label:o(`profile.tax_other_income`),help:o(`profile.tax_other_income_caption_${r}`),children:[(0,w.jsx)(J,{label:o(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:v.currency,disabled:t===`tax_other_income`,onCommit:e=>i(`tax_other_income`,e)}),(0,w.jsx)(M,{message:S(`tax_other_income`)})]},n):n===`subnational_rate`?(0,w.jsxs)(O,{label:o(`profile.tax_subnational`),help:o(`profile.tax_subnational_caption`),children:[(0,w.jsx)(J,{label:o(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:t===`tax_subnational_rate`,onCommit:e=>i(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,w.jsx)(M,{message:S(`tax_subnational_rate`)})]},n):(0,w.jsxs)(O,{label:o(`profile.tax_niit`),help:o(`profile.tax_niit_caption`),middle:!0,children:[(0,w.jsx)(j,{label:o(`profile.tax_niit`),checked:e.tax_niit,disabled:t===`tax_niit`,onToggle:e=>i(`tax_niit`,e)}),(0,w.jsx)(M,{message:S(`tax_niit`)})]},n)})]}),(0,w.jsxs)(D,{title:o(`profile.data_section`),children:[(0,w.jsx)(O,{label:o(`profile.export_title`),help:o(`profile.export_help`),children:c.state===`loaded`&&c.data.total>0?(0,w.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:o(`profile.export_button`)}):(0,w.jsx)(`span`,{className:`pr-muted`,children:o(`profile.export_none`)})}),a===!1&&(0,w.jsx)(ue,{})]}),(0,w.jsx)(G,{})]}),(0,w.jsxs)(`aside`,{className:`pr-rail`,children:[(0,w.jsx)(pe,{}),(0,w.jsx)(de,{}),(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:o(`profile.summary_title`)}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:o(`profile.language`)}),(0,w.jsx)(`b`,{children:(u(e.language??q).split(`(`)[0]??``).trim()})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:o(`profile.display_currency`)}),(0,w.jsx)(`b`,{children:e.currency})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:o(`profile.tax_section`)}),(0,w.jsx)(`b`,{children:v?`${v.flag?`${v.flag} `:``}${(o(`profile.tax_residence_${v.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:o(`common.loading`)})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:o(`profile.summary_last_import`)}),(0,w.jsx)(`b`,{children:s.state===`loaded`?s.data.imported_at?.slice(0,10)??o(`profile.summary_never`):o(`common.loading`)})]}),(0,w.jsx)(`div`,{className:`pr-sum-rule`}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:o(`profile.summary_note`)})]})})]})]})}var he=new Set([`currency`,`language`]);function ge(t){let n=v(),[r,i]=(0,b.useState)(n.prefs),[o,s]=(0,b.useState)(null),[c,l]=(0,b.useState)(null);return{prefs:r,saving:o,failure:c,save:(0,b.useCallback)((r,o)=>{s(r),l(null),e(`PATCH`,`/prefs`,{[r]:o}).then(e=>{s(null),i(e),he.has(r)&&n.reload()},e=>{if(s(null),e instanceof a){n.reload();return}l({field:r,message:x(e,t)})})},[n,t])}}var _e=`
.pr-head {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px;
  margin-bottom: 16px;
}
.pr-title { font-size: var(--ag-fs-2xl); font-weight: 600; margin: 0; }
.pr-savehint { font-size: var(--ag-fs-sm); color: var(--ag-text-faint); }

/* ------------------------------------------------------------- identity */
.pr-ident {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 18px 24px;
}
.pr-avatar {
  width: 52px; height: 52px; flex: 0 0 auto; border-radius: var(--ag-radius-pill);
  background: var(--ag-purple-900); border: 1px solid var(--ag-purple-800);
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: var(--ag-fs-lg); color: var(--ag-purple-400);
}
.pr-ident-t { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pr-ident-e {
  font-size: var(--ag-fs-lg); font-weight: 600; color: var(--ag-text-primary);
  overflow-wrap: anywhere;
}
.pr-ident-note { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }
.pr-avatar img {
  width: 100%; height: 100%; border-radius: var(--ag-radius-pill); object-fit: cover;
}
.pr-ident-n {
  font-size: var(--ag-fs-lg); font-weight: 600; color: var(--ag-text-primary);
  overflow-wrap: anywhere;
}
.pr-ident-n + .pr-ident-e {
  font-size: var(--ag-fs-sm); font-weight: 400; color: var(--ag-text-secondary);
}
/* Where the files live, and what that scope means: the right-hand column of
   the card, beside the way out. */
.pr-ident-r {
  margin-left: auto; display: flex; flex-direction: column; gap: 6px;
  align-items: flex-end; min-width: 0;
}
.pr-morehint {
  display: block; margin-top: 8px;
  font-size: var(--ag-fs-sm); color: var(--ag-text-faint);
}
/* The setup progress under the tour button: capabilities on, of all of them. */
.pr-prog { display: flex; align-items: center; gap: 8px; }
.pr-prog-track {
  flex: 1; height: 4px; border-radius: var(--ag-radius-pill);
  background: var(--ag-purple-800); overflow: hidden;
}
.pr-prog-fill { height: 100%; background: var(--ag-purple-400); }
.pr-prog-n {
  font-family: var(--ag-font-mono, ui-monospace, monospace); font-size: var(--ag-fs-2xs);
  font-weight: 500; color: var(--ag-purple-400);
}

/* ----------------------------------------------------------------- tabs */
.pr-tabs {
  display: flex; gap: 4px; flex-wrap: wrap; margin: 20px 0 16px;
  border-bottom: 1px solid var(--ag-border);
}
.pr-tab {
  appearance: none; background: none; border: none; cursor: pointer;
  font: inherit; font-size: var(--ag-fs-md); color: var(--ag-text-muted);
  padding: 9px 14px; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
@media (hover: hover) {
  .pr-tab:hover { color: var(--ag-text-primary); }
}
.pr-tab-on { color: var(--ag-text-primary); border-bottom-color: var(--ag-purple-400); }
.pr-tab-n {
  margin-left: 7px; border-radius: var(--ag-radius-pill); padding: 1px 7px;
  background: var(--ag-surface-sunken); font-size: var(--ag-fs-2xs);
}

/* ------------------------------------------------- the body and its rail */
.pr-body { display: flex; align-items: flex-start; gap: 20px; }
.pr-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.pr-rail {
  flex: 0 0 320px; position: sticky; top: 1rem;
  display: flex; flex-direction: column; gap: 20px;
}

/* ---------------------------------------------------------------- cards */
.pr-card {
  background: var(--ag-surface-card); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-lg); box-shadow: var(--ag-shadow-card); overflow: hidden;
}
.pr-cardhead {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
  padding: 16px 24px 14px;
}
.pr-cardtitle {
  font-size: var(--ag-fs-lg); font-weight: 600; line-height: 1.3;
  color: var(--ag-text-primary);
}
.pr-cardsub { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }
.pr-cardnote {
  border-radius: var(--ag-radius-pill); padding: 2px 9px;
  font-size: var(--ag-fs-xs); font-weight: 600;
  background: var(--ag-warn-fill); color: var(--ag-warn);
}
.pr-cardbody { padding: 0 24px 18px; display: flex; flex-direction: column; gap: 12px; }

/* --------------------------------------------------------- setting rows */
/* The divider is the row's own top border, inset like the canvas's rule. */
.pr-row { display: flex; gap: 20px; padding: 20px 24px; position: relative; }
.pr-row::before {
  content: ""; position: absolute; left: 24px; right: 24px; top: 0;
  height: 1px; background: var(--ag-border);
}
.pr-row-mid { align-items: center; }
/* Fixed label gutter, as in the canvas: the help text must not reflow with
   the viewport, and the control takes whatever is left — until what is left
   is too little to draw a control in, where the row stacks (see the
   container queries at the bottom). */
.pr-row-l { flex: 0 0 260px; display: flex; flex-direction: column; gap: 4px; }
.pr-row-lab { font-weight: 600; font-size: var(--ag-fs-md); }
.pr-row-help {
  font-size: var(--ag-fs-sm); line-height: 1.55; color: var(--ag-text-muted);
}
.pr-row-ctl { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 8px; }

/* -------------------------------------------------------------- controls */
.pr-select, .pr-input {
  font: inherit; font-size: var(--ag-fs-md); color: var(--ag-text-primary);
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-xs); padding: 7px 10px;
  max-width: min(340px, 100%);
}
.pr-input-sm { padding: 4px 8px; font-size: var(--ag-fs-sm); max-width: 100%; }
.pr-input-wide { max-width: 100%; width: 100%; }
.pr-select:focus, .pr-input:focus { outline: 2px solid var(--ag-border-focus); }
.pr-chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
/* Free text for the assistant. Resizes vertically only: a textarea a reader
   can drag wider than its card is a layout bug they caused themselves. */
.pr-notes {
  width: 100%; min-height: 90px; resize: vertical; font: inherit;
  font-size: var(--ag-fs-sm); padding: 8px 10px;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-sm);
  background: var(--ag-surface-page); color: var(--ag-text-primary);
}
.pr-notes:focus { outline: 2px solid var(--ag-border-focus); }
.pr-examples { list-style: none; margin: 8px 0; padding: 0; }
.pr-examples li {
  display: flex; gap: 8px; align-items: baseline; padding: 4px 0;
  font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
}
.pr-download {
  display: inline-block; align-self: flex-start; white-space: nowrap; font-size: var(--ag-fs-sm); text-decoration: none;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; color: var(--ag-text-primary);
  background: var(--ag-surface-page);
}
@media (hover: hover) {
  .pr-download:hover { border-color: var(--ag-border-focus); }
}
.pr-muted { color: var(--ag-text-muted); font-size: var(--ag-fs-sm); }
.pr-signout {
  margin-left: auto; align-self: center; white-space: nowrap;
  font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; text-decoration: none;
}
@media (hover: hover) {
  .pr-signout:hover { border-color: var(--ag-border-focus); color: var(--ag-text-primary); }
}
.pr-more { margin-top: 4px; }
.pr-more > summary {
  cursor: pointer; list-style: none; display: inline-block;
  border: 1px dashed var(--ag-border-focus); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
}
.pr-more > summary::-webkit-details-marker { display: none; }
.pr-more > div { margin-top: 10px; }
@media (pointer: coarse) {
  .pr-signout, .pr-more > summary { display: inline-flex; align-items: center; min-height: 44px; box-sizing: border-box; }
  .pr-btn { min-height: 44px; }
  .pr-download, .pr-linkbtn { display: inline-flex; align-items: center; min-height: 44px; box-sizing: border-box; }
}
.pr-btn {
  appearance: none; font: inherit; font-size: var(--ag-fs-sm); cursor: pointer;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-xs);
  background: var(--ag-surface-sunken); color: var(--ag-text-primary);
  padding: 6px 12px;
}
@media (hover: hover) {
  .pr-btn:hover:enabled { border-color: var(--ag-border-focus); }
}
.pr-btn:disabled { opacity: 0.5; cursor: default; }
.pr-btn-p {
  background: var(--ag-purple-900); border-color: var(--ag-purple-800);
  color: var(--ag-text-primary);
}
/* The one control on this page that destroys something, coloured like it. */
.pr-btn-danger {
  background: var(--ag-loss-band); border-color: var(--ag-critical-fill);
  color: var(--ag-critical-fill); font-weight: 600;
}
/* A link the reader presses like a button — leaving the app is a navigation,
   so it stays an anchor with an href they can copy. */
.pr-linkbtn {
  align-self: flex-start; text-decoration: none;
  font-size: var(--ag-fs-sm); padding: 6px 12px;
  border: 1px solid var(--ag-purple-800); border-radius: var(--ag-radius-xs);
  background: var(--ag-purple-900); color: var(--ag-text-primary);
}
@media (hover: hover) {
  .pr-linkbtn:hover { border-color: var(--ag-border-focus); }
}
/* In a column that stretches its children, a button that should not. */
.pr-selfstart { align-self: flex-start; }
/* The same for a lone button as a row's control: a Delete bar the width of
   the card reads as a banner, not a button. */
.pr-row-ctl > .pr-btn { align-self: flex-start; }
.pr-switch { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; }
.pr-switch input { width: 18px; height: 18px; accent-color: var(--ag-purple-400); }
.pr-switch span { font-size: var(--ag-fs-sm); color: var(--ag-text-secondary); }
.pr-err {
  font-size: var(--ag-fs-sm); line-height: 1.5; color: var(--ag-critical-fill);
}
.pr-busy { font-size: var(--ag-fs-sm); color: var(--ag-text-faint); }
.pr-warn { font-size: var(--ag-fs-sm); color: var(--ag-warn); }
.pr-hint { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); line-height: 1.55; }
.pr-badge {
  display: inline-block; border-radius: var(--ag-radius-pill); padding: 2px 10px;
  font-size: var(--ag-fs-xs); font-weight: 600;
  background: var(--ag-surface-sunken); color: var(--ag-success-fill);
}

/* ------------------------------------ what the jurisdiction decides, as facts */
.pr-rules {
  display: flex; flex-wrap: wrap; gap: 22px; margin-top: 4px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  border-radius: var(--ag-radius-md); padding: 12px 16px;
}
/* A basis, so a narrow box wraps a whole fact onto the next line instead of
   squeezing all three until every word sits on a line of its own. */
.pr-rule { display: flex; flex-direction: column; gap: 3px; flex: 1 1 9rem; min-width: 0; }
.pr-rule-k { font-size: var(--ag-fs-xs); font-weight: 500; color: var(--ag-text-muted); }
.pr-rule-v { font-size: var(--ag-fs-md); font-weight: 600; color: var(--ag-text-primary); }

/* ------------------------------------------------------------- the rail */
.pr-sum { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px; }
.pr-sum-t { font-size: var(--ag-fs-lg); font-weight: 600; }
.pr-sum-row {
  display: flex; justify-content: space-between; gap: 12px; font-size: var(--ag-fs-md);
}
.pr-sum-row span { color: var(--ag-text-secondary); }
.pr-sum-row b { color: var(--ag-text-primary); font-weight: 600; text-align: right; }
.pr-sum-rule { height: 1px; background: var(--ag-border); }
.pr-sum-note { font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-muted); }

/* The persona, folded under the summary it is built from. Monospaced because
   it is a prompt and not prose: what the model reads, wrapped as it arrives. */
.pr-persona { margin-top: 14px; }
.pr-persona > summary {
  cursor: pointer; font-size: var(--ag-fs-sm); font-weight: 600;
  color: var(--ag-text-secondary);
}
@media (hover: hover) {
  .pr-persona > summary:hover { color: var(--ag-text-primary); }
}
.pr-persona > * { margin-top: 8px; }
.pr-persona-text {
  display: block; padding: 10px 12px; border-radius: var(--ag-radius-sm);
  background: var(--ag-surface-sunken); color: var(--ag-text-secondary);
  font-family: var(--ag-font-mono, ui-monospace, monospace);
  font-size: var(--ag-fs-sm); line-height: 1.6; white-space: pre-wrap;
}

.pr-prose { font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-secondary); }
.pr-prose p { margin: 0 0 8px; }
.pr-prose ul { margin: 0; padding-left: 18px; }
.pr-prose li { margin-bottom: 6px; }
.pr-prose code {
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
}

/* ------------------------------------------------- the Claude connector */
/* Something to copy, beside the button that copies it. The text wraps rather
   than scrolls: an address cut off at the card's edge is one a reader cannot
   check against what they pasted. */
.pr-copyline { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pr-code {
  flex: 1 1 16rem; min-width: 0; overflow-wrap: anywhere;
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
  padding: 7px 10px; border-radius: var(--ag-radius-xs);
  border: 1px solid var(--ag-border); background: var(--ag-surface-sunken);
  color: var(--ag-text-primary);
}
.pr-copyline > .pr-btn { flex: 0 0 auto; }
.pr-conns { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.pr-conn {
  display: flex; align-items: center; gap: 14px; padding: 10px 0;
  border-top: 1px solid var(--ag-border);
}
.pr-conn:first-child { border-top: 0; padding-top: 0; }
.pr-conn-l { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.pr-conn-name {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-weight: 600; font-size: var(--ag-fs-md); overflow-wrap: anywhere;
}
.pr-conn-meta { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); overflow-wrap: anywhere; }
.pr-conn > .pr-btn { flex: 0 0 auto; }

/* --------------------------------------------------------- the watchlist */
.pr-ticks { display: flex; flex-wrap: wrap; gap: 8px; }
.pr-tick {
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  background: var(--ag-surface-page); padding: 3px 11px;
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
  color: var(--ag-text-primary); text-decoration: none;
}
@media (hover: hover) {
  .pr-tick:hover { border-color: var(--ag-border-focus); }
}
.pr-res { display: flex; flex-direction: column; gap: 6px; }
.pr-resrow {
  display: flex; align-items: baseline; gap: 10px; width: 100%; text-align: left;
  padding: 8px 12px;
}
.pr-resrow-t {
  font-family: "Martian Mono", ui-monospace, monospace; font-weight: 600;
  font-size: var(--ag-fs-sm);
}
.pr-resrow-n {
  flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--ag-text-secondary);
}
.pr-resrow-k { font-size: var(--ag-fs-xs); color: var(--ag-text-faint); }
.pr-ghead {
  display: flex; align-items: center; gap: 10px; padding: 16px 0 6px;
}
.pr-gt { font-size: var(--ag-fs-md); font-weight: 600; }
.pr-gc {
  border-radius: var(--ag-radius-pill); padding: 1px 8px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  font-size: var(--ag-fs-xs); font-weight: 600; color: var(--ag-text-muted);
}
.pr-wrow {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 0; border-top: 1px solid var(--ag-border);
}
.pr-wsym {
  flex: 0 0 8.5rem; font-family: "Martian Mono", ui-monospace, monospace;
  font-size: var(--ag-fs-sm); font-weight: 600; color: var(--ag-text-primary);
  text-decoration: none; overflow: hidden; text-overflow: ellipsis;
}
@media (hover: hover) {
  .pr-wsym:hover { color: var(--ag-purple-400); }
}
.pr-wname { flex: 1 1 12rem; min-width: 8rem; }
.pr-wnum { flex: 0 1 6.5rem; min-width: 5rem; text-align: right; }
.pr-wnum { flex: 0 0 7rem; }
.pr-star {
  appearance: none; background: none; border: none; cursor: pointer;
  font-size: var(--ag-fs-lg); line-height: 1; padding: 2px 4px;
  color: var(--ag-text-faint);
}
.pr-star-on { color: var(--ag-warn); }
.pr-wtags { flex: 1 1 100%; }
.pr-wtags > summary {
  cursor: pointer; list-style: none; font-size: var(--ag-fs-sm);
  color: var(--ag-text-muted);
}
.pr-wtags > summary::-webkit-details-marker { display: none; }
.pr-wtags > div { padding: 10px 0 4px; display: flex; flex-direction: column; gap: 8px; }
.pr-foot {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  padding-top: 14px; border-top: 1px solid var(--ag-border);
}

/* ------------------------------------------------- the deletion dialog */
/* A destructive control opens something before it can do anything, and what
   it opens is over the page rather than on it. */
.pr-modal {
  position: fixed; inset: 0; z-index: 40; padding: 1rem;
  display: flex; align-items: center; justify-content: center;
  background: var(--ag-surface-page-veil);
}
.pr-modal-card {
  width: 100%; max-width: 30rem; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 14px;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-md);
  background: var(--ag-surface-card); box-shadow: var(--ag-shadow-overlay);
}
.pr-modal-t { margin: 0; font-size: var(--ag-fs-xl); font-weight: 600; }
.pr-modal-confirm { display: flex; flex-direction: column; gap: 7px; }
.pr-modal-foot { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }

/* Laid out by the room the page has, not the viewport's: \`.ag-main\` is the
   \`ag-main\` size container, and a viewport query cannot see the chat drawer
   — at 1440px with the drawer open wide the page gets ~480px while
   \`@media\` still believes it is on a desktop.

   First the rail goes: a 320px column beside the cards is what leaves a
   setting row too little room to draw its control in. It follows the cards
   instead of floating beside them, and stops being sticky — a sticky block
   under the content would only cover it. */
@container ag-main (max-width: 60rem) {
  .pr-body { flex-direction: column; align-items: stretch; }
  .pr-rail { position: static; flex: 1 1 auto; width: 100%; }
}

/* Then the rows stack — control under its label — with a narrower gutter,
   down to a phone or a page beside the drawer. */
@container ag-main (max-width: 44rem) {
  .pr-row { flex-direction: column; gap: 10px; padding: 14px 16px; }
  .pr-row-mid { align-items: stretch; }
  .pr-row::before { left: 16px; right: 16px; }
  .pr-row-l { flex: 1 1 auto; }
  .pr-cardhead { padding: 14px 16px 12px; }
  .pr-cardbody { padding: 0 16px 16px; }
  .pr-ident { padding: 14px 16px; }
  .pr-ident-r { margin-left: 0; align-items: flex-start; width: 100%; }
  .pr-savehint { display: none; }
  /* The symbol takes the rest of the star's line, so the star is not left on
     a line of its own above it. */
  .pr-wsym { flex: 1 1 calc(100% - 3rem); }
}
`,ve={analyze:`raw`},Y=2;function ye({listed:e,tags:t,onAdd:n,busy:r,failure:i}){let a=y(),[o,s]=(0,b.useState)(``),[c,l]=(0,b.useState)([]),[d,p]=(0,b.useState)(``),[m,h]=(0,b.useState)(!1),[g,_]=(0,b.useState)(null),[v,x]=(0,b.useState)(null),S=o.trim();(0,b.useEffect)(()=>{if(S.length<Y){_(null);return}let e=!0,t=window.setTimeout(()=>{f(`/search`,{q:S,limit:8}).then(t=>e&&(_(t.matches),x(null)),()=>e&&(_([]),x(a(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[S]);let C=e=>{n({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...c.length?{tags:c}:{}}),s(``),_(null)},T=[...new Set([...t,...c])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,w.jsx)(D,{title:a(`watchlist.add_title`),sub:a(`watchlist.add_sub`),children:(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,w.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,"aria-label":a(`watchlist.add_title`),placeholder:a(`watchlist.add_placeholder`),value:o,onChange:e=>s(e.target.value)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups`)}),T.map(e=>(0,w.jsx)(u,{on:c.includes(e),onClick:()=>l(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.add_groups`),placeholder:a(`watchlist.add_groups_ph`),value:d,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(l(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,w.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups_help`)}),(0,w.jsxs)(`label`,{className:`pr-switch`,children:[(0,w.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,w.jsx)(`span`,{children:a(`watchlist.add_fav`)})]}),(0,w.jsx)(M,{message:i??v}),S.length<Y?(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_hint`)}):g===null?(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`common.loading`)}):g.length===0?(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_none`)}):(0,w.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),i=ve[t.kind]??t.kind;return(0,w.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||r,title:a(n?`watchlist.add_listed`:`watchlist.kind_${i}`),onClick:()=>C(t),children:[(0,w.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,w.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,w.jsx)(`span`,{className:`pr-resrow-k`,children:n?a(`watchlist.add_listed`):(t.exchange??``)||a(`watchlist.kind_${i}`)})]},t.ticker)})})]})})}var X=e=>e?String(e):``;function be(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var xe=[`tags`,`favorites`,`flat`];function Z(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function Se(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Ce({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let a=y(),[o,s]=(0,b.useState)(e.name),[c,l]=(0,b.useState)(e.name),[d,f]=(0,b.useState)(``),[p,m]=(0,b.useState)(X(e.shares)),[g,_]=(0,b.useState)(X(e.cost)),[v,x]=(0,b.useState)([e.shares,e.cost]);c!==e.name&&(l(e.name),s(e.name)),(v[0]!==e.shares||v[1]!==e.cost)&&(x([e.shares,e.cost]),m(X(e.shares)),_(X(e.cost)));let S=(t,n)=>{let i=be(n,e[t]);if(i===void 0){t===`shares`?m(X(e.shares)):_(X(e.cost));return}r(e.ticker,{[t]:i})},C=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),T=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,w.jsxs)(`div`,{className:`pr-wrow`,children:[(0,w.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":a(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,w.jsx)(h,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":a(`watchlist.col_name`),value:o,disabled:n,onChange:e=>s(e.target.value),onBlur:()=>o!==e.name&&r(e.ticker,{name:o}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_shares`),placeholder:a(`watchlist.col_shares`),inputMode:`decimal`,value:p,disabled:n,onChange:e=>m(e.target.value),onBlur:()=>S(`shares`,p),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_cost`),placeholder:a(`watchlist.col_cost`),title:a(`watchlist.col_cost_help`),inputMode:`decimal`,value:g,disabled:n,onChange:e=>_(e.target.value),onBlur:()=>S(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:a(`watchlist.act_remove`)}),(0,w.jsxs)(`details`,{className:`pr-wtags`,children:[(0,w.jsxs)(`summary`,{children:[a(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,w.jsxs)(`div`,{children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.col_tags_help`)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[T.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,w.jsx)(u,{on:r,disabled:n,onClick:()=>C(t),children:t},t)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.col_tags`),placeholder:a(`watchlist.add_groups_ph`),value:d,disabled:n,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(f(``),C(t))}})]})]})]})]})}function we({section:e,busy:t,onRename:n,onDissolve:r}){let i=y(),[a,o]=(0,b.useState)(e.tag??``);return(0,w.jsxs)(`div`,{className:`pr-ghead`,children:[(0,w.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,w.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),value:a,disabled:t,onChange:e=>o(e.target.value)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!a.trim()||a.trim()===e.tag,onClick:()=>n(e.tag,a.trim()),children:i(`watchlist.group_rename_apply`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function Te({entries:t,reload:n}){let r=y(),[i,o]=(0,b.useState)(!1),[s,c]=(0,b.useState)(null),[l,d]=(0,b.useState)(``),[f,p]=(0,b.useState)([]),[m,h]=(0,b.useState)(`tags`),g=(e,t=`list`)=>{o(!0),c(null),e.then(()=>{o(!1),n()},e=>{if(o(!1),e instanceof a){n();return}c({where:t,message:x(e,r(`common.offline`))})})},_=[...new Set(t.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),v=new Set(t.map(e=>e.ticker.toUpperCase())),S=new Set(f.map(e=>e.toLowerCase())),C=t.filter(e=>Se(e,l)&&(!S.size||e.tags.some(e=>S.has(e.toLowerCase()))));return(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(ye,{listed:v,tags:_,busy:i,failure:s?.where===`add`?s.message:null,onAdd:t=>g(e(`POST`,`/watchlist`,t),`add`)}),t.length===0?(0,w.jsx)(D,{title:r(`profile.empty_watchlist_title`),children:(0,w.jsx)(`div`,{className:`pr-cardbody`,children:(0,w.jsx)(`p`,{className:`pr-hint`,children:r(`profile.empty_watchlist_body`)})})}):(0,w.jsx)(D,{title:r(`watchlist.list_title`),sub:r(`watchlist.list_sub`),children:(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,"aria-label":r(`watchlist.filter`),placeholder:r(`watchlist.filter_ph`),value:l,onChange:e=>d(e.target.value)}),xe.map(e=>(0,w.jsx)(u,{on:e===m,onClick:()=>h(e),children:r(`watchlist.group_${e}`)},e))]}),_.length>0&&(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.tag_filter`)}),_.map(e=>(0,w.jsx)(u,{on:S.has(e.toLowerCase()),onClick:()=>p(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,w.jsx)(M,{message:s?.where===`list`?s.message:null}),C.length===0?(0,w.jsx)(`p`,{className:`pr-hint`,children:r(`watchlist.no_match`)}):Z(C,m,r(`watchlist.g_untagged`),{all:r(`watchlist.g_all`),favorites:r(`watchlist.g_favorites`),rest:r(`watchlist.g_rest`)}).map(t=>(0,w.jsxs)(`div`,{children:[(0,w.jsx)(we,{section:t,busy:i,onRename:(t,n)=>g(e(`PATCH`,`/watchlist/tags/${encodeURIComponent(t)}`,{name:n})),onDissolve:t=>g(e(`DELETE`,`/watchlist/tags/${encodeURIComponent(t)}`))}),t.rows.map(n=>(0,w.jsx)(Ce,{entry:n,tags:_,busy:i,onEdit:(t,n)=>g(e(`PATCH`,`/watchlist/${encodeURIComponent(t)}`,n)),onRemove:t=>g(e(`DELETE`,`/watchlist/${encodeURIComponent(t)}`))},`${t.id}_${n.ticker}`))]},t.id)),(0,w.jsxs)(`div`,{className:`pr-foot`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.count`,{n:t.length})}),(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:r(`watchlist.how_open`)}),(0,w.jsx)(`div`,{children:(0,w.jsx)(E,{text:r(`watchlist.how`)})})]})]})]})})]})}function Ee({onAdded:t}){let n=y(),[i,a]=(0,b.useState)(0),o=r(()=>f(`/watchlist/suggestions`),[i]),[s,c]=(0,b.useState)(!1),[l,u]=(0,b.useState)(null);if(o.state!==`loaded`||o.data.suggestions.length===0)return null;let d=o.data.suggestions;function p(){c(!0),u(null),d.reduce((t,n)=>t.then(()=>e(`POST`,`/watchlist`,{ticker:n.ticker,name:n.name,tags:n.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{a(e=>e+1),t()}).catch(e=>u(x(e,n(`common.offline`)))).finally(()=>c(!1))}return(0,w.jsxs)(D,{title:n(`profile.focus_suggest_title`),children:[(0,w.jsx)(E,{text:n(`profile.focus_suggest_help`)}),(0,w.jsx)(`ul`,{className:`pr-examples`,children:d.map(e=>(0,w.jsxs)(`li`,{children:[(0,w.jsx)(h,{ticker:e.ticker,className:`pr-wsym`}),(0,w.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,w.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:s,onClick:p,children:n(`profile.focus_suggest_add`,{n:d.length})}),(0,w.jsx)(M,{message:l})]})}function De({query:e}){return(0,w.jsx)(`div`,{className:`pr-main`,children:(0,w.jsx)(_,{query:e,children:(e,t)=>(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(Te,{entries:e.entries,reload:t}),(0,w.jsx)(Ee,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Oe(){return l()?(0,w.jsx)(c,{text:`common.sign_in`}):(0,w.jsx)(ke,{})}function ke(){let e=y(),t=d(),{params:n,setParams:i}=g(),a=ge(e(`common.offline`)),o=r(()=>f(`/me`),[]),s=o.state===`loaded`?o.data:null,c=r(()=>f(`/watchlist`),[]),l=c.state===`loaded`?c.data.entries.length:0,[u,p]=(0,b.useState)(!1),m=s?.name?.trim()||``,h=n.get(`tab`)??``,_=Q.some(e=>e.id===h)?h:`prefs`,v=t.email??``;return(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:_e}),(0,w.jsxs)(`header`,{className:`pr-head`,children:[(0,w.jsx)(`h1`,{className:`pr-title`,children:e(`nav.profile`)}),(0,w.jsx)(`span`,{className:`pr-savehint`,children:e(`profile.saves_instantly`)})]}),(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-ident`,children:[(0,w.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:s?.picture&&!u?(0,w.jsx)(`img`,{src:s.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>p(!0)}):$(v,m)}),(0,w.jsxs)(`div`,{className:`pr-ident-t`,children:[m&&m!==v&&(0,w.jsx)(`span`,{className:`pr-ident-n`,children:m}),(0,w.jsx)(`span`,{className:`pr-ident-e`,children:v})]}),(0,w.jsx)(`div`,{className:`pr-ident-r`,children:(0,w.jsx)(`span`,{className:`pr-ident-note`,children:e(`profile.account_scope`)})}),(0,w.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,children:e(`common.log_out`)})]})}),(0,w.jsx)(`div`,{className:`pr-tabs`,role:`tablist`,"aria-label":e(`nav.profile`),children:Q.map(t=>(0,w.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":t.id===_,className:t.id===_?`pr-tab pr-tab-on`:`pr-tab`,onClick:()=>i({tab:t.id}),children:[e(t.label),t.id===`watch`&&l>0&&(0,w.jsx)(`span`,{className:`pr-tab-n`,children:l})]},t.id))}),_===`prefs`&&(0,w.jsx)(me,{...a,owner:o.state===`loaded`?!!s?.owner:null}),_===`iv`&&(0,w.jsx)(te,{}),_===`watch`&&(0,w.jsx)(De,{query:c}),_===`notify`&&(0,w.jsx)(ee,{...a})]})}export{Oe as default,$ as initials};