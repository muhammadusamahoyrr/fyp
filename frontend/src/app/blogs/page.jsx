'use client';
import React, { useState } from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

const BLOGS = [
  {
    image: '/image1.png',
    category: 'AI & Law',
    title: 'Will AI Replace Lawyers? Exploring the Future of Legal Practice',
    excerpt: 'Artificial intelligence is reshaping industries worldwide — but can it truly replace the nuanced judgment of a trained Pakistani lawyer?',
    readTime: '5 min read',
  },
  {
    image: '/image2.png',
    category: 'Criminal Law',
    title: 'Fighting Fake Cases with Attorney AI in Pakistan',
    excerpt: 'False FIRs and malicious litigation are a serious problem. Here\'s how AI-powered legal tools are helping Pakistanis fight back.',
    readTime: '4 min read',
  },
  {
    image: '/image3.png',
    category: 'Legal Ethics',
    title: 'Attorney AI and Attorney-Client Privilege: Navigating the Complexities',
    excerpt: 'How does confidentiality work when an AI platform is involved in your legal matters? We break down the legal framework under Pakistani law.',
    readTime: '6 min read',
  },
  {
    image: '/image4.png',
    category: 'Civil Law',
    title: 'Attorney AI for Car Accidents: Simplifying Legal Assistance',
    excerpt: 'Road accidents can be legally complex. Attorney AI helps victims understand their rights, file claims, and connect with the right lawyer instantly.',
    readTime: '4 min read',
  },
  {
    image: '/image5.png',
    category: 'Technology',
    title: 'How Attorneys Are Using AI to Revolutionize Legal Practice',
    excerpt: 'Pakistani law firms are beginning to adopt AI tools for research, drafting, and case analysis. Here\'s what early adopters are discovering.',
    readTime: '5 min read',
  },
  {
    image: '/image6.png',
    category: 'Privacy Law',
    title: 'AI and Privacy: Balancing Innovation with Protection',
    excerpt: 'As AI platforms handle sensitive legal data, the PDPA and PECA 2016 become critically important. Here\'s what Pakistani users need to know.',
    readTime: '5 min read',
  },
  {
    image: '/image7.png',
    category: 'Contract Law',
    title: 'Understanding an NDA: What It Is and Why It Matters',
    excerpt: 'Non-disclosure agreements are increasingly common in Pakistan\'s growing startup ecosystem. Learn what they cover, what they don\'t, and how to negotiate one.',
    readTime: '4 min read',
  },
  {
    image: '/image8.png',
    category: 'Constitutional Law',
    title: 'Understanding a Writ Petition: What It Is and How to File',
    excerpt: 'A writ petition is one of the most powerful tools a Pakistani citizen has against unlawful state action. Here\'s a step-by-step guide.',
    readTime: '6 min read',
  },
  {
    image: '/image9.png',
    category: 'Productivity',
    title: 'How AI Can Help You Save Time in Your Legal Practice',
    excerpt: 'From automating routine documents to summarising lengthy case files, discover how AI tools give Pakistani lawyers hours back in their week.',
    readTime: '4 min read',
  },
];

const CATEGORIES = ['All', ...Array.from(new Set(BLOGS.map(b => b.category)))];

export default function BlogsPage() {
  const [activeCategory, setActiveCategory] = useState('All');

  const filtered = activeCategory === 'All' ? BLOGS : BLOGS.filter(b => b.category === activeCategory);

  return (
    <PublicLayout activePage="blogs">
      {/* Page hero — matches bloc1guide.png design */}
      <section className="pt-32 pb-10 bg-white">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <h1 className="text-4xl font-bold text-[#004743] sm:text-5xl">Blogs</h1>
          <p className="mt-3 text-lg text-gray-500">
            Latest LegalTech updates and insights from Attorney AI's expert team.
          </p>
        </div>
      </section>

      {/* Category filter */}
      <section className="pb-6 bg-white">
        <div className="mx-auto max-w-7xl px-6 flex gap-2 flex-wrap justify-center">
          {CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`px-5 py-2 rounded-full text-sm font-semibold transition-all ${
                activeCategory === cat
                  ? 'bg-[#004743] text-white shadow-md'
                  : 'bg-gray-100 text-gray-600 hover:bg-[#E8F5E9] hover:text-[#025E56]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </section>

      {/* Blog grid — matches bloc1guide + bloc2guide 3-column layout */}
      <section className="py-6 pb-20 bg-white">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
            {filtered.map((blog, idx) => (
              <article
                key={idx}
                className="group rounded-2xl overflow-hidden bg-white border border-gray-100 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 cursor-pointer"
              >
                {/* Blog image */}
                <div className="overflow-hidden h-52">
                  <img
                    src={blog.image}
                    alt={blog.title}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                  />
                </div>

                {/* Blog content */}
                <div className="p-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-wide px-3 py-1 rounded-full">
                      {blog.category}
                    </span>
                    <span className="text-xs text-gray-400">{blog.readTime}</span>
                  </div>
                  <h3 className="text-base font-bold text-gray-900 group-hover:text-[#025E56] transition-colors leading-snug mb-2">
                    {blog.title}
                  </h3>
                  <p className="text-sm text-gray-500 leading-relaxed line-clamp-2">{blog.excerpt}</p>
                  <div className="mt-4 flex items-center gap-1 text-sm text-[#025E56] font-semibold group-hover:gap-2 transition-all">
                    Read
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {filtered.length === 0 && (
            <div className="text-center py-20">
              <p className="text-4xl mb-3">📰</p>
              <p className="text-gray-500 font-medium">No blogs in this category yet.</p>
            </div>
          )}
        </div>
      </section>

      {/* CTA */}
      <section className="bg-[#004743] py-16 px-6 text-center">
        <h2 className="text-3xl font-bold text-white">Want expert legal help right now?</h2>
        <p className="mt-3 text-gray-300 text-lg max-w-lg mx-auto">Stop reading about it — experience Attorney AI for yourself.</p>
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
