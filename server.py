from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.security import HTTPBearer
import uvicorn
import os
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from livekit import api
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

load_dotenv('.env.local')
app = FastAPI()
security = HTTPBearer()
# List of allowed origins (use ["*"] to allow all, but avoid in production)
allowed_origins = [
    "*", 
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # List of allowed origins
    allow_credentials=True,         # Allow cookies
    allow_methods=["*"],            # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],            # Allow all headers
)
class AgentConfig(BaseModel):
    stt_engine: str = "deepgram"
    stt_model: str = "nova-3"
    stt_language: str = "multi"
    llm_engine: str = "openai"
    llm_model: str = "gpt-4o-mini"
    tts_engine: str = "cartesia"
    tts_language: str = "pt"
    tts_voice: str ="2ccd63be-1c60-4b19-99f6-fa7465af0738"
    user_language: str = "pt-BR"
    business_context: str = "general"
    prompt: str = "You are a helpful voice AI assistant."
    agent_name: str
    room_name: str


class Permissions(BaseModel):
    join:            Optional[bool]      = None
    create:          Optional[bool]      = None
    list:            Optional[bool]      = None
    admin:           Optional[bool]      = None
    record:          Optional[bool]      = None   # maps to room_record
    egress:          Optional[bool]      = None   # deprecated → recorder
    ingress:         Optional[bool]      = None
    publish:         Optional[bool]      = None
    subscribe:       Optional[bool]      = None
    publish_data:    Optional[bool]      = None
    publish_sources: Optional[List[str]] = None
    update_metadata: Optional[bool]      = None
    hidden:          Optional[bool]      = None
    agent:           Optional[bool]      = None

class TokenRequest(BaseModel):
    roomName:        str                   = Field(..., description="room to join")
    participantName: str                   = Field(..., description="your identity")
    ttl:             Optional[int]         = Field(600, description="ttl of the token, until expiry")
    metadata:        Optional[Dict[str,Any]] = None
    permissions:     Permissions           = Field(default_factory=Permissions)


class TokenResponse(BaseModel):
    token: str


@app.post("/dispatch-agent")
async def dispatch_agent(
    config: AgentConfig = Body(...),
    credentials: HTTPBearer = Depends(security)
):
    return await _dispatch_agent(config)

async def _dispatch_agent(config: AgentConfig):
    lkapi = api.LiveKitAPI()
    
    try:
        # Serialize config to JSON for metadata
        metadata = config.model_dump_json()
        print(metadata)
        dispatch = await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=config.agent_name,
                room=config.room_name,
                metadata=metadata
            )
        )
        return {"dispatch_id": dispatch.id}
    finally:
        await lkapi.aclose()


@app.post("/get-token", response_model=TokenResponse)
async def get_token(body: TokenRequest):
    try:
        api_key = os.getenv("LIVEKIT_API_KEY")
        api_secret = os.getenv("LIVEKIT_API_SECRET")
        if not api_key or not api_secret:
            raise HTTPException(500, "LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set")

        perms = body.permissions

        at = api.AccessToken(
            api_key=api_key,
            api_secret=api_secret)\
            .with_identity(body.participantName) \
            .with_ttl( timedelta(seconds=body.ttl or 300)) \
            .with_grants(api.VideoGrants(
                room=body.roomName,
                room_join=              perms.join               is not False,
                room_create=            bool(perms.create),
                room_list=              bool(perms.list),
                room_admin=             bool(perms.admin),
                room_record=            bool(perms.record),
                recorder=               bool(perms.egress),       # deprecated flag
                ingress_admin=          bool(perms.ingress),
                can_publish=            perms.publish             is not False,
                can_subscribe=          perms.subscribe           is not False,
                can_publish_data=       bool(perms.publish_data),
                can_publish_sources=    perms.publish_sources  or [],
                can_update_own_metadata=bool(perms.update_metadata),
                hidden=                 bool(perms.hidden),
                agent=                  bool(perms.agent),
            ))
        
        if body.metadata is not None:
            at.metadata = body.metadata
        
        jwt = at.to_jwt()
        config = AgentConfig(
            agent_name=body.participantName,
            room_name=body.roomName,
            stt_engine="deepgram",
            stt_model="nova-3",
            stt_language="multi",
            llm_engine="openai",
            llm_model="gpt-4o-mini",
            tts_engine="cartesia",
            tts_language="pt",
            tts_voice="2ccd63be-1c60-4b19-99f6-fa7465af0738",
            user_language="pt-BR",
            business_context="general",
            prompt="You are a helpful voice AI assistant.",
            metadata=body.metadata
        )
        await dispatch_agent(config)
        return TokenResponse(token=jwt)
    except Exception as e:
        raise HTTPException(500, f"Failed to create token: {e!s}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)