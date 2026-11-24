// Тонкі лінійні іконки в одному стилі з логотипом.
// Колір — currentColor: іконка бере колір тексту поруч (зелений для доходу, рожевий для витрат…),
// а неонове світіння додає CSS (.icon).

const PATHS = {
  // фінанси
  expense: (
    <>
      <path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" />
      <path d="M9 8h6M9 12h6M9 16h3" />
    </>
  ),
  income: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2" />
      <circle cx="12" cy="12" r="2.6" />
      <path d="M6 9.5v5M18 9.5v5" />
    </>
  ),
  profit: (
    <>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  loss: (
    <>
      <path d="M3 7l6 6 4-4 8 8" />
      <path d="M15 17h6v-6" />
    </>
  ),
  // статуси
  sold: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.7 2.7L16 9.5" />
    </>
  ),
  inWork: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" />,
  // категорії
  cart: (
    <>
      <path d="M3 4h2l2.4 10.2a1.5 1.5 0 0 0 1.5 1.1h8.2a1.5 1.5 0 0 0 1.4-1.1L20 8H6.2" />
      <circle cx="9.5" cy="19.5" r="1.3" />
      <circle cx="16.5" cy="19.5" r="1.3" />
    </>
  ),
  truck: (
    <>
      <path d="M2.5 6.5h10.5v9.5H2.5z" />
      <path d="M13 9.5h4l3.5 3.5v3H13" />
      <circle cx="6.5" cy="17.5" r="1.8" />
      <circle cx="16.5" cy="17.5" r="1.8" />
    </>
  ),
  customs: (
    <>
      <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" />,
  gear: (
    <>
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2.4" />
      <path d="M12 3.2V6M12 18v2.8M3.2 12H6M18 12h2.8M5.8 5.8l2 2M16.2 16.2l2 2M5.8 18.2l2-2M16.2 7.8l2-2" />
    </>
  ),
  box: (
    <>
      <path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z" />
      <path d="M3.5 7.5L12 12l8.5-4.5M12 12v9" />
    </>
  ),
  tag: (
    <>
      <path d="M3 12.5V4h8.5l9.5 9.5-7.5 7.5z" />
      <circle cx="7.5" cy="8" r="1.4" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="3" />,
  // інтерфейс
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </>
  ),
  warning: (
    <>
      <path d="M12 3.5l9.5 16.5h-19z" />
      <path d="M12 10v4.5M12 17.3v.4" />
    </>
  ),
};

// Категорія з бази → іконка
export const CATEGORY_ICON = {
  "Купівля авто": "cart",
  "Доставка": "truck",
  "Розмитнення": "customs",
  "Ремонт": "wrench",
  "Запчастини": "gear",
  "Інше": "box",
  "Продаж авто": "tag",
};

export function Icon({ name, className = "" }) {
  return (
    <svg
      className={`icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name] ?? PATHS.dot}
    </svg>
  );
}
