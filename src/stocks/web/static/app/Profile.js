import{B as e,E as t,G as n,H as r,K as i,N as a,P as o,U as s,V as c,W as l,i as u,j as d,n as f,o as p,q as m,t as h,u as g,z as _}from"./app.js";var v=m(i(),1);function y(e,t){return e instanceof r?e.detail:t}var b=3e3;function x(e){let{reload:t}=o(),[r,i]=(0,v.useState)(null),[a,c]=(0,v.useState)(null),[u,d]=(0,v.useState)(!1),[f,p]=(0,v.useState)(!1),[m,h]=(0,v.useState)(null),[g,_]=(0,v.useState)(null),x=(0,v.useCallback)(n=>n instanceof s?(t(),null):{kind:`failed`,error:y(n,e)},[t,e]);(0,v.useEffect)(()=>{let e=!0;return l(`/notify/telegram`).then(t=>e&&i(t),t=>{e&&_(x(t))}),()=>{e=!1}},[x]);let[S,C]=(0,v.useState)(()=>typeof document>`u`||!document.hidden);return(0,v.useEffect)(()=>{let e=()=>C(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,v.useEffect)(()=>{if(!a||!S)return;if(Date.now()>=a.deadline){c(null),d(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=a.deadline){c(null),d(!0);return}l(`/notify/telegram`).then(t=>{e&&(p(!1),i(t),t.linked&&c(null))},()=>e&&p(!0))},b);return()=>{e=!1,window.clearInterval(t)}},[a,S]),{state:r,pending:a,expired:u,stalled:f,busy:m,note:g,connect:(0,v.useCallback)(()=>{h(`connect`),_(null),d(!1),n(`POST`,`/notify/telegram`).then(e=>{h(null),c({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{h(null),_(x(e))})},[x]),test:(0,v.useCallback)(()=>{h(`test`),_(null),n(`POST`,`/notify/telegram/test`).then(e=>{h(null),i(e),_({kind:`test_sent`})},n=>{if(h(null),n instanceof s){t();return}_({kind:`test_failed`,error:y(n,e)})})},[t,e]),unlink:(0,v.useCallback)(()=>{h(`unlink`),_(null),n(`DELETE`,`/notify/telegram`).then(e=>{h(null),i(e),c(null),d(!1),_({kind:`unlinked`})},e=>{h(null),_(x(e))})},[x])}}var S=e();function C({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,S.jsx)(S.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,S.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,S.jsx)(`code`,{children:e.slice(1,-1)},t):(0,S.jsx)(v.Fragment,{children:e},t))})}function w({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,S.jsx)(`ul`,{children:r.map((e,t)=>(0,S.jsx)(`li`,{children:(0,S.jsx)(C,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,S.jsx)(`p`,{children:(0,S.jsx)(C,{text:a})},t))}),i(-1),(0,S.jsx)(`div`,{className:t??`pr-prose`,children:n})}function T({title:e,sub:t,note:n,children:r}){return(0,S.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,S.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,S.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,S.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,S.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function E({label:e,help:t,middle:n,children:r}){return(0,S.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,S.jsxs)(`div`,{className:`pr-row-l`,children:[(0,S.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,S.jsx)(`span`,{className:`pr-row-help`,children:(0,S.jsx)(C,{text:t})})]}),(0,S.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function D({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,S.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,S.jsx)(`option`,{value:e,children:n(e)},e))})}function O({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,S.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,S.jsx)(p,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function k({checked:e,onToggle:t,label:n,disabled:r}){return(0,S.jsx)(`label`,{className:`pr-switch`,children:(0,S.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function A({message:e}){return e?(0,S.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function j({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,S.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,S.jsx)(p,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ee({prefs:e,saving:t,failure:n,save:r}){let i=_(),a=x(i(`common.offline`)),o=e=>n?.field===e?n.message:null,s=a.state?a.state.linked:e.telegram_linked,c=a.state?.configured??(e.telegram_linked?!0:null);return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[c===null&&!a.note&&(0,S.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),c===!1&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),c===!0&&s&&(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,S.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:a.state?.username?`@${a.state.username}`:``}).trim()})]}),c===!0&&!s&&!a.pending&&(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:a.busy===`connect`,onClick:a.connect,children:i(`profile.tg_connect`)}),a.expired&&(0,S.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),c===!0&&!s&&a.pending&&(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(`a`,{className:`pr-linkbtn`,href:a.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,S.jsx)(`p`,{className:`pr-hint`,children:(0,S.jsx)(C,{text:i(`profile.tg_manual`,{bot:a.pending.bot,code:a.pending.code})})}),(0,S.jsx)(`p`,{className:`pr-busy`,children:a.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),a.note?.kind===`failed`&&(0,S.jsx)(A,{message:a.note.error}),a.note?.kind===`unlinked`&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),c===!0&&s&&(0,S.jsxs)(S.Fragment,{children:[(0,S.jsxs)(E,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`test`,onClick:a.test,children:i(`profile.tg_test`)}),a.note?.kind===`test_sent`&&(0,S.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),a.note?.kind===`test_failed`&&(0,S.jsx)(A,{message:i(`profile.tg_test_failed`,{error:a.note.error})})]}),(0,S.jsx)(E,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`unlink`,onClick:a.unlink,children:i(`profile.tg_unlink`)})})]})]}),c===!0&&s&&(0,S.jsxs)(T,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,S.jsxs)(E,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,S.jsx)(A,{message:o(`notify_digest`)})]}),(0,S.jsxs)(E,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,S.jsx)(A,{message:o(`notify_weekly`)})]}),(0,S.jsxs)(E,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,S.jsx)(k,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,S.jsx)(A,{message:o(`notify_alerts`)})]})]})]}),(0,S.jsx)(`aside`,{className:`pr-rail`,children:(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,S.jsx)(w,{text:i(`profile.tg_how_body`)})]})})})]})}function te(){let e=c(async()=>{let[e,t]=await Promise.all([l(`/profile-options`),l(`/profile`)]);return{options:e,profile:t}},[]);return(0,S.jsx)(h,{query:e,skeleton:(0,S.jsx)(f,{rows:8}),children:e=>(0,S.jsx)(M,{options:e.options,stored:e.profile})})}function M({options:e,stored:t}){let r=_(),[i,a]=(0,v.useState)(t),[o,s]=(0,v.useState)(null),[c,l]=(0,v.useState)(null);function u(e,i){a(e),s(i),l(null),n(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>a(e)).catch(e=>{a(t),l(y(e,r(`common.offline`)))}).finally(()=>s(null))}let d=e=>t=>r(`profile.iv_${e}_${t}`);return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:r(`profile.iv_how_title`),sub:r(`profile.iv_how_sub`),children:[(0,S.jsx)(E,{label:r(`profile.iv_risk`),help:r(`profile.iv_risk_help`),children:(0,S.jsx)(D,{label:r(`profile.iv_risk`),value:i.risk,options:e.risk,labelOf:d(`risk`),disabled:o===`risk`,onPick:e=>e!==i.risk&&u({...i,risk:e},`risk`)})}),(0,S.jsx)(E,{label:r(`profile.iv_horizon`),help:r(`profile.iv_horizon_help`),children:(0,S.jsx)(D,{label:r(`profile.iv_horizon`),value:i.horizon,options:e.horizon,labelOf:d(`horizon`),disabled:o===`horizon`,onPick:e=>e!==i.horizon&&u({...i,horizon:e},`horizon`)})})]}),(0,S.jsxs)(T,{title:r(`profile.iv_what_title`),sub:r(`profile.iv_what_sub`),children:[(0,S.jsx)(E,{label:r(`profile.iv_focus`),help:r(`profile.iv_focus_help`),children:(0,S.jsx)(j,{values:i.focus,options:e.focus,labelOf:d(`focus`),disabled:o===`focus`,onToggle:(e,t)=>u({...i,focus:t?[...i.focus,e]:i.focus.filter(t=>t!==e)},`focus`)})}),(0,S.jsx)(E,{label:r(`profile.iv_constraints`),help:r(`profile.iv_constraints_help`),children:(0,S.jsx)(j,{values:i.constraints,options:e.constraints,labelOf:d(`constraints`),disabled:o===`constraints`,onToggle:(e,t)=>u({...i,constraints:t?[...i.constraints,e]:i.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,S.jsxs)(T,{title:r(`profile.iv_notes_title`),sub:r(`profile.iv_caption`),children:[(0,S.jsx)(E,{label:r(`profile.iv_notes`),help:r(`profile.iv_notes_help`),children:(0,S.jsx)(F,{value:i.notes,placeholder:r(`profile.iv_notes_ph`),label:r(`profile.iv_notes`),disabled:o===`notes`,onCommit:e=>e!==i.notes&&u({...i,notes:e},`notes`)})}),(0,S.jsx)(A,{message:c})]})]}),(0,S.jsx)(`aside`,{className:`pr-rail`,children:(0,S.jsxs)(T,{children:[(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:r(`profile.iv_sum_title`)}),(0,S.jsx)(P,{label:r(`profile.iv_risk`),value:r(`profile.iv_risk_${i.risk}`)}),(0,S.jsx)(P,{label:r(`profile.iv_horizon`),value:r(`profile.iv_horizon_${i.horizon}`)}),(0,S.jsx)(P,{label:r(`profile.iv_focus`),value:N(i.focus,d(`focus`),r(`profile.iv_sum_none`))}),(0,S.jsx)(P,{label:r(`profile.iv_constraints`),value:N(i.constraints,d(`constraints`),r(`profile.iv_sum_none`))}),(0,S.jsx)(`div`,{className:`pr-sum-rule`}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:r(`profile.iv_privacy`)})]}),i.persona?(0,S.jsxs)(`details`,{className:`pr-persona`,children:[(0,S.jsx)(`summary`,{children:r(`profile.iv_persona_open`)}),(0,S.jsx)(`p`,{className:`pr-sum-note`,children:r(`profile.iv_persona_help`)}),(0,S.jsx)(`code`,{className:`pr-persona-text`,children:i.persona})]}):null]})})]})}function N(e,t,n){return e.length?e.map(t).join(`, `):n}function P({label:e,value:t}){return(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:e}),(0,S.jsx)(`b`,{children:t})]})}function F({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,v.useState)(e);return(0,v.useEffect)(()=>o(e),[e]),(0,S.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}var I=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],L=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ne={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function R(e){let t=ne[e];return t&&t!==e?`${t} ${e}`:e}var z={en:`English`,es:`Español`},B=[0,.08,.09];function V(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function re(e,t){if(t)return V(e,t)??V(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return V(e,n.length>1&&n[1]?.length===2?n[1]:``)??V(e,e.default)}function H(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function U({email:e,onClose:t}){let i=_(),[a,o]=(0,v.useState)(``),[c,l]=(0,v.useState)(!1),[u,d]=(0,v.useState)(null),f=H(a,e);return(0,v.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!c&&t()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[t,c]),(0,S.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!c&&t()},children:(0,S.jsxs)(`div`,{className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":i(`profile.delete_title`),children:[(0,S.jsx)(`h2`,{className:`pr-modal-t`,children:i(`profile.delete_title`)}),(0,S.jsx)(w,{text:i(`profile.delete_body`)}),(0,S.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:i(`profile.delete_confirm`)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:a,disabled:c,onChange:e=>o(e.target.value)})]}),(0,S.jsx)(A,{message:u}),(0,S.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:t,children:i(`common.cancel`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!f||c,onClick:()=>{l(!0),d(null),n(`DELETE`,`/account`,{confirm:a.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;window.location.assign(n)},e=>{if(l(!1),e instanceof s){window.location.assign(`/auth/logout`);return}d(e instanceof r&&e.status===422?e.detail:e instanceof r?i(`profile.delete_failed`):i(`common.offline`))})},children:i(`profile.delete_button`)})]})]})})}function W(){let e=_(),t=d(),[n,r]=(0,v.useState)(!1);return(0,S.jsxs)(E,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>r(!0),children:e(`profile.delete_open`)}),n&&(0,S.jsx)(U,{email:t.email??``,onClose:()=>r(!1)})]})}function G(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function K(){let e=_(),{setParams:n}=t(),r=c(()=>l(`/onboarding`),[]),i=r.state===`loaded`?G(r.data.setup):null;return(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:e(`tour.launch`)}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:e(`tour.launch_caption`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{n({tour:`1`})},children:e(`tour.launch_start`)}),i&&(0,S.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":e(`home.setup_progress`,{done:i[0],total:i[1]}),"aria-valuemin":0,"aria-valuemax":i[1],"aria-valuenow":i[0],children:[(0,S.jsx)(`div`,{className:`pr-prog-track`,children:(0,S.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(i[0]/i[1]*100)}%`}})}),(0,S.jsxs)(`span`,{className:`pr-prog-n`,children:[i[0],`/`,i[1]]})]})]})})}var q=`auto`;function J({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,v.useState)(String(e)),[u,d]=(0,v.useState)(e);return u!==e&&(d(e),l(String(e))),(0,S.jsxs)(`span`,{className:`pr-chips`,children:[(0,S.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,S.jsx)(`span`,{className:`pr-hint`,children:o})]})}function Y({prefs:e,saving:t,failure:n,save:r,owner:i}){let a=_(),o=c(()=>l(`/import/last`),[]),s=c(()=>l(`/portfolio/transactions`,{limit:1}),[]),u=[q,...Object.keys(z)],d=e=>e===q?a(`profile.lang_auto`):z[e]??e,f=L.includes(e.currency)?[...L]:[...L,e.currency],p=I.filter(e=>!f.includes(e)),m=c(()=>l(`/jurisdictions`),[]),h=m.state===`loaded`?m.data:null,g=[q,...(h?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===q)return`🌐 ${a(`profile.tax_residence_auto`)}`;let t=h?.jurisdictions.find(t=>t.code===e),n=a(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=h?re(h,e.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?a(`profile.tax_year_calendar`):a(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?a(`profile.tax_match_${y.matching}`):``,C=e=>n?.field===e?n.message:null;return(0,S.jsxs)(`div`,{className:`pr-body`,children:[(0,S.jsxs)(`div`,{className:`pr-main`,children:[(0,S.jsxs)(T,{title:a(`profile.ui_section`),sub:a(`profile.ui_section_sub`),children:[(0,S.jsxs)(E,{label:a(`profile.language`),help:a(`profile.language_caption`),children:[(0,S.jsx)(D,{label:a(`profile.language`),value:e.language??q,options:u,labelOf:d,disabled:t===`language`,onPick:t=>{let n=t===q?null:t;n!==e.language&&r(`language`,n)}}),(0,S.jsx)(A,{message:C(`language`)})]}),(0,S.jsxs)(E,{label:a(`profile.display_currency`),help:a(`profile.currency_caption`),children:[(0,S.jsx)(O,{value:e.currency,options:f,labelOf:R,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)}),p.length>0&&(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:a(`profile.currency_more`,{n:p.length})}),(0,S.jsx)(`div`,{children:(0,S.jsx)(O,{value:e.currency,options:p,labelOf:R,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)})})]}),p.length>0&&(0,S.jsx)(`span`,{className:`pr-morehint`,children:p.join(` · `)}),(0,S.jsx)(A,{message:C(`currency`)})]})]}),(0,S.jsxs)(T,{title:a(`profile.tax_section`),note:a(`profile.tax_legal_note`),children:[(0,S.jsxs)(E,{label:a(`profile.tax_residence`),help:a(`profile.tax_residence_caption`),children:[(0,S.jsx)(D,{label:a(`profile.tax_residence`),value:e.tax_residence??q,options:g,labelOf:v,disabled:t===`tax_residence`,onPick:t=>{let n=t===q?null:t;n!==e.tax_residence&&r(`tax_residence`,n)}}),(0,S.jsx)(A,{message:C(`tax_residence`)}),y?(0,S.jsxs)(`div`,{className:`pr-rules`,children:[(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:a(`profile.tax_rule_cost`)}),(0,S.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,a(`profile.tax_rule_fx`)]})]}),(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:a(`profile.tax_rule_matching`)}),(0,S.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,S.jsxs)(`div`,{className:`pr-rule`,children:[(0,S.jsx)(`span`,{className:`pr-rule-k`,children:a(`profile.tax_rule_year`)}),(0,S.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(n=>{let i=y.code.toLowerCase();return n===`filing_status`?(0,S.jsxs)(E,{label:a(`profile.tax_filing_status`),help:a(`profile.tax_filing_status_caption_${i}`),children:[(0,S.jsx)(D,{label:a(`profile.tax_filing_status`),value:y.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>a(`profile.tax_status_${e}`),disabled:t===`tax_filing_status`,onPick:e=>r(`tax_filing_status`,e)}),(0,S.jsx)(A,{message:C(`tax_filing_status`)})]},n):n===`church_tax_rate`?(0,S.jsxs)(E,{label:a(`profile.tax_church`),help:a(`profile.tax_church_caption`),children:[(0,S.jsx)(D,{label:a(`profile.tax_church`),value:String(B.includes(e.tax_church_rate)?e.tax_church_rate:0),options:B.map(String),labelOf:e=>a(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:t===`tax_church_rate`,onPick:e=>r(`tax_church_rate`,Number(e))}),(0,S.jsx)(A,{message:C(`tax_church_rate`)})]},n):n===`other_income`?(0,S.jsxs)(E,{label:a(`profile.tax_other_income`),help:a(`profile.tax_other_income_caption_${i}`),children:[(0,S.jsx)(J,{label:a(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:t===`tax_other_income`,onCommit:e=>r(`tax_other_income`,e)}),(0,S.jsx)(A,{message:C(`tax_other_income`)})]},n):n===`subnational_rate`?(0,S.jsxs)(E,{label:a(`profile.tax_subnational`),help:a(`profile.tax_subnational_caption`),children:[(0,S.jsx)(J,{label:a(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:t===`tax_subnational_rate`,onCommit:e=>r(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,S.jsx)(A,{message:C(`tax_subnational_rate`)})]},n):(0,S.jsxs)(E,{label:a(`profile.tax_niit`),help:a(`profile.tax_niit_caption`),middle:!0,children:[(0,S.jsx)(k,{label:a(`profile.tax_niit`),checked:e.tax_niit,disabled:t===`tax_niit`,onToggle:e=>r(`tax_niit`,e)}),(0,S.jsx)(A,{message:C(`tax_niit`)})]},n)})]}),(0,S.jsxs)(T,{title:a(`profile.data_section`),children:[(0,S.jsx)(E,{label:a(`profile.export_title`),help:a(`profile.export_help`),children:s.state===`loaded`&&s.data.total>0?(0,S.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:a(`profile.export_button`)}):(0,S.jsx)(`span`,{className:`pr-muted`,children:a(`profile.export_none`)})}),i===!1&&(0,S.jsx)(W,{})]})]}),(0,S.jsxs)(`aside`,{className:`pr-rail`,children:[(0,S.jsx)(K,{}),(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-sum`,children:[(0,S.jsx)(`span`,{className:`pr-sum-t`,children:a(`profile.summary_title`)}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:a(`profile.language`)}),(0,S.jsx)(`b`,{children:(d(e.language??q).split(`(`)[0]??``).trim()})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:a(`profile.display_currency`)}),(0,S.jsx)(`b`,{children:e.currency})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:a(`profile.tax_section`)}),(0,S.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(a(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:a(`common.loading`)})]}),(0,S.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,S.jsx)(`span`,{children:a(`profile.summary_last_import`)}),(0,S.jsx)(`b`,{children:o.state===`loaded`?o.data.imported_at?.slice(0,10)??a(`profile.summary_never`):a(`common.loading`)})]}),(0,S.jsx)(`div`,{className:`pr-sum-rule`}),(0,S.jsx)(`span`,{className:`pr-sum-note`,children:a(`profile.summary_note`)})]})})]})]})}var ie=new Set([`currency`,`language`]);function ae(e){let t=o(),[r,i]=(0,v.useState)(t.prefs),[a,c]=(0,v.useState)(null),[l,u]=(0,v.useState)(null);return{prefs:r,saving:a,failure:l,save:(0,v.useCallback)((r,a)=>{c(r),u(null),n(`PATCH`,`/prefs`,{[r]:a}).then(e=>{c(null),i(e),ie.has(r)&&t.reload()},n=>{if(c(null),n instanceof s){t.reload();return}u({field:r,message:y(n,e)})})},[t,e])}}var oe=`
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
`,se={analyze:`raw`},X=2;function ce({listed:e,tags:t,onAdd:n,busy:r,failure:i}){let a=_(),[o,s]=(0,v.useState)(``),[c,u]=(0,v.useState)([]),[d,f]=(0,v.useState)(``),[m,h]=(0,v.useState)(!1),[g,y]=(0,v.useState)(null),[b,x]=(0,v.useState)(null),C=o.trim();(0,v.useEffect)(()=>{if(C.length<X){y(null);return}let e=!0,t=window.setTimeout(()=>{l(`/search`,{q:C,limit:8}).then(t=>e&&(y(t.matches),x(null)),()=>e&&(y([]),x(a(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[C]);let w=e=>{n({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...c.length?{tags:c}:{}}),s(``),y(null)},E=[...new Set([...t,...c])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,S.jsx)(T,{title:a(`watchlist.add_title`),sub:a(`watchlist.add_sub`),children:(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,S.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,"aria-label":a(`watchlist.add_title`),placeholder:a(`watchlist.add_placeholder`),value:o,onChange:e=>s(e.target.value)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups`)}),E.map(e=>(0,S.jsx)(p,{on:c.includes(e),onClick:()=>u(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.add_groups`),placeholder:a(`watchlist.add_groups_ph`),value:d,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(u(e=>e.includes(t)?e:[...e,t]),f(``))}})]}),(0,S.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups_help`)}),(0,S.jsxs)(`label`,{className:`pr-switch`,children:[(0,S.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,S.jsx)(`span`,{children:a(`watchlist.add_fav`)})]}),(0,S.jsx)(A,{message:i??b}),C.length<X?(0,S.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_hint`)}):g===null?(0,S.jsx)(`p`,{className:`pr-hint`,children:a(`common.loading`)}):g.length===0?(0,S.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_none`)}):(0,S.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),i=se[t.kind]??t.kind;return(0,S.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||r,title:a(n?`watchlist.add_listed`:`watchlist.kind_${i}`),onClick:()=>w(t),children:[(0,S.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,S.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,S.jsx)(`span`,{className:`pr-resrow-k`,children:n?a(`watchlist.add_listed`):(t.exchange??``)||a(`watchlist.kind_${i}`)})]},t.ticker)})})]})})}var Z=e=>e?String(e):``;function le(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var ue=[`tags`,`favorites`,`flat`];function de(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function fe(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function pe({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let a=_(),[o,s]=(0,v.useState)(e.name),[c,l]=(0,v.useState)(e.name),[d,f]=(0,v.useState)(``),[m,h]=(0,v.useState)(Z(e.shares)),[g,y]=(0,v.useState)(Z(e.cost)),[b,x]=(0,v.useState)([e.shares,e.cost]);c!==e.name&&(l(e.name),s(e.name)),(b[0]!==e.shares||b[1]!==e.cost)&&(x([e.shares,e.cost]),h(Z(e.shares)),y(Z(e.cost)));let C=(t,n)=>{let i=le(n,e[t]);if(i===void 0){t===`shares`?h(Z(e.shares)):y(Z(e.cost));return}r(e.ticker,{[t]:i})},w=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),T=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,S.jsxs)(`div`,{className:`pr-wrow`,children:[(0,S.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":a(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,S.jsx)(u,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":a(`watchlist.col_name`),value:o,disabled:n,onChange:e=>s(e.target.value),onBlur:()=>o!==e.name&&r(e.ticker,{name:o}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_shares`),placeholder:a(`watchlist.col_shares`),inputMode:`decimal`,value:m,disabled:n,onChange:e=>h(e.target.value),onBlur:()=>C(`shares`,m),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_cost`),placeholder:a(`watchlist.col_cost`),title:a(`watchlist.col_cost_help`),inputMode:`decimal`,value:g,disabled:n,onChange:e=>y(e.target.value),onBlur:()=>C(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:a(`watchlist.act_remove`)}),(0,S.jsxs)(`details`,{className:`pr-wtags`,children:[(0,S.jsxs)(`summary`,{children:[a(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,S.jsxs)(`div`,{children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.col_tags_help`)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[T.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,S.jsx)(p,{on:r,disabled:n,onClick:()=>w(t),children:t},t)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.col_tags`),placeholder:a(`watchlist.add_groups_ph`),value:d,disabled:n,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(f(``),w(t))}})]})]})]})]})}function me({section:e,busy:t,onRename:n,onDissolve:r}){let i=_(),[a,o]=(0,v.useState)(e.tag??``);return(0,S.jsxs)(`div`,{className:`pr-ghead`,children:[(0,S.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,S.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),value:a,disabled:t,onChange:e=>o(e.target.value)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!a.trim()||a.trim()===e.tag,onClick:()=>n(e.tag,a.trim()),children:i(`watchlist.group_rename_apply`)}),(0,S.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function he({entries:e,reload:t}){let r=_(),[i,a]=(0,v.useState)(!1),[o,c]=(0,v.useState)(null),[l,u]=(0,v.useState)(``),[d,f]=(0,v.useState)([]),[m,h]=(0,v.useState)(`tags`),g=(e,n=`list`)=>{a(!0),c(null),e.then(()=>{a(!1),t()},e=>{if(a(!1),e instanceof s){t();return}c({where:n,message:y(e,r(`common.offline`))})})},b=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),x=new Set(e.map(e=>e.ticker.toUpperCase())),C=new Set(d.map(e=>e.toLowerCase())),E=e.filter(e=>fe(e,l)&&(!C.size||e.tags.some(e=>C.has(e.toLowerCase()))));return(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(ce,{listed:x,tags:b,busy:i,failure:o?.where===`add`?o.message:null,onAdd:e=>g(n(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,S.jsx)(T,{title:r(`profile.empty_watchlist_title`),children:(0,S.jsx)(`div`,{className:`pr-cardbody`,children:(0,S.jsx)(`p`,{className:`pr-hint`,children:r(`profile.empty_watchlist_body`)})})}):(0,S.jsx)(T,{title:r(`watchlist.list_title`),sub:r(`watchlist.list_sub`),children:(0,S.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,"aria-label":r(`watchlist.filter`),placeholder:r(`watchlist.filter_ph`),value:l,onChange:e=>u(e.target.value)}),ue.map(e=>(0,S.jsx)(p,{on:e===m,onClick:()=>h(e),children:r(`watchlist.group_${e}`)},e))]}),b.length>0&&(0,S.jsxs)(`div`,{className:`pr-chips`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.tag_filter`)}),b.map(e=>(0,S.jsx)(p,{on:C.has(e.toLowerCase()),onClick:()=>f(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,S.jsx)(A,{message:o?.where===`list`?o.message:null}),E.length===0?(0,S.jsx)(`p`,{className:`pr-hint`,children:r(`watchlist.no_match`)}):de(E,m,r(`watchlist.g_untagged`),{all:r(`watchlist.g_all`),favorites:r(`watchlist.g_favorites`),rest:r(`watchlist.g_rest`)}).map(e=>(0,S.jsxs)(`div`,{children:[(0,S.jsx)(me,{section:e,busy:i,onRename:(e,t)=>g(n(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>g(n(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,S.jsx)(pe,{entry:t,tags:b,busy:i,onEdit:(e,t)=>g(n(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>g(n(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,S.jsxs)(`div`,{className:`pr-foot`,children:[(0,S.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.count`,{n:e.length})}),(0,S.jsxs)(`details`,{className:`pr-more`,children:[(0,S.jsx)(`summary`,{children:r(`watchlist.how_open`)}),(0,S.jsx)(`div`,{children:(0,S.jsx)(w,{text:r(`watchlist.how`)})})]})]})]})})]})}function ge({onAdded:e}){let t=_(),[r,i]=(0,v.useState)(0),a=c(()=>l(`/watchlist/suggestions`),[r]),[o,s]=(0,v.useState)(!1),[d,f]=(0,v.useState)(null);if(a.state!==`loaded`||a.data.suggestions.length===0)return null;let p=a.data.suggestions;function m(){s(!0),f(null),p.reduce((e,t)=>e.then(()=>n(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{i(e=>e+1),e()}).catch(e=>f(y(e,t(`common.offline`)))).finally(()=>s(!1))}return(0,S.jsxs)(T,{title:t(`profile.focus_suggest_title`),children:[(0,S.jsx)(w,{text:t(`profile.focus_suggest_help`)}),(0,S.jsx)(`ul`,{className:`pr-examples`,children:p.map(e=>(0,S.jsxs)(`li`,{children:[(0,S.jsx)(u,{ticker:e.ticker,className:`pr-wsym`}),(0,S.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,S.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:o,onClick:m,children:t(`profile.focus_suggest_add`,{n:p.length})}),(0,S.jsx)(A,{message:d})]})}function _e({query:e}){return(0,S.jsx)(`div`,{className:`pr-main`,children:(0,S.jsx)(h,{query:e,children:(e,t)=>(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(he,{entries:e.entries,reload:t}),(0,S.jsx)(ge,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function ve(){return a()?(0,S.jsx)(g,{text:`common.sign_in`}):(0,S.jsx)(ye,{})}function ye(){let e=_(),n=d(),{params:r,setParams:i}=t(),a=ae(e(`common.offline`)),o=c(()=>l(`/me`),[]),s=o.state===`loaded`?o.data:null,u=c(()=>l(`/watchlist`),[]),f=u.state===`loaded`?u.data.entries.length:0,[p,m]=(0,v.useState)(!1),h=s?.name?.trim()||``,g=r.get(`tab`)??``,y=Q.some(e=>e.id===g)?g:`prefs`,b=n.email??``;return(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:oe}),(0,S.jsxs)(`header`,{className:`pr-head`,children:[(0,S.jsx)(`h1`,{className:`pr-title`,children:e(`nav.profile`)}),(0,S.jsx)(`span`,{className:`pr-savehint`,children:e(`profile.saves_instantly`)})]}),(0,S.jsx)(T,{children:(0,S.jsxs)(`div`,{className:`pr-ident`,children:[(0,S.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:s?.picture&&!p?(0,S.jsx)(`img`,{src:s.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>m(!0)}):$(b,h)}),(0,S.jsxs)(`div`,{className:`pr-ident-t`,children:[h&&h!==b&&(0,S.jsx)(`span`,{className:`pr-ident-n`,children:h}),(0,S.jsx)(`span`,{className:`pr-ident-e`,children:b})]}),(0,S.jsx)(`div`,{className:`pr-ident-r`,children:(0,S.jsx)(`span`,{className:`pr-ident-note`,children:e(`profile.account_scope`)})}),(0,S.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,children:e(`common.log_out`)})]})}),(0,S.jsx)(`div`,{className:`pr-tabs`,role:`tablist`,"aria-label":e(`nav.profile`),children:Q.map(t=>(0,S.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":t.id===y,className:t.id===y?`pr-tab pr-tab-on`:`pr-tab`,onClick:()=>i({tab:t.id}),children:[e(t.label),t.id===`watch`&&f>0&&(0,S.jsx)(`span`,{className:`pr-tab-n`,children:f})]},t.id))}),y===`prefs`&&(0,S.jsx)(Y,{...a,owner:o.state===`loaded`?!!s?.owner:null}),y===`iv`&&(0,S.jsx)(te,{}),y===`watch`&&(0,S.jsx)(_e,{query:u}),y===`notify`&&(0,S.jsx)(ee,{...a})]})}export{ve as default,$ as initials};