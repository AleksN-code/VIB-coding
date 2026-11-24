import { useState } from "react";
import { deleteTransaction } from "./api.js";
import { formatDate, formatUah, formatUsd } from "./format.js";
import { Icon } from "./icons.jsx";
import Modal from "./Modal.jsx";

// Підтвердження перед видаленням: показуємо, що саме буде видалено.
// Для продажу — окреме попередження: авто знову стане непроданим.
export default function DeleteTransactionDialog({ transaction: t, onClose, onDeleted }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);
  const isSale = t.type === "income";

  const close = () => {
    if (!deleting) onClose();
  };

  async function confirm() {
    setDeleting(true);
    setError(null);
    try {
      await deleteTransaction(t.id);
      onDeleted(t);
    } catch (err) {
      setError(err.message);
      setDeleting(false);
    }
  }

  return (
    <Modal title="Видалити операцію?" onClose={close} tone="danger">
      <dl className="confirm-details">
        <div>
          <dt>Дата</dt>
          <dd>{formatDate(t.date)}</dd>
        </div>
        <div>
          <dt>Тип</dt>
          <dd>
            <span className={`badge badge-${t.type}`}>{isSale ? "Дохід" : "Витрата"}</span>
          </dd>
        </div>
        <div>
          <dt>Категорія</dt>
          <dd>{t.category}</dd>
        </div>
        <div>
          <dt>Сума</dt>
          <dd>
            {formatUah(t.amount_uah)} · {formatUsd(t.amount_usd)}
          </dd>
        </div>
        {t.description && (
          <div>
            <dt>Опис</dt>
            <dd>{t.description}</dd>
          </div>
        )}
      </dl>

      {isSale && (
        <div className="warning-box">
          <Icon name="warning" />
          <p>
            <strong>Це продаж.</strong> Після видалення авто стане непроданим, а прибуток зникне.
          </p>
        </div>
      )}
      <p className="muted">Операцію буде видалено з бази назавжди.</p>

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
          {deleting ? "Видалення…" : "Видалити"}
        </button>
      </div>
    </Modal>
  );
}
