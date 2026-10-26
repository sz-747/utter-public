# coding: utf-8
"""
Communication protocol

Dataclasses for the messages between the client and the server.
Both the server and the client use them, so the message format always matches.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Literal, Optional
import json


@dataclass
class AudioMessage:
    """
    Client -> server: audio data message

    Attributes:
        task_id: unique task ID
        source: audio source ('mic' microphone or 'file' file)
        data: Base64-encoded audio (float32, 16kHz, mono)
        is_final: whether this is the last packet of the task
        time_start: recording/audio start timestamp
        seg_duration: segment length (seconds)
        seg_overlap: overlap length (seconds)
    """
    task_id: str
    source: Literal['mic', 'file']
    data: str                    # Base64-encoded audio
    is_final: bool
    time_start: float
    seg_duration: float = 15.0
    seg_overlap: float = 2.0

    def to_json(self) -> str:
        """Serialize to a JSON string"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> 'AudioMessage':
        """Create an instance from a dict"""
        return cls(
            task_id=data['task_id'],
            source=data['source'],
            data=data['data'],
            is_final=data['is_final'],
            time_start=data['time_start'],
            seg_duration=data.get('seg_duration', 15.0),
            seg_overlap=data.get('seg_overlap', 2.0),
        )


@dataclass
class RecognitionResult:
    """
    Server -> client: recognition result message

    Attributes:
        task_id: unique task ID
        is_final: whether this is the final result (all segments recognized)
        duration: total audio processed so far (seconds)
        time_start: recording/audio start timestamp
        time_submit: timestamp when the last segment was submitted
        time_complete: timestamp when recognition finished

        text: main output - text joined simply (does not rely on timestamps)
        text_accu: accurate output - text joined with timestamp-based deduplication (for subtitles)
        tokens: token list (matches timestamps)
        timestamps: token timestamps (seconds)
    """
    task_id: str
    is_final: bool
    duration: float
    time_start: float
    time_submit: float
    time_complete: float

    # Main output (simple text join)
    text: str

    # Accurate output (timestamp join)
    text_accu: str = ''
    tokens: List[str] = field(default_factory=list)
    timestamps: List[float] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize to a JSON string"""
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> dict:
        """Convert to a dict"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'RecognitionResult':
        """Create an instance from a dict"""
        return cls(
            task_id=data['task_id'],
            is_final=data['is_final'],
            duration=data['duration'],
            time_start=data['time_start'],
            time_submit=data['time_submit'],
            time_complete=data['time_complete'],
            text=data['text'],
            text_accu=data.get('text_accu', ''),
            tokens=data.get('tokens', []),
            timestamps=data.get('timestamps', []),
        )
