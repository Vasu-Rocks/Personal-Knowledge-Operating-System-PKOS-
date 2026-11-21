import React, { createContext, useContext, useState, useEffect } from 'react';
import { API } from '../api';

const AuthContext = createContext();

export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(localStorage.getItem('pkos_token') || null);
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(!!token);

  const fetchCurrentUser = async (currentToken) => {
    try {
      const res = await fetch(`${API}/me`, {
        headers: {
          Authorization: `Bearer ${currentToken}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else if (res.status === 401) {
        logout();
      }
    } catch (err) {
      console.error("Failed to fetch user profile details:", err);
    }
  };

  useEffect(() => {
    if (token) {
      localStorage.setItem('pkos_token', token);
      setIsAuthenticated(true);
      fetchCurrentUser(token);
    } else {
      localStorage.removeItem('pkos_token');
      setIsAuthenticated(false);
      setUser(null);
    }
  }, [token]);

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

  const logout = () => {
    setToken(null);
  };

  const authFetch = async (url, options = {}) => {
    const headers = {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    };
    return fetch(url, { ...options, headers });
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, register, logout, authFetch }}>
      {children}
    </AuthContext.Provider>
  );
};
