import{$t as e,Et as t,Ht as n,It as r,Lt as i,O as a,Pt as o,Qt as s,T as c,Tt as l,Ut as u,Wt as d,Xt as f,Zt as p,h as m,in as h,m as g,nn as _,on as v,r as y,t as b,tn as x,x as S}from"./app-CP1O5g_J.js";import{t as C}from"./dates-CJpVElMb.js";import{t as ee}from"./Tabs-BdI4RMQN.js";import{a as te,i as ne,n as re,r as ie}from"./Journal-C-sKaYlX.js";var w=v(h(),1);function T(e,t){return e instanceof p?e.detail:t}var ae=3e3;function oe(t){let{reload:n}=i(),[r,a]=(0,w.useState)(null),[o,c]=(0,w.useState)(null),[l,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(!1),[p,m]=(0,w.useState)(null),[h,g]=(0,w.useState)(null),_=(0,w.useCallback)(e=>e instanceof s?(n(),null):{kind:`failed`,error:T(e,t)},[n,t]);(0,w.useEffect)(()=>{let t=!0;return e(`/notify/telegram`).then(e=>t&&a(e),e=>{t&&g(_(e))}),()=>{t=!1}},[_]);let[v,y]=(0,w.useState)(()=>typeof document>`u`||!document.hidden);return(0,w.useEffect)(()=>{let e=()=>y(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,w.useEffect)(()=>{if(!o||!v)return;if(Date.now()>=o.deadline){c(null),u(!0);return}let t=!0,n=window.setInterval(()=>{if(Date.now()>=o.deadline){c(null),u(!0);return}e(`/notify/telegram`).then(e=>{t&&(f(!1),a(e),e.linked&&c(null))},()=>t&&f(!0))},ae);return()=>{t=!1,window.clearInterval(n)}},[o,v]),{state:r,pending:o,expired:l,stalled:d,busy:p,note:h,connect:(0,w.useCallback)(()=>{m(`connect`),g(null),u(!1),x(`POST`,`/notify/telegram`).then(e=>{m(null),c({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{m(null),g(_(e))})},[_]),test:(0,w.useCallback)(()=>{m(`test`),g(null),x(`POST`,`/notify/telegram/test`).then(e=>{m(null),a(e),g({kind:`test_sent`})},e=>{if(m(null),e instanceof s){n();return}g({kind:`test_failed`,error:T(e,t)})})},[n,t]),unlink:(0,w.useCallback)(()=>{m(`unlink`),g(null),x(`DELETE`,`/notify/telegram`).then(e=>{m(null),a(e),c(null),u(!1),g({kind:`unlinked`})},e=>{m(null),g(_(e))})},[_])}}var E=f();function D({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,E.jsx)(E.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,E.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,E.jsx)(`code`,{children:e.slice(1,-1)},t):(0,E.jsx)(w.Fragment,{children:e},t))})}function O({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,E.jsx)(`ul`,{children:r.map((e,t)=>(0,E.jsx)(`li`,{children:(0,E.jsx)(D,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,E.jsx)(`p`,{children:(0,E.jsx)(D,{text:a})},t))}),i(-1),(0,E.jsx)(`div`,{className:t??`pr-prose`,children:n})}function k({title:e,sub:t,note:n,children:r}){return(0,E.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,E.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,E.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,E.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function A({label:e,help:t,middle:n,children:r}){return(0,E.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,E.jsxs)(`div`,{className:`pr-row-l`,children:[(0,E.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-row-help`,children:(0,E.jsx)(D,{text:t})})]}),(0,E.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function j({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,E.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,E.jsx)(`option`,{value:e,children:n(e)},e))})}function M({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,E.jsx)(S,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function N({checked:e,onToggle:t,label:n,disabled:r}){return(0,E.jsx)(`label`,{className:`pr-switch`,children:(0,E.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function P({message:e}){return e?(0,E.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function F({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,E.jsx)(S,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function se({prefs:e,saving:t,failure:n,save:r}){let i=u(),a=oe(i(`common.offline`)),o=e=>n?.field===e?n.message:null,s=a.state?a.state.linked:e.telegram_linked,c=a.state?.configured??(e.telegram_linked?!0:null);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[c===null&&!a.note&&(0,E.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),c===!1&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),c===!0&&s&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:a.state?.username?`@${a.state.username}`:``}).trim()})]}),c===!0&&!s&&!a.pending&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:a.busy===`connect`,onClick:a.connect,children:i(`profile.tg_connect`)}),a.expired&&(0,E.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),c===!0&&!s&&a.pending&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`a`,{className:`pr-linkbtn`,href:a.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:i(`profile.tg_manual`,{bot:a.pending.bot,code:a.pending.code})})}),(0,E.jsx)(`p`,{className:`pr-busy`,children:a.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),a.note?.kind===`failed`&&(0,E.jsx)(P,{message:a.note.error}),a.note?.kind===`unlinked`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),c===!0&&s&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsxs)(A,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`test`,onClick:a.test,children:i(`profile.tg_test`)}),a.note?.kind===`test_sent`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),a.note?.kind===`test_failed`&&(0,E.jsx)(P,{message:i(`profile.tg_test_failed`,{error:a.note.error})})]}),(0,E.jsx)(A,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`unlink`,onClick:a.unlink,children:i(`profile.tg_unlink`)})})]})]}),c===!0&&s&&(0,E.jsxs)(k,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,E.jsxs)(A,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,E.jsx)(P,{message:o(`notify_digest`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,E.jsx)(P,{message:o(`notify_weekly`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,E.jsx)(P,{message:o(`notify_alerts`)})]})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,E.jsx)(O,{text:i(`profile.tg_how_body`)})]})})})]})}function ce(){let t=d(async()=>{let[t,n]=await Promise.all([e(`/profile-options`),e(`/profile`)]);return{options:t,profile:n}},[]);return(0,E.jsx)(b,{query:t,skeleton:(0,E.jsx)(y,{rows:8}),children:e=>(0,E.jsx)(le,{options:e.options,stored:e.profile})})}function le({options:e,stored:t}){let n=u(),[r,i]=(0,w.useState)(t),[a,o]=(0,w.useState)(null),[s,c]=(0,w.useState)(null);function l(e,r){i(e),o(r),c(null),x(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>i(e)).catch(e=>{i(t),c(T(e,n(`common.offline`)))}).finally(()=>o(null))}let d=e=>t=>n(`profile.iv_${e}_${t}`);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:n(`profile.iv_how_title`),sub:n(`profile.iv_how_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_risk`),help:n(`profile.iv_risk_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_risk`),value:r.risk,options:e.risk,labelOf:d(`risk`),disabled:a===`risk`,onPick:e=>e!==r.risk&&l({...r,risk:e},`risk`)})}),(0,E.jsx)(A,{label:n(`profile.iv_horizon`),help:n(`profile.iv_horizon_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_horizon`),value:r.horizon,options:e.horizon,labelOf:d(`horizon`),disabled:a===`horizon`,onPick:e=>e!==r.horizon&&l({...r,horizon:e},`horizon`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_what_title`),sub:n(`profile.iv_what_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_focus`),help:n(`profile.iv_focus_help`),children:(0,E.jsx)(F,{values:r.focus,options:e.focus,labelOf:d(`focus`),disabled:a===`focus`,onToggle:(e,t)=>l({...r,focus:t?[...r.focus,e]:r.focus.filter(t=>t!==e)},`focus`)})}),(0,E.jsx)(A,{label:n(`profile.iv_constraints`),help:n(`profile.iv_constraints_help`),children:(0,E.jsx)(F,{values:r.constraints,options:e.constraints,labelOf:d(`constraints`),disabled:a===`constraints`,onToggle:(e,t)=>l({...r,constraints:t?[...r.constraints,e]:r.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_notes_title`),sub:n(`profile.iv_caption`),children:[(0,E.jsx)(A,{label:n(`profile.iv_notes`),help:n(`profile.iv_notes_help`),children:(0,E.jsx)(ue,{value:r.notes,placeholder:n(`profile.iv_notes_ph`),label:n(`profile.iv_notes`),disabled:a===`notes`,onCommit:e=>e!==r.notes&&l({...r,notes:e},`notes`)})}),(0,E.jsx)(P,{message:s})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsxs)(k,{children:[(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`profile.iv_sum_title`)}),(0,E.jsx)(L,{label:n(`profile.iv_risk`),value:n(`profile.iv_risk_${r.risk}`)}),(0,E.jsx)(L,{label:n(`profile.iv_horizon`),value:n(`profile.iv_horizon_${r.horizon}`)}),(0,E.jsx)(L,{label:n(`profile.iv_focus`),value:I(r.focus,d(`focus`),n(`profile.iv_sum_none`))}),(0,E.jsx)(L,{label:n(`profile.iv_constraints`),value:I(r.constraints,d(`constraints`),n(`profile.iv_sum_none`))}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`profile.iv_privacy`)})]}),r.persona?(0,E.jsxs)(`details`,{className:`pr-persona`,children:[(0,E.jsx)(`summary`,{children:n(`profile.iv_persona_open`)}),(0,E.jsx)(`p`,{className:`pr-sum-note`,children:n(`profile.iv_persona_help`)}),(0,E.jsx)(`code`,{className:`pr-persona-text`,children:r.persona})]}):null]})})]})}function I(e,t,n){return e.length?e.map(t).join(`, `):n}function L({label:e,value:t}){return(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:e}),(0,E.jsx)(`b`,{children:t})]})}function ue({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,w.useState)(e);return(0,w.useEffect)(()=>o(e),[e]),(0,E.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}function R(e){return e.split(`.`)[0]?.toLowerCase()??``}function de(){let e=u(),t=d(()=>te(),[]);return(0,E.jsxs)(k,{title:e(`journal.title`),children:[(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.intro`)})})}),(0,E.jsx)(b,{query:t,skeleton:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(y,{rows:6})}),children:t=>t.entries.length?(0,E.jsx)(fe,{entries:t.entries}):(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.empty`)})}),(0,E.jsx)(l,{page:`review`,className:`pr-btn ag-jr-cta`,children:e(`tour.review_cta`)})]})})]})}function fe({entries:e}){let t=u(),[n,r]=(0,w.useState)(`all`),[i,a]=(0,w.useState)(`all`),[o,s]=(0,w.useState)(``),c=(0,w.useMemo)(()=>{let t=R(o.trim());return e.filter(e=>(i===`all`||e.source===i)&&(!t||R(e.ticker).startsWith(t)))},[e,i,o]),l=(0,w.useMemo)(()=>{let e={};for(let t of c)e[t.state]=(e[t.state]??0)+1;return e},[c]),d=n===`all`?c:c.filter(e=>e.state===n),f=[`all`,...ne],p=[`all`,...ie];return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:t(`journal.filter_state`),children:(0,E.jsx)(M,{value:n,options:f,labelOf:e=>e===`all`?`${t(`journal.all_states`)} · ${c.length}`:`${t(`journal.state_${e}`)} · ${l[e]??0}`,onPick:r})}),(0,E.jsx)(A,{label:t(`journal.filter_source`),children:(0,E.jsx)(j,{value:i,options:p,labelOf:e=>t(e===`all`?`journal.all_sources`:`journal.source_${e}`),onPick:a,label:t(`journal.filter_source`)})}),(0,E.jsx)(A,{label:t(`journal.filter_ticker`),children:(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,value:o,placeholder:t(`journal.filter_ticker_hint`),"aria-label":t(`journal.filter_ticker`),autoCapitalize:`characters`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,onChange:e=>s(e.target.value)})}),(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,"aria-live":`polite`,children:d.length?t(`journal.count`,{n:d.length}):t(`journal.empty_filtered`)}),d.length?null:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn ag-jr-cta`,onClick:()=>{r(`all`),a(`all`),s(``)},children:t(`journal.clear_filters`)}),d.length?(0,E.jsx)(re,{entries:d}):null]})]})}var pe=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],z=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],me={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function B(e){let t=me[e];return t&&t!==e?`${t} ${e}`:e}var V={en:`English`,es:`Español`},he={en:`🇬🇧`,es:`🇪🇸`},H=[0,.08,.09];function U(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function ge(e,t){if(t)return U(e,t)??U(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return U(e,n.length>1&&n[1]?.length===2?n[1]:``)??U(e,e.default)}function W(e){return`claude mcp add --transport http topstocks ${e}`}function G(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function K({text:e,label:t}){let n=u(),[r,i]=(0,w.useState)(!1);return(0,w.useEffect)(()=>{if(!r)return;let e=setTimeout(()=>i(!1),2e3);return()=>clearTimeout(e)},[r]),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":t,onClick:()=>void navigator.clipboard?.writeText(e).then(()=>i(!0),()=>void 0),children:n(r?`profile.connector_copied`:`profile.connector_copy`)})}function _e({connection:e,onGone:t}){let r=u(),i=n(),[a,o]=(0,w.useState)(!1),[c,l]=(0,w.useState)(null),d=()=>{o(!0),l(null),x(`DELETE`,`/connections/${encodeURIComponent(e.id)}`).then(t,e=>{if(o(!1),e instanceof s){window.location.assign(`/auth/logout`);return}if(e instanceof p&&e.status===404){t();return}l(e instanceof p?r(`profile.connector_revoke_failed`):r(`common.offline`))})},f=G(e.used,i);return(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[e.client_name,!e.verified&&(0,E.jsx)(g,{title:r(`profile.connector_unverified_help`),children:r(`profile.connector_unverified`)}),e.can_write&&(0,E.jsx)(g,{title:r(`profile.connector_can_edit_help`),children:r(`profile.connector_can_edit`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:r(`profile.connector_returns_to`,{host:e.redirect_host})}),(0,E.jsxs)(`span`,{className:`pr-conn-meta`,children:[r(`profile.connector_since`,{date:G(e.created,i)??``}),` · `,f?r(`profile.connector_used`,{date:f}):r(`profile.connector_never_used`)]}),(0,E.jsx)(P,{message:c})]}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a,onClick:d,children:r(`profile.connector_revoke`)})]})}function ve(){let t=d(()=>e(`/connections`),[]),[n,r]=(0,w.useState)(new Set);return t.state===`loaded`?(0,E.jsx)(ye,{url:t.data.url,connections:t.data.connections.filter(e=>!n.has(e.id)),onGone:e=>r(t=>new Set(t).add(e))}):null}function ye({url:e,connections:t,onGone:n}){let r=u();return!e&&t.length===0?null:(0,E.jsxs)(k,{title:r(`profile.connector_title`),sub:r(`profile.connector_sub`),children:[e&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:r(`profile.connector_url`),help:r(`profile.connector_url_help`),children:(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:e}),(0,E.jsx)(K,{text:e,label:r(`profile.connector_copy_url`)})]})}),(0,E.jsxs)(A,{label:r(`profile.connector_how`),children:[(0,E.jsx)(O,{text:r(`profile.connector_how_app`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`profile.connector_how_code`)}),(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:W(e)}),(0,E.jsx)(K,{text:W(e),label:r(`profile.connector_copy_command`)})]})]})]}),(0,E.jsx)(A,{label:r(`profile.connector_list`),help:r(`profile.connector_logout_note`),children:t.length===0?(0,E.jsx)(`span`,{className:`pr-muted`,children:r(`profile.connector_none`)}):(0,E.jsx)(`ul`,{className:`pr-conns`,children:t.map(e=>(0,E.jsx)(_e,{connection:e,onGone:()=>n(e.id)},e.id))})})]})}function be(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function xe({email:e,onClose:t}){let n=u(),[r,i]=(0,w.useState)(``),[a,o]=(0,w.useState)(!1),[l,d]=(0,w.useState)(null),f=be(r,e),m=(0,w.useRef)(null),h=(0,w.useRef)(null);return c(m,{initial:h}),(0,w.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!a&&t()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[t,a]),(0,E.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!a&&t()},children:(0,E.jsxs)(`div`,{ref:m,className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":n(`profile.delete_title`),children:[(0,E.jsx)(`h2`,{className:`pr-modal-t`,children:n(`profile.delete_title`)}),(0,E.jsx)(O,{text:n(`profile.delete_body`)}),(0,E.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`profile.delete_confirm`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,ref:h,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:r,disabled:a,onChange:e=>i(e.target.value)})]}),(0,E.jsx)(P,{message:l}),(0,E.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a,onClick:t,children:n(`common.cancel`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!f||a,onClick:()=>{o(!0),d(null),x(`DELETE`,`/account`,{confirm:r.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;_(n)},e=>{if(o(!1),e instanceof s){_(`/auth/logout`);return}d(e instanceof p&&e.status===422?e.detail:e instanceof p?n(`profile.delete_failed`):n(`common.offline`))})},children:n(`profile.delete_button`)})]})]})})}function Se(){let e=u(),t=o(),[n,r]=(0,w.useState)(!1);return(0,E.jsxs)(A,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>r(!0),children:e(`profile.delete_open`)}),n&&(0,E.jsx)(xe,{email:t.email??``,onClose:()=>r(!1)})]})}function Ce(){let n=u(),{setParams:r}=t(),i=d(()=>e(`/chat/memories`),[]),a=i.state===`loaded`?i.data:null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`profile.memory_title`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`profile.memory_caption`)}),a&&(0,E.jsx)(`span`,{className:`pr-sum-note`,children:a.enabled?n(`profile.memory_count`,{n:a.memories.length,max:a.max}):n(`profile.memory_off`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>r({chat:`memory`}),children:n(`profile.memory_open`)})]})})}function we(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function Te(){let n=u(),{setParams:r}=t(),i=d(()=>e(`/onboarding`),[]),a=i.state===`loaded`?we(i.data.setup):null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`tour.launch`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`tour.launch_caption`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{r({tour:`1`})},children:n(`tour.launch_start`)}),a&&(0,E.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":n(`home.setup_progress`,{done:a[0],total:a[1]}),"aria-valuemin":0,"aria-valuemax":a[1],"aria-valuenow":a[0],children:[(0,E.jsx)(`div`,{className:`pr-prog-track`,children:(0,E.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(a[0]/a[1]*100)}%`}})}),(0,E.jsx)(`span`,{className:`pr-prog-n`,children:n(`home.setup_progress`,{done:a[0],total:a[1]})})]})]})})}var q=`auto`;function J({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,w.useState)(String(e)),[u,d]=(0,w.useState)(e);return u!==e&&(d(e),l(String(e))),(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}let a=Math.min(i??n,Math.max(r??n,n));a!==n&&l(String(a)),a!==e&&t(a)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,E.jsx)(`span`,{className:`pr-hint`,children:o})]})}function Ee({prefs:t,saving:n,failure:r,save:i,owner:a}){let o=u(),s=d(()=>e(`/import/last`),[]),c=d(()=>e(`/portfolio/transactions`,{limit:1}),[]),l=[q,...Object.keys(V)],f=e=>e===q?`🌐 ${o(`profile.lang_auto`)}`:`${he[e]??``} ${V[e]??e}`.trim(),p=z.includes(t.currency)?[...z]:[...z,t.currency],m=pe.filter(e=>!p.includes(e)),h=d(()=>e(`/jurisdictions`),[]),g=h.state===`loaded`?h.data:null,_=[q,...(g?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===q)return`🌐 ${o(`profile.tax_residence_auto`)}`;let t=g?.jurisdictions.find(t=>t.code===e),n=o(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=g?ge(g,t.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?o(`profile.tax_year_calendar`):o(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?o(`profile.tax_match_${y.matching}`):``,S=e=>r?.field===e?r.message:null;return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:o(`profile.ui_section`),sub:o(`profile.ui_section_sub`),children:[(0,E.jsxs)(A,{label:o(`profile.language`),help:o(`profile.language_caption`),children:[(0,E.jsx)(j,{label:o(`profile.language`),value:t.language??q,options:l,labelOf:f,disabled:n===`language`,onPick:e=>{let n=e===q?null:e;n!==t.language&&i(`language`,n)}}),(0,E.jsx)(P,{message:S(`language`)})]}),(0,E.jsxs)(A,{label:o(`profile.display_currency`),help:o(`profile.currency_caption`),children:[(0,E.jsx)(M,{value:t.currency,options:p,labelOf:B,disabled:n===`currency`,onPick:e=>e!==t.currency&&i(`currency`,e)}),m.length>0&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:o(`profile.currency_more`,{n:m.length})}),(0,E.jsx)(`div`,{children:(0,E.jsx)(M,{value:t.currency,options:m,labelOf:B,disabled:n===`currency`,onPick:e=>e!==t.currency&&i(`currency`,e)})})]}),m.length>0&&(0,E.jsx)(`span`,{className:`pr-morehint`,children:m.join(` · `)}),(0,E.jsx)(P,{message:S(`currency`)})]})]}),(0,E.jsxs)(k,{title:o(`profile.tax_section`),note:o(`profile.tax_legal_note`),children:[(0,E.jsxs)(A,{label:o(`profile.tax_residence`),help:o(`profile.tax_residence_caption`),children:[(0,E.jsx)(j,{label:o(`profile.tax_residence`),value:t.tax_residence??q,options:_,labelOf:v,disabled:n===`tax_residence`,onPick:e=>{let n=e===q?null:e;n!==t.tax_residence&&i(`tax_residence`,n)}}),(0,E.jsx)(P,{message:S(`tax_residence`)}),y?(0,E.jsxs)(`div`,{className:`pr-rules`,children:[(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_cost`)}),(0,E.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,o(`profile.tax_rule_fx`)]})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_matching`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_year`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(e=>{let r=y.code.toLowerCase();return e===`filing_status`?(0,E.jsxs)(A,{label:o(`profile.tax_filing_status`),help:o(`profile.tax_filing_status_caption_${r}`),children:[(0,E.jsx)(j,{label:o(`profile.tax_filing_status`),value:y.filing_statuses.includes(t.tax_filing_status)?t.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>o(`profile.tax_status_${e}`),disabled:n===`tax_filing_status`,onPick:e=>i(`tax_filing_status`,e)}),(0,E.jsx)(P,{message:S(`tax_filing_status`)})]},e):e===`church_tax_rate`?(0,E.jsxs)(A,{label:o(`profile.tax_church`),help:o(`profile.tax_church_caption`),children:[(0,E.jsx)(j,{label:o(`profile.tax_church`),value:String(H.includes(t.tax_church_rate)?t.tax_church_rate:0),options:H.map(String),labelOf:e=>o(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:n===`tax_church_rate`,onPick:e=>i(`tax_church_rate`,Number(e))}),(0,E.jsx)(P,{message:S(`tax_church_rate`)})]},e):e===`other_income`?(0,E.jsxs)(A,{label:o(`profile.tax_other_income`),help:o(`profile.tax_other_income_caption_${r}`),children:[(0,E.jsx)(J,{label:o(`profile.tax_other_income`),value:t.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:n===`tax_other_income`,onCommit:e=>i(`tax_other_income`,e)}),(0,E.jsx)(P,{message:S(`tax_other_income`)})]},e):e===`subnational_rate`?(0,E.jsxs)(A,{label:o(`profile.tax_subnational`),help:o(`profile.tax_subnational_caption`),children:[(0,E.jsx)(J,{label:o(`profile.tax_subnational`),value:Math.round(t.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:n===`tax_subnational_rate`,onCommit:e=>i(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,E.jsx)(P,{message:S(`tax_subnational_rate`)})]},e):(0,E.jsxs)(A,{label:o(`profile.tax_niit`),help:o(`profile.tax_niit_caption`),middle:!0,children:[(0,E.jsx)(N,{label:o(`profile.tax_niit`),checked:t.tax_niit,disabled:n===`tax_niit`,onToggle:e=>i(`tax_niit`,e)}),(0,E.jsx)(P,{message:S(`tax_niit`)})]},e)})]}),(0,E.jsxs)(k,{title:o(`profile.data_section`),children:[(0,E.jsx)(A,{label:o(`profile.export_title`),help:o(`profile.export_help`),children:c.state===`loaded`&&c.data.total>0?(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:o(`profile.export_button`)}):(0,E.jsx)(`span`,{className:`pr-muted`,children:o(`profile.export_none`)})}),a===!1&&(0,E.jsx)(Se,{})]}),(0,E.jsx)(ve,{})]}),(0,E.jsxs)(`aside`,{className:`pr-rail`,children:[(0,E.jsx)(Te,{}),(0,E.jsx)(Ce,{}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:o(`profile.summary_title`)}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.language`)}),(0,E.jsx)(`b`,{children:(f(t.language??q).split(`(`)[0]??``).trim()})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.display_currency`)}),(0,E.jsx)(`b`,{children:t.currency})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.tax_section`)}),(0,E.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(o(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:o(`common.loading`)})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.summary_last_import`)}),(0,E.jsx)(`b`,{children:s.state===`loaded`?C(s.data.imported_on)||o(`profile.summary_never`):o(`common.loading`)})]}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:o(`profile.summary_note`)})]})})]})]})}var De=new Set([`currency`,`language`]);function Oe(e){let t=i(),[n,r]=(0,w.useState)(t.prefs),[a,o]=(0,w.useState)(null),[c,l]=(0,w.useState)(null);return{prefs:n,saving:a,failure:c,save:(0,w.useCallback)((n,i)=>{o(n),l(null),x(`PATCH`,`/prefs`,{[n]:i}).then(e=>{o(null),r(e),De.has(n)&&t.reload()},r=>{if(o(null),r instanceof s){t.reload();return}l({field:n,message:T(r,e)})})},[t,e])}}var ke=`
.pr-head {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px;
  margin-bottom: 16px;
}
.pr-title { font-size: var(--ag-fs-2xl); letter-spacing: var(--ag-track-2xl); font-weight: 600; margin: 0; }
.pr-savehint { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }

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
  font-size: var(--ag-fs-sm); color: var(--ag-text-muted);
}
/* The setup progress under the tour button: capabilities on, of all of them. */
.pr-prog { display: flex; align-items: center; gap: 8px; }
.pr-prog-track {
  flex: 1; height: 4px; border-radius: var(--ag-radius-pill);
  background: var(--ag-purple-800); overflow: hidden;
}
.pr-prog-fill { height: 100%; background: var(--ag-purple-400); }
.pr-prog-n {
  font-family: var(--ag-font-mono, 'Martian Mono', ui-monospace, monospace); font-size: var(--ag-fs-2xs);
  font-weight: 500; color: var(--ag-purple-400);
}

