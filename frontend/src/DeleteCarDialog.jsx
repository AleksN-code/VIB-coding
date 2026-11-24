import { useState } from "react";
import { deleteCar } from "./api.js";
import { formatDate, plural } from "./format.js";
import { Icon } from "./icons.jsx";
import Modal from "./Modal.jsx";

// Підтвердження перед видаленням авто: разом з ним видаляються всі його операції
export default function DeleteCarDialog({ car, onClose, onDeleted }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);
  const count = car.transactions_count;

  const close = () => {
    if (!deleting) onClose();
  };

  async function confirm() {
    setDeleting(true);
    setError(null);
    try {
      await deleteCar(car.id);
      onDeleted(car);
    } catch (err) {
      setError(err.message);
      setDeleting(false);
    }
  }

  return (
    <Modal title="Видалити авто?" onClose={close} tone="danger">
      <dl className="confirm-details">
        <div>
          <dt>Авто</dt>
          <dd>{car.title}</dd>
        </div>
        {car.vin && (
          <div>
            <dt>VIN</dt>
            <dd>{car.vin}</dd>
          </div>
        )}
        <div>
          <dt>Власник</dt>
          <dd>{car.owner}</dd>
        </div>
        <div>
          <dt>Статус</dt>
          <dd>{car.sold ? `Продано ${formatDate(car.sale_date)}` : "В роботі"}</dd>
        </div>
      </dl>

      {count > 0 ? (
        <div className="warning-box">
          <Icon name="warning" />
          <p>
            <strong>Разом з авто буде видалено {plural(count, "операцію", "операції", "операцій")}</strong>
            {car.sold ? " — витрати й продаж. Прибуток по цьому авто теж зникне." : " — усі витрати по ньому."}
          </p>
        </div>
      ) : (
        <p className="muted">Операцій по цьому авто немає.</p>
      )}
      <p className="muted">Авто зникне і з сайту, і з Telegram-бота. Скасувати це неможливо.</p>

      {error && (
        <div className="form-error" role="alert">
          <Icon name="warning" />
          <span>{error}</span>
        </div>
      )}

      <div className="form-actions">
        <button type="button" className="button button-ghost" onClick={close} disabled={deleting}>
          Скасувати
        </button>
        <button type="button" className="button button-danger" onClick={confirm} disabled={deleting}>
          <Icon name="trash" />
          {deleting ? "Видалення…" : count > 0 ? "Видалити авто й операції" : "Видалити авто"}
        </button>
      </div>
    </Modal>
  );
}
