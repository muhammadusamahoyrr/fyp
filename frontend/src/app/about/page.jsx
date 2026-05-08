'use client';
import React from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

const team = [
  { name: 'Muhammad Usama', role: 'Founder & Lead Engineer', initials: 'MU', bg: 'bg-[#E8F5E9]', text: 'text-[#025E56]' },
  { name: 'Full-Stack Team', role: 'Frontend & Backend Engineers', initials: 'FS', bg: 'bg-[#f0f4ff]', text: 'text-indigo-600' },
  { name: 'AI Research', role: 'NLP & Legal AI Specialists', initials: 'AI', bg: 'bg-[#fff8e8]', text: 'text-amber-600' },
];

const milestones = [
  { year: '2023', label: 'Idea', desc: 'Conceived at COMSATS University — a final-year project to democratise legal access in Pakistan.' },
  { year: '2024', label: 'Build', desc: 'Designed the LangGraph RAG pipeline, ingested 1,000+ federal statutes, and built the core AI modules.' },
  { year: '2025', label: 'Launch', desc: 'Public beta launched. First verified lawyers onboarded. 100+ users across Pakistan in the first month.' },
  { year: '2026', label: 'Scale', desc: 'Expanding to provincial legislation, voice input (Urdu), and mobile apps for iOS and Android.' },
];

const values = [
  { emoji: '⚖️', title: 'Access to Justice', desc: 'Legal help shouldn\'t be a luxury. We believe every Pakistani — regardless of income — deserves access to clear, accurate legal information.' },
  { emoji: '🔒', title: 'Privacy First', desc: 'Your legal matters are private. We encrypt everything in transit and at rest, and we never sell your data.' },
  { emoji: '🇵🇰', title: 'Built for Pakistan', desc: 'We don\'t adapt foreign tools — we build natively for Pakistani law, language, and legal culture.' },
  { emoji: '🤝', title: 'Empowering Lawyers', desc: 'Attorney AI enhances legal professionals, not replaces them. We save hours on research and drafting so lawyers focus on people.' },
];

