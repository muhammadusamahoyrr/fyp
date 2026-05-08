'use client';
import React, { useState } from 'react';
import PublicLayout from '@/components/shared/PublicLayout';

const PLANS = [
  {
    name: 'Free',
    price: { monthly: 0, annual: 0 },
    badge: null,
    desc: 'For individuals who need occasional legal guidance.',
    cta: 'Get Started Free',
    ctaHref: '/register',
    highlight: false,
    features: [
      '5 AI chat queries per month',
      'Basic document preview',
      'Access to Pakistani statute library',
      'Legal information (not advice)',
      'English & Urdu support',
    ],
    missing: ['Document generation & PDF export', 'Lawyer matching', 'E-signature', 'Case tracking', 'Priority support'],
  },
  {
    name: 'Professional',
    price: { monthly: 1999, annual: 1499 },
    badge: 'Most Popular',
    desc: 'For practising lawyers, paralegals, and serious legal researchers.',
    cta: 'Start Free Trial',
    ctaHref: '/register',
    highlight: true,
    features: [
      'Unlimited AI chat queries',
      'Full document generation & PDF export',
      'AI lawyer matching engine',
      'Canvas & typed e-signature',
      'Case tracking with milestones',
      'All Free features included',
      'Priority email support',
    ],
    missing: ['White-label branding', 'Team collaboration (multi-seat)', 'API access'],
  },
  {
    name: 'Firm',
    price: { monthly: 7999, annual: 5999 },
    badge: 'For Teams',
    desc: 'For law firms and organisations needing multi-user access.',
    cta: 'Contact Sales',
    ctaHref: '/touch',
    highlight: false,
    features: [
      'Everything in Professional',
      'Up to 10 team seats',
      'Team case management',
      'Shared document workspace',
      'Bulk document generation',
      'Custom intake templates',
      'Dedicated account manager',
      'API access',
    ],
    missing: [],
  },
];

const FAQ_PRICING = [
  { q: 'Can I switch plans at any time?', a: 'Yes. You can upgrade or downgrade your plan at any time from your account settings. Changes take effect at the start of your next billing cycle.' },
  { q: 'Is there a free trial for paid plans?', a: 'Yes — Professional includes a 7-day free trial. No credit card required to start.' },
  { q: 'What payment methods do you accept?', a: 'We accept all major credit and debit cards, JazzCash, Easypaisa, and bank transfers for Firm plans.' },
  { q: 'Can I get a refund?', a: 'We offer a 7-day money-back guarantee on all paid plans. See our Refund Policy for details.' },
];

