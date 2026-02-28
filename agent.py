import json
import time
from ai_tools import get_ai_client
import settings
import agent_tools

class Agent:
    def __init__(self):
        pass

    def chat_stream(self, user_input, chat_history):
        """
        Generator that handles Native Tool Calling streaming.
        Accepts a ChatHistory object.
        """
        token_costs = (0,0)

        # User input handling
        if user_input:
            token_costs = chat_history.add_user_message(user_input)

        max_turns = 25
        turn = 0

        while turn < max_turns:
            # Start the Stream
            client = get_ai_client()

            # Access the raw list for the API call
            messages_payload = chat_history.get_history()

            stream = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages_payload,
                tools=agent_tools.tools_schema,
                stream=True
            )

            full_content_buffer = ""
            full_reasoning_buffer = ""
            tool_calls_buffer = {}
            is_tool_call = False

            has_started_reasoning = False
            has_finished_reasoning = False

            yield "status", "🤔 Thinking..."

            # 2. Process the Stream
            for chunk in stream:
                delta = chunk.choices[0].delta

                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    if not has_started_reasoning:
                        has_started_reasoning = True
                    yield "reasoning", delta.reasoning_content
                    full_reasoning_buffer += delta.reasoning_content

                if delta.content:
                    if has_started_reasoning and not has_finished_reasoning:
                        has_finished_reasoning = True
                    yield "text", delta.content
                    full_content_buffer += delta.content

                if delta.tool_calls:
                    is_tool_call = True
                    for tool_chunk in delta.tool_calls:
                        idx = tool_chunk.index
                        if idx not in tool_calls_buffer:
                            tool_calls_buffer[idx] = {"id": "", "name": "", "args": ""}
                            yield "status", "🧠 The Reaper is grabbing a tool..."

                        if tool_chunk.id:
                            tool_calls_buffer[idx]["id"] += tool_chunk.id

                        if tool_chunk.function.name:
                            tool_calls_buffer[idx]["name"] += tool_chunk.function.name
                            friendly_name = agent_tools.get_friendly_status(tool_calls_buffer[idx]['name'])
                            yield "status", f"{friendly_name}"

                        if tool_chunk.function.arguments:
                            tool_calls_buffer[idx]["args"] += tool_chunk.function.arguments

            # 3. End of Stream Logic
            if is_tool_call:
                final_tool_calls = []
                for idx in sorted(tool_calls_buffer.keys()):
                    tool_data = tool_calls_buffer[idx]
                    final_tool_calls.append({
                        "id": tool_data["id"],
                        "type": "function",
                        "function": {
                            "name": tool_data["name"],
                            "arguments": tool_data["args"]
                        }
                    })

                assistant_msg_kwargs = {
                    "tool_calls": final_tool_calls
                }
                if full_reasoning_buffer:
                    assistant_msg_kwargs["reasoning_content"] = full_reasoning_buffer

                chat_history.add_message("assistant", full_content_buffer if full_content_buffer else None, **assistant_msg_kwargs)

                # 4. EXECUTE TOOLS
                for tool_call in final_tool_calls:
                    call_id = tool_call["id"]
                    func_name = tool_call["function"]["name"]
                    func_args_str = tool_call["function"]["arguments"]

                    friendly_status = agent_tools.get_friendly_status(func_name)
                    yield "status", f"{friendly_status} Working..."
                    print(f"Agent Calling: {func_name} | ID: {call_id}")

                    try:
                        params = json.loads(func_args_str)
                        action_desc = params.get("action_description")
                        yield "action", action_desc
                        tool_result_str = agent_tools.execute_tool({"tool": func_name, "params": params})
                    except Exception as e:
                        tool_result_str = f"Error executing tool: {str(e)}"

                    chat_history.add_message("tool", tool_result_str, tool_call_id=call_id, name=func_name)

                turn += 1
                yield "status", "Reading results..."

            else:
                assistant_msg_kwargs = {}
                if full_reasoning_buffer:
                    assistant_msg_kwargs["reasoning_content"] = full_reasoning_buffer

                chat_history.add_message("assistant", full_content_buffer, **assistant_msg_kwargs)
                return

        yield "text", "\n\n(Max turns reached.)"
