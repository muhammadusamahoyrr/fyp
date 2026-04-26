'use client';
import React from 'react';

const ic = (c, children) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
    stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    style={{ display: 'inline-block', flexShrink: 0 }}>
    {children}
  </svg>
);

export const Ic = {
  arrowL: (c) => ic(c, <><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></>),
  arrowR: (c) => ic(c, <><path d="M5 12h14" /><path d="M12 5l7 7-7 7" /></>),
  shield: (c) => ic(c, <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />),
  mail:   (c) => ic(c, <><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M22 7l-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" /></>),
  lock:   (c) => ic(c, <><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>),
  eye:    (c) => ic(c, <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>),
  eyeOff: (c) => ic(c, <><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" /><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" /><line x1="1" y1="1" x2="23" y2="23" /></>),
  user:   (c) => ic(c, <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>),
  phone:  (c) => ic(c, <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.59 1h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.56a16 16 0 0 0 6.29 6.29l.43-.38a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />),
  cert:   (c) => ic(c, <><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /><path d="M9 10l2 2 4-4" /></>),
  scale:  (c) => ic(c, <><path d="M12 3v18M6 6l-3 6h6L6 6zM18 6l-3 6h6L18 6zM3 21h18" /></>),
  client: (c) => ic(c, <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>),
};
