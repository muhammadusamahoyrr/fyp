'use client';
import React from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

/* ── Mini UI previews — lightweight mockups hinting at the actual product ── */

function ResearchPreview() {
  return (
    <div className="mt-5 space-y-2.5">
      <div className="flex gap-2 items-start">
        <div className="w-6 h-6 rounded-full bg-white/20 flex-shrink-0 mt-0.5 flex items-center justify-center text-[10px] font-bold text-white">U</div>
        <div className="bg-white/10 rounded-xl px-3 py-2 text-xs text-white/80 leading-relaxed">What is Section 302 of the PPC?</div>
      </div>
      <div className="flex gap-2 items-start">
        <div className="w-6 h-6 rounded-full bg-[#E8F5E9] flex-shrink-0 mt-0.5 flex items-center justify-center text-[10px] font-bold text-[#025E56]">AI</div>
        <div className="bg-white rounded-xl px-3 py-2 text-xs text-gray-700 leading-relaxed flex-1">
          <span className="font-semibold text-[#025E56]">PPC § 302</span> — Qatl-i-amd (intentional murder). Punishable by death or life imprisonment under Pakistani law...
          <div className="mt-1.5 flex items-center gap-1 text-[10px] text-gray-400">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block"/>Cited · Pakistan Penal Code 1860
          </div>
        </div>
      </div>
    </div>
  );
}