export default function AboutPage() {
  return (
    <PublicLayout activePage="about">
      {/* Hero */}
      <section className="pt-32 pb-16 bg-gradient-to-b from-[#f4f9f8] to-white">
        <div className="mx-auto max-w-4xl px-6 text-center">
          <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-5">
            Our Story
          </span>
          <h1 className="text-4xl font-bold text-[#004743] sm:text-5xl lg:text-6xl leading-tight">
            Democratising Legal Access<br />for Every Pakistani
          </h1>
          <p className="mt-6 text-lg text-gray-600 max-w-2xl mx-auto leading-relaxed">
            Attorney AI started as a university final-year project at COMSATS University Islamabad. Today it's a growing platform trusted by legal professionals, students, and individuals across Pakistan.
          </p>
        </div>
      </section>

      {/* Mission */}
      <section className="py-20 bg-white">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="flex flex-col lg:flex-row items-center gap-16">
            <div className="lg:w-1/2">
              <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-3 py-1 rounded-full mb-4">Our Mission</span>
              <h2 className="text-3xl font-bold text-[#004743] sm:text-4xl leading-snug mb-6">
                Legal intelligence, accessible to everyone.
              </h2>
              <p className="text-gray-600 text-base leading-relaxed mb-4">
                Pakistan has one of the most complex legal systems in the world — with centuries of British common law layered on top of Islamic jurisprudence, provincial acts, and rapidly evolving cyber law. For most Pakistanis, navigating this system requires expensive lawyers and hours of research.
              </p>
              <p className="text-gray-600 text-base leading-relaxed">
                We built Attorney AI to change that. By combining large language models, hybrid RAG search, and a comprehensive knowledge base of Pakistani federal law, we've created a platform that delivers the legal expertise of a seasoned lawyer — instantly, affordably, and in both English and Urdu.
              </p>
            </div>
            <div className="lg:w-1/2 grid grid-cols-2 gap-4">
              {[
                { value: '1,000+', label: 'Federal Statutes' },
                { value: '6', label: 'AI-Powered Modules' },
                { value: '100+', label: 'Users in Beta' },
                { value: '24/7', label: 'AI Availability' },
              ].map((s, i) => (
                <div key={i} className="bg-[#f4f9f8] rounded-2xl p-6 text-center border border-[#E8F5E9]">
                  <p className="text-3xl font-extrabold text-[#004743]">{s.value}</p>
                  <p className="text-sm text-gray-500 font-medium mt-1">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Values */}
      <section className="py-20 bg-[#004743]">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="text-center mb-14">
            <span className="inline-block bg-white/10 text-white text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-4">What We Stand For</span>
            <h2 className="text-3xl font-bold text-white sm:text-4xl">Our Core Values</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {values.map((v, i) => (
              <div key={i} className="bg-white/10 rounded-2xl p-6 border border-white/10 hover:bg-white/15 transition-colors">
                <span className="text-3xl block mb-4">{v.emoji}</span>
                <h3 className="text-white font-bold text-base mb-2">{v.title}</h3>
                <p className="text-gray-300 text-sm leading-relaxed">{v.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="py-20 bg-white">
        <div className="mx-auto max-w-4xl px-6 lg:px-8">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-[#004743] sm:text-4xl">Our Journey</h2>
          </div>
          <div className="relative">
            <div className="absolute left-1/2 -translate-x-px top-0 bottom-0 w-0.5 bg-[#E8F5E9] hidden md:block" />
            <div className="space-y-10">
              {milestones.map((m, i) => (
                <div key={i} className={`relative flex flex-col md:flex-row items-start md:items-center gap-6 ${i % 2 === 1 ? 'md:flex-row-reverse' : ''}`}>
                  <div className={`md:w-1/2 ${i % 2 === 1 ? 'md:text-right md:pl-8' : 'md:pr-8'}`}>
                    <span className="text-xs font-bold text-[#025E56] uppercase tracking-widest">{m.year}</span>
                    <h3 className="text-lg font-bold text-[#004743] mt-1 mb-2">{m.label}</h3>
                    <p className="text-gray-500 text-sm leading-relaxed">{m.desc}</p>
                  </div>
                  <div className="hidden md:flex absolute left-1/2 -translate-x-1/2 h-10 w-10 rounded-full bg-[#004743] border-4 border-[#E8F5E9] items-center justify-center">
                    <span className="text-white text-xs font-bold">{m.year.slice(2)}</span>
                  </div>
                  <div className="md:w-1/2" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Team */}
      <section className="py-20 bg-[#f4f9f8]">
        <div className="mx-auto max-w-5xl px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold text-[#004743] sm:text-4xl">Built by a Dedicated Team</h2>
            <p className="mt-3 text-gray-500 text-lg">SP23-BCS-069 · COMSATS University Islamabad</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {team.map((m, i) => (
              <div key={i} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-8 text-center hover:shadow-md transition-shadow">
                <div className={`h-16 w-16 rounded-full ${m.bg} flex items-center justify-center mx-auto mb-4`}>
                  <span className={`text-xl font-bold ${m.text}`}>{m.initials}</span>
                </div>
                <p className="text-base font-bold text-[#004743]">{m.name}</p>
                <p className="text-sm text-gray-500 mt-1">{m.role}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-[#004743] py-16 px-6 text-center">
        <h2 className="text-3xl font-bold text-white">Ready to experience Attorney AI?</h2>
        <p className="mt-3 text-gray-300 text-lg max-w-lg mx-auto">Join hundreds of Pakistanis already using the platform.</p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a href="/login" className="inline-flex items-center justify-center rounded-full bg-white text-[#004743] px-10 py-4 text-sm font-bold shadow-lg hover:scale-105 transition-transform">
            Try For Free →
          </a>
          <a href="/touch" className="inline-flex items-center justify-center rounded-full border-2 border-white/50 px-10 py-4 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
            Contact Us
          </a>
        </div>
      </section>
    </PublicLayout>
  );
}
