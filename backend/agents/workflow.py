from google.adk.agents import SequentialAgent
from agents.extraction_agent import ExtractionAgent
from agents.summary_agent import summary_agent
from agents.section_agents import SectionAnalysisOrchestrator

extraction_agent = ExtractionAgent(name="extraction_agent")
section_orchestrator = SectionAnalysisOrchestrator(name="section_orchestrator")

# Compose the ADK 1.x SequentialAgent workflow
document_pipeline = SequentialAgent(
    name="document_pipeline",
    sub_agents=[
        extraction_agent,
        summary_agent,
        section_orchestrator
    ]
)
