'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Logo, PillInput, FieldLabel, Checkbox } from '@/app/UIComponents';
import { Ic } from '@/app/Icons';

import { DARK } from '@/components/admin/themes.js';

function SignUp({ t, role, goBack, onNext }) {
  const [spw, setSPW] = useState(false);
  const [terms, setTerms] = useState(false);
  const [pw, setPw] = useState("");

  const strength = pw.length === 0 ? 0
    : pw.length < 8 ? 1
    : (pw.length >= 12 && /[A-Z]/.test(pw) && /[0-9]/.test(pw)) ? 3 : 2;

  const sLabels = ["","Weak — use 8+ characters","Good — add numbers to strengthen","Strong password ✓"];
  const sColors = [t.border, t.danger, t.warn, t.success];

  return (
    <div style={{
      minHeight:"100vh", background:t.bg,
      display:"flex", alignItems:"center", justifyContent:"center",
      padding:"32px 20px", position:"relative", overflow:"hidden",
    }}>
      {/* Background glows */}
      <div style={{position:"absolute",width:400,height:400,borderRadius:"50%",background:t.primaryGlow2,filter:"blur(90px)",top:-100,right:-80,pointerEvents:"none"}}/>
      <div style={{position:"absolute",width:300,height:300,borderRadius:"50%",background:t.primaryGlow2,filter:"blur(70px)",bottom:-60,left:-60,pointerEvents:"none"}}/>

      {/* Card */}
      <div style={{
        width:"100%", maxWidth:500,
        background: t.mode==="dark" ? "rgba(32,55,63,0.98)" : t.surface,
        borderRadius: t.r.xl,
        border:`1px solid ${t.border}`,
        padding:"24px 22px 20px",
        boxShadow: t.shadowCard,
        position:"relative", zIndex:1,
        backdropFilter:"blur(20px)",
        animation:"scaleUp .35s cubic-bezier(.4,0,.2,1) both",
      }}>

        {/* Logo */}
        <div style={{marginBottom:16}}><Logo t={t} sm/></div>

        {/* Header */}
        <div style={{marginBottom:16}}>
          <h1 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:22,fontWeight:700,color:t.text,lineHeight:1.2,marginBottom:3}}>
            {role==="lawyer" ? "Create your Lawyer Profile" : "Create your Account"}
          </h1>
          <p style={{color:t.textMuted,fontSize:12.5}}>Let's get started — it's free.</p>
        </div>

        {/* Fields */}
        <div style={{display:"flex",flexDirection:"column",gap:10}}>

          {/* Name row */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            <div>
              <FieldLabel t={t}>First Name</FieldLabel>
              <PillInput t={t} placeholder="Ahmad" icon={Ic.user(t.textFaint)}/>
            </div>
            <div>
              <FieldLabel t={t}>Last Name</FieldLabel>
              <PillInput t={t} placeholder="Khan"/>
            </div>
          </div>

          {/* Email */}
          <div>
            <FieldLabel t={t}>Email Address</FieldLabel>
            <PillInput t={t} placeholder="you@lawfirm.com" type="email" icon={Ic.mail(t.textFaint)}/>
          </div>

          {/* Phone */}
          <div>
            <FieldLabel t={t}>Phone Number</FieldLabel>
            <PillInput t={t} placeholder="+92 300 000 0000" type="tel" icon={Ic.phone(t.textFaint)}/>
          </div>

          {/* CNIC — lawyer only */}
          {role==="lawyer" && (
            <div>
              <FieldLabel t={t}>CNIC / Bar Council ID</FieldLabel>
              <PillInput t={t} placeholder="BCI/PNJ/2019/12345" icon={Ic.cert(t.textFaint)}/>
            </div>
          )}

          {/* Password + strength */}
          <div>
            <FieldLabel t={t}>Password</FieldLabel>
            <PillInput
              t={t} placeholder="Min. 8 characters"
              type={spw?"text":"password"}
              icon={Ic.lock(t.textFaint)}
              value={pw}
              onChange={e=>setPw(e.target.value)}
              right={
                <button onClick={()=>setSPW(p=>!p)} style={{background:"none",border:"none",cursor:"pointer",padding:0,color:t.textFaint,display:"flex",flexShrink:0}}>
                  {spw ? Ic.eyeOff(t.textFaint) : Ic.eye(t.textFaint)}
                </button>
              }
            />
            {/* Strength bar */}
            <div style={{height:24,marginTop:5}}>
              {pw.length > 0 && (
                <>
                  <div style={{display:"flex",gap:3,marginBottom:3}}>
                    {[1,2,3].map(n=>(
                      <div key={n} style={{flex:1,height:2.5,borderRadius:2,transition:"background .3s",background:n<=strength ? sColors[strength] : t.border}}/>
                    ))}
                  </div>
                  <span style={{fontSize:11,color:sColors[strength],fontWeight:600}}>{sLabels[strength]}</span>
                </>
              )}
            </div>
          </div>

        </div>{/* /fields */}

        {/* Optional links */}
        <div style={{display:"flex",gap:16,marginTop:2}}>
          <span style={{fontSize:12,color:t.primary,cursor:"pointer",fontWeight:500}}>Have referral?</span>
          <span style={{fontSize:12,color:t.primary,cursor:"pointer",fontWeight:500}}>Redeem coupon?</span>
          {role==="lawyer" && <span style={{fontSize:12,color:t.primary,cursor:"pointer",fontWeight:500}}>Joined a Firm?</span>}
        </div>

        {/* Terms */}
        <label style={{display:"flex",alignItems:"flex-start",gap:9,cursor:"pointer",marginTop:12}}>
          <Checkbox on={terms} onChange={()=>setTerms(v=>!v)} t={t}/>
          <span style={{fontSize:12,color:t.textMuted,lineHeight:1.5,paddingTop:1}}>
            I agree to the <span style={{color:t.primary,fontWeight:600}}>Terms and Conditions</span>
          </span>
        </label>

        {/* Free badge */}
        <div style={{display:"flex",alignItems:"center",gap:8,marginTop:10,padding:"8px 12px",borderRadius:t.r.md,background:t.primaryGlow2,border:`1px solid ${t.primary}30`}}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={t.primary} strokeWidth="2.5"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          <p style={{fontSize:12,color:t.primary,fontWeight:500}}>Free to get started — no credit card required</p>
        </div>

        {/* Actions */}
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginTop:16,gap:10}}>
          {/* Role badge / back */}
          <button onClick={goBack} style={{
            display:"flex", alignItems:"center", gap:7,
            padding:"8px 12px 8px 9px",
            borderRadius:t.r.md,
            background: t.mode==="dark" ? "rgba(42,68,80,0.85)" : t.inputBg,
            border:`1.5px solid ${t.border}`,
            cursor:"pointer", flexShrink:0,
          }}>
            <div style={{width:26,height:26,borderRadius:"50%",background:t.primaryGlow2,border:`1.5px solid ${t.primary}50`,display:"flex",alignItems:"center",justifyContent:"center"}}>
              {role==="lawyer" ? Ic.scale(t.primary) : Ic.client(t.primary)}
            </div>
            <span style={{fontSize:12,fontWeight:600,color:t.textDim,whiteSpace:"nowrap"}}>
              {role==="lawyer" ? "Individual Lawyer" : "Public User"}
            </span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={t.textFaint} strokeWidth="2"><path d="M6 9l6 6 6-6"/></svg>
          </button>

          {/* Create */}
          <button className="aBtn" onClick={onNext} style={{
            flex:1, padding:"11px 16px",
            borderRadius:t.r.md,
            background:t.grad1, border:"none",
            color: t.mode==="dark" ? "#182B32" : "#fff",
            fontSize:13, fontWeight:700,
            display:"flex", alignItems:"center", justifyContent:"center", gap:7,
            cursor:"pointer",
            boxShadow:`0 6px 20px ${t.primaryGlow}`,
          }}>
            Create Account {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
          </button>
        </div>

      </div>
    </div>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const [role, setRole] = React.useState('client');
  return (
    <SignUp
      t={DARK}
      role={role}
      goBack={() => setRole(r => r === 'client' ? 'lawyer' : 'client')}
      onNext={() => { try { localStorage.setItem('aai-role', role); } catch {} router.push(role === 'lawyer' ? '/lawyer' : '/login'); }}
    />
  );
}
