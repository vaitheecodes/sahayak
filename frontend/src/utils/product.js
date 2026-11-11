/* The product profile from /api/meta (admin Settings -> Product), loaded
 * once before the app renders. Empty name: the product is unnamed and the
 * UI says "the product". The platform itself is Sahayak. */
let product = { name: "", support_team_name: "Support Team" };

export function setProduct(value) {
  if (value) product = { ...product, ...value };
}

// Public customer sign-up (CUSTOMER_SIGNUP_ENABLED on the backend). Open
// until /api/meta says otherwise; the backend refuses a closed sign-up anyway.
let signup = true;

export function setSignupOpen(value) {
  if (typeof value === "boolean") signup = value;
}

export const signupOpen = () => signup;
export const productName = () => product.name;
export const supportTeamName = () => product.support_team_name || "Support Team";
