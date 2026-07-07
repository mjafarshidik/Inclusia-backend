import os
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent

class OptimizationOutput(BaseModel):
    optimized_prompt: str = Field(description="The optimized system prompt text. Returns ONLY the prompt text, retaining any formatting, placeholders and variables.")

feedback_agent = LlmAgent(
    name="feedback_agent",
    model="gemini-3.5-flash",
    instruction="""You are an expert AI Prompt Engineer.
We have a system prompt that generates educational summary/accessibility content for students with disabilities.

A user has submitted negative feedback regarding the generated output:
- User Comment: "{comment}"
- Associated Tags: {tags}

Here is the current system prompt:
---
{current_prompt}
---

Please rewrite and optimize the system prompt to directly address the user's feedback (e.g. if the user complained about formulas being too verbose, or descriptions not being clear, refine the instructions inside the prompt to handle these scenarios better).

Maintain the original requirements, variables (like {{text}} or {{context_before_str}} and {{context_after_str}} or any required JSON structure), but enhance the rules to prevent the issues mentioned in the user feedback.
Return the newly optimized prompt.""",
    output_schema=OptimizationOutput,
    output_key="result"
)

def run_feedback_agent_sync(comment: str, tags: list, current_prompt: str) -> str:
    """Runs the feedback agent synchronously using ADK runner."""
    import asyncio
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    # Ensure GOOGLE_API_KEY is mapped from GEMINI_API_KEY in the environment for ADK
    if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

    adk_app = App(name="agents", root_agent=feedback_agent)
    runner = InMemoryRunner(app=adk_app)

    async def _run():
        session_id = "temp_feedback_session"
        await runner.session_service.create_session(
            app_name="agents",
            user_id="system",
            session_id=session_id,
            state={
                "comment": comment,
                "tags": str(tags),
                "current_prompt": current_prompt
            }
        )
        async for event in runner.run_async(
            user_id="system",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text="Optimize this prompt")])
        ):
            pass
        session = await runner.session_service.get_session(app_name="agents", session_id=session_id)
        res = session.state.get("result")
        return res.get("optimized_prompt") if res else None

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
        optimized = loop.run_until_complete(_run())
    else:
        optimized = asyncio.run(_run())

    return optimized or ""
