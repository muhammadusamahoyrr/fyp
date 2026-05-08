'use client';
import React, { useState, useMemo } from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

const ALL_FAQS = [
  {
    category: 'General',
    question: 'What is Attorney AI, and who can use it?',
    answer: 'Attorney AI is an AI-powered legal assistance platform built specifically for Pakistan. It can be used by individuals seeking legal guidance, law students doing research, practising lawyers and paralegals, and law firms wanting to automate their workflows. Anyone who needs reliable access to Pakistani legal information can benefit from Attorney AI.',
  },
  {
    category: 'General',
    question: 'What is Attorney AI Legal Assistant?',
    answer: 'Attorney AI Legal Assistant is the core conversational AI module of the platform. It uses a hybrid Retrieval-Augmented Generation (RAG) pipeline trained on Pakistani statutes, case law, and constitutional texts to answer legal queries in plain English or Urdu, with cited references.',
  },
  {
    category: 'General',
    question: 'Is Attorney AI available 24/7?',
    answer: "Yes. The AI Legal Assistant, document automation, and case tracking features are available around the clock. Lawyer availability depends on the individual lawyer's schedule, but you can always submit consultation requests at any time.",
  },
  {
    category: 'Legal Coverage',
    question: 'What areas of Pakistani law does Attorney AI cover?',
    answer: 'Attorney AI covers federal Pakistani law including Constitutional Law (1973 Constitution), Criminal Law (PPC 1860, CrPC 1898), Civil Law (CPC 1908), Family Law, Contract Law, Property Law, Cyber Law (PECA 2016), ETO 2002, PDPA, and over 1,000 additional federal statutes. Provincial legislation will be added in a future version.',
  },
  {
    category: 'Legal Coverage',
    question: 'Is the legal information provided by Attorney AI accurate?',
    answer: 'Attorney AI is trained on verified Pakistani legal sources. While we strive for accuracy, all information is for educational purposes only and does not constitute formal legal advice. The platform always includes an "informational only" disclaimer. For complex matters or court proceedings, consult a qualified Pakistani lawyer.',
  },
  {
    category: 'Legal Coverage',
    question: 'Can Attorney AI replace a real lawyer?',
    answer: 'No. Attorney AI is designed to complement legal professionals, not replace them. It accelerates research, automates document drafting, and provides legal information — but for court representation, case-specific strategy, or formal legal advice, you must consult a qualified Pakistani lawyer.',
  },
  {
    category: 'Features',
    question: 'How does document automation work?',
    answer: 'Fill in a structured intake form describing your legal need (e.g., "rental agreement", "legal notice", "affidavit"). Attorney AI generates a professionally formatted, Pakistan-law-compliant draft document that you can review, edit, e-sign, and download as a PDF.',
  },
  {
    category: 'Features',
    question: 'How does lawyer matching work?',
    answer: 'After completing the legal intake form, our AI embedding model analyses your case description and matches it against verified lawyer profiles using semantic similarity. You receive a shortlist ranked by relevance, location, and rating. You can then book a consultation directly through the platform.',
  },
  {
    category: 'Features',
    question: 'Can I use Attorney AI in Urdu?',
    answer: 'Yes. Attorney AI supports both English and Urdu queries. Our multilingual embedding model (paraphrase-multilingual-MiniLM-L12-v2) is trained on Urdu legal texts, ensuring every Pakistani citizen can access legal help in their preferred language.',
  },
  {
    category: 'Privacy & Security',
    question: 'How secure is my data on Attorney AI?',
    answer: 'All communications, documents, and case data are encrypted in transit and at rest. We follow strict data privacy protocols. Your information is never sold or shared with third parties. Lawyer-client communications on the platform are kept strictly confidential.',
  },
  {
    category: 'Pricing',
    question: 'Is Attorney AI free to use?',
    answer: 'Attorney AI offers a freemium model. Basic features — including limited AI chat queries and document previews — are free. Premium plans unlock unlimited AI chat, advanced document generation, priority lawyer matching, case tracking, and e-signature. Visit our Pricing page for full details.',
  },
  {
    category: 'Pricing',
    question: 'Do I need a credit card to sign up?',
    answer: 'No. You can sign up and access the free tier without any payment information. A credit card is only required when upgrading to a paid plan.',
  },
];

