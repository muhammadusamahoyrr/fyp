'use client';
import ProtectedRoute from '@/components/shared/ProtectedRoute';

export default function ClientLayout({ children }) {
  return <ProtectedRoute allowedRoles={['client']}>{children}</ProtectedRoute>;
}
