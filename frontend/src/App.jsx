import { useCallback, useEffect, useId, useState } from "react";
import {
  AUTH_REQUIRED_EVENT,
  fetchCars,
  fetchCategories,
  fetchSummary,
  fetchTransactions,
  fetchUsers,
  login,
  logout,
} from "./api.js";
import CarForm from "./CarForm.jsx";
import DeleteCarDialog from "./DeleteCarDialog.jsx";
import DeleteTransactionDialog from "./DeleteTransactionDialog.jsx";
import { formatDate, formatRate, formatUah, formatUsd, plural } from "./format.js";
import { CATEGORY_ICON, Icon } from "./icons.jsx";
import TransactionForm from "./TransactionForm.jsx";

// Фільтри таблиці операцій: лише змінюють, що видно; дані в базі не змінюються
const FILTERS = [
  { value: "all", label: "Усі" },
  { value: "income", label: "Доходи" },
  { value: "expense", label: "Витрати" },
];

// Обрана вкладка зберігається в адресі (#car-4), щоб після оновлення сторінки лишатися на ній
function carIdFromHash() {
  const match = window.location.hash.match(/^#car-(\d+)$/);
  return match ? Number(match[1]) : null;
}

// Повідомлення після дії («Авто додано») — зникає само через 5 секунд
function useNotice() {
  const [notice, setNotice] = useState(null);
  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  return [notice, setNotice];
}

function Notice({ text }) {
  return (
    text && (
      <div className="notice" role="status">
        <Icon name="check" />
        {text}
      </div>
    )
  );
}

export default function App() {
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  const [cars, setCars] = useState([]);
  const [categories, setCategories] = useState([]);
  const [users, setUsers] = useState([]);
  const [selectedId, setSelectedId] = useState(carIdFromHash);
  // Вікна для авто: форма (нове або зміна) і підтвердження видалення
  const [carDialog, setCarDialog] = useState(null); // null | { car: null | {...} }
  const [deletingCar, setDeletingCar] = useState(null);
  const [notice, setNotice] = useNotice();
  // true — backend відповів 401: показуємо екран входу замість даних
  const [authRequired, setAuthRequired] = useState(false);
  const [loadedAt, setLoadedAt] = useState(null);
  // Лічильник оновлень: після «Оновити» вкладка авто заново завантажує свої операції
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const [summaryData, carsData, categoriesData, usersData] = await Promise.all([
        fetchSummary(),
        fetchCars(),
        fetchCategories(),
        fetchUsers(),
      ]);
      setSummary(summaryData);
      setCars(carsData);
      setCategories(categoriesData);
      setUsers(usersData);
      setLoadedAt(new Date());
      setReloadKey((key) => key + 1);
      setStatus("ready");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onHashChange = () => setSelectedId(carIdFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // Будь-який запит отримав 401 (немає входу або сесія закінчилась) — показати екран входу
  useEffect(() => {
    const onAuthRequired = () => {
      setCarDialog(null);
      setDeletingCar(null);
      setAuthRequired(true);
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // навіть якщо backend недоступний — ховаємо дані й показуємо вхід
    }
    setSummary(null);
    setCars([]);
    setUsers([]);
    setAuthRequired(true);
  }

  // Якщо в адресі немає авто або такого вже немає — відкриваємо перше
  const selectedCar = cars.find((car) => car.id === selectedId) ?? cars[0] ?? null;

  async function handleCarSaved(saved, isNew) {
    setCarDialog(null);
    setNotice(isNew ? `Авто ${saved.title} додано.` : `Зміни авто ${saved.title} збережено.`);
    await load();
    if (isNew) {
      // Нове авто вже є в списку — відкриваємо його вкладку
      window.location.hash = `car-${saved.id}`;
    }
  }

  function handleCarDeleted(car) {
    setDeletingCar(null);
    const removed = car.transactions_count;
    setNotice(
      removed > 0
        ? `Авто ${car.title} видалено разом з ${plural(removed, "операцією", "операціями", "операціями")}.`
        : `Авто ${car.title} видалено.`,
    );
    // Вкладки видаленого авто більше немає — повертаємось до першого авто
    window.history.replaceState(null, "", window.location.pathname);
    setSelectedId(null);
    load();
  }

  if (authRequired) {
    return (
      <LoginScreen
        onLoggedIn={() => {
          setAuthRequired(false);
          load();
        }}
      />
    );
  }

  return (
    <div className="page">
      <header className="header">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            <LogoMark />
          </span>
          <div>
            <h1>Car Finance</h1>
            <p className="subtitle">Фінансовий облік по авто</p>
          </div>
        </div>
        {summary && <OverallLine summary={summary} carsCount={cars.length} loadedAt={loadedAt} />}
        <div className="header-actions">
          <button className="button" onClick={load} disabled={status === "loading"}>
            <Icon name="refresh" className={status === "loading" ? "spin" : ""} />
            {status === "loading" ? "Оновлення…" : "Оновити"}
          </button>
          <button className="button button-ghost" onClick={handleLogout} title="Вийти з адмінки">
            <Icon name="logout" />
            Вийти
          </button>
        </div>
      </header>

      {status === "error" && <ErrorBox message={error} onRetry={load} />}
      {status === "loading" && !summary && <p className="muted">Завантаження даних…</p>}

      <Notice text={notice} />

      {summary && (
        <>
          {cars.length === 0 ? (
            <div className="panel empty">
              <p className="muted">Авто ще немає. Додайте перше авто тут або в Telegram-боті.</p>
              <button type="button" className="button button-primary" onClick={() => setCarDialog({ car: null })}>
                <Icon name="plus" />
                Додати авто
              </button>
            </div>
          ) : (
            <>
              <CarTabs cars={cars} selectedId={selectedCar?.id} onAdd={() => setCarDialog({ car: null })} />
              {selectedCar && (
                <CarView
                  key={selectedCar.id}
                  car={selectedCar}
                  cars={cars}
                  categories={categories}
                  reloadKey={reloadKey}
                  // Після зміни даних — заново завантажити загальні цифри, картки авто й таблицю
                  onChanged={load}
                  onEditCar={() => setCarDialog({ car: selectedCar })}
                  onDeleteCar={() => setDeletingCar(selectedCar)}
                />
              )}
            </>
          )}
        </>
      )}

      {carDialog && (
        <CarForm car={carDialog.car} users={users} onClose={() => setCarDialog(null)} onSaved={handleCarSaved} />
      )}
      {deletingCar && (
        <DeleteCarDialog car={deletingCar} onClose={() => setDeletingCar(null)} onDeleted={handleCarDeleted} />
      )}
    </div>
  );
}

// Екран входу: пароль іде лише в POST /api/login; у браузері він не зберігається.
// Backend у відповідь ставить cookie сесії (HttpOnly), далі браузер додає його сам.
function LoginScreen({ onLoggedIn }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();

  async function submit(event) {
    event.preventDefault();
    if (!password) {
      setError("Введіть пароль.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(password);
      setPassword("");
      onLoggedIn();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit} noValidate>
        <span className="logo" aria-hidden="true">
          <LogoMark />
        </span>
        <h1>Car Finance</h1>
        <p className="subtitle">Вхід в адмінку</p>

        <div className="field">
          <label htmlFor={inputId}>Пароль</label>
          <input
            id={inputId}
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            aria-invalid={error ? "true" : undefined}
            onChange={(e) => {
              setPassword(e.target.value);
              setError(null);
            }}
          />
        </div>

        {error && (
          <div className="form-error" role="alert">
            <Icon name="warning" />
            <span>{error}</span>
          </div>
        )}

        <button type="submit" className="button button-primary login-button" disabled={busy}>
          <Icon name="lock" />
          {busy ? "Перевірка…" : "Увійти"}
        </button>
        <p className="muted login-note">Пароль задається у файлі .env — змінна ADMIN_PASSWORD.</p>
      </form>
    </div>
  );
}

// Загальні цифри по всіх авто — компактні колонки в шапці, поруч із заголовком
function OverallLine({ summary, carsCount, loadedAt }) {
  const balanceTone = summary.balance.usd < 0 ? "expense" : "income";
  return (
    <section className="overall" aria-label="Усього по всіх авто">
      <div className="overall-head">
        Усього по всіх авто
        {loadedAt && <span className="overall-time"> · оновлено о {loadedAt.toLocaleTimeString("uk-UA")}</span>}
      </div>
      <div className="overall-stats">
        <OverallStat label="Авто" value={carsCount} />
        <OverallStat label="Доходи" tone="income" money={summary.total_income} />
        <OverallStat label="Витрати" tone="expense" money={summary.total_expense} />
        <OverallStat label="Баланс" tone={balanceTone} money={summary.balance} />
      </div>
    </section>
  );
}

// У шапці — лише долари: коротко й рівно. Гривні — у картках авто й у таблиці.
function OverallStat({ label, tone, money, value }) {
  return (
    <div className={`overall-stat ${tone ? `tone-${tone}` : ""}`}>
      <div className="overall-label">{label}</div>
      <div className="overall-value">{money ? formatUsd(money.usd) : value}</div>
    </div>
  );
}

function CarTabs({ cars, selectedId, onAdd }) {
  return (
    <nav className="tabs" aria-label="Авто">
      {cars.map((car) => (
        <a
          key={car.id}
          href={`#car-${car.id}`}
          className={`tab ${car.id === selectedId ? "tab-active" : ""}`}
          aria-current={car.id === selectedId ? "page" : undefined}
          // Повна назва при наведенні — якщо довга назва у вкладці обрізана «…»
          title={car.title}
        >
          <CarImage car={car} className="tab-image" />
          <span className="tab-text">
            <span className="tab-title">
              {car.brand} {car.model}
            </span>
            {/* Рік — окремим рядком під назвою, поруч зі статусом */}
            <span className="tab-meta">
              {car.year} ·
              <span className={`tab-status ${car.sold ? "is-sold" : "in-work"}`}>
                <Icon name={car.sold ? "sold" : "inWork"} />
                {car.sold ? "Продано" : "В роботі"}
              </span>
            </span>
          </span>
        </a>
      ))}
      <button type="button" className="tab tab-add" onClick={onAdd}>
        <Icon name="plus" />
        Додати авто
      </button>
    </nav>
  );
}

// Неоновий градієнт для SVG-іконок; id унікальний для кожної іконки на сторінці
function NeonGradient({ id }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stopColor="#22d3ee" />
        <stop offset="0.55" stopColor="#a78bfa" />
        <stop offset="1" stopColor="#f472b6" />
      </linearGradient>
    </defs>
  );
}

// Логотип: спідометр зі стрілкою вгору — авто й ріст грошей
function LogoMark() {
  const id = useId();
  const stroke = `url(#${id})`;
  return (
    <svg viewBox="0 0 48 48" fill="none" width="40" height="40">
      <NeonGradient id={id} />
      <path d="M9.5 35 A17 17 0 1 1 38.5 35" stroke={stroke} strokeWidth="3" strokeLinecap="round" />
      <path d="M14 22.5 l2.4 1.1 M24 11 v2.6 M34 22.5 l-2.4 1.1" stroke={stroke} strokeWidth="2.2" strokeLinecap="round" />
      <path d="M24 29 L33 17.5" stroke={stroke} strokeWidth="3.2" strokeLinecap="round" />
      <circle cx="24" cy="29" r="3.4" fill={stroke} />
    </svg>
  );
}

// Контур авто — коли фото моделі немає
function CarOutline() {
  const id = useId();
  const stroke = `url(#${id})`;
  return (
    <svg viewBox="0 0 64 32" fill="none" className="car-outline">
      <NeonGradient id={id} />
      <path
        d="M5 23.5 V20 Q5 17.5 7.5 16.8 L14 15 L21 9.5 Q23 8 26 8 H38 Q41 8 43.5 10 L49 15 L56 16.5 Q59 17.2 59 20.5 V23.5"
        stroke={stroke}
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M11 23.5 H5 M21 23.5 H43 M59 23.5 H53" stroke={stroke} strokeWidth="2" strokeLinecap="round" />
      <circle cx="16" cy="23.5" r="4.5" stroke={stroke} strokeWidth="2" />
      <circle cx="48" cy="23.5" r="4.5" stroke={stroke} strokeWidth="2" />
    </svg>
  );
}

function CarImage({ car, className }) {
  const [failed, setFailed] = useState(false);
  if (!car.image_url || failed) {
    return (
      <span className={`${className} image-placeholder`}>
        <CarOutline />
      </span>
    );
  }
  return <img className={className} src={car.image_url} alt={car.title} loading="lazy" onError={() => setFailed(true)} />;
}

function CarView({ car, cars, categories, reloadKey, onChanged, onEditCar, onDeleteCar }) {
  const [status, setStatus] = useState("loading");
  // null — ще не завантажено; після першого завантаження таблиця лишається видимою під час оновлень
  const [transactions, setTransactions] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  // Відкрите вікно: форма (нова операція або зміна) чи підтвердження видалення
  const [editing, setEditing] = useState(null); // null | { transaction: null | {...} }
  const [deleting, setDeleting] = useState(null); // null | операція
  const [notice, setNotice] = useNotice();

  const load = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      setTransactions(await fetchTransactions(car.id));
      setStatus("ready");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }, [car.id]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  function handleSaved(saved) {
    const isNew = editing.transaction == null;
    setEditing(null);
    let text = isNew ? "Операцію додано." : "Зміни збережено.";
    if (saved.car_id !== car.id) text += ` Операцію перенесено на ${saved.car}.`;
    setNotice(text);
    onChanged();
  }

  function handleDeleted(deleted) {
    setDeleting(null);
    setNotice(deleted.type === "income" ? "Продаж видалено — авто знову в роботі." : "Операцію видалено.");
    onChanged();
  }

  const counts = {
    all: transactions?.length ?? 0,
    income: transactions?.filter((t) => t.type === "income").length ?? 0,
    expense: transactions?.filter((t) => t.type === "expense").length ?? 0,
  };
  const visible = transactions?.filter((t) => filter === "all" || t.type === filter) ?? [];

  return (
    <section className="car">
      <div className="car-head">
        <figure className="car-photo">
          <CarImage car={car} className="car-image" />
          {car.image_page_url && (
            <figcaption>
              Фото моделі:{" "}
              <a href={car.image_page_url} target="_blank" rel="noreferrer">
                Вікіпедія — {car.image_page_title}
              </a>
            </figcaption>
          )}
        </figure>
        <div className="car-info">
          <h2>{car.title}</h2>
          {car.vin && <p className="muted">VIN: {car.vin}</p>}
          <p className="muted">Власник: {car.owner}</p>
          <p className={`car-status ${car.sold ? "is-sold" : "in-work"}`}>
            <Icon name={car.sold ? "sold" : "inWork"} />
            {car.sold ? `Продано ${formatDate(car.sale_date)}` : "В роботі — ще не продано"}
          </p>
          <p className="muted">Операцій: {car.transactions_count}</p>
          <div className="car-actions">
            <button type="button" className="button button-ghost button-small" onClick={onEditCar}>
              <Icon name="edit" />
              Змінити авто
            </button>
            <button type="button" className="button button-danger button-small" onClick={onDeleteCar}>
              <Icon name="trash" />
              Видалити авто
            </button>
          </div>
        </div>
      </div>

      <div className="cards">
        <SummaryCard title="Витрати" icon="expense" tone="expense" money={car.expenses} />
        <SummaryCard
          title="Дохід"
          icon="income"
          tone="income"
          money={car.sold ? car.income : null}
          placeholder="ще не продано"
        />
        <SummaryCard
          title={car.profit && car.profit.uah < 0 ? "Збиток" : "Прибуток"}
          icon={car.profit && car.profit.uah < 0 ? "loss" : "profit"}
          tone={car.profit && car.profit.uah < 0 ? "expense" : "income"}
          money={car.profit}
          placeholder="буде після продажу"
          hint="дохід − витрати"
        />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>
            Операції
            {status === "loading" && <span className="muted loading-note"> · завантаження…</span>}
          </h3>
          <div className="panel-tools">
            <div className="filters" role="group" aria-label="Показати операції">
              {FILTERS.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  className={`filter filter-${f.value} ${filter === f.value ? "is-active" : ""}`}
                  aria-pressed={filter === f.value}
                  onClick={() => setFilter(f.value)}
                >
                  {f.label}
                  <span className="filter-count">{counts[f.value]}</span>
                </button>
              ))}
            </div>
            <button type="button" className="button button-primary" onClick={() => setEditing({ transaction: null })}>
              <Icon name="plus" />
              Додати операцію
            </button>
          </div>
        </div>

        <Notice text={notice} />
        {status === "error" && <ErrorBox message={error} onRetry={load} />}
        {transactions && status !== "error" && (
          <TransactionsTable
            transactions={visible}
            totalCount={transactions.length}
            filter={filter}
            onEdit={(t) => setEditing({ transaction: t })}
            onDelete={setDeleting}
          />
        )}
      </div>

      {editing && (
        <TransactionForm
          car={car}
          cars={cars}
          categories={categories}
          transaction={editing.transaction}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      )}
      {deleting && (
        <DeleteTransactionDialog transaction={deleting} onClose={() => setDeleting(null)} onDeleted={handleDeleted} />
      )}
    </section>
  );
}

