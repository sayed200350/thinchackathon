/** Taktile icon (taktile.com): five tapering bars. Inherits the text colour through currentColor. */
export function TaktileLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="29.245 29.245 80 80"
      role="img"
      aria-label="Taktile"
      fill="currentColor"
      className={className}
    >
      <path d="M29.245 29.245h16.667v80H29.245zM49.245 29.245h8.334v80h-8.334zM62.434 29.245h5.145v80h-5.145zM79.245 29.245h3.333v80h-3.333zM105.912 29.245h3.333v80h-3.333z" />
    </svg>
  );
}
