'use client';
import AuthGuard from '@/components/shared/AuthGuard';

export default function ClientLayout({ children }) {
  return <AuthGuard requiredRole="client">{children}</AuthGuard>;
}
