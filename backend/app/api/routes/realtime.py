import asyncio
import ipaddress
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, or_, select

from app.config import settings
from app.core.security import decode_access_token, get_local_user
from app.database import AsyncSessionLocal
from app.database.models import AgentEvent, AgentRun, Conversation, User

router = APIRouter(tags=["realtime"])
_AUTH_SUBPROTOCOL_PREFIX = "aether.bearer."
_LOCAL_SUBPROTOCOL = "aether.local"
_MAX_REPLAY_CURSORS = 1000
_EVENT_BATCH_SIZE = 100


def _read_replay_cursors(raw: str | None) -> dict[str, int]:
    if raw is None:
        return {}
    try:
        cursors = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Invalid replay cursor") from None
    if not isinstance(cursors, dict) or len(cursors) > _MAX_REPLAY_CURSORS:
        raise ValueError("Invalid replay cursor")
    if any(
        not isinstance(run_id, str)
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 0
        for run_id, sequence in cursors.items()
    ):
        raise ValueError("Invalid replay cursor")
    return cursors


@router.websocket("/ws/chat/{conversation_id}")
async def stream_conversation_events(websocket: WebSocket, conversation_id: UUID) -> None:
    protocols = websocket.scope.get("subprotocols", [])
    credential = next(
        (protocol[len(_AUTH_SUBPROTOCOL_PREFIX):] for protocol in protocols if protocol.startswith(_AUTH_SUBPROTOCOL_PREFIX)),
        None,
    )
    local_protocol = _LOCAL_SUBPROTOCOL in protocols
    local_user_id: str | None = None

    if settings.local_auth_mode:
        client = websocket.client
        origin = websocket.headers.get("origin")
        allowed_origins = {
            entry.strip()
            for entry in settings.cors_allowed_origins.split(",")
            if entry.strip()
        }
        try:
            is_loopback = client is not None and ipaddress.ip_address(client.host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            await websocket.close(code=4403, reason="Local access only")
            return
        if origin is not None and origin not in allowed_origins:
            await websocket.close(code=4403, reason="Origin is not allowed")
            return
        if not local_protocol:
            await websocket.accept(subprotocol="aether")
            await websocket.close(code=4401, reason="Local access protocol required")
            return
    elif credential is None:
        await websocket.accept(subprotocol="aether")
        await websocket.close(code=4401, reason="Authentication failed")
        return

    try:
        cursors = _read_replay_cursors(websocket.query_params.get("after"))
    except ValueError:
        await websocket.accept(subprotocol="aether")
        await websocket.close(code=4400, reason="Replay cursor is invalid")
        return

    await websocket.accept(subprotocol="aether")
    session_factory = getattr(websocket.app.state, "test_session_factory", AsyncSessionLocal)
    async with session_factory() as session:
        if settings.local_auth_mode:
            local_user = await get_local_user(session)
            local_user_id = local_user.id
        else:
            try:
                user_id = decode_access_token(credential)
            except ValueError:
                await websocket.close(code=4401, reason="Authentication failed")
                return
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == str(conversation_id),
                Conversation.user_id == local_user_id if settings.local_auth_mode else Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            await websocket.close(code=4404, reason="Conversation not found")
            return

    receive_task = asyncio.create_task(websocket.receive())
    try:
        while True:
            async with session_factory() as session:
                run_ids_result = await session.scalars(
                    select(AgentRun.id).where(
                        AgentRun.conversation_id == str(conversation_id),
                        AgentRun.user_id == local_user_id if settings.local_auth_mode else AgentRun.user_id == user_id,
                    )
                )
                run_ids = list(run_ids_result.all())
                if not run_ids:
                    events = []
                else:
                    replay_conditions = [
                        and_(
                            AgentEvent.agent_run_id == run_id,
                            AgentEvent.sequence > cursors.get(run_id, 0),
                        )
                        for run_id in run_ids
                    ]
                    result = await session.execute(
                        select(AgentEvent, AgentRun)
                        .join(AgentRun, AgentEvent.agent_run_id == AgentRun.id)
                        .where(or_(*replay_conditions))
                        .order_by(AgentEvent.created_at, AgentEvent.id)
                        .limit(_EVENT_BATCH_SIZE)
                    )
                    events = result.all()

            for event, run in events:
                await websocket.send_json(
                    jsonable_encoder(
                        {
                            "event_id": event.id,
                            "sequence": event.sequence,
                            "type": event.event_type,
                            "conversation_id": run.conversation_id,
                            "run_id": run.id,
                            "created_at": event.created_at,
                            "data": {"agent": event.agent_name, **event.payload},
                        }
                    )
                )
                cursors[run.id] = event.sequence

            if len(events) >= _EVENT_BATCH_SIZE:
                continue

            completed, _ = await asyncio.wait({receive_task}, timeout=0.5)
            if completed:
                incoming = receive_task.result()
                if incoming["type"] == "websocket.disconnect":
                    return
                await websocket.close(code=1008, reason="This connection is read-only")
                return
    except WebSocketDisconnect:
        return
    finally:
        if not receive_task.done():
            receive_task.cancel()
