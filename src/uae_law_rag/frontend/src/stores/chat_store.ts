// src/stores/chat_store.ts
//docstring
// 职责: Chat 状态容器的最小实现（可替换为专业状态库）；负责持有回放状态并提供 actions。
// 边界: 不直接调用 api/endpoints；不解析 HTTP DTO（只消费 service 输出的 domain 结果）。
// 上游关系: services/chat_service.ts。
// 下游关系: pages/chat（读取状态与触发 actions）。
import { sendChat } from '@/services/chat_service'
import type { ChatSendInput } from '@/types/domain/chat'
import type { ChatNormalizedResult } from '@/types/domain/chat'

type ChatStoreState = {
  results: ChatNormalizedResult[]
}

const initialState: ChatStoreState = {
  results: [],
}

let state: ChatStoreState = { ...initialState }

export const chatStore = {
  getState: () => state,
  setState: (next: Partial<ChatStoreState>) => {
    state = { ...state, ...next }
  },

  // --- Actions (M1 minimal) ---

  appendResult: (result: ChatNormalizedResult) => {
    state = { ...state, results: [...state.results, result] }
  },

  sendChatAndAppend: async (input: ChatSendInput): Promise<ChatNormalizedResult> => {
    const result = await sendChat(input)
    state = { ...state, results: [...state.results, result] }
    return result
  },

  reset: () => {
    state = { ...initialState }
  },
}
