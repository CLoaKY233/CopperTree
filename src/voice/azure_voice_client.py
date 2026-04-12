"""
Azure Voice Live client for CopperTree debt collections.
Based on Azure's official BasicVoiceAssistant sample, adapted for API key auth
and wrapped to return VoiceCallResult for ResolutionAgent.extract_updates().
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import logging
import os
import queue
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Union, TYPE_CHECKING, cast

import pyaudio
from azure.ai.voicelive.aio import connect, AgentSessionConfig
from azure.ai.voicelive.models import (
    InputAudioFormat,
    InputTextContentPart,
    MessageItem,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
)
from azure.core.credentials import AzureKeyCredential

from src.config import settings

if TYPE_CHECKING:
    from azure.ai.voicelive.aio import VoiceLiveConnection

logger = logging.getLogger(__name__)
logging.getLogger("azure.ai.voicelive").setLevel(logging.CRITICAL)  # suppress transport-close noise

SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_SIZE = 1200  # 50ms at 24kHz


def _suppress_alsa_errors() -> None:
    """Silence ALSA/JACK noise from PyAudio device probing via stderr redirect."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
        os.close(devnull)
        # Restore after a tick so only PyAudio init is silenced
        import atexit
        atexit.register(lambda: os.dup2(old_stderr, 2))
        # Restore immediately after PyAudio init completes (called from __init__)
        _suppress_alsa_errors._restore = old_stderr
    except Exception:
        pass


def _restore_stderr() -> None:
    restore = getattr(_suppress_alsa_errors, "_restore", None)
    if restore is not None:
        try:
            os.dup2(restore, 2)
        except Exception:
            pass
        _suppress_alsa_errors._restore = None


@dataclass
class VoiceCallResult:
    call_id: str
    status: str                       # "completed" | "interrupted" | "failed"
    transcript: str
    transcript_turns: list[dict]      # [{"role": "agent"|"user", "content": str}]
    call_successful: Optional[bool] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None


class AudioProcessor:
    """PyAudio capture + playback — Azure's official pattern with seq-number barge-in."""

    class AudioPlaybackPacket:
        def __init__(self, seq_num: int, data: Optional[bytes]):
            self.seq_num = seq_num
            self.data = data

    def __init__(self, connection: "VoiceLiveConnection") -> None:
        self.connection = connection
        _suppress_alsa_errors()
        self.audio = pyaudio.PyAudio()
        _restore_stderr()
        self.format = pyaudio.paInt16
        self.channels = CHANNELS
        self.rate = SAMPLE_RATE
        self.chunk_size = CHUNK_SIZE
        self.input_stream = None
        self.playback_queue: queue.Queue[AudioProcessor.AudioPlaybackPacket] = queue.Queue()
        self.playback_base = 0
        self.next_seq_num = 0
        self.output_stream: Optional[pyaudio.Stream] = None
        self.loop: asyncio.AbstractEventLoop

    def start_capture(self) -> None:
        if self.input_stream:
            return
        self.loop = asyncio.get_event_loop()

        def _capture_callback(in_data, _frame_count, _time_info, _status_flags):
            audio_base64 = base64.b64encode(in_data).decode("utf-8")
            try:
                asyncio.run_coroutine_threadsafe(
                    self.connection.input_audio_buffer.append(audio=audio_base64), self.loop
                )
            except Exception:
                pass  # connection closing — ignore
            return (None, pyaudio.paContinue)

        self.input_stream = self.audio.open(
            format=self.format, channels=self.channels, rate=self.rate,
            input=True, frames_per_buffer=self.chunk_size,
            stream_callback=_capture_callback,
        )

    def start_playback(self) -> None:
        if self.output_stream:
            return
        remaining = bytes()

        def _playback_callback(_in_data, frame_count, _time_info, _status_flags):
            nonlocal remaining
            frame_count *= pyaudio.get_sample_size(pyaudio.paInt16)
            out = remaining[:frame_count]
            remaining = remaining[frame_count:]
            while len(out) < frame_count:
                try:
                    packet = self.playback_queue.get_nowait()
                except queue.Empty:
                    out = out + bytes(frame_count - len(out))
                    continue
                except Exception:
                    logger.exception("Error in audio playback")
                    raise
                if not packet or not packet.data:
                    break
                if packet.seq_num < self.playback_base:
                    if len(remaining) > 0:
                        remaining = bytes()
                    continue
                num_to_take = frame_count - len(out)
                out = out + packet.data[:num_to_take]
                remaining = packet.data[num_to_take:]
            return (out, pyaudio.paContinue) if len(out) >= frame_count else (out, pyaudio.paComplete)

        self.output_stream = self.audio.open(
            format=self.format, channels=self.channels, rate=self.rate,
            output=True, frames_per_buffer=self.chunk_size,
            stream_callback=_playback_callback,
        )

    def _get_and_increase_seq_num(self) -> int:
        seq = self.next_seq_num
        self.next_seq_num += 1
        return seq

    def queue_audio(self, audio_data: Optional[bytes]) -> None:
        self.playback_queue.put(AudioProcessor.AudioPlaybackPacket(
            seq_num=self._get_and_increase_seq_num(), data=audio_data
        ))

    def skip_pending_audio(self) -> None:
        self.playback_base = self._get_and_increase_seq_num()

    def shutdown(self) -> None:
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
        if self.output_stream:
            self.skip_pending_audio()
            self.queue_audio(None)
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
        if self.audio:
            self.audio.terminate()


