# Build Tasks: Landing Page Redesign

Generated from: .design/landing-page/DESIGN_BRIEF.md
Date: 2026-05-23

Philosophy: Modern legal SaaS (Linear/Notion feel) with brand teal (#004743 / #025E56).
Stack: Next.js 15, React 19, Tailwind CSS 3, framer-motion (installed), GSAP (installed).

---

## Foundation

- [ ] **Create CSS design tokens**: Add CSS custom properties to `frontend/src/app/globals.css` — brand colors, spacing scale, font sizes, border-radius, shadow, motion durations. Use `:root` block. This prevents hardcoded hex values in every component going forward. _New file content (extend existing globals.css)._

- [ ] **Add Inter or Geist font**: Load a modern sans-serif via `next/font` in `frontend/src/app/layout.jsx`. Replace Tailwind system font stack. Inter is the Notion/Linear standard. _Modifies: layout.jsx._

---

## Core UI

- [ ] **Rewrite HeroSection**: New hero with animated radial gradient background (framer-motion), bold headline, subheadline, and the DualCTACards component. Remove current hero image (replace later with product screenshot or keep clean). _Modifies: Landing.jsx HeroSection. New sub-component: DualCTACards._

- [ ] **Build DualCTACards**: Two side-by-side cards ("I'm a Lawyer" → `/register?role=lawyer`, "I Need Legal Help" → `/register?role=client`). Each card has: role icon (SVG), title, one-line description, arrow CTA. Hover: card lifts with shadow. Mobile: stacks vertically. _New component inside Landing.jsx._

- [ ] **Build HowItWorksSection**: 3-step section with number badge, SVG icon, step title, one-line description. Desktop: horizontal 3-column. Mobile: vertical list. Scroll-reveal via framer-motion `whileInView`. _New section in Landing.jsx._

- [ ] **Rewrite AudienceSection**: Keep 4-card grid, replace emoji icons with inline SVG, tighten copy. Remove dark background or make it a subtle teal gradient instead of solid `#004743`. Scroll-reveal. _Modifies: Landing.jsx AudienceSection._

- [ ] **Rewrite WhyChooseSection**: Replace emoji icons with proper SVG icons. Keep 4 feature points. Fix layout so image and text are properly balanced. Scroll-reveal. _Modifies: Landing.jsx WhyChooseSection._

- [ ] **Rewrite StatsSection**: Change stats from user counts to activity metrics (Documents Generated 5,000+, Hours Saved 1,200+, Cases Managed 300+, Legal Professionals 100+). Add count-up animation using framer-motion when section enters viewport. _Modifies: Landing.jsx StatsSection._

- [ ] **Build PricingTeaserSection**: 3 plan cards (Free / Pro / Firm) with plan name, price anchor, 2-3 bullet features, and a CTA button. "Most Popular" badge on Pro. Links to `/plans`. Scroll-reveal. _New section in Landing.jsx, inserted before CTASection._

---

## Interactions & States

- [ ] **Scroll-reveal wrapper**: Create a reusable `<Reveal>` component using framer-motion `whileInView` + `initial` (fade up). Wrap every section with it. _New component, defined at top of Landing.jsx or in a separate file._

- [ ] **Hero gradient animation**: Animate two soft radial gradients in the hero background using framer-motion `animate` with slow looping keyframes. Colors: translucent teal (`rgba(2,94,86,0.12)` and `rgba(0,71,67,0.08)`). _Part of HeroSection rewrite._

- [ ] **DualCTACards hover states**: lift (`translateY(-4px)`), stronger shadow, subtle border highlight on hover. Active: slight press (`translateY(-1px)`). _Part of DualCTACards build._

- [ ] **Stats count-up**: Use framer-motion `useInView` + `useMotionValue` + `useTransform` to animate numbers counting up when StatsSection enters viewport. _Part of StatsSection rewrite._

- [ ] **Testimonial auto-scroll**: On desktop, auto-scroll the testimonial container slowly using a CSS `@keyframes` marquee or GSAP. On hover/touch: pause. _Modifies: Landing.jsx TestimonialsSection._

---

## Responsive & Polish

- [ ] **Mobile audit**: Check all sections at 375px (iPhone SE). DualCTACards must stack. HowItWorks must be vertical. PricingTeaser must be 1-column. Fix any overflow or padding issues. _Breakpoints: sm (375px), md (768px), lg (1024px)._

- [ ] **Replace all emoji icons**: Systematically find every emoji in Landing.jsx (⚖️ 💰 ⚡ 🔒 👤 👨‍🎓 🏢 ★) and replace with inline SVG or lucide-react icons (lucide is not installed — use inline SVGs from heroicons set to keep bundle lean). _Modifies: AudienceSection, WhyChooseSection, TestimonialsSection._

- [ ] **Accessibility pass**: Add `aria-label` to CTA links ("Sign up as a lawyer", "Sign up as a client"). Add `aria-hidden="true"` to all decorative SVGs. Verify focus rings are visible on DualCTACards and all buttons. _All new components._

---

## Review

- [ ] **Design review**: Check visual consistency — spacing rhythm, color usage (only use token values), typography hierarchy, hover states across all new sections.
- [ ] **Cross-browser check**: Test in Chrome + Safari on mobile. Check backdrop-blur support on the nav pill.
- [ ] **Performance**: No new heavy dependencies added. framer-motion and GSAP are already in bundle.
