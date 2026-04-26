'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Logo, InputField } from '@/app/UIComponents';
import { AuthLayout } from '@/app/LayoutComponents';
import { Ic } from '@/app/Icons';

import { DARK } from '@/components/admin/themes.js';

function ForgotPw({ t, goBack }) {
  const [sub, setSub] = useState(0);
  const [spw, setSPW] = useState(false);
  const [scf, setSCF] = useState(false);
  const [resent, setResent] = useState(false);
  const STEP_LABELS = ["Enter your email", "Set new password", "All done"];

  const ProgressHeader = () => (
    <div style={{marginBottom:22}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:8}}>
        <span style={{fontSize:11.5,fontWeight:600,color:t.textMuted,letterSpacing:".04em"}}>
          Step <strong style={{color:t.text,fontFamily:"'Cormorant Garamond',serif",fontSize:13}}>{sub+1}</strong> of 3
          <span style={{color:t.textFaint,fontWeight:400}}> — {STEP_LABELS[sub]}</span>
        </span>
      </div>
      <div style={{width:"100%",height:3,borderRadius:2,background:t.border,overflow:"hidden"}}>
        <div className="stepLine" style={{height:"100%",borderRadius:2,background:t.grad1,width:`${((sub+1)/3)*100}%`}}/>
      </div>
    </div>
  );

  if (sub === 0) return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{animation:"scaleUp .35s ease both"}}>
        <button onClick={goBack} className="aBtn" style={{display:"flex",alignItems:"center",gap:7,background:"none",border:"none",cursor:"pointer",color:t.textMuted,fontSize:13,fontWeight:500,marginBottom:22,padding:0}}>
          {Ic.arrowL(t.textFaint)} Back to login
        </button>
        <div style={{textAlign:"center",marginBottom:22}}>
          <div style={{width:60,height:60,borderRadius:"50%",margin:"0 auto 14px",background:t.primaryGlow2,border:`2px solid ${t.primary}40`,display:"flex",alignItems:"center",justifyContent:"center"}}>{Ic.shield(t.primary)}</div>
          <h1 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:26,fontWeight:700,color:t.text,marginBottom:5}}>Reset your password</h1>
          <p style={{color:t.textMuted,fontSize:13,lineHeight:1.6}}>Enter your registered email and we'll send you a secure reset link.</p>
        </div>
        <ProgressHeader/>
        <InputField label="Registered Email" type="email" placeholder="you@lawfirm.com" t={t} d={0} icon={Ic.mail(t.textFaint)}/>
        <div style={{display:"flex",gap:10,marginTop:14}}>
          <button className="aBtn" onClick={goBack} style={{flex:1,padding:"11px 0",borderRadius:t.r.md,background:"transparent",border:`1.5px solid ${t.border}`,color:t.textDim,fontSize:13,fontWeight:600,display:"flex",alignItems:"center",justifyContent:"center",gap:7,cursor:"pointer"}}>
            {Ic.arrowL(t.textDim)} Back
          </button>
          <button className="aBtn" onClick={()=>setSub(1)} style={{flex:2,padding:"11px 0",borderRadius:t.r.md,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:13,fontWeight:700,display:"flex",alignItems:"center",justifyContent:"center",gap:7,cursor:"pointer",boxShadow:`0 4px 16px ${t.primaryGlow}`}}>
            Send Reset Link {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
          </button>
        </div>
      </div>
    </AuthLayout>
  );

  if (sub === 1) return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{animation:"scaleUp .35s ease both"}}>
        <div style={{padding:"10px 14px",borderRadius:t.r.md,background:"rgba(60,201,154,.07)",border:`1px solid ${t.success}30`,marginBottom:18,display:"flex",alignItems:"flex-start",gap:10}}>
          <div style={{flexShrink:0,marginTop:1}}>{Ic.mail(t.success)}</div>
          <div>
            <p style={{fontSize:12,fontWeight:600,color:t.success,marginBottom:2}}>Reset link sent</p>
            <p style={{fontSize:12,color:t.textMuted,lineHeight:1.5}}>
              Code sent to <strong style={{color:t.text}}>your@email.com</strong>{" · "}
              <button onClick={()=>setResent(r=>!r)} style={{background:"none",border:"none",cursor:"pointer",color:resent?t.success:t.primary,fontSize:12,fontWeight:600,padding:0}}>{resent?"Resent ✓":"Resend"}</button>
            </p>
          </div>
        </div>
        <ProgressHeader/>
        <h2 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:24,fontWeight:700,color:t.text,marginBottom:4}}>Set new password</h2>
        <p style={{color:t.textMuted,fontSize:13,marginBottom:16}}>Choose a strong password for your account.</p>
        <div style={{display:"flex",flexDirection:"column",gap:12}}>
          <InputField label="New Password" type={spw?"text":"password"} placeholder="Min. 8 characters" t={t} d={.06}
            icon={Ic.lock(t.textFaint)} right={<button onClick={()=>setSPW(p=>!p)} style={{background:"none",border:"none",cursor:"pointer",padding:0,color:t.textFaint,display:"flex"}}>{spw?Ic.eyeOff(t.textFaint):Ic.eye(t.textFaint)}</button>}/>
          <InputField label="Confirm New Password" type={scf?"text":"password"} placeholder="Re-enter password" t={t} d={.11}
            icon={Ic.lock(t.textFaint)} right={<button onClick={()=>setSCF(p=>!p)} style={{background:"none",border:"none",cursor:"pointer",padding:0,color:t.textFaint,display:"flex"}}>{scf?Ic.eyeOff(t.textFaint):Ic.eye(t.textFaint)}</button>}/>
        </div>
        <div style={{display:"flex",gap:10,marginTop:14}}>
          <button className="aBtn" onClick={()=>setSub(0)} style={{flex:1,padding:"11px 0",borderRadius:t.r.md,background:"transparent",border:`1.5px solid ${t.border}`,color:t.textDim,fontSize:13,fontWeight:600,display:"flex",alignItems:"center",justifyContent:"center",gap:7,cursor:"pointer"}}>
            {Ic.arrowL(t.textDim)} Back
          </button>
          <button className="aBtn" onClick={()=>setSub(2)} style={{flex:2,padding:"11px 0",borderRadius:t.r.md,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:13,fontWeight:700,display:"flex",alignItems:"center",justifyContent:"center",gap:7,cursor:"pointer",boxShadow:`0 4px 16px ${t.primaryGlow}`}}>
            Set New Password {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
          </button>
        </div>
      </div>
    </AuthLayout>
  );

  return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{textAlign:"center",animation:"scaleUp .4s ease both",padding:"16px 0"}}>
        <div style={{position:"relative",width:76,height:76,margin:"0 auto 20px"}}>
          <div style={{position:"absolute",inset:-10,borderRadius:"50%",background:"rgba(60,201,154,.08)",animation:"pulse 2s infinite"}}/>
          <div style={{width:76,height:76,borderRadius:"50%",background:"rgba(60,201,154,.1)",border:`2.5px solid ${t.success}`,display:"flex",alignItems:"center",justifyContent:"center"}}>
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke={t.success} strokeWidth="2"><path d="M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9"/><path d="M9 12l2 2 8-8" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
        </div>
        <h2 style={{fontFamily:"'Cormorant Garamond',serif",fontSize:26,fontWeight:700,color:t.text,marginBottom:8}}>Password updated!</h2>
        <p style={{color:t.textMuted,fontSize:13,lineHeight:1.7,marginBottom:24}}>Your password has been successfully changed.<br/>You can now sign in with your new credentials.</p>
        <button className="aBtn" onClick={goBack} style={{width:"100%",padding:"12px 0",borderRadius:t.r.md,background:t.grad1,border:"none",color:t.mode==="dark"?"#182B32":"#fff",fontSize:13.5,fontWeight:700,display:"flex",alignItems:"center",justifyContent:"center",gap:7,cursor:"pointer",boxShadow:`0 4px 16px ${t.primaryGlow}`}}>
          Return to Sign In {Ic.arrowR(t.mode==="dark"?"#182B32":"#fff")}
        </button>
      </div>
    </AuthLayout>
  );
}

export default function ResetPasswordPage() {
  const router = useRouter();
  return <ForgotPw t={DARK} goBack={() => router.push('/login')} />;
}
