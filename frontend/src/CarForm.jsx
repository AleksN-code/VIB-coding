import { useId, useRef, useState } from "react";
import { createCar, updateCar } from "./api.js";
import { Icon } from "./icons.jsx";
import Modal from "./Modal.jsx";

// Ті самі правила, що в боті й на backend (app/rules.py); backend перевіряє все ще раз
const MAX_NAME = 50;
const MIN_YEAR = 1950;
const VIN_RE = /^[A-HJ-NPR-Z0-9]{17}$/; // 17 символів, латиниця й цифри, без I, O, Q

function validate(values) {
  const errors = {};
  const maxYear = new Date().getFullYear() + 1;
  if (!values.ownerId) {
    errors.ownerId = "Оберіть власника авто.";
  }
  if (!values.brand.trim()) {
    errors.brand = "Вкажіть марку, наприклад BMW.";
  } else if (values.brand.trim().length > MAX_NAME) {
    errors.brand = `Марка — до ${MAX_NAME} символів.`;
  }
  if (!values.model.trim()) {
    errors.model = "Вкажіть модель, наприклад X5.";
  } else if (values.model.trim().length > MAX_NAME) {
    errors.model = `Модель — до ${MAX_NAME} символів.`;
  }
  const year = values.year.trim();
  if (!year) {
    errors.year = "Вкажіть рік випуску.";
  } else if (!/^\d{4}$/.test(year) || Number(year) < MIN_YEAR || Number(year) > maxYear) {
    errors.year = `Рік випуску — від ${MIN_YEAR} до ${maxYear}, наприклад 2018.`;
  }
  const vin = values.vin.trim();
  if (vin && !VIN_RE.test(vin)) {
    errors.vin = "VIN — 17 символів: латинські літери (без I, O, Q) і цифри.";
  }
  return errors;
}

// Форма додавання (car = null) або зміни авто
export default function CarForm({ car, users, onClose, onSaved }) {
  const isEdit = car != null;
  const [values, setValues] = useState(() => ({
    // Якщо власник один — обираємо його одразу
    ownerId: isEdit ? String(car.owner_id) : users.length === 1 ? String(users[0].id) : "",
    brand: car?.brand ?? "",
    model: car?.model ?? "",
    year: car ? String(car.year) : "",
    vin: car?.vin ?? "",
  }));
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState(null);
  const [saving, setSaving] = useState(false);
  const formRef = useRef(null);
  const uid = useId();

  function change(field, value) {
    setValues((v) => ({ ...v, [field]: value }));
    setErrors((e) => ({ ...e, [field]: undefined }));
    setServerError(null);
  }

  const close = () => {
    if (!saving) onClose();
  };

  async function submit(event) {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      requestAnimationFrame(() => formRef.current?.querySelector('[aria-invalid="true"]')?.focus());
      return;
    }

    setSaving(true);
    setServerError(null);
    const data = {
      owner_id: Number(values.ownerId),
      brand: values.brand.trim(),
      model: values.model.trim(),
      year: Number(values.year.trim()),
      vin: values.vin.trim() || null,
    };
    try {
      const saved = isEdit ? await updateCar(car.id, data) : await createCar(data);
      onSaved(saved, !isEdit);
    } catch (err) {
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

  const ownerChanged = isEdit && values.ownerId !== String(car.owner_id);

  return (
    <Modal title={isEdit ? "Змінити авто" : "Нове авто"} onClose={close}>
      <form ref={formRef} className="form" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor={`${uid}-ownerId`}>Власник</label>
          <select {...fieldProps("ownerId")} value={values.ownerId} onChange={(e) => change("ownerId", e.target.value)}>
            <option value="">— оберіть —</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          {fieldError("ownerId")}
          <p className="field-hint">
            {ownerChanged
              ? "Авто разом з усіма операціями перейде до нового власника."
              : "Власник бачитиме це авто в Telegram-боті."}
          </p>
        </div>

        <div className="form-row">
          <div className="field">
            <label htmlFor={`${uid}-brand`}>Марка</label>
            <input
              {...fieldProps("brand")}
              maxLength={MAX_NAME}
              autoComplete="off"
              placeholder="BMW"
              value={values.brand}
              onChange={(e) => change("brand", e.target.value)}
            />
            {fieldError("brand")}
          </div>
          <div className="field">
            <label htmlFor={`${uid}-model`}>Модель</label>
            <input
              {...fieldProps("model")}
              maxLength={MAX_NAME}
              autoComplete="off"
              placeholder="X5"
              value={values.model}
              onChange={(e) => change("model", e.target.value)}
            />
            {fieldError("model")}
          </div>
        </div>

        <div className="form-row">
          <div className="field">
            <label htmlFor={`${uid}-year`}>Рік випуску</label>
            <input
              {...fieldProps("year")}
              inputMode="numeric"
              maxLength={4}
              autoComplete="off"
              placeholder="2018"
              value={values.year}
              onChange={(e) => change("year", e.target.value)}
            />
            {fieldError("year")}
          </div>
          <div className="field">
            <label htmlFor={`${uid}-vin`}>
              VIN <span className="muted">— необов'язково</span>
            </label>
            <input
              {...fieldProps("vin")}
              className="vin-input"
              maxLength={17}
              autoComplete="off"
              spellCheck={false}
              placeholder="17 символів"
              value={values.vin}
              // VIN завжди великими літерами
              onChange={(e) => change("vin", e.target.value.toUpperCase())}
            />
            {fieldError("vin")}
          </div>
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
            {saving ? "Збереження…" : isEdit ? "Зберегти зміни" : "Додати авто"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
