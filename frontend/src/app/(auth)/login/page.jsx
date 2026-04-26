'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Logo, InputField, PrimaryBtn, Checkbox, Divider, GoogleBtn } from '@/app/UIComponents';
import { AuthLayout } from '@/app/LayoutComponents';
import { Ic } from '@/app/Icons';

import { DARK } from '@/components/admin/themes.js';

function LoginScreen({ t, role, setRole, onSuccess, onForgot, onCreateAccount, goBack }) {
  const [spw, setSPW] = useState(false);
  const [rem, setRem] = useState(false);
  return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{animation:"scaleUp .35s cubic-bezier(.4,0,.2,1) both"}}>
        <button onClick={goBack} className="aBtn" style={{display:"flex",alignItems:"center",gap:7,background:"none",border:"none",cursor:"pointer",color:t.textMuted,fontSize:13,fontWeight:500,marginBottom:22,padding:0}}>
          {Ic.arrowL(t.textFaint)} Back
        </button>
        {/* Role selector */}
        <div style={{display:"flex",gap:6,marginBottom:20,padding:4,background:t.inputBg,borderRadius:t.r.md,border:`1px solid ${t.border}`}}>
          {["client","lawyer"].map(r => (
            <button key={r} onClick={() => setRole(r)} style={{
              flex:1, padding:"7px 0", borderRadius:8, border:"none", cursor:"pointer",
              background: role===r ? t.grad1 : "transparent",
              color: role===r ? (t.mode==="dark"?"#182B32":"#fff") : t.textMuted,
              fontSize:12.5, fontWeight:600, textTransform:"capitalize", transition:"all .2s",
            }}>{r==="lawyer" ? "Lawyer" : "Client"}</button>
          ))}
        </div>
        <div style={{marginBottom:18}}>
          <h1 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:28,fontWeight:700,color:t.text,lineHeight:1.15,marginBottom:4,animation:"fadeUp .4s ease both"}}>Welcome back</h1>
          <p style={{color:t.textMuted,fontSize:13,animation:"fadeUp .4s ease .04s both"}}>Sign in to your AttorneyAI workspace</p>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:9,padding:"9px 14px",background:t.inputBg,border:`1px solid ${t.border}`,borderRadius:t.r.md,marginBottom:18,animation:"fadeUp .4s ease .08s both"}}>
          {Ic.shield(t.success)}
          <span style={{fontSize:12,color:t.success,fontWeight:600}}>Secure Authentication</span>
          <span style={{fontSize:11.5,color:t.textFaint,marginLeft:"auto"}}>AES-256 · TLS 1.3</span>
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:12}}>
          <InputField label="Email Address" type="email" placeholder="you@lawfirm.com" t={t} d={.12} icon={Ic.mail(t.textFaint)}/>
          <InputField label="Password" type={spw?"text":"password"} placeholder="Enter your password" t={t} d={.17}
            icon={Ic.lock(t.textFaint)}
            right={<button onClick={()=>setSPW(p=>!p)} style={{background:"none",border:"none",cursor:"pointer",padding:0,color:t.textFaint,display:"flex"}}>{spw?Ic.eyeOff(t.textFaint):Ic.eye(t.textFaint)}</button>}/>
        </div>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",margin:"14px 0 18px",animation:"fadeUp .4s ease .21s both"}}>
          <label style={{display:"flex",alignItems:"center",gap:8,cursor:"pointer"}}>
            <Checkbox on={rem} onChange={()=>setRem(v=>!v)} t={t}/>
            <span style={{fontSize:13,color:t.textMuted}}>Remember me</span>
          </label>
          <button onClick={onForgot} style={{background:"none",border:"none",cursor:"pointer",color:t.primary,fontSize:13,fontWeight:600}}>Forgot Password?</button>
        </div>
        <PrimaryBtn onClick={onSuccess} t={t} d={.25}>Sign In {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}</PrimaryBtn>
        <Divider t={t}/>
        <GoogleBtn t={t}/>
        <p style={{textAlign:"center",marginTop:16,fontSize:13,color:t.textMuted,animation:"fadeUp .4s ease .38s both"}}>
          Don't have an account?{" "}
          <button onClick={onCreateAccount} style={{background:"none",border:"none",cursor:"pointer",color:t.primary,fontWeight:700,fontSize:13}}>Create one →</button>
        </p>
      </div>
    </AuthLayout>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [role, setRole] = useState('client');
  return (
    <LoginScreen
      t={DARK}
      role={role}
      setRole={setRole}
      onSuccess={() => { try { localStorage.setItem('aai-role', role); } catch {} router.push(role === 'lawyer' ? '/lawyer' : '/dashboard'); }}
      onForgot={() => router.push('/reset-password')}
      onCreateAccount={() => router.push('/register')}
      goBack={() => router.push('/')}
    />
  );
}
