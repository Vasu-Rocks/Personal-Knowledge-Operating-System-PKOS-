import React, { useState } from 'react';
import { useAuth } from '../context/useAuth';
import { Lock, User, KeyRound, AlertCircle } from 'lucide-react';

export default function AuthView() {
  const { login, register } = useAuth();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      if (isLogin) {
        // Log in using the email state, which holds either the email address or the username
        await login(email, password);
      } else {
        await register(email, username, name, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleMode = () => {
    setIsLogin(!isLogin);
    setError(null);
    // Flush state values to maintain a clean form slate
    setEmail('');
    setUsername('');
    setName('');
    setPassword('');
  };

  return (
    <div style={{
      display: 'flex', width: '100vw', height: '100vh', 
      alignItems: 'center', justifyContent: 'center',
      background: 'radial-gradient(ellipse at top, hsla(217, 91%, 60%, 0.15), transparent 80%), var(--bg-core)'
    }}>
      <div className="glass-panel" style={{
        padding: '40px', width: '380px', borderRadius: 'var(--radius-lg)',
        display: 'flex', flexDirection: 'column', gap: '24px'
      }}>
        
        <div style={{ textAlign: 'center' }}>
          <div style={{
            background: 'var(--glass-bg)', width: '64px', height: '64px',
            borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px', border: 'var(--pane-border)'
          }}>
            {isLogin ? <Lock size={28} color="var(--accent-blue)" /> : <KeyRound size={28} color="var(--accent-blue)" />}
          </div>
          <h2 style={{ fontSize: '24px', fontWeight: '600', marginBottom: '8px' }}>
            {isLogin ? 'Log in to PKOS' : 'Create your account'}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px' }}>
            {isLogin ? 'Your private AI for your own documents.' : 'Your documents and chats stay on this computer.'}
          </p>
        </div>

        {error && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)',
            padding: '12px', borderRadius: 'var(--radius-sm)', display: 'flex', gap: '12px',
            alignItems: 'center', color: '#ef4444', fontSize: '13px'
          }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Email / Identification Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              {isLogin ? 'Email or username' : 'Email'}
            </label>
            <div style={{
              display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)',
              border: 'var(--pane-border)', borderRadius: 'var(--radius-sm)', padding: '0 12px'
            }}>
              <User size={16} color="var(--text-muted)" />
              <input 
                type={isLogin ? "text" : "email"} 
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder={isLogin ? "user@gmail.com or username" : "user@gmail.com"} 
                required spellCheck="false"
                style={{ padding: '12px', width: '100%', fontSize: '14px' }} 
              />
            </div>
          </div>

          {/* Full Name Field (Register Only) */}
          {!isLogin && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Name</label>
              <div style={{
                display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)',
                border: 'var(--pane-border)', borderRadius: 'var(--radius-sm)', padding: '0 12px'
              }}>
                <User size={16} color="var(--text-muted)" />
                <input 
                  type="text" 
                  value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="John Doe" required spellCheck="false" maxLength={100}
                  style={{ padding: '12px', width: '100%', fontSize: '14px' }} 
                />
              </div>
            </div>
          )}

          {/* Username Field (Register Only) */}
          {!isLogin && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Username</label>
              <div style={{
                display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)',
                border: 'var(--pane-border)', borderRadius: 'var(--radius-sm)', padding: '0 12px'
              }}>
                <User size={16} color="var(--text-muted)" />
                <input 
                  type="text" 
                  value={username} onChange={(e) => setUsername(e.target.value)}
                  placeholder="johndoe" required spellCheck="false"
                  minLength={3} maxLength={32} pattern="[A-Za-z0-9_.\-]{3,32}"
                  title="3-32 characters: letters, digits, _ . or -"
                  style={{ padding: '12px', width: '100%', fontSize: '14px' }}
                />
              </div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>3-32 characters: letters, digits, _ . -</span>
            </div>
          )}
          
          {/* Passkey Field */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Password</label>
            <div style={{
              display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)',
              border: 'var(--pane-border)', borderRadius: 'var(--radius-sm)', padding: '0 12px'
            }}>
              <Lock size={16} color="var(--text-muted)" />
              <input 
                type="password" 
                value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••" required
                minLength={isLogin ? undefined : 8}
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                style={{ padding: '12px', width: '100%', fontSize: '14px', letterSpacing: '2px' }}
              />
            </div>
            {!isLogin && <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>At least 8 characters</span>}
          </div>

          <button 
            type="submit" 
            disabled={isLoading}
            style={{
              background: 'var(--accent-blue)', color: 'white', padding: '12px',
              borderRadius: 'var(--radius-sm)', fontWeight: '500', fontSize: '14px',
              marginTop: '8px', opacity: isLoading ? 0.7 : 1
            }}
          >
            {isLoading ? 'Please wait...' : (isLogin ? 'Log in' : 'Create account')}
          </button>
        </form>

        <div style={{ textAlign: 'center', fontSize: '13px', color: 'var(--text-muted)' }}>
          {isLogin ? 'No account yet? ' : 'Already have an account? '}
          <button type="button" onClick={toggleMode}
            style={{ color: 'var(--accent-blue)', cursor: 'pointer', fontWeight: '500', fontSize: '13px' }}>
            {isLogin ? 'Create one' : 'Log in'}
          </button>
        </div>
      </div>
    </div>
  );
}
