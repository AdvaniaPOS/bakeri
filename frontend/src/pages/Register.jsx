/**
 * Registration page for new bakery tenants.
 * 
 * Creates a new tenant (bakery organization) with an admin user.
 */
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function Register() {
  const navigate = useNavigate();
  const { register, loading } = useAuth();
  
  const [formData, setFormData] = useState({
    tenantName: '',
    tenantSlug: '',
    adminName: '',
    adminEmail: '',
    adminPassword: '',
    confirmPassword: '',
  });
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(null);
  const [step, setStep] = useState(1); // 1 = bakery info, 2 = admin info

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    
    // Auto-generate slug from tenant name
    if (name === 'tenantName') {
      const slug = value
        .toLowerCase()
        .replace(/[æ]/g, 'ae')
        .replace(/[ø]/g, 'o')
        .replace(/[å]/g, 'a')
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
      setFormData(prev => ({ ...prev, tenantSlug: slug }));
    }
  };

  const validateStep1 = () => {
    if (!formData.tenantName.trim()) {
      setError('Vennligst oppgi bakeriets navn');
      return false;
    }
    if (!formData.tenantSlug.trim()) {
      setError('Vennligst oppgi en URL-vennlig ID');
      return false;
    }
    if (!/^[a-z0-9-]+$/.test(formData.tenantSlug)) {
      setError('URL-ID kan kun inneholde små bokstaver, tall og bindestreker');
      return false;
    }
    return true;
  };

  const validateStep2 = () => {
    if (!formData.adminName.trim()) {
      setError('Vennligst oppgi ditt navn');
      return false;
    }
    if (!formData.adminEmail.trim()) {
      setError('Vennligst oppgi din e-post');
      return false;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.adminEmail)) {
      setError('Vennligst oppgi en gyldig e-postadresse');
      return false;
    }
    if (formData.adminPassword.length < 8) {
      setError('Passordet må være minst 8 tegn');
      return false;
    }
    if (formData.adminPassword !== formData.confirmPassword) {
      setError('Passordene er ikke like');
      return false;
    }
    return true;
  };

  const handleNextStep = () => {
    setError(null);
    if (validateStep1()) {
      setStep(2);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (!validateStep2()) {
      return;
    }

    const result = await register(
      formData.tenantName,
      formData.tenantSlug,
      formData.adminEmail,
      formData.adminPassword,
      formData.adminName
    );

    if (result.success) {
      navigate('/');
    } else {
      setError(result.error);
    }
  };

  return (
    <div className="min-h-screen bg-[#f6f6f7] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
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
          <h1 className="text-xl font-semibold text-gray-900">Registrer nytt bakeri</h1>
          <p className="mt-1 text-sm text-gray-500">
            {step === 1 ? 'Steg 1/2: Om bakeriet' : 'Steg 2/2: Administrator-konto'}
          </p>
        </div>

        {/* Progress bar */}
        <div className="mb-6 flex items-center justify-center">
          <div className="flex items-center">
            <div className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-medium ${
              step >= 1 ? 'bg-amber-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              1
            </div>
            <div className={`w-12 h-0.5 ${step >= 2 ? 'bg-amber-600' : 'bg-gray-200'}`}></div>
            <div className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-medium ${
              step >= 2 ? 'bg-amber-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              2
            </div>
          </div>
        </div>

        {/* Registration form */}
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error message */}
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
                {error}
              </div>
            )}

            {step === 1 ? (
              <>
                {/* Bakery name */}
                <div>
                  <label htmlFor="tenantName" className="block text-sm font-medium text-gray-700 mb-1">
                    Bakeriets navn
                  </label>
                  <input
                    id="tenantName"
                    name="tenantName"
                    type="text"
                    required
                    value={formData.tenantName}
                    onChange={handleChange}
                    className="input w-full"
                    placeholder="F.eks. Lampeland Bakeri"
                  />
                </div>

                {/* Tenant slug */}
                <div>
                  <label htmlFor="tenantSlug" className="block text-sm font-medium text-gray-700 mb-1">
                    URL-vennlig ID
                  </label>
                  <div className="flex">
                    <span className="inline-flex items-center px-3 bg-gray-50 border border-r-0 border-gray-300 rounded-l-lg text-gray-500 text-sm">
                      ordresystem.no/
                    </span>
                    <input
                      id="tenantSlug"
                      name="tenantSlug"
                      type="text"
                      required
                      value={formData.tenantSlug}
                      onChange={handleChange}
                      className="input flex-1 rounded-l-none"
                      placeholder="lampeland-bakeri"
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
                    Kun små bokstaver, tall og bindestreker
                  </p>
                </div>

                <button
                  type="button"
                  onClick={handleNextStep}
                  className="btn-primary w-full justify-center"
                >
                  Neste steg
                </button>
              </>
            ) : (
              <>
                {/* Admin name */}
                <div>
                  <label htmlFor="adminName" className="block text-sm font-medium text-gray-700 mb-1">
                    Ditt navn
                  </label>
                  <input
                    id="adminName"
                    name="adminName"
                    type="text"
                    required
                    value={formData.adminName}
                    onChange={handleChange}
                    className="input w-full"
                    placeholder="Ola Nordmann"
                  />
                </div>

                {/* Admin email */}
                <div>
                  <label htmlFor="adminEmail" className="block text-sm font-medium text-gray-700 mb-1">
                    E-post
                  </label>
                  <input
                    id="adminEmail"
                    name="adminEmail"
                    type="email"
                    required
                    value={formData.adminEmail}
                    onChange={handleChange}
                    className="input w-full"
                    placeholder="ola@bakeri.no"
                  />
                </div>

                {/* Password */}
                <div>
                  <label htmlFor="adminPassword" className="block text-sm font-medium text-gray-700 mb-1">
                    Passord
                  </label>
                  <div className="relative">
                    <input
                      id="adminPassword"
                      name="adminPassword"
                      type={showPassword ? 'text' : 'password'}
                      required
                      value={formData.adminPassword}
                      onChange={handleChange}
                      className="input w-full pr-10"
                      placeholder="Minst 8 tegn"
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

                {/* Confirm password */}
                <div>
                  <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-1">
                    Bekreft passord
                  </label>
                  <input
                    id="confirmPassword"
                    name="confirmPassword"
                    type={showPassword ? 'text' : 'password'}
                    required
                    value={formData.confirmPassword}
                    onChange={handleChange}
                    className="input w-full"
                    placeholder="Gjenta passordet"
                  />
                </div>

                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setStep(1)}
                    className="btn-secondary flex-1 justify-center"
                  >
                    Tilbake
                  </button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="btn-primary flex-1 justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loading ? (
                      <span className="flex items-center justify-center">
                        <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        Oppretter...
                      </span>
                    ) : (
                      'Opprett konto'
                    )}
                  </button>
                </div>
              </>
            )}
          </form>

          {/* Login link */}
          <div className="mt-6 text-center">
            <p className="text-sm text-gray-600">
              Har du allerede en konto?{' '}
              <Link to="/login" className="text-amber-600 hover:text-amber-700 font-medium">
                Logg inn her
              </Link>
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="mt-8 text-center text-sm text-gray-500">
          © 2026 Bakeri Ordresystem. Alle rettigheter reservert.
        </p>
      </div>
    </div>
  );
}
