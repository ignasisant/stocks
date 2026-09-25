import{A as W,b as ee,r as f,N as M,g as E,s as z,j as e,u as L,d as $,L as ae,S as ie,n as te,f as se,l as ne,p as le}from"./app.js";import{T as re}from"./tickers.js";function U(a,i){return a instanceof W?a.detail:i}const oe=3e3;function ce(a){const{reload:i}=ee(),[s,r]=f.useState(null),[n,t]=f.useState(null),[p,d]=f.useState(!1),[u,h]=f.useState(!1),[v,l]=f.useState(null),[b,g]=f.useState(null),j=f.useCallback(c=>c instanceof M?(i(),null):{kind:"failed",error:U(c,a)},[i,a]);f.useEffect(()=>{let c=!0;return E("/notify/telegram").then(o=>c&&r(o),o=>{c&&g(j(o))}),()=>{c=!1}},[j]);const[y,_]=f.useState(()=>typeof document>"u"||!document.hidden);f.useEffect(()=>{const c=()=>_(!document.hidden);return document.addEventListener("visibilitychange",c),()=>document.removeEventListener("visibilitychange",c)},[]),f.useEffect(()=>{if(!n||!y)return;if(Date.now()>=n.deadline){t(null),d(!0);return}let c=!0;const o=window.setInterval(()=>{if(Date.now()>=n.deadline){t(null),d(!0);return}E("/notify/telegram").then(x=>{c&&(h(!1),r(x),x.linked&&t(null))},()=>c&&h(!0))},oe);return()=>{c=!1,window.clearInterval(o)}},[n,y]);const T=f.useCallback(()=>{l("connect"),g(null),d(!1),z("POST","/notify/telegram").then(c=>{l(null),t({code:c.code,deepLink:c.deep_link,bot:c.bot,deadline:Date.now()+c.expires_in*1e3})},c=>{l(null),g(j(c))})},[j]),m=f.useCallback(()=>{l("test"),g(null),z("POST","/notify/telegram/test").then(c=>{l(null),r(c),g({kind:"test_sent"})},c=>{if(l(null),c instanceof M){i();return}g({kind:"test_failed",error:U(c,a)})})},[i,a]),w=f.useCallback(()=>{l("unlink"),g(null),z("DELETE","/notify/telegram").then(c=>{l(null),r(c),t(null),d(!1),g({kind:"unlinked"})},c=>{l(null),g(j(c))})},[j]);return{state:s,pending:n,expired:p,stalled:u,busy:v,note:b,connect:T,test:m,unlink:w}}function K({text:a}){const i=a.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return e.jsx(e.Fragment,{children:i.map((s,r)=>s.startsWith("**")&&s.endsWith("**")&&s.length>4?e.jsx("b",{children:s.slice(2,-2)},r):s.startsWith("`")&&s.endsWith("`")&&s.length>2?e.jsx("code",{children:s.slice(1,-1)},r):e.jsx(f.Fragment,{children:s},r))})}function I({text:a,className:i}){const s=[];let r=[];const n=t=>{r.length&&(s.push(e.jsx("ul",{children:r.map((p,d)=>e.jsx("li",{children:e.jsx(K,{text:p})},d))},`ul${t}`)),r=[])};return a.split(`
`).forEach((t,p)=>{const d=t.trim();if(d.startsWith("- ")){r.push(d.slice(2));return}n(p),d&&s.push(e.jsx("p",{children:e.jsx(K,{text:d})},p))}),n(-1),e.jsx("div",{className:i??"pf-prose",children:s})}function S({title:a,sub:i,note:s,children:r}){return e.jsxs("section",{className:"pf-card",children:[a!==void 0&&e.jsxs("div",{className:"pf-cardhead",children:[e.jsx("span",{className:"pf-cardtitle",children:a}),i&&e.jsx("span",{className:"pf-cardsub",children:i}),s&&e.jsx("span",{className:"pf-cardnote",children:s})]}),r]})}function k({label:a,help:i,middle:s,children:r}){return e.jsxs("div",{className:s?"pf-row pf-row-mid":"pf-row",children:[e.jsxs("div",{className:"pf-row-l",children:[e.jsx("span",{className:"pf-row-lab",children:a}),i&&e.jsx("span",{className:"pf-row-help",children:e.jsx(K,{text:i})})]}),e.jsx("div",{className:"pf-row-ctl",children:r})]})}function A({value:a,options:i,labelOf:s,onPick:r,label:n,disabled:t}){return e.jsx("select",{className:"pf-select","aria-label":n,value:a,disabled:t,onChange:p=>r(p.target.value),children:i.map(p=>e.jsx("option",{value:p,children:s(p)},p))})}function G({value:a,options:i,labelOf:s,onPick:r,disabled:n}){return e.jsx("div",{className:"pf-chips",children:i.map(t=>e.jsx("button",{type:"button",className:t===a?"pf-chip pf-chip-on":"pf-chip","aria-pressed":t===a,disabled:n,onClick:()=>r(t),children:s(t)},t))})}function R({checked:a,onToggle:i,label:s,disabled:r}){return e.jsx("label",{className:"pf-switch",children:e.jsx("input",{type:"checkbox",checked:a,disabled:r,"aria-label":s,onChange:n=>i(n.target.checked)})})}function N({message:a}){return a?e.jsx("p",{className:"pf-err",role:"alert",children:a}):null}function H({values:a,options:i,labelOf:s,onToggle:r,disabled:n}){const t=new Set(a);return e.jsx("div",{className:"pf-chips",children:i.map(p=>{const d=t.has(p);return e.jsx("button",{type:"button",className:d?"pf-chip pf-chip-on":"pf-chip","aria-pressed":d,disabled:n,onClick:()=>r(p,!d),children:s(p)},p)})})}function pe({prefs:a,saving:i,failure:s,save:r}){const n=L(),t=ce(n("common.offline")),p=h=>s?.field===h?s.message:null,d=t.state?t.state.linked:a.telegram_linked,u=t.state?.configured??(a.telegram_linked?!0:null);return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(S,{title:n("profile.notify_channel_title"),sub:n("profile.notify_channel_sub"),children:[e.jsxs("div",{className:"pf-cardbody",children:[u===null&&!t.note&&e.jsx("p",{className:"pf-busy",children:n("common.loading")}),u===!1&&e.jsx("p",{className:"pf-hint",children:n("profile.tg_not_configured")}),u===!0&&d&&e.jsxs("span",{className:"pf-chips",children:[e.jsx("span",{className:"pf-badge",children:n("profile.notify_connected")}),e.jsx("span",{className:"pf-hint",children:n("profile.tg_linked_as",{handle:t.state?.username?`@${t.state.username}`:""}).trim()})]}),u===!0&&!d&&!t.pending&&e.jsxs("span",{className:"pf-chips",children:[e.jsx("button",{type:"button",className:"pf-btn pf-btn-p",disabled:t.busy==="connect",onClick:t.connect,children:n("profile.tg_connect")}),t.expired&&e.jsx("span",{className:"pf-warn",children:n("profile.tg_expired")})]}),u===!0&&!d&&t.pending&&e.jsxs(e.Fragment,{children:[e.jsx("a",{className:"pf-linkbtn",href:t.pending.deepLink,target:"_blank",rel:"noreferrer noopener",children:n("profile.tg_open")}),e.jsx("p",{className:"pf-hint",children:e.jsx(K,{text:n("profile.tg_manual",{bot:t.pending.bot,code:t.pending.code})})}),e.jsx("p",{className:"pf-busy",children:t.stalled?n("profile.tg_poll_error"):n("profile.tg_waiting")})]}),t.note?.kind==="failed"&&e.jsx(N,{message:t.note.error}),t.note?.kind==="unlinked"&&e.jsx("p",{className:"pf-hint",children:n("profile.tg_unlinked")})]}),u===!0&&d&&e.jsxs(e.Fragment,{children:[e.jsxs(k,{label:n("profile.notify_test_row"),help:n("profile.notify_test_help"),middle:!0,children:[e.jsx("button",{type:"button",className:"pf-btn",disabled:t.busy==="test",onClick:t.test,children:n("profile.tg_test")}),t.note?.kind==="test_sent"&&e.jsx("p",{className:"pf-hint",children:n("profile.tg_test_sent")}),t.note?.kind==="test_failed"&&e.jsx(N,{message:n("profile.tg_test_failed",{error:t.note.error})})]}),e.jsx(k,{label:n("profile.notify_unlink_row"),help:n("profile.notify_unlink_help"),middle:!0,children:e.jsx("button",{type:"button",className:"pf-btn",disabled:t.busy==="unlink",onClick:t.unlink,children:n("profile.tg_unlink")})})]})]}),u===!0&&d&&e.jsxs(S,{title:n("profile.notify_what_title"),sub:n("profile.notify_what_sub"),children:[e.jsxs(k,{label:n("profile.notify_digest"),help:n("profile.notify_digest_help"),middle:!0,children:[e.jsx(R,{label:n("profile.notify_digest"),checked:a.notify_digest,disabled:i==="notify_digest",onToggle:h=>r("notify_digest",h)}),e.jsx(N,{message:p("notify_digest")})]}),e.jsxs(k,{label:n("profile.notify_weekly"),help:n("profile.notify_weekly_help"),middle:!0,children:[e.jsx(R,{label:n("profile.notify_weekly"),checked:a.notify_weekly,disabled:i==="notify_weekly",onToggle:h=>r("notify_weekly",h)}),e.jsx(N,{message:p("notify_weekly")})]}),e.jsxs(k,{label:n("profile.notify_alerts"),help:n("profile.notify_alerts_help"),middle:!0,children:[e.jsx(R,{label:n("profile.notify_alerts"),checked:a.notify_alerts,disabled:i==="notify_alerts",onToggle:h=>r("notify_alerts",h)}),e.jsx(N,{message:p("notify_alerts")})]})]})]}),e.jsx("aside",{className:"pf-rail",children:e.jsx(S,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("b",{className:"pf-sum-t",children:n("profile.notify_caption")}),e.jsx(I,{text:n("profile.tg_how_body")})]})})})]})}function de(){const a=$(async()=>{const[i,s]=await Promise.all([E("/profile-options"),E("/profile")]);return{options:i,profile:s}},[]);return e.jsx(ae,{query:a,skeleton:e.jsx(ie,{rows:8}),children:i=>e.jsx(fe,{options:i.options,stored:i.profile})})}function fe({options:a,stored:i}){const s=L(),[r,n]=f.useState(i),[t,p]=f.useState(null),[d,u]=f.useState(null);function h(l,b){n(l),p(b),u(null),z("PUT","/profile",{risk:l.risk,horizon:l.horizon,focus:l.focus,constraints:l.constraints,notes:l.notes}).then(g=>n(g)).catch(g=>{n(i),u(U(g,s("common.offline")))}).finally(()=>p(null))}const v=l=>b=>s(`profile.iv_${l}_${b}`);return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(S,{title:s("profile.iv_how_title"),sub:s("profile.iv_how_sub"),children:[e.jsx(k,{label:s("profile.iv_risk"),help:s("profile.iv_risk_help"),children:e.jsx(A,{label:s("profile.iv_risk"),value:r.risk,options:a.risk,labelOf:v("risk"),disabled:t==="risk",onPick:l=>l!==r.risk&&h({...r,risk:l},"risk")})}),e.jsx(k,{label:s("profile.iv_horizon"),help:s("profile.iv_horizon_help"),children:e.jsx(A,{label:s("profile.iv_horizon"),value:r.horizon,options:a.horizon,labelOf:v("horizon"),disabled:t==="horizon",onPick:l=>l!==r.horizon&&h({...r,horizon:l},"horizon")})})]}),e.jsxs(S,{title:s("profile.iv_what_title"),sub:s("profile.iv_what_sub"),children:[e.jsx(k,{label:s("profile.iv_focus"),help:s("profile.iv_focus_help"),children:e.jsx(H,{values:r.focus,options:a.focus,labelOf:v("focus"),disabled:t==="focus",onToggle:(l,b)=>h({...r,focus:b?[...r.focus,l]:r.focus.filter(g=>g!==l)},"focus")})}),e.jsx(k,{label:s("profile.iv_constraints"),help:s("profile.iv_constraints_help"),children:e.jsx(H,{values:r.constraints,options:a.constraints,labelOf:v("constraints"),disabled:t==="constraints",onToggle:(l,b)=>h({...r,constraints:b?[...r.constraints,l]:r.constraints.filter(g=>g!==l)},"constraints")})})]}),e.jsxs(S,{title:s("profile.iv_notes_title"),sub:s("profile.iv_caption"),children:[e.jsx(k,{label:s("profile.iv_notes"),help:s("profile.iv_notes_help"),children:e.jsx(ue,{value:r.notes,placeholder:s("profile.iv_notes_ph"),label:s("profile.iv_notes"),disabled:t==="notes",onCommit:l=>l!==r.notes&&h({...r,notes:l},"notes")})}),e.jsx(N,{message:d})]})]}),e.jsx("aside",{className:"pf-rail",children:e.jsxs(S,{children:[e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:s("profile.iv_sum_title")}),e.jsx(F,{label:s("profile.iv_risk"),value:s(`profile.iv_risk_${r.risk}`)}),e.jsx(F,{label:s("profile.iv_horizon"),value:s(`profile.iv_horizon_${r.horizon}`)}),e.jsx(F,{label:s("profile.iv_focus"),value:q(r.focus,v("focus"),s("profile.iv_sum_none"))}),e.jsx(F,{label:s("profile.iv_constraints"),value:q(r.constraints,v("constraints"),s("profile.iv_sum_none"))}),e.jsx("div",{className:"pf-sum-rule"}),e.jsx("span",{className:"pf-sum-note",children:s("profile.iv_privacy")})]}),r.persona?e.jsxs("details",{className:"pf-persona",children:[e.jsx("summary",{children:s("profile.iv_persona_open")}),e.jsx("p",{className:"pf-sum-note",children:s("profile.iv_persona_help")}),e.jsx("code",{className:"pf-persona-text",children:r.persona})]}):null]})})]})}function q(a,i,s){return a.length?a.map(i).join(", "):s}function F({label:a,value:i}){return e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:a}),e.jsx("b",{children:i})]})}function ue({value:a,label:i,placeholder:s,disabled:r,onCommit:n}){const[t,p]=f.useState(a);return f.useEffect(()=>p(a),[a]),e.jsx("textarea",{className:"pf-notes",rows:4,value:t,"aria-label":i,placeholder:s,disabled:r,onChange:d=>p(d.target.value),onBlur:()=>n(t.trim())})}const he=["EUR","USD","GBP","CHF","SEK","NOK","DKK","PLN","CZK","CAD","AUD"],B=["EUR","USD","GBP","CHF","SEK"],ge={EUR:"€",USD:"$",GBP:"£",CHF:"₣",SEK:"kr",NOK:"kr",DKK:"kr",PLN:"zł",CZK:"Kč",CAD:"CA$",AUD:"A$"};function Q(a){const i=ge[a];return i&&i!==a?`${i} ${a}`:a}const Y={en:"English",es:"Español"},Z=[0,.08,.09];function O(a,i){const s=String(i??"").replace("_","-").split("-")[0]?.toUpperCase();return a.jurisdictions.find(r=>r.code===s)??null}function me(a,i){if(i)return O(a,i)??O(a,a.default);const s=String(navigator.language??"").replace("_","-").split("-"),r=s.length>1&&s[1]?.length===2?s[1]:"";return O(a,r)??O(a,a.default)}function xe(a,i){return a.trim().toLowerCase()===i.trim().toLowerCase()&&i!==""}function be({email:a,onClose:i}){const s=L(),[r,n]=f.useState(""),[t,p]=f.useState(!1),[d,u]=f.useState(null),h=xe(r,a);f.useEffect(()=>{const l=b=>{b.key==="Escape"&&!t&&i()};return window.addEventListener("keydown",l),()=>window.removeEventListener("keydown",l)},[i,t]);const v=()=>{p(!0),u(null),z("DELETE","/account",{confirm:r.trim()}).then(l=>{const b=l.sign_out,g=b.startsWith("/")&&!b.startsWith("//")?b:"/auth/logout";window.location.assign(g)},l=>{if(p(!1),l instanceof M){window.location.assign("/auth/logout");return}u(l instanceof W&&l.status===422?l.detail:l instanceof W?s("profile.delete_failed"):s("common.offline"))})};return e.jsx("div",{className:"pf-modal",onClick:l=>{l.target===l.currentTarget&&!t&&i()},children:e.jsxs("div",{className:"pf-modal-card",role:"dialog","aria-modal":"true","aria-label":s("profile.delete_title"),children:[e.jsx("h2",{className:"pf-modal-t",children:s("profile.delete_title")}),e.jsx(I,{text:s("profile.delete_body")}),e.jsxs("label",{className:"pf-modal-confirm",children:[e.jsx("span",{className:"pf-hint",children:s("profile.delete_confirm")}),e.jsx("input",{className:"pf-input pf-input-wide",type:"text",autoFocus:!0,autoComplete:"off",autoCapitalize:"off",spellCheck:!1,placeholder:a,value:r,disabled:t,onChange:l=>n(l.target.value)})]}),e.jsx(N,{message:d}),e.jsxs("div",{className:"pf-modal-foot",children:[e.jsx("button",{type:"button",className:"pf-btn",disabled:t,onClick:i,children:s("common.cancel")}),e.jsx("button",{type:"button",className:"pf-btn pf-btn-danger",disabled:!h||t,onClick:v,children:s("profile.delete_button")})]})]})})}function ve(){const a=L(),i=te(),[s,r]=f.useState(!1);return e.jsxs(k,{label:a("profile.delete_row_title"),help:a("profile.delete_row_help"),middle:!0,children:[e.jsx("button",{type:"button",className:"pf-btn",onClick:()=>r(!0),children:a("profile.delete_open")}),s&&e.jsx(be,{email:i.email??"",onClose:()=>r(!1)})]})}function we(a){const i=Object.values(a);return i.length?[i.filter(Boolean).length,i.length]:null}function _e(){const a=L(),{setParams:i}=se(),s=$(()=>E("/onboarding"),[]),r=s.state==="loaded"?we(s.data.setup):null,n=()=>{i({tour:"1"})};return e.jsx(S,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:a("tour.launch")}),e.jsx("span",{className:"pf-sum-note",children:a("tour.launch_caption")}),e.jsx("button",{type:"button",className:"pf-btn pf-btn-p pf-selfstart",onClick:n,children:a("tour.launch_start")}),r&&e.jsxs("div",{className:"pf-prog",role:"progressbar","aria-label":a("home.setup_progress",{done:r[0],total:r[1]}),"aria-valuemin":0,"aria-valuemax":r[1],"aria-valuenow":r[0],children:[e.jsx("div",{className:"pf-prog-track",children:e.jsx("div",{className:"pf-prog-fill",style:{width:`${Math.round(r[0]/r[1]*100)}%`}})}),e.jsxs("span",{className:"pf-prog-n",children:[r[0],"/",r[1]]})]})]})})}const P="auto";function J({value:a,onCommit:i,label:s,min:r,max:n,step:t,suffix:p,disabled:d}){const[u,h]=f.useState(String(a)),[v,l]=f.useState(a);v!==a&&(l(a),h(String(a)));const b=()=>{const g=Number(u);if(u.trim()===""||Number.isNaN(g)){h(String(a));return}g!==a&&i(g)};return e.jsxs("span",{className:"pf-chips",children:[e.jsx("input",{className:"pf-input",type:"number",inputMode:"decimal","aria-label":s,value:u,min:r,max:n,step:t,disabled:d,onChange:g=>h(g.target.value),onBlur:b,onKeyDown:g=>{g.key==="Enter"&&g.currentTarget.blur()}}),p&&e.jsx("span",{className:"pf-hint",children:p})]})}function je({prefs:a,saving:i,failure:s,save:r,owner:n}){const t=L(),p=$(()=>E("/import/last"),[]),d=$(()=>E("/portfolio/transactions",{limit:1}),[]),u=[P,...Object.keys(Y)],h=c=>c===P?t("profile.lang_auto"):Y[c]??c,v=B.includes(a.currency)?[...B]:[...B,a.currency],l=he.filter(c=>!v.includes(c)),b=$(()=>E("/jurisdictions"),[]),g=b.state==="loaded"?b.data:null,j=[P,...(g?.jurisdictions??[]).map(c=>c.code)],y=c=>{if(c===P)return`🌐 ${t("profile.tax_residence_auto")}`;const o=g?.jurisdictions.find(C=>C.code===c),x=t(`profile.tax_residence_${c.toLowerCase()}`);return`${o?.flag??""} ${x}`.trim()},_=g?me(g,a.tax_residence):null,T=_?_.year_start[0]===1&&_.year_start[1]===1?t("profile.tax_year_calendar"):t("profile.tax_year_from",{day:_.year_start[1],month:_.year_start[0]}):"",m=_?t(`profile.tax_match_${_.matching}`):"",w=c=>s?.field===c?s.message:null;return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(S,{title:t("profile.ui_section"),sub:t("profile.ui_section_sub"),children:[e.jsxs(k,{label:t("profile.language"),help:t("profile.language_caption"),children:[e.jsx(A,{label:t("profile.language"),value:a.language??P,options:u,labelOf:h,disabled:i==="language",onPick:c=>{const o=c===P?null:c;o!==a.language&&r("language",o)}}),e.jsx(N,{message:w("language")})]}),e.jsxs(k,{label:t("profile.display_currency"),help:t("profile.currency_caption"),children:[e.jsx(G,{value:a.currency,options:v,labelOf:Q,disabled:i==="currency",onPick:c=>c!==a.currency&&r("currency",c)}),l.length>0&&e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:t("profile.currency_more",{n:l.length})}),e.jsx("div",{children:e.jsx(G,{value:a.currency,options:l,labelOf:Q,disabled:i==="currency",onPick:c=>c!==a.currency&&r("currency",c)})})]}),l.length>0&&e.jsx("span",{className:"pf-morehint",children:l.join(" · ")}),e.jsx(N,{message:w("currency")})]})]}),e.jsxs(S,{title:t("profile.tax_section"),note:t("profile.tax_legal_note"),children:[e.jsxs(k,{label:t("profile.tax_residence"),help:t("profile.tax_residence_caption"),children:[e.jsx(A,{label:t("profile.tax_residence"),value:a.tax_residence??P,options:j,labelOf:y,disabled:i==="tax_residence",onPick:c=>{const o=c===P?null:c;o!==a.tax_residence&&r("tax_residence",o)}}),e.jsx(N,{message:w("tax_residence")}),_?e.jsxs("div",{className:"pf-rules",children:[e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:t("profile.tax_rule_cost")}),e.jsxs("span",{className:"pf-rule-v",children:[_.currency," · ",t("profile.tax_rule_fx")]})]}),e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:t("profile.tax_rule_matching")}),e.jsx("span",{className:"pf-rule-v",children:m})]}),e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:t("profile.tax_rule_year")}),e.jsx("span",{className:"pf-rule-v",children:T})]})]}):null]}),(_?.settings_fields??[]).map(c=>{const o=_.code.toLowerCase();return c==="filing_status"?e.jsxs(k,{label:t("profile.tax_filing_status"),help:t(`profile.tax_filing_status_caption_${o}`),children:[e.jsx(A,{label:t("profile.tax_filing_status"),value:_.filing_statuses.includes(a.tax_filing_status)?a.tax_filing_status:_.filing_statuses[0]??"single",options:_.filing_statuses,labelOf:x=>t(`profile.tax_status_${x}`),disabled:i==="tax_filing_status",onPick:x=>r("tax_filing_status",x)}),e.jsx(N,{message:w("tax_filing_status")})]},c):c==="church_tax_rate"?e.jsxs(k,{label:t("profile.tax_church"),help:t("profile.tax_church_caption"),children:[e.jsx(A,{label:t("profile.tax_church"),value:String(Z.includes(a.tax_church_rate)?a.tax_church_rate:0),options:Z.map(String),labelOf:x=>t(`profile.tax_church_${Math.round(Number(x)*100)}`),disabled:i==="tax_church_rate",onPick:x=>r("tax_church_rate",Number(x))}),e.jsx(N,{message:w("tax_church_rate")})]},c):c==="other_income"?e.jsxs(k,{label:t("profile.tax_other_income"),help:t(`profile.tax_other_income_caption_${o}`),children:[e.jsx(J,{label:t("profile.tax_other_income"),value:a.tax_other_income,min:0,step:1e3,suffix:_.currency,disabled:i==="tax_other_income",onCommit:x=>r("tax_other_income",x)}),e.jsx(N,{message:w("tax_other_income")})]},c):c==="subnational_rate"?e.jsxs(k,{label:t("profile.tax_subnational"),help:t("profile.tax_subnational_caption"),children:[e.jsx(J,{label:t("profile.tax_subnational"),value:Math.round(a.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:"%",disabled:i==="tax_subnational_rate",onCommit:x=>r("tax_subnational_rate",Math.round(x*100)/1e4)}),e.jsx(N,{message:w("tax_subnational_rate")})]},c):e.jsxs(k,{label:t("profile.tax_niit"),help:t("profile.tax_niit_caption"),middle:!0,children:[e.jsx(R,{label:t("profile.tax_niit"),checked:a.tax_niit,disabled:i==="tax_niit",onToggle:x=>r("tax_niit",x)}),e.jsx(N,{message:w("tax_niit")})]},c)})]}),e.jsxs(S,{title:t("profile.data_section"),children:[e.jsx(k,{label:t("profile.export_title"),help:t("profile.export_help"),children:d.state==="loaded"&&d.data.total>0?e.jsx("a",{className:"pf-download",href:"/api/v1/portfolio/transactions.csv",children:t("profile.export_button")}):e.jsx("span",{className:"pf-muted",children:t("profile.export_none")})}),n===!1&&e.jsx(ve,{})]})]}),e.jsxs("aside",{className:"pf-rail",children:[e.jsx(_e,{}),e.jsx(S,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:t("profile.summary_title")}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:t("profile.language")}),e.jsx("b",{children:(h(a.language??P).split("(")[0]??"").trim()})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:t("profile.display_currency")}),e.jsx("b",{children:a.currency})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:t("profile.tax_section")}),e.jsx("b",{children:_?`${_.flag?`${_.flag} `:""}${(t(`profile.tax_residence_${_.code.toLowerCase()}`).split("—")[0]??"").trim()} · ${m}`:t("common.loading")})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:t("profile.summary_last_import")}),e.jsx("b",{children:p.state==="loaded"?p.data.imported_at?.slice(0,10)??t("profile.summary_never"):t("common.loading")})]}),e.jsx("div",{className:"pf-sum-rule"}),e.jsx("span",{className:"pf-sum-note",children:t("profile.summary_note")})]})})]})]})}const ye=new Set(["currency","language"]);function ke(a){const i=ee(),[s,r]=f.useState(i.prefs),[n,t]=f.useState(null),[p,d]=f.useState(null),u=f.useCallback((h,v)=>{t(h),d(null),z("PATCH","/prefs",{[h]:v}).then(l=>{t(null),r(l),ye.has(h)&&i.reload()},l=>{if(t(null),l instanceof M){i.reload();return}d({field:h,message:U(l,a)})})},[i,a]);return{prefs:s,saving:n,failure:p,save:u}}const Ne=`
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
`,Ce={analyze:"raw"},V=2;function Se({listed:a,tags:i,onAdd:s,busy:r,failure:n}){const t=L(),[p,d]=f.useState(""),[u,h]=f.useState([]),[v,l]=f.useState(""),[b,g]=f.useState(!1),[j,y]=f.useState(null),[_,T]=f.useState(null),m=p.trim();f.useEffect(()=>{if(m.length<V){y(null);return}let o=!0;const x=window.setTimeout(()=>{E("/search",{q:m,limit:8}).then(C=>o&&(y(C.matches),T(null)),()=>o&&(y([]),T(t("common.offline"))))},250);return()=>{o=!1,window.clearTimeout(x)}},[m]);const w=o=>{s({ticker:o.ticker,name:o.name,...b?{favorite:!0}:{},...u.length?{tags:u}:{}}),d(""),y(null)},c=[...new Set([...i,...u])].sort((o,x)=>o.toLowerCase().localeCompare(x.toLowerCase()));return e.jsx(S,{title:t("watchlist.add_title"),sub:t("watchlist.add_sub"),children:e.jsxs("div",{className:"pf-cardbody",children:[e.jsx("input",{className:"pf-input pf-input-wide",type:"search","aria-label":t("watchlist.add_title"),placeholder:t("watchlist.add_placeholder"),value:p,onChange:o=>d(o.target.value)}),e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:t("watchlist.add_groups")}),c.map(o=>e.jsx("button",{type:"button",className:u.includes(o)?"pf-chip pf-chip-on":"pf-chip","aria-pressed":u.includes(o),onClick:()=>h(x=>x.includes(o)?x.filter(C=>C!==o):[...x,o]),children:o},o)),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":t("watchlist.add_groups"),placeholder:t("watchlist.add_groups_ph"),value:v,onChange:o=>l(o.target.value),onKeyDown:o=>{if(o.key!=="Enter")return;const x=v.trim();x&&(h(C=>C.includes(x)?C:[...C,x]),l(""))}})]}),e.jsx("span",{className:"pf-hint",children:t("watchlist.add_groups_help")}),e.jsxs("label",{className:"pf-switch",children:[e.jsx("input",{type:"checkbox",checked:b,onChange:o=>g(o.target.checked)}),e.jsx("span",{children:t("watchlist.add_fav")})]}),e.jsx(N,{message:n??_}),m.length<V?e.jsx("p",{className:"pf-hint",children:t("watchlist.add_hint")}):j===null?e.jsx("p",{className:"pf-hint",children:t("common.loading")}):j.length===0?e.jsx("p",{className:"pf-hint",children:t("watchlist.add_none")}):e.jsx("div",{className:"pf-res",children:j.map(o=>{const x=a.has(o.ticker.toUpperCase()),C=Ce[o.kind]??o.kind;return e.jsxs("button",{type:"button",className:"pf-btn pf-resrow",disabled:x||r,title:t(x?"watchlist.add_listed":`watchlist.kind_${C}`),onClick:()=>w(o),children:[e.jsx("span",{className:"pf-resrow-t",children:o.ticker}),e.jsx("span",{className:"pf-resrow-n",children:o.name}),e.jsx("span",{className:"pf-resrow-k",children:x?t("watchlist.add_listed"):(o.exchange??"")||t(`watchlist.kind_${C}`)})]},o.ticker)})})]})})}const D=a=>a?String(a):"";function ze(a,i){const s=a.trim().replace(",","."),r=s===""?0:Number(s);if(!(!Number.isFinite(r)||r<0))return r===(i??0)?void 0:r}const Ee=["tags","favorites","flat"];function Le(a,i,s,r){if(i==="flat")return[{id:"all",label:r.all,rows:a,tag:null}];const n=[],t=a.filter(u=>u.favorite);if(t.length&&n.push({id:"fav",label:r.favorites,rows:t,tag:null}),i==="favorites"){const u=a.filter(h=>!h.favorite);return u.length&&n.push({id:"rest",label:r.rest,rows:u,tag:null}),n}const p=new Map;for(const u of a)for(const h of u.tags){const v=h.toLowerCase(),l=p.get(v)??{label:h,rows:[]};l.rows.push(u),p.set(v,l)}for(const u of[...p.keys()].sort()){const h=p.get(u);n.push({id:`tag_${u}`,label:h.label,rows:h.rows,tag:h.label})}const d=a.filter(u=>!u.tags.length&&!u.favorite);return d.length&&n.push({id:"none",label:s,rows:d,tag:null}),n}function Te(a,i){if(!i)return!0;const s=i.trim().toUpperCase();return a.ticker.toUpperCase().includes(s)||(a.name??"").toUpperCase().includes(s)||a.tags.some(r=>r.toUpperCase().includes(s))}function Pe({entry:a,tags:i,busy:s,onEdit:r,onRemove:n}){const t=L(),[p,d]=f.useState(a.name),[u,h]=f.useState(a.name),[v,l]=f.useState(""),[b,g]=f.useState(D(a.shares)),[j,y]=f.useState(D(a.cost)),[_,T]=f.useState([a.shares,a.cost]);u!==a.name&&(h(a.name),d(a.name)),(_[0]!==a.shares||_[1]!==a.cost)&&(T([a.shares,a.cost]),g(D(a.shares)),y(D(a.cost)));const m=(o,x)=>{const C=ze(x,a[o]);if(C===void 0){o==="shares"?g(D(a.shares)):y(D(a.cost));return}r(a.ticker,{[o]:C})},w=o=>r(a.ticker,{tags:a.tags.some(x=>x.toLowerCase()===o.toLowerCase())?a.tags.filter(x=>x.toLowerCase()!==o.toLowerCase()):[...a.tags,o]}),c=[...new Set([...i,...a.tags])].sort((o,x)=>o.toLowerCase().localeCompare(x.toLowerCase()));return e.jsxs("div",{className:"pf-wrow",children:[e.jsx("button",{type:"button",className:a.favorite?"pf-star pf-star-on":"pf-star","aria-label":t("watchlist.col_favorite"),"aria-pressed":a.favorite,disabled:s,onClick:()=>r(a.ticker,{favorite:!a.favorite}),children:a.favorite?"★":"☆"}),e.jsx(re,{ticker:a.ticker,className:"pf-wsym",children:a.ticker}),e.jsx("input",{className:"pf-input pf-input-sm pf-wname","aria-label":t("watchlist.col_name"),value:p,disabled:s,onChange:o=>d(o.target.value),onBlur:()=>p!==a.name&&r(a.ticker,{name:p}),onKeyDown:o=>{o.key==="Enter"&&o.currentTarget.blur()}}),e.jsx("input",{className:"pf-input pf-input-sm pf-wnum","aria-label":t("watchlist.col_shares"),placeholder:t("watchlist.col_shares"),inputMode:"decimal",value:b,disabled:s,onChange:o=>g(o.target.value),onBlur:()=>m("shares",b),onKeyDown:o=>{o.key==="Enter"&&o.currentTarget.blur()}}),e.jsx("input",{className:"pf-input pf-input-sm pf-wnum","aria-label":t("watchlist.col_cost"),placeholder:t("watchlist.col_cost"),title:t("watchlist.col_cost_help"),inputMode:"decimal",value:j,disabled:s,onChange:o=>y(o.target.value),onBlur:()=>m("cost",j),onKeyDown:o=>{o.key==="Enter"&&o.currentTarget.blur()}}),e.jsx("button",{type:"button",className:"pf-btn",disabled:s,onClick:()=>n(a.ticker),children:t("watchlist.act_remove")}),e.jsxs("details",{className:"pf-wtags",children:[e.jsxs("summary",{children:[t("watchlist.col_tags"),a.tags.length?` · ${a.tags.join(", ")}`:""]}),e.jsxs("div",{children:[e.jsx("span",{className:"pf-hint",children:t("watchlist.col_tags_help")}),e.jsxs("div",{className:"pf-chips",children:[c.map(o=>{const x=a.tags.some(C=>C.toLowerCase()===o.toLowerCase());return e.jsx("button",{type:"button",className:x?"pf-chip pf-chip-on":"pf-chip","aria-pressed":x,disabled:s,onClick:()=>w(o),children:o},o)}),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":t("watchlist.col_tags"),placeholder:t("watchlist.add_groups_ph"),value:v,disabled:s,onChange:o=>l(o.target.value),onKeyDown:o=>{if(o.key!=="Enter")return;const x=v.trim();x&&(l(""),w(x))}})]})]})]})]})}function $e({section:a,busy:i,onRename:s,onDissolve:r}){const n=L(),[t,p]=f.useState(a.tag??"");return e.jsxs("div",{className:"pf-ghead",children:[e.jsx("span",{className:"pf-gt",children:a.label}),e.jsx("span",{className:"pf-gc",children:a.rows.length}),a.tag!==null&&e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:n("watchlist.group_manage")}),e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:n("watchlist.group_manage_help")}),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":n("watchlist.group_rename"),value:t,disabled:i,onChange:d=>p(d.target.value)}),e.jsx("button",{type:"button",className:"pf-btn",disabled:i||!t.trim()||t.trim()===a.tag,onClick:()=>s(a.tag,t.trim()),children:n("watchlist.group_rename_apply")}),e.jsx("button",{type:"button",className:"pf-btn",disabled:i,title:n("watchlist.group_delete_help"),onClick:()=>r(a.tag),children:n("watchlist.group_delete")})]})]})]})}function De({entries:a,reload:i}){const s=L(),[r,n]=f.useState(!1),[t,p]=f.useState(null),[d,u]=f.useState(""),[h,v]=f.useState([]),[l,b]=f.useState("tags"),g=(m,w="list")=>{n(!0),p(null),m.then(()=>{n(!1),i()},c=>{if(n(!1),c instanceof M){i();return}p({where:w,message:U(c,s("common.offline"))})})},j=[...new Set(a.flatMap(m=>m.tags))].sort((m,w)=>m.toLowerCase().localeCompare(w.toLowerCase())),y=new Set(a.map(m=>m.ticker.toUpperCase())),_=new Set(h.map(m=>m.toLowerCase())),T=a.filter(m=>Te(m,d)&&(!_.size||m.tags.some(w=>_.has(w.toLowerCase()))));return e.jsxs(e.Fragment,{children:[e.jsx(Se,{listed:y,tags:j,busy:r,failure:t?.where==="add"?t.message:null,onAdd:m=>g(z("POST","/watchlist",m),"add")}),a.length===0?e.jsx(S,{title:s("profile.empty_watchlist_title"),children:e.jsx("div",{className:"pf-cardbody",children:e.jsx("p",{className:"pf-hint",children:s("profile.empty_watchlist_body")})})}):e.jsx(S,{title:s("watchlist.list_title"),sub:s("watchlist.list_sub"),children:e.jsxs("div",{className:"pf-cardbody",children:[e.jsxs("div",{className:"pf-chips",children:[e.jsx("input",{className:"pf-input pf-input-sm",type:"search","aria-label":s("watchlist.filter"),placeholder:s("watchlist.filter_ph"),value:d,onChange:m=>u(m.target.value)}),Ee.map(m=>e.jsx("button",{type:"button",className:m===l?"pf-chip pf-chip-on":"pf-chip","aria-pressed":m===l,onClick:()=>b(m),children:s(`watchlist.group_${m}`)},m))]}),j.length>0&&e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:s("watchlist.tag_filter")}),j.map(m=>e.jsx("button",{type:"button",className:_.has(m.toLowerCase())?"pf-chip pf-chip-on":"pf-chip","aria-pressed":_.has(m.toLowerCase()),onClick:()=>v(w=>w.includes(m)?w.filter(c=>c!==m):[...w,m]),children:m},m))]}),e.jsx(N,{message:t?.where==="list"?t.message:null}),T.length===0?e.jsx("p",{className:"pf-hint",children:s("watchlist.no_match")}):Le(T,l,s("watchlist.g_untagged"),{all:s("watchlist.g_all"),favorites:s("watchlist.g_favorites"),rest:s("watchlist.g_rest")}).map(m=>e.jsxs("div",{children:[e.jsx($e,{section:m,busy:r,onRename:(w,c)=>g(z("PATCH",`/watchlist/tags/${encodeURIComponent(w)}`,{name:c})),onDissolve:w=>g(z("DELETE",`/watchlist/tags/${encodeURIComponent(w)}`))}),m.rows.map(w=>e.jsx(Pe,{entry:w,tags:j,busy:r,onEdit:(c,o)=>g(z("PATCH",`/watchlist/${encodeURIComponent(c)}`,o)),onRemove:c=>g(z("DELETE",`/watchlist/${encodeURIComponent(c)}`))},`${m.id}_${w.ticker}`))]},m.id)),e.jsxs("div",{className:"pf-foot",children:[e.jsx("span",{className:"pf-hint",children:s("watchlist.count",{n:a.length})}),e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:s("watchlist.how_open")}),e.jsx("div",{children:e.jsx(I,{text:s("watchlist.how")})})]})]})]})})]})}function Ae({onAdded:a}){const i=L(),[s,r]=f.useState(0),n=$(()=>E("/watchlist/suggestions"),[s]),[t,p]=f.useState(!1),[d,u]=f.useState(null);if(n.state!=="loaded"||n.data.suggestions.length===0)return null;const h=n.data.suggestions;function v(){p(!0),u(null),h.reduce((l,b)=>l.then(()=>z("POST","/watchlist",{ticker:b.ticker,name:b.name,tags:b.tags}).then(()=>{})),Promise.resolve()).then(()=>{r(l=>l+1),a()}).catch(l=>u(U(l,i("common.offline")))).finally(()=>p(!1))}return e.jsxs(S,{title:i("profile.focus_suggest_title"),children:[e.jsx(I,{text:i("profile.focus_suggest_help")}),e.jsx("ul",{className:"pf-examples",children:h.map(l=>e.jsxs("li",{children:[e.jsx(re,{ticker:l.ticker,className:"pf-wsym"}),e.jsx("span",{children:l.name})]},l.ticker))}),e.jsx("button",{type:"button",className:"pf-linkbtn",disabled:t,onClick:v,children:i("profile.focus_suggest_add",{n:h.length})}),e.jsx(N,{message:d})]})}function Ue({query:a}){return e.jsx("div",{className:"pf-main",children:e.jsx(ae,{query:a,children:(i,s)=>e.jsxs(e.Fragment,{children:[e.jsx(De,{entries:i.entries,reload:s}),e.jsx(Ae,{onAdded:s})]})})})}const X=[{id:"prefs",label:"profile.preferences"},{id:"iv",label:"profile.iv_section"},{id:"watch",label:"profile.watchlist"},{id:"notify",label:"profile.notifications"}];function Me(a,i){return(i?.trim()?i.trim().split(/\s+/):(a.split("@")[0]??"").split(/[^\p{L}\p{N}]+/u)).filter(Boolean).slice(0,2).map(n=>n[0]??"").join("").toUpperCase()||"?"}function Ke(){return ne()?e.jsx(le,{text:"common.sign_in"}):e.jsx(Fe,{})}function Fe(){const a=L(),i=te(),{params:s,setParams:r}=se(),n=ke(a("common.offline")),t=$(()=>E("/me"),[]),p=t.state==="loaded"?t.data:null,d=$(()=>E("/watchlist"),[]),u=d.state==="loaded"?d.data.entries.length:0,[h,v]=f.useState(!1),l=p?.name?.trim()||"",b=s.get("tab")??"",g=X.some(y=>y.id===b)?b:"prefs",j=i.email??"";return e.jsxs(e.Fragment,{children:[e.jsx("style",{href:"ag-profile",precedence:"default",children:Ne}),e.jsxs("header",{className:"pf-head",children:[e.jsx("h1",{className:"pf-title",children:a("nav.profile")}),e.jsx("span",{className:"pf-savehint",children:a("profile.saves_instantly")})]}),e.jsx(S,{children:e.jsxs("div",{className:"pf-ident",children:[e.jsx("div",{className:"pf-avatar","aria-hidden":"true",children:p?.picture&&!h?e.jsx("img",{src:p.picture,alt:"",referrerPolicy:"no-referrer",onError:()=>v(!0)}):Me(j,l)}),e.jsxs("div",{className:"pf-ident-t",children:[l&&l!==j&&e.jsx("span",{className:"pf-ident-n",children:l}),e.jsx("span",{className:"pf-ident-e",children:j})]}),e.jsxs("div",{className:"pf-ident-r",children:[p?.data_dir&&e.jsx("span",{className:"pf-folder",title:p.data_dir_full??p.data_dir,children:e.jsx("span",{className:"pf-folder-p",children:p.data_dir})}),e.jsx("span",{className:"pf-ident-note",children:a("profile.account_scope")})]}),e.jsx("a",{className:"pf-signout",href:"/auth/logout",children:a("common.log_out")})]})}),e.jsx("div",{className:"pf-tabs",role:"tablist","aria-label":a("nav.profile"),children:X.map(y=>e.jsxs("button",{type:"button",role:"tab","aria-selected":y.id===g,className:y.id===g?"pf-tab pf-tab-on":"pf-tab",onClick:()=>r({tab:y.id}),children:[a(y.label),y.id==="watch"&&u>0&&e.jsx("span",{className:"pf-tab-n",children:u})]},y.id))}),g==="prefs"&&e.jsx(je,{...n,owner:t.state==="loaded"?!!p?.owner:null}),g==="iv"&&e.jsx(de,{}),g==="watch"&&e.jsx(Ue,{query:d}),g==="notify"&&e.jsx(pe,{...n})]})}export{Ke as default,Me as initials};
