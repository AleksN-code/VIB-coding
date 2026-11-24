import { useEffect, useId, useRef } from "react";
import { Icon } from "./icons.jsx";

// Вікно поверх сторінки на основі вбудованого в браузер <dialog>:
// сторінка позаду недоступна, Esc закриває, фокус лишається всередині вікна.
export default function Modal({ title, onClose, children, tone }) {
  const ref = useRef(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog.open) dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog
      ref={ref}
      className={`modal ${tone ? `modal-${tone}` : ""}`}
      aria-labelledby={titleId}
      // Esc: браузер хоче закрити вікно сам — замість цього питаємо компонент (він може бути зайнятий збереженням)
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="modal-head">
        <h3 id={titleId}>{title}</h3>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Закрити" title="Закрити">
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}
