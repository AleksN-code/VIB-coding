import { useId, useRef, useState } from "react";
import { createTransaction, updateTransaction } from "./api.js";
import { todayInKyiv } from "./format.js";
import { Icon } from "./icons.jsx";
import Modal from "./Modal.jsx";

// Ті самі правила, що в боті й на backend (app/rules.py). Тут — щоб одразу підказати
// в формі; backend однаково перевіряє все ще раз.
const AMOUNT_RE = /^\d{1,10}([.,]\d{1,2})?$/; // 450, 1250,50, 1250.5
const MIN_DATE = "2000-01-01";
const MAX_DESCRIPTION = 500;

const TYPES = [
  { value: "expense", label: "Витрата" },
  { value: "income", label: "Дохід (продаж)" },
];
const CURRENCIES = [
  { value: "UAH", label: "₴ Гривня", symbol: "грн" },
  { value: "USD", label: "$ Долар", symbol: "$" },
];

// Пробіли в сумі прибираємо: у полі форми «1 200» однозначно означає 1200
const cleanAmount = (text) => text.replace(/[\s ]/g, "");

function initialValues(car, transaction) {
  if (transaction) {
    return {
      type: transaction.type,
      carId: String(transaction.car_id),
      categoryId: String(transaction.category_id),
      date: transaction.date,
      currency: transaction.currency,
      amount: String(transaction.amount),
      description: transaction.description ?? "",
    };
  }
  return {
    type: "expense",
    carId: String(car.id),
    categoryId: "",
    date: todayInKyiv(),
    currency: "UAH",
    amount: "",
    description: "",
  };
}

function validate(values, today) {
  const errors = {};
  if (!TYPES.some((t) => t.value === values.type)) {
    errors.type = "Оберіть тип операції.";
  }
  if (!values.categoryId) {
    errors.categoryId = "Оберіть категорію.";
  }
  if (!values.date) {
    errors.date = "Вкажіть дату.";
  } else if (values.date > today) {
    errors.date = "Дата не може бути в майбутньому: на неї ще немає курсу НБУ.";
  } else if (values.date < MIN_DATE) {
    errors.date = "Дата занадто давня. Вкажіть дату після 01.01.2000.";
  }
  const amount = cleanAmount(values.amount);
  if (!amount) {
    errors.amount = "Вкажіть суму.";
  } else if (amount.startsWith("-")) {
    errors.amount = "Сума має бути більшою за 0.";
  } else if (!AMOUNT_RE.test(amount)) {
    errors.amount = "Сума має бути числом, наприклад 450 або 1250,50 (до 2 знаків після коми).";
  } else if (Number(amount.replace(",", ".")) <= 0) {
    errors.amount = "Сума має бути більшою за 0.";
  }
  if (values.description.trim().length > MAX_DESCRIPTION) {
    errors.description = `Опис — до ${MAX_DESCRIPTION} символів.`;
  }
  return errors;
}

