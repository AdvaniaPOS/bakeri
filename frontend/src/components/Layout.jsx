import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { getStoredTheme, applyTheme } from '../theme';
import NotificationBell from './NotificationBell';
import advaniaLogo from '../assets/advania-logo.svg';
import { 
  LayoutDashboard, 
  Package, 
  Users, 
  ShoppingCart, 
  FileText,
  Settings,
  LogOut,
  Croissant,
  Truck,
  ClipboardList,
  MapPin,
  Building2,
  CheckCircle2,
  TrendingDown,
  History,
  Activity,
  Moon,
  Sun,
  Menu,
  X,
  ShieldAlert
} from 'lucide-react';

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Produkter', href: '/produkter', icon: Package },
  { name: 'Kunder', href: '/kunder', icon: Users },
  { name: 'Bestillinger', href: '/bestillinger', icon: ShoppingCart },
  { name: 'Maler', href: '/maler', icon: FileText, feature: 'templates' },
  { name: 'Ruter', href: '/ruter', icon: Truck, feature: 'routes' },
  { name: 'Produksjon', href: '/produksjon', icon: ClipboardList, feature: 'production' },
  { name: 'Svinn & faktisk', href: '/produksjon/logg', icon: TrendingDown, feature: 'production' },
  { name: 'Kjøreliste', href: '/kjoreliste', icon: MapPin, feature: 'routes' },
  { name: 'Sjåfør', href: '/sjafor', icon: CheckCircle2, feature: 'driver_app' },
  { name: 'Innstillinger', href: '/innstillinger', icon: Settings },
  { name: 'Audit-logg', href: '/audit-logg', icon: History, roles: ['SUPER_ADMIN', 'TENANT_ADMIN', 'MANAGER'] },
];

const superAdminNavigation = [
  { name: 'Kunder / Portaler', href: '/admin/tenants', icon: Building2 },
  { name: 'Systemstatus', href: '/status', icon: Activity },
];

