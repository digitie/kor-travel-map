import {
  LIVE_STORAGE_STATE,
  removeStorageState,
} from "../_auth-state";

export default function globalTeardown(): void {
  removeStorageState(LIVE_STORAGE_STATE);
}
