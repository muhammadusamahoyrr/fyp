'use client';
import ProtectedRoute from '@/components/shared/ProtectedRoute';

export default function LawyerLayout({ children }) {
  return <ProtectedRoute allowedRoles={['lawyer']}>{children}</ProtectedRoute>;
}
