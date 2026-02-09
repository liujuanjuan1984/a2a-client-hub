import { apiRequest } from "@/lib/api/client";

export type InvitationStatus = "pending" | "registered" | "revoked" | "expired";

export type InvitationResponse = {
  id: string;
  code: string;
  target_email: string;
  status: InvitationStatus;
  creator_user_id: string;
  target_user_id?: string | null;
  memo?: string | null;
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
  registered_at?: string | null;
  revoked_at?: string | null;
};

export type InvitationWithCreatorResponse = InvitationResponse & {
  creator_email?: string | null;
  creator_name?: string | null;
};

export type InvitationListResponse<TItem> = {
  items: TItem[];
  pagination: {
    page: number;
    size: number;
    total: number;
    pages: number;
  };
  meta: Record<string, unknown>;
};

export type InvitationCreateRequest = {
  email: string;
  memo?: string | null;
};

export const createInvitation = (payload: InvitationCreateRequest) =>
  apiRequest<InvitationResponse, InvitationCreateRequest>("/invitations", {
    method: "POST",
    body: payload,
  });

export const listMyInvitations = (page = 1, size = 100) =>
  apiRequest<InvitationListResponse<InvitationResponse>>("/invitations/mine", {
    query: { page, size },
  });

export const listInvitationsForMe = (page = 1, size = 100) =>
  apiRequest<InvitationListResponse<InvitationWithCreatorResponse>>(
    "/invitations/invited-me",
    { query: { page, size } },
  );

export const revokeInvitation = (invitationId: string) =>
  apiRequest<void>(`/invitations/${encodeURIComponent(invitationId)}`, {
    method: "DELETE",
  });

export const restoreInvitation = (invitationId: string) =>
  apiRequest<InvitationResponse>(
    `/invitations/${encodeURIComponent(invitationId)}/restore`,
    { method: "POST" },
  );
