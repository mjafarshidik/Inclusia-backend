from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from config import Config

class SummaryOutput(BaseModel):
    summary: str = Field(description="A concise summary of the document (max 3 sentences).")
    topics: list[str] = Field(description="Key topics covered in the document.")
    suggested_questions: list[str] = Field(description="Suggested initial questions a user could ask about this document.")

async def before_summary(callback_context) -> None:
    document_id = callback_context.state.get("document_id")
    if document_id:
        from services import firebase_service
        from datetime import datetime, timezone
        firebase_service.save_document(document_id, {
            "status": "PROCESSING_AI",
            "updatedAt": datetime.now(timezone.utc)
        })

summary_agent = LlmAgent(
    name="summary_agent",
    model="gemini-3.5-flash",
    instruction="""You are a Staff AI Document Analyst. Your task is to analyze the provided document text and extract the summary, key topics, and suggested questions.

Document Text:
{extracted_text}""",
    output_schema=SummaryOutput,
    output_key="summary_analysis",
    before_agent_callback=before_summary
)

def run_summary_agent_sync(extracted_text: str, document_id: str) -> dict:
    """Runs the SummaryAgent synchronously in an event loop and returns the results."""
    import asyncio
    import os
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    # Ensure GOOGLE_API_KEY is mapped from GEMINI_API_KEY in the environment for ADK
    if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

    adk_app = App(name="agents", root_agent=summary_agent)
    runner = InMemoryRunner(app=adk_app)

    async def _run():
        session = await runner.session_service.create_session(
            app_name="agents",
            user_id="system",
            session_id=document_id,
            state={"extracted_text": extracted_text}
        )
        async for event in runner.run_async(
            user_id="system",
            session_id=document_id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text="Analyze the document")])
        ):
            pass
        updated_session = await runner.session_service.get_session(app_name="agents", session_id=document_id)
        return updated_session.state.get("summary_analysis")

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
        analysis_raw = loop.run_until_complete(_run())
    else:
        analysis_raw = asyncio.run(_run())

    if not analysis_raw:
        raise ValueError("SummaryAgent returned empty results.")
        
    return {
        "summary": analysis_raw.get("summary", ""),
        "topics": analysis_raw.get("topics", []),
        "suggested_questions": analysis_raw.get("suggested_questions", [])
    }
