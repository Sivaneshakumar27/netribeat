import { useEffect, useId, useState } from 'react';

export function Button({ variant = 'secondary', block, busy, children, className = '', ...rest }) {
  return (
    <button
      type="button"
      className={`nb-btn nb-btn-${variant}${block ? ' nb-btn-block' : ''} ${className}`}
      disabled={busy || rest.disabled}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className="nb-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

export function Field({ label, error, hint, type = 'text', value, onChange, ...rest }) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const isPassword = type === 'password';
  const describedBy = [error && `${id}-err`, hint && `${id}-hint`].filter(Boolean).join(' ') || undefined;
  return (
    <div className={`nb-field${error ? ' is-invalid' : ''}`}>
      <label className="nb-field-label" htmlFor={id}>{label}</label>
      <div className="nb-input-wrap">
        <input
          id={id}
          className="nb-input"
          type={isPassword && shown ? 'text' : type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...rest}
        />
        {isPassword ? (
          <button
            type="button"
            className="nb-reveal"
            onClick={() => setShown((s) => !s)}
            aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          >
            {shown ? 'Hide' : 'Show'}
          </button>
        ) : null}
      </div>
      {hint && !error ? <div id={`${id}-hint`} className="nb-field-hint">{hint}</div> : null}
      {error ? <div id={`${id}-err`} className="nb-field-error">{error}</div> : null}
    </div>
  );
}

export function Alert({ tone = 'error', children }) {
  if (!children) return null;
  return (
    <div className={`nb-alert nb-alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

const PULSE = 'M2 13h5l2-5 3 10 2.5-7 1.5 2H22';

export function BrandMark({ size = 18 }) {
  return (
    <span className="nb-brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size} height={size}>
        <path d={PULSE} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function Wordmark() {
  return <span className="nb-wordmark">Netri<span>Beat</span></span>;
}

/** Two-column auth screen from the prototype: dark brand panel + form card. */
export function AuthLayout({ title, subtitle, children, onSubmit, badge }) {
  return (
    <main className="nb-auth">
      <section className="nb-auth-brand" aria-hidden="true">
        <svg className="nb-auth-wave" viewBox="0 0 600 80" preserveAspectRatio="none">
          <path d="M0 52 L120 52 L135 52 L142 30 L150 70 L158 8 L166 64 L174 52 L300 52 L315 52 L322 30 L330 70 L338 8 L346 64 L354 52 L480 52 L495 52 L502 30 L510 70 L518 8 L526 64 L534 52 L600 52" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
        <div className="nb-auth-logo"><BrandMark /><Wordmark /></div>
        <p className="nb-auth-lede">Heart rate, load and HRV analysis for recorded training sessions.</p>
        <ol className="nb-steps">
          <li><span>01</span>Create your account and verify your email</li>
          <li><span>02</span>Upload a recording to your own record</li>
          <li><span>03</span>Review the analysis — only you and admins can see it</li>
        </ol>
      </section>
      <form className="nb-auth-card" onSubmit={(e) => { e.preventDefault(); onSubmit(); }} noValidate>
        {badge ? <span className="nb-badge">{badge}</span> : null}
        <h1 className="nb-auth-title">{title}</h1>
        {subtitle ? <p className="nb-auth-sub">{subtitle}</p> : null}
        {children}
      </form>
    </main>
  );
}

/** Seconds left on a resend cooldown, ticking once a second. */
export function useCooldown() {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return undefined;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, setLeft];
}