// Форма створення (transaction = null) або зміни операції
export default function TransactionForm({ car, cars, categories, transaction, onClose, onSaved }) {
  const isEdit = transaction != null;
  const [values, setValues] = useState(() => initialValues(car, transaction));
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState(null);
  const [saving, setSaving] = useState(false);
  const formRef = useRef(null);
  const uid = useId();
  const today = todayInKyiv();

  const typeCategories = categories.filter((c) => c.type === values.type);
  // Продане авто вдруге не продаємо (backend теж перевіряє)
  const incomeBlocked = !isEdit && car.sold;
  const currency = CURRENCIES.find((c) => c.value === values.currency);

  function change(field, value) {
    setValues((v) => ({ ...v, [field]: value }));
    setErrors((e) => ({ ...e, [field]: undefined }));
    setServerError(null);
  }

  function changeType(type) {
    // Категорія має відповідати типу. Якщо категорія одна (дохід — «Продаж авто») — обираємо її одразу
    const list = categories.filter((c) => c.type === type);
    setValues((v) => ({ ...v, type, categoryId: list.length === 1 ? String(list[0].id) : "" }));
    setErrors({});
    setServerError(null);
  }

  const close = () => {
    if (!saving) onClose();
  };

  async function submit(event) {
    event.preventDefault();
    const found = validate(values, today);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      // Курсор — у перше поле з помилкою
      requestAnimationFrame(() => formRef.current?.querySelector('[aria-invalid="true"]')?.focus());
      return;
    }

    setSaving(true);
    setServerError(null);
    const data = {
      car_id: Number(values.carId),
      type: values.type,
      category_id: Number(values.categoryId),
      date: values.date,
      // Рядком, а не числом: так копійки не спотворюються при перетворенні
      amount: cleanAmount(values.amount).replace(",", "."),
      currency: values.currency,
      description: values.description.trim() || null,
    };
    try {
      const saved = isEdit ? await updateTransaction(transaction.id, data) : await createTransaction(data);
      onSaved(saved);
    } catch (err) {
      // Backend не прийняв дані — показуємо його пояснення, форма лишається заповненою
      setServerError(err.message);
      setSaving(false);
    }
  }

  const fieldProps = (name) => ({
    id: `${uid}-${name}`,
    "aria-invalid": errors[name] ? "true" : undefined,
    "aria-describedby": errors[name] ? `${uid}-${name}-error` : undefined,
  });
  const fieldError = (name) =>
    errors[name] && (
      <p className="field-error" id={`${uid}-${name}-error`}>
        {errors[name]}
      </p>
    );

  return (
    <Modal title={isEdit ? "Змінити операцію" : "Нова операція"} onClose={close}>
      <form ref={formRef} className="form" onSubmit={submit} noValidate>
        {isEdit ? (
          <div className="field">
            <label htmlFor={`${uid}-carId`}>Авто</label>
            <select {...fieldProps("carId")} value={values.carId} onChange={(e) => change("carId", e.target.value)}>
              {cars.map((c) => (
                <option
                  key={c.id}
                  value={c.id}
                  // Продаж можна перенести лише на непродане авто
                  disabled={values.type === "income" && c.sold && c.id !== transaction.car_id}
                >
                  {c.title}
                  {c.sold && c.id !== transaction.car_id ? " · продано" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <p className="form-car">
            Авто: <strong>{car.title}</strong>
          </p>
        )}

        <fieldset className="field">
          <legend>Тип</legend>
          <div className="segmented">
            {TYPES.map((t) => {
              const disabled = isEdit || (t.value === "income" && incomeBlocked);
              return (
                <label
                  key={t.value}
                  className={`segment segment-${t.value} ${values.type === t.value ? "is-checked" : ""} ${disabled ? "is-disabled" : ""}`}
                >
                  <input
                    type="radio"
                    name={`${uid}-type`}
                    value={t.value}
                    checked={values.type === t.value}
                    disabled={disabled}
                    onChange={() => changeType(t.value)}
                  />
                  {t.label}
                </label>
              );
            })}
          </div>
          {isEdit && <p className="field-hint">Тип змінити не можна. Якщо помилились — видаліть операцію і створіть нову.</p>}
          {incomeBlocked && <p className="field-hint">Авто вже продано — другий продаж записати не можна.</p>}
          {fieldError("type")}
        </fieldset>

        <div className="form-row">
          <div className="field">
            <label htmlFor={`${uid}-categoryId`}>Категорія</label>
            <select
              {...fieldProps("categoryId")}
              value={values.categoryId}
              onChange={(e) => change("categoryId", e.target.value)}
            >
              <option value="">— оберіть —</option>
              {typeCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {fieldError("categoryId")}
          </div>

          <div className="field">
            <label htmlFor={`${uid}-date`}>Дата</label>
            <input
              {...fieldProps("date")}
              type="date"
              min={MIN_DATE}
              max={today}
              value={values.date}
              onChange={(e) => change("date", e.target.value)}
            />
            {fieldError("date")}
          </div>
        </div>

        <fieldset className="field">
          <legend>Валюта суми</legend>
          <div className="segmented">
            {CURRENCIES.map((c) => (
              <label key={c.value} className={`segment ${values.currency === c.value ? "is-checked" : ""}`}>
                <input
                  type="radio"
                  name={`${uid}-currency`}
                  value={c.value}
                  checked={values.currency === c.value}
                  onChange={() => change("currency", c.value)}
                />
                {c.label}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor={`${uid}-amount`}>Сума</label>
          <div className="input-suffix">
            <input
              {...fieldProps("amount")}
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="наприклад 450 або 1250,50"
              value={values.amount}
              onChange={(e) => change("amount", e.target.value)}
            />
            <span aria-hidden="true">{currency.symbol}</span>
          </div>
          {fieldError("amount")}
          <p className="field-hint">
            Суму в другій валюті backend порахує сам за курсом НБУ на дату операції.
            {isEdit && " Нова дата — новий курс; та сама дата — курс лишається."}
          </p>
        </div>

        <div className="field">
          <label htmlFor={`${uid}-description`}>
            Опис <span className="muted">— необов'язково</span>
          </label>
          <textarea
            {...fieldProps("description")}
            rows={2}
            maxLength={MAX_DESCRIPTION}
            placeholder="наприклад: заміна фар"
            value={values.description}
            onChange={(e) => change("description", e.target.value)}
          />
          {fieldError("description")}
        </div>

        {serverError && (
          <div className="form-error" role="alert">
            <Icon name="warning" />
            <span>{serverError}</span>
          </div>
        )}

        <div className="form-actions">
          <button type="button" className="button button-ghost" onClick={close} disabled={saving}>
            Скасувати
          </button>
          <button type="submit" className="button button-primary" disabled={saving}>
            <Icon name="check" />
            {saving ? "Збереження…" : isEdit ? "Зберегти зміни" : "Додати операцію"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
