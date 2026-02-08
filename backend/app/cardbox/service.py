"""High level helpers for interacting with Cardbox."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from card_box_core.structures import Card, CardBox, TextContent

from app.cardbox.engine_factory import create_engine
from app.cardbox.utils import cardbox_for_session, tenant_for_user
from app.core.logging import get_logger
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.utils.json_encoder import json_dumps
from app.utils.timezone_util import utc_now_iso

logger = get_logger(__name__)


class CardBoxService:
    """Wraps common Cardbox operations used throughout Compass.

    The service keeps a lightweight in-memory cache of recently accessed
    ``CardBox`` instances. The cache primarily targets short-lived request
    cycles so we can avoid hitting DuckDB multiple times when appending several
    cards in sequence. The cache is intentionally simple and can be replaced
    with a more advanced strategy in the future.
    """

    def __init__(self) -> None:
        self._box_cache: Dict[Tuple[str, str], CardBox] = {}
        self._engine_cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    def clear_cache(self) -> None:
        """Clear the local CardBox cache."""

        self._box_cache.clear()
        self._engine_cache.clear()

    def _cache_key(self, tenant_id: str, box_name: str) -> Tuple[str, str]:
        return tenant_id, box_name

    def _get_engine(self, tenant_id: str) -> Any:
        """Return a cached ``ContextEngine`` for the tenant."""

        engine = self._engine_cache.get(tenant_id)
        if engine is None:
            engine = create_engine(tenant_id)
            self._engine_cache[tenant_id] = engine
        return engine

    def _get_box(
        self, tenant_id: str, box_name: str, *, engine: Optional[Any] = None
    ) -> CardBox:
        """Return a ``CardBox``, initialising it if necessary."""

        cache_key = self._cache_key(tenant_id, box_name)
        if cache_key in self._box_cache:
            box = self._box_cache[cache_key]
            logger.info(
                f"_get_box called with tenant_id={tenant_id}, box_name={box_name}, box_length={len(box.card_ids)}, cache_hit"
            )
            return box

        engine = engine or self._get_engine(tenant_id)
        storage = engine.storage_adapter
        box = storage.load_card_box(box_name, tenant_id)
        if box is None:
            box = CardBox()
            storage.save_card_box(box, name=box_name, tenant_id=tenant_id)
            logger.info(
                f"_get_box called with tenant_id={tenant_id}, box_name={box_name}, box_length={len(box.card_ids)}, box_created"
            )
        self._box_cache[cache_key] = box
        return box

    def _save_box(
        self,
        tenant_id: str,
        box_name: str,
        box: CardBox,
        *,
        engine: Optional[Any] = None,
    ) -> None:
        logger.info(f"_save_box called with tenant_id={tenant_id}, box_name={box_name}")
        engine = engine or self._get_engine(tenant_id)
        engine.storage_adapter.save_card_box(box, name=box_name, tenant_id=tenant_id)
        self._box_cache[self._cache_key(tenant_id, box_name)] = box

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def ensure_session_box(self, session: AgentSession) -> str:
        """Ensure the session has an associated CardBox with a manifest."""

        tenant_id = tenant_for_user(session.user_id)
        box_name = session.cardbox_name or cardbox_for_session(session)
        engine = self._get_engine(tenant_id)
        box = self._get_box(tenant_id, box_name, engine=engine)
        box = self._ensure_session_manifest(
            session=session,
            tenant_id=tenant_id,
            box_name=box_name,
            engine=engine,
            box=box,
        )
        session.cardbox_name = box_name
        return box_name

    def _ensure_session_manifest(
        self,
        *,
        session: AgentSession,
        tenant_id: str,
        box_name: str,
        engine: Any,
        box: CardBox,
    ) -> CardBox:
        """Insert or refresh the manifest card for a session CardBox."""

        existing_ids = list(box.card_ids or [])
        current_manifest = None
        if existing_ids:
            first_card = engine.card_store.get(existing_ids[0])
            if first_card and isinstance(first_card, Card):
                manifest_type = (
                    first_card.metadata.get("type") if first_card.metadata else None
                )
                module = (
                    first_card.metadata.get("module") if first_card.metadata else None
                )
                if manifest_type == "context_manifest" and module == "chat":
                    current_manifest = first_card

        desired_title = session.name or "Chat Session"
        should_refresh = True

        if current_manifest is not None:
            title_matches = current_manifest.metadata.get("title") == desired_title
            session_id_matches = current_manifest.metadata.get("session_id") == (
                str(session.id) if session.id else None
            )
            if title_matches and session_id_matches:
                should_refresh = False

        if not should_refresh:
            return box

        manifest_card = self._build_session_manifest_card(session)
        engine.card_store.add(manifest_card)

        new_box = CardBox()
        new_box.add(manifest_card.card_id)
        for card_id in existing_ids:
            if current_manifest and card_id == current_manifest.card_id:
                continue
            new_box.add(card_id)

        self._save_box(tenant_id, box_name, new_box, engine=engine)
        return new_box

    def _build_session_manifest_card(self, session: AgentSession) -> Card:
        """Create a manifest card describing a chat session CardBox."""

        title = session.name or "Chat Session"
        payload = {
            "session_id": str(session.id) if session.id else None,
            "title": title,
            "updated_at": (
                session.updated_at.isoformat()
                if getattr(session, "updated_at", None)
                else utc_now_iso()
            ),
        }
        content = TextContent(text=json_dumps(payload, ensure_ascii=False, indent=2))
        metadata = {
            "type": "context_manifest",
            "module": "chat",
            "title": title,
            "session_id": payload["session_id"],
            "source": "chat_session",
            "updated_at": payload["updated_at"],
            "indexable": False,
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}
        return Card(content=content, metadata=metadata)

    def add_cards(self, tenant_id: str, box_name: str, cards: Iterable[Card]) -> None:
        """Persist cards and append them to a ``CardBox``."""

        logger.info(
            f"add_cards called with tenant_id={tenant_id}, box_name={box_name}, cards={len(cards)}"
        )

        engine = self._get_engine(tenant_id)
        box = self._get_box(tenant_id, box_name, engine=engine)

        for card in cards:
            engine.card_store.add(card)
            box.add(card.card_id)

        self._save_box(tenant_id, box_name, box, engine=engine)

    def replace_box(
        self,
        tenant_id: str,
        box_name: str,
        cards: Iterable[Card],
        *,
        allow_overwrite: bool = True,
    ) -> CardBox:
        """Create or replace a ``CardBox`` with the provided cards."""

        engine = self._get_engine(tenant_id)
        storage = engine.storage_adapter

        existing = storage.load_card_box(box_name, tenant_id)
        if existing is not None and not allow_overwrite:
            raise ValueError(
                f"CardBox '{box_name}' already exists for tenant '{tenant_id}'"
            )

        materialised: List[Card] = []
        for card in cards:
            engine.card_store.add(card)
            materialised.append(card)

        new_box = CardBox()
        for card in materialised:
            new_box.add(card.card_id)

        storage.save_card_box(new_box, name=box_name, tenant_id=tenant_id)
        self._box_cache[self._cache_key(tenant_id, box_name)] = new_box
        logger.info(
            "replace_box completed",
            extra={
                "tenant_id": tenant_id,
                "box_name": box_name,
                "card_count": len(new_box.card_ids),
            },
        )
        return new_box

    def delete_box(self, tenant_id: str, box_name: str) -> bool:
        """Delete a ``CardBox`` if the storage adapter supports it."""

        engine = self._get_engine(tenant_id)
        storage = engine.storage_adapter

        if hasattr(storage, "delete_card_box"):
            try:
                storage.delete_card_box(box_name, tenant_id)
                self._box_cache.pop(self._cache_key(tenant_id, box_name), None)
                logger.info(
                    "delete_box completed",
                    extra={"tenant_id": tenant_id, "box_name": box_name},
                )
                return True
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to delete CardBox %s for tenant %s: %s",
                    box_name,
                    tenant_id,
                    exc,
                    exc_info=True,
                )
        else:
            logger.debug(
                "Storage adapter does not support delete_card_box; skipping deletion",
                extra={"tenant_id": tenant_id, "box_name": box_name},
            )
        return False

    def _normalise_tool_payload(self, payload: Any) -> str:
        """Conservatively convert tool outputs or errors into text content."""

        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        try:
            return json_dumps(payload, ensure_ascii=False)
        except TypeError:
            return str(payload)

    def build_tool_result_card(
        self,
        *,
        session_id: Optional[str],
        tool_name: str,
        tool_call_id: str,
        result: Any,
        arguments: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        success: bool = True,
    ) -> Card:
        """Create a ``Card`` describing the output of a tool execution."""

        logger.info(
            f"build_tool_result_card called with session_id={session_id}, tool_name={tool_name}, tool_call_id={tool_call_id}, result_type={type(result)}, result={result}, arguments={arguments}, message_id={message_id}, success={success}"
        )

        content = TextContent(text=self._normalise_tool_payload(result))
        metadata: Dict[str, Any] = {
            "role": "tool",
            "type": "tool_result",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "session_id": session_id,
            "message_id": message_id,
            "success": success,
            "source": "tool",
            "indexable": True,
            "tags": [
                "tool_result",
                tool_name,
                "success" if success else "failed",
            ],
        }

        if arguments:
            metadata["tool_arguments"] = arguments

        parsed_result: Optional[Dict[str, Any]] = None
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
            except (TypeError, json.JSONDecodeError):  # pragma: no cover - defensive
                parsed_result = None
        elif isinstance(result, dict):
            parsed_result = result

        if parsed_result:
            detail_value = parsed_result.get("detail")
            if detail_value:
                metadata.setdefault("error_detail", detail_value)
            debug_info = parsed_result.get("debug")
            if debug_info:
                metadata.setdefault("debug", debug_info)

        metadata = {key: value for key, value in metadata.items() if value is not None}

        logger.info(f"build_tool_result_card metadata: {metadata}")

        return Card(content=content, metadata=metadata)

    def build_message_card(self, message: AgentMessage) -> Card:
        """Convert an agent message into a Cardbox card."""

        content_text = message.content or ""
        content = TextContent(text=content_text)
        metadata = {
            "role": message.sender,
            "session_id": str(message.session_id) if message.session_id else None,
            "message_id": str(message.id),
            "type": "message",
            "source": "chat",
            "created_at": (
                message.created_at.isoformat() if message.created_at else None
            ),
            "is_typing": message.is_typing,
            "indexable": True,
            "tags": [
                "chat_message",
                message.sender,
            ],
        }
        # Remove None values to keep payload tidy
        metadata = {k: v for k, v in metadata.items() if v is not None}

        # Token usage fields are optional but useful for analytics
        if message.model_name:
            metadata["model_name"] = message.model_name
        if message.prompt_tokens is not None:
            metadata["prompt_tokens"] = message.prompt_tokens
        if message.completion_tokens is not None:
            metadata["completion_tokens"] = message.completion_tokens
        if message.total_tokens is not None:
            metadata["total_tokens"] = message.total_tokens
        if message.cost_usd is not None:
            metadata["cost_usd"] = float(message.cost_usd)
        if message.response_time_ms is not None:
            metadata["response_time_ms"] = message.response_time_ms

        return Card(content=content, metadata=metadata)

    def sync_message(
        self, message: AgentMessage, session: Optional[AgentSession] = None
    ) -> Optional[str]:
        """Persist a message to Cardbox and return the card identifier.

        Errors are logged but swallowed to avoid breaking the main chat flow.
        """

        try:
            session = session or message.session
            if session is None and message.session_id is None:
                logger.warning(
                    "Skipping Cardbox sync: message %s has no session", message.id
                )
                return None

            if session is None:
                # Fallback: best effort load via SQLAlchemy relationship
                session = message.session  # triggers lazy load if configured

            if session is None:
                logger.warning(
                    "Skipping Cardbox sync: unable to resolve session for message %s",
                    message.id,
                )
                return None

            box_name = session.cardbox_name or cardbox_for_session(session)
            tenant_id = tenant_for_user(message.user_id)

            card = self.build_message_card(message)
            self.add_cards(tenant_id, box_name, [card])

            # Ensure the session remembers the assigned Cardbox name.
            session.cardbox_name = box_name
            message.cardbox_card_id = card.card_id
            return card.card_id

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox sync failed for message %s: %s", message.id, exc, exc_info=True
            )
            return None

    def record_tool_result(
        self,
        *,
        session: AgentSession,
        user_id: Any,
        tool_name: str,
        tool_call_id: str,
        result: Any,
        arguments: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        success: bool = True,
    ) -> Optional[str]:
        """Append a tool execution outcome to the session Cardbox."""

        logger.info(
            f"record_tool_result called with session={session}, user_id={user_id}, tool_name={tool_name}, tool_call_id={tool_call_id}, result_type={type(result)}, result={result}, arguments={arguments}, message_id={message_id}, success={success}"
        )

        try:
            box_name = self.ensure_session_box(session)
            tenant_id = tenant_for_user(user_id)

            card = self.build_tool_result_card(
                session_id=str(session.id) if session.id else None,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=result,
                arguments=arguments,
                message_id=message_id,
                success=success,
            )

            self.add_cards(tenant_id, box_name, [card])
            return card.card_id

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox tool result sync failed for session %s: %s",
                getattr(session, "id", "unknown"),
                exc,
                exc_info=True,
            )
            return None

    def record_summary(
        self,
        *,
        session: AgentSession,
        user_id: Any,
        summary: str,
        covered_message_ids: Iterable[str],
        language: str,
    ) -> Optional[str]:
        """Persist a conversation summary into the session Cardbox."""

        try:
            box_name = self.ensure_session_box(session)
            tenant_id = tenant_for_user(user_id)
            metadata: Dict[str, Any] = {
                "role": "system",
                "type": "summary",
                "language": language,
                "summary_version": 1,
                "generated_at": utc_now_iso(),
                "session_id": str(session.id) if session.id else None,
                "covered_messages": list(covered_message_ids),
                "indexable": True,
                "tags": ["conversation_summary", language],
            }

            card = Card(
                content=TextContent(text=summary),
                metadata={k: v for k, v in metadata.items() if v is not None},
            )

            logger.info(
                "record_summary called",
                extra={
                    "session_id": str(session.id) if session.id else None,
                    "covered_count": len(metadata["covered_messages"] or []),
                },
            )

            self.add_cards(tenant_id, box_name, [card])
            return card.card_id

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox summary sync failed for session %s: %s",
                getattr(session, "id", "unknown"),
                exc,
                exc_info=True,
            )
            return None

    def record_session_overview(
        self,
        *,
        session: AgentSession,
        user_id: Any,
        title: str,
        description: str,
        confidence: Optional[float],
        language: str,
        model_name: Optional[str] = None,
    ) -> Optional[str]:
        """Persist the latest user-facing session overview."""

        try:
            box_name = self.ensure_session_box(session)
            tenant_id = tenant_for_user(user_id)

            metadata: Dict[str, Any] = {
                "role": "system",
                "type": "session_overview",
                "language": language,
                "model_name": model_name,
                "generated_at": utc_now_iso(),
                "title": title,
                "description": description,
                "confidence": confidence,
                "indexable": True,
                "tags": ["session_overview", language],
            }

            payload = {
                "title": title,
                "description": description,
                "confidence": confidence,
                "language": language,
            }

            card = Card(
                content=TextContent(text=json_dumps(payload, ensure_ascii=False)),
                metadata={k: v for k, v in metadata.items() if v is not None},
            )

            self.add_cards(tenant_id, box_name, [card])
            return card.card_id

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Cardbox session overview sync failed for session %s: %s",
                getattr(session, "id", "unknown"),
                exc,
                exc_info=True,
            )
            return None

    def get_latest_session_overview(
        self,
        *,
        user_id: Any,
        session_id: Any,
    ) -> Optional[Dict[str, Any]]:
        """Fetch the most recent session overview metadata if available."""

        try:
            records = self.list_session_messages(
                user_id=user_id,
                session_id=session_id,
                limit=1,
                include_types=["session_overview"],
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Failed to load session overview from Cardbox: %s",
                exc,
                exc_info=True,
            )
            return None

        if not records:
            return None

        record = records[-1]
        metadata = record.get("metadata") or {}
        content = record.get("content") or ""
        try:
            payload = json.loads(content) if content else {}
        except json.JSONDecodeError:
            payload = {"title": metadata.get("title"), "description": content}

        return {
            "title": metadata.get("title") or payload.get("title"),
            "description": metadata.get("description") or payload.get("description"),
            "confidence": metadata.get("confidence") or payload.get("confidence"),
            "language": metadata.get("language") or payload.get("language"),
            "generated_at": metadata.get("generated_at"),
            "card_id": record.get("card_id"),
        }

    def list_session_messages(
        self,
        *,
        user_id: Any,
        session_id: Any,
        limit: Optional[int] = 20,
        include_types: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return message cards for a session, newest last."""

        tenant_id = tenant_for_user(user_id)
        box_name = cardbox_for_session(session_id)
        engine = self._get_engine(tenant_id)
        card_box = engine.storage_adapter.load_card_box(box_name, tenant_id)
        if card_box is None:
            return []

        card_ids = list(getattr(card_box, "card_ids", []) or [])
        if not card_ids:
            return []
        if limit and limit > 0:
            card_ids = card_ids[-limit:]

        allowed_types = set(include_types) if include_types else None

        results: List[Dict[str, Any]] = []
        for cid in card_ids:
            card = engine.card_store.get(cid)
            if card is None:
                continue
            metadata = getattr(card, "metadata", {}) or {}
            if allowed_types is not None and metadata.get("type") not in allowed_types:
                continue
            content_obj = getattr(card, "content", None)
            text = getattr(content_obj, "text", "") if content_obj else ""
            results.append(
                {
                    "card_id": str(getattr(card, "card_id", cid)),
                    "metadata": metadata,
                    "role": metadata.get("role"),
                    "content": text,
                }
            )

        return results

    def initialize_storage(self, user_id: Any, cleanup_test_boxes: bool = True) -> bool:
        """Initialize DuckDB storage schema for a user.

        This method ensures that the DuckDB tables exist for the given user
        by creating a test CardBox and verifying it can be loaded back.

        Parameters
        ----------
        user_id : Any
            The user identifier (will be converted to tenant_id internally).
        cleanup_test_boxes : bool, default True
            Whether to clean up test CardBoxes after initialization.

        Returns
        -------
        bool
            True if initialization was successful, False otherwise.

        Raises
        ------
        Exception
            If initialization fails and cleanup_test_boxes is False.
        """
        try:
            tenant_id = tenant_for_user(user_id)
            logger.info(
                f"Initializing storage for user {user_id} (tenant: {tenant_id})"
            )

            # Create engine and test basic operations
            engine = create_engine(tenant_id)
            storage = engine.storage_adapter

            # Create a test box to trigger schema creation
            test_box_name = f"init-test-box-{tenant_id}"
            test_box = CardBox()

            # Save the box (this triggers table creation if they don't exist)
            storage.save_card_box(test_box, name=test_box_name, tenant_id=tenant_id)
            logger.info(f"Test box '{test_box_name}' created for tenant '{tenant_id}'")

            # Verify the box can be loaded back
            loaded_box = storage.load_card_box(test_box_name, tenant_id)
            if loaded_box is None:
                raise RuntimeError(
                    f"Failed to load test box '{test_box_name}' for tenant '{tenant_id}'"
                )

            # Clean up test box if requested
            if cleanup_test_boxes:
                try:
                    # Try to delete the test box (if the storage adapter supports it)
                    if hasattr(storage, "delete_card_box"):
                        storage.delete_card_box(test_box_name, tenant_id)
                        logger.debug(f"Cleaned up test box '{test_box_name}'")
                    else:
                        logger.debug(
                            f"Storage adapter does not support delete_card_box, leaving test box '{test_box_name}'"
                        )
                except Exception as cleanup_exc:
                    logger.warning(
                        f"Failed to clean up test box '{test_box_name}': {cleanup_exc}"
                    )

            logger.info(f"Storage initialization successful for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Storage initialization failed for user {user_id}: {e}")
            if not cleanup_test_boxes:
                raise
            return False

    def check_storage_exists(self, user_id: Any) -> bool:
        """Check if DuckDB storage schema exists for a user.

        This method performs a lightweight check by attempting to query
        the card_boxes table without creating any test data.

        Parameters
        ----------
        user_id : Any
            The user identifier (will be converted to tenant_id internally).

        Returns
        -------
        bool
            True if storage schema exists and is accessible, False otherwise.
        """
        try:
            tenant_id = tenant_for_user(user_id)

            # Create engine and test basic operations
            engine = create_engine(tenant_id)
            storage = engine.storage_adapter

            # Try to execute a simple query to check if tables exist
            # This is a lightweight check that doesn't create any data
            if hasattr(storage, "_connection") and hasattr(
                storage._connection, "execute"
            ):
                # Direct DuckDB query to check if card_boxes table exists
                result = storage._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='card_boxes'"
                ).fetchone()
                return result is not None
            else:
                # Fallback: try to create and load a temporary box
                test_box_name = f"schema-check-{tenant_id}"
                test_box = CardBox()

                storage.save_card_box(test_box, name=test_box_name, tenant_id=tenant_id)
                loaded_box = storage.load_card_box(test_box_name, tenant_id)

                # Clean up the test box
                try:
                    if hasattr(storage, "delete_card_box"):
                        storage.delete_card_box(test_box_name, tenant_id)
                except Exception:
                    pass  # Ignore cleanup errors

                return loaded_box is not None

        except Exception as e:
            logger.debug(f"Storage check failed for user {user_id}: {e}")
            return False


cardbox_service = CardBoxService()

__all__ = ["CardBoxService", "cardbox_service"]
