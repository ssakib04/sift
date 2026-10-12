import asyncio
import logging
from typing import Protocol

from app.services.interview_rules import outbound_signal

logger = logging.getLogger(__name__)


class SignalPeer(Protocol):
    async def send_json(self, data: dict[str, object]) -> None:
        """Send one signaling message."""


class SignalHub:
    """Relay WebRTC signaling between the recruiter and the candidate."""

    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, SignalPeer]] = {}
        self._lock = asyncio.Lock()

    async def join(self, session_id: str, role: str, peer: SignalPeer) -> None:
        async with self._lock:
            room = self._rooms.setdefault(session_id, {})
            previous = room.get(role)
            room[role] = peer
            others = [name for name in room if name != role]
        if previous is not None and previous is not peer:
            await self._close(previous)
        await self._send(peer, {"type": "peers", "roles": others})
        for name in others:
            other = self._peer(session_id, name)
            if other is not None:
                await self._send(other, {"type": "peer-joined", "role": role})

    async def relay(self, session_id: str, role: str, message: dict[str, object]) -> None:
        payload = outbound_signal(role, message)
        if payload is None:
            return
        if payload["type"] == "bye":
            await self.leave(session_id, role, notify=True)
            return
        other_role = "candidate" if role == "recruiter" else "recruiter"
        other = self._peer(session_id, other_role)
        if other is not None:
            await self._send(other, payload)

    async def leave(self, session_id: str, role: str, *, notify: bool) -> None:
        other_role = "candidate" if role == "recruiter" else "recruiter"
        async with self._lock:
            room = self._rooms.get(session_id)
            if room is None:
                return
            room.pop(role, None)
            other = room.get(other_role)
            if not room:
                self._rooms.pop(session_id, None)
        if notify and other is not None:
            await self._send(other, {"type": "peer-left", "role": role})

    def _peer(self, session_id: str, role: str) -> SignalPeer | None:
        room = self._rooms.get(session_id)
        if room is None:
            return None
        return room.get(role)

    async def _send(self, peer: SignalPeer, payload: dict[str, object]) -> None:
        try:
            await peer.send_json(payload)
        except Exception as exc:
            logger.warning("signal_send_failed error_type=%s", type(exc).__name__)

    async def _close(self, peer: SignalPeer) -> None:
        close = getattr(peer, "close", None)
        if close is None:
            return
        try:
            await close()
        except Exception as exc:
            logger.warning("signal_close_failed error_type=%s", type(exc).__name__)


signal_hub = SignalHub()
