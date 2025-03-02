import os
import logfire
import asyncio
from typing import Any, Optional, List, Coroutine
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from db.struct import MsgClassification

async def classify_text(agent: Agent, result_type: type, text: str) -> Optional[MsgClassification]:
    """Classifies text into categories with error handling."""

    model_settings = {
        'temperature': 0.1,
        'max_tokens': 32,
    }

    try:
        response = await agent.run(
            user_prompt=text,
            result_type=result_type,
            model_settings=model_settings,
        )

        return response.data

    except Exception as e:
        logfire.exception(f"Error classifying text: {e}")
        return None


def get_tasks(text: str, list_of_enums: List[List[MsgClassification]]) -> List[Coroutine[Any, Any, MsgClassification | None]]:
    model = OpenAIModel(
        model_name=os.getenv("CLASSIFIER_MODEL"),
        base_url=os.getenv("OPENAI_API_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    sys_prompt_base = """"
    You are a classifier. Classify user prompt as either:
    """

    agents = [
        Agent(
            model,
            retries=3,
            system_prompt=sys_prompt_base + "\n".join([str(e) for e in enums]),
        )
        for enums in list_of_enums
    ]

    rtypes = [MsgClassification.literally(enums) for enums in list_of_enums]

    tasks = []
    for agent, rtype in zip(agents, rtypes):
        tasks.append(classify_text(agent, rtype, text))

    return tasks

async def multi_pass(text: str) -> Optional[MsgClassification]:
    """Runs multiple passes of classification to determine if the text is safe to tweet."""
    try:
        pass_0 = [
            [MsgClassification.instruction, MsgClassification.other],
            [MsgClassification.inquiry, MsgClassification.other],
            [MsgClassification.spam, MsgClassification.other],
            [MsgClassification.story, MsgClassification.other],
        ]
        tasks = get_tasks(text, pass_0)
        results = await asyncio.gather(*tasks)
        
        # decision tree to determine if the text is a story     
        if None in results:
            return None # some passes failed
        elif MsgClassification.spam.name in results:
            return MsgClassification.spam
        elif MsgClassification.instruction.name in results:
            return MsgClassification.instruction
        elif MsgClassification.inquiry.name in results:
            return MsgClassification.inquiry
        elif MsgClassification.story.name in results:
            pass
        else:
            return MsgClassification.other
    except Exception as e:
        logfire.error(f"Error during pass 0 classification: {e}")
        return None

    try:
        pass_1 = [
            [MsgClassification.banned, MsgClassification.safe],
            [MsgClassification.illegal, MsgClassification.safe],
            [MsgClassification.interesting, MsgClassification.boring],
        ]
        tasks = get_tasks(text, pass_1)
        results = await asyncio.gather(*tasks)

        # decision tree to determine if the story should be shared
        if None in results:
            return None # some passes failed
        elif MsgClassification.illegal.name in results:
            return MsgClassification.illegal
        elif MsgClassification.banned.name in results:
            return MsgClassification.banned
        elif MsgClassification.boring.name in results:
            return MsgClassification.boring
        else:
            return MsgClassification.story

        raise AssertionError("This code path should never be reached.")
    
    except Exception as e:
        logfire.error(f"Error during pass 1 classification: {e}")
        return None