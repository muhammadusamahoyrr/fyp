'use client';
import { useState } from 'react';
import Dashboard from '@/components/client/Dashboard.jsx';

export default function Page() {
  const [isDark, setIsDark] = useState(true);
  const toggleTheme = () => setIsDark(prev => !prev);
  
  return <Dashboard isDark={isDark} toggleTheme={toggleTheme} />;
}
