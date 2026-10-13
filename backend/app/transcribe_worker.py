import asyncio
import logging
from collections.abc import Awaitable, Callable

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    StopResponse,
    cli,
    inference,
    llm,
    room_io,
    utils,
)
from livekit.agents.voice.events import UserInputTranscribedEvent

from app.services.interview_sessions import finish_open_line, save_spoken_line
from app.services.interview_transcript import accepted_speaker

logger = logging.getLogger(__name__)

server = AgentServer()


class Transcriber(Agent):
    def __init__(self, *, participant_identity: str, session_id: str, save: Callable[..., Awaitable[None]]) -> None:
        super().__init__(
            instructions="Transcribe the interview. Do not speak.",
            stt=inference.STT("assemblyai/universal-3-6-pro", language="en"),
        )
        self.participant_identity = participant_identity
        self.session_id = session_id
        self._save = save

    async def on_user_turn_completed(self, chat_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        del chat_ctx
        text = new_message.text_content or ""
        if accepted_speaker(self.participant_identity) and text.strip():
            await self._save(self.participant_identity, text, final=True)
        raise StopResponse()


class MultiUserTranscriber:
    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx
        self._sessions: dict[str, AgentSession] = {}
        self._tasks: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    def start(self) -> None:
        self.ctx.room.on("participant_connected", self.on_participant_connected)
        self.ctx.room.on("participant_disconnected", self.on_participant_disconnected)

    async def aclose(self) -> None:
        await utils.aio.cancel_and_wait(*self._tasks)
        await asyncio.gather(
            *[
                self._close_session(session, speaker=identity)
                for identity, session in list(self._sessions.items())
            ]
        )
        self.ctx.room.off("participant_connected", self.on_participant_connected)
        self.ctx.room.off("participant_disconnected", self.on_participant_disconnected)

    def on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        if accepted_speaker(participant.identity) is None or participant.identity in self._sessions:
            return
        task = asyncio.create_task(self._start_session(participant))
        self._tasks.add(task)

        def on_task_done(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            try:
                self._sessions[participant.identity] = done.result()
            except Exception:
                logger.exception("transcriber_session_failed")

        task.add_done_callback(on_task_done)

    def on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        session = self._sessions.pop(participant.identity, None)
        if session is None:
            return
        task = asyncio.create_task(self._close_session(session, speaker=participant.identity))
        self._tasks.add(task)
        task.add_done_callback(lambda _: self._tasks.discard(task))

    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        session = AgentSession()
        await session.start(
            agent=Transcriber(
                participant_identity=participant.identity,
                session_id=self.ctx.room.name,
                save=self._save,
            ),
            room=self.ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=True,
                text_output=True,
                audio_output=False,
                participant_identity=participant.identity,
                text_input=False,
                close_on_disconnect=False,
            ),
        )
        session.on("user_input_transcribed", lambda event: self._remember(participant.identity, event))
        return session

    def _remember(self, identity: str, event: UserInputTranscribedEvent) -> None:
        task = asyncio.create_task(self._save(identity, event.transcript or "", final=event.is_final))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _save(self, identity: str, text: str, *, final: bool) -> None:
        lock = self._locks.setdefault(identity, asyncio.Lock())
        async with lock:
            try:
                await save_spoken_line(self.ctx.room.name, identity, text, final=final)
            except Exception:
                logger.exception("transcript_save_failed")

    async def _close_session(self, session: AgentSession, *, speaker: str) -> None:
        await asyncio.sleep(0.8)
        try:
            await finish_open_line(self.ctx.room.name, speaker)
        except Exception:
            logger.exception("transcript_finish_failed")
        await session.drain()
        await session.aclose()


@server.rtc_session(agent_name="sift-transcriber")
async def entrypoint(ctx: JobContext) -> None:
    transcriber = MultiUserTranscriber(ctx)
    transcriber.start()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    for participant in ctx.room.remote_participants.values():
        transcriber.on_participant_connected(participant)

    async def cleanup() -> None:
        await transcriber.aclose()

    ctx.add_shutdown_callback(cleanup)


if __name__ == "__main__":
    cli.run_app(server)
