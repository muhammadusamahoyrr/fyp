'use client';
import AuthGuard from '@/components/shared/AuthGuard';

export default function LawyerLayout({ children }) {
  return <AuthGuard requiredRole="lawyer">{children}</AuthGuard>;
}
