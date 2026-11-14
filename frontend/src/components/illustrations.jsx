/* Flat illustrations as React SVG: no image files, no external assets.
 * Colours: the sunrise and green ground come from the theme tokens; the cream
 * and deep-green shapes are fixed because they sit on the hero panel, which is
 * deep green in both themes. */

export function Hero({ className }) {
  return (
    <svg viewBox="0 0 520 380" className={className} aria-hidden="true">
      <circle cx="350" cy="230" r="150" fill="none" stroke="var(--accent)" strokeOpacity="0.18" strokeWidth="3" />
      <circle cx="350" cy="230" r="118" fill="none" stroke="var(--accent)" strokeOpacity="0.35" strokeWidth="3" />
      <circle cx="350" cy="230" r="86" fill="var(--accent)" />
      <path d="M0 305C80 255 160 255 240 290C320 325 420 275 520 295L520 380L0 380Z" fill="#14573F" />
      <path d="M0 340C100 305 200 315 290 340C380 365 450 335 520 345L520 380L0 380Z" fill="#072C1F" />
      <rect x="30" y="64" width="190" height="72" rx="22" fill="#FFF6E8" />
      <path d="M64 136l-8 24l32-24z" fill="#FFF6E8" />
      <rect x="54" y="88" width="122" height="10" rx="5" fill="#0B3F2E" opacity="0.75" />
      <rect x="54" y="108" width="86" height="10" rx="5" fill="#0B3F2E" opacity="0.35" />
      <rect x="262" y="30" width="206" height="66" rx="22" fill="#CFEFDD" />
      <path d="M430 96l10 22l-30-22z" fill="#CFEFDD" />
      <rect x="286" y="52" width="140" height="10" rx="5" fill="#0B3F2E" opacity="0.75" />
      <rect x="286" y="72" width="100" height="10" rx="5" fill="#0B3F2E" opacity="0.35" />
      <g transform="translate(142 178)">
        <line x1="60" y1="0" x2="60" y2="-26" stroke="#FFF6E8" strokeWidth="5" strokeLinecap="round" />
        <circle cx="60" cy="-32" r="9" fill="var(--accent)" />
        <rect x="-10" y="38" width="14" height="30" rx="7" fill="var(--accent)" />
        <rect x="116" y="38" width="14" height="30" rx="7" fill="var(--accent)" />
        <rect x="0" y="0" width="120" height="98" rx="34" fill="#FFF6E8" />
        <rect x="14" y="20" width="92" height="58" rx="24" fill="#0B3F2E" />
        <circle cx="44" cy="46" r="8" fill="#7EE0AE" />
        <circle cx="76" cy="46" r="8" fill="#7EE0AE" />
        <path d="M46 62q14 12 28 0" fill="none" stroke="#7EE0AE" strokeWidth="5" strokeLinecap="round" />
        <rect x="22" y="106" width="76" height="54" rx="22" fill="#FFF6E8" />
        <circle cx="60" cy="133" r="10" fill="#1B7F5A" />
      </g>
    </svg>
  );
}

/* Pip, the AI assistant: a round robot face on a sunrise disc. */
export function PipAvatar({ className = "size-9" }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <circle cx="20" cy="20" r="20" fill="var(--accent)" />
      <line x1="20" y1="6" x2="20" y2="10" stroke="#0B3F2E" strokeWidth="2" strokeLinecap="round" />
      <circle cx="20" cy="5.5" r="2" fill="#0B3F2E" />
      <rect x="7" y="10" width="26" height="22" rx="9" fill="#FFF6E8" />
      <rect x="10.5" y="14" width="19" height="14" rx="6" fill="#0B3F2E" />
      <circle cx="16" cy="20" r="2" fill="#7EE0AE" />
      <circle cx="24" cy="20" r="2" fill="#7EE0AE" />
      <path d="M16.5 24q3.5 3 7 0" fill="none" stroke="#7EE0AE" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/* A wide sunrise over green hills, for card headers and banners; the sun stays
 * in view when the banner is narrow (xMax). */
export function SunriseBanner({ className = "h-24 w-full" }) {
  return (
    <svg viewBox="0 0 1200 96" preserveAspectRatio="xMaxYMid slice" className={className} aria-hidden="true">
      <rect width="1200" height="96" fill="var(--green-tint)" />
      <circle cx="1020" cy="54" r="46" fill="var(--accent)" />
      <path d="M0 70C150 40 300 44 450 62C600 80 750 52 900 58C1020 62 1120 54 1200 60L1200 96L0 96Z" fill="var(--primary)" />
      <path d="M0 82C200 66 380 74 560 84C760 95 980 78 1200 86L1200 96L0 96Z" fill="var(--hero)" />
    </svg>
  );
}