class _CopperTreeVoiceSession:
    """
    Runs a single voice session against the coppertreevoice Foundry agent.
    Injects handoff context as a system message, collects transcript turns.
    """

    # Strong farewell phrases that signal the agent has wrapped up
    _FAREWELL_PHRASES = (
        "have a good day", "have a great day", "goodbye", "good bye",
        "wishing you the best", "this concludes",
    )
    # Soft signals that combined with a farewell indicate wrap-up
    _SOFT_FAREWELL = (
        "take care", "thank you for working", "we will be in touch",
        "i'll be in touch", "don't hesitate to reach out",
        "written confirmation", "formal agreement",
    )

    def __init__(self, system_prompt: str, call_id: str) -> None:
        self.system_prompt = system_prompt
        self.call_id = call_id
        self.transcript_turns: list[dict] = []
        self.connection: Optional["VoiceLiveConnection"] = None
        self.audio_processor: Optional[AudioProcessor] = None
        self._active_response = False
        self._response_api_done = False
        self._greeting_sent = False
        self._farewell_count = 0   # auto-end after 2 farewell turns
        self._end_session = False  # clean exit flag — set True to break event loop

    async def run(self) -> VoiceCallResult:
        agent_version = os.environ.get("AZURE_VOICELIVE_AGENT_VERSION") or None
        agent_config: AgentSessionConfig = {
            "agent_name": os.environ.get("AZURE_VOICELIVE_AGENT_ID", "coppertreevoice"),
            "agent_version": agent_version,
            "project_name": os.environ.get("AZURE_VOICELIVE_PROJECT_NAME", "coppertree"),
        }

        max_duration = settings.azure_voice_max_duration
        start_time = time.time()
        print(f"\n{'='*65}\nCopperTree Voice Session | {self.call_id}\nPress Ctrl+C to end\n{'='*65}\n")

        try:
            async with connect(
                endpoint=settings.azure_foundry_endpoint.rstrip("/"),
                credential=AzureKeyCredential(settings.azure_openai_api_key),
                api_version="2026-01-01-preview",
                agent_config=agent_config,
            ) as conn:
                self.connection = conn
                ap = AudioProcessor(conn)
                self.audio_processor = ap

                await conn.session.update(session=RequestSession(
                    modalities=[Modality.TEXT, Modality.AUDIO],
                    input_audio_format=InputAudioFormat.PCM16,
                    output_audio_format=OutputAudioFormat.PCM16,
                ))

                ap.start_playback()
                print(f"🎤 VOICE ASSISTANT READY\nStart speaking to begin conversation\n")

                async for event in conn:
                    if time.time() - start_time > max_duration:
                        print(f"\n[voice] Max duration ({max_duration}s) reached — ending session")
                        break
                    await self._handle_event(event, conn, ap)
                    if self._end_session:
                        break

        finally:
            if self.audio_processor:
                self.audio_processor.shutdown()

        duration = time.time() - start_time
        transcript_text = "\n".join(
            f"{'Agent' if t['role'] == 'agent' else 'You'}: {t['content']}"
            for t in self.transcript_turns
        )
        print(f"\n{'='*65}\nSession ended | {duration:.1f}s | {len(self.transcript_turns)} turns\n{'='*65}\n")
        return VoiceCallResult(
            call_id=self.call_id,
            status="completed",
            transcript=transcript_text,
            transcript_turns=self.transcript_turns,
            duration_seconds=duration,
        )

    async def _handle_event(self, event: Any, conn: "VoiceLiveConnection", ap: AudioProcessor) -> None:
        etype = event.type

        if etype == ServerEventType.SESSION_UPDATED:
            print("Agent ready! Start speaking...\n")
            if not self._greeting_sent:
                self._greeting_sent = True
                try:
                    # Inject borrower context + trigger opening
                    await conn.conversation.item.create(item=MessageItem(
                        role="system",
                        content=[InputTextContentPart(text=self.system_prompt)],
                    ))
                    await conn.conversation.item.create(item=MessageItem(
                        role="system",
                        content=[InputTextContentPart(
                            text=(
                                "Begin the resolution conversation now. "
                                "The borrower's identity was already verified. "
                                "Respond in the same language the borrower uses (English, Hindi, or Hinglish)."
                            )
                        )],
                    ))
                    await conn.response.create()
                except Exception:
                    logger.exception("Failed to send greeting")
            ap.start_capture()

        elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            print("🎤 Listening...")
            ap.skip_pending_audio()
            if self._active_response and not self._response_api_done:
                try:
                    await conn.response.cancel()
                except Exception as e:
                    if "no active response" not in str(e).lower():
                        logger.warning("Cancel failed: %s", e)

        elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            print("🤔 Processing...")

        elif etype == ServerEventType.RESPONSE_CREATED:
            self._active_response = True
            self._response_api_done = False

        elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
            ap.queue_audio(event.delta)

        elif etype == ServerEventType.RESPONSE_AUDIO_DONE:
            print("🎤 Ready for next input...")

        elif etype == ServerEventType.RESPONSE_DONE:
            self._active_response = False
            self._response_api_done = True

        elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            text = getattr(event, "transcript", "") or ""
            if text.strip():
                self.transcript_turns.append({"role": "agent", "content": text.strip()})
                print(f"🤖 Agent: {text.strip()}\n")
                # Auto-end detection: strong farewell = immediate, soft signals accumulate
                text_lower = text.lower()
                if any(phrase in text_lower for phrase in self._FAREWELL_PHRASES):
                    # Strong farewell — end after a short buffer for audio to finish
                    self._farewell_count += 2
                elif any(phrase in text_lower for phrase in self._SOFT_FAREWELL):
                    self._farewell_count += 1
                if self._farewell_count >= 2:
                    print("\n[voice] Agent wrapped up — ending session automatically")
                    self._end_session = True

        elif etype == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            text = getattr(event, "transcript", "") or ""
            if text.strip():
                self.transcript_turns.append({"role": "user", "content": text.strip()})
                print(f"👤 You: {text.strip()}\n")

        elif etype == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            if getattr(event, "name", "") == "end_call":
                print("\n[voice] Agent ended the call")
                self._end_session = True

        elif etype == ServerEventType.ERROR:
            msg = getattr(getattr(event, "error", None), "message", str(event))
            if "no active response" not in msg.lower() and "cancellation failed" not in msg.lower():
                logger.error("VoiceLive error: %s", msg)
                print(f"[voice] Error: {msg}")


class AzureVoiceClient:
    """Entry point used by run_resolution activity and test scripts."""

    def run_session(self, system_prompt: str, borrower_id: str) -> VoiceCallResult:
        call_id = f"azure_{borrower_id}_{int(time.time())}"
        try:
            return asyncio.run(_CopperTreeVoiceSession(system_prompt, call_id).run())
        except KeyboardInterrupt:
            print("\n[voice] Session ended by user")
            return VoiceCallResult(call_id=call_id, status="interrupted", transcript="", transcript_turns=[])
        except Exception as e:
            logger.error("[voice] Session failed: %s", e)
            return VoiceCallResult(call_id=call_id, status="failed", transcript="", transcript_turns=[], error_message=str(e))
