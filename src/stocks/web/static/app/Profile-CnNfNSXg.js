import{At as e,Bt as t,Ct as n,Gt as r,Ht as i,Mt as a,Rt as o,Ut as s,ft as c,jt as l,kt as u,o as d,p as f,pt as p,qt as m,r as h,s as g,t as _,wt as v,xt as y,y as b,zt as x}from"./app-DZjnT6bD.js";import{t as S}from"./dates-fkUL9J5t.js";import{a as C,i as ee,n as te,r as ne}from"./Journal-NQNop_sY.js";var w=m(r(),1);function T(e,t){return e instanceof o?e.detail:t}var re=3e3;function ie(e){let{reload:n}=v(),[r,a]=(0,w.useState)(null),[o,s]=(0,w.useState)(null),[c,l]=(0,w.useState)(!1),[u,d]=(0,w.useState)(!1),[f,p]=(0,w.useState)(null),[m,h]=(0,w.useState)(null),g=(0,w.useCallback)(t=>t instanceof x?(n(),null):{kind:`failed`,error:T(t,e)},[n,e]);(0,w.useEffect)(()=>{let e=!0;return t(`/notify/telegram`).then(t=>e&&a(t),t=>{e&&h(g(t))}),()=>{e=!1}},[g]);let[_,y]=(0,w.useState)(()=>typeof document>`u`||!document.hidden);return(0,w.useEffect)(()=>{let e=()=>y(!document.hidden);return document.addEventListener(`visibilitychange`,e),()=>document.removeEventListener(`visibilitychange`,e)},[]),(0,w.useEffect)(()=>{if(!o||!_)return;if(Date.now()>=o.deadline){s(null),l(!0);return}let e=!0,n=window.setInterval(()=>{if(Date.now()>=o.deadline){s(null),l(!0);return}t(`/notify/telegram`).then(t=>{e&&(d(!1),a(t),t.linked&&s(null))},()=>e&&d(!0))},re);return()=>{e=!1,window.clearInterval(n)}},[o,_]),{state:r,pending:o,expired:c,stalled:u,busy:f,note:m,connect:(0,w.useCallback)(()=>{p(`connect`),h(null),l(!1),i(`POST`,`/notify/telegram`).then(e=>{p(null),s({code:e.code,deepLink:e.deep_link,bot:e.bot,deadline:Date.now()+e.expires_in*1e3})},e=>{p(null),h(g(e))})},[g]),test:(0,w.useCallback)(()=>{p(`test`),h(null),i(`POST`,`/notify/telegram/test`).then(e=>{p(null),a(e),h({kind:`test_sent`})},t=>{if(p(null),t instanceof x){n();return}h({kind:`test_failed`,error:T(t,e)})})},[n,e]),unlink:(0,w.useCallback)(()=>{p(`unlink`),h(null),i(`DELETE`,`/notify/telegram`).then(e=>{p(null),a(e),s(null),l(!1),h({kind:`unlinked`})},e=>{p(null),h(g(e))})},[g])}}var E=l();function D({text:e}){let t=e.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return(0,E.jsx)(E.Fragment,{children:t.map((e,t)=>e.startsWith(`**`)&&e.endsWith(`**`)&&e.length>4?(0,E.jsx)(`b`,{children:e.slice(2,-2)},t):e.startsWith("`")&&e.endsWith("`")&&e.length>2?(0,E.jsx)(`code`,{children:e.slice(1,-1)},t):(0,E.jsx)(w.Fragment,{children:e},t))})}function O({text:e,className:t}){let n=[],r=[],i=e=>{r.length&&(n.push((0,E.jsx)(`ul`,{children:r.map((e,t)=>(0,E.jsx)(`li`,{children:(0,E.jsx)(D,{text:e})},t))},`ul${e}`)),r=[])};return e.split(`
`).forEach((e,t)=>{let a=e.trim();if(a.startsWith(`- `)){r.push(a.slice(2));return}i(t),a&&n.push((0,E.jsx)(`p`,{children:(0,E.jsx)(D,{text:a})},t))}),i(-1),(0,E.jsx)(`div`,{className:t??`pr-prose`,children:n})}function k({title:e,sub:t,note:n,children:r}){return(0,E.jsxs)(`section`,{className:`pr-card`,children:[e!==void 0&&(0,E.jsxs)(`div`,{className:`pr-cardhead`,children:[(0,E.jsx)(`span`,{className:`pr-cardtitle`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-cardsub`,children:t}),n&&(0,E.jsx)(`span`,{className:`pr-cardnote`,children:n})]}),r]})}function A({label:e,help:t,middle:n,children:r}){return(0,E.jsxs)(`div`,{className:n?`pr-row pr-row-mid`:`pr-row`,children:[(0,E.jsxs)(`div`,{className:`pr-row-l`,children:[(0,E.jsx)(`span`,{className:`pr-row-lab`,children:e}),t&&(0,E.jsx)(`span`,{className:`pr-row-help`,children:(0,E.jsx)(D,{text:t})})]}),(0,E.jsx)(`div`,{className:`pr-row-ctl`,children:r})]})}function j({value:e,options:t,labelOf:n,onPick:r,label:i,disabled:a}){return(0,E.jsx)(`select`,{className:`pr-select`,"aria-label":i,value:e,disabled:a,onChange:e=>r(e.target.value),children:t.map(e=>(0,E.jsx)(`option`,{value:e,children:n(e)},e))})}function M({value:e,options:t,labelOf:n,onPick:r,disabled:i}){return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(t=>(0,E.jsx)(f,{on:t===e,disabled:i,onClick:()=>r(t),children:n(t)},t))})}function N({checked:e,onToggle:t,label:n,disabled:r}){return(0,E.jsx)(`label`,{className:`pr-switch`,children:(0,E.jsx)(`input`,{type:`checkbox`,checked:e,disabled:r,"aria-label":n,onChange:e=>t(e.target.checked)})})}function P({message:e}){return e?(0,E.jsx)(`p`,{className:`pr-err`,role:`alert`,children:e}):null}function F({values:e,options:t,labelOf:n,onToggle:r,disabled:i}){let a=new Set(e);return(0,E.jsx)(`div`,{className:`pr-chips`,children:t.map(e=>{let t=a.has(e);return(0,E.jsx)(f,{on:t,disabled:i,onClick:()=>r(e,!t),children:n(e)},e)})})}function ae({prefs:t,saving:n,failure:r,save:i}){let a=e(),o=ie(a(`common.offline`)),s=e=>r?.field===e?r.message:null,c=o.state?o.state.linked:t.telegram_linked,l=o.state?.configured??(t.telegram_linked?!0:null);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:a(`profile.notify_channel_title`),sub:a(`profile.notify_channel_sub`),children:[(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[l===null&&!o.note&&(0,E.jsx)(`p`,{className:`pr-busy`,children:a(`common.loading`)}),l===!1&&(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_not_configured`)}),l===!0&&c&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-badge`,children:a(`profile.notify_connected`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`profile.tg_linked_as`,{handle:o.state?.username?`@${o.state.username}`:``}).trim()})]}),l===!0&&!c&&!o.pending&&(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p`,disabled:o.busy===`connect`,onClick:o.connect,children:a(`profile.tg_connect`)}),o.expired&&(0,E.jsx)(`span`,{className:`pr-warn`,children:a(`profile.tg_expired`)})]}),l===!0&&!c&&o.pending&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`a`,{className:`pr-linkbtn`,href:o.pending.deepLink,target:`_blank`,rel:`noreferrer noopener`,children:a(`profile.tg_open`)}),(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:a(`profile.tg_manual`,{bot:o.pending.bot,code:o.pending.code})})}),(0,E.jsx)(`p`,{className:`pr-busy`,children:o.stalled?a(`profile.tg_poll_error`):a(`profile.tg_waiting`)})]}),o.note?.kind===`failed`&&(0,E.jsx)(P,{message:o.note.error}),o.note?.kind===`unlinked`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_unlinked`)})]}),l===!0&&c&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsxs)(A,{label:a(`profile.notify_test_row`),help:a(`profile.notify_test_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`test`,onClick:o.test,children:a(`profile.tg_test`)}),o.note?.kind===`test_sent`&&(0,E.jsx)(`p`,{className:`pr-hint`,children:a(`profile.tg_test_sent`)}),o.note?.kind===`test_failed`&&(0,E.jsx)(P,{message:a(`profile.tg_test_failed`,{error:o.note.error})})]}),(0,E.jsx)(A,{label:a(`profile.notify_unlink_row`),help:a(`profile.notify_unlink_help`),middle:!0,children:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:o.busy===`unlink`,onClick:o.unlink,children:a(`profile.tg_unlink`)})})]})]}),l===!0&&c&&(0,E.jsxs)(k,{title:a(`profile.notify_what_title`),sub:a(`profile.notify_what_sub`),children:[(0,E.jsxs)(A,{label:a(`profile.notify_digest`),help:a(`profile.notify_digest_help`),middle:!0,children:[(0,E.jsx)(N,{label:a(`profile.notify_digest`),checked:t.notify_digest,disabled:n===`notify_digest`,onToggle:e=>i(`notify_digest`,e)}),(0,E.jsx)(P,{message:s(`notify_digest`)})]}),(0,E.jsxs)(A,{label:a(`profile.notify_weekly`),help:a(`profile.notify_weekly_help`),middle:!0,children:[(0,E.jsx)(N,{label:a(`profile.notify_weekly`),checked:t.notify_weekly,disabled:n===`notify_weekly`,onToggle:e=>i(`notify_weekly`,e)}),(0,E.jsx)(P,{message:s(`notify_weekly`)})]}),(0,E.jsxs)(A,{label:a(`profile.notify_alerts`),help:a(`profile.notify_alerts_help`),middle:!0,children:[(0,E.jsx)(N,{label:a(`profile.notify_alerts`),checked:t.notify_alerts,disabled:n===`notify_alerts`,onToggle:e=>i(`notify_alerts`,e)}),(0,E.jsx)(P,{message:s(`notify_alerts`)})]})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`b`,{className:`pr-sum-t`,children:a(`profile.notify_caption`)}),(0,E.jsx)(O,{text:a(`profile.tg_how_body`)})]})})})]})}function oe(){let e=a(async()=>{let[e,n]=await Promise.all([t(`/profile-options`),t(`/profile`)]);return{options:e,profile:n}},[]);return(0,E.jsx)(_,{query:e,skeleton:(0,E.jsx)(h,{rows:8}),children:e=>(0,E.jsx)(se,{options:e.options,stored:e.profile})})}function se({options:t,stored:n}){let r=e(),[a,o]=(0,w.useState)(n),[s,c]=(0,w.useState)(null),[l,u]=(0,w.useState)(null);function d(e,t){o(e),c(t),u(null),i(`PUT`,`/profile`,{risk:e.risk,horizon:e.horizon,focus:e.focus,constraints:e.constraints,notes:e.notes}).then(e=>o(e)).catch(e=>{o(n),u(T(e,r(`common.offline`)))}).finally(()=>c(null))}let f=e=>t=>r(`profile.iv_${e}_${t}`);return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:r(`profile.iv_how_title`),sub:r(`profile.iv_how_sub`),children:[(0,E.jsx)(A,{label:r(`profile.iv_risk`),help:r(`profile.iv_risk_help`),children:(0,E.jsx)(j,{label:r(`profile.iv_risk`),value:a.risk,options:t.risk,labelOf:f(`risk`),disabled:s===`risk`,onPick:e=>e!==a.risk&&d({...a,risk:e},`risk`)})}),(0,E.jsx)(A,{label:r(`profile.iv_horizon`),help:r(`profile.iv_horizon_help`),children:(0,E.jsx)(j,{label:r(`profile.iv_horizon`),value:a.horizon,options:t.horizon,labelOf:f(`horizon`),disabled:s===`horizon`,onPick:e=>e!==a.horizon&&d({...a,horizon:e},`horizon`)})})]}),(0,E.jsxs)(k,{title:r(`profile.iv_what_title`),sub:r(`profile.iv_what_sub`),children:[(0,E.jsx)(A,{label:r(`profile.iv_focus`),help:r(`profile.iv_focus_help`),children:(0,E.jsx)(F,{values:a.focus,options:t.focus,labelOf:f(`focus`),disabled:s===`focus`,onToggle:(e,t)=>d({...a,focus:t?[...a.focus,e]:a.focus.filter(t=>t!==e)},`focus`)})}),(0,E.jsx)(A,{label:r(`profile.iv_constraints`),help:r(`profile.iv_constraints_help`),children:(0,E.jsx)(F,{values:a.constraints,options:t.constraints,labelOf:f(`constraints`),disabled:s===`constraints`,onToggle:(e,t)=>d({...a,constraints:t?[...a.constraints,e]:a.constraints.filter(t=>t!==e)},`constraints`)})})]}),(0,E.jsxs)(k,{title:r(`profile.iv_notes_title`),sub:r(`profile.iv_caption`),children:[(0,E.jsx)(A,{label:r(`profile.iv_notes`),help:r(`profile.iv_notes_help`),children:(0,E.jsx)(ce,{value:a.notes,placeholder:r(`profile.iv_notes_ph`),label:r(`profile.iv_notes`),disabled:s===`notes`,onCommit:e=>e!==a.notes&&d({...a,notes:e},`notes`)})}),(0,E.jsx)(P,{message:l})]})]}),(0,E.jsx)(`aside`,{className:`pr-rail`,children:(0,E.jsxs)(k,{children:[(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:r(`profile.iv_sum_title`)}),(0,E.jsx)(L,{label:r(`profile.iv_risk`),value:r(`profile.iv_risk_${a.risk}`)}),(0,E.jsx)(L,{label:r(`profile.iv_horizon`),value:r(`profile.iv_horizon_${a.horizon}`)}),(0,E.jsx)(L,{label:r(`profile.iv_focus`),value:I(a.focus,f(`focus`),r(`profile.iv_sum_none`))}),(0,E.jsx)(L,{label:r(`profile.iv_constraints`),value:I(a.constraints,f(`constraints`),r(`profile.iv_sum_none`))}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:r(`profile.iv_privacy`)})]}),a.persona?(0,E.jsxs)(`details`,{className:`pr-persona`,children:[(0,E.jsx)(`summary`,{children:r(`profile.iv_persona_open`)}),(0,E.jsx)(`p`,{className:`pr-sum-note`,children:r(`profile.iv_persona_help`)}),(0,E.jsx)(`code`,{className:`pr-persona-text`,children:a.persona})]}):null]})})]})}function I(e,t,n){return e.length?e.map(t).join(`, `):n}function L({label:e,value:t}){return(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:e}),(0,E.jsx)(`b`,{children:t})]})}function ce({value:e,label:t,placeholder:n,disabled:r,onCommit:i}){let[a,o]=(0,w.useState)(e);return(0,w.useEffect)(()=>o(e),[e]),(0,E.jsx)(`textarea`,{className:`pr-notes`,rows:4,value:a,"aria-label":t,placeholder:n,disabled:r,onChange:e=>o(e.target.value),onBlur:()=>i(a.trim())})}function R(e){return e.split(`.`)[0]?.toLowerCase()??``}function le(){let t=e(),n=a(()=>C(),[]);return(0,E.jsxs)(k,{title:t(`journal.title`),children:[(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:t(`journal.intro`)})})}),(0,E.jsx)(_,{query:n,skeleton:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(h,{rows:6})}),children:e=>e.entries.length?(0,E.jsx)(ue,{entries:e.entries}):(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,children:(0,E.jsx)(D,{text:t(`journal.empty`)})}),(0,E.jsx)(c,{page:`review`,className:`pr-btn ag-jr-cta`,children:t(`tour.review_cta`)})]})})]})}function ue({entries:t}){let n=e(),[r,i]=(0,w.useState)(`all`),[a,o]=(0,w.useState)(`all`),[s,c]=(0,w.useState)(``),l=(0,w.useMemo)(()=>{let e=R(s.trim());return t.filter(t=>(a===`all`||t.source===a)&&(!e||R(t.ticker).startsWith(e)))},[t,a,s]),u=(0,w.useMemo)(()=>{let e={};for(let t of l)e[t.state]=(e[t.state]??0)+1;return e},[l]),d=r===`all`?l:l.filter(e=>e.state===r),f=[`all`,...ee],p=[`all`,...ne];return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:n(`journal.filter_state`),children:(0,E.jsx)(M,{value:r,options:f,labelOf:e=>e===`all`?`${n(`journal.all_states`)} · ${l.length}`:`${n(`journal.state_${e}`)} · ${u[e]??0}`,onPick:i})}),(0,E.jsx)(A,{label:n(`journal.filter_source`),children:(0,E.jsx)(j,{value:a,options:p,labelOf:e=>n(e===`all`?`journal.all_sources`:`journal.source_${e}`),onPick:o,label:n(`journal.filter_source`)})}),(0,E.jsx)(A,{label:n(`journal.filter_ticker`),children:(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,value:s,placeholder:n(`journal.filter_ticker_hint`),"aria-label":n(`journal.filter_ticker`),autoCapitalize:`characters`,spellCheck:!1,onChange:e=>c(e.target.value)})}),(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`p`,{className:`pr-hint`,"aria-live":`polite`,children:d.length?n(`journal.count`,{n:d.length}):n(`journal.empty_filtered`)}),d.length?null:(0,E.jsx)(`button`,{type:`button`,className:`pr-btn ag-jr-cta`,onClick:()=>{i(`all`),o(`all`),c(``)},children:n(`journal.clear_filters`)}),d.length?(0,E.jsx)(te,{entries:d}):null]})]})}var de=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`,`NOK`,`DKK`,`PLN`,`CZK`,`CAD`,`AUD`],z=[`EUR`,`USD`,`GBP`,`CHF`,`SEK`],fe={EUR:`€`,USD:`$`,GBP:`£`,CHF:`₣`,SEK:`kr`,NOK:`kr`,DKK:`kr`,PLN:`zł`,CZK:`Kč`,CAD:`CA$`,AUD:`A$`};function B(e){let t=fe[e];return t&&t!==e?`${t} ${e}`:e}var V={en:`English`,es:`Español`},pe={en:`🇬🇧`,es:`🇪🇸`},H=[0,.08,.09];function U(e,t){let n=String(t??``).replace(`_`,`-`).split(`-`)[0]?.toUpperCase();return e.jurisdictions.find(e=>e.code===n)??null}function me(e,t){if(t)return U(e,t)??U(e,e.default);let n=String(navigator.language??``).replace(`_`,`-`).split(`-`);return U(e,n.length>1&&n[1]?.length===2?n[1]:``)??U(e,e.default)}function W(e){return`claude mcp add --transport http topstocks ${e}`}function G(e,t){if(!e)return null;let n=new Date(e);return Number.isNaN(n.getTime())?null:new Intl.DateTimeFormat(t,{day:`numeric`,month:`short`,year:`numeric`}).format(n)}function K({text:t,label:n}){let r=e(),[i,a]=(0,w.useState)(!1);return(0,w.useEffect)(()=>{if(!i)return;let e=setTimeout(()=>a(!1),2e3);return()=>clearTimeout(e)},[i]),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,"aria-label":n,onClick:()=>void navigator.clipboard?.writeText(t).then(()=>a(!0),()=>void 0),children:r(i?`profile.connector_copied`:`profile.connector_copy`)})}function he({connection:t,onGone:n}){let r=e(),a=u(),[s,c]=(0,w.useState)(!1),[l,f]=(0,w.useState)(null),p=()=>{c(!0),f(null),i(`DELETE`,`/connections/${encodeURIComponent(t.id)}`).then(n,e=>{if(c(!1),e instanceof x){window.location.assign(`/auth/logout`);return}if(e instanceof o&&e.status===404){n();return}f(e instanceof o?r(`profile.connector_revoke_failed`):r(`common.offline`))})},m=G(t.used,a);return(0,E.jsxs)(`li`,{className:`pr-conn`,children:[(0,E.jsxs)(`div`,{className:`pr-conn-l`,children:[(0,E.jsxs)(`span`,{className:`pr-conn-name`,children:[t.client_name,!t.verified&&(0,E.jsx)(d,{title:r(`profile.connector_unverified_help`),children:r(`profile.connector_unverified`)}),t.can_write&&(0,E.jsx)(d,{title:r(`profile.connector_can_edit_help`),children:r(`profile.connector_can_edit`)})]}),(0,E.jsx)(`span`,{className:`pr-conn-meta`,children:r(`profile.connector_returns_to`,{host:t.redirect_host})}),(0,E.jsxs)(`span`,{className:`pr-conn-meta`,children:[r(`profile.connector_since`,{date:G(t.created,a)??``}),` · `,m?r(`profile.connector_used`,{date:m}):r(`profile.connector_never_used`)]}),(0,E.jsx)(P,{message:l})]}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:s,onClick:p,children:r(`profile.connector_revoke`)})]})}function ge(){let e=a(()=>t(`/connections`),[]),[n,r]=(0,w.useState)(new Set);return e.state===`loaded`?(0,E.jsx)(_e,{url:e.data.url,connections:e.data.connections.filter(e=>!n.has(e.id)),onGone:e=>r(t=>new Set(t).add(e))}):null}function _e({url:t,connections:n,onGone:r}){let i=e();return!t&&n.length===0?null:(0,E.jsxs)(k,{title:i(`profile.connector_title`),sub:i(`profile.connector_sub`),children:[t&&(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(A,{label:i(`profile.connector_url`),help:i(`profile.connector_url_help`),children:(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:t}),(0,E.jsx)(K,{text:t,label:i(`profile.connector_copy_url`)})]})}),(0,E.jsxs)(A,{label:i(`profile.connector_how`),children:[(0,E.jsx)(O,{text:i(`profile.connector_how_app`)}),(0,E.jsx)(`span`,{className:`pr-hint`,children:i(`profile.connector_how_code`)}),(0,E.jsxs)(`div`,{className:`pr-copyline`,children:[(0,E.jsx)(`code`,{className:`pr-code`,children:W(t)}),(0,E.jsx)(K,{text:W(t),label:i(`profile.connector_copy_command`)})]})]})]}),(0,E.jsx)(A,{label:i(`profile.connector_list`),help:i(`profile.connector_logout_note`),children:n.length===0?(0,E.jsx)(`span`,{className:`pr-muted`,children:i(`profile.connector_none`)}):(0,E.jsx)(`ul`,{className:`pr-conns`,children:n.map(e=>(0,E.jsx)(he,{connection:e,onGone:()=>r(e.id)},e.id))})})]})}function q(e,t){return e.trim().toLowerCase()===t.trim().toLowerCase()&&t!==``}function ve({email:t,onClose:n}){let r=e(),[a,c]=(0,w.useState)(``),[l,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(null),p=q(a,t);return(0,w.useEffect)(()=>{let e=e=>{e.key===`Escape`&&!l&&n()};return window.addEventListener(`keydown`,e),()=>window.removeEventListener(`keydown`,e)},[n,l]),(0,E.jsx)(`div`,{className:`pr-modal`,onClick:e=>{e.target===e.currentTarget&&!l&&n()},children:(0,E.jsxs)(`div`,{className:`pr-modal-card`,role:`dialog`,"aria-modal":`true`,"aria-label":r(`profile.delete_title`),children:[(0,E.jsx)(`h2`,{className:`pr-modal-t`,children:r(`profile.delete_title`)}),(0,E.jsx)(O,{text:r(`profile.delete_body`)}),(0,E.jsxs)(`label`,{className:`pr-modal-confirm`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`profile.delete_confirm`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`text`,autoFocus:!0,autoComplete:`off`,autoCapitalize:`off`,spellCheck:!1,placeholder:t,value:a,disabled:l,onChange:e=>c(e.target.value)})]}),(0,E.jsx)(P,{message:d}),(0,E.jsxs)(`div`,{className:`pr-modal-foot`,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:l,onClick:n,children:r(`common.cancel`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-danger`,disabled:!p||l,onClick:()=>{u(!0),f(null),i(`DELETE`,`/account`,{confirm:a.trim()}).then(e=>{let t=e.sign_out,n=t.startsWith(`/`)&&!t.startsWith(`//`)?t:`/auth/logout`;s(n)},e=>{if(u(!1),e instanceof x){s(`/auth/logout`);return}f(e instanceof o&&e.status===422?e.detail:e instanceof o?r(`profile.delete_failed`):r(`common.offline`))})},children:r(`profile.delete_button`)})]})]})})}function ye(){let t=e(),n=y(),[r,i]=(0,w.useState)(!1);return(0,E.jsxs)(A,{label:t(`profile.delete_row_title`),help:t(`profile.delete_row_help`),middle:!0,children:[(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,onClick:()=>i(!0),children:t(`profile.delete_open`)}),r&&(0,E.jsx)(ve,{email:n.email??``,onClose:()=>i(!1)})]})}function be(){let n=e(),{setParams:r}=p(),i=a(()=>t(`/chat/memories`),[]),o=i.state===`loaded`?i.data:null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`profile.memory_title`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`profile.memory_caption`)}),o&&(0,E.jsx)(`span`,{className:`pr-sum-note`,children:o.enabled?n(`profile.memory_count`,{n:o.memories.length,max:o.max}):n(`profile.memory_off`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-selfstart`,onClick:()=>r({chat:`memory`}),children:n(`profile.memory_open`)})]})})}function xe(e){let t=Object.values(e);return t.length?[t.filter(Boolean).length,t.length]:null}function Se(){let n=e(),{setParams:r}=p(),i=a(()=>t(`/onboarding`),[]),o=i.state===`loaded`?xe(i.data.setup):null;return(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:n(`tour.launch`)}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:n(`tour.launch_caption`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn pr-btn-p pr-selfstart`,onClick:()=>{r({tour:`1`})},children:n(`tour.launch_start`)}),o&&(0,E.jsxs)(`div`,{className:`pr-prog`,role:`progressbar`,"aria-label":n(`home.setup_progress`,{done:o[0],total:o[1]}),"aria-valuemin":0,"aria-valuemax":o[1],"aria-valuenow":o[0],children:[(0,E.jsx)(`div`,{className:`pr-prog-track`,children:(0,E.jsx)(`div`,{className:`pr-prog-fill`,style:{width:`${Math.round(o[0]/o[1]*100)}%`}})}),(0,E.jsx)(`span`,{className:`pr-prog-n`,children:n(`home.setup_progress`,{done:o[0],total:o[1]})})]})]})})}var J=`auto`;function Y({value:e,onCommit:t,label:n,min:r,max:i,step:a,suffix:o,disabled:s}){let[c,l]=(0,w.useState)(String(e)),[u,d]=(0,w.useState)(e);return u!==e&&(d(e),l(String(e))),(0,E.jsxs)(`span`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input`,type:`number`,inputMode:`decimal`,"aria-label":n,value:c,min:r,max:i,step:a,disabled:s,onChange:e=>l(e.target.value),onBlur:()=>{let n=Number(c);if(c.trim()===``||Number.isNaN(n)){l(String(e));return}n!==e&&t(n)},onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),o&&(0,E.jsx)(`span`,{className:`pr-hint`,children:o})]})}function Ce({prefs:n,saving:r,failure:i,save:o,owner:s}){let c=e(),l=a(()=>t(`/import/last`),[]),u=a(()=>t(`/portfolio/transactions`,{limit:1}),[]),d=[J,...Object.keys(V)],f=e=>e===J?`🌐 ${c(`profile.lang_auto`)}`:`${pe[e]??``} ${V[e]??e}`.trim(),p=z.includes(n.currency)?[...z]:[...z,n.currency],m=de.filter(e=>!p.includes(e)),h=a(()=>t(`/jurisdictions`),[]),g=h.state===`loaded`?h.data:null,_=[J,...(g?.jurisdictions??[]).map(e=>e.code)],v=e=>{if(e===J)return`🌐 ${c(`profile.tax_residence_auto`)}`;let t=g?.jurisdictions.find(t=>t.code===e),n=c(`profile.tax_residence_${e.toLowerCase()}`);return`${t?.flag??``} ${n}`.trim()},y=g?me(g,n.tax_residence):null,b=y?y.year_start[0]===1&&y.year_start[1]===1?c(`profile.tax_year_calendar`):c(`profile.tax_year_from`,{day:y.year_start[1],month:y.year_start[0]}):``,x=y?c(`profile.tax_match_${y.matching}`):``,C=e=>i?.field===e?i.message:null;return(0,E.jsxs)(`div`,{className:`pr-body`,children:[(0,E.jsxs)(`div`,{className:`pr-main`,children:[(0,E.jsxs)(k,{title:c(`profile.ui_section`),sub:c(`profile.ui_section_sub`),children:[(0,E.jsxs)(A,{label:c(`profile.language`),help:c(`profile.language_caption`),children:[(0,E.jsx)(j,{label:c(`profile.language`),value:n.language??J,options:d,labelOf:f,disabled:r===`language`,onPick:e=>{let t=e===J?null:e;t!==n.language&&o(`language`,t)}}),(0,E.jsx)(P,{message:C(`language`)})]}),(0,E.jsxs)(A,{label:c(`profile.display_currency`),help:c(`profile.currency_caption`),children:[(0,E.jsx)(M,{value:n.currency,options:p,labelOf:B,disabled:r===`currency`,onPick:e=>e!==n.currency&&o(`currency`,e)}),m.length>0&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:c(`profile.currency_more`,{n:m.length})}),(0,E.jsx)(`div`,{children:(0,E.jsx)(M,{value:n.currency,options:m,labelOf:B,disabled:r===`currency`,onPick:e=>e!==n.currency&&o(`currency`,e)})})]}),m.length>0&&(0,E.jsx)(`span`,{className:`pr-morehint`,children:m.join(` · `)}),(0,E.jsx)(P,{message:C(`currency`)})]})]}),(0,E.jsxs)(k,{title:c(`profile.tax_section`),note:c(`profile.tax_legal_note`),children:[(0,E.jsxs)(A,{label:c(`profile.tax_residence`),help:c(`profile.tax_residence_caption`),children:[(0,E.jsx)(j,{label:c(`profile.tax_residence`),value:n.tax_residence??J,options:_,labelOf:v,disabled:r===`tax_residence`,onPick:e=>{let t=e===J?null:e;t!==n.tax_residence&&o(`tax_residence`,t)}}),(0,E.jsx)(P,{message:C(`tax_residence`)}),y?(0,E.jsxs)(`div`,{className:`pr-rules`,children:[(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:c(`profile.tax_rule_cost`)}),(0,E.jsxs)(`span`,{className:`pr-rule-v`,children:[y.currency,` · `,c(`profile.tax_rule_fx`)]})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:c(`profile.tax_rule_matching`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:x})]}),(0,E.jsxs)(`div`,{className:`pr-rule`,children:[(0,E.jsx)(`span`,{className:`pr-rule-k`,children:c(`profile.tax_rule_year`)}),(0,E.jsx)(`span`,{className:`pr-rule-v`,children:b})]})]}):null]}),(y?.settings_fields??[]).map(e=>{let t=y.code.toLowerCase();return e===`filing_status`?(0,E.jsxs)(A,{label:c(`profile.tax_filing_status`),help:c(`profile.tax_filing_status_caption_${t}`),children:[(0,E.jsx)(j,{label:c(`profile.tax_filing_status`),value:y.filing_statuses.includes(n.tax_filing_status)?n.tax_filing_status:y.filing_statuses[0]??`single`,options:y.filing_statuses,labelOf:e=>c(`profile.tax_status_${e}`),disabled:r===`tax_filing_status`,onPick:e=>o(`tax_filing_status`,e)}),(0,E.jsx)(P,{message:C(`tax_filing_status`)})]},e):e===`church_tax_rate`?(0,E.jsxs)(A,{label:c(`profile.tax_church`),help:c(`profile.tax_church_caption`),children:[(0,E.jsx)(j,{label:c(`profile.tax_church`),value:String(H.includes(n.tax_church_rate)?n.tax_church_rate:0),options:H.map(String),labelOf:e=>c(`profile.tax_church_${Math.round(Number(e)*100)}`),disabled:r===`tax_church_rate`,onPick:e=>o(`tax_church_rate`,Number(e))}),(0,E.jsx)(P,{message:C(`tax_church_rate`)})]},e):e===`other_income`?(0,E.jsxs)(A,{label:c(`profile.tax_other_income`),help:c(`profile.tax_other_income_caption_${t}`),children:[(0,E.jsx)(Y,{label:c(`profile.tax_other_income`),value:n.tax_other_income,min:0,step:1e3,suffix:y.currency,disabled:r===`tax_other_income`,onCommit:e=>o(`tax_other_income`,e)}),(0,E.jsx)(P,{message:C(`tax_other_income`)})]},e):e===`subnational_rate`?(0,E.jsxs)(A,{label:c(`profile.tax_subnational`),help:c(`profile.tax_subnational_caption`),children:[(0,E.jsx)(Y,{label:c(`profile.tax_subnational`),value:Math.round(n.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:`%`,disabled:r===`tax_subnational_rate`,onCommit:e=>o(`tax_subnational_rate`,Math.round(e*100)/1e4)}),(0,E.jsx)(P,{message:C(`tax_subnational_rate`)})]},e):(0,E.jsxs)(A,{label:c(`profile.tax_niit`),help:c(`profile.tax_niit_caption`),middle:!0,children:[(0,E.jsx)(N,{label:c(`profile.tax_niit`),checked:n.tax_niit,disabled:r===`tax_niit`,onToggle:e=>o(`tax_niit`,e)}),(0,E.jsx)(P,{message:C(`tax_niit`)})]},e)})]}),(0,E.jsxs)(k,{title:c(`profile.data_section`),children:[(0,E.jsx)(A,{label:c(`profile.export_title`),help:c(`profile.export_help`),children:u.state===`loaded`&&u.data.total>0?(0,E.jsx)(`a`,{className:`pr-download`,href:`/api/v1/portfolio/transactions.csv`,children:c(`profile.export_button`)}):(0,E.jsx)(`span`,{className:`pr-muted`,children:c(`profile.export_none`)})}),s===!1&&(0,E.jsx)(ye,{})]}),(0,E.jsx)(ge,{})]}),(0,E.jsxs)(`aside`,{className:`pr-rail`,children:[(0,E.jsx)(Se,{}),(0,E.jsx)(be,{}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-sum`,children:[(0,E.jsx)(`span`,{className:`pr-sum-t`,children:c(`profile.summary_title`)}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:c(`profile.language`)}),(0,E.jsx)(`b`,{children:(f(n.language??J).split(`(`)[0]??``).trim()})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:c(`profile.display_currency`)}),(0,E.jsx)(`b`,{children:n.currency})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:c(`profile.tax_section`)}),(0,E.jsx)(`b`,{children:y?`${y.flag?`${y.flag} `:``}${(c(`profile.tax_residence_${y.code.toLowerCase()}`).split(`—`)[0]??``).trim()} · ${x}`:c(`common.loading`)})]}),(0,E.jsxs)(`div`,{className:`pr-sum-row`,children:[(0,E.jsx)(`span`,{children:c(`profile.summary_last_import`)}),(0,E.jsx)(`b`,{children:l.state===`loaded`?S(l.data.imported_on)||c(`profile.summary_never`):c(`common.loading`)})]}),(0,E.jsx)(`div`,{className:`pr-sum-rule`}),(0,E.jsx)(`span`,{className:`pr-sum-note`,children:c(`profile.summary_note`)})]})})]})]})}var we=new Set([`currency`,`language`]);function Te(e){let t=v(),[n,r]=(0,w.useState)(t.prefs),[a,o]=(0,w.useState)(null),[s,c]=(0,w.useState)(null);return{prefs:n,saving:a,failure:s,save:(0,w.useCallback)((n,a)=>{o(n),c(null),i(`PATCH`,`/prefs`,{[n]:a}).then(e=>{o(null),r(e),we.has(n)&&t.reload()},r=>{if(o(null),r instanceof x){t.reload();return}c({field:n,message:T(r,e)})})},[t,e])}}var Ee=`
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
`,De={analyze:`raw`},X=2;function Oe({listed:n,tags:r,onAdd:i,busy:a,failure:o}){let s=e(),[c,l]=(0,w.useState)(``),[u,d]=(0,w.useState)([]),[p,m]=(0,w.useState)(``),[h,g]=(0,w.useState)(!1),[_,v]=(0,w.useState)(null),[y,b]=(0,w.useState)(null),x=c.trim();(0,w.useEffect)(()=>{if(x.length<X){v(null);return}let e=!0,n=window.setTimeout(()=>{t(`/search`,{q:x,limit:8}).then(t=>e&&(v(t.matches),b(null)),()=>e&&(v([]),b(s(`common.offline`))))},250);return()=>{e=!1,window.clearTimeout(n)}},[x]);let S=e=>{i({ticker:e.ticker,name:e.name,...h?{favorite:!0}:{},...u.length?{tags:u}:{}}),l(``),v(null)},C=[...new Set([...r,...u])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsx)(k,{title:s(`watchlist.add_title`),sub:s(`watchlist.add_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-wide`,type:`search`,"aria-label":s(`watchlist.add_title`),placeholder:s(`watchlist.add_placeholder`),value:c,onChange:e=>l(e.target.value)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:s(`watchlist.add_groups`)}),C.map(e=>(0,E.jsx)(f,{on:u.includes(e),onClick:()=>d(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e)),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":s(`watchlist.add_groups`),placeholder:s(`watchlist.add_groups_ph`),value:p,onChange:e=>m(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=p.trim();t&&(d(e=>e.includes(t)?e:[...e,t]),m(``))}})]}),(0,E.jsx)(`span`,{className:`pr-hint`,children:s(`watchlist.add_groups_help`)}),(0,E.jsxs)(`label`,{className:`pr-switch`,children:[(0,E.jsx)(`input`,{type:`checkbox`,checked:h,onChange:e=>g(e.target.checked)}),(0,E.jsx)(`span`,{children:s(`watchlist.add_fav`)})]}),(0,E.jsx)(P,{message:o??y}),x.length<X?(0,E.jsx)(`p`,{className:`pr-hint`,children:s(`watchlist.add_hint`)}):_===null?(0,E.jsx)(`p`,{className:`pr-hint`,children:s(`common.loading`)}):_.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:s(`watchlist.add_none`)}):(0,E.jsx)(`div`,{className:`pr-res`,children:_.map(e=>{let t=n.has(e.ticker.toUpperCase()),r=De[e.kind]??e.kind;return(0,E.jsxs)(`button`,{type:`button`,className:`pr-btn pr-resrow`,disabled:t||a,title:s(t?`watchlist.add_listed`:`watchlist.kind_${r}`),onClick:()=>S(e),children:[(0,E.jsx)(`span`,{className:`pr-resrow-t`,children:e.ticker}),(0,E.jsx)(`span`,{className:`pr-resrow-n`,children:e.name}),(0,E.jsx)(`span`,{className:`pr-resrow-k`,children:t?s(`watchlist.add_listed`):(e.exchange??``)||s(`watchlist.kind_${r}`)})]},e.ticker)})})]})})}var Z=e=>e?String(e):``;function ke(e,t){let n=e.trim().replace(`,`,`.`),r=n===``?0:Number(n);if(!(!Number.isFinite(r)||r<0))return r===(t??0)?void 0:r}var Ae=[`tags`,`favorites`,`flat`];function je(e,t,n,r){if(t===`flat`)return[{id:`all`,label:r.all,rows:e,tag:null}];let i=[],a=e.filter(e=>e.favorite);if(a.length&&i.push({id:`fav`,label:r.favorites,rows:a,tag:null}),t===`favorites`){let t=e.filter(e=>!e.favorite);return t.length&&i.push({id:`rest`,label:r.rest,rows:t,tag:null}),i}let o=new Map;for(let t of e)for(let e of t.tags){let n=e.toLowerCase(),r=o.get(n)??{label:e,rows:[]};r.rows.push(t),o.set(n,r)}for(let e of[...o.keys()].sort()){let t=o.get(e);i.push({id:`tag_${e}`,label:t.label,rows:t.rows,tag:t.label})}let s=e.filter(e=>!e.tags.length&&!e.favorite);return s.length&&i.push({id:`none`,label:n,rows:s,tag:null}),i}function Me(e,t){if(!t)return!0;let n=t.trim().toUpperCase();return e.ticker.toUpperCase().includes(n)||(e.name??``).toUpperCase().includes(n)||e.tags.some(e=>e.toUpperCase().includes(n))}function Ne({entry:t,tags:n,busy:r,onEdit:i,onRemove:a}){let o=e(),[s,c]=(0,w.useState)(t.name),[l,u]=(0,w.useState)(t.name),[d,p]=(0,w.useState)(``),[m,h]=(0,w.useState)(Z(t.shares)),[_,v]=(0,w.useState)(Z(t.cost)),[y,b]=(0,w.useState)([t.shares,t.cost]);l!==t.name&&(u(t.name),c(t.name)),(y[0]!==t.shares||y[1]!==t.cost)&&(b([t.shares,t.cost]),h(Z(t.shares)),v(Z(t.cost)));let x=(e,n)=>{let r=ke(n,t[e]);if(r===void 0){e===`shares`?h(Z(t.shares)):v(Z(t.cost));return}i(t.ticker,{[e]:r})},S=e=>i(t.ticker,{tags:t.tags.some(t=>t.toLowerCase()===e.toLowerCase())?t.tags.filter(t=>t.toLowerCase()!==e.toLowerCase()):[...t.tags,e]}),C=[...new Set([...n,...t.tags])].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase()));return(0,E.jsxs)(`div`,{className:`pr-wrow`,children:[(0,E.jsx)(`button`,{type:`button`,className:t.favorite?`pr-star pr-star-on`:`pr-star`,"aria-label":o(`watchlist.col_favorite`),"aria-pressed":t.favorite,disabled:r,onClick:()=>i(t.ticker,{favorite:!t.favorite}),children:t.favorite?`★`:`☆`}),(0,E.jsx)(g,{ticker:t.ticker,className:`pr-wsym`,children:t.ticker}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wname`,"aria-label":o(`watchlist.col_name`),value:s,disabled:r,onChange:e=>c(e.target.value),onBlur:()=>s!==t.name&&i(t.ticker,{name:s}),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_shares`),placeholder:o(`watchlist.col_shares`),inputMode:`decimal`,value:m,disabled:r,onChange:e=>h(e.target.value),onBlur:()=>x(`shares`,m),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm pr-wnum`,"aria-label":o(`watchlist.col_cost`),placeholder:o(`watchlist.col_cost`),title:o(`watchlist.col_cost_help`),inputMode:`decimal`,value:_,disabled:r,onChange:e=>v(e.target.value),onBlur:()=>x(`cost`,_),onKeyDown:e=>{e.key===`Enter`&&e.currentTarget.blur()}}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:r,onClick:()=>a(t.ticker),children:o(`watchlist.act_remove`)}),(0,E.jsxs)(`details`,{className:`pr-wtags`,children:[(0,E.jsxs)(`summary`,{children:[o(`watchlist.col_tags`),t.tags.length?` · ${t.tags.join(`, `)}`:``]}),(0,E.jsxs)(`div`,{children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:o(`watchlist.col_tags_help`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[C.map(e=>{let n=t.tags.some(t=>t.toLowerCase()===e.toLowerCase());return(0,E.jsx)(f,{on:n,disabled:r,onClick:()=>S(e),children:e},e)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":o(`watchlist.col_tags`),placeholder:o(`watchlist.add_groups_ph`),value:d,disabled:r,onChange:e=>p(e.target.value),onKeyDown:e=>{if(e.key!==`Enter`)return;let t=d.trim();t&&(p(``),S(t))}})]})]})]})]})}function Pe({section:t,busy:n,onRename:r,onDissolve:i}){let a=e(),[o,s]=(0,w.useState)(t.tag??``);return(0,E.jsxs)(`div`,{className:`pr-ghead`,children:[(0,E.jsx)(`span`,{className:`pr-gt`,children:t.label}),(0,E.jsx)(`span`,{className:`pr-gc`,children:t.rows.length}),t.tag!==null&&(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:a(`watchlist.group_manage`)}),(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:a(`watchlist.group_manage_help`)}),(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,"aria-label":a(`watchlist.group_rename`),value:o,disabled:n,onChange:e=>s(e.target.value)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n||!o.trim()||o.trim()===t.tag,onClick:()=>r(t.tag,o.trim()),children:a(`watchlist.group_rename_apply`)}),(0,E.jsx)(`button`,{type:`button`,className:`pr-btn`,disabled:n,title:a(`watchlist.group_delete_help`),onClick:()=>i(t.tag),children:a(`watchlist.group_delete`)})]})]})]})}function Fe({entries:t,reload:n}){let r=e(),[a,o]=(0,w.useState)(!1),[s,c]=(0,w.useState)(null),[l,u]=(0,w.useState)(``),[d,p]=(0,w.useState)([]),[m,h]=(0,w.useState)(`tags`),g=(e,t=`list`)=>{o(!0),c(null),e.then(()=>{o(!1),n()},e=>{if(o(!1),e instanceof x){n();return}c({where:t,message:T(e,r(`common.offline`))})})},_=[...new Set(t.flatMap(e=>e.tags))].sort((e,t)=>e.toLowerCase().localeCompare(t.toLowerCase())),v=new Set(t.map(e=>e.ticker.toUpperCase())),y=new Set(d.map(e=>e.toLowerCase())),b=t.filter(e=>Me(e,l)&&(!y.size||e.tags.some(e=>y.has(e.toLowerCase()))));return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(Oe,{listed:v,tags:_,busy:a,failure:s?.where===`add`?s.message:null,onAdd:e=>g(i(`POST`,`/watchlist`,e),`add`)}),t.length===0?(0,E.jsx)(k,{title:r(`profile.empty_watchlist_title`),children:(0,E.jsx)(`div`,{className:`pr-cardbody`,children:(0,E.jsx)(`p`,{className:`pr-hint`,children:r(`profile.empty_watchlist_body`)})})}):(0,E.jsx)(k,{title:r(`watchlist.list_title`),sub:r(`watchlist.list_sub`),children:(0,E.jsxs)(`div`,{className:`pr-cardbody`,children:[(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`input`,{className:`pr-input pr-input-sm`,type:`search`,"aria-label":r(`watchlist.filter`),placeholder:r(`watchlist.filter_ph`),value:l,onChange:e=>u(e.target.value)}),Ae.map(e=>(0,E.jsx)(f,{on:e===m,onClick:()=>h(e),children:r(`watchlist.group_${e}`)},e))]}),_.length>0&&(0,E.jsxs)(`div`,{className:`pr-chips`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.tag_filter`)}),_.map(e=>(0,E.jsx)(f,{on:y.has(e.toLowerCase()),onClick:()=>p(t=>t.includes(e)?t.filter(t=>t!==e):[...t,e]),children:e},e))]}),(0,E.jsx)(P,{message:s?.where===`list`?s.message:null}),b.length===0?(0,E.jsx)(`p`,{className:`pr-hint`,children:r(`watchlist.no_match`)}):je(b,m,r(`watchlist.g_untagged`),{all:r(`watchlist.g_all`),favorites:r(`watchlist.g_favorites`),rest:r(`watchlist.g_rest`)}).map(e=>(0,E.jsxs)(`div`,{children:[(0,E.jsx)(Pe,{section:e,busy:a,onRename:(e,t)=>g(i(`PATCH`,`/watchlist/tags/${encodeURIComponent(e)}`,{name:t})),onDissolve:e=>g(i(`DELETE`,`/watchlist/tags/${encodeURIComponent(e)}`))}),e.rows.map(t=>(0,E.jsx)(Ne,{entry:t,tags:_,busy:a,onEdit:(e,t)=>g(i(`PATCH`,`/watchlist/${encodeURIComponent(e)}`,t)),onRemove:e=>g(i(`DELETE`,`/watchlist/${encodeURIComponent(e)}`))},`${e.id}_${t.ticker}`))]},e.id)),(0,E.jsxs)(`div`,{className:`pr-foot`,children:[(0,E.jsx)(`span`,{className:`pr-hint`,children:r(`watchlist.count`,{n:t.length})}),(0,E.jsxs)(`details`,{className:`pr-more`,children:[(0,E.jsx)(`summary`,{children:r(`watchlist.how_open`)}),(0,E.jsx)(`div`,{children:(0,E.jsx)(O,{text:r(`watchlist.how`)})})]})]})]})})]})}function Ie({onAdded:n}){let r=e(),[o,s]=(0,w.useState)(0),c=a(()=>t(`/watchlist/suggestions`),[o]),[l,u]=(0,w.useState)(!1),[d,f]=(0,w.useState)(null);if(c.state!==`loaded`||c.data.suggestions.length===0)return null;let p=c.data.suggestions;function m(){u(!0),f(null),p.reduce((e,t)=>e.then(()=>i(`POST`,`/watchlist`,{ticker:t.ticker,name:t.name,tags:t.tags}).then(()=>void 0)),Promise.resolve()).then(()=>{s(e=>e+1),n()}).catch(e=>f(T(e,r(`common.offline`)))).finally(()=>u(!1))}return(0,E.jsxs)(k,{title:r(`profile.focus_suggest_title`),children:[(0,E.jsx)(O,{text:r(`profile.focus_suggest_help`)}),(0,E.jsx)(`ul`,{className:`pr-examples`,children:p.map(e=>(0,E.jsxs)(`li`,{children:[(0,E.jsx)(g,{ticker:e.ticker,className:`pr-wsym`}),(0,E.jsx)(`span`,{children:e.name})]},e.ticker))}),(0,E.jsx)(`button`,{type:`button`,className:`pr-linkbtn`,disabled:l,onClick:m,children:r(`profile.focus_suggest_add`,{n:p.length})}),(0,E.jsx)(P,{message:d})]})}function Le({query:e}){return(0,E.jsx)(`div`,{className:`pr-main`,children:(0,E.jsx)(_,{query:e,children:(e,t)=>(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(Fe,{entries:e.entries,reload:t}),(0,E.jsx)(Ie,{onAdded:t})]})})})}var Q=[{id:`prefs`,label:`profile.preferences`},{id:`iv`,label:`profile.iv_section`},{id:`watch`,label:`profile.watchlist`},{id:`notify`,label:`profile.notifications`},{id:`journal`,label:`journal.tab`}];function $(e,t){return(t?.trim()?t.trim().split(/\s+/):(e.split(`@`)[0]??``).split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(e=>e[0]??``).join(``).toUpperCase()||`?`}function Re(){return n()?(0,E.jsx)(b,{text:`common.sign_in`}):(0,E.jsx)(ze,{})}function ze(){let n=e(),r=y(),{params:i,setParams:o}=p(),c=Te(n(`common.offline`)),l=a(()=>t(`/me`),[]),u=l.state===`loaded`?l.data:null,d=a(()=>t(`/watchlist`),[]),f=d.state===`loaded`?d.data.entries.length:0,[m,h]=(0,w.useState)(!1),g=u?.name?.trim()||``,_=i.get(`tab`)??``,v=Q.some(e=>e.id===_)?_:`prefs`,b=r.email??``;return(0,E.jsxs)(E.Fragment,{children:[(0,E.jsx)(`style`,{href:`ag-profile`,precedence:`default`,children:Ee}),(0,E.jsxs)(`header`,{className:`pr-head`,children:[(0,E.jsx)(`h1`,{className:`pr-title`,children:n(`nav.profile`)}),(0,E.jsx)(`span`,{className:`pr-savehint`,children:n(`profile.saves_instantly`)})]}),(0,E.jsx)(k,{children:(0,E.jsxs)(`div`,{className:`pr-ident`,children:[(0,E.jsx)(`div`,{className:`pr-avatar`,"aria-hidden":`true`,children:u?.picture&&!m?(0,E.jsx)(`img`,{src:u.picture,alt:``,referrerPolicy:`no-referrer`,onError:()=>h(!0)}):$(b,g)}),(0,E.jsxs)(`div`,{className:`pr-ident-t`,children:[g&&g!==b&&(0,E.jsx)(`span`,{className:`pr-ident-n`,children:g}),(0,E.jsx)(`span`,{className:`pr-ident-e`,children:b})]}),(0,E.jsx)(`div`,{className:`pr-ident-r`,children:(0,E.jsx)(`span`,{className:`pr-ident-note`,children:n(`profile.account_scope`)})}),(0,E.jsx)(`a`,{className:`pr-signout`,href:`/auth/logout`,onClick:e=>{e.preventDefault(),s(`/auth/logout`)},children:n(`common.log_out`)})]})}),(0,E.jsx)(`div`,{className:`pr-tabs`,role:`tablist`,"aria-label":n(`nav.profile`),children:Q.map(e=>(0,E.jsxs)(`button`,{type:`button`,role:`tab`,"aria-selected":e.id===v,className:e.id===v?`pr-tab pr-tab-on`:`pr-tab`,onClick:()=>o({tab:e.id}),children:[n(e.label),e.id===`watch`&&f>0&&(0,E.jsxs)(E.Fragment,{children:[` `,(0,E.jsx)(`span`,{className:`pr-tab-n`,children:f})]})]},e.id))}),v===`prefs`&&(0,E.jsx)(Ce,{...c,owner:l.state===`loaded`?!!u?.owner:null}),v===`iv`&&(0,E.jsx)(oe,{}),v===`watch`&&(0,E.jsx)(Le,{query:d}),v===`notify`&&(0,E.jsx)(ae,{...c}),v===`journal`&&(0,E.jsx)(le,{})]})}export{Re as default,$ as initials};