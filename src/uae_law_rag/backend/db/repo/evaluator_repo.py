# src/uae_law_rag/backend/db/repo/evaluator_repo.py

"""
[职责] EvaluatorRepo：EvaluationRecordModel 的数据访问层（创建/查询），供 services/pipelines 落库与前端查询使用。
[边界] 不实现 evaluator 规则；不依赖 Milvus；仅处理 SQLAlchemy 会话与持久化一致性。
[上游关系] pipelines/evaluator 产出 EvaluationResult；services 将其转换并写入本 repo。
[下游关系] API 层用于按 message_id/conversation_id 获取评估结果；sql_gate 用于回归断言。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.evaluator import EvaluationRecordModel


class EvaluatorRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session  # docstring: SQLAlchemy AsyncSession

    async def get_record(self, evaluation_record_id: str) -> Optional[EvaluationRecordModel]:
        """Fetch evaluation record by id."""  # docstring: 回放与调试
        return await self._session.get(EvaluationRecordModel, evaluation_record_id)

    async def create(
        self,
        *,
        conversation_id: str,
        message_id: str,
        retrieval_record_id: str,
        generation_record_id: Optional[str],
        status: str,
        rule_version: str,
        config: Dict[str, Any],
        checks: Dict[str, Any],
        scores: Dict[str, Any],
        error_message: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> EvaluationRecordModel:
        """Insert evaluation record (1 message -> 1 evaluation)."""  # docstring: 落库入口
        obj = EvaluationRecordModel(
            conversation_id=conversation_id,
            message_id=message_id,
            retrieval_record_id=retrieval_record_id,
            generation_record_id=generation_record_id,
            status=status,
            rule_version=rule_version,
            config=config,
            checks=checks,
            scores=scores,
            error_message=error_message,
            meta=meta or {},
        )
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def get_by_message_id(self, message_id: str) -> Optional[EvaluationRecordModel]:
        """Fetch evaluation record by message_id."""  # docstring: 1:1 查询
        stmt = select(EvaluationRecordModel).where(EvaluationRecordModel.message_id == message_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_latest_by_conversation_id(self, conversation_id: str) -> Optional[EvaluationRecordModel]:
        """Fetch latest evaluation record by conversation_id."""  # docstring: 会话维度最近评估
        stmt = (
            select(EvaluationRecordModel)
            .where(EvaluationRecordModel.conversation_id == conversation_id)
            .order_by(EvaluationRecordModel.created_at.desc())  # docstring: 依赖 Base 提供 created_at
            .limit(1)
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()
