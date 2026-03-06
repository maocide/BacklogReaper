from openai import OpenAI
import settings
import datetime


def aiCall(data, system, return_tokens=False):
    """
    Calls the OpenAI API to analyze the provided data.

    Args:
        data: The data to be analyzed.
        system: The request to be sent to the AI.
        return_tokens (bool): Whether to return a tuple containing the token usage.

    Returns:
        The content of the AI's response, or a tuple containing (content, in_tokens, out_tokens) if return_tokens is True.
    """

    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": data},
        ],
        stream=False,
        temperature=settings.LLM_TEMPERATURE,
        top_p=settings.LLM_TOP_P,
        presence_penalty=settings.LLM_PRESENCE_PENALTY
    )

    content = response.choices[0].message.content

    if return_tokens:
        in_tokens = getattr(response.usage, 'prompt_tokens', 0) if hasattr(response, 'usage') else 0
        out_tokens = getattr(response.usage, 'completion_tokens', 0) if hasattr(response, 'usage') else 0
        return content, in_tokens, out_tokens

    return content


def aiCall_chat(chat_history=None):
    if chat_history is None:
        chat_history = []
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=240.0)

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=chat_history,
        stream=False,
        temperature=settings.LLM_TEMPERATURE,
        top_p=settings.LLM_TOP_P,
        presence_penalty=settings.LLM_PRESENCE_PENALTY
    )

    return (response.choices[0].message.content)


def ai_chat_stream(chat_history=None):
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    stream = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=chat_history,
        stream=True,
        temperature=settings.LLM_TEMPERATURE,
        top_p=settings.LLM_TOP_P,
        presence_penalty=settings.LLM_PRESENCE_PENALTY
    )
    return stream


def get_ai_client():
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=240.0)
    return (client)


def clean_json_for_ai(data, keep_keys=None, transformations=None):
    """
    Recursively optimizes JSON data for AI ingestion.

    :param data: The input dictionary or list.
    :param keep_keys: A list of strings. If provided, ONLY these keys are kept in dicts.
    :param transformations: A dict mapping 'key_name' -> 'type_of_conversion'.
                            Types: 'date', 'minutes_to_hours', 'seconds_to_hours', 'round_2'.
    """
    if transformations is None:
        transformations = {}

    # Helper Conversion
    def apply_transform(key, value):
        rule = transformations.get(key)

        # Handle transformation logic
        if not rule:
            return value

        # If value is None and we have a rule, we might want to handle it (e.g. N/A)
        if value is None:
            if "or_na" in rule: return "N/A"
            return value

        try:
            if rule == 'date':
                # Assumes Unix timestamp (int or float)
                dt = datetime.datetime.fromtimestamp(int(value))
                return dt.strftime("%Y-%m-%d")

            elif rule == 'datetime':
                # Assumes Unix timestamp (int or float)
                dt = datetime.datetime.fromtimestamp(int(value))
                return dt.strftime("%Y-%m-%d %H:%M")

            elif rule == 'minutes_to_hours':
                return f"{round(value / 60, 1)}h"

            elif rule == 'minutes_to_hours_or_na':
                if value == 0: return "N/A"
                return f"{round(value / 60, 1)}h"

            elif rule == 'seconds_to_hours':
                return f"{round(value / 3600, 1)}h"

            elif rule == 'round_2':
                return round(float(value), 2)

            elif rule == 'bool_text':
                return "Yes" if value else "No"

        except Exception:
            # If conversion fails, return original value to avoid crashing
            return value
        return value

    # Recursive Traversal
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            # 1. Filter: Skip keys not in allowlist (if allowlist exists)
            if keep_keys is not None and k not in keep_keys:
                continue

            # 2. Transform: Recursive call
            new_val = clean_json_for_ai(v, keep_keys, transformations)

            # 3. Value Conversion: Apply formatting rule based on key name
            final_val = apply_transform(k, new_val)

            new_dict[k] = final_val
        return new_dict

    elif isinstance(data, list):
        return [clean_json_for_ai(item, keep_keys, transformations) for item in data]

    else:
        # Base case (int, str, bool, etc.)
        return data