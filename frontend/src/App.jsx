import React from 'react';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import AuthView from './components/AuthView';
import Dashboard from './components/Dashboard';

function AppContent() {
  const { isAuthenticated } = useAuth();
  
  // Conditionally render the entire OS depending on the cryptographic boundary
  return isAuthenticated ? <Dashboard /> : <AuthView />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
