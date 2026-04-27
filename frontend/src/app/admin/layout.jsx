'use client';
import AuthGuard from '@/components/shared/AuthGuard';

export default function AdminLayout({ children }) {
  return <AuthGuard requiredRole="admin">{children}</AuthGuard>;
}
