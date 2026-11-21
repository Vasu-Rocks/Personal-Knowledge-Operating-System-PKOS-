import React, { useState, useEffect, useCallback } from 'react';
import { API } from '../api';
import { AuthContext } from './useAuth';

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(localStorage.getItem('pkos_token') || null);
  const [profile, setProfile] = useState(null);
  const isAuthenticated = !!token;
  const user = token ? profile : null; // derived, so logging out needs no extra state reset

  const logout = useCallback(() => {
    setToken(null);
  }, []);

  useEffect(() => {
    if (!token) {
      localStorage.removeItem('pkos_token');
      return;
    }
    localStorage.setItem('pkos_token', token);
    (async () => {
      try {
        const res = await fetch(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } });
        if (res.ok) {
          setProfile(await res.json());
        } else if (res.status === 401) {
          logout();
        }
      } catch (err) {
        console.error("Failed to fetch user profile details:", err);
      }
    })();
  }, [token, logout]);

  // FastAPI sends `detail` as a string for our own errors but as a list of objects for validation errors.
  const errorMessage = async (response, fallback) => {
    try {
      const { detail } = await response.json();
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail) && detail.length) return detail.map((d) => d.msg).join('; ');
    } catch { /* body was not JSON */ }
    return fallback;
  };

  const login = async (usernameOrEmail, password) => {
    // URL Encoded form mapping natively to FastAPI OAuth2PasswordRequestForm
    const formData = new URLSearchParams();
    formData.append('username', usernameOrEmail);
    formData.append('password', password);

    const response = await fetch(`${API}/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData,
    });

    if (!response.ok) {
        throw new Error(await errorMessage(response, 'Login failed'));
    }

    const data = await response.json();
    setToken(data.access_token);
  };

  const register = async (email, username, name, password) => {
    const response = await fetch(`${API}/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, username, name, password }),
    });

    if (!response.ok) {
        throw new Error(await errorMessage(response, 'Registration failed'));
    }

    // Extract the token directly from the successful registration response
    // This eliminates the redundant second /login network call
    const data = await response.json();
    setToken(data.access_token);
  };

  // Stable identity (changes only when the token does) so effects can depend on it.
  const authFetch = useCallback(async (url, options = {}) => {
    const headers = {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    };
    return fetch(url, { ...options, headers });
  }, [token]);

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, register, logout, authFetch }}>
      {children}
    </AuthContext.Provider>
  );
};
