import { useEffect, useRef } from 'react';

/** Accessible modal: focus moves in on open, Escape closes, focus returns on close. */
export default function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    const first = ref.current?.querySelector('input, button, select, textarea');
    first?.focus();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="nb-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="nb-modal" role="dialog" aria-modal="true" aria-labelledby="nb-modal-title" ref={ref}>
        <h2 id="nb-modal-title" className="nb-card-title">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function ConfirmModal({ title, body, confirmLabel, danger, busy, error, onConfirm, onClose }) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="nb-muted nb-modal-body">{body}</p>
      {error ? <div className="nb-alert nb-alert-error" role="alert">{error}</div> : null}
      <div className="nb-modal-actions">
        <button type="button" className="nb-btn nb-btn-secondary" onClick={onClose}>Cancel</button>
        <button type="button" className={`nb-btn ${danger ? 'nb-btn-danger' : 'nb-btn-primary'}`} onClick={onConfirm} disabled={busy} aria-busy={busy || undefined}>
          {busy ? <span className="nb-spinner" aria-hidden="true" /> : null}{confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
