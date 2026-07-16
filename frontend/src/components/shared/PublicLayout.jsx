'use client';
import React, { useState } from 'react';

export const Icons = {
  menu: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className={cls}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
    </svg>
  ),
  chevronDown: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" className={cls} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
    </svg>
  ),
  star: (cls) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className={cls} height="14" width="14" xmlns="http://www.w3.org/2000/svg">
      <path d="M394 480a16 16 0 0 1-9.39-3L256 383.76 127.39 477a16 16 0 0 1-24.55-18.08L153 310.35 23 221.2a16 16 0 0 1 9-29.2h160.38l48.4-148.95a16 16 0 0 1 30.44 0l48.4 149H480a16 16 0 0 1 9.05 29.2L359 310.35l50.13 148.53A16 16 0 0 1 394 480z" />
    </svg>
  ),
  search: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className={cls}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
    </svg>
  ),
  plus: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" className={cls}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
    </svg>
  ),
  minus: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor" className={cls}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12h-15" />
    </svg>
  ),
  facebook: (cls) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className={cls} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M504 256C504 119 393 8 256 8S8 119 8 256c0 123.78 90.69 226.38 209.25 245V327.69h-63V256h63v-54.64c0-62.15 37-96.48 93.67-96.48 27.14 0 55.52 4.84 55.52 4.84v61h-31.28c-30.8 0-40.41 19.12-40.41 38.73V256h68.78l-11 71.69h-57.78V501C413.31 482.38 504 379.78 504 256z" />
    </svg>
  ),
  instagram: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 24 24" className={cls}>
      <path fillRule="evenodd" d="M12.315 2c2.43 0 2.784.013 3.808.06 1.064.049 1.791.218 2.427.465a4.902 4.902 0 011.772 1.153 4.902 4.902 0 011.153 1.772c.247.636.416 1.363.465 2.427.048 1.067.06 1.407.06 4.123v.08c0 2.643-.012 2.987-.06 4.043-.049 1.064-.218 1.791-.465 2.427a4.902 4.902 0 01-1.153 1.772 4.902 4.902 0 01-1.772 1.153c-.636.247-1.363.416-2.427.465-1.067.048-1.407.06-4.123.06h-.08c-2.643 0-2.987-.012-4.043-.06-1.064-.049-1.791-.218-2.427-.465a4.902 4.902 0 01-1.772-1.153 4.902 4.902 0 01-1.153-1.772c-.247-.636-.416-1.363-.465-2.427-.047-1.024-.06-1.379-.06-3.808v-.63c0-2.43.013-2.784.06-3.808.049-1.064.218-1.791.465-2.427a4.902 4.902 0 011.153-1.772A4.902 4.902 0 015.45 2.525c.636-.247 1.363-.416 2.427-.465C8.901 2.013 9.256 2 11.685 2h.63zm-.081 1.802h-.468c-2.456 0-2.784.011-3.807.058-.975.045-1.504.207-1.857.344-.467.182-.8.398-1.15.748-.35.35-.566.683-.748 1.15-.137.353-.3.882-.344 1.857-.047 1.023-.058 1.351-.058 3.807v.468c0 2.456.011 2.784.058 3.807.045.975.207 1.504.344 1.857.182.466.399.8.748 1.15.35.35.683.566 1.15.748.353.137.882.3 1.857.344 1.054.048 1.37.058 4.041.058h.08c2.597 0 2.917-.01 3.96-.058.976-.045 1.505-.207 1.858-.344.466-.182.8-.398 1.15-.748.35-.35.566-.683.748-1.15.137-.353.3-.882.344-1.857.048-1.055.058-1.37.058-4.041v-.08c0-2.597-.01-2.917-.058-3.96-.045-.976-.207-1.505-.344-1.858a3.097 3.097 0 00-.748-1.15 3.098 3.098 0 00-1.15-.748c-.353-.137-.882-.3-1.857-.344-1.023-.047-1.351-.058-3.807-.058zM12 6.865a5.135 5.135 0 110 10.27 5.135 5.135 0 010-10.27zm0 1.802a3.333 3.333 0 100 6.666 3.333 3.333 0 000-6.666zm5.338-3.205a1.2 1.2 0 110 2.4 1.2 1.2 0 010-2.4z" clipRule="evenodd" />
    </svg>
  ),
  linkedin: (cls) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 448 512" className={cls}>
      <path d="M100.28 448H7.4V149.63h92.88zm-46.44-338C24 110 0 85.33 0 56.7 0 26.87 23.52 0 57.24 0c33.36 0 57.24 26.64 57.24 56.7-.04 28.63-23.88 53.3-57.24 53.3zm394.12 338h-92.8V302.4c0-34.71-12.35-58.42-43.35-58.42-23.64 0-37.65 15.87-43.8 31.18-2.26 5.48-2.82 13.08-2.82 20.72V448h-92.84s1.24-253.83 0-279.4h92.84v39.59c-.19.29-.43.61-.61.89h.61v-.89c12.33-19.02 34.35-46.16 83.56-46.16 60.92 0 106.64 39.78 106.64 125.23V448z" />
    </svg>
  ),
  twitter: (cls) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 16 16" className={cls} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M12.6.75h2.454l-5.36 6.142L16 15.25h-4.937l-3.867-5.07-4.425 5.07H.316l5.733-6.57L0 .75h5.063l3.495 4.633L12.601.75Zm-.86 13.028h1.36L4.323 2.145H2.865z" />
    </svg>
  ),
  whatsapp: (cls) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 448 512" className={cls} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-30.3 1.8-3.7.9-6.9-.5-9.7-1.4-2.8-12.5-30.1-17.1-41.2-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z" />
    </svg>
  ),
};

