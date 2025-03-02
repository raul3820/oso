import os
import logfire
from typing import List, Tuple, Optional
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
    ToolCallPart,
    SystemPromptPart,
)
from db.struct import AppMsg, MsgClassification

model = OpenAIModel(
    model_name=os.environ["STORY_MODEL"],
    base_url=os.environ["OPENAI_API_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
)

async def generate_response(msgs: List[AppMsg]) -> Optional[str]:
    """Generates a response based on the given prompt."""
    try:
        system_prompt = os.environ["INQUIRY_SYSTEM_PROMPT"]
        user_prompt, message_history = _to_pydantic_messages(system_prompt, msgs)

        bounced = msgs[-1].classification not in [
            MsgClassification.inquiry
            ]
        if bounced:
            bounced_prompt = os.environ["BOUNCED_PROMPT"].replace("{MsgClassification}", f"`{msgs[-1].classification.value}`")
            user_prompt = bounced_prompt + user_prompt

        agent = Agent(
            model,
            retries=3,
            system_prompt=system_prompt
        )

        response = await agent.run(
            user_prompt=user_prompt,
            message_history=message_history,
            model_settings={
                'temperature': 0.7,
                'max_tokens': 1024,
            },
        )

        logfire.info(f"Successfully generated response. User prompt: {user_prompt}")
        return response.data

    except Exception as e:
        logfire.exception(f"Error generating response: {e}", exc_info=True)
        return None

def _to_pydantic_message(message: dict) -> ModelMessage:
    """Maps a dict to `pydantic_ai.ModelMessage`."""

    role = message.get("role")
    content = message.get("content")
    tool_calls = message.get("tool_calls", [])
    
    if role == "user":
        return ModelRequest(parts=[UserPromptPart(content=content)]) if content else None

    elif role == "assistant":
        parts = []
        if content:
            parts.append(TextPart(content=content))

        for tool_call in tool_calls:
            parts.append(_to_pydantic_tool_msg(tool_call))

        return ModelResponse(parts=parts) if parts else None

    else:
        raise ValueError(f"Unsupported role: {role}")

def _to_pydantic_tool_msg(tool_call: dict) -> ToolCallPart:
    """Maps a dict to `pydantic_ai.ToolCallPart`."""

    return ToolCallPart(
        tool_name=tool_call.get("tool_name"),
        args=tool_call.get("arguments"),
        tool_call_id=tool_call.get("id"),
    )

def _to_pydantic_messages(system_prompt: str, msgs: List[AppMsg]) -> Tuple[str, List[ModelMessage]]:
    """Converts a list of AppMsg to a list of Pydantic ModelMessages."""
    # Reference: https://ai.pydantic.dev/message-history/#using-messages-as-input-for-further-agent-runs
    if not msgs:
        return []
    
    assert len(set([msg.sender for msg in msgs])) == 1, "Msgs must be from the same thread"
    
    messages = []
    if len(msgs) > 1:
        for i in range(len(msgs) - 1):
            e = msgs[i]
            messages.append({
                "role": "user",
                "content": e.body,
            })
            if e.reply_body:
                messages.append({
                    "role": "assistant",
                    "content": e.reply_body,
                })

    if messages:
        messages = [_to_pydantic_message(m) for m in messages]

    first_msg = ModelRequest(parts=[SystemPromptPart(content=system_prompt)])
    
    return msgs[-1].body, [first_msg] + messages
