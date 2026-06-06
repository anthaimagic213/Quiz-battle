import  apiClient  from "@/services/api";
import { UUID } from "crypto";

export interface Conversation {
  id: UUID;
  type: string;
  title?: string;
  created_at: string;
  updated_at: string;
  last_message_at?: string;
}

export interface ConversationDetail extends Conversation {
  members: ConversationMember[];
  message_count?: number;
}

export interface ConversationMember {
  id: UUID;
  conversation_id: UUID;
  user_id: UUID;
  role: string;
  last_read_at?: string;
  joined_at: string;
}

export interface Message {
  id: UUID;
  conversation_id: UUID;
  sender_id: UUID;
  sender_type: string;
  content: string;
  is_ai_generated: boolean;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
  sender_username?: string;
  sender_avatar_url?: string;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
}

export const conversationsService = {
  // List all conversations
  async listConversations(): Promise<Conversation[]> {
    const response = await apiClient.get("/conversations");
    return response.data;
  },

  // Create a direct conversation with a friend
  async createDirectConversation(friendId: UUID): Promise<Conversation> {
    const response = await apiClient.post("/conversations", {
      type: "direct",
      member_ids: [friendId],
    });
    return response.data;
  },

  // Get conversation details
  async getConversation(conversationId: UUID): Promise<ConversationDetail> {
    const response = await apiClient.get(
      `/api/v1/conversations/${conversationId}`
    );
    return response.data;
  },

  // Update conversation (group title)
  async updateConversation(
    conversationId: UUID,
    title: string
  ): Promise<Conversation> {
    const response = await apiClient.put(
      `/api/v1/conversations/${conversationId}`,
      { title }
    );
    return response.data;
  },
};

export const messagesService = {
  // Send message
  async sendMessage(
    conversationId: UUID,
    content: string,
    metadata?: Record<string, any>
  ): Promise<Message> {
    const response = await apiClient.post(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        content,
        metadata,
      }
    );
    return response.data;
  },

  // Get messages
  async getMessages(
    conversationId: UUID,
    limit: number = 50,
    offset: number = 0
  ): Promise<MessageListResponse> {
    const response = await apiClient.get(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        params: {
          limit,
          offset,
        },
      }
    );
    return response.data;
  },

  // Update message
  async updateMessage(
    conversationId: UUID,
    messageId: UUID,
    content: string
  ): Promise<Message> {
    const response = await apiClient.put(
      `/conversations/${conversationId}/messages/${messageId}`,
      { content }
    );
    return response.data;
  },

  // Delete message
  async deleteMessage(
    conversationId: UUID,
    messageId: UUID
  ): Promise<void> {
    await apiClient.delete(
      `/conversations/${conversationId}/messages/${messageId}`
    );
  },

  // Mark conversation as read
  async markAsRead(conversationId: UUID): Promise<void> {
    await apiClient.post(
      `/conversations/${conversationId}/messages/mark-read`,
      {}
    );
  },
};
