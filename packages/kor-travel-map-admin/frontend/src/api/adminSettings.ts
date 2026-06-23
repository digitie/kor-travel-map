import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, postJson, pathWithQuery } from "./client";

export type PublicApiKeyState = "active" | "revoked";

export type PublicApiKeyRecord = {
  public_api_key_id: string;
  key_hint: string;
  state: PublicApiKeyState;
  created_at: string;
  label?: string | null;
  created_by?: string | null;
  revoked_at?: string | null;
  revoked_by?: string | null;
};

export type PublicApiKeyListResponse = {
  data: { items: PublicApiKeyRecord[] };
  meta: { page_size?: number | null };
};

export type PublicApiKeyCreateResponse = {
  data: {
    key: string;
    item: PublicApiKeyRecord;
  };
  meta: Record<string, unknown>;
};

export type AdminAuthEventRecord = {
  auth_event_id: string;
  event_type: "login" | "logout";
  outcome: "succeeded" | "failed" | "denied";
  attempted_username?: string | null;
  actor?: string | null;
  reason?: string | null;
  next_path?: string | null;
  client_ip?: string | null;
  user_agent?: string | null;
  request_id?: string | null;
  created_at: string;
};

export type AdminAuthEventListResponse = {
  data: { items: AdminAuthEventRecord[] };
  meta: { page_size?: number | null };
};

export function usePublicApiKeys() {
  return useQuery<PublicApiKeyListResponse, Error>({
    queryKey: ["admin-settings", "public-api-keys"],
    queryFn: ({ signal }) =>
      getJson<PublicApiKeyListResponse>(
        pathWithQuery("/v1/admin/public-api-keys", { page_size: 100 }),
        { signal },
      ),
    staleTime: 0,
  });
}

export function useAdminAuthEvents() {
  return useQuery<AdminAuthEventListResponse, Error>({
    queryKey: ["admin-settings", "auth-events"],
    queryFn: ({ signal }) =>
      getJson<AdminAuthEventListResponse>(
        pathWithQuery("/v1/admin/auth-events", { page_size: 100 }),
        { signal },
      ),
    staleTime: 10_000,
  });
}

export function useCreatePublicApiKeyMutation() {
  const queryClient = useQueryClient();
  return useMutation<PublicApiKeyCreateResponse, Error, { label?: string | null }>({
    mutationFn: (body) =>
      postJson<PublicApiKeyCreateResponse>("/v1/admin/public-api-keys", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin-settings", "public-api-keys"],
      });
    },
  });
}

export function useRevokePublicApiKeyMutation() {
  const queryClient = useQueryClient();
  return useMutation<PublicApiKeyRecord, Error, string>({
    mutationFn: async (publicApiKeyId) => {
      const response = await postJson<{ data: PublicApiKeyRecord }>(
        `/v1/admin/public-api-keys/${encodeURIComponent(publicApiKeyId)}/revoke`,
        {},
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin-settings", "public-api-keys"],
      });
    },
  });
}