export default function Layout() {
  const { user, tenant, logout, notification, dismissNotification, hasFeature, isImpersonating, endImpersonation } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const role = (user?.role || '').toLowerCase();
  // SUPER_ADMIN i master-modus (ikke impersonert) skal kun se admin-meny.
  const isSuperAdminMaster = role === 'super_admin' && !isImpersonating;

  // Mobil-meny (drawer)
  const [mobileOpen, setMobileOpen] = useState(false);
  // Lukk drawer ved navigasjon
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  // Tema (lys/morkt) — persistert i localStorage, sentralt handtert
  const [theme, setTheme] = useState(getStoredTheme);
  useEffect(() => { applyTheme(theme); }, [theme]);
  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  // Auto-dismiss toast etter 5 sek
  useEffect(() => {
    if (!notification) return;
    const t = setTimeout(() => dismissNotification(), 5000);
    return () => clearTimeout(t);
  }, [notification, dismissNotification]);
  
  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };
  
  // Get user initials for avatar
  const getInitials = (name) => {
    if (!name) return '??';
    const parts = name.split(' ');
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  };
  
  // Get role display name (case-insensitive)
  const getRoleDisplay = (role) => {
    const key = (role || '').toUpperCase();
    const roleMap = {
      'SUPER_ADMIN': 'Super Admin',
      'TENANT_ADMIN': 'Administrator',
      'MANAGER': 'Leder',
      'DRIVER': 'Sjåfør',
      'VIEWER': 'Leser'
    };
    return roleMap[key] || role;
  };

  return (
    <div className="min-h-screen flex app-bg">
      {/* Mobil topp-bar (vises kun under lg) */}
      <header className="lg:hidden fixed top-0 inset-x-0 z-30 flex items-center justify-between px-3 h-12 app-sidebar border-b border-white/5">
        <button
          onClick={() => setMobileOpen(true)}
          className="p-2 -ml-2 rounded-md text-gray-300 hover:text-white hover:bg-white/10"
          aria-label="Åpne meny"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-2 min-w-0">
          <img src={advaniaLogo} alt="Advania" className="h-5 w-auto flex-shrink-0" />
          <span className="text-sm font-semibold text-white/90 truncate">{tenant?.name || 'Bakeri'}</span>
        </div>
        <div className="flex items-center gap-1">
          {!isSuperAdminMaster && <NotificationBell />}
          <button
            onClick={toggleTheme}
            className="p-2 -mr-2 rounded-md text-gray-300 hover:text-white hover:bg-white/10"
            aria-label="Bytt tema"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* Bakteppe naar mobil-drawer er aapen */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={`w-60 flex flex-col app-sidebar fixed inset-y-0 left-0 z-50 transform transition-transform duration-200 ease-out lg:static lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        {/* Advania-logo */}
        <div className="px-4 pt-4 pb-2">
          <img src={advaniaLogo} alt="Advania" className="h-6 w-auto" />
        </div>

        {/* Tenant + verktøy */}
        <div className="px-4 pb-3 flex items-center gap-2.5 border-b border-white/5">
          {tenant?.logo_url ? (
            <img
              src={tenant.logo_url}
              alt=""
              className="w-7 h-7 rounded-md object-cover shadow-sm"
            />
          ) : (
            <div
              className="w-7 h-7 rounded-md flex items-center justify-center shadow-sm"
              style={{ backgroundColor: tenant?.primary_color || '#4f46e5' }}
            >
              <Croissant className="w-4 h-4 text-white" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold text-white truncate" title={tenant?.name || 'Bakeri'}>
              {tenant?.name || 'Bakeri'}
            </h1>
          </div>
          <button
            onClick={toggleTheme}
            className="hidden lg:inline-flex p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
            title={theme === 'dark' ? 'Bytt til lyst tema' : 'Bytt til mørkt tema'}
            aria-label="Bytt tema"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          {!isSuperAdminMaster && (
            <div className="hidden lg:block">
              <NotificationBell />
            </div>
          )}
          <button
            onClick={() => setMobileOpen(false)}
            className="lg:hidden p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/10"
            aria-label="Lukk meny"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 pt-1 space-y-0.5 overflow-y-auto">
          {!isSuperAdminMaster && navigation.filter(item => {
            if (item.feature && !hasFeature(item.feature)) return false;
            if (item.roles && !item.roles.includes((user?.role || '').toUpperCase())) return false;
            return true;
          }).map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              end={item.href === '/'}
              className={({ isActive }) =>
                `sidebar-link ${isActive ? 'active' : ''}`
              }
            >
              <item.icon className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">{item.name}</span>
            </NavLink>
          ))}
          {role === 'super_admin' && (
            <>
              {!isSuperAdminMaster && <div className="sidebar-section-label">Super-admin</div>}
              {superAdminNavigation.map((item) => (
                <NavLink
                  key={item.name}
                  to={item.href}
                  className={({ isActive }) =>
                    `sidebar-link ${isActive ? 'active' : ''}`
                  }
                >
                  <item.icon className="w-4 h-4 flex-shrink-0" />
                  <span className="truncate">{item.name}</span>
                </NavLink>
              ))}
            </>
          )}
        </nav>

        {/* User section */}
        <div className="p-2 border-t border-white/5">
          <div className="flex items-center gap-2 px-2 py-2 rounded-md hover:bg-white/10 transition-colors">
            <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0" style={{ backgroundColor: 'rgba(99,102,241,0.18)' }}>
              <span className="text-xs font-semibold" style={{ color: '#a5b4fc' }}>
                {getInitials(user?.name)}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate" title={user?.name}>
                {user?.name || 'Bruker'}
              </p>
              <p className="text-xs text-gray-400 truncate">
                {getRoleDisplay(user?.role)}
              </p>
            </div>
            <button
              onClick={handleLogout}
              className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded transition-colors"
              title="Logg ut"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto app-main pt-12 lg:pt-0">
        {isImpersonating && (
          <div className="sticky top-0 z-30 bg-amber-500 text-white px-4 py-2 flex items-center justify-between gap-3 text-sm shadow-md">
            <div className="flex items-center gap-2 min-w-0">
              <ShieldAlert className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">
                Supportøkt: du er logget inn som <strong>{tenant?.name || 'kunde'}</strong>
              </span>
            </div>
            <button
              onClick={() => endImpersonation()}
              className="flex-shrink-0 bg-white text-amber-700 hover:bg-amber-50 px-3 py-1 rounded-md text-xs font-semibold"
            >
              Avslutt supportøkt
            </button>
          </div>
        )}
        <div className="lg:border-l border-gray-200 min-h-full app-divider">
          <Outlet />
        </div>
      </main>

      {/* Toast varsler (periodeplan-sjekk osv.) */}
      {notification && (
        <div
          role="status"
          className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-white border border-gray-200 shadow-lg rounded-lg px-4 py-3 min-w-[260px] animate-in slide-in-from-bottom-4"
        >
          <CheckCircle2
            className={`w-5 h-5 flex-shrink-0 ${
              notification.type === 'success' ? 'text-green-600' : 'text-blue-600'
            }`}
          />
          <p className="text-sm text-gray-800 flex-1">{notification.message}</p>
          <button
            onClick={dismissNotification}
            className="text-gray-400 hover:text-gray-700"
            aria-label="Lukk varsel"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
