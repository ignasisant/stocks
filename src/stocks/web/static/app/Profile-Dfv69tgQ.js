import{Ct as e,Dt as t,Et as n,St as r,Tt as i,at as a,ft as o,g as s,ht as c,jt as l,kt as u,mt as d,o as f,r as p,t as m,u as h,wt as g,xt as _}from"./app-Dt9VqxgG.js";var v=l(u(),1);function y(e,t){return e instanceof g?e.detail:t}var b=3e3;function x(e){let{reload:r}=c(),[a,o]=(0,v.useState)(null),[s,l]=(0,v.useState)(null),[u,d]=(0,v.useState)(!1),[f,p]=(0,v.useState)(!1),[m,h]=(0,v.useState)(null),[g,_]=(0,v.useState)(null),x=(0,v.useCallback)(t=>t instanceof i?(r(),null):{kind:`failed`,error:y(t,e)},[r,e]);(0,v.useEffect)(()=>{let e=!0;return n(`/notify/telegram`).then(t=>e&&o(t),t=>{e&&_(x(t))}),()=>{e=!1}},[x]);let[S,C]=(0,v.useState)(()=>typeof document>`u`||!document.hidden);return(0,v.useEffect)(()=>{let e=()=>C(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,v.useEffect)(()=>{if(!s||!S)return;if(Date.now()>=s.deadline){l(null),d(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=s.deadline){l(null),d(!0);return}n(`/notify/telegram`).then(t=>{e&&(p(!1),o(t),t.linked&&l(null))},()=>e&&p(!0))},b);return()=>{e=!1,window.clearInterval(t)}},[s,S]),{state:a,pending:s,expired:u,stalled:f,busy:m,note:g,connect:(0,v.useCallback)(()=>{h(`connect`),_(null),d(!1),t(`POST`,`/notify/telegram`).then(e=>{h(null),l({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{h(null),_(x(e))})},[x]),test:(0,v.useCallback)(()=>{h(`test`),_(null),t(`POST`,`/notify/telegram/test`).then(e=>{h(null),o(e),_({kind:`test_sent`})},t=>{if(h(null),t instanceof i){r();return}_({kind:`test_failed`,error:y(t,e)})})},[r,e]),unlink:(0,v.useCallback)(()=>{h(`unlink`),_(null),t(`DELETE`,`/notify/telegram`).then(e=>{h(null),o(e),l(null),d(!1),_({kind:`unlinked`})},e=>{h(null),_(x(e))})},[x])}}var S=r();function C({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,S.jsx)(S.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,S.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,S.jsx)(`code`,{children:e.slice(1,-1)},t):(0,S.jsx)(v.Fragment,{children:e},t))})}function w({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,S.jsx)(`ul`,{children:r.map((e,t)=>(0,S.jsx)(`li`,{children:(0,S.jsx)(C,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,S.jsx)(`p`,{children:(0,S.jsx)(C,{text:a})},t))}),i(-1),(0,S.jsx)(`div`,{className:t??`pr-prose`,children:n})}function T({title:e,sub:t,note:n,children:r}){return(0,S.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,S.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,S.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,S.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,S.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function E({label:e,help:t,middle:n,children:r}){return(0,S.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,S.jsxs)(`div`,{className:`pr-row-l`,children:[(0,S.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,S.jsx)(`span`,{className:`pr-row-help`,children:(0,S.jsx)(C,{text:t})})]}),(0,S.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function D({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,S.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,S.jsx)(`option`,{value:e,children:n(e)},e))})}function O({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,S.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,S.jsx)(h,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function k({checked:e,onToggle:t,label:n,disabled:r}){return(0,S.jsx)(`label`,{className:`pr-switch`,children:(0,S.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function A({message:e}){return e?(0,S.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function j({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,S.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,S.jsx)(h,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ee({prefs:e,saving:t,failure:n,save:r}){let i=_(),a=x(i(`common.offline`)),o=e=>n?.field===e?n.message:null,s=a.state?a.state.linked:e.telegram_linked,c=a.state?.configured??(e.telegram_linked?!0:null);return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[c===null&&!a.note&&(0,S.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),c===!1&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),c===!0&&s&&(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,S.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:a.state?.username?`@${a.state.username}`:``}).trim()})]}),c===!0&&!s&&!a.pending&&(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:a.busy===`connect`,onClick:a.connect,children:i(`profile.tg_connect`)}),a.expired&&(0,S.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),c===!0&&!s&&a.pending&&(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(`a`,{className:`pr-linkbtn`,href:a.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,S.jsx)(`p`,{className:`pr-hint`,children:(0,S.jsx)(C,{text:i(`profile.tg_manual`,{bot:a.pending.bot,code:a.pending.code})})}),(0,S.jsx)(`p`,{className:`pr-busy`,children:a.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),a.note?.kind===`failed`&&(0,S.jsx)(A,{message:a.note.error}),a.note?.kind===`unlinked`&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),c===!0&&s&&(0,S.jsxs)(S.Fragment,{children:[(0,S.jsxs)(E,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`test`,onClick:a.test,children:i(`profile.tg_test`)}),a.note?.kind===`test_sent`&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),a.note?.kind===`test_failed`&&(0,S.jsx)(A,{message:i(`profile.tg_test_failed`,{error:a.note.error})})]}),(0,S.jsx)(E,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`unlink`,onClick:a.unlink,children:i(`profile.tg_unlink`)})})]})]}),c===!0&&s&&(0,S.jsxs)(T,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,S.jsxs)(E,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,S.jsx)(A,{message:o(`notify_digest`)})]}),(0,S.jsxs)(E,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,S.jsx)(A,{message:o(`notify_weekly`)})]}),(0,S.jsxs)(E,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,S.jsx)(A,{message:o(`notify_alerts`)})]})]})]}),(0,S.jsx)(`aside`,{className:`pr-rail`,children:(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,S.jsx)(w,{text:i(`profile.tg_how_body`)})]})})})]})}function te(){let t=e(async()=>{let[e,t]=await Promise.all([n(`/profile-options`),n(`/profile`)]);return{options:e,profile:t}},[]);return(0,S.jsx)(m,{query:t,skeleton:(0,S.jsx)(p,{rows:8}),children:e=>(0,S.jsx)(M,{options:e.options,stored:e.profile})})}function M({options:e,stored:n}){let r=_(),[i,a]=(0,v.useState)(n),[o,s]=(0,v.useState)(null),[c,l]=(0,v.useState)(null);function u(e,i){a(e),s(i),l(null),t(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>a(e)).catch(e=>{a(n),l(y(e,r(`common.offline`)))}).finally(()=>s(null))}let d=e=>t=>r(`profile.iv_${e}_${t}`);return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:r(`profile.iv_how_title`),sub:r(`profile.iv_how_sub`),children:[(0,S.jsx)(E,{label:r(`profile.iv_risk`),help:r(`profile.iv_risk_help`),children:(0,S.jsx)(D,{label:r(`profile.iv_risk`),value:i.risk,options:e.risk,labelOf:d(`risk`),disabled:o===`risk`,onPick:e=>e!==i.risk&&u({...i,risk:e},`risk`)})}),(0,S.jsx)(E,{label:r(`profile.iv_horizon`),help:r(`profile.iv_horizon_help`),children:(0,S.jsx)(D,{label:r(`profile.iv_horizon`),value:i.horizon,options:e.horizon,labelOf:d(`horizon`),disabled:o===`horizon`,onPick:e=>e!==i.horizon&&u({...i,horizon:e},`horizon`)})})]}),(0,S.jsxs)(T,{title:r(`profile.iv_what_title`),sub:r(`profile.iv_what_sub`),children:[(0,S.jsx)(E,{label:r(`profile.iv_focus`),help:r(`profile.iv_focus_help`),children:(0,S.jsx)(j,{values:i.focus,options:e.focus,labelOf:d(`focus`),disabled:o===`focus`,onToggle:(e,t)=>u({...i,focus:t?[...i.focus,e]:i.focus.filter(t=>t!==e)},`focus`)})}),(0,S.jsx)(E,{label:r(`profile.iv_constraints`),help:r(`profile.iv_constraints_help`),children:(0,S.jsx)(j,{values:i.constraints,options:e.constraints,labelOf:d(`constraints`),disabled:o===`constraints`,onToggle:(e,t)=>u({...i,constraints:t?[...i.constraints,e]:i.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,S.jsxs)(T,{title:r(`profile.iv_notes_title`),sub:r(`profile.iv_caption`),children:[(0,S.jsx)(E,{label:r(`profile.iv_notes`),help:r(`profile.iv_notes_help`),children:(0,S.jsx)(ne,{value:i.notes,placeholder:r(`profile.iv_notes_ph`),label:r(`profile.iv_notes`),disabled:o===`notes`,onCommit:e=>e!==i.notes&&u({...i,notes:e},`notes`)})}),(0,S.jsx)(A,{message:c})]})]}),(0,S.jsx)(`aside`,{className:`pr-rail`,children:(0,S.jsxs)(T,{children:[(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:r(`profile.iv_sum_title`)}),(0,S.jsx)(P,{label:r(`profile.iv_risk`),value:r(`profile.iv_risk_${i.risk}`)}),(0,S.jsx)(P,{label:r(`profile.iv_horizon`),value:r(`profile.iv_horizon_${i.horizon}`)}),(0,S.jsx)(P,{label:r(`profile.iv_focus`),value:N(i.focus,d(`focus`),r(`profile.iv_sum_none`))}),(0,S.jsx)(P,{label:r(`profile.iv_constraints`),value:N(i.constraints,d(`constraints`),r(`profile.iv_sum_none`))}),(0,S.jsx)(`div`,{className:`pr-sum-rule`}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:r(`profile.iv_privacy`)})]}),i.persona?(0,S.jsxs)(`details`,{className:`pr-persona`,children:[(0,S.jsx)(`summary`,{children:r(`profile.iv_persona_open`)}),(0,S.jsx)(`p`,{className:`pr-sum-note`,children:r(`profile.iv_persona_help`)}),(0,S.jsx)(`code`,{className:`pr-persona-text`,children:i.persona})]}):null]})})]})}function N(e,t,n){return e.length?e.map(t).join(`, `):n}function P({label:e,value:t}){return(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:e}),(0,S.jsx)(`b`,{children:t})]})}function ne({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,v.useState)(e);return(0,v.useEffect)(()=>o(e),[e]),(0,S.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}var re=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],F=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ie={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function I(e){let t=ie[e];return t&&t!==e?`${t} ${e}`:e}var L={en:`English`,es:`Español`},ae={en:`🇬🇧`,es:`🇪🇸`},R=[0,.08,.09];function z(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function B(e,t){if(t)return z(e,t)??z(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return z(e,n.length>1&&n[1]?.length===2?n[1]:``)??z(e,e.default)}function V(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function H({email:e,onClose:n}){let r=_(),[a,o]=(0,v.useState)(``),[s,c]=(0,v.useState)(!1),[l,u]=(0,v.useState)(null),d=V(a,e);return(0,v.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!s&&n()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[n,s]),(0,S.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!s&&n()},children:(0,S.jsxs)(`div`,{className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":r(`profile.delete_title`),children:[(0,S.jsx)(`h2`,{className:`pr-modal-t`,children:r(`profile.delete_title`)}),(0,S.jsx)(w,{text:r(`profile.delete_body`)}),(0,S.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:r(`profile.delete_confirm`)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:a,disabled:s,onChange:e=>o(e.target.value)})]}),(0,S.jsx)(A,{message:l}),(0,S.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:s,onClick:n,children:r(`common.cancel`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!d||s,onClick:()=>{c(!0),u(null),t(`DELETE`,`/account`,{confirm:a.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;window.location.assign(n)},e=>{if(c(!1),e instanceof i){window.location.assign(`/auth/logout`);return}u(e instanceof g&&e.status===422?e.detail:e instanceof g?r(`profile.delete_failed`):r(`common.offline`))})},children:r(`profile.delete_button`)})]})]})})}function U(){let e=_(),t=o(),[n,r]=(0,v.useState)(!1);return(0,S.jsxs)(E,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>r(!0),children:e(`profile.delete_open`)}),n&&(0,S.jsx)(H,{email:t.email??``,onClose:()=>r(!1)})]})}function W(){let t=_(),{setParams:r}=a(),i=e(()=>n(`/chat/memories`),[]),o=i.state===`loaded`?i.data:null;return(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:t(`profile.memory_title`)}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:t(`profile.memory_caption`)}),o&&(0,S.jsx)(`span`,{className:`pr-sum-note`,children:o.enabled?t(`profile.memory_count`,{n:o.memories.length,max:o.max}):t(`profile.memory_off`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>r({chat:`memory`}),children:t(`profile.memory_open`)})]})})}function G(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function K(){let t=_(),{setParams:r}=a(),i=e(()=>n(`/onboarding`),[]),o=i.state===`loaded`?G(i.data.setup):null;return(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:t(`tour.launch`)}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:t(`tour.launch_caption`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{r({tour:`1`})},children:t(`tour.launch_start`)}),o&&(0,S.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":t(`home.setup_progress`,{done:o[0],total:o[1]}),"aria-valuemin":0,"aria-valuemax":o[1],"aria-valuenow":o[0],children:[(0,S.jsx)(`div`,{className:`pr-prog-track`,children:(0,S.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(o[0]/o[1]*100)}%`}})}),(0,S.jsxs)(`span`,{className:`pr-prog-n`,children:[o[0],`/`,o[1]]})]})]})})}var q=`auto`;function J({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,v.useState)(String(e)),[u,d]=(0,v.useState)(e);return u!==e&&(d(e),l(String(e))),(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,S.jsx)(`span`,{className:`pr-hint`,children:o})]})}function oe({prefs:t,saving:r,failure:i,save:a,owner:o}){let s=_(),c=e(()=>n(`/import/last`),[]),l=e(()=>n(`/portfolio/transactions`,{limit:1}),[]),u=[q,...Object.keys(L)],d=e=>e===q?`🌐 ${s(`profile.lang_auto`)}`:`${ae[e]??``} ${L[e]??e}`.trim(),f=F.includes(t.currency)?[...F]:[...F,t.currency],p=re.filter(e=>!f.includes(e)),m=e(()=>n(`/jurisdictions`),[]),h=m.state===`loaded`?m.data:null,g=[q,...(h?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===q)return`🌐 ${s(`profile.tax_residence_auto`)}`;let t=h?.jurisdictions.find(t=>t.code===e),n=s(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=h?B(h,t.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?s(`profile.tax_year_calendar`):s(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?s(`profile.tax_match_${y.matching}`):``,C=e=>i?.field===e?i.message:null;return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:s(`profile.ui_section`),sub:s(`profile.ui_section_sub`),children:[(0,S.jsxs)(E,{label:s(`profile.language`),help:s(`profile.language_caption`),children:[(0,S.jsx)(D,{label:s(`profile.language`),value:t.language??q,options:u,labelOf:d,disabled:r===`language`,onPick:e=>{let n=e===q?null:e;n!==t.language&&a(`language`,n)}}),(0,S.jsx)(A,{message:C(`language`)})]}),(0,S.jsxs)(E,{label:s(`profile.display_currency`),help:s(`profile.currency_caption`),children:[(0,S.jsx)(O,{value:t.currency,options:f,labelOf:I,disabled:r===`currency`,onPick:e=>e!==t.currency&&a(`currency`,e)}),p.length>0&&(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:s(`profile.currency_more`,{n:p.length})}),(0,S.jsx)(`div`,{children:(0,S.jsx)(O,{value:t.currency,options:p,labelOf:I,disabled:r===`currency`,onPick:e=>e!==t.currency&&a(`currency`,e)})})]}),p.length>0&&(0,S.jsx)(`span`,{className:`pr-morehint`,children:p.join(` · `)}),(0,S.jsx)(A,{message:C(`currency`)})]})]}),(0,S.jsxs)(T,{title:s(`profile.tax_section`),note:s(`profile.tax_legal_note`),children:[(0,S.jsxs)(E,{label:s(`profile.tax_residence`),help:s(`profile.tax_residence_caption`),children:[(0,S.jsx)(D,{label:s(`profile.tax_residence`),value:t.tax_residence??q,options:g,labelOf:v,disabled:r===`tax_residence`,onPick:e=>{let n=e===q?null:e;n!==t.tax_residence&&a(`tax_residence`,n)}}),(0,S.jsx)(A,{message:C(`tax_residence`)}),y?(0,S.jsxs)(`div`,{className:`pr-rules`,children:[(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_cost`)}),(0,S.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,s(`profile.tax_rule_fx`)]})]}),(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_matching`)}),(0,S.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_year`)}),(0,S.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(e=>{let n=y.code.toLowerCase();return e===`filing_status`?(0,S.jsxs)(E,{label:s(`profile.tax_filing_status`),help:s(`profile.tax_filing_status_caption_${n}`),children:[(0,S.jsx)(D,{label:s(`profile.tax_filing_status`),value:y.filing_statuses.includes(t.tax_filing_status)?t.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>s(`profile.tax_status_${e}`),disabled:r===`tax_filing_status`,onPick:e=>a(`tax_filing_status`,e)}),(0,S.jsx)(A,{message:C(`tax_filing_status`)})]},e):e===`church_tax_rate`?(0,S.jsxs)(E,{label:s(`profile.tax_church`),help:s(`profile.tax_church_caption`),children:[(0,S.jsx)(D,{label:s(`profile.tax_church`),value:String(R.includes(t.tax_church_rate)?t.tax_church_rate:0),options:R.map(String),labelOf:e=>s(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:r===`tax_church_rate`,onPick:e=>a(`tax_church_rate`,Number(e))}),(0,S.jsx)(A,{message:C(`tax_church_rate`)})]},e):e===`other_income`?(0,S.jsxs)(E,{label:s(`profile.tax_other_income`),help:s(`profile.tax_other_income_caption_${n}`),children:[(0,S.jsx)(J,{label:s(`profile.tax_other_income`),value:t.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:r===`tax_other_income`,onCommit:e=>a(`tax_other_income`,e)}),(0,S.jsx)(A,{message:C(`tax_other_income`)})]},e):e===`subnational_rate`?(0,S.jsxs)(E,{label:s(`profile.tax_subnational`),help:s(`profile.tax_subnational_caption`),children:[(0,S.jsx)(J,{label:s(`profile.tax_subnational`),value:Math.round(t.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:r===`tax_subnational_rate`,onCommit:e=>a(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,S.jsx)(A,{message:C(`tax_subnational_rate`)})]},e):(0,S.jsxs)(E,{label:s(`profile.tax_niit`),help:s(`profile.tax_niit_caption`),middle:!0,children:[(0,S.jsx)(k,{label:s(`profile.tax_niit`),checked:t.tax_niit,disabled:r===`tax_niit`,onToggle:e=>a(`tax_niit`,e)}),(0,S.jsx)(A,{message:C(`tax_niit`)})]},e)})]}),(0,S.jsxs)(T,{title:s(`profile.data_section`),children:[(0,S.jsx)(E,{label:s(`profile.export_title`),help:s(`profile.export_help`),children:l.state===`loaded`&&l.data.total>0?(0,S.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:s(`profile.export_button`)}):(0,S.jsx)(`span`,{className:`pr-muted`,children:s(`profile.export_none`)})}),o===!1&&(0,S.jsx)(U,{})]})]}),(0,S.jsxs)(`aside`,{className:`pr-rail`,children:[(0,S.jsx)(K,{}),(0,S.jsx)(W,{}),(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:s(`profile.summary_title`)}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:s(`profile.language`)}),(0,S.jsx)(`b`,{children:(d(t.language??q).split(`(`)[0]??``).trim()})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:s(`profile.display_currency`)}),(0,S.jsx)(`b`,{children:t.currency})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:s(`profile.tax_section`)}),(0,S.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(s(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:s(`common.loading`)})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:s(`profile.summary_last_import`)}),(0,S.jsx)(`b`,{children:c.state===`loaded`?c.data.imported_at?.slice(0,10)??s(`profile.summary_never`):s(`common.loading`)})]}),(0,S.jsx)(`div`,{className:`pr-sum-rule`}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:s(`profile.summary_note`)})]})})]})]})}var se=new Set([`currency`,`language`]);function ce(e){let n=c(),[r,a]=(0,v.useState)(n.prefs),[o,s]=(0,v.useState)(null),[l,u]=(0,v.useState)(null);return{prefs:r,saving:o,failure:l,save:(0,v.useCallback)((r,o)=>{s(r),u(null),t(`PATCH`,`/prefs`,{[r]:o}).then(e=>{s(null),a(e),se.has(r)&&n.reload()},t=>{if(s(null),t instanceof i){n.reload();return}u({field:r,message:y(t,e)})})},[n,e])}}var le=`
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
.pr-tab:hover { color: var(--ag-text-primary); }
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
.pr-download:hover { border-color: var(--ag-border-focus); }
.pr-muted { color: var(--ag-text-muted); font-size: var(--ag-fs-sm); }
.pr-signout {
  margin-left: auto; align-self: center; white-space: nowrap;
  font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; text-decoration: none;
}
.pr-signout:hover { border-color: var(--ag-border-focus); color: var(--ag-text-primary); }
.pr-more { margin-top: 4px; }
.pr-more > summary {
  cursor: pointer; list-style: none; display: inline-block;
  border: 1px dashed var(--ag-border-focus); border-radius: var(--ag-radius-pill);
  padding: 5px 12px; font-size: var(--ag-fs-sm); color: var(--ag-text-secondary);
}
.pr-more > summary::-webkit-details-marker { display: none; }
.pr-more > div { margin-top: 10px; }
.pr-btn {
  appearance: none; font: inherit; font-size: var(--ag-fs-sm); cursor: pointer;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-xs);
  background: var(--ag-surface-sunken); color: var(--ag-text-primary);
  padding: 6px 12px;
}
.pr-btn:hover:enabled { border-color: var(--ag-border-focus); }
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
.pr-linkbtn:hover { border-color: var(--ag-border-focus); }
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
.pr-persona > summary:hover { color: var(--ag-text-primary); }
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

/* --------------------------------------------------------- the watchlist */
.pr-ticks { display: flex; flex-wrap: wrap; gap: 8px; }
.pr-tick {
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-pill);
  background: var(--ag-surface-page); padding: 3px 11px;
  font-family: "Martian Mono", ui-monospace, monospace; font-size: var(--ag-fs-xs);
  color: var(--ag-text-primary); text-decoration: none;
}
.pr-tick:hover { border-color: var(--ag-border-focus); }
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
.pr-wsym:hover { color: var(--ag-purple-400); }
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

/* Then the rows stack — control under its label, as the Streamlit page lays
   them — with a narrower gutter, down to a phone or a page beside the
   drawer. */
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
`,ue={analyze:`raw`},Y=2;function de({listed:e,tags:t,onAdd:r,busy:i,failure:a}){let o=_(),[s,c]=(0,v.useState)(``),[l,u]=(0,v.useState)([]),[d,f]=(0,v.useState)(``),[p,m]=(0,v.useState)(!1),[g,y]=(0,v.useState)(null),[b,x]=(0,v.useState)(null),C=s.trim();(0,v.useEffect)(()=>{if(C.length<Y){y(null);return}let e=!0,t=window.setTimeout(()=>{n(`/search`,{q:C,limit:8}).then(t=>e&&(y(t.matches),x(null)),()=>e&&(y([]),x(o(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[C]);let w=e=>{r({ticker:e.ticker,name:e.name,...p?{favorite:!0}:{},...l.length?{tags:l}:{}}),c(``),y(null)},E=[...new Set([...t,...l])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,S.jsx)(T,{title:o(`watchlist.add_title`),sub:o(`watchlist.add_sub`),children:(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,S.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,"aria-label":o(`watchlist.add_title`),placeholder:o(`watchlist.add_placeholder`),value:s,onChange:e=>c(e.target.value)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups`)}),E.map(e=>(0,S.jsx)(h,{on:l.includes(e),onClick:()=>u(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.add_groups`),placeholder:o(`watchlist.add_groups_ph`),value:d,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(u(e=>e.includes(t)?e:[...e,t]),f(``))}})]}),(0,S.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups_help`)}),(0,S.jsxs)(`label`,{className:`pr-switch`,children:[(0,S.jsx)(`input`,{type:`checkbox`,checked:p,onChange:e=>m(e.target.checked)}),(0,S.jsx)(`span`,{children:o(`watchlist.add_fav`)})]}),(0,S.jsx)(A,{message:a??b}),C.length<Y?(0,S.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_hint`)}):g===null?(0,S.jsx)(`p`,{className:`pr-hint`,children:o(`common.loading`)}):g.length===0?(0,S.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_none`)}):(0,S.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),r=ue[t.kind]??t.kind;return(0,S.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||i,title:o(n?`watchlist.add_listed`:`watchlist.kind_${r}`),onClick:()=>w(t),children:[(0,S.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,S.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,S.jsx)(`span`,{className:`pr-resrow-k`,children:n?o(`watchlist.add_listed`):(t.exchange??``)||o(`watchlist.kind_${r}`)})]},t.ticker)})})]})})}var X=e=>e?String(e):``;function fe(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var pe=[`tags`,`favorites`,`flat`];function me(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function he(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Z({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let a=_(),[o,s]=(0,v.useState)(e.name),[c,l]=(0,v.useState)(e.name),[u,d]=(0,v.useState)(``),[p,m]=(0,v.useState)(X(e.shares)),[g,y]=(0,v.useState)(X(e.cost)),[b,x]=(0,v.useState)([e.shares,e.cost]);c!==e.name&&(l(e.name),s(e.name)),(b[0]!==e.shares||b[1]!==e.cost)&&(x([e.shares,e.cost]),m(X(e.shares)),y(X(e.cost)));let C=(t,n)=>{let i=fe(n,e[t]);if(i===void 0){t===`shares`?m(X(e.shares)):y(X(e.cost));return}r(e.ticker,{[t]:i})},w=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),T=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,S.jsxs)(`div`,{className:`pr-wrow`,children:[(0,S.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":a(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,S.jsx)(f,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":a(`watchlist.col_name`),value:o,disabled:n,onChange:e=>s(e.target.value),onBlur:()=>o!==e.name&&r(e.ticker,{name:o}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_shares`),placeholder:a(`watchlist.col_shares`),inputMode:`decimal`,value:p,disabled:n,onChange:e=>m(e.target.value),onBlur:()=>C(`shares`,p),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_cost`),placeholder:a(`watchlist.col_cost`),title:a(`watchlist.col_cost_help`),inputMode:`decimal`,value:g,disabled:n,onChange:e=>y(e.target.value),onBlur:()=>C(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:a(`watchlist.act_remove`)}),(0,S.jsxs)(`details`,{className:`pr-wtags`,children:[(0,S.jsxs)(`summary`,{children:[a(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,S.jsxs)(`div`,{children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.col_tags_help`)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[T.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,S.jsx)(h,{on:r,disabled:n,onClick:()=>w(t),children:t},t)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.col_tags`),placeholder:a(`watchlist.add_groups_ph`),value:u,disabled:n,onChange:e=>d(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=u.trim();t&&(d(``),w(t))}})]})]})]})]})}function ge({section:e,busy:t,onRename:n,onDissolve:r}){let i=_(),[a,o]=(0,v.useState)(e.tag??``);return(0,S.jsxs)(`div`,{className:`pr-ghead`,children:[(0,S.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,S.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),value:a,disabled:t,onChange:e=>o(e.target.value)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!a.trim()||a.trim()===e.tag,onClick:()=>n(e.tag,a.trim()),children:i(`watchlist.group_rename_apply`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function _e({entries:e,reload:n}){let r=_(),[a,o]=(0,v.useState)(!1),[s,c]=(0,v.useState)(null),[l,u]=(0,v.useState)(``),[d,f]=(0,v.useState)([]),[p,m]=(0,v.useState)(`tags`),g=(e,t=`list`)=>{o(!0),c(null),e.then(()=>{o(!1),n()},e=>{if(o(!1),e instanceof i){n();return}c({where:t,message:y(e,r(`common.offline`))})})},b=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),x=new Set(e.map(e=>e.ticker.toUpperCase())),C=new Set(d.map(e=>e.toLowerCase())),E=e.filter(e=>he(e,l)&&(!C.size||e.tags.some(e=>C.has(e.toLowerCase()))));return(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(de,{listed:x,tags:b,busy:a,failure:s?.where===`add`?s.message:null,onAdd:e=>g(t(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,S.jsx)(T,{title:r(`profile.empty_watchlist_title`),children:(0,S.jsx)(`div`,{className:`pr-cardbody`,children:(0,S.jsx)(`p`,{className:`pr-hint`,children:r(`profile.empty_watchlist_body`)})})}):(0,S.jsx)(T,{title:r(`watchlist.list_title`),sub:r(`watchlist.list_sub`),children:(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,"aria-label":r(`watchlist.filter`),placeholder:r(`watchlist.filter_ph`),value:l,onChange:e=>u(e.target.value)}),pe.map(e=>(0,S.jsx)(h,{on:e===p,onClick:()=>m(e),children:r(`watchlist.group_${e}`)},e))]}),b.length>0&&(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.tag_filter`)}),b.map(e=>(0,S.jsx)(h,{on:C.has(e.toLowerCase()),onClick:()=>f(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,S.jsx)(A,{message:s?.where===`list`?s.message:null}),E.length===0?(0,S.jsx)(`p`,{className:`pr-hint`,children:r(`watchlist.no_match`)}):me(E,p,r(`watchlist.g_untagged`),{all:r(`watchlist.g_all`),favorites:r(`watchlist.g_favorites`),rest:r(`watchlist.g_rest`)}).map(e=>(0,S.jsxs)(`div`,{children:[(0,S.jsx)(ge,{section:e,busy:a,onRename:(e,n)=>g(t(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:n})),onDissolve:e=>g(t(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(n=>(0,S.jsx)(Z,{entry:n,tags:b,busy:a,onEdit:(e,n)=>g(t(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,n)),onRemove:e=>g(t(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${n.ticker}`))]},e.id)),(0,S.jsxs)(`div`,{className:`pr-foot`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.count`,{n:e.length})}),(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:r(`watchlist.how_open`)}),(0,S.jsx)(`div`,{children:(0,S.jsx)(w,{text:r(`watchlist.how`)})})]})]})]})})]})}function ve({onAdded:r}){let i=_(),[a,o]=(0,v.useState)(0),s=e(()=>n(`/watchlist/suggestions`),[a]),[c,l]=(0,v.useState)(!1),[u,d]=(0,v.useState)(null);if(s.state!==`loaded`||s.data.suggestions.length===0)return null;let p=s.data.suggestions;function m(){l(!0),d(null),p.reduce((e,n)=>e.then(()=>t(`POST`,`/watchlist`,{ticker:n.ticker,name:n.name,tags:n.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{o(e=>e+1),r()}).catch(e=>d(y(e,i(`common.offline`)))).finally(()=>l(!1))}return(0,S.jsxs)(T,{title:i(`profile.focus_suggest_title`),children:[(0,S.jsx)(w,{text:i(`profile.focus_suggest_help`)}),(0,S.jsx)(`ul`,{className:`pr-examples`,children:p.map(e=>(0,S.jsxs)(`li`,{children:[(0,S.jsx)(f,{ticker:e.ticker,className:`pr-wsym`}),(0,S.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,S.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:c,onClick:m,children:i(`profile.focus_suggest_add`,{n:p.length})}),(0,S.jsx)(A,{message:u})]})}function ye({query:e}){return(0,S.jsx)(`div`,{className:`pr-main`,children:(0,S.jsx)(m,{query:e,children:(e,t)=>(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(_e,{entries:e.entries,reload:t}),(0,S.jsx)(ve,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function be(){return d()?(0,S.jsx)(s,{text:`common.sign_in`}):(0,S.jsx)(xe,{})}function xe(){let t=_(),r=o(),{params:i,setParams:s}=a(),c=ce(t(`common.offline`)),l=e(()=>n(`/me`),[]),u=l.state===`loaded`?l.data:null,d=e(()=>n(`/watchlist`),[]),f=d.state===`loaded`?d.data.entries.length:0,[p,m]=(0,v.useState)(!1),h=u?.name?.trim()||``,g=i.get(`tab`)??``,y=Q.some(e=>e.id===g)?g:`prefs`,b=r.email??``;return(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:le}),(0,S.jsxs)(`header`,{className:`pr-head`,children:[(0,S.jsx)(`h1`,{className:`pr-title`,children:t(`nav.profile`)}),(0,S.jsx)(`span`,{className:`pr-savehint`,children:t(`profile.saves_instantly`)})]}),(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-ident`,children:[(0,S.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:u?.picture&&!p?(0,S.jsx)(`img`,{src:u.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>m(!0)}):$(b,h)}),(0,S.jsxs)(`div`,{className:`pr-ident-t`,children:[h&&h!==b&&(0,S.jsx)(`span`,{className:`pr-ident-n`,children:h}),(0,S.jsx)(`span`,{className:`pr-ident-e`,children:b})]}),(0,S.jsx)(`div`,{className:`pr-ident-r`,children:(0,S.jsx)(`span`,{className:`pr-ident-note`,children:t(`profile.account_scope`)})}),(0,S.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,children:t(`common.log_out`)})]})}),(0,S.jsx)(`div`,{className:`pr-tabs`,role:`tablist`,"aria-label":t(`nav.profile`),children:Q.map(e=>(0,S.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":e.id===y,className:e.id===y?`pr-tab pr-tab-on`:`pr-tab`,onClick:()=>s({tab:e.id}),children:[t(e.label),e.id===`watch`&&f>0&&(0,S.jsx)(`span`,{className:`pr-tab-n`,children:f})]},e.id))}),y===`prefs`&&(0,S.jsx)(oe,{...c,owner:l.state===`loaded`?!!u?.owner:null}),y===`iv`&&(0,S.jsx)(te,{}),y===`watch`&&(0,S.jsx)(ye,{query:d}),y===`notify`&&(0,S.jsx)(ee,{...c})]})}export{be as default,$ as initials};