export default function PlansPage() {
  const [annual, setAnnual] = useState(false);
  const [openFaq, setOpenFaq] = useState(null);

  return (
    <PublicLayout activePage="plans">
      {/* Hero */}
      <section className="pt-32 pb-14 bg-gradient-to-b from-[#f4f9f8] to-white">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <span className="inline-block bg-[#E8F5E9] text-[#025E56] text-xs font-bold uppercase tracking-widest px-4 py-1.5 rounded-full mb-5">
            Pricing
          </span>
          <h1 className="text-4xl font-bold text-[#004743] sm:text-5xl">Simple, Transparent Pricing</h1>
          <p className="mt-4 text-lg text-gray-500 max-w-xl mx-auto">
            Start free, pay only when you need more. No hidden fees.
          </p>

          {/* Billing toggle */}
          <div className="mt-8 inline-flex items-center gap-3 bg-gray-100 rounded-full px-2 py-1.5">
            <button
              onClick={() => setAnnual(false)}
              className={`px-5 py-2 rounded-full text-sm font-semibold transition-all ${!annual ? 'bg-white text-[#004743] shadow-sm' : 'text-gray-500'}`}
            >
              Monthly
            </button>
            <button
              onClick={() => setAnnual(true)}
              className={`px-5 py-2 rounded-full text-sm font-semibold transition-all ${annual ? 'bg-white text-[#004743] shadow-sm' : 'text-gray-500'}`}
            >
              Annual
              <span className="ml-1.5 text-xs text-[#025E56] font-bold">-25%</span>
            </button>
          </div>
        </div>
      </section>

      {/* Plans grid */}
      <section className="pb-20 bg-white">
        <div className="mx-auto max-w-6xl px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 items-start">
            {PLANS.map((plan, i) => (
              <div
                key={i}
                className={`relative rounded-3xl border p-8 flex flex-col transition-all duration-300 ${
                  plan.highlight
                    ? 'border-[#004743] shadow-2xl shadow-[#004743]/10 bg-[#004743] text-white scale-105'
                    : 'border-gray-200 bg-white hover:shadow-lg'
                }`}
              >
                {plan.badge && (
                  <span className={`absolute -top-3 left-1/2 -translate-x-1/2 text-xs font-bold uppercase tracking-widest px-4 py-1 rounded-full ${
                    plan.highlight ? 'bg-[#E8F5E9] text-[#025E56]' : 'bg-[#004743] text-white'
                  }`}>
                    {plan.badge}
                  </span>
                )}

                <div className="mb-6">
                  <p className={`text-sm font-bold uppercase tracking-widest mb-2 ${plan.highlight ? 'text-[#a5d6a7]' : 'text-[#025E56]'}`}>{plan.name}</p>
                  <div className="flex items-end gap-1.5 mb-3">
                    {plan.price.monthly === 0 ? (
                      <span className={`text-4xl font-extrabold ${plan.highlight ? 'text-white' : 'text-[#004743]'}`}>Free</span>
                    ) : (
                      <>
                        <span className={`text-4xl font-extrabold ${plan.highlight ? 'text-white' : 'text-[#004743]'}`}>
                          ₨{(annual ? plan.price.annual : plan.price.monthly).toLocaleString()}
                        </span>
                        <span className={`text-sm mb-1.5 ${plan.highlight ? 'text-[#a5d6a7]' : 'text-gray-400'}`}>/mo</span>
                      </>
                    )}
                  </div>
                  <p className={`text-sm leading-snug ${plan.highlight ? 'text-[#a5d6a7]' : 'text-gray-500'}`}>{plan.desc}</p>
                </div>

                <a
                  href={plan.ctaHref}
                  className={`block w-full text-center py-3 rounded-full text-sm font-bold mb-8 transition-all hover:scale-105 ${
                    plan.highlight
                      ? 'bg-white text-[#004743] shadow-md'
                      : 'bg-gradient-to-br from-[#004743] to-[#025E56] text-white shadow-lg'
                  }`}
                >
                  {plan.cta}
                </a>

                <ul className="space-y-3 flex-1">
                  {plan.features.map((f, fi) => (
                    <li key={fi} className="flex items-start gap-2.5">
                      <svg className={`h-4 w-4 flex-shrink-0 mt-0.5 ${plan.highlight ? 'text-[#a5d6a7]' : 'text-[#025E56]'}`} fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                      <span className={`text-sm ${plan.highlight ? 'text-gray-100' : 'text-gray-700'}`}>{f}</span>
                    </li>
                  ))}
                  {plan.missing.map((f, fi) => (
                    <li key={`m${fi}`} className="flex items-start gap-2.5 opacity-40">
                      <svg className="h-4 w-4 flex-shrink-0 mt-0.5 text-gray-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                      <span className={`text-sm ${plan.highlight ? 'text-gray-300' : 'text-gray-400'}`}>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing FAQ */}
      <section className="py-20 bg-[#f4f9f8]">
        <div className="mx-auto max-w-3xl px-6">
          <h2 className="text-2xl font-bold text-[#004743] text-center mb-10">Pricing FAQs</h2>
          <div className="space-y-3">
            {FAQ_PRICING.map((faq, i) => {
              const isOpen = openFaq === i;
              return (
                <div key={i} className={`rounded-2xl border bg-white overflow-hidden transition-all ${isOpen ? 'border-[#025E56]/30 shadow-sm' : 'border-gray-200'}`}>
                  <button onClick={() => setOpenFaq(isOpen ? null : i)} className="w-full flex items-center justify-between px-6 py-4 text-left gap-4">
                    <span className={`font-semibold text-sm ${isOpen ? 'text-[#025E56]' : 'text-gray-800'}`}>{faq.q}</span>
                    <span className={`flex-shrink-0 h-7 w-7 rounded-full border-2 flex items-center justify-center transition-all ${isOpen ? 'border-[#025E56] bg-[#025E56] text-white rotate-180' : 'border-gray-300 text-gray-400'}`}>
                      <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    </span>
                  </button>
                  {isOpen && (
                    <div className="px-6 pb-5">
                      <p className="text-gray-500 text-sm leading-relaxed border-t border-gray-100 pt-3">{faq.a}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-[#004743] py-16 px-6 text-center">
        <h2 className="text-3xl font-bold text-white">Start free today — no credit card needed.</h2>
        <p className="mt-3 text-gray-300 text-lg max-w-lg mx-auto">Upgrade whenever you're ready.</p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a href="/register" className="inline-flex items-center justify-center rounded-full bg-white text-[#004743] px-10 py-4 text-sm font-bold shadow-lg hover:scale-105 transition-transform">
            Create Free Account →
          </a>
          <a href="/touch" className="inline-flex items-center justify-center rounded-full border-2 border-white/50 px-10 py-4 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
            Talk to Sales
          </a>
        </div>
      </section>
    </PublicLayout>
  );
}
