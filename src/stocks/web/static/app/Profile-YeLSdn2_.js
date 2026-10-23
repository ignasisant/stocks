import{At as e,Bt as t,M as n,Rt as r,Vt as i,Xt as a,Yt as o,Zt as s,b as c,dn as l,g as u,h as d,hn as f,i as p,in as m,k as h,kt as g,ln as _,on as v,pn as y,rn as b,sn as x,t as S,w as C}from"./app-C7efgYeI.js";import{t as ee}from"./dates-CgZxxnD1.js";import{t as te}from"./Tabs-q--RC4Br.js";import{a as ne,i as re,n as ie,r as ae}from"./Journal-Dpj3grw2.js";var w=f(y(),1);function T(e,t){return e instanceof m?e.detail:t}var oe=3e3;function se(e){let{reload:t}=i(),[n,r]=(0,w.useState)(null),[a,o]=(0,w.useState)(null),[s,c]=(0,w.useState)(!1),[l,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(null),[p,m]=(0,w.useState)(null),h=(0,w.useCallback)(n=>n instanceof v?(t(),null):{kind:`failed`,error:T(n,e)},[t,e]);(0,w.useEffect)(()=>{let e=!0;return x(`/notify/telegram`).then(t=>e&&r(t),t=>{e&&m(h(t))}),()=>{e=!1}},[h]);let[g,y]=(0,w.useState)(()=>typeof document>`u`||!document.hidden);return(0,w.useEffect)(()=>{let e=()=>y(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,w.useEffect)(()=>{if(!a||!g)return;if(Date.now()>=a.deadline){o(null),c(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=a.deadline){o(null),c(!0);return}x(`/notify/telegram`).then(t=>{e&&(u(!1),r(t),t.linked&&o(null))},()=>e&&u(!0))},oe);return()=>{e=!1,window.clearInterval(t)}},[a,g]),{state:n,pending:a,expired:s,stalled:l,busy:d,note:p,connect:(0,w.useCallback)(()=>{f(`connect`),m(null),c(!1),_(`POST`,`/notify/telegram`).then(e=>{f(null),o({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{f(null),m(h(e))})},[h]),test:(0,w.useCallback)(()=>{f(`test`),m(null),_(`POST`,`/notify/telegram/test`).then(e=>{f(null),r(e),m({kind:`test_sent`})},n=>{if(f(null),n instanceof v){t();return}m({kind:`test_failed`,error:T(n,e)})})},[t,e]),unlink:(0,w.useCallback)(()=>{f(`unlink`),m(null),_(`DELETE`,`/notify/telegram`).then(e=>{f(null),r(e),o(null),c(!1),m({kind:`unlinked`})},e=>{f(null),m(h(e))})},[h])}}var E=b();function D({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,E.jsx)(E.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,E.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,E.jsx)(`code`,{children:e.slice(1,-1)},t):(0,E.jsx)(w.Fragment,{children:e},t))})}function O({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,E.jsx)(`ul`,{children:r.map((e,t)=>(0,E.jsx)(`li`,{children:(0,E.jsx)(D,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,E.jsx)(`p`,{children:(0,E.jsx)(D,{text:a})},t))}),i(-1),(0,E.jsx)(`div`,{className:t??`pr-prose`,children:n})}function k({title:e,sub:t,note:n,children:r}){return(0,E.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,E.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,E.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,E.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function A({label:e,help:t,middle:n,children:r}){return(0,E.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,E.jsxs)(`div`,{className:`pr-row-l`,children:[(0,E.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-row-help`,children:(0,E.jsx)(D,{text:t})})]}),(0,E.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function j({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,E.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,E.jsx)(`option`,{value:e,children:n(e)},e))})}function M({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,E.jsx)(C,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function N({checked:e,onToggle:t,label:n,disabled:r}){return(0,E.jsx)(`label`,{className:`pr-switch`,children:(0,E.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function P({message:e}){return e?(0,E.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function F({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,E.jsx)(C,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ce({prefs:e,saving:t,failure:n,save:r}){let i=a(),o=se(i(`common.offline`)),s=e=>n?.field===e?n.message:null,c=o.state?o.state.linked:e.telegram_linked,l=o.state?.configured??(e.telegram_linked?!0:null);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[l===null&&!o.note&&(0,E.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),l===!1&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),l===!0&&c&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:o.state?.username?`@${o.state.username}`:``}).trim()})]}),l===!0&&!c&&!o.pending&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:o.busy===`connect`,onClick:o.connect,children:i(`profile.tg_connect`)}),o.expired&&(0,E.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),l===!0&&!c&&o.pending&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`a`,{className:`pr-linkbtn`,href:o.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:i(`profile.tg_manual`,{bot:o.pending.bot,code:o.pending.code})})}),(0,E.jsx)(`p`,{className:`pr-busy`,children:o.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),o.note?.kind===`failed`&&(0,E.jsx)(P,{message:o.note.error}),o.note?.kind===`unlinked`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),l===!0&&c&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsxs)(A,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`test`,onClick:o.test,children:i(`profile.tg_test`)}),o.note?.kind===`test_sent`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),o.note?.kind===`test_failed`&&(0,E.jsx)(P,{message:i(`profile.tg_test_failed`,{error:o.note.error})})]}),(0,E.jsx)(A,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`unlink`,onClick:o.unlink,children:i(`profile.tg_unlink`)})})]})]}),l===!0&&c&&(0,E.jsxs)(k,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,E.jsxs)(A,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,E.jsx)(P,{message:s(`notify_digest`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,E.jsx)(P,{message:s(`notify_weekly`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,E.jsx)(P,{message:s(`notify_alerts`)})]})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,E.jsx)(O,{text:i(`profile.tg_how_body`)})]})})})]})}function le(){let e=s(async()=>{let[e,t]=await Promise.all([x(`/profile-options`),x(`/profile`)]);return{options:e,profile:t}},[]);return(0,E.jsx)(S,{query:e,skeleton:(0,E.jsx)(p,{rows:8}),children:e=>(0,E.jsx)(ue,{options:e.options,stored:e.profile})})}function ue({options:e,stored:t}){let n=a(),[r,i]=(0,w.useState)(t),[o,s]=(0,w.useState)(null),[c,l]=(0,w.useState)(null);function u(e,r){i(e),s(r),l(null),_(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>i(e)).catch(e=>{i(t),l(T(e,n(`common.offline`)))}).finally(()=>s(null))}let d=e=>t=>n(`profile.iv_${e}_${t}`);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:n(`profile.iv_how_title`),sub:n(`profile.iv_how_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_risk`),help:n(`profile.iv_risk_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_risk`),value:r.risk,options:e.risk,labelOf:d(`risk`),disabled:o===`risk`,onPick:e=>e!==r.risk&&u({...r,risk:e},`risk`)})}),(0,E.jsx)(A,{label:n(`profile.iv_horizon`),help:n(`profile.iv_horizon_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_horizon`),value:r.horizon,options:e.horizon,labelOf:d(`horizon`),disabled:o===`horizon`,onPick:e=>e!==r.horizon&&u({...r,horizon:e},`horizon`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_what_title`),sub:n(`profile.iv_what_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_focus`),help:n(`profile.iv_focus_help`),children:(0,E.jsx)(F,{values:r.focus,options:e.focus,labelOf:d(`focus`),disabled:o===`focus`,onToggle:(e,t)=>u({...r,focus:t?[...r.focus,e]:r.focus.filter(t=>t!==e)},`focus`)})}),(0,E.jsx)(A,{label:n(`profile.iv_constraints`),help:n(`profile.iv_constraints_help`),children:(0,E.jsx)(F,{values:r.constraints,options:e.constraints,labelOf:d(`constraints`),disabled:o===`constraints`,onToggle:(e,t)=>u({...r,constraints:t?[...r.constraints,e]:r.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_notes_title`),sub:n(`profile.iv_caption`),children:[(0,E.jsx)(A,{label:n(`profile.iv_notes`),help:n(`profile.iv_notes_help`),children:(0,E.jsx)(de,{value:r.notes,placeholder:n(`profile.iv_notes_ph`),label:n(`profile.iv_notes`),disabled:o===`notes`,onCommit:e=>e!==r.notes&&u({...r,notes:e},`notes`)})}),(0,E.jsx)(P,{message:c})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsxs)(k,{children:[(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`profile.iv_sum_title`)}),(0,E.jsx)(L,{label:n(`profile.iv_risk`),value:n(`profile.iv_risk_${r.risk}`)}),(0,E.jsx)(L,{label:n(`profile.iv_horizon`),value:n(`profile.iv_horizon_${r.horizon}`)}),(0,E.jsx)(L,{label:n(`profile.iv_focus`),value:I(r.focus,d(`focus`),n(`profile.iv_sum_none`))}),(0,E.jsx)(L,{label:n(`profile.iv_constraints`),value:I(r.constraints,d(`constraints`),n(`profile.iv_sum_none`))}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`profile.iv_privacy`)})]}),r.persona?(0,E.jsxs)(`details`,{className:`pr-persona`,children:[(0,E.jsx)(`summary`,{children:n(`profile.iv_persona_open`)}),(0,E.jsx)(`p`,{className:`pr-sum-note`,children:n(`profile.iv_persona_help`)}),(0,E.jsx)(`code`,{className:`pr-persona-text`,children:r.persona})]}):null]})})]})}function I(e,t,n){return e.length?e.map(t).join(`, `):n}function L({label:e,value:t}){return(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:e}),(0,E.jsx)(`b`,{children:t})]})}function de({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,w.useState)(e);return(0,w.useEffect)(()=>o(e),[e]),(0,E.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}function R(e){return e.split(`.`)[0]?.toLowerCase()??``}function fe(){let e=a(),t=s(()=>ne(),[]);return(0,E.jsxs)(k,{title:e(`journal.title`),children:[(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.intro`)})})}),(0,E.jsx)(S,{query:t,skeleton:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(p,{rows:6})}),children:t=>t.entries.length?(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(pe,{record:t.record}),(0,E.jsx)(me,{entries:t.entries}),(0,E.jsx)(A,{label:e(`journal.export`),help:e(`journal.export_help`),children:(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/journal.md`,children:e(`journal.export_button`)})})]}):(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.empty`)})}),(0,E.jsx)(g,{page:`review`,className:`pr-btn ag-jr-cta`,children:e(`tour.review_cta`)})]})})]})}function pe({record:e}){let t=a();return e.proposed?(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsxs)(`p`,{className:`pr-hint`,children:[(0,E.jsx)(D,{text:t(`journal.record`,{n:e.proposed,followed:e.followed,declined:e.declined,lapsed:e.lapsed,open:e.open})}),e.marked?(0,E.jsxs)(E.Fragment,{children:[` `,(0,E.jsx)(D,{text:t(`journal.record_marked`,{n:e.marked,way:e.its_way??0})})]}):null]})}):null}function me({entries:e}){let t=a(),[n,r]=(0,w.useState)(`all`),[i,o]=(0,w.useState)(`all`),[s,c]=(0,w.useState)(``),l=(0,w.useMemo)(()=>{let t=R(s.trim());return e.filter(e=>(i===`all`||e.source===i)&&(!t||R(e.ticker).startsWith(t)))},[e,i,s]),u=(0,w.useMemo)(()=>{let e={};for(let t of l)e[t.state]=(e[t.state]??0)+1;return e},[l]),d=n===`all`?l:l.filter(e=>e.state===n),f=[`all`,...re],p=[`all`,...ae];return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:t(`journal.filter_state`),children:(0,E.jsx)(M,{value:n,options:f,labelOf:e=>e===`all`?`${t(`journal.all_states`)} · ${l.length}`:`${t(`journal.state_${e}`)} · ${u[e]??0}`,onPick:r})}),(0,E.jsx)(A,{label:t(`journal.filter_source`),children:(0,E.jsx)(j,{value:i,options:p,labelOf:e=>t(e===`all`?`journal.all_sources`:`journal.source_${e}`),onPick:o,label:t(`journal.filter_source`)})}),(0,E.jsx)(A,{label:t(`journal.filter_ticker`),children:(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,value:s,placeholder:t(`journal.filter_ticker_hint`),"aria-label":t(`journal.filter_ticker`),autoCapitalize:`characters`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,onChange:e=>c(e.target.value)})}),(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,"aria-live":`polite`,children:d.length?t(`journal.count`,{n:d.length}):t(`journal.empty_filtered`)}),d.length?null:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn ag-jr-cta`,onClick:()=>{r(`all`),o(`all`),c(``)},children:t(`journal.clear_filters`)}),d.length?(0,E.jsx)(ie,{entries:d}):null]})]})}var he=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],z=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ge={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function B(e){let t=ge[e];return t&&t!==e?`${t} ${e}`:e}var V={en:`English`,es:`Español`},_e={en:`🇬🇧`,es:`🇪🇸`},H=[0,.08,.09];function U(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function ve(e,t){if(t)return U(e,t)??U(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return U(e,n.length>1&&n[1]?.length===2?n[1]:``)??U(e,e.default)}function W(e){return`claude mcp add --transport http topstocks ${e}`}function G(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function K({text:e,label:t}){let n=a(),[r,i]=(0,w.useState)(!1);return(0,w.useEffect)(()=>{if(!r)return;let e=setTimeout(()=>i(!1),2e3);return()=>clearTimeout(e)},[r]),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":t,onClick:()=>void navigator.clipboard?.writeText(e).then(()=>i(!0),()=>void 0),children:n(r?`profile.connector_copied`:`profile.connector_copy`)})}function ye({connection:e,onGone:t}){let n=a(),r=o(),[i,s]=(0,w.useState)(!1),[c,u]=(0,w.useState)(null),f=()=>{s(!0),u(null),_(`DELETE`,`/connections/${encodeURIComponent(e.id)}`).then(t,e=>{if(s(!1),e instanceof v){l();return}if(e instanceof m&&e.status===404){t();return}u(e instanceof m?n(`profile.connector_revoke_failed`):n(`common.offline`))})},p=G(e.used,r);return(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[e.client_name,!e.verified&&(0,E.jsx)(d,{title:n(`profile.connector_unverified_help`),children:n(`profile.connector_unverified`)}),e.can_write&&(0,E.jsx)(d,{title:n(`profile.connector_can_edit_help`),children:n(`profile.connector_can_edit`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:n(`profile.connector_returns_to`,{host:e.redirect_host})}),(0,E.jsxs)(`span`,{className:`pr-conn-meta`,children:[n(`profile.connector_since`,{date:G(e.created,r)??``}),` · `,p?n(`profile.connector_used`,{date:p}):n(`profile.connector_never_used`)]}),(0,E.jsx)(P,{message:c})]}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:i,onClick:f,children:n(`profile.connector_revoke`)})]})}function q(){let e=s(()=>x(`/connections`),[]),[t,n]=(0,w.useState)(new Set);return e.state===`loaded`?(0,E.jsx)(be,{url:e.data.url,connections:e.data.connections.filter(e=>!t.has(e.id)),onGone:e=>n(t=>new Set(t).add(e))}):null}function be({url:e,connections:t,onGone:n}){let r=a();return!e&&t.length===0?null:(0,E.jsxs)(k,{title:r(`profile.connector_title`),sub:r(`profile.connector_sub`),children:[e&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:r(`profile.connector_url`),help:r(`profile.connector_url_help`),children:(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:e}),(0,E.jsx)(K,{text:e,label:r(`profile.connector_copy_url`)})]})}),(0,E.jsxs)(A,{label:r(`profile.connector_how`),children:[(0,E.jsx)(O,{text:r(`profile.connector_how_app`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`profile.connector_how_code`)}),(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:W(e)}),(0,E.jsx)(K,{text:W(e),label:r(`profile.connector_copy_command`)})]})]})]}),(0,E.jsx)(A,{label:r(`profile.connector_list`),help:r(`profile.connector_logout_note`),children:t.length===0?(0,E.jsx)(`span`,{className:`pr-muted`,children:r(`profile.connector_none`)}):(0,E.jsx)(`ul`,{className:`pr-conns`,children:t.map(e=>(0,E.jsx)(ye,{connection:e,onGone:()=>n(e.id)},e.id))})})]})}function xe(e,t,n=Date.now()/1e3){let r=Math.max(0,n-e),i=new Intl.RelativeTimeFormat(t,{numeric:`auto`});return r<600?i.format(0,`second`):r<7200?i.format(-Math.round(r/60),`minute`):r<172800?i.format(-Math.round(r/3600),`hour`):i.format(-Math.round(r/86400),`day`)}function Se({rows:e,busy:t,failure:n,onEnd:r,onEndOthers:i}){let s=a(),c=o(),l=e.filter(e=>!e.current);return(0,E.jsxs)(A,{label:s(`profile.sessions_title`),help:s(`profile.sessions_help`),children:[(0,E.jsx)(`ul`,{className:`pr-conns`,children:e.map(e=>(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[e.device||s(`profile.sessions_unknown`),e.current&&(0,E.jsx)(d,{children:s(`profile.sessions_this`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:s(`profile.sessions_active`,{when:xe(e.seen,c)})})]}),!e.current&&(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t!==null,onClick:()=>r(e.id),children:s(`profile.sessions_end`)})]},e.id))}),l.length>0&&(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t!==null,onClick:i,children:s(`profile.sessions_end_others`)}),(0,E.jsx)(P,{message:n})]})}function Ce(){let e=a(),t=s(()=>x(`/account/sessions`),[]),[n,r]=(0,w.useState)(null),[i,o]=(0,w.useState)(null),[c,u]=(0,w.useState)(new Set);if(t.state!==`loaded`)return null;let d=t.data.sessions.filter(e=>!c.has(e.id));if(d.length===0)return null;let f=(t,n,i)=>{r(t),o(null),n.then(()=>{r(null),u(e=>{let t=new Set(e);return i(t),t})},n=>{if(r(null),n instanceof v){l();return}if(n instanceof m&&n.status===404){u(e=>new Set(e).add(t));return}o(n instanceof m?e(`profile.sessions_failed`):e(`common.offline`))})};return(0,E.jsx)(Se,{rows:d,busy:n,failure:i,onEnd:e=>f(e,_(`DELETE`,`/account/sessions/${encodeURIComponent(e)}`),t=>t.add(e)),onEndOthers:()=>f(`others`,_(`DELETE`,`/account/sessions/others`),e=>d.filter(e=>!e.current).forEach(t=>e.add(t.id)))})}function we(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function Te({email:e,onClose:t}){let n=a(),[r,i]=(0,w.useState)(``),[o,s]=(0,w.useState)(!1),[c,u]=(0,w.useState)(null),d=we(r,e),f=(0,w.useRef)(null),p=(0,w.useRef)(null);return h(f,{initial:p}),(0,w.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!o&&t()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[t,o]),(0,E.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!o&&t()},children:(0,E.jsxs)(`div`,{ref:f,className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":n(`profile.delete_title`),children:[(0,E.jsx)(`h2`,{className:`pr-modal-t`,children:n(`profile.delete_title`)}),(0,E.jsx)(O,{text:n(`profile.delete_body`)}),(0,E.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`profile.delete_confirm`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,ref:p,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:r,disabled:o,onChange:e=>i(e.target.value)})]}),(0,E.jsx)(P,{message:c}),(0,E.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o,onClick:t,children:n(`common.cancel`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!d||o,onClick:()=>{s(!0),u(null),_(`DELETE`,`/account`,{confirm:r.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;l(n)},e=>{if(s(!1),e instanceof v){l();return}u(e instanceof m&&e.status===422?e.detail:e instanceof m?n(`profile.delete_failed`):n(`common.offline`))})},children:n(`profile.delete_button`)})]})]})})}function Ee(){let e=a(),t=r(),[n,i]=(0,w.useState)(!1);return(0,E.jsxs)(A,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>i(!0),children:e(`profile.delete_open`)}),n&&(0,E.jsx)(Te,{email:t.email??``,onClose:()=>i(!1)})]})}function De(){let t=a(),{setParams:n}=e(),r=s(()=>x(`/chat/memories`),[]),i=r.state===`loaded`?r.data:null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:t(`profile.memory_title`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:t(`profile.memory_caption`)}),i&&(0,E.jsx)(`span`,{className:`pr-sum-note`,children:i.enabled?t(`profile.memory_count`,{n:i.memories.length,max:i.max}):t(`profile.memory_off`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>n({chat:`memory`}),children:t(`profile.memory_open`)})]})})}function Oe(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function ke(){let t=a(),{setParams:n}=e(),r=s(()=>x(`/onboarding`),[]),i=r.state===`loaded`?Oe(r.data.setup):null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:t(`tour.launch`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:t(`tour.launch_caption`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{n({tour:`1`})},children:t(`tour.launch_start`)}),i&&(0,E.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":t(`home.setup_progress`,{done:i[0],total:i[1]}),"aria-valuemin":0,"aria-valuemax":i[1],"aria-valuenow":i[0],children:[(0,E.jsx)(`div`,{className:`pr-prog-track`,children:(0,E.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(i[0]/i[1]*100)}%`}})}),(0,E.jsx)(`span`,{className:`pr-prog-n`,children:t(`home.setup_progress`,{done:i[0],total:i[1]})})]})]})})}var J=`auto`;function Y({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,w.useState)(String(e)),[u,d]=(0,w.useState)(e);return u!==e&&(d(e),l(String(e))),(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}let a=Math.min(i??n,Math.max(r??n,n));a!==n&&l(String(a)),a!==e&&t(a)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,E.jsx)(`span`,{className:`pr-hint`,children:o})]})}function Ae({prefs:e,saving:t,failure:n,save:r,owner:i}){let o=a(),c=s(()=>x(`/import/last`),[]),l=s(()=>x(`/portfolio/transactions`,{limit:1}),[]),u=[J,...Object.keys(V)],d=e=>e===J?`🌐 ${o(`profile.lang_auto`)}`:`${_e[e]??``} ${V[e]??e}`.trim(),f=z.includes(e.currency)?[...z]:[...z,e.currency],p=he.filter(e=>!f.includes(e)),m=s(()=>x(`/jurisdictions`),[]),h=m.state===`loaded`?m.data:null,g=[J,...(h?.jurisdictions??[]).map(e=>e.code)],_=e=>{if(e===J)return`🌐 ${o(`profile.tax_residence_auto`)}`;let t=h?.jurisdictions.find(t=>t.code===e),n=o(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},v=h?ve(h,e.tax_residence):null,y=v?v.year_start[0]===1&&v.year_start[1]===1?o(`profile.tax_year_calendar`):o(`profile.tax_year_from`,{day:v.year_start[1],month:v.year_start[0]}):``,b=v?o(`profile.tax_match_${v.matching}`):``,S=e=>n?.field===e?n.message:null;return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:o(`profile.ui_section`),sub:o(`profile.ui_section_sub`),children:[(0,E.jsxs)(A,{label:o(`profile.language`),help:o(`profile.language_caption`),children:[(0,E.jsx)(j,{label:o(`profile.language`),value:e.language??J,options:u,labelOf:d,disabled:t===`language`,onPick:t=>{let n=t===J?null:t;n!==e.language&&r(`language`,n)}}),(0,E.jsx)(P,{message:S(`language`)})]}),(0,E.jsxs)(A,{label:o(`profile.display_currency`),help:o(`profile.currency_caption`),children:[(0,E.jsx)(M,{value:e.currency,options:f,labelOf:B,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)}),p.length>0&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:o(`profile.currency_more`,{n:p.length})}),(0,E.jsx)(`div`,{children:(0,E.jsx)(M,{value:e.currency,options:p,labelOf:B,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)})})]}),p.length>0&&(0,E.jsx)(`span`,{className:`pr-morehint`,children:p.join(` · `)}),(0,E.jsx)(P,{message:S(`currency`)})]})]}),(0,E.jsxs)(k,{title:o(`profile.tax_section`),note:o(`profile.tax_legal_note`),children:[(0,E.jsxs)(A,{label:o(`profile.tax_residence`),help:o(`profile.tax_residence_caption`),children:[(0,E.jsx)(j,{label:o(`profile.tax_residence`),value:e.tax_residence??J,options:g,labelOf:_,disabled:t===`tax_residence`,onPick:t=>{let n=t===J?null:t;n!==e.tax_residence&&r(`tax_residence`,n)}}),(0,E.jsx)(P,{message:S(`tax_residence`)}),v?(0,E.jsxs)(`div`,{className:`pr-rules`,children:[(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_cost`)}),(0,E.jsxs)(`span`,{className:`pr-rule-v`,children:[v.currency,` · `,o(`profile.tax_rule_fx`)]})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_matching`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:b})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:o(`profile.tax_rule_year`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:y})]})]}):null]}),(v?.settings_fields??[]).map(n=>{let i=v.code.toLowerCase();return n===`filing_status`?(0,E.jsxs)(A,{label:o(`profile.tax_filing_status`),help:o(`profile.tax_filing_status_caption_${i}`),children:[(0,E.jsx)(j,{label:o(`profile.tax_filing_status`),value:v.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:v.filing_statuses[0]??`single`,options:v.filing_statuses,labelOf:e=>o(`profile.tax_status_${e}`),disabled:t===`tax_filing_status`,onPick:e=>r(`tax_filing_status`,e)}),(0,E.jsx)(P,{message:S(`tax_filing_status`)})]},n):n===`church_tax_rate`?(0,E.jsxs)(A,{label:o(`profile.tax_church`),help:o(`profile.tax_church_caption`),children:[(0,E.jsx)(j,{label:o(`profile.tax_church`),value:String(H.includes(e.tax_church_rate)?e.tax_church_rate:0),options:H.map(String),labelOf:e=>o(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:t===`tax_church_rate`,onPick:e=>r(`tax_church_rate`,Number(e))}),(0,E.jsx)(P,{message:S(`tax_church_rate`)})]},n):n===`other_income`?(0,E.jsxs)(A,{label:o(`profile.tax_other_income`),help:o(`profile.tax_other_income_caption_${i}`),children:[(0,E.jsx)(Y,{label:o(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:v.currency,disabled:t===`tax_other_income`,onCommit:e=>r(`tax_other_income`,e)}),(0,E.jsx)(P,{message:S(`tax_other_income`)})]},n):n===`subnational_rate`?(0,E.jsxs)(A,{label:o(`profile.tax_subnational`),help:o(`profile.tax_subnational_caption`),children:[(0,E.jsx)(Y,{label:o(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:t===`tax_subnational_rate`,onCommit:e=>r(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,E.jsx)(P,{message:S(`tax_subnational_rate`)})]},n):(0,E.jsxs)(A,{label:o(`profile.tax_niit`),help:o(`profile.tax_niit_caption`),middle:!0,children:[(0,E.jsx)(N,{label:o(`profile.tax_niit`),checked:e.tax_niit,disabled:t===`tax_niit`,onToggle:e=>r(`tax_niit`,e)}),(0,E.jsx)(P,{message:S(`tax_niit`)})]},n)})]}),(0,E.jsxs)(k,{title:o(`profile.data_section`),children:[(0,E.jsx)(A,{label:o(`profile.export_title`),help:o(`profile.export_help`),children:l.state===`loaded`&&l.data.total>0?(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:o(`profile.export_button`)}):(0,E.jsx)(`span`,{className:`pr-muted`,children:o(`profile.export_none`)})}),(0,E.jsx)(A,{label:o(`profile.export_all_title`),help:o(`profile.export_all_help`),children:(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/account/export`,children:o(`profile.export_all_button`)})}),(0,E.jsx)(Ce,{}),i===!1&&(0,E.jsx)(Ee,{})]}),(0,E.jsx)(q,{})]}),(0,E.jsxs)(`aside`,{className:`pr-rail`,children:[(0,E.jsx)(ke,{}),(0,E.jsx)(De,{}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:o(`profile.summary_title`)}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.language`)}),(0,E.jsx)(`b`,{children:(d(e.language??J).split(`(`)[0]??``).trim()})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.display_currency`)}),(0,E.jsx)(`b`,{children:e.currency})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.tax_section`)}),(0,E.jsx)(`b`,{children:v?`${v.flag?`${v.flag} `:``}${(o(`profile.tax_residence_${v.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${b}`:o(`common.loading`)})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:o(`profile.summary_last_import`)}),(0,E.jsx)(`b`,{children:c.state===`loaded`?ee(c.data.imported_on)||o(`profile.summary_never`):o(`common.loading`)})]}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:o(`profile.summary_note`)})]})})]})]})}var je=new Set([`currency`,`language`]);function Me(e){let t=i(),[n,r]=(0,w.useState)(t.prefs),[a,o]=(0,w.useState)(null),[s,c]=(0,w.useState)(null);return{prefs:n,saving:a,failure:s,save:(0,w.useCallback)((n,i)=>{o(n),c(null),_(`PATCH`,`/prefs`,{[n]:i}).then(e=>{o(null),r(e),je.has(n)&&t.reload()},r=>{if(o(null),r instanceof v){t.reload();return}c({field:n,message:T(r,e)})})},[t,e])}}var Ne=`
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
`,Pe={analyze:`raw`},X=2;function Fe({listed:e,tags:t,onAdd:n,busy:r,failure:i}){let o=a(),[s,l]=(0,w.useState)(``),[u,d]=(0,w.useState)([]),[f,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(!1),[g,_]=(0,w.useState)(null),[v,y]=(0,w.useState)(null),b=s.trim();(0,w.useEffect)(()=>{if(b.length<X){_(null);return}let e=!0,t=window.setTimeout(()=>{c(b,{limit:8}).then(t=>e&&(_(t.matches),y(null)),()=>e&&(_([]),y(o(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[b]);let x=e=>{n({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...u.length?{tags:u}:{}}),l(``),_(null)},S=[...new Set([...t,...u])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsx)(k,{title:o(`watchlist.add_title`),sub:o(`watchlist.add_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,autoCapitalize:`off`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,"aria-label":o(`watchlist.add_title`),placeholder:o(`watchlist.add_placeholder`),value:s,onChange:e=>l(e.target.value)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups`)}),S.map(e=>(0,E.jsx)(C,{on:u.includes(e),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.add_groups`),autoComplete:`off`,enterKeyHint:`done`,placeholder:o(`watchlist.add_groups_ph`),value:f,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(d(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.add_groups_help`)}),(0,E.jsxs)(`label`,{className:`pr-switch`,children:[(0,E.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,E.jsx)(`span`,{children:o(`watchlist.add_fav`)})]}),(0,E.jsx)(P,{message:i??v}),b.length<X?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_hint`)}):g===null?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`common.loading`)}):g.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:o(`watchlist.add_none`)}):(0,E.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),i=Pe[t.kind]??t.kind;return(0,E.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||r,title:o(n?`watchlist.add_listed`:`watchlist.kind_${i}`),onClick:()=>x(t),children:[(0,E.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,E.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,E.jsx)(`span`,{className:`pr-resrow-k`,children:n?o(`watchlist.add_listed`):(t.exchange??``)||o(`watchlist.kind_${i}`)})]},t.ticker)})})]})})}var Z=e=>e?String(e):``;function Ie(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var Le=[`tags`,`favorites`,`flat`];function Re(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function ze(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Be({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let o=a(),[s,c]=(0,w.useState)(e.name),[l,d]=(0,w.useState)(e.name),[f,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(Z(e.shares)),[g,_]=(0,w.useState)(Z(e.cost)),[v,y]=(0,w.useState)([e.shares,e.cost]);l!==e.name&&(d(e.name),c(e.name)),(v[0]!==e.shares||v[1]!==e.cost)&&(y([e.shares,e.cost]),h(Z(e.shares)),_(Z(e.cost)));let b=(t,n)=>{let i=Ie(n,e[t]);if(i===void 0){t===`shares`?h(Z(e.shares)):_(Z(e.cost));return}r(e.ticker,{[t]:i})},x=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),S=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsxs)(`div`,{className:`pr-wrow`,children:[(0,E.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":o(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,E.jsx)(u,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":o(`watchlist.col_name`),autoComplete:`off`,enterKeyHint:`done`,value:s,disabled:n,onChange:e=>c(e.target.value),onBlur:()=>s!==e.name&&r(e.ticker,{name:s}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_shares`),placeholder:o(`watchlist.col_shares`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:m,disabled:n,onChange:e=>h(e.target.value),onBlur:()=>b(`shares`,m),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_cost`),placeholder:o(`watchlist.col_cost`),title:o(`watchlist.col_cost_help`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:g,disabled:n,onChange:e=>_(e.target.value),onBlur:()=>b(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:o(`watchlist.act_remove`)}),(0,E.jsxs)(`details`,{className:`pr-wtags`,children:[(0,E.jsxs)(`summary`,{children:[o(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,E.jsxs)(`div`,{children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.col_tags_help`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[S.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,E.jsx)(C,{on:r,disabled:n,onClick:()=>x(t),children:t},t)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.col_tags`),autoComplete:`off`,enterKeyHint:`done`,placeholder:o(`watchlist.add_groups_ph`),value:f,disabled:n,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(p(``),x(t))}})]})]})]})]})}function Ve({section:e,busy:t,onRename:n,onDissolve:r}){let i=a(),[o,s]=(0,w.useState)(e.tag??``);return(0,E.jsxs)(`div`,{className:`pr-ghead`,children:[(0,E.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,E.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),autoComplete:`off`,enterKeyHint:`done`,value:o,disabled:t,onChange:e=>s(e.target.value),onKeyDown:t=>{if(t.key!==`Enter`)return;let r=o.trim();r&&r!==e.tag&&n(e.tag,r)}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!o.trim()||o.trim()===e.tag,onClick:()=>n(e.tag,o.trim()),children:i(`watchlist.group_rename_apply`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function He({entries:e,reload:t}){let n=a(),[r,i]=(0,w.useState)(!1),[o,s]=(0,w.useState)(null),[c,l]=(0,w.useState)(``),[u,d]=(0,w.useState)([]),[f,p]=(0,w.useState)(`tags`),m=(e,r=`list`)=>{i(!0),s(null),e.then(()=>{i(!1),t()},e=>{if(i(!1),e instanceof v){t();return}s({where:r,message:T(e,n(`common.offline`))})})},h=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),g=new Set(e.map(e=>e.ticker.toUpperCase())),y=new Set(u.map(e=>e.toLowerCase())),b=e.filter(e=>ze(e,c)&&(!y.size||e.tags.some(e=>y.has(e.toLowerCase()))));return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(Fe,{listed:g,tags:h,busy:r,failure:o?.where===`add`?o.message:null,onAdd:e=>m(_(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,E.jsx)(k,{title:n(`profile.empty_watchlist_title`),children:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`profile.empty_watchlist_body`)})})}):(0,E.jsx)(k,{title:n(`watchlist.list_title`),sub:n(`watchlist.list_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,autoComplete:`off`,enterKeyHint:`search`,"aria-label":n(`watchlist.filter`),placeholder:n(`watchlist.filter_ph`),value:c,onChange:e=>l(e.target.value)}),Le.map(e=>(0,E.jsx)(C,{on:e===f,onClick:()=>p(e),children:n(`watchlist.group_${e}`)},e))]}),h.length>0&&(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.tag_filter`)}),h.map(e=>(0,E.jsx)(C,{on:y.has(e.toLowerCase()),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,E.jsx)(P,{message:o?.where===`list`?o.message:null}),b.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`watchlist.no_match`)}):Re(b,f,n(`watchlist.g_untagged`),{all:n(`watchlist.g_all`),favorites:n(`watchlist.g_favorites`),rest:n(`watchlist.g_rest`)}).map(e=>(0,E.jsxs)(`div`,{children:[(0,E.jsx)(Ve,{section:e,busy:r,onRename:(e,t)=>m(_(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>m(_(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,E.jsx)(Be,{entry:t,tags:h,busy:r,onEdit:(e,t)=>m(_(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>m(_(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,E.jsxs)(`div`,{className:`pr-foot`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.count`,{n:e.length})}),(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:n(`watchlist.how_open`)}),(0,E.jsx)(`div`,{children:(0,E.jsx)(O,{text:n(`watchlist.how`)})})]})]})]})})]})}function Ue({onAdded:e}){let t=a(),[n,r]=(0,w.useState)(0),i=s(()=>x(`/watchlist/suggestions`),[n]),[o,c]=(0,w.useState)(!1),[l,d]=(0,w.useState)(null);if(i.state!==`loaded`||i.data.suggestions.length===0)return null;let f=i.data.suggestions;function p(){c(!0),d(null),f.reduce((e,t)=>e.then(()=>_(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{r(e=>e+1),e()}).catch(e=>d(T(e,t(`common.offline`)))).finally(()=>c(!1))}return(0,E.jsxs)(k,{title:t(`profile.focus_suggest_title`),children:[(0,E.jsx)(O,{text:t(`profile.focus_suggest_help`)}),(0,E.jsx)(`ul`,{className:`pr-examples`,children:f.map(e=>(0,E.jsxs)(`li`,{children:[(0,E.jsx)(u,{ticker:e.ticker,className:`pr-wsym`}),(0,E.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,E.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:o,onClick:p,children:t(`profile.focus_suggest_add`,{n:f.length})}),(0,E.jsx)(P,{message:l})]})}function We({query:e}){return(0,E.jsx)(`div`,{className:`pr-main`,children:(0,E.jsx)(S,{query:e,children:(e,t)=>(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(He,{entries:e.entries,reload:t}),(0,E.jsx)(Ue,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`},{id:`journal`,label:`journal.tab`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Ge(){return t()?(0,E.jsx)(n,{text:`common.sign_in`}):(0,E.jsx)(Ke,{})}function Ke(){let t=a(),n=r(),{params:i,setParams:o}=e(),c=Me(t(`common.offline`)),u=s(()=>x(`/me`),[]),d=u.state===`loaded`?u.data:null,f=s(()=>x(`/watchlist`),[]),p=f.state===`loaded`?f.data.entries.length:0,[m,h]=(0,w.useState)(!1),g=d?.name?.trim()||``,_=i.get(`tab`)??``,v=Q.some(e=>e.id===_)?_:`prefs`,y=n.email??``;return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:Ne}),(0,E.jsxs)(`header`,{className:`pr-head`,children:[(0,E.jsx)(`h1`,{className:`pr-title`,children:t(`nav.profile`)}),(0,E.jsx)(`span`,{className:`pr-savehint`,children:t(`profile.saves_instantly`)})]}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-ident`,children:[(0,E.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:d?.picture&&!m?(0,E.jsx)(`img`,{src:d.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>h(!0)}):$(y,g)}),(0,E.jsxs)(`div`,{className:`pr-ident-t`,children:[g&&g!==y&&(0,E.jsx)(`span`,{className:`pr-ident-n`,children:g}),(0,E.jsx)(`span`,{className:`pr-ident-e`,children:y})]}),(0,E.jsx)(`div`,{className:`pr-ident-r`,children:(0,E.jsx)(`span`,{className:`pr-ident-note`,children:t(`profile.account_scope`)})}),(0,E.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,onClick:e=>{e.preventDefault(),l()},children:t(`common.log_out`)})]})}),(0,E.jsx)(te,{className:`pr-tabs`,label:t(`nav.profile`),items:Q.map(e=>({id:e.id,label:t(e.label),count:e.id===`watch`?p:null})),active:v,onPick:e=>o({tab:e})}),v===`prefs`&&(0,E.jsx)(Ae,{...c,owner:u.state===`loaded`?!!d?.owner:null}),v===`iv`&&(0,E.jsx)(le,{}),v===`watch`&&(0,E.jsx)(We,{query:f}),v===`notify`&&(0,E.jsx)(ce,{...c}),v===`journal`&&(0,E.jsx)(fe,{})]})}export{Ge as default,$ as initials};