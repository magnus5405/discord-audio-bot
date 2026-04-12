"""Compatibility shims for discord-ext-voice_recv with discord.py >= 2.7 / DAVE voice.

Discord voice can be protected by DAVE (MLS). RTP payloads are still SRTP-decrypted,
but Opus frames need an extra ``DaveSession`` unwrap before ``opus_decode``. Without
that step, libopus reports corrupted streams and downstream STT sees unusable audio.

Upstream fix: https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54
This module applies an equivalent patch at import/runtime so we do not depend on a
pre-release package pin.
"""

from __future__ import annotations

import logging
from typing import Any

from discord.opus import OpusError

logger = logging.getLogger(__name__)

_PATCH_APPLIED = False

try:
    from davey import MediaType as _DaveMediaType

    _HAVE_DAVEY = True
except ImportError:  # pragma: no cover - optional until voice is used
    _DaveMediaType = None  # type: ignore[misc, assignment]
    _HAVE_DAVEY = False


def apply_discord_ext_voice_recv_patches() -> None:
    """Idempotently patch discord-ext-voice_recv for DAVE and safer routing."""
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
        return

    try:
        from discord.ext.voice_recv import opus as vr_opus
        from discord.ext.voice_recv.router import PacketRouter
        from discord.ext.voice_recv.rtp import RTPPacket
    except ImportError:  # pragma: no cover
        logger.debug("discord.ext.voice_recv is not installed; skipping voice receive patches.")
        _PATCH_APPLIED = True
        return

    if not getattr(vr_opus.PacketDecoder, "_discord_audio_bot_patched", False):
        _patch_packet_decoder(vr_opus, RTPPacket)
    if not getattr(PacketRouter, "_discord_audio_bot_patched", False):
        _patch_packet_router(PacketRouter)

    _PATCH_APPLIED = True
    if _HAVE_DAVEY:
        logger.info("discord-ext-voice_recv: DAVE voice receive compatibility patch is active.")
    else:
        logger.warning(
            "discord-ext-voice_recv: applied routing/decode patches only; install `davey` "
            "for full DAVE (E2EE) voice receive support with discord.py 2.7+."
        )


def _dave_session_for_sink(sink: Any) -> Any:
    vc = getattr(sink, "voice_client", None)
    if vc is None:
        return None
    conn = getattr(vc, "_connection", None)
    if conn is None:
        return None
    return getattr(conn, "dave_session", None)


def _patch_packet_decoder(vr_opus: Any, RTPPacket: type) -> None:
    PacketDecoder = vr_opus.PacketDecoder
    orig_init = PacketDecoder.__init__

    def patched_init(self: Any, router: Any, ssrc: int) -> None:
        orig_init(self, router, ssrc)
        ds = _dave_session_for_sink(self.sink)
        if ds is None or not hasattr(ds, "set_passthrough_mode"):
            return
        try:
            ds.set_passthrough_mode(True, 10)
        except Exception:
            logger.debug("DAVE set_passthrough_mode failed", exc_info=True)

    def patched_process(self: Any, packet: Any) -> Any:
        pcm = None

        member = self._get_cached_member()
        if member is None:
            self._cached_id = self.sink.voice_client._get_id_from_ssrc(self.ssrc)  # type: ignore[union-attr]
            member = self._get_cached_member()

        if (
            _HAVE_DAVEY
            and member is not None
            and not packet.is_silence()
            and packet.decrypted_data is not None
        ):
            if isinstance(packet, RTPPacket) and packet.payload != 120:
                self._last_seq = packet.sequence
                self._last_ts = packet.timestamp
                return vr_opus.VoiceData(packet, None, pcm=b"")

            ds = _dave_session_for_sink(self.sink)
            if ds is not None and getattr(ds, "ready", False):
                try:
                    packet.decrypted_data = ds.decrypt(
                        int(member.id),
                        _DaveMediaType.audio,
                        bytes(packet.decrypted_data),
                    )
                except Exception:
                    self._last_seq = packet.sequence
                    self._last_ts = packet.timestamp
                    return vr_opus.VoiceData(packet, None, pcm=b"")

        if not self.sink.wants_opus():
            packet, pcm = self._decode_packet(packet)

        data = vr_opus.VoiceData(packet, member, pcm=pcm)
        self._last_seq = packet.sequence
        self._last_ts = packet.timestamp
        return data

    def patched_decode(self: Any, packet: Any) -> tuple[Any, bytes]:
        assert self._decoder is not None

        if packet:
            try:
                pcm = self._decoder.decode(packet.decrypted_data, fec=False)
                return packet, pcm
            except OpusError:
                pcm = self._decoder.decode(None, fec=False)
                return packet, pcm

        next_packet = self._buffer.peek_next()

        if next_packet is not None:
            nextdata: bytes = next_packet.decrypted_data  # type: ignore[assignment]
            pcm = self._decoder.decode(nextdata, fec=True)
        else:
            pcm = self._decoder.decode(None, fec=False)

        return packet, pcm

    PacketDecoder.__init__ = patched_init  # type: ignore[method-assign]
    PacketDecoder._process_packet = patched_process  # type: ignore[method-assign]
    PacketDecoder._decode_packet = patched_decode  # type: ignore[method-assign]
    PacketDecoder._discord_audio_bot_patched = True


def _patch_packet_router(PacketRouter: type) -> None:
    def patched_do_run(self: Any) -> None:
        while not self._end_thread.is_set():
            self.waiter.wait()
            with self._lock:
                for decoder in self.waiter.items:
                    data = decoder.pop_data()
                    if data is not None and data.source is not None:
                        self.sink.write(data.source, data)

    PacketRouter._do_run = patched_do_run  # type: ignore[method-assign]
    PacketRouter._discord_audio_bot_patched = True
