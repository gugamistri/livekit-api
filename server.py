import os
import re
import json
import logging
from datetime import timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Body, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import uvicorn
from livekit import api

# -----------------------------------------------------------------------------
# 1) Load environment
# -----------------------------------------------------------------------------
load_dotenv(".env.local")

# -----------------------------------------------------------------------------
# 2) App & CORS
# -----------------------------------------------------------------------------
app = FastAPI()
security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# 3) Data Models
# -----------------------------------------------------------------------------
class AgentConfig(BaseModel):
    stt_engine: str = "deepgram"
    stt_model: str = "nova-2"
    stt_language: str = "pt"
    llm_engine: str = "openai"
    llm_model: str = "gpt-4o-mini"
    tts_engine: str = "cartesia"
    tts_language: str = "pt"
    tts_voice: str = "2ccd63be-1c60-4b19-99f6-fa7465af0738"
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
    record:          Optional[bool]      = None
    egress:          Optional[bool]      = None
    ingress:         Optional[bool]      = None
    publish:         Optional[bool]      = None
    subscribe:       Optional[bool]      = None
    publish_data:    Optional[bool]      = None
    publish_sources: Optional[List[str]] = None
    update_metadata: Optional[bool]      = None
    hidden:          Optional[bool]      = None
    agent:           Optional[bool]      = None


class TokenRequest(BaseModel):
    roomName:        str                    = Field(..., description="room to join")
    participantName: str                    = Field(..., description="your identity")
    ttl:             Optional[int]          = Field(600, description="token TTL in seconds")
    metadata:        Optional[Dict[str, Any]] = None
    permissions:     Permissions            = Field(default_factory=Permissions)
    phoneNumber:     Optional[str]          = Field(None, description="Phone number to dial")


class TokenResponse(BaseModel):
    token:       str
    sipCallSid:  Optional[str] = None


# -----------------------------------------------------------------------------
# 4) Helper: validate bearer token
# -----------------------------------------------------------------------------
def validate_bearer_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    expected_token = os.getenv("API_TOKEN")
    if not expected_token or credentials.credentials != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token"
        )


# -----------------------------------------------------------------------------
# 5) Helper: dispatch an agent
# -----------------------------------------------------------------------------
@app.post("/dispatch-agent")
async def dispatch_agent(
    config: AgentConfig = Body(...),
    _: HTTPAuthorizationCredentials = Depends(validate_bearer_token),
):
    return await _dispatch_agent(config)


async def _dispatch_agent(config: AgentConfig):
    lkapi = api.LiveKitAPI()
    try:
        dispatch = await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=config.agent_name,
                room=config.room_name,
                metadata=config.model_dump_json()
            )
        )
        return {"dispatch_id": dispatch.id}
    finally:
        await lkapi.aclose()

async def create_sip_participant(room_name: str, phone_number: str):
    lkapi = api.LiveKitAPI()
    try:
        trunk = os.getenv("SIP_OUTBOUND_TRUNK_ID")
        if not trunk or not trunk.startswith("ST_"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SIP_OUTBOUND_TRUNK_ID not configured"
            )

        sip_part = await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room_name,
                sip_trunk_id=trunk,
                sip_call_to=phone_number,
                participant_identity="phone_user",
                wait_until_answered=True,
            )
        )
        sip_call_sid = sip_part.call_sid
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create SIP participant: {e!s}"
        )
    finally:
        await lkapi.aclose()
    return sip_call_sid

# -----------------------------------------------------------------------------
# 6) Main: get-token endpoint
# -----------------------------------------------------------------------------
@app.post("/get-token", response_model=TokenResponse)
async def get_token(
    body: TokenRequest,
    _: HTTPAuthorizationCredentials = Depends(validate_bearer_token),
):
    try:
        api_key = os.getenv("LIVEKIT_API_KEY")
        api_secret = os.getenv("LIVEKIT_API_SECRET")
        if not api_key or not api_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set"
            )
        if body.phoneNumber:
            if not re.fullmatch(r"^\d+$", body.phoneNumber):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="phoneNumber must be digits only"
                )
        perms = body.permissions

        # Build AccessToken with VideoGrants
        at = api.AccessToken(api_key=api_key, api_secret=api_secret)\
            .with_identity(body.participantName)\
            .with_ttl(timedelta(seconds=body.ttl or 300))\
            .with_grants(api.VideoGrants(
                room=body.roomName,
                room_join=              perms.join               is not False,
                room_create=            bool(perms.create),
                room_list=              bool(perms.list),
                room_admin=             bool(perms.admin),
                room_record=            bool(perms.record),
                recorder=               bool(perms.egress),
                ingress_admin=          bool(perms.ingress),
                can_publish=            perms.publish             is not False,
                can_subscribe=          perms.subscribe           is not False,
                can_publish_data=       bool(perms.publish_data),
                can_publish_sources=    perms.publish_sources   or [],
                can_update_own_metadata=bool(perms.update_metadata),
                hidden=                 bool(perms.hidden),
                agent=                  bool(perms.agent),
            ))

        if body.agentData is not None:
            at.metadata = body.agentData

        jwt = at.to_jwt()
        sip_call_sid: Optional[str] = None


        dispatch_meta = body.agentData or {}

        await _dispatch_agent(
            AgentConfig(
                agent_name="test-agent",
                room_name=body.roomName,
                tts_voice= "5063f45b-d9e0-4095-b056-8f3ee055d411" if dispatch_meta.voiceModel == "male" else  "2ccd63be-1c60-4b19-99f6-fa7465af0738",
                prompt= dispatch_meta.prompt or  "Você é um atendente virtual que atende clientes por telefone.",
            )
        )

        if body.phoneNumber:
            sip_call_sid = await create_sip_participant(body.roomName, body.phoneNumber)

        return TokenResponse(token=jwt, sipCallSid=sip_call_sid)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create token: {e!s}"
        )


# -----------------------------------------------------------------------------
# 7) Run Server
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
