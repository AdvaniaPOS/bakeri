import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useEffect, useState } from 'react';

const API_BASE = '/api/v1';

export default function PortalLayout() {
  const { user, logout, tenant } = useAuth();
  const navigate = useNavigate();
  const [me, setMe] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    fetch(`${API_BASE}/portal/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : null)
      .then(setMe)
      .catch(() => {});
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-amber-50 flex flex-col">
      <header className="bg-white shadow-sm border-b border-amber-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-2xl">🥖</div>
            <div>
              <div className="font-semibold text-amber-900">
                {me?.tenant_name || tenant?.name || 'Bestillingsportal'}
              </div>
              <div className="text-xs text-amber-700">
                {me?.main_customer?.name || user?.email}
              </div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="text-sm text-amber-800 hover:text-amber-900 underline"
          >
            Logg ut
          </button>
        </div>
        <nav className="max-w-5xl mx-auto px-4 flex gap-1 -mb-px">
          {[
            { to: '/portal', label: 'Mine bestillinger', end: true },
            { to: '/portal/ny', label: 'Ny bestilling' },
            { to: '/portal/historikk', label: 'Historikk' },
          ].map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'border-amber-600 text-amber-900'
                    : 'border-transparent text-gray-600 hover:text-amber-800'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-6">
        <Outlet context={{ me, refreshMe: () => {
          const token = localStorage.getItem('access_token');
          if (!token) return;
          fetch(`${API_BASE}/portal/me`, { headers: { Authorization: `Bearer ${token}` }})
            .then(r => r.ok ? r.json() : null).then(setMe);
        }}} />
      </main>
      <footer className="text-center text-xs text-amber-700 py-4">
        Bestillingsportal · Cutoff er kl. 10:00 dagen før levering
      </footer>
    </div>
  );
}
