# Design Brief: Landing Page Redesign

## Problem

Lawyers and potential clients land on the page and see a generic, template-feel website that doesn't communicate trust, modernity, or the platform's dual audience. There's no clear split between "I am a lawyer" and "I need legal help" — both users see the same generic CTA and bounce because the page doesn't speak to them specifically.

## Solution

A high-conviction landing page that immediately presents two paths — one for lawyers, one for clients — using a dual-CTA hero in the style of Airbnb and Toptal. The rest of the page builds confidence through activity metrics, a clear "how it works" flow, social proof, and a pricing teaser. The visual language is modern SaaS (Notion/Linear) with legal gravitas — not a government site, not a template.

## Experience Principles

1. **Two audiences, one page** — Every section speaks to both lawyers and clients without making either feel like an afterthought. The hero splits them cleanly; sections below apply to both.
2. **Show don't tell** — Replace generic feature bullet points with a concrete 3-step "how it works" flow. Users should understand the product in 10 seconds.
3. **Confidence through specificity** — Activity metrics (documents generated, hours saved) instead of vanity user counts. Real testimonial names and roles. A pricing section that doesn't hide numbers.

## Aesthetic Direction

- **Philosophy**: Modern legal SaaS — clean, spacious, typographically strong. Inspired by Linear, Notion, and Clio. NOT a law firm brochure, NOT a government portal.
- **Tone**: Authoritative yet approachable. Calm confidence. Pakistan-context aware (Urdu-adjacent typography consideration, WhatsApp-native users).
- **Reference points**: Linear.app (tight typographic rhythm), Toptal.com (dual-audience hero), Airbnb (role-split CTA), Clio (legal SaaS credibility)
- **Anti-references**: LexisNexis (dated), government e-portals (bureaucratic), generic Tailwind templates (forgettable)

## Existing Patterns

- **Typography**: Tailwind defaults (system font stack) — no custom fonts loaded currently
- **Colors**: `#004743` (dark teal, primary), `#025E56` (deep teal, brand), `#E8F5E9` (mint, accent bg), white/gray for text
- **Spacing**: Tailwind default scale — no custom tokens
- **Components**: `ui/Button`, `ui/Card`, `ui/Input`, `ui/Modal` exist but are not used on the landing page — landing page is fully custom JSX
- **Animations**: framer-motion, GSAP, and lenis are installed and available

## Component Inventory

| Component | Status | Notes |
|-----------|--------|-------|
| PublicHeader (pill nav) | Exists | Keep as-is, minor tweaks only |
| PublicFooter | Exists | Keep as-is |
| HeroSection | Modify | Add dual-CTA split (lawyer / client), animated gradient bg, scroll-reveal |
| DualCTACards | New | Two role cards side by side — lawyer + client — each linking to own signup |
| HowItWorksSection | New | 3-step flow, numbered, with icon per step |
| AudienceSection | Modify | Remove emojis, use SVG icons, tighten copy |
| WhyChooseSection | Modify | Remove emojis, use SVG icons, reorder layout |
| StatsSection | Modify | Reframe to activity metrics: documents generated, hours saved, cases managed |
| TestimonialsSection | Modify | Keep carousel, clean up card styling, remove emoji stars → SVG stars |
| PricingTeaserSection | New | Show 2-3 plan names + price anchors, link to /plans |
| CTASection | Modify | Dual-CTA variant matching hero style |

## Key Interactions

- **Hero dual CTA**: Two cards or buttons side by side. On hover, card lifts slightly and shows a subtitle. On mobile, stacks vertically.
- **Scroll reveal**: Each section fades + slides up on scroll entry using framer-motion `whileInView`.
- **Hero gradient**: Subtle animated background — slow-moving radial gradient in brand teal.
- **Testimonial scroll**: Existing horizontal scroll stays. Add auto-scroll on desktop.
- **Stats counter**: Numbers count up when section enters viewport.
- **Pricing teaser**: Cards with hover lift. "Most popular" badge on middle plan.

## Responsive Behavior

- **Mobile-first** — hero dual CTA stacks vertically on mobile, side-by-side on md+
- **Nav**: Already has mobile hamburger — keep it
- **How it works**: Vertical list on mobile, horizontal 3-column on lg+
- **Stats**: 2-column grid on mobile, 4-column on lg+
- **Pricing teaser**: 1 column mobile, 3 columns lg+

## Accessibility Requirements

- All SVG icons must have `aria-hidden="true"` (decorative)
- CTA links must have descriptive text (not just "Sign Up")
- Color contrast: white text on `#004743` passes AA (checked: 7.2:1)
- Focus rings on all interactive elements
- Keyboard-navigable testimonial scroll

## Out of Scope

- Redesigning PublicHeader or PublicFooter (keep as-is)
- Adding Urdu language support
- Video hero or product screenshots (no screenshots exist yet)
- Blog or FAQ page redesigns
- Any backend changes
