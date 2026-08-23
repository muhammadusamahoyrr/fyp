'use client';
import React from 'react';
import PublicLayout from './PublicLayout';

// Marketing art is decorative — if an asset is missing, collapse the image
// rather than leaving a broken-image icon in the hero.
const hideOnError = (e) => { e.currentTarget.style.display = 'none'; };

function HeroSection() {
  return (
    <section className="relative isolate pt-20 lg:pt-24">
      <div className="relative isolate overflow-hidden bg-gradient-to-b from-indigo-100/20">
        <div className="mx-auto max-w-7xl px-6 pb-12 pt-6 lg:pb-16 lg:pt-8 lg:px-16">
          <div className="mx-auto max-w-2xl lg:mx-0 lg:grid lg:max-w-none lg:grid-cols-2 lg:gap-x-16 lg:gap-y-6 lg:items-center">
            <div className="max-w-xl">
              <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-[#004743] sm:text-5xl lg:text-6xl mb-4">
                <span className="text-[#025E56]">Attorney AI</span>
                <span className="text-3xl md:text-4xl lg:text-5xl block mt-2">– Faster, Smarter Legal Assistance</span>
              </h1>
              <p className="text-lg font-medium text-gray-600 sm:text-xl/8 pb-2 md:pb-4">
                Get instant and professional legal drafting, unparalleled case insights, and powerful research tools — all tailored for Pakistani law. Trusted by top legal professionals, built for ultimate speed and accuracy.
              </p>
              <div className="mt-4 mb-2 flex items-center gap-4">
                <a className="inline-block py-3 px-8 text-sm font-semibold bg-gradient-to-br from-[#004743] to-[#025E56] text-white rounded-full shadow-lg hover:scale-105 transition-transform" href="/login">
                  Try For Free
                </a>
                <a className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#025E56] hover:underline" href="/features">
                  See Features
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </a>
              </div>
            </div>
            <div className="relative flex justify-center items-center h-full mt-8 lg:mt-0">
              <img alt="Attorney AI Hero" src="/hero.png" onError={hideOnError} className="w-auto md:w-full max-w-md lg:max-w-lg" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function AboutSection() {
  return (
    <div className="mx-auto max-w-7xl px-6 lg:flex lg:px-8 py-16">
      <div className="mx-auto flex max-w-2xl flex-col-reverse gap-x-12 gap-y-16 lg:mx-0 lg:min-w-full lg:max-w-none lg:flex-row lg:gap-x-12 lg:gap-y-0">
        <div className="w-auto flex-auto lg:ml-auto lg:w-1/2 lg:flex-none lg:self-center">
          <img alt="Attorney AI Illustration" src="/illustrate.png" onError={hideOnError} className="w-auto md:w-[35rem] h-auto px-0 md:px-12" />
        </div>
        <div className="lg:col-end-1 lg:w-1/2 lg:max-w-lg lg:pb-8 lg:self-center">
          <h2 className="text-4xl font-semibold tracking-tight text-[#025E56] sm:text-5xl">What is Attorney AI?</h2>
          <p className="mt-4 text-lg font-medium text-gray-600 sm:text-xl/8">
            Attorney AI isn't just a tool — it's a transformative legal intelligence platform designed to reshape how legal professionals work in Pakistan. Far beyond a simple chatbot, it's an integrated, AI-powered assistant that automates everyday legal workflows, accelerates drafting, and streamlines complex research.
            <br /><br />
            With real-time document generation, instant access to comprehensive Pakistani case law, and contextual legal insights, Attorney AI empowers lawyers, law firms, and individuals to operate with unprecedented speed, precision, and confidence.
          </p>
        </div>
      </div>
    </div>
  );
}

function AudienceSection() {
  const audiences = [
    { emoji: '👤', title: 'Individuals', description: 'Everyday individuals seeking legal solutions or quick insights for personal matters' },
    { emoji: '👨‍🎓', title: 'Law Students', description: 'Students aiming to bridge academic theory with practical legal application' },
    { emoji: '⚖️', title: 'Legal Professionals', description: 'Lawyers and paralegals seeking to streamline research and automate drafting' },
    { emoji: '🏢', title: 'Law Firms', description: 'Firms leveraging AI to enhance team efficiency and document automation' },
  ];

  return (
    <div className="bg-[#004743] py-10 px-4 lg:py-28 mt-10">
      <div className="mx-auto max-w-7xl">
        <div className="text-center">
          <h2 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl">Who is Attorney AI for?</h2>
          <p className="mt-4 text-lg text-gray-300">
            Our Mission: Legal Access. Simplified. For Everyone.<br />
            Attorney AI empowers all stakeholders in Pakistan's legal ecosystem.
          </p>
        </div>
        <div className="mx-auto mt-16 lg:mt-20 grid grid-cols-1 gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
          {audiences.map((item, idx) => (
            <div key={idx} className="bg-white rounded-2xl shadow-lg hover:shadow-2xl transition-all duration-300 hover:-translate-y-1">
              <div className="flex flex-col items-center justify-center py-8 px-8">
                <div className="h-16 w-16 bg-[#E8F5E9] rounded-2xl flex items-center justify-center text-3xl mb-4">
                  {item.emoji}
                </div>
                <p className="text-base font-semibold text-[#004743]">{item.title}</p>
                <p className="mt-3 text-base text-gray-600 text-center">{item.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function WhyChooseSection() {
  const features = [
    { emoji: '⚖️', title: 'Your Always-On Legal Partner, Built for Pakistan', description: 'Available 24/7 with unparalleled understanding of Pakistani law — precise, context-aware support for research, drafting, and litigation.' },
    { emoji: '💰', title: 'Smarter Legal Help, Without the High Fees', description: 'Skip traditional billable hours. Transparent pricing makes premium legal services accessible to individuals, students, and firms alike.' },
    { emoji: '⚡', title: 'Fast, Clear, Actionable Answers', description: 'From contract clauses to case summaries, Attorney AI explains the law in plain language instantly. No jargon, no delays.' },
    { emoji: '🔒', title: 'Privacy You Can Trust', description: 'Every interaction, document, and chat is secured with robust encryption. Your sensitive information remains protected at all times.' },
  ];

  return (
    <div className="mt-32 overflow-hidden sm:mt-40">
      <div className="mx-auto max-w-7xl px-6 lg:flex lg:px-8">
        <div className="mx-auto grid max-w-2xl grid-cols-1 gap-x-12 gap-y-16 lg:mx-0 lg:min-w-full lg:max-w-none lg:flex-none lg:gap-y-8">
          <div className="lg:col-end-1 lg:w-full lg:max-w-lg lg:pb-8">
            <div className="px-4 py-5">
              <h2 className="text-2xl font-semibold tracking-tight text-[#025E56] lg:text-4xl mb-6">Why choose Attorney AI?</h2>
              {features.map((f, idx) => (
                <div key={idx} className="relative mt-6 pl-16">
                  <div className="absolute left-0 top-0 flex h-12 w-12 items-center justify-center rounded-xl bg-[#E8F5E9] shadow-sm">
                    <span className="text-2xl">{f.emoji}</span>
                  </div>
                  <p className="text-base lg:text-lg font-semibold text-[#004743]">{f.title}</p>
                  <p className="mt-2 text-sm md:text-base text-gray-600">{f.description}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-center w-full">
            <img alt="Attorney AI Features" src="/feature.png" onError={hideOnError} className="w-auto md:w-[37rem] rounded-2xl object-cover shadow-xl" />
          </div>
        </div>
      </div>
    </div>
  );
}

function StatsSection() {
  const stats = [
    { emoji: '👤', label: 'Consumers', value: '17+' },
    { emoji: '👨‍🎓', label: 'Students', value: '75+' },
    { emoji: '⚖️', label: 'Legal Professionals', value: '11+' },
    { emoji: '🏢', label: 'Legal Firms', value: '1+' },
  ];

  return (
    <section className="py-20">
      <div className="mx-auto max-w-7xl px-6 lg:flex lg:items-center lg:justify-between">
        <div className="lg:w-2/3">
          <h2 className="text-4xl font-semibold text-[#004743]">
            Trusted by Professionals,<br />
            <span className="text-[#025E56]">Chosen by Pakistan.</span>
          </h2>
          <p className="mt-4 text-lg text-gray-500">
            From individuals and law students to leading legal professionals and rapidly growing firms, Attorney AI is the definitive platform for fast, secure, and intelligent legal solutions across Pakistan.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:w-1/2 mt-8 lg:mt-0">
          {stats.map((s, idx) => (
            <div key={idx} className="flex items-center space-x-4 bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
              <span className="text-4xl">{s.emoji}</span>
              <div>
                <p className="text-sm font-semibold text-gray-500">{s.label}</p>
                <p className="text-2xl font-bold text-[#025E56]">{s.value}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function TestimonialsSection() {
  const testimonials = [
    { name: 'Muzammil', role: 'Advocate', text: 'As a legal consultant, Attorney AI has been a game-changer, providing quick access to precedents and legal analytics that drive better decision-making.' },
    { name: 'Rafay', role: 'Advocate', text: 'The automated features of Attorney AI save us hours of work every week. It\'s reliable, fast, and exactly what our legal department needed to stay ahead.' },
    { name: 'Ayan', role: 'Advocate', text: 'Attorney AI is the future of legal technology. Its ability to adapt and learn our specific legal needs has made it an irreplaceable part of our firm.' },
    { name: 'Mehdi', role: 'Advocate', text: 'Document automation alone is worth every rupee. From contracts to petitions, it handles them all with incredible accuracy and speed.' },
  ];

  return (
    <section className="bg-[#004743] py-14">
      <div className="mx-auto max-w-7xl lg:max-w-full">
        <header className="text-center px-6">
          <span className="inline-block bg-white/10 text-white text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-4">What They Say</span>
          <h2 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl">Testimonials</h2>
          <p className="mt-2 text-lg text-gray-300">See what professionals and legal experts are saying about Attorney AI.</p>
        </header>
        <div className="relative overflow-hidden py-4 mt-8">
          <div className="absolute inset-0 pointer-events-none z-10" style={{ background: 'linear-gradient(to right,rgba(0,71,67,.9) 0%,rgba(0,71,67,.2) 10%,rgba(0,71,67,0) 50%,rgba(0,71,67,.2) 80%,rgba(0,71,67,.9) 100%)' }} />
          <div className="flex gap-4 overflow-x-auto px-6 pb-4 hide-scrollbar">
            {testimonials.map((t, idx) => (
              <div key={idx} className="flex-shrink-0 min-w-[300px] md:min-w-[360px] py-6 px-6 rounded-3xl bg-white shadow-xl">
                <div className="flex justify-between items-center mb-4">
                  <div className="flex text-[#004743]">
                    {[1,2,3,4,5].map(i => (
                      <svg key={i} stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className="h-4 w-4 mr-0.5" height="14" width="14" xmlns="http://www.w3.org/2000/svg">
                        <path d="M394 480a16 16 0 0 1-9.39-3L256 383.76 127.39 477a16 16 0 0 1-24.55-18.08L153 310.35 23 221.2a16 16 0 0 1 9-29.2h160.38l48.4-148.95a16 16 0 0 1 30.44 0l48.4 149H480a16 16 0 0 1 9.05 29.2L359 310.35l50.13 148.53A16 16 0 0 1 394 480z" />
                      </svg>
                    ))}
                  </div>
                  <span className="text-xs text-gray-400 font-medium">Verified Review</span>
                </div>
                <blockquote className="text-gray-700 text-sm leading-relaxed mb-4">"{t.text}"</blockquote>
                <div className="flex items-center gap-3 pt-3 border-t border-gray-100">
                  <div className="h-9 w-9 rounded-full bg-[#E8F5E9] flex items-center justify-center text-[#004743] font-bold text-sm">
                    {t.name[0]}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-800">{t.name}</p>
                    <span className="text-xs text-gray-500">{t.role}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function CTASection() {
  return (
    <section className="relative isolate overflow-hidden py-20 px-6 lg:px-8">
      <div className="absolute inset-0 -z-10">
        <div className="absolute top-1/4 left-1/4 h-64 w-64 rounded-full bg-gradient-to-br from-[#025E56] to-transparent opacity-20 blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 h-64 w-64 rounded-full bg-gradient-to-br from-[#004743] to-transparent opacity-20 blur-3xl" />
      </div>
      <div className="mx-auto max-w-7xl text-center">
        <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-6">Get Started</span>
        <h2 className="text-4xl font-bold text-[#004743] sm:text-5xl">Ready to Simplify Your Legal Journey?</h2>
        <p className="mt-4 text-lg text-gray-600 max-w-xl mx-auto">
          Join hundreds of Pakistanis who already use Attorney AI for faster, smarter legal assistance.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a href="/login" className="inline-flex items-center justify-center rounded-full bg-gradient-to-br from-[#004743] to-[#025E56] px-10 py-4 text-sm font-semibold text-white shadow-lg hover:scale-105 transition-transform">
            Start For Free →
          </a>
          <a href="/plans" className="inline-flex items-center justify-center rounded-full border-2 border-[#025E56] px-10 py-4 text-sm font-semibold text-[#025E56] hover:bg-[#E8F5E9] transition-colors">
            View Pricing
          </a>
        </div>
      </div>
    </section>
  );
}

export default function LandingPage() {
  return (
    <PublicLayout activePage="home">
      <HeroSection />
      <AboutSection />
      <AudienceSection />
      <WhyChooseSection />
      <StatsSection />
      <TestimonialsSection />
      <CTASection />
    </PublicLayout>
  );
}
