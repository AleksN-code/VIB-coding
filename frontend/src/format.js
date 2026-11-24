// Форматування для показу. API віддає точні суми з копійками, а в адмінці —
// як у боті: суми до цілого числа, курс — 2 знаки після коми.

// maximumFractionDigits: 0 округлює .5 від нуля — так само, як бот (ROUND_HALF_UP)
const whole = new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 });

function sign(value) {
  return value < 0 ? "−" : "";
}

export function formatUah(value) {
  return `${sign(value)}${whole.format(Math.abs(value))} грн`;
}

export function formatUsd(value) {
  return `${sign(value)}$${whole.format(Math.abs(value))}`;
}

export function formatRate(value) {
  return value.toFixed(2);
}

// "2026-11-24" → "24.11.2026" (без перетворення в Date, щоб часовий пояс не зсунув день)
export function formatDate(isoDate) {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

// Українські відмінки після числа: plural(1, "операцію", "операції", "операцій") → "1 операцію",
// 3 → "3 операції", 5 / 11 / 12 → "5 операцій"
export function plural(n, one, few, many) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}

// Сьогоднішня дата за київським часом у форматі "2026-11-24" — як у боті.
// Формат en-CA дає саме РРРР-ММ-ДД.
export function todayInKyiv() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Kyiv" }).format(new Date());
}