/* ----------------------------------------------------------------- tabs */
.pr-tabs { margin: 20px 0 16px; }

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
.pr-select:focus, .pr-input:focus { outline: 2px solid var(--ag-brand-accent); }
.pr-chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
/* Free text for the assistant. Resizes vertically only: a textarea a reader
   can drag wider than its card is a layout bug they caused themselves. */
.pr-notes {
  width: 100%; min-height: 90px; resize: vertical; font: inherit;
  font-size: var(--ag-fs-sm); padding: 8px 10px;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-sm);
  background: var(--ag-surface-page); color: var(--ag-text-primary);
}
.pr-notes:focus { outline: 2px solid var(--ag-brand-accent); }
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
  .pr-input, .pr-select { min-height: 44px; }
  .pr-star, .pr-switch { min-height: 44px; min-width: 44px; }
  .pr-switch input { width: 22px; height: 22px; }
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
.pr-busy { font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }
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
  font-family: var(--ag-font-mono, 'Martian Mono', ui-monospace, monospace);
  font-size: var(--ag-fs-sm); line-height: 1.6; white-space: pre-wrap;
}

.pr-prose { font-size: var(--ag-fs-sm); line-height: 1.6; color: var(--ag-text-secondary); }
.pr-prose p { margin: 0 0 8px; }
.pr-prose ul { margin: 0; padding-left: 18px; }
.pr-prose li { margin-bottom: 6px; }
.pr-prose code {
  font-family: var(--ag-font-mono); font-size: var(--ag-fs-xs);
}

