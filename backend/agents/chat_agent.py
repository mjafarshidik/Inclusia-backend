import os
from google.adk.agents import LlmAgent

# Define ChatAgent as an ADK LlmAgent
chat_agent = LlmAgent(
    name="chat_agent",
    model="gemini-3.5-flash",
    instruction="""You are Inclusia's accessibility tutor helper. Your task is to help the user understand the document context provided below. Be extremely clear, concise, encouraging, and write in Indonesian.

Document Context:
{document_context}
{chat_history}""",
    output_key="chat_response"
)

def run_chat_agent_sync(user_message: str, document_context: str, chat_history: list = None) -> str:
    """Runs the ChatAgent synchronously in an event loop using the ADK runner."""
    import asyncio
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    # Ensure GOOGLE_API_KEY is mapped from GEMINI_API_KEY in the environment for ADK
    if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

    adk_app = App(name="agents", root_agent=chat_agent)
    runner = InMemoryRunner(app=adk_app)

    async def _run():
        session_id = "temp_chat_session"
        
        # Format history string
        history_str = ""
        if chat_history:
            history_str = "\n\nChat History:\n"
            for msg in chat_history:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_str += f"{role}: {msg.get('content')}\n"

        # Create session and populate context variables in state
        await runner.session_service.create_session(
            app_name="agents",
            user_id="system",
            session_id=session_id,
            state={
                "document_context": document_context,
                "chat_history": history_str
            }
        )
        
        # Run
        async for event in runner.run_async(
            user_id="system",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        ):
            pass
            
        updated_session = await runner.session_service.get_session(app_name="agents", session_id=session_id)
        return updated_session.state.get("chat_response")

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass
        response_text = loop.run_until_complete(_run())
    else:
        response_text = asyncio.run(_run())

    return response_text or ""
