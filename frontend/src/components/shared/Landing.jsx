'use client';
import React, { useState, useEffect } from 'react';
import { DARK, LIGHT } from './themes';

// Simple icon components
const Icons = {
  menu: (className) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
    </svg>
  ),
  chevronDown: (className) => (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
    </svg>
  ),
  star: (className) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className={className} height="14" width="14" xmlns="http://www.w3.org/2000/svg">
      <path d="M394 480a16 16 0 0 1-9.39-3L256 383.76 127.39 477a16 16 0 0 1-24.55-18.08L153 310.35 23 221.2a16 16 0 0 1 9-29.2h160.38l48.4-148.95a16 16 0 0 1 30.44 0l48.4 149H480a16 16 0 0 1 9.05 29.2L359 310.35l50.13 148.53A16 16 0 0 1 394 480z" />
    </svg>
  ),
  user: (className) => (
    <svg stroke="currentColor" fill="none" strokeWidth="0" viewBox="0 0 24 24" className={className} height="30" width="30" xmlns="http://www.w3.org/2000/svg">
      <path fillRule="evenodd" clipRule="evenodd" d="M16 9C16 11.2091 14.2091 13 12 13C9.79086 13 8 11.2091 8 9C8 6.79086 9.79086 5 12 5C14.2091 5 16 6.79086 16 9ZM14 9C14 10.1046 13.1046 11 12 11C10.8954 11 10 10.1046 10 9C10 7.89543 10.8954 7 12 7C13.1046 7 14 7.89543 14 9Z" fill="currentColor" />
      <path fillRule="evenodd" clipRule="evenodd" d="M12 1C5.92487 1 1 5.92487 1 12C1 18.0751 5.92487 23 12 23C18.0751 23 23 18.0751 23 12C23 5.92487 18.0751 1 12 1ZM3 12C3 14.0902 3.71255 16.014 4.90798 17.5417C6.55245 15.3889 9.14627 14 12.0645 14C14.9448 14 17.5092 15.3531 19.1565 17.4583C20.313 15.9443 21 14.0524 21 12C21 7.02944 16.9706 3 12 3C7.02944 3 3 7.02944 3 12ZM12 21C9.84977 21 7.87565 20.2459 6.32767 18.9878C7.59352 17.1812 9.69106 16 12.0645 16C14.4084 16 16.4833 17.1521 17.7538 18.9209C16.1939 20.2191 14.1881 21 12 21Z" fill="currentColor" />
    </svg>
  ),
  facebook: (className) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className={className} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M504 256C504 119 393 8 256 8S8 119 8 256c0 123.78 90.69 226.38 209.25 245V327.69h-63V256h63v-54.64c0-62.15 37-96.48 93.67-96.48 27.14 0 55.52 4.84 55.52 4.84v61h-31.28c-30.8 0-40.41 19.12-40.41 38.73V256h68.78l-11 71.69h-57.78V501C413.31 482.38 504 379.78 504 256z" />
    </svg>
  ),
  instagram: (className) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 24 24" className={className}>
      <path fillRule="evenodd" d="M12.315 2c2.43 0 2.784.013 3.808.06 1.064.049 1.791.218 2.427.465a4.902 4.902 0 011.772 1.153 4.902 4.902 0 011.153 1.772c.247.636.416 1.363.465 2.427.048 1.067.06 1.407.06 4.123v.08c0 2.643-.012 2.987-.06 4.043-.049 1.064-.218 1.791-.465 2.427a4.902 4.902 0 01-1.153 1.772 4.902 4.902 0 01-1.772 1.153c-.636.247-1.363.416-2.427.465-1.067.048-1.407.06-4.123.06h-.08c-2.643 0-2.987-.012-4.043-.06-1.064-.049-1.791-.218-2.427-.465a4.902 4.902 0 01-1.772-1.153 4.902 4.902 0 01-1.153-1.772c-.247-.636-.416-1.363-.465-2.427-.047-1.024-.06-1.379-.06-3.808v-.63c0-2.43.013-2.784.06-3.808.049-1.064.218-1.791.465-2.427a4.902 4.902 0 011.153-1.772A4.902 4.902 0 015.45 2.525c.636-.247 1.363-.416 2.427-.465C8.901 2.013 9.256 2 11.685 2h.63zm-.081 1.802h-.468c-2.456 0-2.784.011-3.807.058-.975.045-1.504.207-1.857.344-.467.182-.8.398-1.15.748-.35.35-.566.683-.748 1.15-.137.353-.3.882-.344 1.857-.047 1.023-.058 1.351-.058 3.807v.468c0 2.456.011 2.784.058 3.807.045.975.207 1.504.344 1.857.182.466.399.8.748 1.15.35.35.683.566 1.15.748.353.137.882.3 1.857.344 1.054.048 1.37.058 4.041.058h.08c2.597 0 2.917-.01 3.96-.058.976-.045 1.505-.207 1.858-.344.466-.182.8-.398 1.15-.748.35-.35.566-.683.748-1.15.137-.353.3-.882.344-1.857.048-1.055.058-1.37.058-4.041v-.08c0-2.597-.01-2.917-.058-3.96-.045-.976-.207-1.505-.344-1.858a3.097 3.097 0 00-.748-1.15 3.098 3.098 0 00-1.15-.748c-.353-.137-.882-.3-1.857-.344-1.023-.047-1.351-.058-3.807-.058zM12 6.865a5.135 5.135 0 110 10.27 5.135 5.135 0 010-10.27zm0 1.802a3.333 3.333 0 100 6.666 3.333 3.333 0 000-6.666zm5.338-3.205a1.2 1.2 0 110 2.4 1.2 1.2 0 010-2.4z" clipRule="evenodd" />
    </svg>
  ),
  linkedin: (className) => (
    <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 448 512" className={className}>
      <path d="M100.28 448H7.4V149.63h92.88zm-46.44-338C24 110 0 85.33 0 56.7 0 26.87 23.52 0 57.24 0c33.36 0 57.24 26.64 57.24 56.7-.04 28.63-23.88 53.3-57.24 53.3zm394.12 338h-92.8V302.4c0-34.71-12.35-58.42-43.35-58.42-23.64 0-37.65 15.87-43.8 31.18-2.26 5.48-2.82 13.08-2.82 20.72V448h-92.84s1.24-253.83 0-279.4h92.84v39.59c-.19.29-.43.61-.61.89h.61v-.89c12.33-19.02 34.35-46.16 83.56-46.16 60.92 0 106.64 39.78 106.64 125.23V448z" />
    </svg>
  ),
  twitter: (className) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 16 16" className={className} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M12.6.75h2.454l-5.36 6.142L16 15.25h-4.937l-3.867-5.07-4.425 5.07H.316l5.733-6.57L0 .75h5.063l3.495 4.633L12.601.75Zm-.86 13.028h1.36L4.323 2.145H2.865z" />
    </svg>
  ),
  whatsapp: (className) => (
    <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 448 512" className={className} height="1em" width="1em" xmlns="http://www.w3.org/2000/svg">
      <path d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-30.3 1.8-3.7.9-6.9-.5-9.7-1.4-2.8-12.5-30.1-17.1-41.2-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z" />
    </svg>
  )
};