function SummaryCard({ title, icon, tone, money, placeholder, hint }) {
  return (
    <div className={`card ${money ? `card-${tone}` : ""}`}>
      <div className="card-title">
        <Icon name={icon} className="card-icon" />
        {title}
        {hint && <span className="card-hint">{hint}</span>}
      </div>
      {money ? (
        <>
          <div className="card-uah">{formatUah(money.uah)}</div>
          <div className="card-usd">{formatUsd(money.usd)}</div>
        </>
      ) : (
        <div className="card-empty">{placeholder}</div>
      )}
    </div>
  );
}

const EMPTY_FILTER_TEXT = {
  income: "Доходів по цьому авто немає — авто ще не продано.",
  expense: "Витрат по цьому авто ще немає.",
};

function TransactionsTable({ transactions, totalCount, filter, onEdit, onDelete }) {
  if (totalCount === 0) {
    return (
      <p className="muted empty">
        Операцій по цьому авто ще немає. Додайте першу кнопкою «Додати операцію» або в Telegram-боті.
      </p>
    );
  }
  if (transactions.length === 0) {
    return <p className="muted empty">{EMPTY_FILTER_TEXT[filter]}</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Дата</th>
            <th>Тип</th>
            <th className="num">Сума, грн</th>
            <th className="num">Сума, $</th>
            <th>Категорія</th>
            <th>Опис</th>
            <th className="actions-col">
              <span className="visually-hidden">Дії</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={t.id}>
              <td className="nowrap">{formatDate(t.date)}</td>
              <td>
                <span className={`badge badge-${t.type}`}>{t.type === "income" ? "Дохід" : "Витрата"}</span>
              </td>
              {/* Валюту, в якій ввели суму (у боті чи тут), виділено жирним */}
              <td className={`num nowrap ${t.currency === "UAH" ? "entered" : ""}`}>{formatUah(t.amount_uah)}</td>
              <td
                className={`num nowrap ${t.currency === "USD" ? "entered" : ""}`}
                title={`Курс НБУ на ${formatDate(t.date)}: ${formatRate(t.usd_rate)} грн за $1`}
              >
                {formatUsd(t.amount_usd)}
              </td>
              <td className="nowrap category">
                <Icon name={CATEGORY_ICON[t.category] ?? "dot"} className={`cat-icon cat-${t.type}`} />
                {t.category}
              </td>
              <td className="description">{t.description ?? <span className="muted">—</span>}</td>
              <td className="actions">
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => onEdit(t)}
                  aria-label={`Змінити операцію від ${formatDate(t.date)}: ${t.category}`}
                  title="Змінити"
                >
                  <Icon name="edit" />
                </button>
                <button
                  type="button"
                  className="icon-button icon-button-danger"
                  onClick={() => onDelete(t)}
                  aria-label={`Видалити операцію від ${formatDate(t.date)}: ${t.category}`}
                  title="Видалити"
                >
                  <Icon name="trash" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted note">
        Жирним — валюта, в якій ввели суму. Наведіть на суму в $, щоб побачити курс НБУ.
      </p>
    </div>
  );
}

function ErrorBox({ message, onRetry }) {
  return (
    <div className="error" role="alert">
      <strong>
        <Icon name="warning" />
        Не вдалося отримати дані
      </strong>
      <p>{message}</p>
      <p className="muted">Перевірте:</p>
      <ul>
        <li>
          чи запущений backend: <code>docker compose ps</code> — сервіс <code>api</code> має бути <code>running</code>;
        </li>
        <li>
          чи відкривається <a href="http://localhost:8000/api/health">localhost:8000/api/health</a>;
        </li>
        <li>
          логи backend: <code>docker compose logs api</code>.
        </li>
      </ul>
      <button className="button" onClick={onRetry}>
        Спробувати ще раз
      </button>
    </div>
  );
}
