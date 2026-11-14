/* The product mark: a sunrise circle with a speech bubble (a help desk that
 * answers). Drawn for this product; colours come from the theme tokens. */
export default function ProductMark({ className = "size-7" }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <circle cx="20" cy="20" r="20" className="fill-accent" />
      <path
        d="M11 14a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4h-6l-5 4v-4h0a4 4 0 0 1-3-4z"
        className="fill-hero"
      />
    </svg>
  );
}
