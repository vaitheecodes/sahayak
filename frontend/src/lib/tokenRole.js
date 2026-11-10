/* The role inside a sign-in token (a JWT: header.payload.signature, the
 * payload base64url JSON). Read only to pick which portal to show; the
 * server verifies the token and checks the role on every call. No imports,
 * so tests/test_frontend_session.py can run it under Node. */
function claim(token, name) {
  if (!token) return null;
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = part + "=".repeat((4 - (part.length % 4)) % 4);
    const value = JSON.parse(atob(padded))[name];
    return typeof value === "string" ? value : null;
  } catch {
    return null;
  }
}

export const roleFromToken = (token) => claim(token, "role");
