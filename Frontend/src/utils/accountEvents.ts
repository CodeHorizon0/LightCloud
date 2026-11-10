export const ACCOUNT_INVALIDATED = "lightcloud:account-invalidated";

export function accountChanged(): void {
  window.dispatchEvent(new Event(ACCOUNT_INVALIDATED));
}
