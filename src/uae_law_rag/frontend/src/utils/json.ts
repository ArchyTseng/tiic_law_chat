// src/utils/json.ts
//docstring
// 职责: 提供 unknown -> JsonValue 的安全收口与校验（用于 service 层将 domain extra/config 映射为 HTTP DTO）。
// 边界: 仅纯函数与类型守卫；不依赖 api/services/stores/pages；不做 IO。
// 上游关系: domain 输入（unknown）与 types/http/json.ts（JsonValue）。
// 下游关系: services/*（构造 request DTO 时的 JSON-safe 映射）。
import type { JsonValue } from '@/types/http/json'
import { InvariantError } from '@/utils/assert'

export function isJsonValue(value: unknown): value is JsonValue {
    if (value === null) return true
    const t = typeof value
    if (t === 'string' || t === 'number' || t === 'boolean') return true
    if (Array.isArray(value)) return value.every(isJsonValue)
    if (t === 'object') {
        // plain object
        const obj = value as Record<string, unknown>
        return Object.values(obj).every(isJsonValue)
    }
    return false
}

export function toJsonValue(value: unknown, path = '$'): JsonValue {
    if (isJsonValue(value)) return value
    throw new InvariantError('Value is not JSON-serializable', { path })
}

export function toJsonRecord(value: unknown, path = '$'): Record<string, JsonValue> {
    const v = toJsonValue(value, path)
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        return v as Record<string, JsonValue>
    }
    throw new InvariantError('Value is not a JSON object', { path })
}