function DocPreview() {
  const docs = [
    { name: 'Rental Agreement', status: 'Ready', color: 'text-green-600 bg-green-50' },
    { name: 'Legal Notice', status: 'Generating…', color: 'text-amber-600 bg-amber-50' },
    { name: 'Affidavit', status: 'Draft', color: 'text-gray-500 bg-gray-100' },
  ];
  return (
    <div className="mt-5 space-y-2">
      {docs.map((d, i) => (
        <div key={i} className="flex items-center gap-3 bg-white rounded-xl px-3 py-2.5 shadow-sm border border-gray-100">
          <div className="w-7 h-7 rounded-lg bg-[#f4f9f8] flex items-center justify-center flex-shrink-0">
            <svg className="w-3.5 h-3.5 text-[#025E56]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
          </div>
          <span className="flex-1 text-xs font-medium text-gray-700 truncate">{d.name}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${d.color}`}>{d.status}</span>
        </div>
      ))}
    </div>
  );
}

function LawyerPreview() {
  const lawyers = [
    { initials: 'AK', name: 'Ahmad Khan', spec: 'Criminal · Lahore', rating: '4.9', match: '98%' },
    { initials: 'SB', name: 'Sara Baig', spec: 'Family Law · Karachi', rating: '4.8', match: '94%' },
  ];
  return (
    <div className="mt-5 space-y-2.5">
      {lawyers.map((l, i) => (
        <div key={i} className="flex items-center gap-3 bg-white rounded-xl px-3 py-2.5 shadow-sm border border-gray-100">
          <div className="w-8 h-8 rounded-full bg-[#004743] text-white text-xs font-bold flex items-center justify-center flex-shrink-0">{l.initials}</div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-gray-800">{l.name}</p>
            <p className="text-[10px] text-gray-400">{l.spec}</p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-xs font-bold text-amber-500">★ {l.rating}</p>
            <p className="text-[10px] text-[#025E56] font-semibold">{l.match} match</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function TrackingPreview() {
  const steps = [
    { label: 'FIR Filed', date: '12 Jan', done: true },
    { label: 'Bail Hearing', date: '19 Jan', done: true },
    { label: 'Evidence Submission', date: '3 Feb', done: false },
    { label: 'Next Hearing', date: '14 Feb', done: false },
  ];
  return (
    <div className="mt-5 space-y-2">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className={`w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center ${s.done ? 'bg-[#025E56]' : 'bg-gray-200'}`}>
            {s.done && <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>}
          </div>
          <div className={`flex-1 h-px ${i < steps.length - 1 ? 'hidden' : 'hidden'}`}/>
          <span className={`text-xs flex-1 ${s.done ? 'text-gray-700 font-medium' : 'text-gray-400'}`}>{s.label}</span>
          <span className="text-[10px] text-gray-400">{s.date}</span>
        </div>
      ))}
    </div>
  );
}

function SignaturePreview() {
  return (
    <div className="mt-5">
      <div className="bg-white rounded-xl px-4 py-4 border border-dashed border-gray-300">
        <p className="text-[10px] text-gray-400 uppercase tracking-widest mb-3">Signature Area</p>
        <div className="relative h-12">
          <svg viewBox="0 0 200 50" className="w-full h-full">
            <path d="M10 35 C30 10, 50 45, 70 30 S110 10, 140 28 S170 40, 190 25" fill="none" stroke="#004743" strokeWidth="2.5" strokeLinecap="round" opacity="0.7"/>
          </svg>
        </div>
        <div className="flex justify-between mt-2">
          <div className="h-px w-2/3 bg-gray-200"/>
          <span className="text-[10px] text-[#025E56] font-semibold">✓ Signed</span>
        </div>
      </div>
      <div className="flex gap-2 mt-2.5">
        {['Canvas', 'Typed', 'Upload'].map((t, i) => (
          <button key={i} className={`text-[10px] px-3 py-1 rounded-full font-medium ${i === 0 ? 'bg-[#004743] text-white' : 'bg-gray-100 text-gray-500'}`}>{t}</button>
        ))}
      </div>
    </div>
  );
}

function MultilingualPreview() {
  return (
    <div className="mt-5 flex items-start gap-4">
      <div className="flex-1 space-y-2">
        <div className="bg-white/10 rounded-xl px-3 py-2 text-xs text-white/80">What is a writ petition?</div>
        <div className="bg-white rounded-xl px-3 py-2 text-xs text-gray-700">A writ petition is a formal request to a High Court...</div>
      </div>
      <div className="flex-1 space-y-2">
        <div className="bg-white/10 rounded-xl px-3 py-2 text-xs text-white/80 text-right" dir="rtl">رٹ پٹیشن کیا ہے؟</div>
        <div className="bg-white rounded-xl px-3 py-2 text-xs text-gray-700 text-right" dir="rtl">رٹ پٹیشن ہائی کورٹ کو ایک رسمی درخواست ہے...</div>
      </div>
    </div>
  );
}

export default function FeaturesPage() {
  return (
    <PublicLayout activePage="features">

      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="pt-32 pb-10 bg-white">
        <div className="mx-auto max-w-5xl px-6 flex flex-col lg:flex-row lg:items-end gap-6 lg:gap-16">
          <div className="lg:w-1/2">
            <p className="text-xs font-semibold text-[#025E56] uppercase tracking-widest mb-3">What's inside</p>
            <h1 className="text-3xl font-bold text-[#004743] sm:text-4xl leading-snug">
              Six tools. One platform.<br />Built for Pakistani law.
            </h1>
          </div>
          <div className="lg:w-1/2">
            <p className="text-gray-500 text-base leading-relaxed">
              From instant statute search to automated drafting and verified lawyer matching — everything a legal professional needs, without switching between apps.
            </p>
            <div className="mt-5 flex items-center gap-4">
              <a href="/login" className="text-sm font-semibold bg-[#004743] text-white px-6 py-2.5 rounded-full hover:bg-[#025E56] transition-colors">
                Try free →
              </a>
              <a href="/plans" className="text-sm font-semibold text-[#025E56] hover:underline">
                View pricing
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Bento grid ─────────────────────────────────────────── */}
      <section className="py-8 pb-20 bg-white">
        <div className="mx-auto max-w-5xl px-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 auto-rows-auto">

          {/* AI Research — large, spans 2 cols on desktop */}
          <div className="lg:col-span-2 bg-[#004743] rounded-3xl p-7 flex flex-col">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#a5d6a7] mb-1">AI Research</p>
                <h2 className="text-xl font-bold text-white leading-snug">Instant answers from<br />1,000+ Pakistani statutes</h2>
              </div>
              <span className="text-2xl">🤖</span>
            </div>
            <p className="text-sm text-white/60 mt-2 leading-relaxed">Search PPC, CrPC, Constitution and 6 court archives — cited, in seconds.</p>
            <ResearchPreview />
          </div>

          {/* Case Tracking */}
          <div className="bg-[#f4f9f8] rounded-3xl p-7 flex flex-col border border-[#E8F5E9]">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#025E56] mb-1">Case Tracking</p>
                <h2 className="text-lg font-bold text-[#004743] leading-snug">Your case, on a timeline</h2>
              </div>
              <span className="text-xl">📊</span>
            </div>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">Milestones, hearing dates, and deadlines — all in one view.</p>
            <TrackingPreview />
          </div>

          {/* Document Automation */}
          <div className="bg-[#f4f9f8] rounded-3xl p-7 flex flex-col border border-[#E8F5E9]">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#025E56] mb-1">Document Automation</p>
                <h2 className="text-lg font-bold text-[#004743] leading-snug">Drafts in minutes, not hours</h2>
              </div>
              <span className="text-xl">📄</span>
            </div>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">Contracts, petitions, affidavits — formatted to court standards automatically.</p>
            <DocPreview />
          </div>

          {/* Lawyer Matching */}
          <div className="bg-[#004743] rounded-3xl p-7 flex flex-col">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#a5d6a7] mb-1">Lawyer Matching</p>
                <h2 className="text-lg font-bold text-white leading-snug">The right lawyer, ranked by relevance</h2>
              </div>
              <span className="text-xl">👨‍⚖️</span>
            </div>
            <p className="text-xs text-white/60 mt-2 leading-relaxed">AI embedding match — not just keyword search. Filter by city, budget, specialty.</p>
            <LawyerPreview />
          </div>

          {/* E-Signature */}
          <div className="bg-white rounded-3xl p-7 flex flex-col border border-gray-200 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#025E56] mb-1">E-Signature</p>
                <h2 className="text-lg font-bold text-[#004743] leading-snug">Sign anywhere, legally</h2>
              </div>
              <span className="text-xl">✍️</span>
            </div>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">Canvas, typed, or image upload. Secure and instantly shareable as PDF.</p>
            <SignaturePreview />
          </div>

          {/* Multilingual — spans 2 cols */}
          <div className="md:col-span-2 lg:col-span-1 bg-[#025E56] rounded-3xl p-7 flex flex-col">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[#a5d6a7] mb-1">Multilingual</p>
                <h2 className="text-lg font-bold text-white leading-snug">English &amp; Urdu, natively</h2>
              </div>
              <span className="text-xl">🌐</span>
            </div>
            <p className="text-xs text-white/60 mt-2 leading-relaxed">Our multilingual model understands both languages equally — no translating needed.</p>
            <MultilingualPreview />
          </div>

        </div>
      </section>

      {/* ── How it works — compact ─────────────────────────────── */}
      <section className="py-14 border-t border-gray-100 bg-white">
        <div className="mx-auto max-w-5xl px-6">
          <p className="text-xs font-bold text-[#025E56] uppercase tracking-widest mb-8">How it works</p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
            {[
              { n: '01', title: 'Describe', body: 'Tell Attorney AI your legal issue in plain language — English or Urdu.' },
              { n: '02', title: 'Research', body: 'The AI searches statutes and precedents, returning cited answers instantly.' },
              { n: '03', title: 'Draft', body: 'Generate contracts, petitions, or affidavits with one click.' },
              { n: '04', title: 'Connect', body: 'Match with a verified Pakistani lawyer if you need representation.' },
            ].map((w, i) => (
              <div key={i}>
                <span className="text-3xl font-extrabold text-gray-100 leading-none block mb-3">{w.n}</span>
                <h3 className="text-sm font-bold text-[#004743] mb-1">{w.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{w.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ────────────────────────────────────────────────── */}
      <section className="py-14 bg-[#004743]">
        <div className="mx-auto max-w-5xl px-6 flex flex-col sm:flex-row items-center justify-between gap-6">
          <div>
            <h2 className="text-2xl font-bold text-white">Ready to try it yourself?</h2>
            <p className="text-[#a5d6a7] text-sm mt-1">Free to start — no credit card needed.</p>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <a href="/login" className="text-sm font-bold bg-white text-[#004743] px-7 py-3 rounded-full hover:bg-[#E8F5E9] transition-colors shadow-md">
              Get started free →
            </a>
            <a href="/plans" className="text-sm font-semibold text-white/70 hover:text-white transition-colors">
              Pricing
            </a>
          </div>
        </div>
      </section>

    </PublicLayout>
  );
}
