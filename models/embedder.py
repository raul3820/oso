import os
import aiohttp
from typing import List
import logfire
from db.struct import default_embedding

openai_api_url = os.environ['OPENAI_API_URL']
openai_api_key = os.environ['OPENAI_API_KEY']
embeddings_model = os.environ['EMBEDDINGS_MODEL']

async def get_embedding(text: str) -> List[float]:
    """
    Get text embedding using Ollama's nomic-embed-text model
    
    Args:
        text: Input text to embed
        
    Returns:
        List of floats representing the text embedding
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": embeddings_model,
                "prompt": text
            }
            async with session.post(
                openai_api_url.replace('/v1', '/api/embeddings'),
                json=payload
            ) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("embedding", default_embedding)
    except aiohttp.ClientError as e:
        logfire.exception(f"Error during embedding request: {e}")
        return default_embedding
    except Exception as e:
        logfire.exception(f"Unexpected error during embedding: {e}")
        return default_embedding