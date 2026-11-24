// Усі дані адмінка бере й змінює тільки через backend API — до бази напряму не звертається.
// Локально запит іде на ту саму адресу, що й сторінка (/api/...), а Vite пересилає його на FastAPI.
// На хостингу (Render) адресу API можна задати через VITE_API_BASE_URL.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

// Помилка запиту: message — текст для людини, status — HTTP-код (0 — немає з'єднання)
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Немає з'єднання з backend API.", 0);
  }

  // 204 No Content — успішне видалення, тіла відповіді немає
  if (response.status === 204) {
    return null;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  if (!response.ok) {
    if (!isJson) {
      // Так відповідає проксі Vite, коли контейнер API зупинений або ще не запустився
      throw new ApiError(`Backend API не відповідає (HTTP ${response.status}).`, response.status);
    }
    // Backend пояснює помилку українською в полі detail — показуємо її як є
    const data = await response.json();
    const detail = typeof data.detail === "string" ? data.detail : `API повернув помилку ${response.status}.`;
    throw new ApiError(detail, response.status);
  }
  if (!isJson) {
    throw new ApiError(`API повернув не JSON за адресою ${path}.`, response.status);
  }
  return response.json();
}

// ---- Читання ----
export const fetchSummary = () => request("GET", "/api/summary");
export const fetchCars = () => request("GET", "/api/cars");
export const fetchCategories = () => request("GET", "/api/categories");
export const fetchUsers = () => request("GET", "/api/users");
export const fetchTransactions = (carId) =>
  request("GET", carId == null ? "/api/transactions" : `/api/transactions?car_id=${encodeURIComponent(carId)}`);

// ---- Зміни: React-форма → API → перевірка → SQLAlchemy → Neon ----
// data: { car_id, type, category_id, date, amount, currency, description }
export const createTransaction = (data) => request("POST", "/api/transactions", data);
export const updateTransaction = (id, data) => request("PUT", `/api/transactions/${encodeURIComponent(id)}`, data);
export const deleteTransaction = (id) => request("DELETE", `/api/transactions/${encodeURIComponent(id)}`);

// data: { owner_id, brand, model, year, vin }
export const createCar = (data) => request("POST", "/api/cars", data);
export const updateCar = (id, data) => request("PUT", `/api/cars/${encodeURIComponent(id)}`, data);
// Разом з усіма операціями авто
export const deleteCar = (id) => request("DELETE", `/api/cars/${encodeURIComponent(id)}`);
