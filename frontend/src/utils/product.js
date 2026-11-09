/* The product profile from /api/meta (admin Settings -> Product), loaded
 * once before the app renders. Empty name: the product is unnamed and the
 * UI says "the product". The platform itself is Sahayak. */
let product = { name: "", support_team_name: "Support Team" };

export function setProduct(value) {
  if (value) product = { ...product, ...value };
}

export const productName = () => product.name;
export const supportTeamName = () => product.support_team_name || "Support Team";
