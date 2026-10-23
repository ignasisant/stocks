import{Bt as e,Jt as t,Lt as n,O as r,Ot as i,Xt as a,Yt as o,an as s,b as c,cn as l,fn as u,g as d,h as f,i as p,j as m,kt as h,mn as g,nn as _,on as v,rn as y,t as b,un as x,w as S,zt as C}from"./app-CBqfN61u.js";import{t as ee}from"./dates-C2ZgjvJd.js";import{t as te}from"./Tabs-aszwrtu0.js";import{a as ne,i as re,n as ie,r as ae}from"./Journal-tLpKXbo7.js";var w=g(u(),1);function T(e,t){return e instanceof y?e.detail:t}var oe=3e3;function se(t){let{reload:n}=e(),[r,i]=(0,w.useState)(null),[a,o]=(0,w.useState)(null),[c,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(!1),[p,m]=(0,w.useState)(null),[h,g]=(0,w.useState)(null),_=(0,w.useCallback)(e=>e instanceof s?(n(),null):{kind:`failed`,error:T(e,t)},[n,t]);(0,w.useEffect)(()=>{let e=!0;return v(`/notify/telegram`).then(t=>e&&i(t),t=>{e&&g(_(t))}),()=>{e=!1}},[_]);let[y,b]=(0,w.useState)(()=>typeof document>`u`||!document.hidden);return(0,w.useEffect)(()=>{let e=()=>b(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,w.useEffect)(()=>{if(!a||!y)return;if(Date.now()>=a.deadline){o(null),u(!0);return}let e=!0,t=window.setInterval(()=>{if(Date.now()>=a.deadline){o(null),u(!0);return}v(`/notify/telegram`).then(t=>{e&&(f(!1),i(t),t.linked&&o(null))},()=>e&&f(!0))},oe);return()=>{e=!1,window.clearInterval(t)}},[a,y]),{state:r,pending:a,expired:c,stalled:d,busy:p,note:h,connect:(0,w.useCallback)(()=>{m(`connect`),g(null),u(!1),l(`POST`,`/notify/telegram`).then(e=>{m(null),o({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{m(null),g(_(e))})},[_]),test:(0,w.useCallback)(()=>{m(`test`),g(null),l(`POST`,`/notify/telegram/test`).then(e=>{m(null),i(e),g({kind:`test_sent`})},e=>{if(m(null),e instanceof s){n();return}g({kind:`test_failed`,error:T(e,t)})})},[n,t]),unlink:(0,w.useCallback)(()=>{m(`unlink`),g(null),l(`DELETE`,`/notify/telegram`).then(e=>{m(null),i(e),o(null),u(!1),g({kind:`unlinked`})},e=>{m(null),g(_(e))})},[_])}}var E=_();function D({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,E.jsx)(E.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,E.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,E.jsx)(`code`,{children:e.slice(1,-1)},t):(0,E.jsx)(w.Fragment,{children:e},t))})}function O({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,E.jsx)(`ul`,{children:r.map((e,t)=>(0,E.jsx)(`li`,{children:(0,E.jsx)(D,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,E.jsx)(`p`,{children:(0,E.jsx)(D,{text:a})},t))}),i(-1),(0,E.jsx)(`div`,{className:t??`pr-prose`,children:n})}function k({title:e,sub:t,note:n,children:r}){return(0,E.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,E.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,E.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,E.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function A({label:e,help:t,middle:n,children:r}){return(0,E.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,E.jsxs)(`div`,{className:`pr-row-l`,children:[(0,E.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-row-help`,children:(0,E.jsx)(D,{text:t})})]}),(0,E.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function j({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,E.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,E.jsx)(`option`,{value:e,children:n(e)},e))})}function M({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,E.jsx)(S,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function N({checked:e,onToggle:t,label:n,disabled:r}){return(0,E.jsx)(`label`,{className:`pr-switch`,children:(0,E.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function P({message:e}){return e?(0,E.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function F({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,E.jsx)(S,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ce({prefs:e,saving:t,failure:n,save:r}){let i=o(),a=se(i(`common.offline`)),s=e=>n?.field===e?n.message:null,c=a.state?a.state.linked:e.telegram_linked,l=a.state?.configured??(e.telegram_linked?!0:null);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:i(`profile.notify_channel_title`),sub:i(`profile.notify_channel_sub`),children:[(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[l===null&&!a.note&&(0,E.jsx)(`p`,{className:`pr-busy`,children:i(`common.loading`)}),l===!1&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_not_configured`)}),l===!0&&c&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-badge`,children:i(`profile.notify_connected`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`profile.tg_linked_as`,{handle:a.state?.username?`@${a.state.username}`:``}).trim()})]}),l===!0&&!c&&!a.pending&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:a.busy===`connect`,onClick:a.connect,children:i(`profile.tg_connect`)}),a.expired&&(0,E.jsx)(`span`,{className:`pr-warn`,children:i(`profile.tg_expired`)})]}),l===!0&&!c&&a.pending&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`a`,{className:`pr-linkbtn`,href:a.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:i(`profile.tg_open`)}),(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:i(`profile.tg_manual`,{bot:a.pending.bot,code:a.pending.code})})}),(0,E.jsx)(`p`,{className:`pr-busy`,children:a.stalled?i(`profile.tg_poll_error`):i(`profile.tg_waiting`)})]}),a.note?.kind===`failed`&&(0,E.jsx)(P,{message:a.note.error}),a.note?.kind===`unlinked`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_unlinked`)})]}),l===!0&&c&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsxs)(A,{label:i(`profile.notify_test_row`),help:i(`profile.notify_test_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`test`,onClick:a.test,children:i(`profile.tg_test`)}),a.note?.kind===`test_sent`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:i(`profile.tg_test_sent`)}),a.note?.kind===`test_failed`&&(0,E.jsx)(P,{message:i(`profile.tg_test_failed`,{error:a.note.error})})]}),(0,E.jsx)(A,{label:i(`profile.notify_unlink_row`),help:i(`profile.notify_unlink_help`),middle:!0,children:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a.busy===`unlink`,onClick:a.unlink,children:i(`profile.tg_unlink`)})})]})]}),l===!0&&c&&(0,E.jsxs)(k,{title:i(`profile.notify_what_title`),sub:i(`profile.notify_what_sub`),children:[(0,E.jsxs)(A,{label:i(`profile.notify_digest`),help:i(`profile.notify_digest_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_digest`),checked:e.notify_digest,disabled:t===`notify_digest`,onToggle:e=>r(`notify_digest`,e)}),(0,E.jsx)(P,{message:s(`notify_digest`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_weekly`),help:i(`profile.notify_weekly_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_weekly`),checked:e.notify_weekly,disabled:t===`notify_weekly`,onToggle:e=>r(`notify_weekly`,e)}),(0,E.jsx)(P,{message:s(`notify_weekly`)})]}),(0,E.jsxs)(A,{label:i(`profile.notify_alerts`),help:i(`profile.notify_alerts_help`),middle:!0,children:[(0,E.jsx)(N,{label:i(`profile.notify_alerts`),checked:e.notify_alerts,disabled:t===`notify_alerts`,onToggle:e=>r(`notify_alerts`,e)}),(0,E.jsx)(P,{message:s(`notify_alerts`)})]})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`b`,{className:`pr-sum-t`,children:i(`profile.notify_caption`)}),(0,E.jsx)(O,{text:i(`profile.tg_how_body`)})]})})})]})}function le(){let e=a(async()=>{let[e,t]=await Promise.all([v(`/profile-options`),v(`/profile`)]);return{options:e,profile:t}},[]);return(0,E.jsx)(b,{query:e,skeleton:(0,E.jsx)(p,{rows:8}),children:e=>(0,E.jsx)(ue,{options:e.options,stored:e.profile})})}function ue({options:e,stored:t}){let n=o(),[r,i]=(0,w.useState)(t),[a,s]=(0,w.useState)(null),[c,u]=(0,w.useState)(null);function d(e,r){i(e),s(r),u(null),l(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>i(e)).catch(e=>{i(t),u(T(e,n(`common.offline`)))}).finally(()=>s(null))}let f=e=>t=>n(`profile.iv_${e}_${t}`);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:n(`profile.iv_how_title`),sub:n(`profile.iv_how_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_risk`),help:n(`profile.iv_risk_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_risk`),value:r.risk,options:e.risk,labelOf:f(`risk`),disabled:a===`risk`,onPick:e=>e!==r.risk&&d({...r,risk:e},`risk`)})}),(0,E.jsx)(A,{label:n(`profile.iv_horizon`),help:n(`profile.iv_horizon_help`),children:(0,E.jsx)(j,{label:n(`profile.iv_horizon`),value:r.horizon,options:e.horizon,labelOf:f(`horizon`),disabled:a===`horizon`,onPick:e=>e!==r.horizon&&d({...r,horizon:e},`horizon`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_what_title`),sub:n(`profile.iv_what_sub`),children:[(0,E.jsx)(A,{label:n(`profile.iv_focus`),help:n(`profile.iv_focus_help`),children:(0,E.jsx)(F,{values:r.focus,options:e.focus,labelOf:f(`focus`),disabled:a===`focus`,onToggle:(e,t)=>d({...r,focus:t?[...r.focus,e]:r.focus.filter(t=>t!==e)},`focus`)})}),(0,E.jsx)(A,{label:n(`profile.iv_constraints`),help:n(`profile.iv_constraints_help`),children:(0,E.jsx)(F,{values:r.constraints,options:e.constraints,labelOf:f(`constraints`),disabled:a===`constraints`,onToggle:(e,t)=>d({...r,constraints:t?[...r.constraints,e]:r.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,E.jsxs)(k,{title:n(`profile.iv_notes_title`),sub:n(`profile.iv_caption`),children:[(0,E.jsx)(A,{label:n(`profile.iv_notes`),help:n(`profile.iv_notes_help`),children:(0,E.jsx)(de,{value:r.notes,placeholder:n(`profile.iv_notes_ph`),label:n(`profile.iv_notes`),disabled:a===`notes`,onCommit:e=>e!==r.notes&&d({...r,notes:e},`notes`)})}),(0,E.jsx)(P,{message:c})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsxs)(k,{children:[(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`profile.iv_sum_title`)}),(0,E.jsx)(L,{label:n(`profile.iv_risk`),value:n(`profile.iv_risk_${r.risk}`)}),(0,E.jsx)(L,{label:n(`profile.iv_horizon`),value:n(`profile.iv_horizon_${r.horizon}`)}),(0,E.jsx)(L,{label:n(`profile.iv_focus`),value:I(r.focus,f(`focus`),n(`profile.iv_sum_none`))}),(0,E.jsx)(L,{label:n(`profile.iv_constraints`),value:I(r.constraints,f(`constraints`),n(`profile.iv_sum_none`))}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`profile.iv_privacy`)})]}),r.persona?(0,E.jsxs)(`details`,{className:`pr-persona`,children:[(0,E.jsx)(`summary`,{children:n(`profile.iv_persona_open`)}),(0,E.jsx)(`p`,{className:`pr-sum-note`,children:n(`profile.iv_persona_help`)}),(0,E.jsx)(`code`,{className:`pr-persona-text`,children:r.persona})]}):null]})})]})}function I(e,t,n){return e.length?e.map(t).join(`, `):n}function L({label:e,value:t}){return(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:e}),(0,E.jsx)(`b`,{children:t})]})}function de({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,w.useState)(e);return(0,w.useEffect)(()=>o(e),[e]),(0,E.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}function R(e){return e.split(`.`)[0]?.toLowerCase()??``}function fe(){let e=o(),t=a(()=>ne(),[]);return(0,E.jsxs)(k,{title:e(`journal.title`),children:[(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.intro`)})})}),(0,E.jsx)(b,{query:t,skeleton:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(p,{rows:6})}),children:t=>t.entries.length?(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(pe,{record:t.record}),(0,E.jsx)(me,{entries:t.entries}),(0,E.jsx)(A,{label:e(`journal.export`),help:e(`journal.export_help`),children:(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/journal.md`,children:e(`journal.export_button`)})})]}):(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:e(`journal.empty`)})}),(0,E.jsx)(i,{page:`review`,className:`pr-btn ag-jr-cta`,children:e(`tour.review_cta`)})]})})]})}function pe({record:e}){let t=o();return e.proposed?(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsxs)(`p`,{className:`pr-hint`,children:[(0,E.jsx)(D,{text:t(`journal.record`,{n:e.proposed,followed:e.followed,declined:e.declined,lapsed:e.lapsed,open:e.open})}),e.marked?(0,E.jsxs)(E.Fragment,{children:[` `,(0,E.jsx)(D,{text:t(`journal.record_marked`,{n:e.marked,way:e.its_way??0})})]}):null]})}):null}function me({entries:e}){let t=o(),[n,r]=(0,w.useState)(`all`),[i,a]=(0,w.useState)(`all`),[s,c]=(0,w.useState)(``),l=(0,w.useMemo)(()=>{let t=R(s.trim());return e.filter(e=>(i===`all`||e.source===i)&&(!t||R(e.ticker).startsWith(t)))},[e,i,s]),u=(0,w.useMemo)(()=>{let e={};for(let t of l)e[t.state]=(e[t.state]??0)+1;return e},[l]),d=n===`all`?l:l.filter(e=>e.state===n),f=[`all`,...re],p=[`all`,...ae];return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:t(`journal.filter_state`),children:(0,E.jsx)(M,{value:n,options:f,labelOf:e=>e===`all`?`${t(`journal.all_states`)} · ${l.length}`:`${t(`journal.state_${e}`)} · ${u[e]??0}`,onPick:r})}),(0,E.jsx)(A,{label:t(`journal.filter_source`),children:(0,E.jsx)(j,{value:i,options:p,labelOf:e=>t(e===`all`?`journal.all_sources`:`journal.source_${e}`),onPick:a,label:t(`journal.filter_source`)})}),(0,E.jsx)(A,{label:t(`journal.filter_ticker`),children:(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,value:s,placeholder:t(`journal.filter_ticker_hint`),"aria-label":t(`journal.filter_ticker`),autoCapitalize:`characters`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,onChange:e=>c(e.target.value)})}),(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,"aria-live":`polite`,children:d.length?t(`journal.count`,{n:d.length}):t(`journal.empty_filtered`)}),d.length?null:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn ag-jr-cta`,onClick:()=>{r(`all`),a(`all`),c(``)},children:t(`journal.clear_filters`)}),d.length?(0,E.jsx)(ie,{entries:d}):null]})]})}var he=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],z=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],ge={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function B(e){let t=ge[e];return t&&t!==e?`${t} ${e}`:e}var V={en:`English`,es:`Español`},_e={en:`🇬🇧`,es:`🇪🇸`},H=[0,.08,.09];function U(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function ve(e,t){if(t)return U(e,t)??U(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return U(e,n.length>1&&n[1]?.length===2?n[1]:``)??U(e,e.default)}function W(e){return`claude mcp add --transport http topstocks ${e}`}function G(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function K({text:e,label:t}){let n=o(),[r,i]=(0,w.useState)(!1);return(0,w.useEffect)(()=>{if(!r)return;let e=setTimeout(()=>i(!1),2e3);return()=>clearTimeout(e)},[r]),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":t,onClick:()=>void navigator.clipboard?.writeText(e).then(()=>i(!0),()=>void 0),children:n(r?`profile.connector_copied`:`profile.connector_copy`)})}function q({connection:e,onGone:n}){let r=o(),i=t(),[a,c]=(0,w.useState)(!1),[u,d]=(0,w.useState)(null),p=()=>{c(!0),d(null),l(`DELETE`,`/connections/${encodeURIComponent(e.id)}`).then(n,e=>{if(c(!1),e instanceof s){x();return}if(e instanceof y&&e.status===404){n();return}d(e instanceof y?r(`profile.connector_revoke_failed`):r(`common.offline`))})},m=G(e.used,i);return(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[e.client_name,!e.verified&&(0,E.jsx)(f,{title:r(`profile.connector_unverified_help`),children:r(`profile.connector_unverified`)}),e.can_write&&(0,E.jsx)(f,{title:r(`profile.connector_can_edit_help`),children:r(`profile.connector_can_edit`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:r(`profile.connector_returns_to`,{host:e.redirect_host})}),(0,E.jsxs)(`span`,{className:`pr-conn-meta`,children:[r(`profile.connector_since`,{date:G(e.created,i)??``}),` · `,m?r(`profile.connector_used`,{date:m}):r(`profile.connector_never_used`)]}),(0,E.jsx)(P,{message:u})]}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:a,onClick:p,children:r(`profile.connector_revoke`)})]})}function ye(){let e=a(()=>v(`/connections`),[]),[t,n]=(0,w.useState)(new Set);return e.state===`loaded`?(0,E.jsx)(be,{url:e.data.url,connections:e.data.connections.filter(e=>!t.has(e.id)),onGone:e=>n(t=>new Set(t).add(e))}):null}function be({url:e,connections:t,onGone:n}){let r=o();return!e&&t.length===0?null:(0,E.jsxs)(k,{title:r(`profile.connector_title`),sub:r(`profile.connector_sub`),children:[e&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:r(`profile.connector_url`),help:r(`profile.connector_url_help`),children:(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:e}),(0,E.jsx)(K,{text:e,label:r(`profile.connector_copy_url`)})]})}),(0,E.jsxs)(A,{label:r(`profile.connector_how`),children:[(0,E.jsx)(O,{text:r(`profile.connector_how_app`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`profile.connector_how_code`)}),(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:W(e)}),(0,E.jsx)(K,{text:W(e),label:r(`profile.connector_copy_command`)})]})]})]}),(0,E.jsx)(A,{label:r(`profile.connector_list`),help:r(`profile.connector_logout_note`),children:t.length===0?(0,E.jsx)(`span`,{className:`pr-muted`,children:r(`profile.connector_none`)}):(0,E.jsx)(`ul`,{className:`pr-conns`,children:t.map(e=>(0,E.jsx)(q,{connection:e,onGone:()=>n(e.id)},e.id))})})]})}function xe(e,t,n=Date.now()/1e3){let r=Math.max(0,n-e),i=new Intl.RelativeTimeFormat(t,{numeric:`auto`});return r<600?i.format(0,`second`):r<7200?i.format(-Math.round(r/60),`minute`):r<172800?i.format(-Math.round(r/3600),`hour`):i.format(-Math.round(r/86400),`day`)}function Se({rows:e,busy:n,failure:r,onEnd:i,onEndOthers:a}){let s=o(),c=t(),l=e.filter(e=>!e.current);return(0,E.jsxs)(A,{label:s(`profile.sessions_title`),help:s(`profile.sessions_help`),children:[(0,E.jsx)(`ul`,{className:`pr-conns`,children:e.map(e=>(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[e.device||s(`profile.sessions_unknown`),e.current&&(0,E.jsx)(f,{children:s(`profile.sessions_this`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:s(`profile.sessions_active`,{when:xe(e.seen,c)})})]}),!e.current&&(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n!==null,onClick:()=>i(e.id),children:s(`profile.sessions_end`)})]},e.id))}),l.length>0&&(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n!==null,onClick:a,children:s(`profile.sessions_end_others`)}),(0,E.jsx)(P,{message:r})]})}function Ce(){let e=o(),t=a(()=>v(`/account/sessions`),[]),[n,r]=(0,w.useState)(null),[i,c]=(0,w.useState)(null),[u,d]=(0,w.useState)(new Set);if(t.state!==`loaded`)return null;let f=t.data.sessions.filter(e=>!u.has(e.id));if(f.length===0)return null;let p=(t,n,i)=>{r(t),c(null),n.then(()=>{r(null),d(e=>{let t=new Set(e);return i(t),t})},n=>{if(r(null),n instanceof s){x();return}if(n instanceof y&&n.status===404){d(e=>new Set(e).add(t));return}c(n instanceof y?e(`profile.sessions_failed`):e(`common.offline`))})};return(0,E.jsx)(Se,{rows:f,busy:n,failure:i,onEnd:e=>p(e,l(`DELETE`,`/account/sessions/${encodeURIComponent(e)}`),t=>t.add(e)),onEndOthers:()=>p(`others`,l(`DELETE`,`/account/sessions/others`),e=>f.filter(e=>!e.current).forEach(t=>e.add(t.id)))})}function we(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function Te({email:e,onClose:t}){let n=o(),[i,a]=(0,w.useState)(``),[c,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(null),p=we(i,e),m=(0,w.useRef)(null),h=(0,w.useRef)(null);return r(m,{initial:h}),(0,w.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!c&&t()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[t,c]),(0,E.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!c&&t()},children:(0,E.jsxs)(`div`,{ref:m,className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":n(`profile.delete_title`),children:[(0,E.jsx)(`h2`,{className:`pr-modal-t`,children:n(`profile.delete_title`)}),(0,E.jsx)(O,{text:n(`profile.delete_body`)}),(0,E.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`profile.delete_confirm`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,ref:h,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:e,value:i,disabled:c,onChange:e=>a(e.target.value)})]}),(0,E.jsx)(P,{message:d}),(0,E.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:c,onClick:t,children:n(`common.cancel`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!p||c,onClick:()=>{u(!0),f(null),l(`DELETE`,`/account`,{confirm:i.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;x(n)},e=>{if(u(!1),e instanceof s){x();return}f(e instanceof y&&e.status===422?e.detail:e instanceof y?n(`profile.delete_failed`):n(`common.offline`))})},children:n(`profile.delete_button`)})]})]})})}function Ee(){let e=o(),t=n(),[r,i]=(0,w.useState)(!1);return(0,E.jsxs)(A,{label:e(`profile.delete_row_title`),help:e(`profile.delete_row_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>i(!0),children:e(`profile.delete_open`)}),r&&(0,E.jsx)(Te,{email:t.email??``,onClose:()=>i(!1)})]})}function De(){let e=o(),{setParams:t}=h(),n=a(()=>v(`/chat/memories`),[]),r=n.state===`loaded`?n.data:null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:e(`profile.memory_title`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:e(`profile.memory_caption`)}),r&&(0,E.jsx)(`span`,{className:`pr-sum-note`,children:r.enabled?e(`profile.memory_count`,{n:r.memories.length,max:r.max}):e(`profile.memory_off`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>t({chat:`memory`}),children:e(`profile.memory_open`)})]})})}function Oe(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function ke(){let e=o(),{setParams:t}=h(),n=a(()=>v(`/onboarding`),[]),r=n.state===`loaded`?Oe(n.data.setup):null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:e(`tour.launch`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:e(`tour.launch_caption`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{t({tour:`1`})},children:e(`tour.launch_start`)}),r&&(0,E.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":e(`home.setup_progress`,{done:r[0],total:r[1]}),"aria-valuemin":0,"aria-valuemax":r[1],"aria-valuenow":r[0],children:[(0,E.jsx)(`div`,{className:`pr-prog-track`,children:(0,E.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(r[0]/r[1]*100)}%`}})}),(0,E.jsx)(`span`,{className:`pr-prog-n`,children:e(`home.setup_progress`,{done:r[0],total:r[1]})})]})]})})}var J=`auto`;function Y({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,w.useState)(String(e)),[u,d]=(0,w.useState)(e);return u!==e&&(d(e),l(String(e))),(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}let a=Math.min(i??n,Math.max(r??n,n));a!==n&&l(String(a)),a!==e&&t(a)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,E.jsx)(`span`,{className:`pr-hint`,children:o})]})}function Ae({prefs:e,saving:t,failure:n,save:r,owner:i}){let s=o(),c=a(()=>v(`/import/last`),[]),l=a(()=>v(`/portfolio/transactions`,{limit:1}),[]),u=[J,...Object.keys(V)],d=e=>e===J?`🌐 ${s(`profile.lang_auto`)}`:`${_e[e]??``} ${V[e]??e}`.trim(),f=z.includes(e.currency)?[...z]:[...z,e.currency],p=he.filter(e=>!f.includes(e)),m=a(()=>v(`/jurisdictions`),[]),h=m.state===`loaded`?m.data:null,g=[J,...(h?.jurisdictions??[]).map(e=>e.code)],_=e=>{if(e===J)return`🌐 ${s(`profile.tax_residence_auto`)}`;let t=h?.jurisdictions.find(t=>t.code===e),n=s(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=h?ve(h,e.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?s(`profile.tax_year_calendar`):s(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?s(`profile.tax_match_${y.matching}`):``,S=e=>n?.field===e?n.message:null;return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:s(`profile.ui_section`),sub:s(`profile.ui_section_sub`),children:[(0,E.jsxs)(A,{label:s(`profile.language`),help:s(`profile.language_caption`),children:[(0,E.jsx)(j,{label:s(`profile.language`),value:e.language??J,options:u,labelOf:d,disabled:t===`language`,onPick:t=>{let n=t===J?null:t;n!==e.language&&r(`language`,n)}}),(0,E.jsx)(P,{message:S(`language`)})]}),(0,E.jsxs)(A,{label:s(`profile.display_currency`),help:s(`profile.currency_caption`),children:[(0,E.jsx)(M,{value:e.currency,options:f,labelOf:B,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)}),p.length>0&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:s(`profile.currency_more`,{n:p.length})}),(0,E.jsx)(`div`,{children:(0,E.jsx)(M,{value:e.currency,options:p,labelOf:B,disabled:t===`currency`,onPick:t=>t!==e.currency&&r(`currency`,t)})})]}),p.length>0&&(0,E.jsx)(`span`,{className:`pr-morehint`,children:p.join(` · `)}),(0,E.jsx)(P,{message:S(`currency`)})]})]}),(0,E.jsxs)(k,{title:s(`profile.tax_section`),note:s(`profile.tax_legal_note`),children:[(0,E.jsxs)(A,{label:s(`profile.tax_residence`),help:s(`profile.tax_residence_caption`),children:[(0,E.jsx)(j,{label:s(`profile.tax_residence`),value:e.tax_residence??J,options:g,labelOf:_,disabled:t===`tax_residence`,onPick:t=>{let n=t===J?null:t;n!==e.tax_residence&&r(`tax_residence`,n)}}),(0,E.jsx)(P,{message:S(`tax_residence`)}),y?(0,E.jsxs)(`div`,{className:`pr-rules`,children:[(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_cost`)}),(0,E.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,s(`profile.tax_rule_fx`)]})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_matching`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:s(`profile.tax_rule_year`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(n=>{let i=y.code.toLowerCase();return n===`filing_status`?(0,E.jsxs)(A,{label:s(`profile.tax_filing_status`),help:s(`profile.tax_filing_status_caption_${i}`),children:[(0,E.jsx)(j,{label:s(`profile.tax_filing_status`),value:y.filing_statuses.includes(e.tax_filing_status)?e.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>s(`profile.tax_status_${e}`),disabled:t===`tax_filing_status`,onPick:e=>r(`tax_filing_status`,e)}),(0,E.jsx)(P,{message:S(`tax_filing_status`)})]},n):n===`church_tax_rate`?(0,E.jsxs)(A,{label:s(`profile.tax_church`),help:s(`profile.tax_church_caption`),children:[(0,E.jsx)(j,{label:s(`profile.tax_church`),value:String(H.includes(e.tax_church_rate)?e.tax_church_rate:0),options:H.map(String),labelOf:e=>s(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:t===`tax_church_rate`,onPick:e=>r(`tax_church_rate`,Number(e))}),(0,E.jsx)(P,{message:S(`tax_church_rate`)})]},n):n===`other_income`?(0,E.jsxs)(A,{label:s(`profile.tax_other_income`),help:s(`profile.tax_other_income_caption_${i}`),children:[(0,E.jsx)(Y,{label:s(`profile.tax_other_income`),value:e.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:t===`tax_other_income`,onCommit:e=>r(`tax_other_income`,e)}),(0,E.jsx)(P,{message:S(`tax_other_income`)})]},n):n===`subnational_rate`?(0,E.jsxs)(A,{label:s(`profile.tax_subnational`),help:s(`profile.tax_subnational_caption`),children:[(0,E.jsx)(Y,{label:s(`profile.tax_subnational`),value:Math.round(e.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:t===`tax_subnational_rate`,onCommit:e=>r(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,E.jsx)(P,{message:S(`tax_subnational_rate`)})]},n):(0,E.jsxs)(A,{label:s(`profile.tax_niit`),help:s(`profile.tax_niit_caption`),middle:!0,children:[(0,E.jsx)(N,{label:s(`profile.tax_niit`),checked:e.tax_niit,disabled:t===`tax_niit`,onToggle:e=>r(`tax_niit`,e)}),(0,E.jsx)(P,{message:S(`tax_niit`)})]},n)})]}),(0,E.jsxs)(k,{title:s(`profile.data_section`),children:[(0,E.jsx)(A,{label:s(`profile.export_title`),help:s(`profile.export_help`),children:l.state===`loaded`&&l.data.total>0?(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:s(`profile.export_button`)}):(0,E.jsx)(`span`,{className:`pr-muted`,children:s(`profile.export_none`)})}),(0,E.jsx)(A,{label:s(`profile.export_all_title`),help:s(`profile.export_all_help`),children:(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/account/export`,children:s(`profile.export_all_button`)})}),(0,E.jsx)(Ce,{}),i===!1&&(0,E.jsx)(Ee,{})]}),(0,E.jsx)(ye,{})]}),(0,E.jsxs)(`aside`,{className:`pr-rail`,children:[(0,E.jsx)(ke,{}),(0,E.jsx)(De,{}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:s(`profile.summary_title`)}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:s(`profile.language`)}),(0,E.jsx)(`b`,{children:(d(e.language??J).split(`(`)[0]??``).trim()})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:s(`profile.display_currency`)}),(0,E.jsx)(`b`,{children:e.currency})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:s(`profile.tax_section`)}),(0,E.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(s(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:s(`common.loading`)})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:s(`profile.summary_last_import`)}),(0,E.jsx)(`b`,{children:c.state===`loaded`?ee(c.data.imported_on)||s(`profile.summary_never`):s(`common.loading`)})]}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:s(`profile.summary_note`)})]})})]})]})}var je=new Set([`currency`,`language`]);function Me(t){let n=e(),[r,i]=(0,w.useState)(n.prefs),[a,o]=(0,w.useState)(null),[c,u]=(0,w.useState)(null);return{prefs:r,saving:a,failure:c,save:(0,w.useCallback)((e,r)=>{o(e),u(null),l(`PATCH`,`/prefs`,{[e]:r}).then(t=>{o(null),i(t),je.has(e)&&n.reload()},r=>{if(o(null),r instanceof s){n.reload();return}u({field:e,message:T(r,t)})})},[n,t])}}var Ne=`
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
`,Pe={analyze:`raw`},X=2;function Fe({listed:e,tags:t,onAdd:n,busy:r,failure:i}){let a=o(),[s,l]=(0,w.useState)(``),[u,d]=(0,w.useState)([]),[f,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(!1),[g,_]=(0,w.useState)(null),[v,y]=(0,w.useState)(null),b=s.trim();(0,w.useEffect)(()=>{if(b.length<X){_(null);return}let e=!0,t=window.setTimeout(()=>{c(b,{limit:8}).then(t=>e&&(_(t.matches),y(null)),()=>e&&(_([]),y(a(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(t)}},[b]);let x=e=>{n({ticker:e.ticker,name:e.name,...m?{favorite:!0}:{},...u.length?{tags:u}:{}}),l(``),_(null)},C=[...new Set([...t,...u])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsx)(k,{title:a(`watchlist.add_title`),sub:a(`watchlist.add_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,autoCapitalize:`off`,autoComplete:`off`,autoCorrect:`off`,enterKeyHint:`search`,spellCheck:!1,"aria-label":a(`watchlist.add_title`),placeholder:a(`watchlist.add_placeholder`),value:s,onChange:e=>l(e.target.value)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups`)}),C.map(e=>(0,E.jsx)(S,{on:u.includes(e),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.add_groups`),autoComplete:`off`,enterKeyHint:`done`,placeholder:a(`watchlist.add_groups_ph`),value:f,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(d(e=>e.includes(t)?e:[...e,t]),p(``))}})]}),(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.add_groups_help`)}),(0,E.jsxs)(`label`,{className:`pr-switch`,children:[(0,E.jsx)(`input`,{type:`checkbox`,checked:m,onChange:e=>h(e.target.checked)}),(0,E.jsx)(`span`,{children:a(`watchlist.add_fav`)})]}),(0,E.jsx)(P,{message:i??v}),b.length<X?(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_hint`)}):g===null?(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`common.loading`)}):g.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`watchlist.add_none`)}):(0,E.jsx)(`div`,{className:`pr-res`,children:g.map(t=>{let n=e.has(t.ticker.toUpperCase()),i=Pe[t.kind]??t.kind;return(0,E.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:n||r,title:a(n?`watchlist.add_listed`:`watchlist.kind_${i}`),onClick:()=>x(t),children:[(0,E.jsx)(`span`,{className:`pr-resrow-t`,children:t.ticker}),(0,E.jsx)(`span`,{className:`pr-resrow-n`,children:t.name}),(0,E.jsx)(`span`,{className:`pr-resrow-k`,children:n?a(`watchlist.add_listed`):(t.exchange??``)||a(`watchlist.kind_${i}`)})]},t.ticker)})})]})})}var Z=e=>e?String(e):``;function Ie(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var Le=[`tags`,`favorites`,`flat`];function Re(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function ze(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Be({entry:e,tags:t,busy:n,onEdit:r,onRemove:i}){let a=o(),[s,c]=(0,w.useState)(e.name),[l,u]=(0,w.useState)(e.name),[f,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(Z(e.shares)),[g,_]=(0,w.useState)(Z(e.cost)),[v,y]=(0,w.useState)([e.shares,e.cost]);l!==e.name&&(u(e.name),c(e.name)),(v[0]!==e.shares||v[1]!==e.cost)&&(y([e.shares,e.cost]),h(Z(e.shares)),_(Z(e.cost)));let b=(t,n)=>{let i=Ie(n,e[t]);if(i===void 0){t===`shares`?h(Z(e.shares)):_(Z(e.cost));return}r(e.ticker,{[t]:i})},x=t=>r(e.ticker,{tags:e.tags.some(e=>e.toLowerCase()===t.toLowerCase())?e.tags.filter(e=>e.toLowerCase()!==t.toLowerCase()):[...e.tags,t]}),C=[...new Set([...t,...e.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsxs)(`div`,{className:`pr-wrow`,children:[(0,E.jsx)(`button`,{type:`button`,className:e.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":a(`watchlist.col_favorite`),"aria-pressed":e.favorite,disabled:n,onClick:()=>r(e.ticker,{favorite:!e.favorite}),children:e.favorite?`★`:`☆`}),(0,E.jsx)(d,{ticker:e.ticker,className:`pr-wsym`,children:e.ticker}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":a(`watchlist.col_name`),autoComplete:`off`,enterKeyHint:`done`,value:s,disabled:n,onChange:e=>c(e.target.value),onBlur:()=>s!==e.name&&r(e.ticker,{name:s}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_shares`),placeholder:a(`watchlist.col_shares`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:m,disabled:n,onChange:e=>h(e.target.value),onBlur:()=>b(`shares`,m),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":a(`watchlist.col_cost`),placeholder:a(`watchlist.col_cost`),title:a(`watchlist.col_cost_help`),inputMode:`decimal`,autoComplete:`off`,enterKeyHint:`done`,value:g,disabled:n,onChange:e=>_(e.target.value),onBlur:()=>b(`cost`,g),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,onClick:()=>i(e.ticker),children:a(`watchlist.act_remove`)}),(0,E.jsxs)(`details`,{className:`pr-wtags`,children:[(0,E.jsxs)(`summary`,{children:[a(`watchlist.col_tags`),e.tags.length?` · ${e.tags.join(`, `)}`:``]}),(0,E.jsxs)(`div`,{children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.col_tags_help`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[C.map(t=>{let r=e.tags.some(e=>e.toLowerCase()===t.toLowerCase());return(0,E.jsx)(S,{on:r,disabled:n,onClick:()=>x(t),children:t},t)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.col_tags`),autoComplete:`off`,enterKeyHint:`done`,placeholder:a(`watchlist.add_groups_ph`),value:f,disabled:n,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=f.trim();t&&(p(``),x(t))}})]})]})]})]})}function Ve({section:e,busy:t,onRename:n,onDissolve:r}){let i=o(),[a,s]=(0,w.useState)(e.tag??``);return(0,E.jsxs)(`div`,{className:`pr-ghead`,children:[(0,E.jsx)(`span`,{className:`pr-gt`,children:e.label}),(0,E.jsx)(`span`,{className:`pr-gc`,children:e.rows.length}),e.tag!==null&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:i(`watchlist.group_manage`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`watchlist.group_manage_help`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":i(`watchlist.group_rename`),autoComplete:`off`,enterKeyHint:`done`,value:a,disabled:t,onChange:e=>s(e.target.value),onKeyDown:t=>{if(t.key!==`Enter`)return;let r=a.trim();r&&r!==e.tag&&n(e.tag,r)}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t||!a.trim()||a.trim()===e.tag,onClick:()=>n(e.tag,a.trim()),children:i(`watchlist.group_rename_apply`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:t,title:i(`watchlist.group_delete_help`),onClick:()=>r(e.tag),children:i(`watchlist.group_delete`)})]})]})]})}function He({entries:e,reload:t}){let n=o(),[r,i]=(0,w.useState)(!1),[a,c]=(0,w.useState)(null),[u,d]=(0,w.useState)(``),[f,p]=(0,w.useState)([]),[m,h]=(0,w.useState)(`tags`),g=(e,r=`list`)=>{i(!0),c(null),e.then(()=>{i(!1),t()},e=>{if(i(!1),e instanceof s){t();return}c({where:r,message:T(e,n(`common.offline`))})})},_=[...new Set(e.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),v=new Set(e.map(e=>e.ticker.toUpperCase())),y=new Set(f.map(e=>e.toLowerCase())),b=e.filter(e=>ze(e,u)&&(!y.size||e.tags.some(e=>y.has(e.toLowerCase()))));return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(Fe,{listed:v,tags:_,busy:r,failure:a?.where===`add`?a.message:null,onAdd:e=>g(l(`POST`,`/watchlist`,e),`add`)}),e.length===0?(0,E.jsx)(k,{title:n(`profile.empty_watchlist_title`),children:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`profile.empty_watchlist_body`)})})}):(0,E.jsx)(k,{title:n(`watchlist.list_title`),sub:n(`watchlist.list_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,autoComplete:`off`,enterKeyHint:`search`,"aria-label":n(`watchlist.filter`),placeholder:n(`watchlist.filter_ph`),value:u,onChange:e=>d(e.target.value)}),Le.map(e=>(0,E.jsx)(S,{on:e===m,onClick:()=>h(e),children:n(`watchlist.group_${e}`)},e))]}),_.length>0&&(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.tag_filter`)}),_.map(e=>(0,E.jsx)(S,{on:y.has(e.toLowerCase()),onClick:()=>p(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,E.jsx)(P,{message:a?.where===`list`?a.message:null}),b.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:n(`watchlist.no_match`)}):Re(b,m,n(`watchlist.g_untagged`),{all:n(`watchlist.g_all`),favorites:n(`watchlist.g_favorites`),rest:n(`watchlist.g_rest`)}).map(e=>(0,E.jsxs)(`div`,{children:[(0,E.jsx)(Ve,{section:e,busy:r,onRename:(e,t)=>g(l(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>g(l(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,E.jsx)(Be,{entry:t,tags:_,busy:r,onEdit:(e,t)=>g(l(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>g(l(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,E.jsxs)(`div`,{className:`pr-foot`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:n(`watchlist.count`,{n:e.length})}),(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:n(`watchlist.how_open`)}),(0,E.jsx)(`div`,{children:(0,E.jsx)(O,{text:n(`watchlist.how`)})})]})]})]})})]})}function Ue({onAdded:e}){let t=o(),[n,r]=(0,w.useState)(0),i=a(()=>v(`/watchlist/suggestions`),[n]),[s,c]=(0,w.useState)(!1),[u,f]=(0,w.useState)(null);if(i.state!==`loaded`||i.data.suggestions.length===0)return null;let p=i.data.suggestions;function m(){c(!0),f(null),p.reduce((e,t)=>e.then(()=>l(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{r(e=>e+1),e()}).catch(e=>f(T(e,t(`common.offline`)))).finally(()=>c(!1))}return(0,E.jsxs)(k,{title:t(`profile.focus_suggest_title`),children:[(0,E.jsx)(O,{text:t(`profile.focus_suggest_help`)}),(0,E.jsx)(`ul`,{className:`pr-examples`,children:p.map(e=>(0,E.jsxs)(`li`,{children:[(0,E.jsx)(d,{ticker:e.ticker,className:`pr-wsym`}),(0,E.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,E.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:s,onClick:m,children:t(`profile.focus_suggest_add`,{n:p.length})}),(0,E.jsx)(P,{message:u})]})}function We({query:e}){return(0,E.jsx)(`div`,{className:`pr-main`,children:(0,E.jsx)(b,{query:e,children:(e,t)=>(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(He,{entries:e.entries,reload:t}),(0,E.jsx)(Ue,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`},{id:`journal`,label:`journal.tab`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Ge(){return C()?(0,E.jsx)(m,{text:`common.sign_in`}):(0,E.jsx)(Ke,{})}function Ke(){let e=o(),t=n(),{params:r,setParams:i}=h(),s=Me(e(`common.offline`)),c=a(()=>v(`/me`),[]),l=c.state===`loaded`?c.data:null,u=a(()=>v(`/watchlist`),[]),d=u.state===`loaded`?u.data.entries.length:0,[f,p]=(0,w.useState)(!1),m=l?.name?.trim()||``,g=r.get(`tab`)??``,_=Q.some(e=>e.id===g)?g:`prefs`,y=t.email??``;return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:Ne}),(0,E.jsxs)(`header`,{className:`pr-head`,children:[(0,E.jsx)(`h1`,{className:`pr-title`,children:e(`nav.profile`)}),(0,E.jsx)(`span`,{className:`pr-savehint`,children:e(`profile.saves_instantly`)})]}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-ident`,children:[(0,E.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:l?.picture&&!f?(0,E.jsx)(`img`,{src:l.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>p(!0)}):$(y,m)}),(0,E.jsxs)(`div`,{className:`pr-ident-t`,children:[m&&m!==y&&(0,E.jsx)(`span`,{className:`pr-ident-n`,children:m}),(0,E.jsx)(`span`,{className:`pr-ident-e`,children:y})]}),(0,E.jsx)(`div`,{className:`pr-ident-r`,children:(0,E.jsx)(`span`,{className:`pr-ident-note`,children:e(`profile.account_scope`)})}),(0,E.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,onClick:e=>{e.preventDefault(),x()},children:e(`common.log_out`)})]})}),(0,E.jsx)(te,{className:`pr-tabs`,label:e(`nav.profile`),items:Q.map(t=>({id:t.id,label:e(t.label),count:t.id===`watch`?d:null})),active:_,onPick:e=>i({tab:e})}),_===`prefs`&&(0,E.jsx)(Ae,{...s,owner:c.state===`loaded`?!!l?.owner:null}),_===`iv`&&(0,E.jsx)(le,{}),_===`watch`&&(0,E.jsx)(We,{query:u}),_===`notify`&&(0,E.jsx)(ce,{...s}),_===`journal`&&(0,E.jsx)(fe,{})]})}export{Ge as default,$ as initials};