export function PublicHeader({ activePage = '' }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [homeDropOpen, setHomeDropOpen] = useState(false);
  const [mobileHomeOpen, setMobileHomeOpen] = useState(false);

  const navLink = 'relative text-base font-semibold text-[#004743] border-b-2 border-transparent hover:border-[#025E56] pb-0.5 transition-colors';
  const activeNavLink = 'relative text-base font-semibold text-[#025E56] border-b-2 border-[#025E56] pb-0.5';

  return (
    <header className="fixed mx-4 mt-2 lg:mt-6 lg:mx-20 rounded-full shadow-lg shadow-[#004743]/20 inset-x-0 top-0 z-50 bg-white/75 backdrop-blur-xl saturate-150 transition-all duration-300">
      <nav className="flex items-center justify-between p-2 lg:px-4">
        {/* Logo */}
        <div className="hidden lg:flex lg:flex-1">
          <a href="/"><img alt="Attorney AI" src="/logo.png" className="h-10 w-auto md:h-12 max-w-[180px] object-contain" /></a>
        </div>
        <a className="flex lg:hidden ml-1" href="/">
          <img alt="Attorney AI" src="/logo.png" className="h-9 w-auto max-w-[150px] object-contain px-1" />
        </a>

        {/* Mobile toggle */}
        <div className="flex lg:hidden mr-1">
          <button onClick={() => setMobileOpen(!mobileOpen)} className="-m-2.5 inline-flex items-center justify-center rounded-md p-2.5 text-gray-400">
            {mobileOpen ? (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="size-6">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            ) : Icons.menu('size-6')}
          </button>
        </div>

        {/* Desktop nav */}
        <div className="hidden lg:flex lg:gap-x-10 items-center">
          {/* Home dropdown */}
          <div className="relative" onMouseEnter={() => setHomeDropOpen(true)} onMouseLeave={() => setHomeDropOpen(false)}>
            <button className={`flex items-center gap-x-1 ${activePage === 'home' ? activeNavLink : navLink} bg-transparent`}>
              Home
              <span className={`transition-transform duration-200 ${homeDropOpen ? 'rotate-180' : ''}`}>
                {Icons.chevronDown('h-5 w-5 flex-none text-gray-400')}
              </span>
            </button>
            {homeDropOpen && (
              <div className="absolute left-0 top-full pt-2 w-44 z-50">
                <div className="bg-white rounded-2xl shadow-xl border border-gray-100 py-2">
                  <a href="/features" className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#004743] hover:bg-[#E8F5E9] hover:text-[#025E56] transition-colors rounded-lg mx-1">
                    ✨ Features
                  </a>
                  <a href="/faqs" className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#004743] hover:bg-[#E8F5E9] hover:text-[#025E56] transition-colors rounded-lg mx-1">
                    ❓ FAQs
                  </a>
                </div>
              </div>
            )}
          </div>
          <a className={activePage === 'blogs' ? activeNavLink : navLink} href="/blogs">Blogs</a>
          <a className={activePage === 'plans' ? activeNavLink : navLink} href="/plans">Pricing</a>
          <a className={activePage === 'about' ? activeNavLink : navLink} href="/about">About Us</a>
        </div>

        {/* Auth buttons */}
        <div className="hidden items-center lg:flex lg:flex-1 lg:justify-end gap-6">
          <a className="font-bold text-[#025E56] border-b border-transparent hover:border-b-2 hover:border-[#025E56]" href="/register">Sign Up</a>
          <a className="font-bold bg-gradient-to-br from-[#004743] to-[#025E56] hover:bg-gradient-to-tl text-white text-sm py-4 px-10 rounded-full shadow-lg transition-all" href="/login">Login</a>
        </div>
      </nav>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden absolute top-full left-0 right-0 mt-2 bg-white rounded-2xl shadow-xl p-4 mx-4">
          <div className="flex flex-col gap-1">
            <button onClick={() => setMobileHomeOpen(!mobileHomeOpen)} className="flex items-center justify-between w-full text-base font-semibold text-[#004743] py-2 px-2 rounded-lg hover:bg-gray-50">
              <span>Home</span>
              <span className={`transition-transform duration-200 ${mobileHomeOpen ? 'rotate-180' : ''}`}>{Icons.chevronDown('h-5 w-5 text-gray-400')}</span>
            </button>
            {mobileHomeOpen && (
              <div className="ml-4 flex flex-col gap-1 border-l-2 border-[#E8F5E9] pl-3">
                <a href="/features" className="text-sm font-medium text-[#025E56] py-1.5">✨ Features</a>
                <a href="/faqs" className="text-sm font-medium text-[#025E56] py-1.5">❓ FAQs</a>
              </div>
            )}
            <a className="text-base font-semibold text-[#004743] py-2 px-2 rounded-lg hover:bg-gray-50" href="/blogs">Blogs</a>
            <a className="text-base font-semibold text-[#004743] py-2 px-2 rounded-lg hover:bg-gray-50" href="/plans">Pricing</a>
            <a className="text-base font-semibold text-[#004743] py-2 px-2 rounded-lg hover:bg-gray-50" href="/about">About Us</a>
            <hr className="border-gray-200 my-1" />
            <a className="font-bold text-[#025E56] py-2 px-2" href="/register">Sign Up</a>
            <a className="font-bold bg-gradient-to-br from-[#004743] to-[#025E56] text-white text-sm py-3 px-8 rounded-full text-center mt-1" href="/login">Login</a>
          </div>
        </div>
      )}
    </header>
  );
}