// Navigation Component
function Header({ isDark, toggleTheme }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const t = isDark ? DARK : LIGHT;

  return (
    <header className="fixed mx-4 mt-2 lg:mt-6 lg:mx-20 rounded-full shadow-lg shadow-[#004743]/20 inset-x-0 top-0 z-50 transition-all duration-300 bg-white/90 backdrop-blur-sm">
      <nav className="flex items-center justify-between p-2 lg:px-4 lg:pl-4">
        {/* Logo */}
        <div className="hidden lg:flex lg:flex-1">
          <a href="/">
            <img alt="AI Attorney Logo" src="/logo.png" className="h-8 w-auto md:h-12 lg:w-24 lg:h-14" />
          </a>
        </div>
        <a className="flex lg:hidden ml-1" href="/">
          <img alt="AI Attorney Logo" src="/logo.png" className="h-8 w-auto md:h-12 px-1" />
        </a>

        {/* Mobile Menu Button */}
        <div className="flex lg:hidden mr-1">
          <button onClick={() => setMobileMenuOpen(!mobileMenuOpen)} className="-m-2.5 inline-flex items-center justify-center rounded-md p-2.5 text-gray-400">
            {Icons.menu("size-6")}
          </button>
        </div>

        {/* Desktop Navigation */}
        <div className="hidden lg:flex lg:gap-x-10">
          <div className="relative">
            <a className="flex items-center gap-x-1 relative text-base font-semibold text-[#004743] border-b-2 border-transparent hover:border-[#025E56] pb-0.5" href="/">
              Home
              {Icons.chevronDown("h-5 w-5 flex-none text-gray-400 transition-transform duration-300")}
            </a>
          </div>
          <a className="relative text-base font-semibold text-[#004743] border-b-2 border-transparent hover:border-[#025E56] pb-0.5" href="/blogs">Blogs</a>
          <a className="relative text-base font-semibold text-[#004743] border-b-2 border-transparent hover:border-[#025E56] pb-0.5" href="/plans">Pricing</a>
          <a className="relative text-base font-semibold text-[#004743] border-b-2 border-transparent hover:border-[#025E56] pb-0.5" href="/about">About Us</a>
        </div>

        {/* Auth Buttons */}
        <div className="hidden items-center lg:flex lg:flex-1 lg:justify-end gap-6">
          <a className="font-bold text-[#025E56] border-b border-transparent hover:border-b-2 hover:border-[#025E56]" href="/registration">Sign Up</a>
          <a className="font-bold bg-gradient-to-br from-[#004743] to-[#025E56] hover:bg-gradient-to-tl text-white text-sm py-4 px-10 rounded-full shadow-lg" href="/login">Login</a>
          <button onClick={toggleTheme} className="p-2 rounded-full bg-gray-100 hover:bg-gray-200">
            {isDark ? '☀️' : '🌙'}
          </button>
        </div>
      </nav>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="lg:hidden absolute top-full left-0 right-0 mt-2 bg-white rounded-2xl shadow-xl p-4 mx-4">
          <div className="flex flex-col gap-4">
            <a className="text-base font-semibold text-[#004743]" href="/">Home</a>
            <a className="text-base font-semibold text-[#004743]" href="/blogs">Blogs</a>
            <a className="text-base font-semibold text-[#004743]" href="/plans">Pricing</a>
            <a className="text-base font-semibold text-[#004743]" href="/about">About Us</a>
            <hr className="border-gray-200" />
            <a className="font-bold text-[#025E56]" href="/registration">Sign Up</a>
            <a className="font-bold bg-gradient-to-br from-[#004743] to-[#025E56] text-white text-sm py-3 px-8 rounded-full text-center" href="/login">Login</a>
          </div>
        </div>
      )}
    </header>
  );
}

