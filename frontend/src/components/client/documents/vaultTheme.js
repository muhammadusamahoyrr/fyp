/* The client Vault's look (2026-10-10): the lawyer Vault's CSS
 * (lawyer/VaultPage.jsx LAWYER_VAULT_CSS) copied VERBATIM -- only the scope
 * ([data-lawyer-vault] -> [data-client-vault]) and the class prefix (lv- -> cv-)
 * differ -- so the two Vaults look the same, while a change on either side
 * never reaches the other. Colours: the client tokens (client/clientTheme.js). */
export const CLIENT_VAULT_CSS = `[data-client-vault]{color:var(--ink);font:15px/1.5 "Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
[data-client-vault].cv-page{flex:1;min-height:0;overflow-y:auto;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg)}
[data-client-vault] *{box-sizing:border-box}
[data-client-vault] button,[data-client-vault] input,[data-client-vault] select{font:inherit;color:inherit}
[data-client-vault] :focus-visible{outline:2px solid var(--focus);outline-offset:2px}
[data-client-vault] .cv-wrap{max-width:1240px;margin:0 auto;padding:22px clamp(16px,3.2vw,40px) 64px;display:grid;gap:22px}
[data-client-vault] .cv-crumbs{font-size:13px;color:var(--muted)}
[data-client-vault] .cv-crumbs b{color:var(--ink);font-weight:600}
[data-client-vault] .cv-crumbs button{background:none;border:0;padding:0;color:var(--muted);cursor:pointer}
[data-client-vault] .cv-crumbs button:hover{color:var(--hover-ink)}
[data-client-vault] .cv-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
[data-client-vault] .cv-head h1{margin:0;font:600 clamp(28px,3.4vw,38px)/1.1 "Literata",Georgia,serif;letter-spacing:-.01em}
[data-client-vault] .cv-accent{background:linear-gradient(90deg,var(--brand-text),var(--teal-ink));-webkit-background-clip:text;background-clip:text;color:transparent}
[data-client-vault] .cv-head p{margin:8px 0 0;color:var(--muted);max-width:62ch}
[data-client-vault] .cv-btn{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 16px;border-radius:12px;border:1px solid var(--line-strong);background:var(--surface);font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-client-vault] .cv-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-client-vault] .cv-btn:disabled{opacity:.5;cursor:not-allowed}
[data-client-vault] .cv-btn.danger{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 35%,transparent)}
[data-client-vault] .cv-btn.danger:hover:not(:disabled){background:var(--danger-soft);color:var(--danger);border-color:var(--danger)}
[data-client-vault] .cv-cta{position:relative;overflow:hidden;display:inline-flex;align-items:center;gap:10px;height:48px;padding:0 22px;border-radius:14px;border:0;background:var(--brand-solid);color:var(--on-brand);font-weight:700;font-size:15px;cursor:pointer;box-shadow:0 10px 24px -12px rgba(46,196,214,.8);transition:transform .15s,box-shadow .15s}
[data-client-vault] .cv-cta:hover:not(:disabled){background:var(--brand-solid-hover);transform:translateY(-1px);box-shadow:0 14px 28px -12px rgba(46,196,214,.9)}
[data-client-vault] .cv-cta:disabled{opacity:.5;cursor:not-allowed}
[data-client-vault] .cv-cta::after{content:"";position:absolute;top:0;bottom:0;left:0;width:40%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent);transform:translateX(-130%) skewX(-20deg)}
[data-client-vault] .cv-cta:hover::after{animation:cvShine .8s ease}
[data-client-vault] .cv-soon{font-size:10.5px;font-weight:700;letter-spacing:.04em;padding:1px 7px;border-radius:999px;background:var(--chip-n);color:var(--muted)}
[data-client-vault] .cv-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
[data-client-vault] .cv-stat,[data-client-vault] .cv-folder{position:relative;border-radius:20px;overflow:hidden;border:1px solid color-mix(in srgb,var(--c) 14%,var(--line));background:radial-gradient(120% 100% at 100% 0%,color-mix(in srgb,var(--c) 13%,transparent) 0%,transparent 55%),linear-gradient(180deg,color-mix(in srgb,var(--surface) 92%,#fff 8%),var(--surface));box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 10px 24px -18px rgba(0,0,0,.65);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
[data-client-vault] .cv-stat{display:grid;grid-template-columns:auto 1fr;grid-template-areas:"ic l" "v v" "s s";column-gap:12px;align-items:center;padding:18px}
[data-client-vault] .cv-stat:hover,[data-client-vault] .cv-folder:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--c) 45%,var(--line));box-shadow:0 1px 0 rgba(255,255,255,.06) inset,0 18px 32px -20px color-mix(in srgb,var(--c) 70%,#000)}
[data-client-vault] .cv-ic{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 22%,transparent) inset}
[data-client-vault] .cv-ic svg{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-stat .cv-ic{grid-area:ic}
[data-client-vault] .cv-stat .l{grid-area:l;font-size:13.5px;font-weight:600;color:var(--muted)}
[data-client-vault] .cv-stat .v{grid-area:v;font:600 32px/1 "Literata",Georgia,serif;margin:14px 0 6px}
[data-client-vault] .cv-stat .s{grid-area:s;font-size:12.5px;color:var(--muted)}
[data-client-vault] .cv-stat:hover .cv-ic svg{transform:translateY(-2px) scale(1.08)}
[data-client-vault] .cv-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
[data-client-vault] .cv-search{flex:1 1 420px;display:flex;align-items:center;gap:10px;height:48px;padding:0 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest)}
[data-client-vault] .cv-search:hover{border-color:var(--hover-line)}
[data-client-vault] .cv-search:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-client-vault] .cv-search svg{color:var(--faint);flex:none}
[data-client-vault] .cv-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:15px}
[data-client-vault] .cv-search input::placeholder{color:var(--faint)}
[data-client-vault] .cv-kbd{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--faint);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;padding:0 6px;line-height:18px}
[data-client-vault] .cv-sort{position:relative;display:flex;align-items:center;height:48px;border-radius:12px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-rest);min-width:220px}
[data-client-vault] .cv-sort:hover{border-color:var(--hover-line)}
[data-client-vault] .cv-sort:focus-within{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-client-vault] .cv-sort > svg{position:absolute;left:14px;color:var(--muted);pointer-events:none}
[data-client-vault] .cv-sort .chev{left:auto;right:14px}
[data-client-vault] .cv-sort select{appearance:none;-webkit-appearance:none;width:100%;height:100%;border:0;outline:none;background:transparent;padding:0 38px 0 42px;font-weight:600;font-size:14.5px;cursor:pointer}
[data-client-vault] .cv-sort select option{background:var(--surface);color:var(--ink)}
[data-client-vault] .cv-card{border-radius:18px;border:1px solid var(--line);background:var(--surface);box-shadow:var(--shadow-rest);overflow:hidden}
[data-client-vault] .cv-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line)}
[data-client-vault] .cv-tabs{display:inline-flex;gap:4px;padding:4px;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
[data-client-vault] .cv-tab{height:36px;padding:0 14px;border-radius:9px;border:0;background:transparent;color:var(--muted);font-weight:600;font-size:14px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
[data-client-vault] .cv-tab:hover{color:var(--hover-ink)}
[data-client-vault] .cv-tab[aria-selected="true"]{background:var(--brand-solid);color:var(--on-brand)}
[data-client-vault] .cv-n{font-family:"JetBrains Mono",monospace;font-size:11px;padding:1px 7px;border-radius:999px;background:var(--chip-n)}
[data-client-vault] .cv-tab[aria-selected="true"] .cv-n{background:rgba(0,0,0,.18)}
[data-client-vault] .cv-filter{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--muted)}
[data-client-vault] .cv-filter b{color:var(--ink)}
[data-client-vault] .cv-grid{display:grid;grid-template-columns:minmax(0,2.6fr) minmax(0,1fr) minmax(0,1.1fr) 110px 120px 190px;gap:14px;align-items:center;padding:12px 20px;position:relative}
[data-client-vault] .cv-th{font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--muted);background:var(--surface-2);border-bottom:1px solid var(--line);padding-block:10px}
[data-client-vault] .cv-th span:last-child{text-align:right}
[data-client-vault] .cv-row{border-bottom:1px solid var(--line);transition:background .15s,box-shadow .15s}
[data-client-vault] .cv-row:last-child{border-bottom:0}
[data-client-vault] .cv-row:hover{background:var(--hover-tint);box-shadow:inset 0 0 0 1px var(--hover-line)}
[data-client-vault] .cv-row:hover .cv-name{color:var(--hover-ink)}
[data-client-vault] .cv-pdf{width:34px;height:40px;flex:none;border-radius:8px;display:grid;place-items:center;font:800 9.5px "JetBrains Mono",monospace;color:#B3261E;background:#FDECEC;transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-row:hover .cv-pdf{transform:rotate(-6deg) translateY(-2px)}
[data-client-vault] .cv-name{font:600 16px/1.3 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-vault] .cv-sub{font-size:12.5px;color:var(--muted)}
[data-client-vault] .cv-chip{display:inline-flex;align-items:center;gap:6px;max-width:100%;font-size:12.5px;font-weight:600;padding:3px 10px;border-radius:999px;background:rgba(242,195,94,.13);color:var(--gold);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-vault] .cv-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}
[data-client-vault] .cv-pill i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-client-vault] .cv-acts{display:flex;justify-content:flex-end;gap:6px}
[data-client-vault] .cv-ib{width:36px;height:36px;border-radius:11px;border:1px solid var(--line);background:var(--surface-2);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:color .15s,border-color .15s,background .15s}
[data-client-vault] .cv-ib:hover:not(:disabled){color:var(--hover-ink);border-color:var(--hover-line);background:var(--hover-tint)}
[data-client-vault] .cv-ib:disabled{opacity:.4;cursor:not-allowed}
[data-client-vault] .cv-ib.danger:hover:not(:disabled){color:var(--danger);border-color:var(--danger);background:var(--danger-soft)}
[data-client-vault] .cv-ib.k-eye:hover:not(:disabled) svg{animation:cvBlink 1.2s ease infinite}
[data-client-vault] .cv-ib.k-down:hover:not(:disabled) svg{animation:cvBounce .6s ease}
[data-client-vault] .cv-ib.k-move:hover:not(:disabled) svg{animation:cvNudge .5s ease}
[data-client-vault] .cv-ib.k-trash:hover:not(:disabled) svg{animation:cvShake .45s ease}
[data-client-vault] .cv-ib.k-pen:hover svg{animation:cvNudge .5s ease}
[data-client-vault] .cv-folders{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px;padding:18px}
[data-client-vault] .cv-folder{display:flex;flex-direction:column;gap:12px;padding:16px}
[data-client-vault] .cv-folder .open{display:flex;align-items:center;gap:12px;padding:0;border:0;background:transparent;text-align:left;cursor:pointer;min-width:0}
[data-client-vault] .cv-folder:hover .cv-ic svg{transform:translateY(-2px) rotate(-6deg) scale(1.08)}
[data-client-vault] .cv-folder .nm{display:block;font:600 16px/1.3 "Literata",Georgia,serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-client-vault] .cv-new{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;min-height:128px;border-radius:20px;border:1.5px dashed var(--line-strong);background:transparent;color:var(--muted);font-weight:700;cursor:pointer;transition:border-color .15s,color .15s,background .15s}
[data-client-vault] .cv-new:hover{border-color:var(--hover-line);color:var(--hover-ink);background:var(--hover-tint)}
[data-client-vault] .cv-new span{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand-text);transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-new:hover span{transform:rotate(90deg)}
[data-client-vault] .cv-cta:hover svg{animation:cvNudge .5s ease}
[data-client-vault] .cv-empty{padding:48px 20px;text-align:center;color:var(--muted)}
[data-client-vault] .cv-empty b{display:block;font:600 20px "Literata",Georgia,serif;color:var(--ink);margin:12px 0 6px}
[data-client-vault] .cv-foot{display:flex;align-items:center;gap:10px;padding:12px 20px 14px;font-size:13px;color:var(--muted);border-top:1px solid var(--line)}
[data-client-vault].cv-backdrop{position:fixed;inset:0;z-index:1000;background:rgba(4,14,17,.62);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:grid;place-items:start center;padding-top:14vh}
[data-client-vault] .cv-dialog{width:min(470px,calc(100vw - 32px));padding:24px;border-radius:20px;background:var(--surface);border:1px solid var(--line-strong);box-shadow:0 30px 60px -30px rgba(0,0,0,.8);animation:cvIn .22s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-dialog h2{margin:0 0 14px;font:600 20px/1.25 "Literata",Georgia,serif}
[data-client-vault] .cv-dialog label.f{display:block;font-size:13.5px;font-weight:600;margin-bottom:6px}
[data-client-vault] .cv-dialog input[type="text"]{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--line-strong);background:var(--input);font-size:15px;outline:none}
[data-client-vault] .cv-dialog input[type="text"]:focus{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-client-vault] .cv-opt{display:flex;gap:10px;align-items:center;min-height:44px;padding:0 12px;border-radius:12px;border:1px solid var(--line);cursor:pointer;transition:border-color .15s,background .15s}
[data-client-vault] .cv-opt:hover{border-color:var(--hover-line);background:var(--hover-tint)}
[data-client-vault] .cv-opt.on{border-color:var(--brand-text);background:var(--brand-soft)}
[data-client-vault] .cv-problem{margin-top:10px;color:var(--danger);font-size:13.5px}
[data-client-vault] .cv-dialog .row{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
[data-client-vault] .d3{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .2s ease-out,box-shadow .18s ease,border-color .18s ease}
[data-client-vault] .d3:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-3px)}
[data-client-vault] .cv-stat.d3 .cv-ic{position:relative;transition:transform .45s cubic-bezier(.34,1.56,.64,1),box-shadow .3s}
[data-client-vault] .cv-stat.d3 .cv-ic::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .2s;background:radial-gradient(circle at calc((var(--px,0) + .5) * 100%) calc((var(--py,0) + .5) * 100%),rgba(255,255,255,.5),transparent 60%)}
[data-client-vault] .cv-stat.d3:hover .cv-ic{transform:translate(calc(var(--px,0) * 6px),calc(var(--py,0) * 6px - 6px)) scale(1.16) rotate(-5deg);box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 40%,transparent) inset,0 16px 22px -10px color-mix(in srgb,var(--c) 75%,#000),0 4px 8px -4px rgba(0,0,0,.5)}
[data-client-vault] .cv-stat.d3:hover .cv-ic::before{opacity:1}
[data-client-vault] .cv-stat.d3:hover .cv-ic svg{transform:translate(calc(var(--px,0) * 7px),calc(var(--py,0) * 7px)) scale(1.06)}
[data-client-vault] .cv-f3d{position:relative;width:62px;height:50px;flex:none;perspective:170px;margin:12px 4px 0 0;transition:transform .45s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-f3d::after{content:"";position:absolute;left:8%;right:8%;bottom:-9px;height:8px;border-radius:50%;background:rgba(0,0,0,.45);filter:blur(4px);transition:transform .45s,opacity .45s;opacity:.6}
[data-client-vault] .cv-f3d i{position:absolute;display:block}
[data-client-vault] .cv-f3d .bk{inset:0;border-radius:6px 11px 11px 11px;background:linear-gradient(180deg,color-mix(in srgb,var(--gold) 55%,#000),color-mix(in srgb,var(--gold) 70%,#000))}
[data-client-vault] .cv-f3d .bk::before{content:"";position:absolute;left:0;top:-7px;width:25px;height:10px;border-radius:5px 5px 0 0;background:color-mix(in srgb,var(--gold) 55%,#000)}
[data-client-vault] .cv-f3d .pg{left:8px;right:9px;top:4px;height:38px;border-radius:4px;background:repeating-linear-gradient(180deg,transparent 0 6px,rgba(40,60,70,.25) 6px 7px) 6px 9px/68% 70% no-repeat,#FBF8EF;box-shadow:0 2px 5px rgba(0,0,0,.3);transition:transform .5s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-f3d .pg.b{left:14px;right:4px;top:6px;background:#E9E2D0;transition-delay:.05s}
[data-client-vault] .cv-f3d .fr{left:0;right:0;bottom:0;height:37px;border-radius:6px 6px 11px 11px;transform-origin:50% 100%;background:linear-gradient(180deg,color-mix(in srgb,var(--gold) 90%,#fff),var(--gold));box-shadow:0 -1px 0 rgba(255,255,255,.4) inset,0 10px 16px -8px rgba(0,0,0,.6);transition:transform .5s cubic-bezier(.34,1.56,.64,1),filter .5s}
[data-client-vault] .cv-folder:hover .cv-f3d{transform:translateY(-4px) scale(1.06)}
[data-client-vault] .cv-folder:hover .cv-f3d::after{transform:scale(.8);opacity:.35}
[data-client-vault] .cv-folder:hover .cv-f3d .pg{transform:translateY(-20px) rotate(-8deg)}
[data-client-vault] .cv-folder:hover .cv-f3d .pg.b{transform:translateY(-15px) translateX(3px) rotate(10deg)}
[data-client-vault] .cv-folder:hover .cv-f3d .fr{transform:rotateX(-62deg);filter:brightness(1.08)}
[data-client-vault] .cv-ib{position:relative}
[data-client-vault] .cv-ib.k-down:active:not(:disabled){transform:perspective(200px) translateZ(-14px)}
[data-client-vault] .cv-ib.k-down.hit svg,[data-client-vault] .cv-ib.k-down.hit:hover:not(:disabled) svg{animation:cvDrop .55s cubic-bezier(.34,1.56,.64,1)}
[data-client-vault] .cv-burst{position:absolute;left:50%;top:50%;width:0;height:0;pointer-events:none}
[data-client-vault] .cv-burst i{position:absolute;left:-3px;top:-3px;width:6px;height:6px;border-radius:50%;background:var(--brand-text);opacity:0;animation:cvBurst .6s ease-out forwards;transform:rotate(var(--a)) translateY(0)}
[data-client-vault] .cv-burst i:nth-child(even){background:var(--gold);width:4px;height:4px}
[data-client-vault] .cv-cta.k3d{box-shadow:0 4px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 12px 24px -12px rgba(46,196,214,.8)}
[data-client-vault] .cv-cta.k3d:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 6px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 16px 28px -12px rgba(46,196,214,.9)}
[data-client-vault] .cv-cta.k3d:active:not(:disabled){transform:translateY(3px);box-shadow:0 1px 0 color-mix(in srgb,var(--brand-solid) 55%,#000),0 6px 14px -10px rgba(46,196,214,.8)}
@keyframes cvDrop{0%{transform:translateY(-9px);opacity:0}60%{transform:translateY(2px);opacity:1}100%{transform:none}}
@keyframes cvBurst{0%{opacity:1;transform:rotate(var(--a)) translateY(0) scale(1)}100%{opacity:0;transform:rotate(var(--a)) translateY(-22px) scale(.4)}}
@keyframes cvShine{to{transform:translateX(360%) skewX(-20deg)}}
@keyframes cvBlink{0%,42%,52%,100%{transform:scaleY(1)}47%{transform:scaleY(.1)}}
@keyframes cvBounce{0%,100%{transform:translateY(0)}40%{transform:translateY(3px)}70%{transform:translateY(-1px)}}
@keyframes cvNudge{0%,100%{transform:translateX(0) rotate(0)}40%{transform:translateX(2px) rotate(-8deg)}}
@keyframes cvShake{0%,100%{transform:rotate(0)}25%{transform:rotate(-12deg)}50%{transform:rotate(10deg)}75%{transform:rotate(-6deg)}}
@keyframes cvIn{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-client-vault] *,[data-client-vault] *::after{transition:none!important;animation:none!important}}`;
