import { useState, useEffect } from 'react';
import { 
  Calendar, RefreshCw, ChevronLeft, ChevronRight, 
  Package, ClipboardList, Download, Users 
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { openPdf } from '../utils/pdf';

// Day names in Norwegian
const dayNames = ['Søndag', 'Mandag', 'Tirsdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lørdag'];
const monthNames = ['januar', 'februar', 'mars', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'desember'];

const formatDate = (date) => {
  const d = new Date(date);
  return `${dayNames[d.getDay()]} ${d.getDate()}. ${monthNames[d.getMonth()]}`;
};

const formatDateISO = (date) => {
  const d = new Date(date);
  return d.toISOString().split('T')[0];
};

// Beregn standard-dato basert på tenant-innstilling.
// Verdier: "today" | "tomorrow" | heltall (offset i dager).
function resolveDefaultDate(setting) {
  const d = new Date();
  if (setting === undefined || setting === null || setting === 'today') return d;
  if (setting === 'tomorrow') {
    d.setDate(d.getDate() + 1);
    return d;
  }
  const offset = parseInt(setting, 10);
  if (!Number.isNaN(offset)) {
    d.setDate(d.getDate() + offset);
  }
  return d;
}

export default function ProductionReport() {
  const { authFetch } = useAuth();
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [defaultDateLoaded, setDefaultDateLoaded] = useState(false);
  const [report, setReport] = useState(null);
  const [weekOverview, setWeekOverview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState('day'); // 'day' or 'week'

  // Hent default-dato fra tenant-settings én gang ved mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await authFetch('/api/v1/admin/settings');
        if (!resp.ok) return;
        const data = await resp.json();
        const setting = data?.production_report_default_day?.value ?? 'today';
        if (!cancelled) {
          setSelectedDate(resolveDefaultDate(setting));
        }
      } catch {
        // ignore — beholder dagens dato som fallback
      } finally {
        if (!cancelled) setDefaultDateLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchDailyReport = async () => {
    setLoading(true);
    try {
      const dateStr = formatDateISO(selectedDate);
      const response = await authFetch(`/api/v1/reports/production/${dateStr}`);
      if (!response.ok) throw new Error('Kunne ikke hente produksjonsrapport');
      const data = await response.json();
      setReport(data);
      setError(null);
    } catch (err) {
      console.error('Error loading report:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchWeekOverview = async () => {
    setLoading(true);
    try {
      // Get the Monday of the current week
      const monday = new Date(selectedDate);
      monday.setDate(monday.getDate() - monday.getDay() + 1);
      const dateStr = formatDateISO(monday);
      
      const response = await authFetch(`/api/v1/reports/production-week?start_date=${dateStr}`);
      if (!response.ok) throw new Error('Kunne ikke hente ukeoversikt');
      const data = await response.json();
      setWeekOverview(data);
      setError(null);
    } catch (err) {
      console.error('Error loading week overview:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!defaultDateLoaded) return; // vent til default-dato er hentet
    if (view === 'day') {
      fetchDailyReport();
    } else {
      fetchWeekOverview();
    }
  }, [selectedDate, view, defaultDateLoaded]);

  const changeDate = (days) => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() + days);
    setSelectedDate(newDate);
  };

  const goToToday = () => {
    setSelectedDate(new Date());
  };

  const downloadProductionPdf = async () => {
    try {
      await openPdf(authFetch, `/api/v1/reports/pdf/production/${formatDateISO(selectedDate)}`);
    } catch (e) {
      setError(e.message || 'Klarte ikke åpne PDF');
    }
  };

  const downloadPackingListPdf = async () => {
    try {
      await openPdf(authFetch, `/api/v1/reports/pdf/packing-list/${formatDateISO(selectedDate)}`);
    } catch (e) {
      setError(e.message || 'Klarte ikke åpne PDF');
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster produksjonsrapport...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Produksjonsrapport</h1>
          <p className="page-subtitle">Oversikt over produksjonsbehov</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={downloadProductionPdf} className="btn-primary" title="Produksjonsrapport som PDF">
            <Download className="w-4 h-4" /> Produksjon (PDF)
          </button>
          <button onClick={downloadPackingListPdf} className="btn-secondary" title="Pakkeliste pr kunde som PDF">
            <Download className="w-4 h-4" /> Pakkeliste (PDF)
          </button>
          <button onClick={() => view === 'day' ? fetchDailyReport() : fetchWeekOverview()} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      {/* Date Navigation */}
      <div className="card card-tight mb-4">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
          {/* View Toggle */}
          <div className="flex bg-gray-100 rounded-md p-0.5">
            <button
              onClick={() => setView('day')}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                view === 'day' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Dagsvisning
            </button>
            <button
              onClick={() => setView('week')}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                view === 'week' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Ukeoversikt
            </button>
          </div>

          {/* Date Picker */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => changeDate(view === 'week' ? -7 : -1)}
              className="p-1.5 text-gray-600 hover:bg-gray-100 rounded"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 border border-amber-200 rounded-md">
              <Calendar className="w-4 h-4 text-amber-600" />
              <span className="font-medium text-amber-800 text-sm">
                {view === 'day'
                  ? formatDate(selectedDate)
                  : `Uke ${getWeekNumber(selectedDate)}, ${selectedDate.getFullYear()}`
                }
              </span>
            </div>

            <button
              onClick={() => changeDate(view === 'week' ? 7 : 1)}
              className="p-1.5 text-gray-600 hover:bg-gray-100 rounded"
            >
              <ChevronRight className="w-4 h-4" />
            </button>

            <button onClick={goToToday} className="btn-secondary ml-1">I dag</button>
          </div>
        </div>
      </div>

      {/* Day View */}
      {view === 'day' && report && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="card card-tight">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-100 rounded">
                  <ClipboardList className="w-4 h-4 text-amber-600" />
                </div>
                <div>
                  <p className="text-2xl font-semibold text-gray-900">{report.total_orders}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Ordrer</p>
                </div>
              </div>
            </div>
            <div className="card card-tight">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-green-100 rounded">
                  <Users className="w-4 h-4 text-green-600" />
                </div>
                <div>
                  <p className="text-2xl font-semibold text-gray-900">{report.total_customers}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Kunder</p>
                </div>
              </div>
            </div>
            <div className="card card-tight">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-100 rounded">
                  <Package className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <p className="text-2xl font-semibold text-gray-900">{report.total_products}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Produkttyper</p>
                </div>
              </div>
            </div>
          </div>

          {/* Products by Category */}
          <div className="card p-0 overflow-hidden print:shadow-none print:border">
            <div className="px-4 py-2.5 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-900">Produkter å produsere</h2>
            </div>

            {Object.keys(report.products_by_category || {}).length === 0 ? (
              <p className="text-gray-500 text-center py-12 text-sm">Ingen produkter å produsere denne dagen</p>
            ) : (
              <div>
                {Object.entries(report.products_by_category || {}).map(([category, products]) => (
                  <div key={category}>
                    <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
                      <h3 className="text-xs uppercase tracking-wider font-semibold text-gray-700">{category}</h3>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="shop-table">
                        <thead>
                          <tr>
                            <th>Produkt</th>
                            <th className="text-right">Antall</th>
                            <th className="text-right">Enhet</th>
                          </tr>
                        </thead>
                        <tbody>
                          {products.map(product => (
                            <tr key={product.product_id}>
                              <td className="text-gray-900">{product.product_name}</td>
                              <td className="text-right">
                                <span className="text-lg font-semibold text-amber-700">{product.total_quantity}</span>
                              </td>
                              <td className="text-right text-gray-500">{product.unit}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Week View */}
      {view === 'week' && weekOverview && (
        <div className="card">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Ukeoversikt</h2>

          <div className="grid grid-cols-7 gap-2">
            {weekOverview.days?.map(day => (
              <div
                key={day.date}
                onClick={() => {
                  setSelectedDate(new Date(day.date));
                  setView('day');
                }}
                className={`p-3 rounded-md border cursor-pointer transition-all hover:border-amber-400 ${
                  formatDateISO(new Date()) === day.date
                    ? 'border-amber-500 bg-amber-50'
                    : 'border-gray-200'
                }`}
              >
                <p className="text-xs font-medium uppercase tracking-wider text-gray-500">{day.day_name?.slice(0, 3)}</p>
                <p className="text-lg font-semibold text-gray-900">{new Date(day.date).getDate()}.</p>
                <div className="mt-2 space-y-0.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Ordrer</span>
                    <span className={`font-medium ${day.order_count > 0 ? 'text-amber-700' : 'text-gray-400'}`}>{day.order_count}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Kunder</span>
                    <span className={`font-medium ${day.customer_count > 0 ? 'text-green-700' : 'text-gray-400'}`}>{day.customer_count}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 pt-3 border-t border-gray-200 flex items-center justify-between text-xs text-gray-500">
            <span>Totalt denne uken:</span>
            <span>
              <span className="font-medium text-gray-900">{weekOverview.total_orders}</span> ordrer til{' '}
              <span className="font-medium text-gray-900">{weekOverview.total_customers}</span> kunder
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// Helper function to get week number
function getWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}
