'use client';
import { useEffect } from 'react';
import Lenis from 'lenis';

export default function LenisProvider({ children }) {
  useEffect(() => {
    const lenis = new Lenis({ lerp: 0.1, smoothWheel: true, syncTouch: true, touchMultiplier: 2 });

    // Integrate with GSAP ScrollTrigger when present (Landing page uses it)
    let gsapLoaded = false;
    try {
      const { gsap } = require('gsap');
      const { ScrollTrigger } = require('gsap/ScrollTrigger');
      if (gsap && ScrollTrigger) {
        gsapLoaded = true;
        lenis.on('scroll', ScrollTrigger.update);
        const tick = (time) => lenis.raf(time * 1000);
        gsap.ticker.add(tick);
        gsap.ticker.lagSmoothing(0);
        return () => {
          lenis.destroy();
          lenis.off('scroll', ScrollTrigger.update);
          gsap.ticker.remove(tick);
        };
      }
    } catch {}

    if (!gsapLoaded) {
      let raf;
      const loop = (time) => { lenis.raf(time); raf = requestAnimationFrame(loop); };
      raf = requestAnimationFrame(loop);
      return () => { lenis.destroy(); cancelAnimationFrame(raf); };
    }
  }, []);

  return <>{children}</>;
}