export function PublicFooter() {
  const companyLinks = [
    { label: 'Home', href: '/' },
    { label: 'Features', href: '/features' },
    { label: 'Plans', href: '/plans' },
    { label: 'Blogs', href: '/blogs' },
    { label: 'About Us', href: '/about' },
  ];
  const supportLinks = [
    { label: 'FAQs', href: '/faqs' },
    { label: 'Get in Touch', href: '/touch' },
    { label: 'About Us', href: '/about' },
    { label: 'Refund Policy', href: '/faqs#pricing' },
  ];

  return (
    <footer className="bg-[#003734]">
      <div className="mx-auto max-w-7xl px-6 pb-8 pt-16 lg:px-8 lg:pt-12">
        <div className="flex flex-col md:flex-row md:justify-between gap-y-8">
          <div className="space-y-4">
            <div className="w-24 h-24 2xl:w-32 2xl:h-32 mb-8">
              <img src="/logo.png" alt="Attorney AI" className="w-full h-full object-contain brightness-0 invert" />
            </div>
            <p className="text-sm text-gray-300">Copyright © 2026 Firefly Tech Solutions Ltd.<br />All rights reserved</p>
            <div className="flex justify-start gap-x-6">
              <a href="https://www.facebook.com/people/AI-Attorney/61570359906228/" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition-colors">{Icons.facebook('size-5')}</a>
              <a href="https://www.instagram.com/aiattorney.pk/" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition-colors">{Icons.instagram('size-5')}</a>
              <a href="https://www.linkedin.com/company/ai-attorney1/" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition-colors">{Icons.linkedin('size-5')}</a>
              <a href="https://x.com/AiAttorneypk/" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-white transition-colors">{Icons.twitter('size-5')}</a>
            </div>
          </div>
          <div className="mt-8 grid grid-cols-2 gap-8">
            <div>
              <h3 className="text-sm font-semibold text-white">Company</h3>
              <ul className="mt-6 space-y-4">
                {companyLinks.map(l => <li key={l.label}><a className="text-sm text-gray-400 hover:text-white transition-colors" href={l.href}>{l.label}</a></li>)}
              </ul>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Support</h3>
              <ul className="mt-6 space-y-4">
                {supportLinks.map(l => <li key={l.label}><a className="text-sm text-gray-400 hover:text-white transition-colors" href={l.href}>{l.label}</a></li>)}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}

export function WhatsAppButton() {
  return (
    <div className="fixed bottom-4 right-4 z-30 sm:right-6">
      <div className="group">
        <a href="https://wa.me/923709250258" className="flex items-center p-3 bg-gradient-to-r from-green-500 to-teal-500 text-white rounded-full shadow-2xl hover:shadow-green-500/50 transform hover:scale-110 transition-all duration-300">
          {Icons.whatsapp('w-8 h-8')}
          <div className="overflow-hidden max-w-0 group-hover:max-w-xs group-hover:ml-2 transition-all duration-500 ease-in-out">
            <span className="font-semibold text-base whitespace-nowrap pr-2">Contact on WhatsApp</span>
          </div>
        </a>
      </div>
    </div>
  );
}

export default function PublicLayout({ children, activePage = '' }) {
  return (
    <div className="min-h-screen bg-white">
      <PublicHeader activePage={activePage} />
      <main>{children}</main>
      <PublicFooter />
      <WhatsAppButton />
    </div>
  );
}
