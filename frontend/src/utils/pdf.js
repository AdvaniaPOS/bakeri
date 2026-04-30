// Felles hjelper for å hente og åpne PDF-er fra backend.
// Backend returnerer application/pdf med Bearer-auth påkrevd, så vi må
// hente blob først og åpne via blob-URL.

/**
 * Henter PDF og åpner i ny fane (forhåndsvisning).
 * @param {Function} authFetch - authFetch fra AuthContext
 * @param {string} url - PDF-endepunkt (f.eks. /api/v1/reports/...)
 */
export async function openPdf(authFetch, url) {
  const resp = await authFetch(url);
  if (!resp.ok) {
    let msg = `Klarte ikke hente PDF (${resp.status})`;
    try {
      const data = await resp.json();
      if (data.detail) msg = data.detail;
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  const blob = await resp.blob();
  const blobUrl = URL.createObjectURL(blob);
  const newWin = window.open(blobUrl, '_blank');
  // Frigi etter en stund slik at fanen rekker å laste
  setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
  return newWin;
}

/**
 * Henter PDF og trigger lokal nedlasting med gitt filnavn.
 */
export async function downloadPdf(authFetch, url, filename) {
  const resp = await authFetch(url);
  if (!resp.ok) {
    throw new Error(`Klarte ikke laste ned PDF (${resp.status})`);
  }
  const blob = await resp.blob();
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 5_000);
}
