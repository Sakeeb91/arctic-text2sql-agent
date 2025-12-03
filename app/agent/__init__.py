"""
Agent module for Arctic Text2SQL with smolagents integration.

This module provides the agent-based architecture for multi-step
reasoning and self-correction in SQL generation.

Components:
- models: Data classes for agent results and reasoning
- tools: SQL execution, validation, and schema inspection tools
- engine: Main AgentEngine with ReAct loop
"""

from app.agent.engine import AgentText2SQL, get_agent_engine, reset_agent_engine
from app.agent.models import AgentResult, AgentStep

__all__ = [
    "AgentResult",
    "AgentStep",
    "AgentText2SQL",
    "get_agent_engine",
    "reset_agent_engine",
]
