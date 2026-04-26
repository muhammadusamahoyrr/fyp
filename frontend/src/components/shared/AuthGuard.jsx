'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

export default function AuthGuard({ requiredRole, children }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const role = localStorage.getItem('aai-role');
      if (!role) { router.replace('/login'); return; }
      if (requiredRole && role !== requiredRole) {
        router.replace(role === 'admin' ? '/admin' : (role === 'lawyer' ? '/lawyer' : '/dashboard'));
        return;
      }
    } catch {}
    setReady(true);
  }, []);

  if (!ready) return null;
  return <>{children}</>;
}