// Hero Section
function HeroSection() {
  return (
    <section className="relative isolate pt-24 lg:pt-32">
      <div className="relative isolate overflow-hidden bg-gradient-to-b from-indigo-100/20 pt-4">
        <div className="mx-auto max-w-7xl px-6 py-16 lg:py-24 lg:px-16">
          <div className="mx-auto max-w-2xl lg:mx-0 lg:grid lg:max-w-none lg:grid-cols-2 lg:gap-x-16 lg:gap-y-6">
            <div className="mt-6 max-w-xl lg:mt-12">
              <h1 className="max-w-2xl h-auto text-4xl font-semibold tracking-tight text-[#004743] sm:text-5xl lg:text-6xl mb-4">
                <span className="text-[#025E56]">AI Attorney</span>
                <span className="text-3xl md:text-4xl lg:text-5xl block mt-2">- Faster, Smarter Legal Assistance</span>
              </h1>
              <p className="text-pretty text-lg font-medium text-gray-600 sm:text-xl/8 py-2 md:pb-4">
                Get instant and professional legal drafting, unparalleled case insights, and powerful research tools, all tailored for Pakistani law. Trusted by top legal professionals, built for ultimate speed and accuracy.
              </p>
              <div className="my-6">
                <a className="inline-block py-3 px-8 text-sm font-semibold bg-gradient-to-br from-[#004743] to-[#025E56] hover:bg-gradient-to-tl text-white rounded-md shadow-lg" href="/login">
                  Try For Free
                </a>
              </div>
            </div>
            <div className="relative flex justify-center items-center h-full mt-8 lg:mt-0">
              <img alt="AI Attorney Hero" src="/assets/hero%20%201-BIdq_zKZ.png" className="w-auto md:w-full justify-center items-center max-w-md lg:max-w-lg" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// What is AI Attorney Section
function AboutSection() {
  return (
    <div className="mx-auto max-w-7xl px-6 lg:flex lg:px-8 py-16">
      <div className="mx-auto flex max-w-2xl flex-col-reverse gap-x-12 gap-y-16 lg:mx-0 lg:min-w-full lg:max-w-none lg:flex lg:flex-row lg:gap-x-12 lg:gap-y-0">
        <div className="w-auto flex-auto lg:ml-auto lg:w-1/2 lg:flex-none lg:self-center">
          <img alt="AI Attorney Illustration" src="/assets/Illustration-DLjtgThR.png" className="w-auto md:w-[35rem] h-auto px-0 md:px-12" />
        </div>
        <div className="lg:col-end-1 lg:w-1/2 lg:max-w-lg lg:pb-8 lg:self-center">
          <h2 className="text-4xl font-semibold tracking-tight text-[#025E56] sm:text-5xl">What is AI Attorney?</h2>
          <p className="mt-4 text-pretty text-lg font-medium text-gray-600 sm:text-xl/8">
            AI Attorney isn't just a tool it's a transformative legal intelligence platform designed to reshape how legal professionals work in Pakistan. Far beyond a simple chatbot, it's an integrated, AI-powered assistant that automates everyday legal workflows, accelerates drafting, and streamlines complex research.
            <br /><br />
            With real-time document generation, instant access to comprehensive Pakistani case law, and contextual legal insights, AI Attorney empowers lawyers, law firms, and individuals to operate with unprecedented speed, precision, and confidence. Secure, intelligent, and user-friendly, it centralizes your entire legal workflow – from managing court schedules to drafting intricate agreements, and exploring legal precedents – accessible anytime, anywhere.
          </p>
        </div>
      </div>
    </div>
  );
}

// Target Audience Cards
function AudienceSection() {
  const audiences = [
    {
      icon: "/assets/consumers-B_ULSyVd.svg",
      title: "Individuals",
      description: "Everyday individuals seeking legal solutions or quick insights for personal matters"
    },
    {
      icon: null, // Student icon inline
      title: "Law Students",
      description: "Students aiming to bridge academic theory with practical legal application"
    },
    {
      icon: "/assets/professionals-C7RmYMNT.svg",
      title: "Legal Professionals",
      description: "Lawyers and paralegals seeking to streamline research and automate drafting."
    },
    {
      icon: null, // Law firm icon inline
      title: "Law Firms",
      description: "Firms leveraging AI to enhance team efficiency and document automation"
    }
  ];

  return (
    <div className="bg-[#004743] py-10 px-4 lg:py-28 mt-10">
      <div className="mx-auto max-w-7xl lg:max-w-[90rem]">
        <div className="mx-auto max-w-2xl lg:max-w-none">
          <div className="text-center">
            <h2 className="text-balance text-4xl font-semibold tracking-tight text-white sm:text-5xl">Who is AI Attorney for?</h2>
            <p className="mt-4 text-lg/8 text-gray-300">
              Our Mission: Legal Access. Simplified. For Everyone. We believe justice should be accessible, efficient, and intelligent.
              <br />AI Attorney empowers all stakeholders in Pakistan's legal ecosystem, delivering cutting-edge technology that transforms complexity into clarity.
            </p>
          </div>
          <div className="mx-auto mt-16 max-w-2xl sm:mt-16 lg:mt-20 lg:max-w-none md:flex md:justify-center">
            <div className="grid max-w-xl grid-cols-1 gap-x-8 gap-y-16 lg:max-w-none lg:grid-cols-4">
              {audiences.map((item, idx) => (
                <div key={idx} className="bg-white rounded-2xl shadow-lg hover:shadow-2xl transition-shadow duration-300">
                  <div className="flex flex-col items-center justify-center py-6 px-8">
                    <div className="text-base font-semibold text-[#004743]">
                      <div className="flex items-center justify-center rounded-lg mb-3">
                        {item.icon ? (
                          <img src={item.icon} alt={item.title} className="h-12 w-12" />
                        ) : (
                          <div className="h-12 w-12 bg-[#E8F5E9] rounded-lg flex items-center justify-center text-2xl">
                            {idx === 1 ? '👨‍🎓' : '🏢'}
                          </div>
                        )}
                      </div>
                      {item.title}
                    </div>
                    <p className="mt-3 text-base text-gray-600 text-center">{item.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Why Choose Section
function WhyChooseSection() {
  const features = [
    {
      title: "Your Always-On Legal Partner, Built for Pakistan",
      description: "AI Attorney is your intelligent legal companion, available 24/7. Built with an unparalleled understanding of Pakistani law, it delivers precise, context-aware support for your research, drafting, and litigation needs."
    },
    {
      title: "Smarter Legal Help, Without the High Fees",
      description: "Skip the traditional billable hours. With transparent pricing and powerful features, AI Attorney makes premium legal services accessible to individuals, students, and firms alike – ensuring quality and compliance without compromise."
    },
    {
      title: "Fast, Clear, Actionable Answers",
      description: "We simplify legal complexity. From intricate contract clauses to concise case summaries, AI Attorney explains the law in plain language – instantly. No jargon, no delays, just accurate, actionable insights precisely when you need them."
    },
    {
      title: "Privacy You Can Trust",
      description: "Confidentiality is our bedrock. Every interaction, document, and chat is secured with robust encryption. AI Attorney ensures your sensitive information remains protected, allowing you to focus on justice, not risk."
    }
  ];

  return (
    <div className="mt-32 overflow-hidden sm:mt-40">
      <div className="mx-auto max-w-7xl px-6 lg:flex lg:px-8">
        <div className="mx-auto grid max-w-2xl grid-cols-1 gap-x-12 gap-y-16 lg:mx-0 lg:min-w-full lg:max-w-none lg:flex-none lg:gap-y-8">
          <div className="lg:col-end-1 lg:w-full lg:max-w-lg lg:pb-8">
            <div className="bg-white px-4 py-5 sm:px-6">
              <h2 className="text-lg font-semibold tracking-tight text-[#025E56] lg:text-4xl mb-4">Why choose AI Attorney?</h2>
              {features.map((feature, idx) => (
                <div key={idx} className="relative mt-6 pl-6 md:pl-16">
                  <div className="text-base lg:text-lg font-semibold text-[#004743]">
                    <div className="absolute left-0 top-0 flex size-6 md:size-14 items-center justify-center rounded-lg bg-[#E8F5E9]">
                      <span className="text-xl">{['⚖️', '💰', '⚡', '🔒'][idx]}</span>
                    </div>
                    {feature.title}
                  </div>
                  <p className="mt-2 text-sm md:text-base text-gray-600">{feature.description}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-center w-full" style={{ perspective: '1000px' }}>
            <img alt="AI Attorney Features" src="/assets/choose-Ai-CIXyTjdX.svg" className="w-auto md:w-[37rem] rounded-2xl object-cover" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Statistics Section
function StatsSection() {
  const stats = [
    { icon: "/assets/consumer-ngrhytn0.svg", label: "Consumers", value: "17" },
    { icon: null, label: "Students", value: "75", emoji: "👨‍🎓" },
    { icon: null, label: "Legal Professionals", value: "11", emoji: "⚖️" },
    { icon: "/assets/lagal%20firms-jRw86FAP.svg", label: "Legal Firms", value: "1" }
  ];

  return (
    <section className="py-16">
      <div className="mx-auto max-w-7xl px-6 lg:flex lg:items-center lg:justify-between">
        <div className="mt-10 text-left lg:mt-0 lg:w-2/3">
          <h2 className="text-4xl font-semibold text-[#004743]">
            Trusted by Professionals,<br />
            <span className="text-[#025E56]">Chosen by Pakistan.</span>
          </h2>
          <p className="mt-4 text-lg text-gray-500">
            From individuals and law students to leading legal professionals and rapidly growing firms, AI Attorney is the definitive platform for fast, secure, and intelligent legal solutions across Pakistan. Built on trust. Powered by results.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-6 lg:w-1/2 mt-4 lg:mt-0">
          {stats.map((stat, idx) => (
            <div key={idx} className="flex items-center space-x-4">
              {stat.icon ? (
                <img src={stat.icon} alt={stat.label} className="h-7 w-auto md:h-12 md:w-12" />
              ) : (
                <span className="text-3xl md:text-4xl">{stat.emoji}</span>
              )}
              <div className="mt-4 md:mt-0">
                <p className="text-lg font-semibold text-[#004743]">{stat.label}</p>
                <p className="text-lg md:text-2xl font-bold text-[#025E56]">{stat.value}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// Testimonials Section
function TestimonialsSection() {
  const testimonials = [
    { name: "Muzammil", role: "Advocate", text: "As a legal consultant, AI Attorney has been a game-changer, providing quick access to precedents and legal analytics that drive better decision-making." },
    { name: "Rafay", role: "Advocate", text: "The automated features of AI Attorney save us hours of work every week. It's reliable, fast, and exactly what our legal department needed to stay ahead." },
    { name: "Ayan", role: "Advocate", text: "AI Attorney is the future of legal technology. Its ability to adapt and learn our specific legal needs has made it an irreplaceable part of our firm." },
    { name: "Mehdi", role: "Advocate", text: "AI Attorney is the future of legal technology. Its ability to adapt and learn our specific legal needs has made it an irreplaceable part of our firm." }
  ];

  return (
    <section className="bg-[#004743] py-6 relative">
      <div className="mx-auto max-w-7xl lg:max-w-full">
        <header className="text-center">
          <h2 className="text-balance text-4xl font-semibold tracking-tight text-white sm:text-5xl">Testimonials</h2>
          <p className="mt-2 text-lg text-gray-300">See what professionals, students, and legal experts are saying about AI Attorney.</p>
        </header>
        <div className="relative overflow-hidden py-4 mt-8">
          <div className="absolute inset-0 pointer-events-none z-10" style={{ background: 'linear-gradient(to right, rgba(0, 55, 52, 0.9) 0%, rgba(0, 55, 52, 0.3) 10%, rgba(0, 55, 52, 0) 50%, rgba(0, 55, 52, 0.3) 80%, rgba(0, 55, 52, 0.9) 100%)' }} />
          <div className="flex gap-4 overflow-x-auto px-4 pb-4 scrollbar-hide">
            {testimonials.map((item, idx) => (
              <div key={idx} className="flex-shrink-0 min-w-[300px] md:min-w-[350px] py-6 px-4 rounded-3xl bg-white">
                <div className="flex justify-between items-center gap-5 w-full mb-4">
                  <div className="flex text-[#004743]">
                    {[1,2,3,4,5].map(i => <React.Fragment key={i}>{Icons.star("h-4 w-4 mr-1")}</React.Fragment>)}
                  </div>
                  <div className="flex items-center justify-center py-2 gap-2">
                    <div className="bg-[#004743] rounded-full p-1">
                      <svg stroke="currentColor" fill="currentColor" strokeWidth="0" viewBox="0 0 512 512" className="text-white h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg">
                        <path d="M313.4 32.9c26 5.2 42.9 30.5 37.7 56.5l-2.3 11.4c-5.3 26.7-15.1 52.1-28.8 75.2l144 0c26.5 0 48 21.5 48 48c0 18.5-10.5 34.6-25.9 42.6C497 275.4 504 288.9 504 304c0 23.4-16.8 42.9-38.9 47.1c4.4 7.3 6.9 15.8 6.9 24.9c0 21.3-13.9 39.4-33.1 45.6c.7 3.3 1.1 6.8 1.1 10.4c0 26.5-21.5 48-48 48l-97.5 0c-19 0-37.5-5.6-53.3-16.1l-38.5-25.7C176 420.4 160 390.4 160 358.3l0-38.3 0-48 0-24.9c0-29.2 13.3-56.7 36-75l7.4-5.9c26.5-21.2 44.6-51 51.2-84.2l2.3-11.4c5.2-26 30.5-42.9 56.5-37.7zM32 192l64 0c17.7 0 32 14.3 32 32l0 224c0 17.7-14.3 32-32 32l-64 0c-17.7 0-32-14.3-32-32L0 224c0-17.7 14.3-32 32-32z" />
                      </svg>
                    </div>
                    <span className="text-sm text-gray-600">Testimonial</span>
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <blockquote className="text-start text-gray-700 text-sm">
                    <p>{item.text}</p>
                  </blockquote>
                  <div className="flex flex-row items-center justify-start gap-2 mt-3">
                    {Icons.user("h-8 w-8 text-gray-400")}
                    <div className="flex flex-col gap-0">
                      <p className="text-sm font-semibold text-gray-800">{item.name}</p>
                      <span className="text-xs text-gray-500">{item.role}</span>
                    </div>
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

// CTA Section
function CTASection() {
  return (
    <section className="relative isolate overflow-hidden py-16 px-6 lg:px-8 shadow-lg">
      <div className="absolute inset-0 -z-10">
        <div className="absolute top-1/4 left-1/4 h-64 w-64 rounded-full bg-gradient-to-br from-[#025E56] to-transparent opacity-20 blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 h-64 w-64 rounded-full bg-gradient-to-br from-[#004743] to-transparent opacity-20 blur-3xl" />
      </div>
      <div className="mx-auto max-w-7xl text-center">
        <h2 className="text-4xl font-bold text-[#025E56]">How to Use AI Attorney</h2>
        <p className="mt-4 text-lg text-gray-600">Simplify your legal journey with AI Attorney. Try our intuitive and powerful tools for free today!</p>
        <div className="mt-10 flex items-center justify-center">
          <a className="relative group inline-flex items-center justify-center rounded-md bg-[#004743] px-8 py-3 text-sm font-semibold text-white shadow-lg transition-transform hover:scale-105" href="/login">
            <span className="absolute inset-0 rounded-md bg-gradient-to-r from-[#025E56] to-[#004743] opacity-0 group-hover:opacity-20 transition-opacity duration-300" />
            <span>Start Your Freemium</span>
            <span className="ml-2">→</span>
          </a>
        </div>
      </div>
    </section>
  );
}

// WhatsApp Button
function WhatsAppButton() {
  return (
    <div className="fixed bottom-4 right-4 z-30 flex flex-col-reverse items-end gap-2 sm:right-6">
      <div className="group z-30">
        <a href="https://wa.me/923709250258" className="flex items-center p-3 bg-gradient-to-r from-green-500 to-teal-500 text-white rounded-full shadow-2xl hover:shadow-green-500/50 transform hover:scale-110 transition-all duration-300">
          {Icons.whatsapp("w-8 h-8")}
          <div className="overflow-hidden max-w-0 group-hover:max-w-xs group-hover:ml-2 transition-all duration-500 ease-in-out">
            <span className="font-semibold text-base whitespace-nowrap pr-2">Contact on WhatsApp</span>
          </div>
        </a>
      </div>
    </div>
  );
}

// Footer
function Footer() {
  const companyLinks = [
    { label: "Home", href: "/" },
    { label: "Features", href: "/features" },
    { label: "Plans", href: "/plans" },
    { label: "Blogs", href: "/blogs" },
    { label: "About Us", href: "/about" }
  ];

  const supportLinks = [
    { label: "FAQs", href: "/faqs" },
    { label: "Help center", href: "/help_center" },
    { label: "Get in touch", href: "/touch" },
    { label: "Refund Policy", href: "/refund-policy" }
  ];

  return (
    <footer className="bg-[#003734]">
      <div className="mx-auto max-w-7xl px-6 pb-8 pt-16 lg:px-8 lg:pt-12">
        <div className="flex flex-col md:flex-row md:justify-between gap-y-8">
          <div className="space-y-4">
            <div className="w-24 h-24 2xl:w-32 2xl:h-32 mb-8">
              <img src="/logo.png" alt="AI Attorney Logo" className="w-full h-full object-contain brightness-0 invert" />
            </div>
            <p className="text-balance text-sm text-gray-300">
              Copyright © 2026 Firefly Tech Solutions Ltd.<br />All rights reserved
            </p>
            <div className="flex justify-start gap-x-6">
              <a href="https://www.facebook.com/people/AI-Attorney/61570359906228/" target="_blank" className="text-gray-400 hover:text-gray-300">
                <span className="sr-only">Facebook</span>
                {Icons.facebook("size-6")}
              </a>
              <a href="https://www.instagram.com/aiattorney.pk/" target="_blank" className="text-gray-400 hover:text-gray-300">
                <span className="sr-only">Instagram</span>
                {Icons.instagram("size-6")}
              </a>
              <a href="https://www.linkedin.com/company/ai-attorney1/" target="_blank" className="text-gray-400 hover:text-gray-300">
                <span className="sr-only">LinkedIn</span>
                {Icons.linkedin("size-6")}
              </a>
              <a href="https://x.com/AiAttorneypk/" target="_blank" className="text-gray-400 hover:text-gray-300">
                <span className="sr-only">Twitter</span>
                {Icons.twitter("size-6")}
              </a>
            </div>
          </div>
          <div className="mt-16 grid grid-cols-2 gap-8 xl:col-span-2 xl:mt-0">
            <div>
              <h3 className="text-sm font-semibold text-white">Company</h3>
              <ul className="mt-6 space-y-4">
                {companyLinks.map(link => (
                  <li key={link.label}>
                    <a className="text-sm text-gray-400 hover:text-white" href={link.href}>{link.label}</a>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Support</h3>
              <ul className="mt-6 space-y-4">
                {supportLinks.map(link => (
                  <li key={link.label}>
                    <a className="text-sm text-gray-400 hover:text-white" href={link.href}>{link.label}</a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}

// Main Landing Page Component
export default function LandingPage() {
  const [isDark, setIsDark] = useState(() => {
    try { 
      const s = localStorage.getItem("aai-theme"); 
      return s ? s === "dark" : false; 
    } catch { 
      return false; 
    }
  });

  useEffect(() => {
    try { 
      localStorage.setItem("aai-theme", isDark ? "dark" : "light"); 
    } catch {}
  }, [isDark]);

  return (
    <div className="min-h-screen bg-white">
      <Header isDark={isDark} toggleTheme={() => setIsDark(!isDark)} />
      <main>
        <HeroSection />
        <AboutSection />
        <AudienceSection />
        <WhyChooseSection />
        <StatsSection />
        <TestimonialsSection />
        <CTASection />
      </main>
      <Footer />
      <WhatsAppButton />
    </div>
  );
}
