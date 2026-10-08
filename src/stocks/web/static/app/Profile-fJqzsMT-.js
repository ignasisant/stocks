import{At as e,Dt as t,Et as n,Ft as r,Lt as i,Nt as a,Ot as o,Tt as s,_t as c,a as l,bt as u,g as d,jt as f,kt as p,lt as m,o as h,r as g,t as _,u as v,yt as y}from"./app-BJIeYh17.js";var b=i(r(),1);function x(e,t){return e instanceof p?e.detail:t}var S=3e3;function C(t){let{reload:n}=u(),[r,i]=(0,b.useState)(null),[o,s]=(0,b.useState)(null),[c,l]=(0,b.useState)(!1),[d,p]=(0,b.useState)(!1),[m,h]=(0,b.useState)(null),[g,_]=(0,b.useState)(null),v=(0,b.useCallback)(r=>r instanceof e?(n(),null):{kind:`failed`,error:x(r,t)},[n,t]);(0,b.useEffect)(()=>{let e=!0;return f(`/notify/telegram`).then(t=>e&&i(t),t=>{e&&_(v(t))}),()=>{e=!1}},[v]);let[y,C]=(0,b.useState)(()=>typeof document>`u`||!document.hidden);return(0,b.useEffect)(()=>{let e=()=>C(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,b.useEffect)(()=>{if(!o||!y)return;if(Date.now()>=o.deadline){s(null),l(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=o.deadline){s(null),l(!0);return}f(`/notify/telegram`).then(t=>{e&&(p(!1),i(t),t.linked&&s(null))},()=>e&&p(!0))},S);return()=>{e=!1,window.clearInterval(t)}},[o,y]),{state:r,pending:o,expired:c,stalled:d,busy:m,note:g,connect:(0,b.useCallback)(()=>{h(`connect`),_(null),l(!1),a(`POST`,`/notify/telegram`).then(e=>{h(null),s({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{h(null),_(v(e))})},[v]),test:(0,b.useCallback)(()=>{h(`test`),_(null),a(`POST`,`/notify/telegram/test`).then(e=>{h(null),i(e),_({kind:`test_sent`})},r=>{if(h(null),r instanceof e){n();return}_({kind:`test_failed`,error:x(r,t)})})},[n,t]),unlink:(0,b.useCallback)(()=>{h(`unlink`),_(null),a(`DELETE`,`/notify/telegram`).then(e=>{h(null),i(e),s(null),l(!1),_({kind:`unlinked`})},e=>{h(null),_(v(e))})},[v])}}var w=t();function T({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,w.jsx)(w.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,w.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,w.jsx)(`code`,{children:e.slice(1,-1)},t):(0,w.jsx)(b.Fragment,{children:e},t))})}function E({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,w.jsx)(`ul`,{children:r.map((e,t)=>(0,w.jsx)(`li`,{children:(0,w.jsx)(T,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,w.jsx)(`p`,{children:(0,w.jsx)(T,{text:a})},t))}),i(-1),(0,w.jsx)(`div`,{className:t??`pr-prose`,children:n})}function D({title:e,sub:t,note:n,children:r}){return(0,w.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,w.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,w.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,w.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,w.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function O({label:e,help:t,middle:n,children:r}){return(0,w.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,w.jsxs)(`div`,{className:`pr-row-l`,children:[(0,w.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,w.jsx)(`span`,{className:`pr-row-help`,children:(0,w.jsx)(T,{text:t})})]}),(0,w.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function k({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,w.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,w.jsx)(`option`,{value:e,children:n(e)},e))})}function A({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,w.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,w.jsx)(v,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function j({checked:e,onToggle:t,label:n,disabled:r}){return(0,w.jsx)(`label`,{className:`pr-switch`,children:(0,w.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function M({message:e}){return e?(0,w.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function N({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,w.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,w.jsx)(v,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ee({prefs:e,saving:t,failure:r,save:i}){let a=n(),o=C(a(`common.offline`)),s=e=>r?.field===e?r.message:null,c=o.state?o.state.linked:e.telegram_linked,l=o.state?.configured??(e.telegram_linked?!0:null);return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:a(`profile.notify_channel_title`),sub:a(`profile.notify_channel_sub`),children:[(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[l===null&&!o.note&&(0,w.jsx)(`p`,{className:`pr-busy`,children:a(`common.loading`)}),l===!1&&(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_not_configured`)}),l===!0&&c&&(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-badge`,children:a(`profile.notify_connected`)}),(0,w.jsx)(`span`,{className:`pr-hint`,children:a(`profile.tg_linked_as`,{handle:o.state?.username?`@${o.state.username}`:``}).trim()})]}),l===!0&&!c&&!o.pending&&(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:o.busy===`connect`,onClick:o.connect,children:a(`profile.tg_connect`)}),o.expired&&(0,w.jsx)(`span`,{className:`pr-warn`,children:a(`profile.tg_expired`)})]}),l===!0&&!c&&o.pending&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(`a`,{className:`pr-linkbtn`,href:o.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:a(`profile.tg_open`)}),(0,w.jsx)(`p`,{className:`pr-hint`,children:(0,w.jsx)(T,{text:a(`profile.tg_manual`,{bot:o.pending.bot,code:o.pending.code})})}),(0,w.jsx)(`p`,{className:`pr-busy`,children:o.stalled?a(`profile.tg_poll_error`):a(`profile.tg_waiting`)})]}),o.note?.kind===`failed`&&(0,w.jsx)(M,{message:o.note.error}),o.note?.kind===`unlinked`&&(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_unlinked`)})]}),l===!0&&c&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsxs)(O,{label:a(`profile.notify_test_row`),help:a(`profile.notify_test_help`),middle:!0,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`test`,onClick:o.test,children:a(`profile.tg_test`)}),o.note?.kind===`test_sent`&&(0,w.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_test_sent`)}),o.note?.kind===`test_failed`&&(0,w.jsx)(M,{message:a(`profile.tg_test_failed`,{error:o.note.error})})]}),(0,w.jsx)(O,{label:a(`profile.notify_unlink_row`),help:a(`profile.notify_unlink_help`),middle:!0,children:(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`unlink`,onClick:o.unlink,children:a(`profile.tg_unlink`)})})]})]}),l===!0&&c&&(0,w.jsxs)(D,{title:a(`profile.notify_what_title`),sub:a(`profile.notify_what_sub`),children:[(0,w.jsxs)(O,{label:a(`profile.notify_digest`),help:a(`profile.notify_digest_help`),middle:!0,children:[(0,w.jsx)(j,{label:a(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>i(`notify_digest`,e)}),(0,w.jsx)(M,{message:s(`notify_digest`)})]}),(0,w.jsxs)(O,{label:a(`profile.notify_weekly`),help:a(`profile.notify_weekly_help`),middle:!0,children:[(0,w.jsx)(j,{label:a(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>i(`notify_weekly`,e)}),(0,w.jsx)(M,{message:s(`notify_weekly`)})]}),(0,w.jsxs)(O,{label:a(`profile.notify_alerts`),help:a(`profile.notify_alerts_help`),middle:!0,children:[(0,w.jsx)(j,{label:a(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>i(`notify_alerts`,e)}),(0,w.jsx)(M,{message:s(`notify_alerts`)})]})]})]}),(0,w.jsx)(`aside`,{className:`pr-rail`,children:(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`b`,{className:`pr-sum-t`,children:a(`profile.notify_caption`)}),(0,w.jsx)(E,{text:a(`profile.tg_how_body`)})]})})})]})}function te(){let e=o(async()=>{let[e,t]=await Promise.all([f(`/profile-options`),f(`/profile`)]);return{options:e,profile:t}},[]);return(0,w.jsx)(_,{query:e,skeleton:(0,w.jsx)(g,{rows:8}),children:e=>(0,w.jsx)(ne,{options:e.options,stored:e.profile})})}function ne({options:e,stored:t}){let r=n(),[i,o]=(0,b.useState)(t),[s,c]=(0,b.useState)(null),[l,u]=(0,b.useState)(null);function d(e,n){o(e),c(n),u(null),a(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>o(e)).catch(e=>{o(t),u(x(e,r(`common.offline`)))}).finally(()=>c(null))}let f=e=>t=>r(`profile.iv_${e}_${t}`);return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:r(`profile.iv_how_title`),sub:r(`profile.iv_how_sub`),children:[(0,w.jsx)(O,{label:r(`profile.iv_risk`),help:r(`profile.iv_risk_help`),children:(0,w.jsx)(k,{label:r(`profile.iv_risk`),value:i.risk,options:e.risk,labelOf:f(`risk`),disabled:s===`risk`,onPick:e=>e!==i.risk&&d({...i,risk:e},`risk`)})}),(0,w.jsx)(O,{label:r(`profile.iv_horizon`),help:r(`profile.iv_horizon_help`),children:(0,w.jsx)(k,{label:r(`profile.iv_horizon`),value:i.horizon,options:e.horizon,labelOf:f(`horizon`),disabled:s===`horizon`,onPick:e=>e!==i.horizon&&d({...i,horizon:e},`horizon`)})})]}),(0,w.jsxs)(D,{title:r(`profile.iv_what_title`),sub:r(`profile.iv_what_sub`),children:[(0,w.jsx)(O,{label:r(`profile.iv_focus`),help:r(`profile.iv_focus_help`),children:(0,w.jsx)(N,{values:i.focus,options:e.focus,labelOf:f(`focus`),disabled:s===`focus`,onToggle:(e,t)=>d({...i,focus:t?[...i.focus,e]:i.focus.filter(t=>t!==e)},`focus`)})}),(0,w.jsx)(O,{label:r(`profile.iv_constraints`),help:r(`profile.iv_constraints_help`),children:(0,w.jsx)(N,{values:i.constraints,options:e.constraints,labelOf:f(`constraints`),disabled:s===`constraints`,onToggle:(e,t)=>d({...i,constraints:t?[...i.constraints,e]:i.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,w.jsxs)(D,{title:r(`profile.iv_notes_title`),sub:r(`profile.iv_caption`),children:[(0,w.jsx)(O,{label:r(`profile.iv_notes`),help:r(`profile.iv_notes_help`),children:(0,w.jsx)(re,{value:i.notes,placeholder:r(`profile.iv_notes_ph`),label:r(`profile.iv_notes`),disabled:s===`notes`,onCommit:e=>e!==i.notes&&d({...i,notes:e},`notes`)})}),(0,w.jsx)(M,{message:l})]})]}),(0,w.jsx)(`aside`,{className:`pr-rail`,children:(0,w.jsxs)(D,{children:[(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:r(`profile.iv_sum_title`)}),(0,w.jsx)(F,{label:r(`profile.iv_risk`),value:r(`profile.iv_risk_${i.risk}`)}),(0,w.jsx)(F,{label:r(`profile.iv_horizon`),value:r(`profile.iv_horizon_${i.horizon}`)}),(0,w.jsx)(F,{label:r(`profile.iv_focus`),value:P(i.focus,f(`focus`),r(`profile.iv_sum_none`))}),(0,w.jsx)(F,{label:r(`profile.iv_constraints`),value:P(i.constraints,f(`constraints`),r(`profile.iv_sum_none`))}),(0,w.jsx)(`div`,{className:`pr-sum-rule`}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:r(`profile.iv_privacy`)})]}),i.persona?(0,w.jsxs)(`details`,{className:`pr-persona`,children:[(0,w.jsx)(`summary`,{children:r(`profile.iv_persona_open`)}),(0,w.jsx)(`p`,{className:`pr-sum-note`,children:r(`profile.iv_persona_help`)}),(0,w.jsx)(`code`,{className:`pr-persona-text`,children:i.persona})]}):null]})})]})}function P(e,t,n){return e.length?e.map(t).join(`, `):n}function F({label:e,value:t}){return(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:e}),(0,w.jsx)(`b`,{children:t})]})}function re({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,b.useState)(e);return(0,b.useEffect)(()=>o(e),[e]),(0,w.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}var ie=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],I=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ae={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function L(e){let t=ae[e];return t&&t!==e?`${t} ${e}`:e}var R={en:`English`,es:`Español`},oe={en:`🇬🇧`,es:`🇪🇸`},z=[0,.08,.09];function B(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function se(e,t){if(t)return B(e,t)??B(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return B(e,n.length>1&&n[1]?.length===2?n[1]:``)??B(e,e.default)}function V(e){return`claude mcp add --transport http topstocks ${e}`}function H(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function U({text:e,label:t}){let r=n(),[i,a]=(0,b.useState)(!1);return(0,b.useEffect)(()=>{if(!i)return;let e=setTimeout(()=>a(!1),2e3);return()=>clearTimeout(e)},[i]),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":t,onClick:()=>void navigator.clipboard?.writeText(e).then(()=>a(!0),()=>void 0),children:r(i?`profile.connector_copied`:`profile.connector_copy`)})}function W({connection:t,onGone:r}){let i=n(),o=s(),[c,u]=(0,b.useState)(!1),[d,f]=(0,b.useState)(null),m=()=>{u(!0),f(null),a(`DELETE`,`/connections/${encodeURIComponent(t.id)}`).then(r,t=>{if(u(!1),t instanceof e){window.location.assign(`/auth/logout`);return}if(t instanceof p&&t.status===404){r();return}f(t instanceof p?i(`profile.connector_revoke_failed`):i(`common.offline`))})},h=H(t.used,o);return(0,w.jsxs)(`li`,{className:`pr-conn`,children:[(0,w.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,w.jsxs)(`span`,{className:`pr-conn-name`,children:[t.client_name,!t.verified&&(0,w.jsx)(l,{title:i(`profile.connector_unverified_help`),children:i(`profile.connector_unverified`)}),t.can_write&&(0,w.jsx)(l,{title:i(`profile.connector_can_edit_help`),children:i(`profile.connector_can_edit`)})]}),(0,w.jsx)(`span`,{className:`pr-conn-meta`,children:i(`profile.connector_returns_to`,{host:t.redirect_host})}),(0,w.jsxs)(`span`,{className:`pr-conn-meta`,children:[i(`profile.connector_since`,{date:H(t.created,o)??``}),` · `,h?i(`profile.connector_used`,{date:h}):i(`profile.connector_never_used`)]}),(0,w.jsx)(M,{message:d})]}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:m,children:i(`profile.connector_revoke`)})]})}function G(){let e=o(()=>f(`/connections`),[]),[t,n]=(0,b.useState)(new Set);return e.state===`loaded`?(0,w.jsx)(K,{url:e.data.url,connections:e.data.connections.filter(e=>!t.has(e.id)),onGone:e=>n(t=>new Set(t).add(e))}):null}function K({url:e,connections:t,onGone:r}){let i=n();return!e&&t.length===0?null:(0,w.jsxs)(D,{title:i(`profile.connector_title`),sub:i(`profile.connector_sub`),children:[e&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(O,{label:i(`profile.connector_url`),help:i(`profile.connector_url_help`),children:(0,w.jsxs)(`div`,{className:`pr-copyline`,children:[(0,w.jsx)(`code`,{className:`pr-code`,children:e}),(0,w.jsx)(U,{text:e,label:i(`profile.connector_copy_url`)})]})}),(0,w.jsxs)(O,{label:i(`profile.connector_how`),children:[(0,w.jsx)(E,{text:i(`profile.connector_how_app`)}),(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`profile.connector_how_code`)}),(0,w.jsxs)(`div`,{className:`pr-copyline`,children:[(0,w.jsx)(`code`,{className:`pr-code`,children:V(e)}),(0,w.jsx)(U,{text:V(e),label:i(`profile.connector_copy_command`)})]})]})]}),(0,w.jsx)(O,{label:i(`profile.connector_list`),help:i(`profile.connector_logout_note`),children:t.length===0?(0,w.jsx)(`span`,{className:`pr-muted`,children:i(`profile.connector_none`)}):(0,w.jsx)(`ul`,{className:`pr-conns`,children:t.map(e=>(0,w.jsx)(W,{connection:e,onGone:()=>r(e.id)},e.id))})})]})}function ce(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function le({email:t,onClose:r}){let i=n(),[o,s]=(0,b.useState)(``),[c,l]=(0,b.useState)(!1),[u,d]=(0,b.useState)(null),f=ce(o,t);return(0,b.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!c&&r()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[r,c]),(0,w.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!c&&r()},children:(0,w.jsxs)(`div`,{className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":i(`profile.delete_title`),children:[(0,w.jsx)(`h2`,{className:`pr-modal-t`,children:i(`profile.delete_title`)}),(0,w.jsx)(E,{text:i(`profile.delete_body`)}),(0,w.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`profile.delete_confirm`)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:t,value:o,disabled:c,onChange:e=>s(e.target.value)})]}),(0,w.jsx)(M,{message:u}),(0,w.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:r,children:i(`common.cancel`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!f||c,onClick:()=>{l(!0),d(null),a(`DELETE`,`/account`,{confirm:o.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;window.location.assign(n)},t=>{if(l(!1),t instanceof e){window.location.assign(`/auth/logout`);return}d(t instanceof p&&t.status===422?t.detail:t instanceof p?i(`profile.delete_failed`):i(`common.offline`))})},children:i(`profile.delete_button`)})]})]})})}function ue(){let e=n(),t=c(),[r,i]=(0,b.useState)(!1);return(0,w.jsxs)(O,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>i(!0),children:e(`profile.delete_open`)}),r&&(0,w.jsx)(le,{email:t.email??``,onClose:()=>i(!1)})]})}function de(){let e=n(),{setParams:t}=m(),r=o(()=>f(`/chat/memories`),[]),i=r.state===`loaded`?r.data:null;return(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:e(`profile.memory_title`)}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:e(`profile.memory_caption`)}),i&&(0,w.jsx)(`span`,{className:`pr-sum-note`,children:i.enabled?e(`profile.memory_count`,{n:i.memories.length,max:i.max}):e(`profile.memory_off`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>t({chat:`memory`}),children:e(`profile.memory_open`)})]})})}function fe(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function pe(){let e=n(),{setParams:t}=m(),r=o(()=>f(`/onboarding`),[]),i=r.state===`loaded`?fe(r.data.setup):null;return(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:e(`tour.launch`)}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:e(`tour.launch_caption`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{t({tour:`1`})},children:e(`tour.launch_start`)}),i&&(0,w.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":e(`home.setup_progress`,{done:i[0],total:i[1]}),"aria-valuemin":0,"aria-valuemax":i[1],"aria-valuenow":i[0],children:[(0,w.jsx)(`div`,{className:`pr-prog-track`,children:(0,w.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(i[0]/i[1]*100)}%`}})}),(0,w.jsxs)(`span`,{className:`pr-prog-n`,children:[i[0],`/`,i[1]]})]})]})})}var q=`auto`;function J({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,b.useState)(String(e)),[u,d]=(0,b.useState)(e);return u!==e&&(d(e),l(String(e))),(0,w.jsxs)(`span`,{className:`pr-chips`,children:[(0,w.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,w.jsx)(`span`,{className:`pr-hint`,children:o})]})}function me({prefs:e,saving:t,failure:r,save:i,owner:a}){let s=n(),c=o(()=>f(`/import/last`),[]),l=o(()=>f(`/portfolio/transactions`,{limit:1}),[]),u=[q,...Object.keys(R)],d=e=>e===q?`🌐 ${s(`profile.lang_auto`)}`:`${oe[e]??``} ${R[e]??e}`.trim(),p=I.includes(e.currency)?[...I]:[...I,e.currency],m=ie.filter(e=>!p.includes(e)),h=o(()=>f(`/jurisdictions`),[]),g=h.state===`loaded`?h.data:null,_=[q,...(g?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===q)return`🌐 ${s(`profile.tax_residence_auto`)}`;let t=g?.jurisdictions.find(t=>t.code===e),n=s(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=g?se(g,e.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?s(`profile.tax_year_calendar`):s(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?s(`profile.tax_match_${y.matching}`):``,S=e=>r?.field===e?r.message:null;return(0,w.jsxs)(`div`,{className:`pr-body`,children:[(0,w.jsxs)(`div`,{className:`pr-main`,children:[(0,w.jsxs)(D,{title:s(`profile.ui_section`),sub:s(`profile.ui_section_sub`),children:[(0,w.jsxs)(O,{label:s(`profile.language`),help:s(`profile.language_caption`),children:[(0,w.jsx)(k,{label:s(`profile.language`),value:e.language??q,options:u,labelOf:d,disabled:t===`language`,onPick:t=>{let n=t===q?null:t;n!==e.language&&i(`language`,n)}}),(0,w.jsx)(M,{message:S(`language`)})]}),(0,w.jsxs)(O,{label:s(`profile.display_currency`),help:s(`profile.currency_caption`),children:[(0,w.jsx)(A,{value:e.currency,options:p,labelOf:L,disabled:t===`currency`,onPick:t=>t!==e.currency&&i(`currency`,t)}),m.length>0&&(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:s(`profile.currency_more`,{n:m.length})}),(0,w.jsx)(`div`,{children:(0,w.jsx)(A,{value:e.currency,options:m,labelOf:L,disabled:t===`currency`,onPick:t=>t!==e.currency&&i(`currency`,t)})})]}),m.length>0&&(0,w.jsx)(`span`,{className:`pr-morehint`,children:m.join(` · `)}),(0,w.jsx)(M,{message:S(`currency`)})]})]}),(0,w.jsxs)(D,{title:s(`profile.tax_section`),note:s(`profile.tax_legal_note`),children:[(0,w.jsxs)(O,{label:s(`profile.tax_residence`),help:s(`profile.tax_residence_caption`),children:[(0,w.jsx)(k,{label:s(`profile.tax_residence`),value:e.tax_residence??q,options:_,labelOf:v,disabled:t===`tax_residence`,onPick:t=>{let n=t===q?null:t;n!==e.tax_residence&&i(`tax_residence`,n)}}),(0,w.jsx)(M,{message:S(`tax_residence`)}),y?(0,w.jsxs)(`div`,{className:`pr-rules`,children:[(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_cost`)}),(0,w.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,s(`profile.tax_rule_fx`)]})]}),(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_matching`)}),(0,w.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,w.jsxs)(`div`,{className:`pr-rule`,children:[(0,w.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_year`)}),(0,w.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(n=>{let r=y.code.toLowerCase();return n===`filing_status`?(0,w.jsxs)(O,{label:s(`profile.tax_filing_status`),help:s(`profile.tax_filing_status_caption_${r}`),children:[(0,w.jsx)(k,{label:s(`profile.tax_filing_status`),value:y.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>s(`profile.tax_status_${e}`),disabled:t===`tax_filing_status`,onPick:e=>i(`tax_filing_status`,e)}),(0,w.jsx)(M,{message:S(`tax_filing_status`)})]},n):n===`church_tax_rate`?(0,w.jsxs)(O,{label:s(`profile.tax_church`),help:s(`profile.tax_church_caption`),children:[(0,w.jsx)(k,{label:s(`profile.tax_church`),value:String(z.includes(e.tax_church_rate)?e.tax_church_rate:0),options:z.map(String),labelOf:e=>s(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:t===`tax_church_rate`,onPick:e=>i(`tax_church_rate`,Number(e))}),(0,w.jsx)(M,{message:S(`tax_church_rate`)})]},n):n===`other_income`?(0,w.jsxs)(O,{label:s(`profile.tax_other_income`),help:s(`profile.tax_other_income_caption_${r}`),children:[(0,w.jsx)(J,{label:s(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:t===`tax_other_income`,onCommit:e=>i(`tax_other_income`,e)}),(0,w.jsx)(M,{message:S(`tax_other_income`)})]},n):n===`subnational_rate`?(0,w.jsxs)(O,{label:s(`profile.tax_subnational`),help:s(`profile.tax_subnational_caption`),children:[(0,w.jsx)(J,{label:s(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:t===`tax_subnational_rate`,onCommit:e=>i(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,w.jsx)(M,{message:S(`tax_subnational_rate`)})]},n):(0,w.jsxs)(O,{label:s(`profile.tax_niit`),help:s(`profile.tax_niit_caption`),middle:!0,children:[(0,w.jsx)(j,{label:s(`profile.tax_niit`),checked:e.tax_niit,disabled:t===`tax_niit`,onToggle:e=>i(`tax_niit`,e)}),(0,w.jsx)(M,{message:S(`tax_niit`)})]},n)})]}),(0,w.jsxs)(D,{title:s(`profile.data_section`),children:[(0,w.jsx)(O,{label:s(`profile.export_title`),help:s(`profile.export_help`),children:l.state===`loaded`&&l.data.total>0?(0,w.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:s(`profile.export_button`)}):(0,w.jsx)(`span`,{className:`pr-muted`,children:s(`profile.export_none`)})}),a===!1&&(0,w.jsx)(ue,{})]}),(0,w.jsx)(G,{})]}),(0,w.jsxs)(`aside`,{className:`pr-rail`,children:[(0,w.jsx)(pe,{}),(0,w.jsx)(de,{}),(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-sum`,children:[(0,w.jsx)(`span`,{className:`pr-sum-t`,children:s(`profile.summary_title`)}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:s(`profile.language`)}),(0,w.jsx)(`b`,{children:(d(e.language??q).split(`(`)[0]??``).trim()})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:s(`profile.display_currency`)}),(0,w.jsx)(`b`,{children:e.currency})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:s(`profile.tax_section`)}),(0,w.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(s(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:s(`common.loading`)})]}),(0,w.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,w.jsx)(`span`,{children:s(`profile.summary_last_import`)}),(0,w.jsx)(`b`,{children:c.state===`loaded`?c.data.imported_at?.slice(0,10)??s(`profile.summary_never`):s(`common.loading`)})]}),(0,w.jsx)(`div`,{className:`pr-sum-rule`}),(0,w.jsx)(`span`,{className:`pr-sum-note`,children:s(`profile.summary_note`)})]})})]})]})}var he=new Set([`currency`,`language`]);function ge(t){let n=u(),[r,i]=(0,b.useState)(n.prefs),[o,s]=(0,b.useState)(null),[c,l]=(0,b.useState)(null);return{prefs:r,saving:o,failure:c,save:(0,b.useCallback)((r,o)=>{s(r),l(null),a(`PATCH`,`/prefs`,{[r]:o}).then(e=>{s(null),i(e),he.has(r)&&n.reload()},i=>{if(s(null),i instanceof e){n.reload();return}l({field:r,message:x(i,t)})})},[n,t])}}var _e=`
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
`,ve={analyze:`raw`},Y=2;function ye({listed:e,tags:t,onAdd:r,busy:i,failure:a}){let o=n(),[s,c]=(0,b.useState)(``),[l,u]=(0,b.useState)([]),[d,p]=(0,b.useState)(``),[m,h]=(0,b.useState)(!1),[g,_]=(0,b.useState)(null),[y,x]=(0,b.useState)(null),S=s.trim();(0,b.useEffect)(()=>{if(S.length<Y){_(null);return}let e=!0,t=window.setTimeout(()=>{f(`/search`,{q:S,limit:8}).then(t=>e&&(_(t.matches),x(null)),()=>e&&(_([]),x(o(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[S]);let C=e=>{r({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...l.length?{tags:l}:{}}),c(``),_(null)},T=[...new Set([...t,...l])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,w.jsx)(D,{title:o(`watchlist.add_title`),sub:o(`watchlist.add_sub`),children:(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,w.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,"aria-label":o(`watchlist.add_title`),placeholder:o(`watchlist.add_placeholder`),value:s,onChange:e=>c(e.target.value)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups`)}),T.map(e=>(0,w.jsx)(v,{on:l.includes(e),onClick:()=>u(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.add_groups`),placeholder:o(`watchlist.add_groups_ph`),value:d,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(u(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,w.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups_help`)}),(0,w.jsxs)(`label`,{className:`pr-switch`,children:[(0,w.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,w.jsx)(`span`,{children:o(`watchlist.add_fav`)})]}),(0,w.jsx)(M,{message:a??y}),S.length<Y?(0,w.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_hint`)}):g===null?(0,w.jsx)(`p`,{className:`pr-hint`,children:o(`common.loading`)}):g.length===0?(0,w.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_none`)}):(0,w.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),r=ve[t.kind]??t.kind;return(0,w.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||i,title:o(n?`watchlist.add_listed`:`watchlist.kind_${r}`),onClick:()=>C(t),children:[(0,w.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,w.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,w.jsx)(`span`,{className:`pr-resrow-k`,children:n?o(`watchlist.add_listed`):(t.exchange??``)||o(`watchlist.kind_${r}`)})]},t.ticker)})})]})})}var X=e=>e?String(e):``;function be(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var xe=[`tags`,`favorites`,`flat`];function Z(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function Se(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Ce({entry:e,tags:t,busy:r,onEdit:i,onRemove:a}){let o=n(),[s,c]=(0,b.useState)(e.name),[l,u]=(0,b.useState)(e.name),[d,f]=(0,b.useState)(``),[p,m]=(0,b.useState)(X(e.shares)),[g,_]=(0,b.useState)(X(e.cost)),[y,x]=(0,b.useState)([e.shares,e.cost]);l!==e.name&&(u(e.name),c(e.name)),(y[0]!==e.shares||y[1]!==e.cost)&&(x([e.shares,e.cost]),m(X(e.shares)),_(X(e.cost)));let S=(t,n)=>{let r=be(n,e[t]);if(r===void 0){t===`shares`?m(X(e.shares)):_(X(e.cost));return}i(e.ticker,{[t]:r})},C=t=>i(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),T=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,w.jsxs)(`div`,{className:`pr-wrow`,children:[(0,w.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":o(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:r,onClick:()=>i(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,w.jsx)(h,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":o(`watchlist.col_name`),value:s,disabled:r,onChange:e=>c(e.target.value),onBlur:()=>s!==e.name&&i(e.ticker,{name:s}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_shares`),placeholder:o(`watchlist.col_shares`),inputMode:`decimal`,value:p,disabled:r,onChange:e=>m(e.target.value),onBlur:()=>S(`shares`,p),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_cost`),placeholder:o(`watchlist.col_cost`),title:o(`watchlist.col_cost_help`),inputMode:`decimal`,value:g,disabled:r,onChange:e=>_(e.target.value),onBlur:()=>S(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:r,onClick:()=>a(e.ticker),children:o(`watchlist.act_remove`)}),(0,w.jsxs)(`details`,{className:`pr-wtags`,children:[(0,w.jsxs)(`summary`,{children:[o(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,w.jsxs)(`div`,{children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.col_tags_help`)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[T.map(t=>{let n=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,w.jsx)(v,{on:n,disabled:r,onClick:()=>C(t),children:t},t)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.col_tags`),placeholder:o(`watchlist.add_groups_ph`),value:d,disabled:r,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(f(``),C(t))}})]})]})]})]})}function we({section:e,busy:t,onRename:r,onDissolve:i}){let a=n(),[o,s]=(0,b.useState)(e.tag??``);return(0,w.jsxs)(`div`,{className:`pr-ghead`,children:[(0,w.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,w.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:a(`watchlist.group_manage`)}),(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.group_manage_help`)}),(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.group_rename`),value:o,disabled:t,onChange:e=>s(e.target.value)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!o.trim()||o.trim()===e.tag,onClick:()=>r(e.tag,o.trim()),children:a(`watchlist.group_rename_apply`)}),(0,w.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:a(`watchlist.group_delete_help`),onClick:()=>i(e.tag),children:a(`watchlist.group_delete`)})]})]})]})}function Te({entries:t,reload:r}){let i=n(),[o,s]=(0,b.useState)(!1),[c,l]=(0,b.useState)(null),[u,d]=(0,b.useState)(``),[f,p]=(0,b.useState)([]),[m,h]=(0,b.useState)(`tags`),g=(t,n=`list`)=>{s(!0),l(null),t.then(()=>{s(!1),r()},t=>{if(s(!1),t instanceof e){r();return}l({where:n,message:x(t,i(`common.offline`))})})},_=[...new Set(t.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),y=new Set(t.map(e=>e.ticker.toUpperCase())),S=new Set(f.map(e=>e.toLowerCase())),C=t.filter(e=>Se(e,u)&&(!S.size||e.tags.some(e=>S.has(e.toLowerCase()))));return(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(ye,{listed:y,tags:_,busy:o,failure:c?.where===`add`?c.message:null,onAdd:e=>g(a(`POST`,`/watchlist`,e),`add`)}),t.length===0?(0,w.jsx)(D,{title:i(`profile.empty_watchlist_title`),children:(0,w.jsx)(`div`,{className:`pr-cardbody`,children:(0,w.jsx)(`p`,{className:`pr-hint`,children:i(`profile.empty_watchlist_body`)})})}):(0,w.jsx)(D,{title:i(`watchlist.list_title`),sub:i(`watchlist.list_sub`),children:(0,w.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,"aria-label":i(`watchlist.filter`),placeholder:i(`watchlist.filter_ph`),value:u,onChange:e=>d(e.target.value)}),xe.map(e=>(0,w.jsx)(v,{on:e===m,onClick:()=>h(e),children:i(`watchlist.group_${e}`)},e))]}),_.length>0&&(0,w.jsxs)(`div`,{className:`pr-chips`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.tag_filter`)}),_.map(e=>(0,w.jsx)(v,{on:S.has(e.toLowerCase()),onClick:()=>p(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,w.jsx)(M,{message:c?.where===`list`?c.message:null}),C.length===0?(0,w.jsx)(`p`,{className:`pr-hint`,children:i(`watchlist.no_match`)}):Z(C,m,i(`watchlist.g_untagged`),{all:i(`watchlist.g_all`),favorites:i(`watchlist.g_favorites`),rest:i(`watchlist.g_rest`)}).map(e=>(0,w.jsxs)(`div`,{children:[(0,w.jsx)(we,{section:e,busy:o,onRename:(e,t)=>g(a(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>g(a(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,w.jsx)(Ce,{entry:t,tags:_,busy:o,onEdit:(e,t)=>g(a(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>g(a(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,w.jsxs)(`div`,{className:`pr-foot`,children:[(0,w.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.count`,{n:t.length})}),(0,w.jsxs)(`details`,{className:`pr-more`,children:[(0,w.jsx)(`summary`,{children:i(`watchlist.how_open`)}),(0,w.jsx)(`div`,{children:(0,w.jsx)(E,{text:i(`watchlist.how`)})})]})]})]})})]})}function Ee({onAdded:e}){let t=n(),[r,i]=(0,b.useState)(0),s=o(()=>f(`/watchlist/suggestions`),[r]),[c,l]=(0,b.useState)(!1),[u,d]=(0,b.useState)(null);if(s.state!==`loaded`||s.data.suggestions.length===0)return null;let p=s.data.suggestions;function m(){l(!0),d(null),p.reduce((e,t)=>e.then(()=>a(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{i(e=>e+1),e()}).catch(e=>d(x(e,t(`common.offline`)))).finally(()=>l(!1))}return(0,w.jsxs)(D,{title:t(`profile.focus_suggest_title`),children:[(0,w.jsx)(E,{text:t(`profile.focus_suggest_help`)}),(0,w.jsx)(`ul`,{className:`pr-examples`,children:p.map(e=>(0,w.jsxs)(`li`,{children:[(0,w.jsx)(h,{ticker:e.ticker,className:`pr-wsym`}),(0,w.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,w.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:c,onClick:m,children:t(`profile.focus_suggest_add`,{n:p.length})}),(0,w.jsx)(M,{message:u})]})}function De({query:e}){return(0,w.jsx)(`div`,{className:`pr-main`,children:(0,w.jsx)(_,{query:e,children:(e,t)=>(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(Te,{entries:e.entries,reload:t}),(0,w.jsx)(Ee,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Oe(){return y()?(0,w.jsx)(d,{text:`common.sign_in`}):(0,w.jsx)(ke,{})}function ke(){let e=n(),t=c(),{params:r,setParams:i}=m(),a=ge(e(`common.offline`)),s=o(()=>f(`/me`),[]),l=s.state===`loaded`?s.data:null,u=o(()=>f(`/watchlist`),[]),d=u.state===`loaded`?u.data.entries.length:0,[p,h]=(0,b.useState)(!1),g=l?.name?.trim()||``,_=r.get(`tab`)??``,v=Q.some(e=>e.id===_)?_:`prefs`,y=t.email??``;return(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:_e}),(0,w.jsxs)(`header`,{className:`pr-head`,children:[(0,w.jsx)(`h1`,{className:`pr-title`,children:e(`nav.profile`)}),(0,w.jsx)(`span`,{className:`pr-savehint`,children:e(`profile.saves_instantly`)})]}),(0,w.jsx)(D,{children:(0,w.jsxs)(`div`,{className:`pr-ident`,children:[(0,w.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:l?.picture&&!p?(0,w.jsx)(`img`,{src:l.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>h(!0)}):$(y,g)}),(0,w.jsxs)(`div`,{className:`pr-ident-t`,children:[g&&g!==y&&(0,w.jsx)(`span`,{className:`pr-ident-n`,children:g}),(0,w.jsx)(`span`,{className:`pr-ident-e`,children:y})]}),(0,w.jsx)(`div`,{className:`pr-ident-r`,children:(0,w.jsx)(`span`,{className:`pr-ident-note`,children:e(`profile.account_scope`)})}),(0,w.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,children:e(`common.log_out`)})]})}),(0,w.jsx)(`div`,{className:`pr-tabs`,role:`tablist`,"aria-label":e(`nav.profile`),children:Q.map(t=>(0,w.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":t.id===v,className:t.id===v?`pr-tab pr-tab-on`:`pr-tab`,onClick:()=>i({tab:t.id}),children:[e(t.label),t.id===`watch`&&d>0&&(0,w.jsx)(`span`,{className:`pr-tab-n`,children:d})]},t.id))}),v===`prefs`&&(0,w.jsx)(me,{...a,owner:s.state===`loaded`?!!l?.owner:null}),v===`iv`&&(0,w.jsx)(te,{}),v===`watch`&&(0,w.jsx)(De,{query:u}),v===`notify`&&(0,w.jsx)(ee,{...a})]})}export{Oe as default,$ as initials};