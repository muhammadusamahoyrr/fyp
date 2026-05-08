'use client';
import ProtectedRoute from '@/components/shared/ProtectedRoute';

export default function AdminLayout({ children }) {
  return <ProtectedRoute allowedRoles={['admin']}>{children}</ProtectedRoute>;
}
