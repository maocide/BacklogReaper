import json
import copy
import sys
from ai_tools import aiCall, get_ai_client
import config
import agent_tools

def clean_history(history, max_user_turns=10):
    """
    Manages context window by summarizing old history.
    Triggered when the number of USER turns exceeds max_user_turns.
    """
    if len(history) <= 2: return history

    working_history = copy.deepcopy(history)
    system_prompt = working_history[0]
    conversation = working_history[1:]  # Everything else

    # Count user turns (actual interactions)
    user_indices = [i for i, msg in enumerate(conversation) if msg.get('role') == 'user']

    # If we are within limits, do nothing
    if len(user_indices) <= max_user_turns:
        return history

    # Determine split point:
    # We want to keep the last `max_user_turns` user messages (and everything after them).
    # The split point is the index of the Nth-to-last user message.
    cutoff_index = user_indices[-max_user_turns]

    # 1. Initial rough slice
    recent_context = conversation[cutoff_index:]
    old_context = conversation[:cutoff_index]

    final_history = [system_prompt]

    # 2. HEALING THE CUT
    # We must ensure 'recent_context' doesn't start with an orphaned Tool Output
    # and doesn't split a tool call from its result.

    while old_context:
        first_recent = recent_context[0]

        # Scenario A: The slice starts with a Tool Output (role='tool')
        # We need to pull the previous message (which might be another tool or the assistant call)
        if first_recent.get('role') == 'tool':
            recent_context.insert(0, old_context.pop())
            continue

        # Scenario B: The slice starts with an Assistant message that HAS tool calls
        # We must ensure we didn't leave any "Tool Outputs" behind in 'old_context'
        # that belong to this assistant message.

        # Scenario C: The END of 'old_context' is an Assistant message with tool_calls.
        # This means the Assistant asked for something, but the result is in 'recent'.
        # We must pull that Assistant message into 'recent' to keep the pair together.
        last_old = old_context[-1]
        if last_old.get('role') == 'assistant' and 'tool_calls' in last_old:
            recent_context.insert(0, old_context.pop())
            continue

        # If we get here, the cut is clean (e.g., starts with User or plain Assistant text)
        break

    # 3. Summarization (Standard)
    # If we have anything in old_context, we summarize it (since we triggered the limit).
    if len(old_context) > 0:
        print("Summarizing history...")

        # Check if there was already a summary in the old context to carry it forward
        prev_summary = ""
        msgs_to_summarize = []

        for msg in old_context:
            if msg['role'] == 'system' and "[SUMMARY" in msg.get('content', ''):
                prev_summary = msg['content']  # Grab the text of the old summary
            else:
                msgs_to_summarize.append(msg)

        # Create the summarization prompt
        summary_instruction_template = agent_tools.get_summary_instruction()
        summary_request = summary_instruction_template.format(
            prev_summary=prev_summary,
            json_msgs=json.dumps(msgs_to_summarize)
        )

        try:
            print("--- TRIGGERING CONTEXT SUMMARIZATION ---")
            new_summary = aiCall(summary_request, "You are a Summarizer.")

            final_history.append({
                "role": "system",
                "content": f"[PREVIOUS CONVERSATION SUMMARY: {new_summary}]"
            })

        except Exception as e:
            print(f"Summarization failed: {e}")
            # Fallback: Just keep the old summary logic or the raw messages
            final_history.extend(old_context)
    else:
        final_history.extend(old_context)

    final_history.extend(recent_context)
    return final_history

def agent_chat_loop_stream(user_input, chat_history):
    """
    Generator that handles Native Tool Calling streaming.
    """
    # Dynamic System Prompt
    current_prompt = agent_tools.get_system_prompt()

    system_message = {"role": "system", "content": current_prompt}

    # If history is empty, initialize it.
    # If history exists, we technically should UPDATE the system prompt if the character changed mid-chat.
    # To handle character switching, we replace index 0 if it's a system message.
    if not chat_history:
        chat_history.append(system_message)
    elif chat_history[0]["role"] == "system":
        chat_history[0] = system_message

    # Run your cleaning logic
    chat_history[:] = clean_history(chat_history)

    chat_history.append({"role": "user", "content": user_input})

    max_turns = 25
    turn = 0

    while turn < max_turns:
        # Start the Stream
        client = get_ai_client()
        stream = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=chat_history,
            tools=agent_tools.tools_schema,
            stream=True
        )

        full_content_buffer = ""
        tool_calls_buffer = {}  # Dict to handle parallel tool streams {index: {id, name, args}}
        is_tool_call = False

        yield "status", "🤔 Thinking..."

        # 2. Process the Stream
        for chunk in stream:
            delta = chunk.choices[0].delta

            # --- CASE A: TEXT CONTENT (Normal Reply) ---
            if delta.content:
                yield "text", delta.content
                full_content_buffer += delta.content

            # --- CASE B: TOOL CALLING (Native) ---
            if delta.tool_calls:
                is_tool_call = True

                for tool_chunk in delta.tool_calls:
                    idx = tool_chunk.index

                    # Initialize this tool index if new
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"id": "", "name": "", "args": ""}
                        yield "status", "🧠 The Reaper is grabbing a tool..."

                    # Append parts (ID and Name usually come in the first chunk of the tool)
                    if tool_chunk.id:
                        tool_calls_buffer[idx]["id"] += tool_chunk.id

                    if tool_chunk.function.name:
                        tool_calls_buffer[idx]["name"] += tool_chunk.function.name
                        # Optional: Yield action update
                        friendly_name = agent_tools.get_friendly_status(tool_calls_buffer[idx]['name'])
                        yield "status", f"{friendly_name}"

                    if tool_chunk.function.arguments:
                        tool_calls_buffer[idx]["args"] += tool_chunk.function.arguments

        # 3. End of Stream Logic
        if is_tool_call:
            # Construct the Assistant Message properly with Tool Calls
            # OpenAI requires the 'tool_calls' list in the message object
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

            # Append ASSISTANT message to history (The "Request")
            # Note: Content is null for pure tool calls
            chat_history.append({
                "role": "assistant",
                "content": full_content_buffer if full_content_buffer else None,
                "tool_calls": final_tool_calls
            })

            # 4. EXECUTE TOOLS
            for tool_call in final_tool_calls:
                call_id = tool_call["id"]
                func_name = tool_call["function"]["name"]
                func_args_str = tool_call["function"]["arguments"]

                # Notify UI
                friendly_status = agent_tools.get_friendly_status(func_name)
                yield "status", f"{friendly_status} Working..."
                print(f"Agent Calling: {func_name} | ID: {call_id}")

                try:
                    # Parse arguments safely
                    params = json.loads(func_args_str)

                    # get action and yield it
                    action_desc = params.get("action_description")
                    yield "action", action_desc

                    # Execute the tool/function
                    tool_result_str, hint, action = agent_tools.execute_tool({"tool": func_name, "params": params})

                except Exception as e:
                    tool_result_str = f"Error executing tool: {str(e)}"

                # Append TOOL message to history (The "Result")
                # This closes the loop with the ID
                chat_history.append({
                    "role": "tool",
                    "tool_call_id": call_id,  # <--- CRITICAL: MUST MATCH REQUEST ID
                    "name": func_name,
                    "content": tool_result_str
                })

            # Loop again to let the Agent read the tool result and reply
            turn += 1
            yield "status", "Reading results..."

        else:
            # Just text, we are done
            chat_history.append({"role": "assistant", "content": full_content_buffer})
            return

    yield "text", "\n\n(Max turns reached.)"
