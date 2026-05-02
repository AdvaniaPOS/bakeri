/**
 * Login page for bakery order system.
 * 
 * Supports:
 * - Email/password login
 * - New tenant registration
 * - Password visibility toggle
 */
import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Sun, Moon } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { getStoredTheme, applyTheme } from '../theme';

export default function Login() {
  const navigate = useNavigate();
  const { login, loading, error } = useAuth();
  
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [twoFactorRequired, setTwoFactorRequired] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [localError, setLocalError] = useState(null);
  const [theme, setTheme] = useState(getStoredTheme);
  useEffect(() => { applyTheme(theme); }, [theme]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLocalError(null);

    if (!email || !password) {
      setLocalError('Vennligst fyll ut alle feltene');
      return;
    }

    const result = await login(email, password, totpCode || undefined);

    if (result.success) {
      navigate('/');
    } else if (result.twoFactorRequired) {
      setTwoFactorRequired(true);
      setLocalError('Skriv inn 2FA-koden fra autentiseringsappen din');
    } else {
      setLocalError(result.error);
    }
  };

  return (
    <div className="min-h-screen app-main flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8 relative">
      <button
        onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
        className="absolute top-4 right-4 p-2 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-200/60"
        title={theme === 'dark' ? 'Bytt til lyst tema' : 'Bytt til mørkt tema'}
        aria-label="Bytt tema"
      >
        {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>
      <div className="max-w-md w-full">
        {/* Logo and title */}
        <div className="text-center mb-6">
          <div className="mx-auto h-12 w-12 bg-amber-600 rounded-md flex items-center justify-center mb-3">
            <svg 
              className="h-7 w-7 text-white" 
              fill="none" 
              viewBox="0 0 24 24" 
              stroke="currentColor"
            >
              <path 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                strokeWidth={2} 
                d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" 
              />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-gray-900">Advania Bakeri</h1>
          <p className="mt-1 text-sm text-gray-500">Logg inn for å fortsette</p>
        </div>

        {/* Login form */}
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error message */}
            {(localError || error) && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
                {localError || error}
              </div>
            )}

            {/* Email/username field */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                E-post eller brukernavn
              </label>
              <input
                id="email"
                name="email"
                type="text"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input w-full"
                placeholder="din@epost.no eller brukernavn"
              />
            </div>

            {/* Password field */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                Passord
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input w-full pr-10"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700"
                >
                  {showPassword ? (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {/* 2FA-kode (vises kun når server krever det) */}
            {twoFactorRequired && (
              <div>
                <label htmlFor="totp" className="block text-sm font-medium text-gray-700 mb-1">
                  2FA-kode
                </label>
                <input
                  id="totp"
                  name="totp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  className="input w-full tracking-widest text-center font-mono"
                  placeholder="123456"
                  autoFocus
                />
                <p className="text-xs text-gray-500 mt-1">6-sifret kode fra autentiseringsappen din</p>
              </div>
            )}

            {/* Remember me & Forgot password */}
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <input
                  id="remember-me"
                  name="remember-me"
                  type="checkbox"
                  className="h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                />
                <label htmlFor="remember-me" className="ml-2 block text-sm text-gray-700">
                  Husk meg
                </label>
              </div>
              <a href="/glemt-passord" className="text-sm text-amber-600 hover:text-amber-700">
                Glemt passord?
              </a>
            </div>

            {/* Submit button */}
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="flex items-center justify-center">
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Logger inn...
                </span>
              ) : (
                'Logg inn'
              )}
            </button>
          </form>

          {/* Register link */}
          <div className="mt-6 text-center">
            <p className="text-sm text-gray-600">
              Har du ikke en konto?{' '}
              <Link to="/register" className="text-amber-600 hover:text-amber-700 font-medium">
                Registrer nytt bakeri
              </Link>
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="mt-8 text-center text-sm text-gray-500">
          © 2026 Advania Bakeri. Alle rettigheter reservert.
        </p>
      </div>
    </div>
  );
}
