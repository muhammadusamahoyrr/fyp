# Information Architecture: Landing Page

## Page Structure (top → bottom)

```
/ (Landing Page)
├── PublicHeader (fixed pill nav)
├── HeroSection
│   ├── Headline + subheadline
│   ├── DualCTACards (Lawyer / Client)
│   └── Trust signal strip (logos / stat pills)
├── HowItWorksSection
│   ├── Step 1: Create your account
│   ├── Step 2: Describe your legal need
│   └── Step 3: Get AI-powered assistance instantly
├── AudienceSection
│   └── 4 cards: Individuals, Law Students, Legal Professionals, Firms
├── WhyChooseSection
│   └── 4 feature points with SVG icons
├── StatsSection
│   └── 4 activity metrics (documents, hours saved, cases, professionals)
├── TestimonialsSection
│   └── Horizontal scroll cards
├── PricingTeaserSection
│   └── 3 plan cards → links to /plans
├── CTASection
│   └── Dual CTA (mirrors hero)
└── PublicFooter
```

## Navigation Model

- **Primary nav**: Home (dropdown: Features, FAQs), Blogs, Pricing, About Us
- **Utility nav**: Sign Up, Login
- **Mobile nav**: Hamburger → drawer with same links
- **In-page anchors**: None (single-page scroll, no anchor nav needed at this scale)

## Content Hierarchy

### HeroSection
1. Headline — who you are and what this does
2. Subheadline — the key promise (Pakistan-specific, AI-powered)
3. Dual CTA — the two paths (lawyer / client)
4. Trust strip — quick credibility (small stat pills or partner logos)

### DualCTACards
1. Lawyer card — "I'm a Lawyer" → /register?role=lawyer
2. Client card — "I Need Legal Help" → /register?role=client

### HowItWorksSection
1. Section label ("How it works")
2. 3 steps with number, icon, title, one-line description
3. No CTA — this section informs, doesn't convert

### StatsSection
Activity metrics (not user counts):
1. Documents Generated — "5,000+"
2. Hours Saved — "1,200+"
3. Cases Managed — "300+"
4. Legal Professionals — "100+"

### PricingTeaserSection
1. Section headline
2. 3 plan cards: Free / Pro / Firm
3. "View full pricing" link → /plans

## User Flows

### Lawyer landing and signing up
1. Lands on `/`
2. Reads headline — "Attorney AI" resonates
3. Sees "I'm a Lawyer" card in hero dual-CTA
4. Clicks → `/register?role=lawyer`
5. Completes lawyer onboarding (KYC flow)

### Client seeking help
1. Lands on `/`
2. Reads headline — "Faster, Smarter Legal Assistance"
3. Sees "I Need Legal Help" card
4. Clicks → `/register?role=client`
5. Completes client intake flow

### Undecided visitor
1. Lands on `/`
2. Scrolls through How It Works, Audience, Why Choose
3. Reads testimonials
4. Sees pricing teaser → clicks "View full pricing"
5. Returns, clicks a CTA

## Naming Conventions

| Concept | Label in UI | Notes |
|---------|-------------|-------|
| Lawyer signup | "I'm a Lawyer" | Active, first-person |
| Client signup | "I Need Legal Help" | Problem-framed, not "I'm a Client" |
| Platform name | "Attorney AI" | Always two words, no hyphen |
| Pricing page | "Pricing" in nav, "View full pricing" in teaser | Consistent |
| How it works | "How It Works" | Title case |

## URL Strategy

- `/` — landing page
- `/register?role=lawyer` — lawyer signup (dual CTA target)
- `/register?role=client` — client signup (dual CTA target)
- `/plans` — full pricing page
- `/features` — features detail page
- `/login` — existing login
