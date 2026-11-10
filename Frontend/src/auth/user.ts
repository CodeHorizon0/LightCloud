import { isRecord } from "../api";

export interface User {
  id: string;
  username: string;
}

export function parseUser(value: unknown): User | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.username !== "string"
  )
    return null;
  return { id: value.id, username: value.username };
}

export function sameUser(first: User | null, second: User): boolean {
  return first?.id === second.id && first.username === second.username;
}
