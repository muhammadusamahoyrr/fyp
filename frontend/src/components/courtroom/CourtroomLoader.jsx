'use client';

import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';

const CourtroomIntro = dynamic(
  () => import('./CourtroomIntro'),
  {
    ssr: false,
    loading: () => (
      <div
        style={{
          width: '100vw',
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#0A0C10',
          color: '#D4AF37',
          fontFamily: 'serif',
          gap: '24px',
        }}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.2, repeat: Infinity, repeatType: 'reverse' }}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px'
          }}
        >
          <div
            style={{
              fontSize: '0.65rem',
              letterSpacing: '0.45em',
              textTransform: 'uppercase',
              color: '#8B8B85',
              fontWeight: 700
            }}
          >
            Attorney.AI · Pakistan
          </div>
          <div
            style={{
              fontSize: '1.0rem',
              letterSpacing: '0.25em',
              textTransform: 'uppercase',
              fontWeight: 300,
              borderTop: '1px solid rgba(212,175,55,0.2)',
              paddingTop: '12px'
            }}
          >
            High Court Simulation
          </div>
          <div style={{ fontSize: '0.58rem', letterSpacing: '0.18em', color: 'rgba(212,175,55,0.45)', marginTop: 6 }}>
            Islamabad · Civil Division
          </div>
        </motion.div>
        
        <div style={{
          width: '140px',
          height: '1px',
          background: 'rgba(212,175,55,0.1)',
          position: 'relative',
          overflow: 'hidden'
        }}>
          <motion.div
            initial={{ x: '-100%' }}
            animate={{ x: '100%' }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
            style={{
              width: '100%',
              height: '100%',
              background: '#D4AF37',
              position: 'absolute'
            }}
          />
        </div>
      </div>
    ),
  }
);

export default function CourtroomLoader() {
  return <CourtroomIntro />;
}