const CATEGORY_ICONS = {
  General: '💬',
  'Legal Coverage': '⚖️',
  Features: '✨',
  'Privacy & Security': '🔒',
  Pricing: '💳',
};

const CATEGORIES = ['All', ...Array.from(new Set(ALL_FAQS.map(f => f.category)))];

export default function FAQsPage() {
  const [search, setSearch] = useState('');
  const [openIdx, setOpenIdx] = useState(null);
  const [activeCategory, setActiveCategory] = useState('All');

  const catCounts = useMemo(() => {
    const counts = {};
    ALL_FAQS.forEach(f => { counts[f.category] = (counts[f.category] || 0) + 1; });
    return counts;
  }, []);

  const filtered = useMemo(() => {
    return ALL_FAQS.filter(f => {
      const matchesCategory = activeCategory === 'All' || f.category === activeCategory;
      const q = search.toLowerCase();
      const matchesSearch = !q || f.question.toLowerCase().includes(q) || f.answer.toLowerCase().includes(q);
      return matchesCategory && matchesSearch;
    });
  }, [search, activeCategory]);

  const handleCategory = (cat) => {
    setActiveCategory(cat);
    setOpenIdx(null);
  };

  return (
    <PublicLayout activePage="faqs">
      {/* Hero */}
      <section className="pt-32 pb-14 bg-gradient-to-b from-[#f4f9f8] to-white">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-5">
            Help Center
          </span>
          <h1 className="text-4xl font-bold text-[#004743] sm:text-5xl">Frequently Asked Questions</h1>
          <p className="mt-4 text-lg text-gray-500">
            Everything you need to know about Attorney AI. Can't find your answer?{' '}
            <a href="/touch" className="text-[#025E56] font-semibold hover:underline">Contact support.</a>
          </p>
        </div>
      </section>

      {/* Main content — sidebar + accordion */}
      <section className="bg-white pb-24">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <div className="flex flex-col lg:flex-row gap-8 items-start">

            {/* ── Sidebar ── */}
            <aside className="w-full lg:w-72 flex-shrink-0">
              <div className="lg:sticky lg:top-24 space-y-4">

                {/* Search */}
                <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3">Search</p>
                  <div className="flex items-center gap-2 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:ring-2 focus-within:ring-[#025E56]/30 focus-within:border-[#025E56] transition-all bg-gray-50">
                    <svg className="h-4 w-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search questions..."
                      value={search}
                      onChange={e => { setSearch(e.target.value); setOpenIdx(null); }}
                      className="flex-1 text-sm text-gray-700 placeholder-gray-400 outline-none bg-transparent"
                    />
                    {search && (
                      <button onClick={() => setSearch('')} className="text-gray-400 hover:text-gray-600 leading-none text-lg">×</button>
                    )}
                  </div>
                </div>

                {/* Categories */}
                <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3">Browse by Topic</p>
                  <ul className="space-y-1">
                    {CATEGORIES.map(cat => {
                      const isActive = activeCategory === cat;
                      const count = cat === 'All' ? ALL_FAQS.length : catCounts[cat] || 0;
                      return (
                        <li key={cat}>
                          <button
                            onClick={() => handleCategory(cat)}
                            className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
                              isActive
                                ? 'bg-[#004743] text-white shadow-sm'
                                : 'text-gray-600 hover:bg-[#E8F5E9] hover:text-[#025E56]'
                            }`}
                          >
                            <span className="flex items-center gap-2">
                              {cat !== 'All' && <span>{CATEGORY_ICONS[cat]}</span>}
                              {cat}
                            </span>
                            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                              isActive ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
                            }`}>
                              {count}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>

                {/* Contact card */}
                <div className="bg-[#004743] rounded-2xl p-5 text-white">
                  <div className="text-2xl mb-2">🤝</div>
                  <p className="font-bold text-base">Still have questions?</p>
                  <p className="text-sm text-[#a5d6a7] mt-1 leading-snug">Our support team is happy to help you out.</p>
                  <a
                    href="/touch"
                    className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold bg-white text-[#004743] px-4 py-2 rounded-full hover:bg-[#E8F5E9] transition-colors"
                  >
                    Contact Us →
                  </a>
                </div>

              </div>
            </aside>

            {/* ── FAQ accordion ── */}
            <main className="flex-1 min-w-0">
              {/* Results count */}
              <div className="mb-5 flex items-center justify-between">
                <p className="text-sm text-gray-500">
                  {filtered.length === 0
                    ? 'No results found'
                    : `Showing ${filtered.length} question${filtered.length !== 1 ? 's' : ''}${activeCategory !== 'All' ? ` in "${activeCategory}"` : ''}`
                  }
                </p>
                {(search || activeCategory !== 'All') && (
                  <button
                    onClick={() => { setSearch(''); setActiveCategory('All'); setOpenIdx(null); }}
                    className="text-xs text-[#025E56] font-semibold hover:underline"
                  >
                    Clear filters
                  </button>
                )}
              </div>

              {filtered.length === 0 ? (
                <div className="text-center py-20 bg-gray-50 rounded-2xl border border-gray-100">
                  <p className="text-4xl mb-3">🔍</p>
                  <p className="text-gray-700 font-semibold">No results for "{search}"</p>
                  <p className="text-gray-400 text-sm mt-1">Try different keywords or browse all categories.</p>
                  <button
                    onClick={() => { setSearch(''); setActiveCategory('All'); }}
                    className="mt-5 inline-block bg-[#004743] text-white text-sm font-semibold px-5 py-2.5 rounded-full hover:opacity-90 transition-opacity"
                  >
                    View All FAQs
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  {filtered.map((faq, idx) => {
                    const isOpen = openIdx === idx;
                    return (
                      <div
                        key={idx}
                        className={`rounded-2xl border transition-all duration-200 overflow-hidden ${
                          isOpen
                            ? 'border-[#025E56]/30 shadow-md bg-white'
                            : 'border-gray-200 bg-white hover:border-[#025E56]/20 hover:shadow-sm'
                        }`}
                      >
                        <button
                          onClick={() => setOpenIdx(isOpen ? null : idx)}
                          className="w-full flex items-center justify-between px-6 py-5 text-left gap-4"
                        >
                          <div className="flex items-start gap-3">
                            <span className="flex-shrink-0 mt-0.5 text-lg">{CATEGORY_ICONS[faq.category]}</span>
                            <span className={`font-semibold text-sm md:text-base leading-snug ${isOpen ? 'text-[#025E56]' : 'text-gray-800'}`}>
                              {faq.question}
                            </span>
                          </div>
                          <span className={`flex-shrink-0 h-8 w-8 rounded-full border-2 flex items-center justify-center transition-all duration-200 ${
                            isOpen ? 'border-[#025E56] bg-[#025E56] text-white rotate-180' : 'border-gray-300 text-gray-400'
                          }`}>
                            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                            </svg>
                          </span>
                        </button>
                        {isOpen && (
                          <div className="px-6 pb-6">
                            <div className="border-t border-gray-100 pt-4 ml-9">
                              <p className="text-gray-600 text-sm md:text-base leading-relaxed">{faq.answer}</p>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </main>

          </div>
        </div>
      </section>

      {/* CTA strip */}
      <section className="bg-[#004743] py-16 px-6 text-center">
        <h2 className="text-3xl font-bold text-white">Need personalised legal help?</h2>
        <p className="mt-3 text-gray-300 text-lg max-w-lg mx-auto">Stop reading — experience Attorney AI for yourself.</p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a href="/login" className="inline-flex items-center justify-center rounded-full bg-white text-[#004743] px-10 py-4 text-sm font-bold shadow-lg hover:scale-105 transition-transform">
            Try Attorney AI Free →
          </a>
          <a href="/features" className="inline-flex items-center justify-center rounded-full border-2 border-white/50 px-10 py-4 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
            Explore Features
          </a>
        </div>
      </section>
    </PublicLayout>
  );
}
