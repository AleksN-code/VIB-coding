// Усі дані адмінка бере тільки з backend API.
// Локально запит іде на ту саму адресу, що й сторінка (/api/...), а Vite пересилає його на FastAPI.
// На хостингу (Render) адресу API можна задати через VITE_API_BASE_URL.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function getJson(path) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new Error("Немає з'єднання з backend API.");
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  if (!response.ok) {
    if (!isJson) {
      // Так відповідає проксі Vite, коли контейнер API зупинений або ще не запустився
      throw new Error(`Backend API не відповідає (HTTP ${response.status}).`);
    }
    const body = await response.json();
    const detail = typeof body.detail === "string" ? `: ${body.detail}` : "";
    throw new Error(`API повернув помилку ${response.status}${detail}.`);
  }
  if (!isJson) {
    throw new Error(`API повернув не JSON за адресою ${path}.`);
  }
  return response.json();
}

export const fetchSummary = () => getJson("/api/summary");
export const fetchCars = () => getJson("/api/cars");
export const fetchTransactions = (carId) =>
  getJson(carId == null ? "/api/transactions" : `/api/transactions?car_id=${encodeURIComponent(carId)}`);
