import { useState, useEffect } from 'react';
import { 
  Calendar, RefreshCw, ChevronLeft, ChevronRight, 
  Truck, MapPin, Phone, Package, CheckCircle, 
  Navigation, Printer, ExternalLink
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

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

export default function DeliveryList() {
  const { authFetch } = useAuth();
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [deliveryList, setDeliveryList] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchRoutes = async () => {
    try {
      const response = await authFetch('/api/v1/routes');
      if (!response.ok) throw new Error('Kunne ikke hente ruter');
      const data = await response.json();
      setRoutes(data.items || []);
      // Auto-select first route
      if (data.items?.length > 0 && !selectedRoute) {
        setSelectedRoute(data.items[0]);
      }
    } catch (err) {
      console.error('Error loading routes:', err);
    }
  };

  const fetchDeliveryList = async () => {
    if (!selectedRoute) return;
    setLoading(true);
    try {
      const dateStr = formatDateISO(selectedDate);
      const response = await authFetch(`/api/v1/reports/delivery-list/${selectedRoute.id}/${dateStr}`);
      if (!response.ok) throw new Error('Kunne ikke hente kjøreliste');
      const data = await response.json();
      setDeliveryList(data);
      setError(null);
    } catch (err) {
      console.error('Error loading delivery list:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoutes();
  }, []);

  useEffect(() => {
    if (selectedRoute) {
      fetchDeliveryList();
    }
  }, [selectedRoute, selectedDate]);

  const changeDate = (days) => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() + days);
    setSelectedDate(newDate);
  };

  const goToToday = () => {
    setSelectedDate(new Date());
  };

  const openGoogleMaps = async () => {
    if (!selectedRoute) return;
    const dateStr = formatDateISO(selectedDate);
    try {
      const response = await authFetch(`/api/v1/reports/delivery-list/${selectedRoute.id}/${dateStr}/google-maps-url`);
      if (!response.ok) throw new Error('Kunne ikke generere Google Maps-lenke');
      const data = await response.json();
      window.open(data.url, '_blank');
    } catch (err) {
      setError(err.message);
    }
  };

  const openSingleAddress = (address) => {
    const encoded = encodeURIComponent(address);
    window.open(`https://www.google.com/maps/search/?api=1&query=${encoded}`, '_blank');
  };

  const printList = () => {
    window.print();
  };

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header print:mb-4">
        <div>
          <h1 className="page-title">Kjøreliste</h1>
          <p className="page-subtitle">Oversikt over leveringer per rute</p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button onClick={printList} className="btn-secondary" title="Skriv ut">
            <Printer className="w-4 h-4" /> Skriv ut
          </button>
          <button onClick={openGoogleMaps} disabled={!selectedRoute} className="btn-primary disabled:opacity-50">
            <Navigation className="w-4 h-4" /> Google Maps
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 print:hidden">{error}</div>
      )}

      {/* Controls */}
      <div className="card card-tight mb-4 print:hidden">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Truck className="w-4 h-4 text-gray-400" />
            <select
              value={selectedRoute?.id || ''}
              onChange={(e) => setSelectedRoute(routes.find(r => r.id === parseInt(e.target.value)))}
              className="input w-64"
            >
              <option value="">Velg rute...</option>
              {routes.map(route => (
                <option key={route.id} value={route.id}>{route.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <button onClick={() => changeDate(-1)} className="p-1.5 text-gray-600 hover:bg-gray-100 rounded">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 border border-amber-200 rounded-md">
              <Calendar className="w-4 h-4 text-amber-600" />
              <span className="font-medium text-amber-800 text-sm">{formatDate(selectedDate)}</span>
            </div>
            <button onClick={() => changeDate(1)} className="p-1.5 text-gray-600 hover:bg-gray-100 rounded">
              <ChevronRight className="w-4 h-4" />
            </button>
            <button onClick={goToToday} className="btn-secondary ml-1">I dag</button>
          </div>
        </div>
      </div>

      {/* Print Header */}
      <div className="hidden print:block mb-4">
        <p className="text-lg font-medium">
          {selectedRoute?.name} - {formatDate(selectedDate)}
        </p>
        <p className="text-sm text-gray-500">
          {deliveryList?.total_stops || 0} stopp, {deliveryList?.total_items || 0} varer
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
          <span className="ml-2 text-gray-500">Laster kjøreliste...</span>
        </div>
      ) : !selectedRoute ? (
        <div className="card flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <Truck className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <p>Velg en rute for å se kjøreliste</p>
          </div>
        </div>
      ) : deliveryList?.stops?.length === 0 ? (
        <div className="card flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <Package className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <p>Ingen leveringer på denne ruten denne dagen</p>
          </div>
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="grid grid-cols-3 gap-3 mb-4 print:gap-2 print:mb-4">
            <div className="card card-tight print:p-2">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-100 rounded print:hidden">
                  <Truck className="w-4 h-4 text-amber-600" />
                </div>
                <div>
                  <p className="text-xl font-semibold text-gray-900">{deliveryList?.total_stops || 0}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Stopp</p>
                </div>
              </div>
            </div>
            <div className="card card-tight print:p-2">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-green-100 rounded print:hidden">
                  <Package className="w-4 h-4 text-green-600" />
                </div>
                <div>
                  <p className="text-xl font-semibold text-gray-900">{deliveryList?.total_items || 0}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Varer totalt</p>
                </div>
              </div>
            </div>
            <div className="card card-tight print:p-2">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-100 rounded print:hidden">
                  <MapPin className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900 truncate">{selectedRoute?.name}</p>
                  <p className="text-xs uppercase tracking-wider text-gray-500">Rute</p>
                </div>
              </div>
            </div>
          </div>

          {/* Stops List */}
          <div className="space-y-4">
            {deliveryList?.stops?.map((stop, idx) => (
              <div
                key={stop.order_id}
                className="card print:break-inside-avoid print:shadow-none print:border print:p-3"
              >
                <div className="flex items-start gap-4">
                  {/* Stop Number */}
                  <div className="flex-shrink-0">
                    <div className="w-10 h-10 bg-amber-100 text-amber-700 rounded-full flex items-center justify-center text-lg font-bold">
                      {stop.stop_number}
                    </div>
                  </div>

                  {/* Customer Info */}
                  <div className="flex-1">
                    <div className="flex items-start justify-between">
                      <div>
                        <h3 className="text-lg font-semibold text-gray-900">
                          {stop.company_name || stop.customer_name}
                        </h3>
                        <p className="text-gray-600 flex items-center gap-1">
                          <MapPin className="w-4 h-4 text-gray-400" />
                          {stop.address}
                        </p>
                        {stop.phone && (
                          <p className="text-gray-500 flex items-center gap-1 mt-1">
                            <Phone className="w-4 h-4 text-gray-400" />
                            {stop.phone}
                          </p>
                        )}
                        {stop.delivery_instructions && (
                          <p className="text-sm text-amber-600 mt-2 bg-amber-50 px-2 py-1 rounded">
                            📝 {stop.delivery_instructions}
                          </p>
                        )}
                        {(stop.delivery_window.start || stop.delivery_window.end) && (
                          <p className="text-sm text-blue-600 mt-1">
                            🕐 Leveringsvindu: {stop.delivery_window.start || '?'} - {stop.delivery_window.end || '?'}
                          </p>
                        )}
                      </div>

                      {/* Navigation Button */}
                      <button
                        onClick={() => openSingleAddress(stop.address)}
                        className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg print:hidden"
                        title="Åpne i kart"
                      >
                        <ExternalLink className="w-5 h-5" />
                      </button>
                    </div>

                    {/* Order Lines */}
                    <div className="mt-4 border-t pt-3">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-gray-500">
                            <th className="pb-2 font-medium">Produkt</th>
                            <th className="pb-2 font-medium text-right">Antall</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stop.lines.map((line, lineIdx) => (
                            <tr key={lineIdx} className="border-b border-gray-100 last:border-0">
                              <td className="py-2 text-gray-900">{line.product_name}</td>
                              <td className="py-2 text-right font-medium text-gray-900">
                                {line.quantity} {line.unit}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr className="border-t">
                            <td className="pt-2 font-medium text-gray-700">Totalt</td>
                            <td className="pt-2 text-right font-bold text-amber-600">
                              {stop.total_items} varer
                            </td>
                          </tr>
                        </tfoot>
                      </table>
                    </div>

                    {/* Checkbox for delivered */}
                    <div className="mt-4 flex items-center gap-2 print:hidden">
                      <input
                        type="checkbox"
                        id={`delivered-${stop.order_id}`}
                        className="w-5 h-5 text-green-600 rounded focus:ring-green-500"
                      />
                      <label 
                        htmlFor={`delivered-${stop.order_id}`}
                        className="text-gray-600 cursor-pointer"
                      >
                        Levert
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
