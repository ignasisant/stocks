import{A as B,c as X,r as g,N as U,g as T,s as S,j as e,u as z,b as A,L as ee,S as re,n as ae,f as se,i as ne,l as ie}from"./app.js";import{T as te}from"./tickers.js";function D(a,n){return a instanceof B?a.detail:n}const le=3e3;function oe(a){const{reload:n}=X(),[t,i]=g.useState(null),[s,r]=g.useState(null),[o,f]=g.useState(!1),[c,x]=g.useState(!1),[w,l]=g.useState(null),[_,m]=g.useState(null),v=g.useCallback(u=>u instanceof U?(n(),null):{kind:"failed",error:D(u,a)},[n,a]);g.useEffect(()=>{let u=!0;return T("/notify/telegram").then(p=>u&&i(p),p=>{u&&m(v(p))}),()=>{u=!1}},[v]);const[b,C]=g.useState(()=>typeof document>"u"||!document.hidden);g.useEffect(()=>{const u=()=>C(!document.hidden);return document.addEventListener("visibilitychange",u),()=>document.removeEventListener("visibilitychange",u)},[]),g.useEffect(()=>{if(!s||!b)return;if(Date.now()>=s.deadline){r(null),f(!0);return}let u=!0;const p=window.setInterval(()=>{if(Date.now()>=s.deadline){r(null),f(!0);return}T("/notify/telegram").then(j=>{u&&(x(!1),i(j),j.linked&&r(null))},()=>u&&x(!0))},le);return()=>{u=!1,window.clearInterval(p)}},[s,b]);const E=g.useCallback(()=>{l("connect"),m(null),f(!1),S("POST","/notify/telegram").then(u=>{l(null),r({code:u.code,deepLink:u.deep_link,bot:u.bot,deadline:Date.now()+u.expires_in*1e3})},u=>{l(null),m(v(u))})},[v]),h=g.useCallback(()=>{l("test"),m(null),S("POST","/notify/telegram/test").then(u=>{l(null),i(u),m({kind:"test_sent"})},u=>{if(l(null),u instanceof U){n();return}m({kind:"test_failed",error:D(u,a)})})},[n,a]),d=g.useCallback(()=>{l("unlink"),m(null),S("DELETE","/notify/telegram").then(u=>{l(null),i(u),r(null),f(!1),m({kind:"unlinked"})},u=>{l(null),m(v(u))})},[v]);return{state:t,pending:s,expired:o,stalled:c,busy:w,note:_,connect:E,test:h,unlink:d}}function M({text:a}){const n=a.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);return e.jsx(e.Fragment,{children:n.map((t,i)=>t.startsWith("**")&&t.endsWith("**")&&t.length>4?e.jsx("b",{children:t.slice(2,-2)},i):t.startsWith("`")&&t.endsWith("`")&&t.length>2?e.jsx("code",{children:t.slice(1,-1)},i):e.jsx(g.Fragment,{children:t},i))})}function K({text:a,className:n}){const t=[];let i=[];const s=r=>{i.length&&(t.push(e.jsx("ul",{children:i.map((o,f)=>e.jsx("li",{children:e.jsx(M,{text:o})},f))},`ul${r}`)),i=[])};return a.split(`
`).forEach((r,o)=>{const f=r.trim();if(f.startsWith("- ")){i.push(f.slice(2));return}s(o),f&&t.push(e.jsx("p",{children:e.jsx(M,{text:f})},o))}),s(-1),e.jsx("div",{className:n??"pf-prose",children:t})}function N({title:a,sub:n,note:t,children:i}){return e.jsxs("section",{className:"pf-card",children:[a!==void 0&&e.jsxs("div",{className:"pf-cardhead",children:[e.jsx("span",{className:"pf-cardtitle",children:a}),n&&e.jsx("span",{className:"pf-cardsub",children:n}),t&&e.jsx("span",{className:"pf-cardnote",children:t})]}),i]})}function y({label:a,help:n,middle:t,children:i}){return e.jsxs("div",{className:t?"pf-row pf-row-mid":"pf-row",children:[e.jsxs("div",{className:"pf-row-l",children:[e.jsx("span",{className:"pf-row-lab",children:a}),n&&e.jsx("span",{className:"pf-row-help",children:e.jsx(M,{text:n})})]}),e.jsx("div",{className:"pf-row-ctl",children:i})]})}function $({value:a,options:n,labelOf:t,onPick:i,label:s,disabled:r}){return e.jsx("select",{className:"pf-select","aria-label":s,value:a,disabled:r,onChange:o=>i(o.target.value),children:n.map(o=>e.jsx("option",{value:o,children:t(o)},o))})}function G({value:a,options:n,labelOf:t,onPick:i,disabled:s}){return e.jsx("div",{className:"pf-chips",children:n.map(r=>e.jsx("button",{type:"button",className:r===a?"pf-chip pf-chip-on":"pf-chip","aria-pressed":r===a,disabled:s,onClick:()=>i(r),children:t(r)},r))})}function F({checked:a,onToggle:n,label:t,disabled:i}){return e.jsx("label",{className:"pf-switch",children:e.jsx("input",{type:"checkbox",checked:a,disabled:i,"aria-label":t,onChange:s=>n(s.target.checked)})})}function k({message:a}){return a?e.jsx("p",{className:"pf-err",role:"alert",children:a}):null}function W({values:a,options:n,labelOf:t,onToggle:i,disabled:s}){const r=new Set(a);return e.jsx("div",{className:"pf-chips",children:n.map(o=>{const f=r.has(o);return e.jsx("button",{type:"button",className:f?"pf-chip pf-chip-on":"pf-chip","aria-pressed":f,disabled:s,onClick:()=>i(o,!f),children:t(o)},o)})})}function ce({prefs:a,saving:n,failure:t,save:i}){const s=z(),r=oe(s("common.offline")),o=x=>t?.field===x?t.message:null,f=r.state?r.state.linked:a.telegram_linked,c=r.state?.configured??(a.telegram_linked?!0:null);return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(N,{title:s("profile.notify_channel_title"),sub:s("profile.notify_channel_sub"),children:[e.jsxs("div",{className:"pf-cardbody",children:[c===null&&!r.note&&e.jsx("p",{className:"pf-busy",children:s("common.loading")}),c===!1&&e.jsx("p",{className:"pf-hint",children:s("profile.tg_not_configured")}),c===!0&&f&&e.jsxs("span",{className:"pf-chips",children:[e.jsx("span",{className:"pf-badge",children:s("profile.notify_connected")}),e.jsx("span",{className:"pf-hint",children:s("profile.tg_linked_as",{handle:""}).trim()})]}),c===!0&&!f&&!r.pending&&e.jsxs("span",{className:"pf-chips",children:[e.jsx("button",{type:"button",className:"pf-btn pf-btn-p",disabled:r.busy==="connect",onClick:r.connect,children:s("profile.tg_connect")}),r.expired&&e.jsx("span",{className:"pf-warn",children:s("profile.tg_expired")})]}),c===!0&&!f&&r.pending&&e.jsxs(e.Fragment,{children:[e.jsx("a",{className:"pf-linkbtn",href:r.pending.deepLink,target:"_blank",rel:"noreferrer noopener",children:s("profile.tg_open")}),e.jsx("p",{className:"pf-hint",children:e.jsx(M,{text:s("profile.tg_manual",{bot:r.pending.bot,code:r.pending.code})})}),e.jsx("p",{className:"pf-busy",children:r.stalled?s("profile.tg_poll_error"):s("profile.tg_waiting")})]}),r.note?.kind==="failed"&&e.jsx(k,{message:r.note.error}),r.note?.kind==="unlinked"&&e.jsx("p",{className:"pf-hint",children:s("profile.tg_unlinked")})]}),c===!0&&f&&e.jsxs(e.Fragment,{children:[e.jsxs(y,{label:s("profile.notify_test_row"),help:s("profile.notify_test_help"),middle:!0,children:[e.jsx("button",{type:"button",className:"pf-btn",disabled:r.busy==="test",onClick:r.test,children:s("profile.tg_test")}),r.note?.kind==="test_sent"&&e.jsx("p",{className:"pf-hint",children:s("profile.tg_test_sent")}),r.note?.kind==="test_failed"&&e.jsx(k,{message:s("profile.tg_test_failed",{error:r.note.error})})]}),e.jsx(y,{label:s("profile.notify_unlink_row"),help:s("profile.notify_unlink_help"),middle:!0,children:e.jsx("button",{type:"button",className:"pf-btn",disabled:r.busy==="unlink",onClick:r.unlink,children:s("profile.tg_unlink")})})]})]}),c===!0&&f&&e.jsxs(N,{title:s("profile.notify_what_title"),sub:s("profile.notify_what_sub"),children:[e.jsxs(y,{label:s("profile.notify_digest"),help:s("profile.notify_digest_help"),middle:!0,children:[e.jsx(F,{label:s("profile.notify_digest"),checked:a.notify_digest,disabled:n==="notify_digest",onToggle:x=>i("notify_digest",x)}),e.jsx(k,{message:o("notify_digest")})]}),e.jsxs(y,{label:s("profile.notify_weekly"),help:s("profile.notify_weekly_help"),middle:!0,children:[e.jsx(F,{label:s("profile.notify_weekly"),checked:a.notify_weekly,disabled:n==="notify_weekly",onToggle:x=>i("notify_weekly",x)}),e.jsx(k,{message:o("notify_weekly")})]}),e.jsxs(y,{label:s("profile.notify_alerts"),help:s("profile.notify_alerts_help"),middle:!0,children:[e.jsx(F,{label:s("profile.notify_alerts"),checked:a.notify_alerts,disabled:n==="notify_alerts",onToggle:x=>i("notify_alerts",x)}),e.jsx(k,{message:o("notify_alerts")})]})]})]}),e.jsx("aside",{className:"pf-rail",children:e.jsx(N,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("b",{className:"pf-sum-t",children:s("profile.notify_caption")}),e.jsx(K,{text:s("profile.tg_how_body")})]})})})]})}function pe(){const a=A(async()=>{const[n,t]=await Promise.all([T("/profile-options"),T("/profile")]);return{options:n,profile:t}},[]);return e.jsx(ee,{query:a,skeleton:e.jsx(re,{rows:8}),children:n=>e.jsx(de,{options:n.options,stored:n.profile})})}function de({options:a,stored:n}){const t=z(),[i,s]=g.useState(n),[r,o]=g.useState(null),[f,c]=g.useState(null);function x(l,_){s(l),o(_),c(null),S("PUT","/profile",{risk:l.risk,horizon:l.horizon,focus:l.focus,constraints:l.constraints,notes:l.notes}).then(m=>s(m)).catch(m=>{s(n),c(D(m,t("common.offline")))}).finally(()=>o(null))}const w=l=>_=>t(`profile.iv_${l}_${_}`);return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(N,{title:t("profile.iv_how_title"),sub:t("profile.iv_how_sub"),children:[e.jsx(y,{label:t("profile.iv_risk"),help:t("profile.iv_risk_help"),children:e.jsx($,{label:t("profile.iv_risk"),value:i.risk,options:a.risk,labelOf:w("risk"),disabled:r==="risk",onPick:l=>l!==i.risk&&x({...i,risk:l},"risk")})}),e.jsx(y,{label:t("profile.iv_horizon"),help:t("profile.iv_horizon_help"),children:e.jsx($,{label:t("profile.iv_horizon"),value:i.horizon,options:a.horizon,labelOf:w("horizon"),disabled:r==="horizon",onPick:l=>l!==i.horizon&&x({...i,horizon:l},"horizon")})})]}),e.jsxs(N,{title:t("profile.iv_what_title"),sub:t("profile.iv_what_sub"),children:[e.jsx(y,{label:t("profile.iv_focus"),help:t("profile.iv_focus_help"),children:e.jsx(W,{values:i.focus,options:a.focus,labelOf:w("focus"),disabled:r==="focus",onToggle:(l,_)=>x({...i,focus:_?[...i.focus,l]:i.focus.filter(m=>m!==l)},"focus")})}),e.jsx(y,{label:t("profile.iv_constraints"),help:t("profile.iv_constraints_help"),children:e.jsx(W,{values:i.constraints,options:a.constraints,labelOf:w("constraints"),disabled:r==="constraints",onToggle:(l,_)=>x({...i,constraints:_?[...i.constraints,l]:i.constraints.filter(m=>m!==l)},"constraints")})})]}),e.jsxs(N,{title:t("profile.iv_notes_title"),sub:t("profile.iv_caption"),children:[e.jsx(y,{label:t("profile.iv_notes"),help:t("profile.iv_notes_help"),children:e.jsx(fe,{value:i.notes,placeholder:t("profile.iv_notes_ph"),label:t("profile.iv_notes"),disabled:r==="notes",onCommit:l=>l!==i.notes&&x({...i,notes:l},"notes")})}),e.jsx(k,{message:f})]})]}),e.jsx("aside",{className:"pf-rail",children:e.jsxs(N,{children:[e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:t("profile.iv_sum_title")}),e.jsx(R,{label:t("profile.iv_risk"),value:t(`profile.iv_risk_${i.risk}`)}),e.jsx(R,{label:t("profile.iv_horizon"),value:t(`profile.iv_horizon_${i.horizon}`)}),e.jsx(R,{label:t("profile.iv_focus"),value:H(i.focus,w("focus"),t("profile.iv_sum_none"))}),e.jsx(R,{label:t("profile.iv_constraints"),value:H(i.constraints,w("constraints"),t("profile.iv_sum_none"))}),e.jsx("div",{className:"pf-sum-rule"}),e.jsx("span",{className:"pf-sum-note",children:t("profile.iv_privacy")})]}),i.persona?e.jsxs("details",{className:"pf-persona",children:[e.jsx("summary",{children:t("profile.iv_persona_open")}),e.jsx("p",{className:"pf-sum-note",children:t("profile.iv_persona_help")}),e.jsx("code",{className:"pf-persona-text",children:i.persona})]}):null]})})]})}function H(a,n,t){return a.length?a.map(n).join(", "):t}function R({label:a,value:n}){return e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:a}),e.jsx("b",{children:n})]})}function fe({value:a,label:n,placeholder:t,disabled:i,onCommit:s}){const[r,o]=g.useState(a);return g.useEffect(()=>o(a),[a]),e.jsx("textarea",{className:"pf-notes",rows:4,value:r,"aria-label":n,placeholder:t,disabled:i,onChange:f=>o(f.target.value),onBlur:()=>s(r.trim())})}const ue=["EUR","USD","GBP","CHF","SEK","NOK","DKK","PLN","CZK","CAD","AUD"],I=["EUR","USD","GBP","CHF","SEK"],he={EUR:"€",USD:"$",GBP:"£",CHF:"₣",SEK:"kr",NOK:"kr",DKK:"kr",PLN:"zł",CZK:"Kč",CAD:"CA$",AUD:"A$"};function q(a){const n=he[a];return n&&n!==a?`${n} ${a}`:a}const Q={en:"English",es:"Español"},Y=[0,.08,.09];function O(a,n){const t=String(n??"").replace("_","-").split("-")[0]?.toUpperCase();return a.jurisdictions.find(i=>i.code===t)??null}function xe(a,n){if(n)return O(a,n)??O(a,a.default);const t=String(navigator.language??"").replace("_","-").split("-"),i=t.length>1&&t[1]?.length===2?t[1]:"";return O(a,i)??O(a,a.default)}function ge(a,n){return a.trim().toLowerCase()===n.trim().toLowerCase()&&n!==""}function me({email:a,onClose:n}){const t=z(),[i,s]=g.useState(""),[r,o]=g.useState(!1),[f,c]=g.useState(null),x=ge(i,a);g.useEffect(()=>{const l=_=>{_.key==="Escape"&&!r&&n()};return window.addEventListener("keydown",l),()=>window.removeEventListener("keydown",l)},[n,r]);const w=()=>{o(!0),c(null),S("DELETE","/account",{confirm:i.trim()}).then(l=>{const _=l.sign_out,m=_.startsWith("/")&&!_.startsWith("//")?_:"/auth/logout";window.location.assign(m)},l=>{if(o(!1),l instanceof U){window.location.assign("/auth/logout");return}c(l instanceof B&&l.status===422?l.detail:l instanceof B?t("profile.delete_failed"):t("common.offline"))})};return e.jsx("div",{className:"pf-modal",onClick:l=>{l.target===l.currentTarget&&!r&&n()},children:e.jsxs("div",{className:"pf-modal-card",role:"dialog","aria-modal":"true","aria-label":t("profile.delete_title"),children:[e.jsx("h2",{className:"pf-modal-t",children:t("profile.delete_title")}),e.jsx(K,{text:t("profile.delete_body")}),e.jsxs("label",{className:"pf-modal-confirm",children:[e.jsx("span",{className:"pf-hint",children:t("profile.delete_confirm")}),e.jsx("input",{className:"pf-input pf-input-wide",type:"text",autoFocus:!0,autoComplete:"off",autoCapitalize:"off",spellCheck:!1,placeholder:a,value:i,disabled:r,onChange:l=>s(l.target.value)})]}),e.jsx(k,{message:f}),e.jsxs("div",{className:"pf-modal-foot",children:[e.jsx("button",{type:"button",className:"pf-btn",disabled:r,onClick:n,children:t("common.cancel")}),e.jsx("button",{type:"button",className:"pf-btn pf-btn-danger",disabled:!x||r,onClick:w,children:t("profile.delete_button")})]})]})})}function be(){const a=z(),n=ae(),[t,i]=g.useState(!1);return e.jsxs(y,{label:a("profile.delete_row_title"),help:a("profile.delete_row_help"),middle:!0,children:[e.jsx("button",{type:"button",className:"pf-btn",onClick:()=>i(!0),children:a("profile.delete_open")}),t&&e.jsx(me,{email:n.email??"",onClose:()=>i(!1)})]})}function ve(){const a=z(),{setParams:n}=se(),t=()=>{n({tour:"1"})};return e.jsx(N,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:a("tour.launch")}),e.jsx("span",{className:"pf-sum-note",children:a("tour.launch_caption")}),e.jsx("button",{type:"button",className:"pf-btn pf-btn-p pf-selfstart",onClick:t,children:a("tour.launch_start")})]})})}const P="auto";function Z({value:a,onCommit:n,label:t,min:i,max:s,step:r,suffix:o,disabled:f}){const[c,x]=g.useState(String(a)),[w,l]=g.useState(a);w!==a&&(l(a),x(String(a)));const _=()=>{const m=Number(c);if(c.trim()===""||Number.isNaN(m)){x(String(a));return}m!==a&&n(m)};return e.jsxs("span",{className:"pf-chips",children:[e.jsx("input",{className:"pf-input",type:"number",inputMode:"decimal","aria-label":t,value:c,min:i,max:s,step:r,disabled:f,onChange:m=>x(m.target.value),onBlur:_,onKeyDown:m=>{m.key==="Enter"&&m.currentTarget.blur()}}),o&&e.jsx("span",{className:"pf-hint",children:o})]})}function _e({prefs:a,saving:n,failure:t,save:i}){const s=z(),r=A(()=>T("/import/last"),[]),o=A(()=>T("/portfolio/transactions",{limit:1}),[]),f=[P,...Object.keys(Q)],c=d=>d===P?s("profile.lang_auto"):Q[d]??d,x=I.includes(a.currency)?[...I]:[...I,a.currency],w=ue.filter(d=>!x.includes(d)),l=A(()=>T("/jurisdictions"),[]),_=l.state==="loaded"?l.data:null,m=[P,...(_?.jurisdictions??[]).map(d=>d.code)],v=d=>{if(d===P)return`🌐 ${s("profile.tax_residence_auto")}`;const u=_?.jurisdictions.find(j=>j.code===d),p=s(`profile.tax_residence_${d.toLowerCase()}`);return`${u?.flag??""} ${p}`.trim()},b=_?xe(_,a.tax_residence):null,C=b?b.year_start[0]===1&&b.year_start[1]===1?s("profile.tax_year_calendar"):s("profile.tax_year_from",{day:b.year_start[1],month:b.year_start[0]}):"",E=b?s(`profile.tax_match_${b.matching}`):"",h=d=>t?.field===d?t.message:null;return e.jsxs("div",{className:"pf-body",children:[e.jsxs("div",{className:"pf-main",children:[e.jsxs(N,{title:s("profile.ui_section"),sub:s("profile.ui_section_sub"),children:[e.jsxs(y,{label:s("profile.language"),help:s("profile.language_caption"),children:[e.jsx($,{label:s("profile.language"),value:a.language??P,options:f,labelOf:c,disabled:n==="language",onPick:d=>{const u=d===P?null:d;u!==a.language&&i("language",u)}}),e.jsx(k,{message:h("language")})]}),e.jsxs(y,{label:s("profile.display_currency"),help:s("profile.currency_caption"),children:[e.jsx(G,{value:a.currency,options:x,labelOf:q,disabled:n==="currency",onPick:d=>d!==a.currency&&i("currency",d)}),w.length>0&&e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:s("profile.currency_more",{n:w.length})}),e.jsx("div",{children:e.jsx(G,{value:a.currency,options:w,labelOf:q,disabled:n==="currency",onPick:d=>d!==a.currency&&i("currency",d)})})]}),e.jsx(k,{message:h("currency")})]})]}),e.jsxs(N,{title:s("profile.data_section"),children:[e.jsx(y,{label:s("profile.export_title"),help:s("profile.export_help"),children:o.state==="loaded"&&o.data.total>0?e.jsx("a",{className:"pf-download",href:"/api/v1/portfolio/transactions.csv",children:s("profile.export_button")}):e.jsx("span",{className:"pf-muted",children:s("profile.export_none")})}),e.jsx(be,{})]}),e.jsxs(N,{title:s("profile.tax_section"),note:s("profile.tax_legal_note"),children:[e.jsxs(y,{label:s("profile.tax_residence"),help:s("profile.tax_residence_caption"),children:[e.jsx($,{label:s("profile.tax_residence"),value:a.tax_residence??P,options:m,labelOf:v,disabled:n==="tax_residence",onPick:d=>{const u=d===P?null:d;u!==a.tax_residence&&i("tax_residence",u)}}),e.jsx(k,{message:h("tax_residence")}),b?e.jsxs("div",{className:"pf-rules",children:[e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:s("profile.tax_rule_cost")}),e.jsxs("span",{className:"pf-rule-v",children:[b.currency," · ",s("profile.tax_rule_fx")]})]}),e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:s("profile.tax_rule_matching")}),e.jsx("span",{className:"pf-rule-v",children:E})]}),e.jsxs("div",{className:"pf-rule",children:[e.jsx("span",{className:"pf-rule-k",children:s("profile.tax_rule_year")}),e.jsx("span",{className:"pf-rule-v",children:C})]})]}):null]}),(b?.settings_fields??[]).map(d=>{const u=b.code.toLowerCase();return d==="filing_status"?e.jsxs(y,{label:s("profile.tax_filing_status"),help:s(`profile.tax_filing_status_caption_${u}`),children:[e.jsx($,{label:s("profile.tax_filing_status"),value:b.filing_statuses.includes(a.tax_filing_status)?a.tax_filing_status:b.filing_statuses[0]??"single",options:b.filing_statuses,labelOf:p=>s(`profile.tax_status_${p}`),disabled:n==="tax_filing_status",onPick:p=>i("tax_filing_status",p)}),e.jsx(k,{message:h("tax_filing_status")})]},d):d==="church_tax_rate"?e.jsxs(y,{label:s("profile.tax_church"),help:s("profile.tax_church_caption"),children:[e.jsx($,{label:s("profile.tax_church"),value:String(Y.includes(a.tax_church_rate)?a.tax_church_rate:0),options:Y.map(String),labelOf:p=>s(`profile.tax_church_${Math.round(Number(p)*100)}`),disabled:n==="tax_church_rate",onPick:p=>i("tax_church_rate",Number(p))}),e.jsx(k,{message:h("tax_church_rate")})]},d):d==="other_income"?e.jsxs(y,{label:s("profile.tax_other_income"),help:s(`profile.tax_other_income_caption_${u}`),children:[e.jsx(Z,{label:s("profile.tax_other_income"),value:a.tax_other_income,min:0,step:1e3,suffix:b.currency,disabled:n==="tax_other_income",onCommit:p=>i("tax_other_income",p)}),e.jsx(k,{message:h("tax_other_income")})]},d):d==="subnational_rate"?e.jsxs(y,{label:s("profile.tax_subnational"),help:s("profile.tax_subnational_caption"),children:[e.jsx(Z,{label:s("profile.tax_subnational"),value:Math.round(a.tax_subnational_rate*1e4)/100,min:0,max:100,step:.5,suffix:"%",disabled:n==="tax_subnational_rate",onCommit:p=>i("tax_subnational_rate",Math.round(p*100)/1e4)}),e.jsx(k,{message:h("tax_subnational_rate")})]},d):e.jsxs(y,{label:s("profile.tax_niit"),help:s("profile.tax_niit_caption"),middle:!0,children:[e.jsx(F,{label:s("profile.tax_niit"),checked:a.tax_niit,disabled:n==="tax_niit",onToggle:p=>i("tax_niit",p)}),e.jsx(k,{message:h("tax_niit")})]},d)})]})]}),e.jsxs("aside",{className:"pf-rail",children:[e.jsx(ve,{}),e.jsx(N,{children:e.jsxs("div",{className:"pf-sum",children:[e.jsx("span",{className:"pf-sum-t",children:s("profile.summary_title")}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:s("profile.language")}),e.jsx("b",{children:(c(a.language??P).split("(")[0]??"").trim()})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:s("profile.display_currency")}),e.jsx("b",{children:a.currency})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:s("profile.tax_section")}),e.jsx("b",{children:b?`${(s(`profile.tax_residence_${b.code.toLowerCase()}`).split("—")[0]??"").trim()} · ${E}`:s("common.loading")})]}),e.jsxs("div",{className:"pf-sum-row",children:[e.jsx("span",{children:s("profile.summary_last_import")}),e.jsx("b",{children:r.state==="loaded"?r.data.imported_at?.slice(0,10)??s("profile.summary_never"):s("common.loading")})]}),e.jsx("div",{className:"pf-sum-rule"}),e.jsx("span",{className:"pf-sum-note",children:s("profile.summary_note")})]})})]})]})}const we=new Set(["currency","language"]);function je(a){const n=X(),[t,i]=g.useState(n.prefs),[s,r]=g.useState(null),[o,f]=g.useState(null),c=g.useCallback((x,w)=>{r(x),f(null),S("PATCH","/prefs",{[x]:w}).then(l=>{r(null),i(l),we.has(x)&&n.reload()},l=>{if(r(null),l instanceof U){n.reload();return}f({field:x,message:D(l,a)})})},[n,a]);return{prefs:t,saving:s,failure:o,save:c}}const ye=`
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
   the viewport, and the control takes whatever is left. */
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
  border-radius: var(--ag-radius-xs); padding: 7px 10px; max-width: 340px;
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
  display: inline-block; font-size: var(--ag-fs-sm); text-decoration: none;
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
.pf-rule { display: flex; flex-direction: column; gap: 3px; }
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

/* Phones: one column, no sticky rail, a narrower gutter. */
@media (max-width: 640px) {
  .pf-body { flex-direction: column; }
  .pf-rail { position: static; flex: 1 1 auto; width: 100%; }
  .pf-row { flex-direction: column; gap: 10px; padding: 14px 16px; }
  .pf-row::before { left: 16px; right: 16px; }
  .pf-row-l { flex: 1 1 auto; }
  .pf-cardhead { padding: 14px 16px 12px; }
  .pf-cardbody { padding: 0 16px 16px; }
  .pf-ident { padding: 14px 16px; }
  .pf-savehint { display: none; }
  .pf-wsym { flex: 1 1 100%; }
}
`,ke={analyze:"raw"},J=2;function Ne({listed:a,tags:n,onAdd:t,busy:i,failure:s}){const r=z(),[o,f]=g.useState(""),[c,x]=g.useState([]),[w,l]=g.useState(""),[_,m]=g.useState(!1),[v,b]=g.useState(null),[C,E]=g.useState(null),h=o.trim();g.useEffect(()=>{if(h.length<J){b(null);return}let p=!0;const j=window.setTimeout(()=>{T("/search",{q:h,limit:8}).then(L=>p&&(b(L.matches),E(null)),()=>p&&(b([]),E(r("common.offline"))))},250);return()=>{p=!1,window.clearTimeout(j)}},[h]);const d=p=>{t({ticker:p.ticker,name:p.name,..._?{favorite:!0}:{},...c.length?{tags:c}:{}}),f(""),b(null)},u=[...new Set([...n,...c])].sort((p,j)=>p.toLowerCase().localeCompare(j.toLowerCase()));return e.jsx(N,{title:r("watchlist.add_title"),sub:r("watchlist.add_sub"),children:e.jsxs("div",{className:"pf-cardbody",children:[e.jsx("input",{className:"pf-input pf-input-wide",type:"search","aria-label":r("watchlist.add_title"),placeholder:r("watchlist.add_placeholder"),value:o,onChange:p=>f(p.target.value)}),e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:r("watchlist.add_groups")}),u.map(p=>e.jsx("button",{type:"button",className:c.includes(p)?"pf-chip pf-chip-on":"pf-chip","aria-pressed":c.includes(p),onClick:()=>x(j=>j.includes(p)?j.filter(L=>L!==p):[...j,p]),children:p},p)),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":r("watchlist.add_groups"),placeholder:r("watchlist.add_groups_ph"),value:w,onChange:p=>l(p.target.value),onKeyDown:p=>{if(p.key!=="Enter")return;const j=w.trim();j&&(x(L=>L.includes(j)?L:[...L,j]),l(""))}})]}),e.jsx("span",{className:"pf-hint",children:r("watchlist.add_groups_help")}),e.jsxs("label",{className:"pf-switch",children:[e.jsx("input",{type:"checkbox",checked:_,onChange:p=>m(p.target.checked)}),e.jsx("span",{children:r("watchlist.add_fav")})]}),e.jsx(k,{message:s??C}),h.length<J?e.jsx("p",{className:"pf-hint",children:r("watchlist.add_hint")}):v===null?e.jsx("p",{className:"pf-hint",children:r("common.loading")}):v.length===0?e.jsx("p",{className:"pf-hint",children:r("watchlist.add_none")}):e.jsx("div",{className:"pf-res",children:v.map(p=>{const j=a.has(p.ticker.toUpperCase()),L=ke[p.kind]??p.kind;return e.jsxs("button",{type:"button",className:"pf-btn pf-resrow",disabled:j||i,title:r(j?"watchlist.add_listed":`watchlist.kind_${L}`),onClick:()=>d(p),children:[e.jsx("span",{className:"pf-resrow-t",children:p.ticker}),e.jsx("span",{className:"pf-resrow-n",children:p.name}),e.jsx("span",{className:"pf-resrow-k",children:j?r("watchlist.add_listed"):(p.exchange??"")||r(`watchlist.kind_${L}`)})]},p.ticker)})})]})})}const Ce=["tags","favorites","flat"];function Se(a,n,t,i){if(n==="flat")return[{id:"all",label:i.all,rows:a,tag:null}];const s=[],r=a.filter(c=>c.favorite);if(r.length&&s.push({id:"fav",label:i.favorites,rows:r,tag:null}),n==="favorites"){const c=a.filter(x=>!x.favorite);return c.length&&s.push({id:"rest",label:i.rest,rows:c,tag:null}),s}const o=new Map;for(const c of a)for(const x of c.tags){const w=x.toLowerCase(),l=o.get(w)??{label:x,rows:[]};l.rows.push(c),o.set(w,l)}for(const c of[...o.keys()].sort()){const x=o.get(c);s.push({id:`tag_${c}`,label:x.label,rows:x.rows,tag:x.label})}const f=a.filter(c=>!c.tags.length&&!c.favorite);return f.length&&s.push({id:"none",label:t,rows:f,tag:null}),s}function ze(a,n){if(!n)return!0;const t=n.trim().toUpperCase();return a.ticker.toUpperCase().includes(t)||(a.name??"").toUpperCase().includes(t)||a.tags.some(i=>i.toUpperCase().includes(t))}function Ee({entry:a,tags:n,busy:t,onEdit:i,onRemove:s}){const r=z(),[o,f]=g.useState(a.name),[c,x]=g.useState(a.name),[w,l]=g.useState("");c!==a.name&&(x(a.name),f(a.name));const _=v=>i(a.ticker,{tags:a.tags.some(b=>b.toLowerCase()===v.toLowerCase())?a.tags.filter(b=>b.toLowerCase()!==v.toLowerCase()):[...a.tags,v]}),m=[...new Set([...n,...a.tags])].sort((v,b)=>v.toLowerCase().localeCompare(b.toLowerCase()));return e.jsxs("div",{className:"pf-wrow",children:[e.jsx("button",{type:"button",className:a.favorite?"pf-star pf-star-on":"pf-star","aria-label":r("watchlist.col_favorite"),"aria-pressed":a.favorite,disabled:t,onClick:()=>i(a.ticker,{favorite:!a.favorite}),children:a.favorite?"★":"☆"}),e.jsx(te,{ticker:a.ticker,className:"pf-wsym",children:a.ticker}),e.jsx("input",{className:"pf-input pf-input-sm pf-wname","aria-label":r("watchlist.col_name"),value:o,disabled:t,onChange:v=>f(v.target.value),onBlur:()=>o!==a.name&&i(a.ticker,{name:o}),onKeyDown:v=>{v.key==="Enter"&&v.currentTarget.blur()}}),e.jsx("button",{type:"button",className:"pf-btn",disabled:t,onClick:()=>s(a.ticker),children:r("watchlist.act_remove")}),e.jsxs("details",{className:"pf-wtags",children:[e.jsxs("summary",{children:[r("watchlist.col_tags"),a.tags.length?` · ${a.tags.join(", ")}`:""]}),e.jsxs("div",{children:[e.jsx("span",{className:"pf-hint",children:r("watchlist.col_tags_help")}),e.jsxs("div",{className:"pf-chips",children:[m.map(v=>{const b=a.tags.some(C=>C.toLowerCase()===v.toLowerCase());return e.jsx("button",{type:"button",className:b?"pf-chip pf-chip-on":"pf-chip","aria-pressed":b,disabled:t,onClick:()=>_(v),children:v},v)}),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":r("watchlist.col_tags"),placeholder:r("watchlist.add_groups_ph"),value:w,disabled:t,onChange:v=>l(v.target.value),onKeyDown:v=>{if(v.key!=="Enter")return;const b=w.trim();b&&(l(""),_(b))}})]})]})]})]})}function Le({section:a,busy:n,onRename:t,onDissolve:i}){const s=z(),[r,o]=g.useState(a.tag??"");return e.jsxs("div",{className:"pf-ghead",children:[e.jsx("span",{className:"pf-gt",children:a.label}),e.jsx("span",{className:"pf-gc",children:a.rows.length}),a.tag!==null&&e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:s("watchlist.group_manage")}),e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:s("watchlist.group_manage_help")}),e.jsx("input",{className:"pf-input pf-input-sm","aria-label":s("watchlist.group_rename"),value:r,disabled:n,onChange:f=>o(f.target.value)}),e.jsx("button",{type:"button",className:"pf-btn",disabled:n||!r.trim()||r.trim()===a.tag,onClick:()=>t(a.tag,r.trim()),children:s("watchlist.group_rename_apply")}),e.jsx("button",{type:"button",className:"pf-btn",disabled:n,title:s("watchlist.group_delete_help"),onClick:()=>i(a.tag),children:s("watchlist.group_delete")})]})]})]})}function Te({entries:a,reload:n}){const t=z(),[i,s]=g.useState(!1),[r,o]=g.useState(null),[f,c]=g.useState(""),[x,w]=g.useState([]),[l,_]=g.useState("tags"),m=(h,d="list")=>{s(!0),o(null),h.then(()=>{s(!1),n()},u=>{if(s(!1),u instanceof U){n();return}o({where:d,message:D(u,t("common.offline"))})})},v=[...new Set(a.flatMap(h=>h.tags))].sort((h,d)=>h.toLowerCase().localeCompare(d.toLowerCase())),b=new Set(a.map(h=>h.ticker.toUpperCase())),C=new Set(x.map(h=>h.toLowerCase())),E=a.filter(h=>ze(h,f)&&(!C.size||h.tags.some(d=>C.has(d.toLowerCase()))));return e.jsxs(e.Fragment,{children:[e.jsx(Ne,{listed:b,tags:v,busy:i,failure:r?.where==="add"?r.message:null,onAdd:h=>m(S("POST","/watchlist",h),"add")}),a.length===0?e.jsx(N,{title:t("profile.empty_watchlist_title"),children:e.jsx("div",{className:"pf-cardbody",children:e.jsx("p",{className:"pf-hint",children:t("profile.empty_watchlist_body")})})}):e.jsx(N,{title:t("watchlist.list_title"),sub:t("watchlist.list_sub"),children:e.jsxs("div",{className:"pf-cardbody",children:[e.jsxs("div",{className:"pf-chips",children:[e.jsx("input",{className:"pf-input pf-input-sm",type:"search","aria-label":t("watchlist.filter"),placeholder:t("watchlist.filter_ph"),value:f,onChange:h=>c(h.target.value)}),Ce.map(h=>e.jsx("button",{type:"button",className:h===l?"pf-chip pf-chip-on":"pf-chip","aria-pressed":h===l,onClick:()=>_(h),children:t(`watchlist.group_${h}`)},h))]}),v.length>0&&e.jsxs("div",{className:"pf-chips",children:[e.jsx("span",{className:"pf-hint",children:t("watchlist.tag_filter")}),v.map(h=>e.jsx("button",{type:"button",className:C.has(h.toLowerCase())?"pf-chip pf-chip-on":"pf-chip","aria-pressed":C.has(h.toLowerCase()),onClick:()=>w(d=>d.includes(h)?d.filter(u=>u!==h):[...d,h]),children:h},h))]}),e.jsx(k,{message:r?.where==="list"?r.message:null}),E.length===0?e.jsx("p",{className:"pf-hint",children:t("watchlist.no_match")}):Se(E,l,t("watchlist.g_untagged"),{all:t("watchlist.g_all"),favorites:t("watchlist.g_favorites"),rest:t("watchlist.g_rest")}).map(h=>e.jsxs("div",{children:[e.jsx(Le,{section:h,busy:i,onRename:(d,u)=>m(S("PATCH",`/watchlist/tags/${encodeURIComponent(d)}`,{name:u})),onDissolve:d=>m(S("DELETE",`/watchlist/tags/${encodeURIComponent(d)}`))}),h.rows.map(d=>e.jsx(Ee,{entry:d,tags:v,busy:i,onEdit:(u,p)=>m(S("PATCH",`/watchlist/${encodeURIComponent(u)}`,p)),onRemove:u=>m(S("DELETE",`/watchlist/${encodeURIComponent(u)}`))},`${h.id}_${d.ticker}`))]},h.id)),e.jsxs("div",{className:"pf-foot",children:[e.jsx("span",{className:"pf-hint",children:t("watchlist.count",{n:a.length})}),e.jsxs("details",{className:"pf-more",children:[e.jsx("summary",{children:t("watchlist.how_open")}),e.jsx("div",{children:e.jsx(K,{text:t("watchlist.how")})})]})]})]})})]})}function Pe({onAdded:a}){const n=z(),[t,i]=g.useState(0),s=A(()=>T("/watchlist/suggestions"),[t]),[r,o]=g.useState(!1),[f,c]=g.useState(null);if(s.state!=="loaded"||s.data.suggestions.length===0)return null;const x=s.data.suggestions;function w(){o(!0),c(null),x.reduce((l,_)=>l.then(()=>S("POST","/watchlist",{ticker:_.ticker,name:_.name,tags:_.tags}).then(()=>{})),Promise.resolve()).then(()=>{i(l=>l+1),a()}).catch(l=>c(D(l,n("common.offline")))).finally(()=>o(!1))}return e.jsxs(N,{title:n("profile.focus_suggest_title"),children:[e.jsx(K,{text:n("profile.focus_suggest_help")}),e.jsx("ul",{className:"pf-examples",children:x.map(l=>e.jsxs("li",{children:[e.jsx(te,{ticker:l.ticker,className:"pf-wsym"}),e.jsx("span",{children:l.name})]},l.ticker))}),e.jsx("button",{type:"button",className:"pf-linkbtn",disabled:r,onClick:w,children:n("profile.focus_suggest_add",{n:x.length})}),e.jsx(k,{message:f})]})}function $e(){const a=A(()=>T("/watchlist"),[]);return e.jsx("div",{className:"pf-main",children:e.jsx(ee,{query:a,children:(n,t)=>e.jsxs(e.Fragment,{children:[e.jsx(Te,{entries:n.entries,reload:t}),e.jsx(Pe,{onAdded:t})]})})})}const V=[{id:"prefs",label:"profile.preferences"},{id:"iv",label:"profile.iv_section"},{id:"watch",label:"profile.watchlist"},{id:"notify",label:"profile.notifications"}];function Ae(a){return(a.split("@")[0]??"").split(/[^\p{L}\p{N}]+/u).filter(Boolean).slice(0,2).map(i=>i[0]??"").join("").toUpperCase()||"?"}function Oe(){return ne()?e.jsx(ie,{text:"common.sign_in"}):e.jsx(De,{})}function De(){const a=z(),n=ae(),{params:t,setParams:i}=se(),s=je(a("common.offline")),r=t.get("tab")??"",o=V.some(c=>c.id===r)?r:"prefs",f=n.email??"";return e.jsxs(e.Fragment,{children:[e.jsx("style",{href:"ag-profile",precedence:"default",children:ye}),e.jsxs("header",{className:"pf-head",children:[e.jsx("h1",{className:"pf-title",children:a("nav.profile")}),e.jsx("span",{className:"pf-savehint",children:a("profile.saves_instantly")})]}),e.jsx(N,{children:e.jsxs("div",{className:"pf-ident",children:[e.jsx("div",{className:"pf-avatar","aria-hidden":"true",children:Ae(f)}),e.jsxs("div",{className:"pf-ident-t",children:[e.jsx("span",{className:"pf-ident-e",children:f}),e.jsx("span",{className:"pf-ident-note",children:a("profile.account_scope")})]}),e.jsx("a",{className:"pf-signout",href:"/auth/logout",children:a("common.log_out")})]})}),e.jsx("div",{className:"pf-tabs",role:"tablist","aria-label":a("nav.profile"),children:V.map(c=>e.jsx("button",{type:"button",role:"tab","aria-selected":c.id===o,className:c.id===o?"pf-tab pf-tab-on":"pf-tab",onClick:()=>i({tab:c.id}),children:a(c.label)},c.id))}),o==="prefs"&&e.jsx(_e,{...s}),o==="iv"&&e.jsx(pe,{}),o==="watch"&&e.jsx($e,{}),o==="notify"&&e.jsx(ce,{...s})]})}export{Oe as default};
