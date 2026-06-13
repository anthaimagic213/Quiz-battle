import  apiClient  from "@/services/api";
import { UUID } from "crypto";

export interface User {
  id: UUID;
  username: string;
  full_name?: string;
  email?: string;
  avatar_url?: string;
}

export interface FriendRequest {
  id: UUID;
  requester_id: UUID;
  addressee_id: UUID;
  status: string;
  created_at: string;
  requester?: User;
}

export interface Friendship {
  id: UUID;
  user_id_1: UUID;
  user_id_2: UUID;
  created_at: string;
  friend?: User;
}

export interface SearchUsersResponse {
  users: User[];
  total: number;
  page: number;
  page_size: number;
}

export const friendsService = {
  // Get all friends
  async getFriends(): Promise<Friendship[]> {
    const response = await apiClient.get("/friends/list");
    return response.data;
  },

  // Send friend request
  async sendFriendRequest(addresseeId: UUID): Promise<FriendRequest> {
    const response = await apiClient.post("/friends/requests", {
      addressee_id: addresseeId,
    });
    return response.data;
  },

  // Get pending friend requests
  async getPendingRequests(): Promise<FriendRequest[]> {
    const response = await apiClient.get("/friends/requests/pending");
    return response.data;
  },

  // Accept/reject friend request
  async respondFriendRequest(
    requestId: UUID,
    status: "accepted" | "rejected"
  ): Promise<FriendRequest> {
    const response = await apiClient.post(
      `/friends/requests/${requestId}/respond`,
      { status }
    );
    return response.data;
  },

  // Search users
  async searchUsers(
    query: string,
    page: number = 1,
    limit: number = 10
  ): Promise<SearchUsersResponse> {
    const response = await apiClient.get("/users/search", {
      params: {
        q: query,
        page,
        limit,
      },
    });
    return response.data;
  },
};
