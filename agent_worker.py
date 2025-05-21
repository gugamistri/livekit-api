import os
import logging
from dotenv import load_dotenv
from typing import Optional

from livekit import agents
from livekit.agents import JobContext, WorkerOptions, cli, AgentSession, Agent
from server import AgentConfig
from livekit.plugins import deepgram, openai, cartesia, silero, assemblyai

logger = logging.getLogger("agent-worker")
load_dotenv(".env.local")


class VoiceAgent(Agent):
    """
    A simple LiveKit voice agent with STT/TTS/LLM.
    """
    def __init__(
        self,
        *,
        instructions: str,
        stt: agents.stt.STT,
        tts: agents.tts.TTS,
        llm: agents.llm.LLM,
        vad: Optional[agents.vad.VAD] = None,
    ):
        super().__init__(
            instructions=instructions,
            stt=stt,
            tts=tts,
            llm=llm,
            vad=vad,
        )


async def entrypoint(ctx: JobContext):
    # 1) Parse the incoming job metadata into your config model
    config = AgentConfig.model_validate_json(ctx.job.metadata)

    # 2) Initialize the chosen STT, TTS, and LLM components
    stt = {
        "deepgram": deepgram.STT(model=config.stt_model, language=config.stt_language),
        "assemblyai": assemblyai.STT(),
    }[config.stt_engine]

    tts = {
        "cartesia": cartesia.TTS(language=config.tts_language, voice=config.tts_voice),
    }[config.tts_engine]

    llm = {
        "openai": openai.LLM(model="gpt-4o-mini"),
    }[config.llm_engine]

    # 3) Build the system prompt combining the base prompt and business context
    instructions = (
        config.prompt + "\n"
        f"You will conduct a voice conversation in {config.user_language}.\n"
    )

    # 4) Instantiate your agent
    agent = VoiceAgent(
        instructions=instructions,
        stt=stt,
        tts=tts,
        llm=llm,
        vad=silero.VAD.load(),
    )

    # 5) Connect to LiveKit, wait for the caller, and start the session
    await ctx.connect()
    
    session = AgentSession()
    await session.start(room=ctx.room, agent=agent)
    await ctx.wait_for_participant()
    # 6) Send an initial greeting
    await session.generate_reply(
        instructions=(
            config.prompt
        )
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            worker_type=agents.WorkerType.ROOM,
            agent_name="test-agent",  # Must match your dispatch configuration
        )
    )
