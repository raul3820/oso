import os
import logfire
from typing import Optional
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel


story_max_chars = int(os.environ["STORY_MAX_CHARS"])

story_model = OpenAIModel(
    model_name=os.environ["STORY_MODEL"],
    base_url=os.environ["OPENAI_API_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
) 

summarizer_agent = Agent(
    story_model,
    retries=3,
    system_prompt=os.environ["SUMMARIZER_SYSTEM_PROMPT"],
)

sanitizer_agent = Agent(
    story_model,
    retries=3,
    system_prompt=os.environ["SANITIZER_SYSTEM_PROMPT"],
)

async def _summarize_text(text: str) -> Optional[str]:
    """Generates a response based on the given prompt."""
    try:
        response = await summarizer_agent.run(
            user_prompt=text,
            model_settings={
                'temperature': 0.7,
                'max_tokens': 256,
            },
        )
        return response.data

    except Exception as e:
        logfire.exception(f"Error summarizing text: {e}")
        return None

async def _sanitize_text(text: str) -> Optional[str]:
    """Generates a response based on the given prompt."""
    try:
        response = await sanitizer_agent.run(
            user_prompt=text,
            model_settings={
                'temperature': 0.1,
                'max_tokens': 256,
                },
        )

        return response.data
    
    except Exception as e:
        logfire.exception(f"Error sanitizing text: {e}")
        return None

async def generate_response(text: str) -> Optional[str]:
    """Generates a response based on the given prompt."""
    try:
        new_text = text
        i = 0
        while story_max_chars < len(new_text):
            new_text = await _summarize_text(text)
            i += 1
        
        if 0 < i:
            s = f"Summarized story in {i} passes, from {len(text)} chars to {len(new_text)} chars."
            if i < 5:
                logfire.info(s)
            else:
                logfire.warning(s)


        new_text = await _sanitize_text(new_text)
        
        return new_text
    
    except Exception as e:
        logfire.exception(f"Error generating response: {e}")
        return None