// src/services/chat_service.ts
//docstring
// 职责: Chat 用例层，负责调用 API 并映射为 domain 结果。
// 边界: 不读写 stores，不直接渲染 UI；仅负责 Domain Input <-> HTTP DTO 映射与传输层调用编排。
// 上游关系: stores/chat_store.ts（由 store 调用本 service）。
// 下游关系: api/endpoints/chat.ts。
import { apiClient } from '@/api/client'
import { normalizeChatResponse } from '@/services/normalize_chat'
import type { ChatNormalizedResult, ChatSendInput } from '@/types/domain/chat'
import type {
  ChatRequestDTO,
} from '@/types/http/chat_response'
import { toJsonRecord } from '@/utils/json'

const toChatRequestDTO = (input: ChatSendInput): ChatRequestDTO => {
  return {
    query: input.query,
    conversation_id: input.conversationId,
    kb_id: input.kbId,
    debug: input.debug,
    context: input.context
      ? {
        keyword_top_k: input.context.keywordTopK,
        vector_top_k: input.context.vectorTopK,
        fusion_top_k: input.context.fusionTopK,
        rerank_top_k: input.context.rerankTopK,
        fusion_strategy: input.context.fusionStrategy,
        rerank_strategy: input.context.rerankStrategy,
        embed_provider: input.context.embedProvider,
        embed_model: input.context.embedModel,
        embed_dim: input.context.embedDim,
        model_provider: input.context.modelProvider,
        model_name: input.context.modelName,
        prompt_name: input.context.promptName,
        prompt_version: input.context.promptVersion,
        evaluator_config: input.context.evaluatorConfig
          ? toJsonRecord(input.context.evaluatorConfig, 'context.evaluatorConfig')
          : undefined,
        return_records: input.context.returnRecords,
        return_hits: input.context.returnHits,
        extra: input.context.extra ? toJsonRecord(input.context.extra, 'context.extra') : undefined,
      }
      : undefined,
  } as ChatRequestDTO
}

export const sendChat = async (input: ChatSendInput): Promise<ChatNormalizedResult> => {
  const payload = toChatRequestDTO(input)
  const response = await apiClient.postChat(payload)
  return normalizeChatResponse(response)
}
