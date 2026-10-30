# coding: utf-8
"""
Audio stream management

Provides the AudioStreamManager class, which manages the audio input stream:
creating, starting and stopping it, and detecting devices.
"""

from __future__ import annotations

import sys
import time
import threading
import json
import subprocess
from pathlib import Path
from .devices import available_names, compatible_inputs, device_key
from . import levels, capture_log
from typing import TYPE_CHECKING, Optional

import numpy as np
import sounddevice as sd
from config_client import ClientConfig as Config

from util.client.state import console, get_state
from . import logger
from util.common.lifecycle import lifecycle

if TYPE_CHECKING:
    from util.client.state import ClientState



class AudioStreamManager:
    """
    Audio stream manager

    Manages the audio input stream's life:
    - detecting and choosing the audio device
    - creating and starting the stream
    - handling the audio data callback
    - restarting and closing the stream

    Attributes:
        state: Client state instance
        sample_rate: Sample rate (default 48000 Hz)
        block_duration: Length of each data block (seconds, default 0.05 s)
    """
    
    SAMPLE_RATE = 48000
    BLOCK_DURATION = 0.05  # 50ms
    
    def __init__(self, state: 'ClientState'):
        """
        Initialize the audio stream manager

        Args:
            state: Client state instance
        """
        self.state = state
        self._channels = 1
        self._running = False
        self._monitor_stop = threading.Event()
        self._lock = threading.RLock()
        self._selected_key = None
        self._available = []
        self._monitor_thread = None
    
    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags
    ) -> None:
        """
        Audio data callback

        Called when the stream receives new data; puts the data on the async queue.
        """
        # Kept separately: every block the mic sends between one shortcut press and the next is saved, to diagnose lost audio
        capture_log.add(indata, self.SAMPLE_RATE, status)

        # Only handle data while recording
        if not self.state.recording:
            return

        # The status bar waveform follows volume and pitch
        try:
            levels.update(indata, self.SAMPLE_RATE)
        except Exception:
            pass

        import asyncio
        
        # Put the data on the queue
        if self.state.loop and self.state.queue_in:
            asyncio.run_coroutine_threadsafe(
                self.state.queue_in.put({
                    'type': 'data',
                    'time': time.time(),
                    'data': indata.copy(),
                }),
                self.state.loop
            )
    
    @property
    def selected_device(self):
        """[device name, host API] of the active microphone, or None."""
        return self._selected_key

    @property
    def available_devices(self):
        """Names of the microphones that can record right now (for the Utter settings list)."""
        return list(self._available)

    def _on_stream_finished(self):
        # The monitor handles recovery outside the PortAudio callback thread.
        pass

    def open(self):
        with self._lock:
            self._selected_key = None
            choices = compatible_inputs(getattr(Config, 'audio_input_device', None), self.SAMPLE_RATE)
            self._available = available_names(choices)
            for choice in choices:
                _, _, index, info, api = choice
                stream = None
                try:
                    self._channels = min(2, info['max_input_channels'])
                    stream = sd.InputStream(
                        samplerate=self.SAMPLE_RATE,
                        blocksize=int(self.BLOCK_DURATION * self.SAMPLE_RATE),
                        device=index, dtype='float32', channels=self._channels,
                        callback=self._audio_callback, finished_callback=self._on_stream_finished)
                    stream.start()
                    self.state.stream = stream
                    self._selected_key = device_key(choice)
                    self._running = True
                    logger.info('Microphone active: %s (%s)', info['name'], api)
                    return stream
                except Exception as exc:
                    if stream is not None:
                        stream.close()
                    logger.warning('Cannot open microphone %s: %s', info['name'], exc)
            self.state.stream = None
            logger.info('Waiting quietly for an available microphone.')
            return None

    def start_monitor(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._running = True
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_devices,
                                                 name='microphone-monitor', daemon=True)
        self._monitor_thread.start()

    def _monitor_devices(self):
        # PortAudio caches its inventory; a short-lived probe sees newly connected devices
        # without interrupting the live stream. Refresh the live inventory only on a switch.
        probe = str(Path(__file__).with_name('devices.py'))
        python = str(Path(sys.executable).with_name('python.exe'))
        while not self._monitor_stop.wait(5):
            if lifecycle.is_shutting_down:
                return
            if self.state.recording:
                continue
            try:
                result = subprocess.run(
                    [python, probe, getattr(Config, 'audio_input_device', None) or ''],
                    capture_output=True, encoding='utf-8', timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode:
                    logger.debug('Microphone probe failed: %s', result.stderr)
                    continue
                probe_result = json.loads(result.stdout)
                desired = probe_result.get('chosen')
                self._available = probe_result.get('available', [])
                try:
                    active = self.state.stream is not None and self.state.stream.active
                except sd.PortAudioError:
                    active = False
                if self._monitor_stop.is_set() or self.state.recording:
                    continue
                if desired != self._selected_key or (desired is not None and not active):
                    logger.info('Microphone availability changed; updating input.')
                    self.reopen()
            except subprocess.TimeoutExpired:
                # Seen right after the PC wakes ("timed out after -3"): the next check, 5 s later, works.
                logger.debug('Microphone probe timed out; checking again shortly')
            except Exception as exc:
                logger.warning('Microphone monitor: %s', exc)

    def _close_stream(self):
        stream, self.state.stream = self.state.stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                logger.debug('Microphone close: %s', exc)
        self._selected_key = None

    def close(self):
        self._monitor_stop.set()
        self._running = False
        with self._lock:
            self._close_stream()

    def reopen(self):
        with self._lock:
            if self._monitor_stop.is_set() or lifecycle.is_shutting_down:
                return None
            self._close_stream()
            sd._terminate()
            sd._initialize()
            return self.open()
