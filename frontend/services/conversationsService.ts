import apiClient from "@/services/api";

export interface OtherMemberInfo {
  id: string;
  username: string;
  full_name?: string | null;
  avatar_url?: string | null;
}

export interface Conversation {
  id: string;
  type: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  other_member?: OtherMemberInfo | null;
  last_message_preview?: string | null;
  unread_count?: number;
}

export interface ConversationDetail extends Conversation {
  members: ConversationMember[];
  message_count?: number;
}

export interface ConversationMember {
  id: string;
  conversation_id: string;
  user_id: string;
  role: string;
  last_read_at?: string | null;
  joined_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_type: string;
  content: string;
  is_ai_generated: boolean;
  metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
  sender_username?: string | null;
  sender_full_name?: string | null;
  sender_avatar_url?: string | null;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
}

export const conversationsService = {
  // List all conversations for the current user (with other-member info embedded)
  async listConversations(): Promise<Conversation[]> {
    const response = await apiClient.get("/conversations");
    return response.data;
  },

  // Create or get the 1-1 conversation with another user.
  // Returns the conversation enriched with the other user's profile.
  async createDirectConversation(friendId: string): Promise<Conversation> {
    const response = await apiClient.post(`/conversations/direct/${friendId}`);
    return response.data;
  },

  // Generic creator used by the original UI (kept for backwards compatibility).
  async createConversation(payload: {
    type: "direct" | "group";
    member_ids?: string[];
    title?: string;
  }): Promise<Conversation> {
    const response = await apiClient.post("/conversations", payload);
    return response.data;
  },

  // Get conversation details
  async getConversation(conversationId: string): Promise<ConversationDetail> {
    const response = await apiClient.get(`/conversations/${conversationId}`);
    return response.data;
  },

  // Update conversation (group title)
  async updateConversation(
    conversationId: string,
    title: string
  ): Promise<Conversation> {
    const response = await apiClient.put(`/conversations/${conversationId}`, {
      title,
    });
    return response.data;
  },
};

export const messagesService = {
  // Send message
  async sendMessage(
    conversationId: string,
    content: string,
    metadata?: Record<string, any>
  ): Promise<Message> {
    const response = await apiClient.post(
      `/conversations/${conversationId}/messages`,
      { content, metadata }
    );
    return response.data;
  },

  // Get messages
  async getMessages(
    conversationId: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<MessageListResponse> {
    const response = await apiClient.get(
      `/conversations/${conversationId}/messages`,
      { params: { limit, offset } }
    );
    return response.data;
  },

  // Update message
  async updateMessage(
    conversationId: string,
    messageId: string,
    content: string
  ): Promise<Message> {
    const response = await apiClient.put(
      `/conversations/${conversationId}/messages/${messageId}`,
      { content }
    );
    return response.data;
  },

  // Delete message
  async deleteMessage(conversationId: string, messageId: string): Promise<void> {
    await apiClient.delete(
      `/conversations/${conversationId}/messages/${messageId}`
    );
  },

  // Mark conversation as read
  async markAsRead(conversationId: string): Promise<void> {
    await apiClient.post(
      `/conversations/${conversationId}/messages/mark-read`,
      {}
    );
  },
};
