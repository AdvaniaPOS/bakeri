/**
 * Authentication Context for multi-tenant bakery order system.
 * 
 * Provides:
 * - User authentication state
 * - Login/logout functions
 * - Token management
 * - Protected route wrapper
 */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext(null);

const API_BASE = '/api/v1';

// Token storage keys
const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';
const TENANT_KEY = 'tenant';

async function parseResponseSafely(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [tenant, setTenant] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null); // { type, message }

  // Clear all auth data
  const clearAuthData = useCallback(() => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TENANT_KEY);
    setUser(null);
    setTenant(null);
  }, []);

  // Trigger periodeplan-horisont-sjekk i bakgrunnen.
  // Backend er idempotent per dag, så det er trygt å kalle ofte.
  // Klient-throttling: maks én gang per dag per nettleser-økt (sessionStorage).
  const triggerHorizonCheck = useCallback((tokenOverride) => {
    const token = tokenOverride || localStorage.getItem(ACCESS_TOKEN_KEY);
    if (!token) return;

    const today = new Date().toISOString().slice(0, 10);
    const lastClientCheck = sessionStorage.getItem('horizon_check_date');
    if (lastClientCheck === today) {
      return; // Allerede forsøkt i denne økten i dag
    }
    sessionStorage.setItem('horizon_check_date', today);

    fetch(`${API_BASE}/orders/ensure-horizon`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
      .then(async (r) => {
        if (!r.ok) return;
        const summary = await parseResponseSafely(r);
        if (!summary) return;

        if (summary.status === 'scheduled') {
          // Vent litt og poll status — gi backend tid til å fullføre genereringen.
          setTimeout(async () => {
            try {
              const statusResp = await fetch(`${API_BASE}/orders/horizon-status`, {
                headers: { 'Authorization': `Bearer ${token}` },
              });
              if (statusResp.ok) {
                const status = await parseResponseSafely(statusResp);
                if (status?.checked_today) {
                  setNotification({
                    type: 'success',
                    message: 'Periodeplaner oppdatert ✓',
                    id: Date.now(),
                  });
                }
              }
            } catch { /* ignore */ }
          }, 3000);
        }
      })
      .catch((e) => console.warn('[ensure-horizon] failed:', e));
  }, []);

  const dismissNotification = useCallback(() => setNotification(null), []);

  // Load stored auth state on mount
  useEffect(() => {
    const storedUser = localStorage.getItem(USER_KEY);
    const storedTenant = localStorage.getItem(TENANT_KEY);
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);

    if (storedUser && storedTenant && accessToken) {
      try {
        setUser(JSON.parse(storedUser));
        setTenant(JSON.parse(storedTenant));
        // Bruker er allerede innlogget (refresh/ny fane) — sjekk horisonten.
        triggerHorizonCheck(accessToken);
      } catch (e) {
        console.error('Failed to parse stored auth data:', e);
        clearAuthData();
      }
    }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Login function
  const login = useCallback(async (email, password) => {
    setError(null);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await parseResponseSafely(response);

      if (!response.ok) {
        throw new Error(data?.detail || 'Login failed');
      }

      if (!data) {
        throw new Error('Server returned an empty response during login');
      }

      // Store tokens and user data
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      localStorage.setItem(TENANT_KEY, JSON.stringify(data.tenant));

      setUser(data.user);
      setTenant(data.tenant);

      // Trigger periodeplan-sjekk for ny økt (token må settes før kall).
      triggerHorizonCheck(data.access_token);

      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  }, []);

  // Register new tenant
  const register = useCallback(async (tenantName, tenantSlug, adminEmail, adminPassword, adminName) => {
    setError(null);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tenant_name: tenantName,
          tenant_slug: tenantSlug,
          admin_email: adminEmail,
          admin_password: adminPassword,
          admin_name: adminName,
        }),
      });

      const data = await parseResponseSafely(response);

      if (!response.ok) {
        throw new Error(data?.detail || 'Registration failed');
      }

      if (!data) {
        throw new Error('Server returned an empty response during registration');
      }

      // Store tokens and user data
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      localStorage.setItem(TENANT_KEY, JSON.stringify(data.tenant));

      setUser(data.user);
      setTenant(data.tenant);

      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  }, []);

  // Logout function
  const logout = useCallback(async () => {
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    
    try {
      // Call logout endpoint to invalidate refresh tokens
      if (accessToken) {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${accessToken}`,
          },
        });
      }
    } catch (err) {
      console.error('Logout API call failed:', err);
    } finally {
      clearAuthData();
    }
  }, [clearAuthData]);

  // Refresh access token
  const refreshAccessToken = useCallback(async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    
    if (!refreshToken) {
      clearAuthData();
      return null;
    }

    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        throw new Error('Token refresh failed');
      }

      const data = await parseResponseSafely(response);
      if (!data) {
        throw new Error('Server returned an empty response during token refresh');
      }
      
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      
      return data.access_token;
    } catch (err) {
      console.error('Token refresh failed:', err);
      clearAuthData();
      return null;
    }
  }, [clearAuthData]);

  // Get access token (with auto-refresh if needed)
  const getAccessToken = useCallback(() => {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }, []);

  // Authenticated fetch wrapper
  const authFetch = useCallback(async (url, options = {}) => {
    const accessToken = getAccessToken();
    
    if (!accessToken) {
      throw new Error('Not authenticated');
    }

    const headers = {
      ...options.headers,
      'Authorization': `Bearer ${accessToken}`,
    };

    if (options.body && typeof options.body === 'object') {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    let response = await fetch(url, { ...options, headers });

    // If unauthorized, try to refresh token
    if (response.status === 401) {
      const newToken = await refreshAccessToken();
      
      if (newToken) {
        headers['Authorization'] = `Bearer ${newToken}`;
        response = await fetch(url, { ...options, headers });
      } else {
        throw new Error('Session expired. Please login again.');
      }
    }

    return response;
  }, [getAccessToken, refreshAccessToken]);

  // Check if user has any of the required roles
  const hasRole = useCallback((...roles) => {
    if (!user) return false;
    return roles.includes(user.role);
  }, [user]);

  // Check if user is admin
  const isAdmin = useCallback(() => {
    return hasRole('SUPER_ADMIN', 'TENANT_ADMIN');
  }, [hasRole]);

  const value = {
    user,
    tenant,
    loading,
    error,
    isAuthenticated: !!user,
    login,
    register,
    logout,
    getAccessToken,
    authFetch,
    hasRole,
    isAdmin,
    refreshAccessToken,
    notification,
    dismissNotification,
    triggerHorizonCheck,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// Hook to use auth context
export function useAuth() {
  const context = useContext(AuthContext);
  
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  
  return context;
}

// Protected route wrapper component
export function ProtectedRoute({ children, requiredRoles = [] }) {
  const { isAuthenticated, loading, hasRole } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-amber-600"></div>
      </div>
    );
  }

  if (!isAuthenticated) {
    // Redirect to login
    window.location.href = '/login';
    return null;
  }

  if (requiredRoles.length > 0 && !hasRole(...requiredRoles)) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Ingen tilgang</h1>
          <p className="text-gray-600">Du har ikke tilgang til denne siden.</p>
        </div>
      </div>
    );
  }

  return children;
}

export default AuthContext;
