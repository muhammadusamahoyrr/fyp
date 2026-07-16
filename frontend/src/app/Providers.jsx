'use client';
import { AuthProvider } from '@/context/AuthContext';
import LenisProvider from '@/components/shared/LenisProvider';

export default function Providers({ children }) {
  return (
    <LenisProvider>
      <AuthProvider>{children}</AuthProvider>
    </LenisProvider>
  );
}
