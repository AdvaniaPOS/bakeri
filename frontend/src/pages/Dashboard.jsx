import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  TrendingUp, 
  Package, 
  Users, 
  ShoppingCart,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const statusColors = {
  draft: 'badge-neutral',
  pending: 'badge-warning',
  confirmed: 'badge-info',
  ready_for_delivery: 'badge-info',
  in_transit: 'badge-amber',
  delivered: 'badge-success',
  cancelled: 'badge-danger',
};

const statusLabels = {
  draft: 'Kladd',
  pending: 'Venter',
  confirmed: 'Bekreftet',
  ready_for_delivery: 'Klar',
  in_transit: 'Under levering',
  delivered: 'Levert',
  cancelled: 'Kansellert',
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();
  const [stats, setStats] = useState({
    orders: 0,
    customers: 0,
    products: 0,
    revenue: 0
  });
  const [recentOrders, setRecentOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      // Fetch stats in parallel
      const [ordersRes, customersRes, productsRes] = await Promise.all([
        authFetch('/api/v1/orders?page_size=10'),
        authFetch('/api/v1/customers?page_size=1'),
        authFetch('/api/v1/products?page_size=1')
      ]);

      const ordersData = await ordersRes.json();
      const customersData = await customersRes.json();
      const productsData = await productsRes.json();

      // Calculate stats
      const todayOrders = ordersData.items?.filter(o => {
        const orderDate = new Date(o.created_at).toDateString();
        return orderDate === new Date().toDateString();
      }).length || 0;

      const totalRevenue = ordersData.items?.reduce((sum, o) => 
        sum + parseFloat(o.total_amount_incl_vat || 0), 0) || 0;

      setStats({
        orders: todayOrders,
        customers: customersData.total || 0,
        products: productsData.total || 0,
        revenue: totalRevenue
      });

      // Map recent orders
      setRecentOrders((ordersData.items || []).slice(0, 5).map(o => ({
        id: `ORD-${o.id}`,
        customer: o.customer_name || `Kunde #${o.customer_id}`,
        items: o.lines?.length || 0,
        total: `kr ${parseFloat(o.total_amount_incl_vat || 0).toFixed(0)}`,
        status: o.status,
        date: new Date(o.delivery_date).toLocaleDateString('nb-NO', { day: 'numeric', month: 'short' })
      })));
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatNumber = (num) => {
    if (num >= 1000) return `${(num/1000).toFixed(1)}k`;
    return num.toString();
  };

  const statsDisplay = [
    { 
      name: 'Dagens bestillinger', 
      value: stats.orders.toString(), 
      change: '+0%',
      trend: 'neutral',
      icon: ShoppingCart,
      color: 'bg-blue-500'
    },
    { 
      name: 'Aktive kunder', 
      value: formatNumber(stats.customers), 
      change: '+0%',
      trend: 'neutral',
      icon: Users,
      color: 'bg-green-500'
    },
    { 
      name: 'Produkter', 
      value: stats.products.toString(), 
      change: '0%',
      trend: 'neutral',
      icon: Package,
      color: 'bg-amber-500'
    },
    { 
      name: 'Total verdi', 
      value: `kr ${formatNumber(stats.revenue)}`, 
      change: '+0%',
      trend: 'neutral',
      icon: TrendingUp,
      color: 'bg-purple-500'
    },
  ];
  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster dashboard...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Hjem</h1>
          <p className="page-subtitle">Velkommen tilbake! Her er dagens oversikt.</p>
        </div>
        <button onClick={fetchDashboardData} className="btn-secondary" title="Oppdater">
          <RefreshCw className="w-4 h-4" /> Oppdater
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {statsDisplay.map((stat) => (
          <div key={stat.name} className="card card-tight">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-xs uppercase tracking-wider font-semibold text-gray-500">{stat.name}</p>
              <div className={`w-7 h-7 ${stat.color} rounded flex items-center justify-center`}>
                <stat.icon className="w-3.5 h-3.5 text-white" />
              </div>
            </div>
            <p className="text-2xl font-semibold text-gray-900">{stat.value}</p>
            <div className="mt-1 flex items-center gap-1 text-xs">
              {stat.trend === 'up' ? (
                <ArrowUpRight className="w-3 h-3 text-green-500" />
              ) : stat.trend === 'down' ? (
                <ArrowDownRight className="w-3 h-3 text-red-500" />
              ) : null}
              <span className={`${stat.trend === 'up' ? 'text-green-600' : stat.trend === 'down' ? 'text-red-600' : 'text-gray-500'}`}>
                {stat.change}
              </span>
              <span className="text-gray-400">fra forrige uke</span>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Orders */}
      <div className="card p-0 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Siste bestillinger</h2>
          <button
            onClick={() => navigate('/bestillinger')}
            className="text-amber-700 hover:text-amber-800 text-xs font-medium"
          >
            Se alle →
          </button>
        </div>

        {recentOrders.length === 0 ? (
          <p className="text-gray-500 text-center py-12 text-sm">Ingen bestillinger ennå</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="shop-table">
              <thead>
                <tr>
                  <th>Ordre</th>
                  <th>Kunde</th>
                  <th>Varer</th>
                  <th className="text-right">Total</th>
                  <th>Status</th>
                  <th>Leveringsdato</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((order) => (
                  <tr key={order.id}>
                    <td className="font-mono font-medium text-gray-900">{order.id}</td>
                    <td className="text-gray-700">{order.customer}</td>
                    <td className="text-gray-500">{order.items} varer</td>
                    <td className="text-right font-medium text-gray-900">{order.total}</td>
                    <td>
                      <span className={`badge ${statusColors[order.status] || 'badge-neutral'}`}>
                        {statusLabels[order.status] || order.status}
                      </span>
                    </td>
                    <td className="text-gray-500">{order.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
