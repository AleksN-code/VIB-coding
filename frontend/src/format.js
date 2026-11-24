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
