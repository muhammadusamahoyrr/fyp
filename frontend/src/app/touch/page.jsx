'use client';
import React, { useState } from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

const CONTACT_OPTIONS = [
  { emoji: '💬', title: 'Live Chat', desc: 'Chat with our team via WhatsApp for the fastest response.', link: 'https://wa.me/923709250258', linkLabel: 'Open WhatsApp' },
  { emoji: '📧', title: 'Email Support', desc: 'Send us a detailed message and we\'ll respond within 24 hours.', link: 'mailto:support@aiattorney.pk', linkLabel: 'Send Email' },
  { emoji: '❓', title: 'Help Center', desc: 'Browse our FAQ library for quick answers to common questions.', link: '/faqs', linkLabel: 'View FAQs' },
];

export default function TouchPage() {
  const [form, setForm] = useState({ name: '', email: '', subject: '', message: '' });
  const [sent, setSent] = useState(false);

  const handleChange = e => setForm(f => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = e => {
    e.preventDefault();
    setSent(true);
  };

  return (
    <PublicLayout activePage="touch">
      {/* Hero */}
      <section className="pt-32 pb-14 bg-gradient-to-b from-[#f4f9f8] to-white">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-5">
            Contact Us
          </span>
          <h1 className="text-4xl font-bold text-[#004743] sm:text-5xl">Get in Touch</h1>
          <p className="mt-4 text-lg text-gray-500 max-w-xl mx-auto">
            Have a question, feedback, or a sales enquiry? We'd love to hear from you.
          </p>
        </div>
      </section>

      {/* Contact options */}
      <section className="pb-14 bg-white">
        <div className="mx-auto max-w-5xl px-6 lg:px-8">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {CONTACT_OPTIONS.map((opt, i) => (
              <div key={i} className="bg-[#f4f9f8] rounded-2xl border border-[#E8F5E9] p-6 text-center hover:shadow-md transition-shadow">
                <span className="text-4xl block mb-3">{opt.emoji}</span>
                <h3 className="text-base font-bold text-[#004743] mb-2">{opt.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed mb-4">{opt.desc}</p>
                <a
                  href={opt.link}
                  target={opt.link.startsWith('http') ? '_blank' : undefined}
                  rel={opt.link.startsWith('http') ? 'noopener noreferrer' : undefined}
                  className="inline-block text-sm font-semibold text-[#025E56] border border-[#025E56] px-5 py-2 rounded-full hover:bg-[#004743] hover:text-white hover:border-[#004743] transition-all"
                >
                  {opt.linkLabel}
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Contact form */}
      <section className="py-16 bg-[#f4f9f8]">
        <div className="mx-auto max-w-2xl px-6">
          <div className="bg-white rounded-3xl border border-gray-200 shadow-md p-8 lg:p-10">
            {sent ? (
              <div className="text-center py-8">
                <div className="h-16 w-16 bg-[#E8F5E9] rounded-full flex items-center justify-center mx-auto mb-5">
                  <svg className="h-8 w-8 text-[#025E56]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <h2 className="text-2xl font-bold text-[#004743] mb-2">Message Sent!</h2>
                <p className="text-gray-500 text-base">Thanks for reaching out. We'll get back to you within 24 hours.</p>
                <button
                  onClick={() => { setSent(false); setForm({ name: '', email: '', subject: '', message: '' }); }}
                  className="mt-6 text-sm font-semibold text-[#025E56] hover:underline"
                >
                  Send another message
                </button>
              </div>
            ) : (
              <>
                <h2 className="text-2xl font-bold text-[#004743] mb-2">Send a Message</h2>
                <p className="text-gray-500 text-sm mb-8">Fill in the form and our team will respond within 24 hours.</p>
                <form onSubmit={handleSubmit} className="space-y-5">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                    <div>
                      <label className="block text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Your Name</label>
                      <input
                        name="name" value={form.name} onChange={handleChange} required
                        placeholder="Ahmad Khan"
                        className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-700 placeholder-gray-400 outline-none focus:border-[#025E56] focus:ring-2 focus:ring-[#025E56]/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Email Address</label>
                      <input
                        name="email" value={form.email} onChange={handleChange} required type="email"
                        placeholder="you@example.com"
                        className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-700 placeholder-gray-400 outline-none focus:border-[#025E56] focus:ring-2 focus:ring-[#025E56]/20 transition-all"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Subject</label>
                    <select
                      name="subject" value={form.subject} onChange={handleChange} required
                      className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-700 outline-none focus:border-[#025E56] focus:ring-2 focus:ring-[#025E56]/20 transition-all bg-white"
                    >
                      <option value="">Select a topic…</option>
                      <option>General Enquiry</option>
                      <option>Technical Support</option>
                      <option>Billing & Plans</option>
                      <option>Lawyer Onboarding</option>
                      <option>Partnership / Sales</option>
                      <option>Report a Bug</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-600 uppercase tracking-widest mb-2">Message</label>
                    <textarea
                      name="message" value={form.message} onChange={handleChange} required rows={5}
                      placeholder="Tell us how we can help…"
                      className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm text-gray-700 placeholder-gray-400 outline-none focus:border-[#025E56] focus:ring-2 focus:ring-[#025E56]/20 transition-all resize-none"
                    />
                  </div>
                  <button
                    type="submit"
                    className="w-full py-3.5 rounded-full bg-gradient-to-br from-[#004743] to-[#025E56] text-white text-sm font-bold shadow-lg hover:scale-105 transition-transform"
                  >
                    Send Message →
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      </section>

      {/* Office info */}
      <section className="py-14 bg-white">
        <div className="mx-auto max-w-5xl px-6 lg:px-8 text-center">
          <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">Our Base</p>
          <p className="text-base text-gray-600">COMSATS University Islamabad · Park Road, Islamabad, Pakistan</p>
          <p className="text-sm text-gray-400 mt-1">Response hours: Mon–Fri, 9 AM – 6 PM PKT</p>
        </div>
      </section>
    </PublicLayout>
  );
}
