'use client';
import React, { useState, useEffect } from 'react';
import { Logo } from './UIComponents';
import { Ic } from './Icons';

const LSTEPS = [
  { l:"Professional Profile", s:"Name, license & specialization" },
  { l:"Credentials & Photo",  s:"Documents & profile picture"    },
  { l:"Office & Availability",s:"Location, fees & working hours" },
  { l:"Workspace Ready",      s:"Your profile is complete"       },
];
const SPECS = [
  { label: "Corporate", icon: "⚖" },
  { label: "Criminal", icon: "⚒" },
  { label: "Family", icon: "⌂" },
  { label: "Civil Litigation", icon: "▦" },
  { label: "Real Estate", icon: "▣" },
  { label: "Immigration", icon: "◌" },
  { label: "Environment Law", icon: "◎" },
  { label: "Intellectual Property", icon: "◉" },
];

export function OnboardSidebar({ t, step }) {
  const rc = t.primary;
  return (
    <div style={{width:252,flexShrink:0,height:"100vh",overflow:"hidden",borderRight:`1px solid ${t.border}`,background:t.mode==="dark"?"linear-gradient(180deg,#182B32 0%,#20373F 100%)":"linear-gradient(180deg,#ffffff 0%,#f5f8f6 100%)",padding:"24px",display:"flex",flexDirection:"column"}}>
      <Logo t={t} sm/>
      <div style={{height:1,background:t.border,margin:"18px 0 16px"}}/>
      <p style={{fontFamily:"'Cormorant Garamond',serif",fontSize:19,fontWeight:700,color:t.text,lineHeight:1.15,marginBottom:5,letterSpacing:"-.02em"}}>Profile Setup</p>
      <p style={{fontSize:12,color:t.textMuted,lineHeight:1.55,marginBottom:22,fontWeight:400}}>Complete your profile to go live</p>
      <div style={{flex:1,display:"flex",flexDirection:"column",justifyContent:"space-between"}}>
        {LSTEPS.map((s,i) => {
          const done=i<step, active=i===step;
          return (
            <div key={i} style={{display:"flex",gap:14,flex:1,opacity:done||active?1:.22,transition:"opacity .3s"}}>
              <div style={{display:"flex",flexDirection:"column",alignItems:"center",flexShrink:0}}>
                <div style={{width:36,height:36,borderRadius:"50%",flexShrink:0,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,fontWeight:700,background:done?rc:active?rc:"transparent",border:`2px solid ${done||active?rc:t.border}`,color:done||active?(t.mode==="dark"?"#182B32":"#fff"):t.textMuted,transition:"all .3s",boxShadow:active?`0 0 0 5px ${t.primaryGlow2}`:"none"}}>
                  {done ? <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke={t.mode==="dark"?"#182B32":"#fff"} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg> : <span style={{fontFamily:"'Inter',sans-serif",fontSize:13}}>{i+1}</span>}
                </div>
                {i < LSTEPS.length-1 && <div style={{width:2,flex:1,minHeight:24,background:done?`linear-gradient(180deg,${rc} 0%,${rc}55 100%)`:t.border,margin:"4px 0",borderRadius:2,transition:"background .4s"}}/>}
              </div>
              <div style={{paddingTop:7}}>
                <p style={{fontSize:14.5,fontWeight:active?700:500,color:active?t.text:done?t.textDim:t.textMuted,lineHeight:1.2,letterSpacing:"-.02em",transition:"all .3s",marginBottom:3}}>{s.l}</p>
                <p style={{fontSize:11.5,color:active?t.textMuted:t.textFaint,lineHeight:1.4}}>{s.s}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function Onboarding({ t, role, onComplete }) {
  const [step, setStep] = useState(0);
  const [specs, setSpecs] = useState([]);

  useEffect(() => { if (role !== "lawyer") onComplete(); }, []);
  if (role !== "lawyer") return null;

  const total = LSTEPS.length;
  const isLast = step === total - 1;
  const togSpec = (s) => setSpecs((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]));

  const TextIn = ({placeholder,type="text",right,icon,d=0}) => {
    const [f,setF] = useState(false);
    return (
      <div style={{display:"flex",alignItems:"center",gap:12,background:f?t.inputFocus:t.mode==="dark"?"rgba(42,90,104,0.22)":t.inputBg,border:`1.5px solid ${f?t.primary:t.border}`,borderRadius:t.r.lg,padding:"0 20px",transition:"all .22s",boxShadow:f?`0 0 0 3px ${t.primaryGlow2}`:"none",animation:`fadeUp .4s ease ${d}s both`}}>
        {icon&&<span style={{color:f?t.primary:t.textFaint,flexShrink:0,display:"flex",transition:"color .2s"}}>{icon}</span>}
        <input type={type} placeholder={placeholder} onFocus={()=>setF(true)} onBlur={()=>setF(false)}
          style={{flex:1,minWidth:0,padding:"11px 0",background:"transparent",border:"none",color:t.text,fontSize:13.5,outline:"none",fontFamily:"'Inter',sans-serif"}}/>
        {right}
      </div>
    );
  };

  const SL = ({children,mt=0}) => (
    <p style={{fontSize:10,fontWeight:700,color:t.textMuted,textTransform:"uppercase",letterSpacing:".14em",marginBottom:12,marginTop:mt}}>{children}</p>
  );

  const renderStep = () => {
    if (step === 0) return (
      <div style={{animation:"slideR .3s ease both",height:"100%",display:"flex",flexDirection:"column",overflow:"hidden"}}>
        <div style={{display:"flex",alignItems:"center",gap:12,padding:"2px 2px 14px",flexShrink:0}}>
          <div style={{width:34,height:34,borderRadius:t.r.md,background:t.primaryGlow2,border:`1px solid ${t.primary}40`,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
            {Ic.user(t.primary)}
          </div>
          <div>
            <p style={{fontSize:15.5,fontWeight:700,color:t.text,lineHeight:1.2,marginBottom:2}}>Professional Profile</p>
            <p style={{fontSize:12.5,color:t.textMuted,lineHeight:1.35}}>Visible to clients on your public listing</p>
          </div>
        </div>

        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(360px, 1fr))",gap:14,alignItems:"start"}}>
          <div style={{background:t.mode==="dark"?"linear-gradient(180deg, rgba(42,90,104,0.2), rgba(42,90,104,0.12))":"rgba(40,96,112,0.04)",border:`1px solid ${t.border}`,borderRadius:t.r.lg,padding:"16px 18px",minHeight:270,overflow:"hidden"}}>
            <p style={{fontSize:10,fontWeight:700,color:t.primary,textTransform:"uppercase",letterSpacing:".12em",marginBottom:2,display:"flex",alignItems:"center",gap:6}}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2.5"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4.4 3.6-7 8-7s8 2.6 8 7"/></svg>
              Identity &amp; License
            </p>
            <p style={{fontSize:12.5,color:t.textMuted,marginBottom:14,lineHeight:1.45}}>Visible to clients on your public listing.</p>
            <div style={{display:"grid",gridTemplateColumns:"repeat(2, minmax(0, 1fr))",gap:10,marginBottom:10}}>
              <div style={{minWidth:0}}><SL>Full Name</SL><TextIn placeholder="Adv. Ahmad Khan" icon={Ic.user(t.textFaint)}/></div>
              <div style={{minWidth:0}}><SL>Bar License No.</SL><TextIn placeholder="BCI/PNJ/2019/12345" icon={Ic.cert(t.textFaint)}/></div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(2, minmax(0, 1fr))",gap:10}}>
              <div style={{minWidth:0}}><SL>Years of Experience</SL><TextIn type="number" placeholder="e.g. 8" icon={Ic.clock(t.textFaint)}/></div>
              <div style={{minWidth:0}}><SL>Bar Council</SL><TextIn placeholder="Punjab Bar Council" icon={Ic.shield(t.textFaint)}/></div>
            </div>
          </div>

          <div style={{background:t.mode==="dark"?"linear-gradient(180deg, rgba(42,90,104,0.2), rgba(42,90,104,0.12))":"rgba(40,96,112,0.04)",border:`1px solid ${t.border}`,borderRadius:t.r.lg,padding:"16px 18px",minHeight:270,overflow:"hidden"}}>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:2}}>
              <p style={{fontSize:10,fontWeight:700,color:t.primary,textTransform:"uppercase",letterSpacing:".12em",display:"flex",alignItems:"center",gap:6}}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2.5"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4" strokeLinecap="round"/></svg>
                Specialization
              </p>
              {specs.length > 0 && (
                <span style={{fontSize:11,fontWeight:600,color:t.primary,background:t.primaryGlow2,padding:"2px 8px",borderRadius:99,border:`1px solid ${t.primary}30`}}>
                  {specs.length} selected
                </span>
              )}
            </div>
            <p style={{fontSize:12.5,color:t.textMuted,marginBottom:14,lineHeight:1.45}}>Tap to select your areas of expertise (min. 1).</p>

            <div style={{display:"grid",gridTemplateColumns:"repeat(4, minmax(0, 1fr))",gap:9}}>
              {SPECS.map((s) => {
                const active = specs.includes(s.label);
                return (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => togSpec(s.label)}
                    className="aBtn"
                    style={{
                      minHeight:84,
                      borderRadius:t.r.md,
                      cursor:"pointer",
                      border:`1.5px solid ${active ? t.primary : t.border}`,
                      background:active ? t.primaryGlow2 : (t.mode === "dark" ? "rgba(42,90,104,0.18)" : "rgba(0,0,0,0.03)"),
                      color:active ? t.primary : t.textDim,
                      display:"flex",
                      flexDirection:"column",
                      alignItems:"center",
                      justifyContent:"center",
                      gap:8,
                      padding:"10px 8px",
                      textAlign:"center",
                      boxShadow:active ? `0 0 0 1px ${t.primary}55` : "none",
                      transition:"all .2s",
                    }}
                  >
                    <span style={{fontSize:17,lineHeight:1,fontWeight:700}}>{s.icon}</span>
                    <span style={{fontSize:12.5,fontWeight:500,lineHeight:1.2}}>{s.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );

    if (step === 1) return (
      <div style={{animation:"slideR .3s ease both",display:"flex",flexDirection:"column",flex:1,minHeight:0}}>
        <div style={{marginBottom:18,flexShrink:0}}>
          <h2 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:30,fontWeight:700,color:t.text,lineHeight:1.12,letterSpacing:"-.02em",marginBottom:4}}>Credentials &amp; Photo</h2>
          <p style={{color:t.textMuted,fontSize:13.5,lineHeight:1.55}}>Upload a professional photo and your credentials — clients see these before booking.</p>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"200px 1fr",gap:16,flex:1,minHeight:0}}>
          <div style={{display:"flex",flexDirection:"column",gap:12,padding:"18px",borderRadius:t.r.lg,background:t.mode==="dark"?"rgba(42,90,104,0.18)":t.inputBg,border:`1px solid ${t.border}`,alignItems:"center",textAlign:"center"}}>
            <div style={{width:80,height:80,borderRadius:"50%",background:`linear-gradient(135deg,${t.primary}25,${t.primary}55)`,border:`2px solid ${t.primary}50`,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
              <span style={{fontFamily:"'Cormorant Garamond',serif",fontSize:26,fontWeight:700,color:t.primary}}>AK</span>
            </div>
            <div>
              <p style={{fontSize:13,fontWeight:700,color:t.text,marginBottom:4}}>Profile Photo</p>
              <p style={{fontSize:11.5,color:t.textMuted,lineHeight:1.5,marginBottom:12}}>JPG or PNG · min 200×200px</p>
              <div style={{display:"flex",flexDirection:"column",gap:8}}>
                <button className="aBtn" style={{padding:"8px 14px",borderRadius:99,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:12.5,fontWeight:700,cursor:"pointer",boxShadow:`0 4px 12px ${t.primaryGlow}`}}>Upload Photo</button>
                <button className="aBtn" style={{padding:"8px 14px",borderRadius:99,background:"transparent",border:`1.5px solid ${t.border}`,color:t.textDim,fontSize:12.5,fontWeight:500,cursor:"pointer"}}>Take Photo</button>
              </div>
            </div>
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:0,minHeight:0}}>
            <p style={{fontSize:10,fontWeight:700,color:t.textMuted,textTransform:"uppercase",letterSpacing:".14em",marginBottom:10,flexShrink:0}}>Professional Credentials</p>
            <div style={{display:"flex",flexDirection:"column",gap:10,flex:1}}>
              {[{l:"Bar Council Certificate",e:"📋",hint:"Official bar membership certificate"},{l:"Educational Credentials",e:"🎓",hint:"LLB or equivalent law degree"},{l:"Professional Certificates",e:"🏆",hint:"Additional certifications or awards"}].map((doc,i)=>(
                <div key={i} style={{display:"flex",alignItems:"center",gap:14,padding:"14px 16px",borderRadius:t.r.lg,background:t.mode==="dark"?"rgba(42,90,104,0.18)":t.inputBg,border:`1px solid ${t.border}`,flex:1,animation:`fadeUp .3s ease ${i*.05}s both`}}>
                  <div style={{width:38,height:38,borderRadius:t.r.md,background:t.primaryGlow2,border:`1px solid ${t.primary}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:20,flexShrink:0}}>{doc.e}</div>
                  <div style={{flex:1,minWidth:0}}>
                    <p style={{fontSize:13.5,fontWeight:600,color:t.text,marginBottom:2}}>{doc.l}</p>
                    <p style={{fontSize:11.5,color:t.textFaint,lineHeight:1.4,whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{doc.hint} · PDF, JPG or PNG · Max 5MB</p>
                  </div>
                  <button className="aBtn" style={{padding:"8px 18px",borderRadius:99,background:t.primaryGlow2,border:`1.5px solid ${t.primary}50`,color:t.primary,fontSize:12.5,fontWeight:700,cursor:"pointer",flexShrink:0}}>Upload</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );

    if (step === 2) return (
      <div style={{animation:"slideR .3s ease both",display:"flex",flexDirection:"column",gap:0}}>
        <div style={{marginBottom:16}}>
          <h2 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:30,fontWeight:700,color:t.text,lineHeight:1.12,letterSpacing:"-.02em",marginBottom:5}}>Office &amp; Availability</h2>
          <p style={{color:t.textMuted,fontSize:14,lineHeight:1.6,fontWeight:400}}>Help clients find your office and know when they can book a consultation.</p>
        </div>
        <SL>Location</SL>
        <div style={{display:"flex",flexDirection:"column",gap:10,marginBottom:16}}>
          <TextIn placeholder="Office address — e.g. 14 Legal Street, Lahore" icon={Ic.pin(t.textFaint)} d={0}/>
          <TextIn type="tel" placeholder="Office phone — e.g. +92 42 111 000 000" icon={Ic.phone(t.textFaint)} d={.05}/>
        </div>
        <SL mt={4}>Consultation Fee Range (PKR)</SL>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:16}}>
          {[["Minimum Fee","5,000"],["Maximum Fee","50,000"]].map(([lb,ph])=>(
            <div key={lb} style={{animation:"fadeUp .35s ease both"}}>
              <label style={{display:"block",fontSize:12,color:t.textMuted,fontWeight:500,marginBottom:6}}>{lb}</label>
              <div style={{display:"flex",alignItems:"center",background:t.mode==="dark"?"rgba(42,90,104,0.22)":t.inputBg,border:`1.5px solid ${t.border}`,borderRadius:t.r.lg,padding:"0 18px"}}>
                <span style={{fontSize:13,color:t.textFaint,marginRight:8,fontWeight:500}}>PKR</span>
                <input placeholder={ph} style={{flex:1,padding:"11px 0",background:"transparent",border:"none",color:t.text,fontSize:14,outline:"none",fontFamily:"'Inter',sans-serif"}}/>
              </div>
            </div>
          ))}
        </div>
        <SL mt={4}>Working Schedule</SL>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>
          {[["Working Days","Mon – Fri"],["Office Hours","9:00 AM – 6:00 PM"]].map(([lb,ph])=>(
            <div key={lb} style={{animation:"fadeUp .35s ease .08s both"}}>
              <label style={{display:"block",fontSize:12,color:t.textMuted,fontWeight:500,marginBottom:8}}>{lb}</label>
              <div style={{background:t.mode==="dark"?"rgba(42,90,104,0.22)":t.inputBg,border:`1.5px solid ${t.border}`,borderRadius:t.r.lg,padding:"0 18px"}}>
                <input placeholder={ph} style={{width:"100%",padding:"12px 0",background:"transparent",border:"none",color:t.text,fontSize:14,outline:"none",fontFamily:"'Inter',sans-serif"}}/>
              </div>
            </div>
          ))}
        </div>
      </div>
    );

    if (isLast) return (
      <div style={{animation:"scaleUp .4s ease both",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",textAlign:"center",height:"100%",minHeight:400,padding:"20px 0"}}>
        <div style={{position:"relative",marginBottom:24}}>
          <div style={{position:"absolute",inset:-20,borderRadius:"50%",background:t.primaryGlow2,animation:"pulse 2.5s ease-in-out infinite"}}/>
          <div style={{width:100,height:100,borderRadius:"50%",position:"relative",background:t.primaryGlow2,border:`2px solid ${t.primary}`,display:"flex",alignItems:"center",justifyContent:"center",boxShadow:`0 0 60px ${t.primaryGlow}`}}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="1.6"><path d="M12 3v18M3 9l9-6 9 6M5 12l-2 5h4l-2-5zM19 12l-2 5h4l-2-5zM3 19h18" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
        </div>
        <h2 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:36,fontWeight:700,color:t.text,marginBottom:6,letterSpacing:"-.03em",fontStyle:"italic"}}>Your workspace is ready</h2>
        <div style={{width:56,height:3,borderRadius:2,background:t.grad1,margin:"0 auto 18px"}}/>
        <p style={{color:t.textMuted,fontSize:14,lineHeight:1.75,maxWidth:480,margin:"0 auto 28px"}}>Your profile is live. Research with AI, manage cases, automated documents, and collaborate with clients — all from one professional workspace.</p>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,width:"100%",maxWidth:540}}>
          {[{icon:"✅",label:"Profile complete",sub:"All steps done"},{icon:"🔐",label:"Security active",sub:"AES-256 encrypted"},{icon:"🚀",label:"Ready to launch",sub:"Go live now"}].map(({icon,label,sub})=>(
            <div key={label} style={{padding:"16px 12px",borderRadius:t.r.lg,background:t.mode==="dark"?"rgba(42,90,104,0.2)":t.inputBg,border:`1px solid ${t.border}`,textAlign:"center"}}>
              <div style={{fontSize:24,marginBottom:8}}>{icon}</div>
              <p style={{fontSize:13,fontWeight:600,color:t.text,marginBottom:4}}>{label}</p>
              <p style={{fontSize:11.5,color:t.textFaint}}>{sub}</p>
            </div>
          ))}
        </div>
      </div>
    );
    return null;
  };

  const NavButtons = () => (
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"14px 16px",marginTop:14,borderRadius:t.r.xl,border:`1px solid ${t.border}`,background:t.mode==="dark"?"rgba(24,43,50,0.78)":"rgba(255,255,255,0.9)",backdropFilter:"blur(10px)",boxShadow:t.shadowSm}}>
      <button onClick={()=>setStep(s=>Math.max(0,s-1))} disabled={step===0} className="aBtn"
        style={{display:"flex",alignItems:"center",gap:8,padding:"10px 22px",borderRadius:99,background:"transparent",border:`1.5px solid ${step===0?t.border+"40":t.border}`,color:step===0?t.textFaint:t.textDim,fontSize:13,fontWeight:600,cursor:step===0?"default":"pointer",opacity:step===0?.3:1,transition:"opacity .2s"}}>
        {Ic.arrowL(step===0?t.textFaint:t.textDim)} Back
      </button>
      <div style={{display:"flex",alignItems:"center",gap:10}}>
        <span style={{fontSize:11.5,color:t.textFaint,fontWeight:500,marginRight:4}}>{step+1} / {total}</span>
        {!isLast && (
          <button onClick={()=>setStep(s=>s+1)} className="aBtn" style={{padding:"10px 20px",borderRadius:99,background:"transparent",border:`1.5px solid ${t.border}`,color:t.textMuted,fontSize:13,fontWeight:500,cursor:"pointer"}}>Skip</button>
        )}
        {isLast ? (
          <button className="aBtn" onClick={onComplete} style={{padding:"10px 28px",borderRadius:99,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:13.5,fontWeight:700,display:"flex",alignItems:"center",gap:8,cursor:"pointer",boxShadow:`0 6px 20px ${t.primaryGlow}`}}>
            Submit Profile {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
          </button>
        ) : (
          <button className="aBtn" onClick={()=>setStep(s=>s+1)} style={{padding:"10px 28px",borderRadius:99,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:13.5,fontWeight:700,display:"flex",alignItems:"center",gap:8,cursor:"pointer",boxShadow:`0 6px 20px ${t.primaryGlow}`}}>
            Continue {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div style={{display:"flex",height:"100vh",overflow:"hidden",background:t.bg}}>
      <OnboardSidebar t={t} step={step}/>
      <div style={{flex:1,display:"flex",flexDirection:"column",height:"100vh",overflow:"hidden",background:t.mode==="dark"?t.bg:t.panel,padding:"62px clamp(18px, 3.8vw, 56px) 22px"}}>
        <div style={{flex:1,minHeight:0,display:"flex",flexDirection:"column",width:"100%",maxWidth:1260,margin:"0 auto"}}>
          <div style={{flex:1,minHeight:0,display:"flex",flexDirection:"column"}}>{renderStep()}</div>
          <NavButtons/>
        </div>
      </div>
    </div>
  );
}
