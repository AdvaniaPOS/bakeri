import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, ProtectedRoute, useAuth } from './contexts/AuthContext';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Customers from './pages/Customers';
import Orders from './pages/Orders';
import NewOrder from './pages/NewOrder';
import Templates from './pages/Templates';
import TemplateMatrix from './pages/TemplateMatrix';
import Settings from './pages/Settings';
import RoutesPage from './pages/RoutesPage';
import ProductionReport from './pages/ProductionReport';
import ProductionLog from './pages/ProductionLog';
import DeliveryList from './pages/DeliveryList';
import Driver from './pages/Driver';
import TenantsAdmin from './pages/TenantsAdmin';
import AuditLog from './pages/AuditLog';
import Status from './pages/Status';
import Login from './pages/Login';
import Register from './pages/Register';
import './index.css';

// Redirect authenticated users away from login/register
function PublicRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-amber-600"></div>
      </div>
    );
  }
  
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={
        <PublicRoute>
          <Login />
        </PublicRoute>
      } />
      <Route path="/register" element={
        <PublicRoute>
          <Register />
        </PublicRoute>
      } />
      
      {/* Protected routes */}
      <Route path="/" element={
        <ProtectedRoute>
          <Layout />
        </ProtectedRoute>
      }>
        <Route index element={<Dashboard />} />
        <Route path="produkter" element={<Products />} />
        <Route path="kunder" element={<Customers />} />
        <Route path="bestillinger" element={<Orders />} />
        <Route path="bestillinger/ny" element={<NewOrder />} />
        <Route path="maler" element={<Templates />} />
        <Route path="maler/kunde/:customerId" element={<TemplateMatrix />} />
        <Route path="ruter" element={<RoutesPage />} />
        <Route path="produksjon" element={<ProductionReport />} />
        <Route path="produksjon/logg" element={<ProductionLog />} />
        <Route path="kjoreliste" element={<DeliveryList />} />
        <Route path="sjafor" element={<Driver />} />
        <Route path="innstillinger" element={<Settings />} />
        <Route path="audit-logg" element={<AuditLog />} />
        <Route path="status" element={<Status />} />
        <Route path="admin/tenants" element={<TenantsAdmin />} />
      </Route>
      
      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
