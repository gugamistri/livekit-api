from livekit import agents
from dotenv import load_dotenv 
from livekit.agents import JobContext, WorkerOptions, cli, AgentSession, Agent
import logging
from server import AgentConfig
from mcp_client.server import MCPServerSse
from livekit.plugins import deepgram, openai, cartesia, silero, assemblyai
import os
from typing import Optional

logger = logging.getLogger("agent-worker")

load_dotenv('.env.local')

class MCPAgent(Agent):
    def __init__(
        self,
        *,
        instructions: str,
        stt: agents.stt.STT,
        tts: agents.tts.TTS,
        llm: agents.llm.LLM,
        vad: Optional[agents.vad.VAD] = None,
        mcp_servers: Optional[list] = None,
    ):
        super().__init__(
            instructions=instructions,
            stt=stt,
            tts=tts,
            llm=llm,
            vad=vad,
        )
        self.mcp_servers = mcp_servers or []

    async def generate_reply(self, prompt: str) -> str:
        # First check if any MCP tools can handle this request
        for server in self.mcp_servers:
            try:
                tools = await server.list_tools()
                for tool in tools:
                    if tool.name.lower() in prompt.lower():
                        logger.info(f"Using MCP tool: {tool.name}")
                        result = await server.call_tool(tool.name, {"prompt": prompt})
                        return str(result)
            except Exception as e:
                logger.error(f"Error using MCP tools: {e}")

        # Fall back to LLM if no MCP tools are applicable
        logger.info(f"No MCP tools applicable. Using LLM")
        return await super().generate_reply(prompt)


async def entrypoint(ctx: JobContext):
    # Parse metadata from dispatch
    config = AgentConfig.model_validate_json(ctx.job.metadata)
    print(ctx.job.metadata)

    # Initialize MCP server connection
    mcp_server = MCPServerSse(
        params={
            "url": os.environ.get("MCP_URL"),
            "headers": {
                "Authorization": f"Bearer {os.environ.get('MCP_TOKEN')}"
            }
        },
        cache_tools_list=True,
        name="SSE MCP Server"
    )
    await mcp_server.connect()

    # Initialize components based on config
    stt = {
        "deepgram": deepgram.STT(
            model=config.stt_model,
            language=config.stt_language
        ),
        "assemblyai": assemblyai.STT()
    }[config.stt_engine]

    tts = {
        "cartesia": cartesia.TTS(language=config.tts_language, voice=config.tts_voice)
    }[config.tts_engine]

    llm = {
        "openai": openai.LLM(model="gpt-4.1-nano")
    }[config.llm_engine]

    instructions = (
        config.prompt + "\n" +
        f"You will interact by voice with the user and maintain conversation in {config.user_language} language " +
        f"Your business context is: {config.business_context}\n" +
        "You have access to specialized tools via MCP. When appropriate, use these tools instead of the LLM."
    )

    # Create agent with configured components and MCP integration
    agent = MCPAgent(
        instructions=instructions,
        stt=stt,
        tts=tts,
        llm=llm,
        vad=silero.VAD.load(),
        mcp_servers=[mcp_server]
    )

    await ctx.connect()
    session = AgentSession()
    await session.start(room=ctx.room, agent=agent)

    # Initial greeting
    await session.generate_reply(
        instructions=f"Saudação Inicial, ex: Olá! Bem vindo(a) ao atendimento da {config.business_context}. Como posso te ajudar hoje?] ou [Saudação com toque humano, ex: Oi! Que bom te ver por aqui. Conta pra gente: o que você precisa hoje?"
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            worker_type=agents.WorkerType.ROOM,
            agent_name="test-agent"  # Match this with dispatch requests
        )
    )