/* ------------------------------------------------- the Claude connector */
/* Something to copy, beside the button that copies it. The text wraps rather
   than scrolls: an address cut off at the card's edge is one a reader cannot
   check against what they pasted. */
.pr-copyline { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pr-code {
  flex: 1 1 16rem; min-width: 0; overflow-wrap: anywhere;
  font-family: var(--ag-font-mono); font-size: var(--ag-fs-xs);
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
  font-family: var(--ag-font-mono); font-size: var(--ag-fs-xs);
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
  font-family: var(--ag-font-mono); font-weight: 600;
  font-size: var(--ag-fs-sm);
}
.pr-resrow-n {
  flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--ag-text-secondary);
}
.pr-resrow-k { font-size: var(--ag-fs-xs); color: var(--ag-text-muted); }
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
  flex: 0 0 8.5rem; font-family: var(--ag-font-mono);
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
  color: var(--ag-text-muted);
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
  position: fixed; inset: 0; z-index: 40;
  padding: max(1rem, env(safe-area-inset-top)) max(1rem, env(safe-area-inset-right))
    max(1rem, env(safe-area-inset-bottom)) max(1rem, env(safe-area-inset-left));
  display: flex; align-items: center; justify-content: center;
  background: var(--ag-surface-page-veil);
}
.pr-modal-card {
  width: 100%; max-width: 30rem; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 14px;
  max-height: 100%; overflow-y: auto; overscroll-behavior: contain;
  border: 1px solid var(--ag-border); border-radius: var(--ag-radius-md);
  background: var(--ag-surface-card); box-shadow: var(--ag-shadow-overlay);
}
.pr-modal-t { margin: 0; font-size: var(--ag-fs-xl); letter-spacing: var(--ag-track-xl); font-weight: 600; }
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
`,Ae={analyze:`raw`},Y=2;function je({listed:t,tags:n,onAdd:r,busy:i,failure:a}){let o=u(),[s,c]=(0,w.useState)(``),[l,d]=(0,w.useState)([]),[f,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(!1),[g,_]=(0,w.useState)(null),[v,y]=(0,w.useState)(null),b=s.trim();(0,w.useEffect)(()=>{if(b.length<Y){_(null);return}let t=!0,n=window.setTimeout(()=>{e(`/search`,{q:b,limit:8}).then(e=>t&&(_(e.matches),y(null)),()=>t&&(_([]),y(o(`common.offline`))))},250);return()=>{t=!1,window.clearTimeout(n)}},[b]);let x=e=>{r({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...l.length?{tags:l}:{}}),c(``),_(null)},C=[...new Set([...n,...l])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsx)(k,{title:o(`watchlist.add_title`),sub:o(`watchlist.add_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,autoCapitalize:`off`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,"aria-label":o(`watchlist.add_title`),placeholder:o(`watchlist.add_placeholder`),value:s,onChange:e=>c(e.target.value)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups`)}),C.map(e=>(0,E.jsx)(S,{on:l.includes(e),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.add_groups`),autoComplete:`off`,enterKeyHint:`done`,placeholder:o(`watchlist.add_groups_ph`),value:f,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(d(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups_help`)}),(0,E.jsxs)(`label`,{className:`pr-switch`,children:[(0,E.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,E.jsx)(`span`,{children:o(`watchlist.add_fav`)})]}),(0,E.jsx)(P,{message:a??v}),b.length<Y?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_hint`)}):g===null?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`common.loading`)}):g.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_none`)}):(0,E.jsx)(`div`,{className:`pr-res`,children:g.map(e=>{let n=t.has(e.ticker.toUpperCase()),r=Ae[e.kind]??e.kind;return(0,E.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||i,title:o(n?`watchlist.add_listed`:`watchlist.kind_${r}`),onClick:()=>x(e),children:[(0,E.jsx)(`span`,{className:`pr-resrow-t`,children:e.ticker}),(0,E.jsx)(`span`,{className:`pr-resrow-n`,children:e.name}),(0,E.jsx)(`span`,{className:`pr-resrow-k`,children:n?o(`watchlist.add_listed`):(e.exchange??``)||o(`watchlist.kind_${r}`)})]},e.ticker)})})]})})}var X=e=>e?String(e):``;function Me(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var Ne=[`tags`,`favorites`,`flat`];function Pe(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function Fe(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Ie({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let a=u(),[o,s]=(0,w.useState)(e.name),[c,l]=(0,w.useState)(e.name),[d,f]=(0,w.useState)(``),[p,h]=(0,w.useState)(X(e.shares)),[g,_]=(0,w.useState)(X(e.cost)),[v,y]=(0,w.useState)([e.shares,e.cost]);c!==e.name&&(l(e.name),s(e.name)),(v[0]!==e.shares||v[1]!==e.cost)&&(y([e.shares,e.cost]),h(X(e.shares)),_(X(e.cost)));let b=(t,n)=>{let i=Me(n,e[t]);if(i===void 0){t===`shares`?h(X(e.shares)):_(X(e.cost));return}r(e.ticker,{[t]:i})},x=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),C=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsxs)(`div`,{className:`pr-wrow`,children:[(0,E.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":a(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,E.jsx)(m,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":a(`watchlist.col_name`),autoComplete:`off`,enterKeyHint:`done`,value:o,disabled:n,onChange:e=>s(e.target.value),onBlur:()=>o!==e.name&&r(e.ticker,{name:o}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_shares`),placeholder:a(`watchlist.col_shares`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:p,disabled:n,onChange:e=>h(e.target.value),onBlur:()=>b(`shares`,p),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_cost`),placeholder:a(`watchlist.col_cost`),title:a(`watchlist.col_cost_help`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:g,disabled:n,onChange:e=>_(e.target.value),onBlur:()=>b(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:a(`watchlist.act_remove`)}),(0,E.jsxs)(`details`,{className:`pr-wtags`,children:[(0,E.jsxs)(`summary`,{children:[a(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,E.jsxs)(`div`,{children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.col_tags_help`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[C.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,E.jsx)(S,{on:r,disabled:n,onClick:()=>x(t),children:t},t)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.col_tags`),autoComplete:`off`,enterKeyHint:`done`,placeholder:a(`watchlist.add_groups_ph`),value:d,disabled:n,onChange:e=>f(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(f(``),x(t))}})]})]})]})]})}function Z({section:e,busy:t,onRename:n,onDissolve:r}){let i=u(),[a,o]=(0,w.useState)(e.tag??``);return(0,E.jsxs)(`div`,{className:`pr-ghead`,children:[(0,E.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,E.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),autoComplete:`off`,enterKeyHint:`done`,value:a,disabled:t,onChange:e=>o(e.target.value),onKeyDown:t=>{if(t.key!==`Enter`)return;let r=a.trim();r&&r!==e.tag&&n(e.tag,r)}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!a.trim()||a.trim()===e.tag,onClick:()=>n(e.tag,a.trim()),children:i(`watchlist.group_rename_apply`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function Le({entries:e,reload:t}){let n=u(),[r,i]=(0,w.useState)(!1),[a,o]=(0,w.useState)(null),[c,l]=(0,w.useState)(``),[d,f]=(0,w.useState)([]),[p,m]=(0,w.useState)(`tags`),h=(e,r=`list`)=>{i(!0),o(null),e.then(()=>{i(!1),t()},e=>{if(i(!1),e instanceof s){t();return}o({where:r,message:T(e,n(`common.offline`))})})},g=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),_=new Set(e.map(e=>e.ticker.toUpperCase())),v=new Set(d.map(e=>e.toLowerCase())),y=e.filter(e=>Fe(e,c)&&(!v.size||e.tags.some(e=>v.has(e.toLowerCase()))));return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(je,{listed:_,tags:g,busy:r,failure:a?.where===`add`?a.message:null,onAdd:e=>h(x(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,E.jsx)(k,{title:n(`profile.empty_watchlist_title`),children:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`profile.empty_watchlist_body`)})})}):(0,E.jsx)(k,{title:n(`watchlist.list_title`),sub:n(`watchlist.list_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,autoComplete:`off`,enterKeyHint:`search`,"aria-label":n(`watchlist.filter`),placeholder:n(`watchlist.filter_ph`),value:c,onChange:e=>l(e.target.value)}),Ne.map(e=>(0,E.jsx)(S,{on:e===p,onClick:()=>m(e),children:n(`watchlist.group_${e}`)},e))]}),g.length>0&&(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.tag_filter`)}),g.map(e=>(0,E.jsx)(S,{on:v.has(e.toLowerCase()),onClick:()=>f(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,E.jsx)(P,{message:a?.where===`list`?a.message:null}),y.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`watchlist.no_match`)}):Pe(y,p,n(`watchlist.g_untagged`),{all:n(`watchlist.g_all`),favorites:n(`watchlist.g_favorites`),rest:n(`watchlist.g_rest`)}).map(e=>(0,E.jsxs)(`div`,{children:[(0,E.jsx)(Z,{section:e,busy:r,onRename:(e,t)=>h(x(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>h(x(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,E.jsx)(Ie,{entry:t,tags:g,busy:r,onEdit:(e,t)=>h(x(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>h(x(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,E.jsxs)(`div`,{className:`pr-foot`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.count`,{n:e.length})}),(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:n(`watchlist.how_open`)}),(0,E.jsx)(`div`,{children:(0,E.jsx)(O,{text:n(`watchlist.how`)})})]})]})]})})]})}function Re({onAdded:t}){let n=u(),[r,i]=(0,w.useState)(0),a=d(()=>e(`/watchlist/suggestions`),[r]),[o,s]=(0,w.useState)(!1),[c,l]=(0,w.useState)(null);if(a.state!==`loaded`||a.data.suggestions.length===0)return null;let f=a.data.suggestions;function p(){s(!0),l(null),f.reduce((e,t)=>e.then(()=>x(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{i(e=>e+1),t()}).catch(e=>l(T(e,n(`common.offline`)))).finally(()=>s(!1))}return(0,E.jsxs)(k,{title:n(`profile.focus_suggest_title`),children:[(0,E.jsx)(O,{text:n(`profile.focus_suggest_help`)}),(0,E.jsx)(`ul`,{className:`pr-examples`,children:f.map(e=>(0,E.jsxs)(`li`,{children:[(0,E.jsx)(m,{ticker:e.ticker,className:`pr-wsym`}),(0,E.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,E.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:o,onClick:p,children:n(`profile.focus_suggest_add`,{n:f.length})}),(0,E.jsx)(P,{message:c})]})}function ze({query:e}){return(0,E.jsx)(`div`,{className:`pr-main`,children:(0,E.jsx)(b,{query:e,children:(e,t)=>(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(Le,{entries:e.entries,reload:t}),(0,E.jsx)(Re,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`},{id:`journal`,label:`journal.tab`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Be(){return r()?(0,E.jsx)(a,{text:`common.sign_in`}):(0,E.jsx)(Ve,{})}function Ve(){let n=u(),r=o(),{params:i,setParams:a}=t(),s=Oe(n(`common.offline`)),c=d(()=>e(`/me`),[]),l=c.state===`loaded`?c.data:null,f=d(()=>e(`/watchlist`),[]),p=f.state===`loaded`?f.data.entries.length:0,[m,h]=(0,w.useState)(!1),g=l?.name?.trim()||``,v=i.get(`tab`)??``,y=Q.some(e=>e.id===v)?v:`prefs`,b=r.email??``;return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:ke}),(0,E.jsxs)(`header`,{className:`pr-head`,children:[(0,E.jsx)(`h1`,{className:`pr-title`,children:n(`nav.profile`)}),(0,E.jsx)(`span`,{className:`pr-savehint`,children:n(`profile.saves_instantly`)})]}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-ident`,children:[(0,E.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:l?.picture&&!m?(0,E.jsx)(`img`,{src:l.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>h(!0)}):$(b,g)}),(0,E.jsxs)(`div`,{className:`pr-ident-t`,children:[g&&g!==b&&(0,E.jsx)(`span`,{className:`pr-ident-n`,children:g}),(0,E.jsx)(`span`,{className:`pr-ident-e`,children:b})]}),(0,E.jsx)(`div`,{className:`pr-ident-r`,children:(0,E.jsx)(`span`,{className:`pr-ident-note`,children:n(`profile.account_scope`)})}),(0,E.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,onClick:e=>{e.preventDefault(),_(`/auth/logout`)},children:n(`common.log_out`)})]})}),(0,E.jsx)(ee,{className:`pr-tabs`,label:n(`nav.profile`),items:Q.map(e=>({id:e.id,label:n(e.label),count:e.id===`watch`?p:null})),active:y,onPick:e=>a({tab:e})}),y===`prefs`&&(0,E.jsx)(Ee,{...s,owner:c.state===`loaded`?!!l?.owner:null}),y===`iv`&&(0,E.jsx)(ce,{}),y===`watch`&&(0,E.jsx)(ze,{query:f}),y===`notify`&&(0,E.jsx)(se,{...s}),y===`journal`&&(0,E.jsx)(de,{})]})}export{Be as default,$ as initials};