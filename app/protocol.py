from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any

class Hello(BaseModel):
    type: Literal["hello"]
    device_id: Optional[str] = None
    fw: Optional[str] = None
    listen_mode: Optional[str] = None

class HelloResponse(BaseModel):
    type: Literal["hello"]
    session_id: str
    audio_params: Dict[str, Any]
    features: Dict[str, bool]
    version: int = 1

class Wake(BaseModel):
    type: Literal["wake"]
    device_id: Optional[str] = None

class AudioStart(BaseModel):
    type: Literal["audio_start"]
    device_id: Optional[str] = None
    format: Optional[str] = "opus"
    rate: Optional[int] = 16000
    channels: Optional[int] = 1

class AudioEnd(BaseModel):
    type: Literal["audio_end"]
    device_id: Optional[str] = None

class Abort(BaseModel):
    type: Literal["abort"]
    reason: Optional[str] = None

class Listen(BaseModel):
    type: Literal["listen"]
    state: Literal["start", "stop", "detect"]
    mode: Optional[str] = None
    text: Optional[str] = None

class AsrText(BaseModel):
    type: Literal["asr_text"]
    text: str

class TtsStart(BaseModel):
    type: Literal["tts_start"]
    text: Optional[str] = None

class TtsEnd(BaseModel):
    type: Literal["tts_end"]
    reason: Optional[str] = None

class ErrorMsg(BaseModel):
    type: Literal["error"]
    message: str
