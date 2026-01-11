from openai import OpenAI
import config

def aiCall(data, system):
    """
    Calls the OpenAI API to analyze the provided data.

    Args:
        data: The data to be analyzed.
        system: The request to be sent to the AI.

    Returns:
        The content of the AI's response.
    """

    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": data},
        ],
        stream=False
    )

    return(response.choices[0].message.content)

def aiCall_chat(chat_history=None):

    if chat_history is None:
        chat_history = []
    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=chat_history,
        stream=False
    )

    return(response.choices[0].message.content)

def ai_chat_stream(chat_history=None):
    client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)
    stream = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=chat_history,
        stream=True
    )
    return stream
