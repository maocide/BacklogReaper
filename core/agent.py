import json
import time
from core.ai_tools import get_ai_client
import core.settings as settings
import core.agent_tools as agent_tools
import ui.utils


class Agent:
    def __init__(self):
        pass

    def chat_stream(self, user_input, chat_history):
        """
        Generator that handles Native Tool Calling streaming.
        Accepts a ChatHistory object.
        """
        token_costs = (0, 0)

        import tiktoken
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            encoding = None

        # User input handling
        if user_input:
            token_costs = chat_history.add_user_message(user_input)
            if token_costs[0] > 0 or token_costs[1] > 0:
                yield "tokens", {"in": token_costs[0], "out": token_costs[1]}

        max_turns = 25
        turn = 0

        while turn < max_turns:
            # Start the Stream
            client = get_ai_client()

            # Access the raw list for the API call
            messages_payload = chat_history.get_history()

            create_kwargs = {
                "model": settings.OPENAI_MODEL,
                "messages": messages_payload,
                "tools": agent_tools.tools_schema,
                "stream": True,
                "temperature": settings.LLM_TEMPERATURE,
                "top_p": settings.LLM_TOP_P,
                "presence_penalty": settings.LLM_PRESENCE_PENALTY
            }

            # Request thinking/reasoning from the model
            if "gemini" in settings.OPENAI_MODEL.lower():
                create_kwargs["extra_body"] = {
                    "extra_body": {
                        "google": {
                            "thinking_config": {
                                "include_thoughts": True
                            }
                        }
                    }
                }

            stream = client.chat.completions.create(**create_kwargs)

            full_content_buffer = ""
            full_reasoning_buffer = ""
            tool_calls_buffer = {}
            is_tool_call = False

            has_started_reasoning = False
            has_finished_reasoning = False

            is_gemini_thinking_tag = False

            yield "status", "🤔 Thinking..."

            # Process the Stream
            for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # Extract reasoning content (Deepseek format)
                reasoning_chunk = getattr(delta, "reasoning_content", None)

                # Check for OpenRouter's reasoning payload
                if not reasoning_chunk and hasattr(delta, "model_extra") and delta.model_extra:
                    reasoning_chunk = delta.model_extra.get("reasoning", None)

                if reasoning_chunk:
                    if not has_started_reasoning:
                        has_started_reasoning = True
                    yield "reasoning", reasoning_chunk
                    full_reasoning_buffer += reasoning_chunk

                if delta.content:
                    text_chunk = delta.content

                    # Intercept nested <thought> or <think> tags from the main content stream
                    if "<thought>" in text_chunk or "<think>" in text_chunk:
                        is_gemini_thinking_tag = True
                        text_chunk = text_chunk.replace("<thought>", "").replace("<think>", "")

                    if "</thought>" in text_chunk or "</think>" in text_chunk:
                        is_gemini_thinking_tag = False
                        if "</thought>" in text_chunk:
                            parts = text_chunk.split("</thought>")
                        else:
                            parts = text_chunk.split("</think>")

                        # Yield the last bit of reasoning before the tag closes
                        if parts[0]:
                            if not has_started_reasoning:
                                has_started_reasoning = True
                            yield "reasoning", parts[0]
                            full_reasoning_buffer += parts[0]

                        # And any standard text that comes after
                        if len(parts) > 1 and parts[1]:
                            if has_started_reasoning and not has_finished_reasoning:
                                has_finished_reasoning = True
                            yield "text", parts[1]
                            full_content_buffer += parts[1]

                    elif is_gemini_thinking_tag:
                        if not has_started_reasoning:
                            has_started_reasoning = True
                        yield "reasoning", text_chunk
                        full_reasoning_buffer += text_chunk
                    else:
                        if has_started_reasoning and not has_finished_reasoning:
                            has_finished_reasoning = True
                        yield "text", text_chunk
                        full_content_buffer += text_chunk

                if delta.tool_calls:
                    # Reset thinking tag if tools are called, as the model may have missed the closing tag
                    is_gemini_thinking_tag = False
                    is_tool_call = True
                    for i, tool_chunk in enumerate(delta.tool_calls):
                        # Fallback to the loop index 'i' if the API sends None
                        idx = tool_chunk.index if tool_chunk.index is not None else i

                        # GEMINI PARALLEL CALLS HANDLED
                        # If Google's API sends multiple tools but labels them all 'index=0',
                        # we detect the collision if the chunk has a NEW id that doesn't match the buffer.
                        if idx in tool_calls_buffer and getattr(tool_chunk, "id", None):
                            if tool_calls_buffer[idx]["id"] and tool_calls_buffer[idx]["id"] != tool_chunk.id:
                                # Force it into a new slot to prevent concatenation!
                                idx = max(tool_calls_buffer.keys()) + 1

                        if idx not in tool_calls_buffer:
                            tool_calls_buffer[idx] = {"id": "", "name": "", "args": "", "thought_signature": ""}
                            yield "status", "🧠 The Reaper is grabbing a tool..."

                        if getattr(tool_chunk, "id", None):
                            tool_calls_buffer[idx]["id"] += tool_chunk.id

                        # Correctly extract thought_signature from the tool_call root extra_content as per Google's OpenAI compatibility schema
                        if hasattr(tool_chunk, "model_dump"):
                            try:
                                chunk_dict = tool_chunk.model_dump()
                                google_data = chunk_dict.get("google", {})
                                if not google_data and "extra_content" in chunk_dict and chunk_dict["extra_content"]:
                                    google_data = chunk_dict["extra_content"].get("google", {})

                                if "thought_signature" in google_data and google_data["thought_signature"]:
                                    tool_calls_buffer[idx]["thought_signature"] += google_data["thought_signature"]
                            except Exception:
                                pass

                        if getattr(tool_chunk, "function", None):
                            if getattr(tool_chunk.function, "name", None):
                                tool_calls_buffer[idx]["name"] += tool_chunk.function.name
                                friendly_name = agent_tools.get_friendly_status(tool_calls_buffer[idx]['name'])
                                yield "status", f"{friendly_name}"

                            if getattr(tool_chunk.function, "arguments", None):
                                tool_calls_buffer[idx]["args"] += tool_chunk.function.arguments

            if encoding:
                try:
                    msgs_str = json.dumps(messages_payload)
                    in_tokens = len(encoding.encode(msgs_str, allowed_special="all"))
                    out_tokens = 0
                    if full_content_buffer:
                        out_tokens += len(encoding.encode(full_content_buffer, allowed_special="all"))
                    if full_reasoning_buffer:
                        out_tokens += len(encoding.encode(full_reasoning_buffer, allowed_special="all"))
                    if in_tokens > 0 or out_tokens > 0:
                        yield "tokens", {"in": in_tokens, "out": out_tokens}
                except Exception as e:
                    print(f"Token count error: {e}")

            # Heuristic Split for Hallucinated Combined Responses
            if not full_content_buffer and full_reasoning_buffer:
                # If there is a double newline in the reasoning buffer
                if "\n\n" in full_reasoning_buffer:
                    parts = full_reasoning_buffer.rsplit("\n\n", 1)
                    full_reasoning_buffer = parts[0]
                    full_content_buffer = parts[1].strip()

            # End of Stream Logic
            if is_tool_call:
                final_tool_calls = []
                for idx in sorted(tool_calls_buffer.keys()):
                    tool_data = tool_calls_buffer[idx]
                    tc = {
                        "id": tool_data["id"],
                        "type": "function",
                        "function": {
                            "name": tool_data["name"],
                            "arguments": tool_data["args"]
                        }
                    }
                    # Place thought_signature inside the root extra_content object as required by the API schema
                    if tool_data.get("thought_signature"):
                        tc["extra_content"] = {
                            "google": {
                                "thought_signature": tool_data["thought_signature"]
                            }
                        }
                        # Also place it in function directly for robust proxy fallback
                        tc["function"]["thought_signature"] = tool_data["thought_signature"]

                    final_tool_calls.append(tc)

                assistant_msg_kwargs = {
                    "tool_calls": final_tool_calls
                }
                if full_reasoning_buffer:
                    assistant_msg_kwargs["reasoning_content"] = full_reasoning_buffer

                chat_history.add_message("assistant", full_content_buffer if full_content_buffer else None,
                                         **assistant_msg_kwargs)

                # EXECUTE TOOLS
                for tool_call in final_tool_calls:
                    call_id = tool_call["id"]
                    func_name = tool_call["function"]["name"]
                    func_args_str = tool_call["function"]["arguments"]

                    friendly_status = agent_tools.get_friendly_status(func_name)
                    yield "status", f"{friendly_status} Working..."
                    print(f"Agent Calling: {func_name} | ID: {call_id}")
                    print(f"Agent Calling: {func_name} | PARAMS: {func_args_str}")

                    # SAFE JSON PARSING
                    try:
                        # If string is empty, default to empty dictionary
                        params = json.loads(func_args_str) if func_args_str else {}

                        # Safely get the action description with a fallback
                        action_desc = params.get("action_description", "Channeling the void...")
                        yield "action", action_desc

                        # Execute
                        tool_result_str = agent_tools.execute_tool({"tool": func_name, "params": params})

                    except json.JSONDecodeError:
                        # Catch corrupted JSON from the model and return it AS JSON to the chat history
                        print(f"CRITICAL: Model hallucinated bad JSON for {func_name}: {func_args_str}")
                        yield "action", "Muttering incomprehensible dark incantations..."
                        tool_result_str = json.dumps({"error": f"Invalid JSON arguments: {func_args_str}"})

                    except Exception as e:
                        # Catch execution errors and return AS JSON
                        print(f"CRITICAL: Tool execution failed: {e}")
                        tool_result_str = json.dumps({"error": f"Tool execution failed: {str(e)}"})

                    # Will get token usage as prepared by the wrap_output after executing the tool
                    try:
                        parsed_res = json.loads(tool_result_str)
                        if isinstance(parsed_res, dict) and "_token_usage" in parsed_res:
                            token_usage = parsed_res.pop("_token_usage")
                            yield "tokens", token_usage
                            # Repackage the JSON payload minus the _token_usage to save LLM context
                            tool_result_str = json.dumps(parsed_res)
                    except Exception as e:
                        print(f"Token count error for tool: {e}")
                        pass

                    chat_history.add_message("tool", tool_result_str, tool_call_id=call_id, name=func_name)

                turn += 1
                yield "status", "Reading results..."

            else:
                assistant_msg_kwargs = {}
                if full_reasoning_buffer:
                    assistant_msg_kwargs["reasoning_content"] = full_reasoning_buffer

                chat_history.add_message("assistant", full_content_buffer, **assistant_msg_kwargs)
                return

        yield "text", f"{ui.utils.get_markdown_newline()}(Max turns reached.)"
