import {
  MOCKED_STORAGE_STATE,
  removeStorageState,
} from "./_auth-state";

export default function globalTeardown(): void {
  removeStorageState(MOCKED_STORAGE_STATE);
}
