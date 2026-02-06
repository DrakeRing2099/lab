export function validateSession(token: string): boolean {
  if (!token) return false;
  return token.startsWith("sess_");
}
