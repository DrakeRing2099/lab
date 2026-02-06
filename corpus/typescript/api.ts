import { validateSession } from "./session";

export function handleRequest(token: string) {
  return validateSession(token);
}
