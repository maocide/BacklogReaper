import time
import json
import threading
import traceback
import uuid
import asyncio
import queue
from warnings import catch_warnings

import flet as ft

import agent
import character_manager
import vault
import settings
from character_manager import CharacterManager, Character
import game_intelligence
from vibe_engine import VibeEngine
import styles
from chat_history import ChatHistory

import ui.utils
from ui.widgets.chat_bubble import ReaperChatBubble
from ui.widgets.game_card import GameCard
from ui.widgets.styled_inputs import GrimoireTextField, GrimoireProgressBar

class ReaperChatView(ft.Container):
    def __init__(self):
        super().__init__()
        self.confirm_dialog = None
        self.expand = True
        self.padding = ft.Padding(0, 5, 5, 10)

        # Initialize ChatHistory and Agent
        self.chat_history = ChatHistory()
        self.character = None
        self.agent = agent.Agent()

        self.br_chat_list = ft.Ref[ft.Column]()
        self.br_input = ft.Ref[ft.TextField]()
        self.br_status = ft.Ref[ft.Text]()
        self.br_btn_send = ft.Ref[ft.IconButton]()
        self.br_btn_stop = ft.Ref[ft.IconButton]()
        self.br_empty_state = ft.Ref[ft.Container]()
        self.br_empty_state_name = ft.Ref[ft.Text]()

        # Threading
        self.current_run_id = None
        self.current_stop_event = None
        self.current_streaming_bubble = None  # Track the active streaming bubble control
        self.stream_queue = queue.Queue()

        self.user_portrait_url = None

        self.current_scroll_offset = 0
        self.max_scroll_extent = 0
        self.stick_to_bottom = True
        self.last_scroll_pixels = 0
        self.max_chat_bubbles = 50  # Limit visible bubbles to prevent UI lag/leaks

        self.stream_active = False

        # State for streaming
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None,
            "needs_update": False
        }

        self.content = ft.Column([
            ft.Row([
                ft.Text("Reaper Chat", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family=styles.FONT_HEADING),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    tooltip="Wipe Ledger",
                    on_click=self.prompt_clear_chat
                ),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy Chat History", on_click=self.copy_chat_history),
            ]),
            ft.Container(
                expand=True,
                padding=0,
                content=ft.Stack(
                    controls=[
                        # Background
                        self._build_empty_state(),
                        # Chat List (Transparent overlay)
                        ft.Column(
                            ref=self.br_chat_list,
                            on_scroll=self.handle_scroll,
                            expand=True,
                            spacing=10,
                            auto_scroll=False,
                            scroll=ft.ScrollMode.AUTO,
                            scroll_interval=100,
                        )
                    ],
                    expand=True,
                )
            ),
            ft.Text(ref=self.br_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY, size=12),
            ft.Row([
                GrimoireTextField(
                    ref=self.br_input,
                    hint_text="Consult the Reaper...",
                    expand=True,
                    multiline=True,
                    shift_enter=True,
                    on_submit=self.send_message,
                    label_style=ft.TextStyle(italic=True, color=styles.COLOR_ACCENT_DIM)
                ),
                ft.IconButton(ref=self.br_btn_send, icon=ft.Icons.SEND, tooltip="Consult", icon_color=styles.COLOR_TEXT_GOLD, on_click=self.send_message),
                ft.IconButton(ref=self.br_btn_stop, icon=ft.Icons.STOP_CIRCLE_OUTLINED, icon_color=styles.COLOR_TEXT_GOLD, on_click=self.stop, visible=False),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ])

    def did_mount(self):
        # Prefetch avatar without blocking using standard threading
        threading.Thread(target=self._prefetch_avatar, daemon=True).start()

        # Initialize Character
        self._initialize_character()

        # Reload chat history
        self._reload_chat_from_history()

    def will_unmount(self):
        # Stop any active stream if unmounting
        if self.current_stop_event:
            self.current_stop_event.set()
        self.stream_active = False

    def _initialize_character(self):
        current_settings = settings.load_settings()
        char_name = current_settings.get("CHARACTER", "Reaper")
        self.character = CharacterManager.load_character(char_name)
        if not self.character:
             self.character = Character.default()
        self.chat_history.load_character(self.character)
        self.chat_history.load()

    def _prefetch_avatar(self):
        try:
            url = game_intelligence.get_steam_avatar(settings.STEAM_USER)

            # If we got a valid URL that is different from what we have
            if url and url != self.user_portrait_url:
                self.user_portrait_url = url

                # Retroactively update any user bubbles already on the screen
                if self.br_chat_list.current and self.br_chat_list.current.page:
                    for ctrl in self.br_chat_list.current.controls:
                        # Check if this control is a user chat bubble
                        if getattr(ctrl, "is_user", False):
                            ctrl.set_avatar(url)
                            # Safely update just the bubble
                            self.page.run_task(ui.utils.smart_update, ctrl)

        except Exception as e:
            print(f"Error fetching avatar: {e}")

    def _reload_chat_from_history(self):
        self.br_chat_list.current.controls.clear()
        if self.chat_history.get_chat_length():
            self.hide_background()

            for message in self.chat_history.messages:
                content = message.get('content', None)
                if message.get('role') == 'assistant' and content:
                    self.br_chat_list.current.controls.append(
                        self.parse_and_render_message(text=content, is_user=False, avatar_path=CharacterManager.get_character_image(self.character.name))
                    )
                elif message.get('role') == 'user' and content:
                    self.br_chat_list.current.controls.append(
                        self.parse_and_render_message(text=content, is_user=True, avatar_path=self.get_user_portrait_url())
                    )

            if self.chat_history.messages and self.chat_history.messages[-1].get('role') == 'assistant':
                self._append_message_actions()

        self.scroll_chat_to_bottom(500,0,True)

    def _build_empty_state(self):
        current_char = ""
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
            if current_char == "Reaper":
                current_char = "the Reaper"
        except Exception as e:
            print(f"Error loading settings: {e}")

        return ft.Container(
            ref=self.br_empty_state,  # We need a ref to hide it later
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.Image(
                        src="assets/summoning_circle.png",
                        width=450, height=450,
                        fit=ft.BoxFit.CONTAIN,
                        opacity=0.12,  # Ghostly faint
                        color_blend_mode=ft.BlendMode.MODULATE  # Optional blending
                    ),
                    ft.Text("The Ledger is Open", font_family=styles.FONT_HEADING, size=22, opacity=0.7),
                    ft.Text(f"Summon {current_char}...", font_family=styles.FONT_MONO, size=12, italic=True,
                            color=styles.COLOR_TEXT_SECONDARY , ref=self.br_empty_state_name),
                ]
            )
        )

    def update_data_sources(self):
        vault.update(settings.STEAM_USER)
        vibes = VibeEngine.get_instance()
        vibes.ingest_library()

    def copy_chat_history(self, e):
        if not self.chat_history.messages: return

        full_log = ""
        for msg in self.chat_history.messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            full_log += f"**{role}**: {content}\n\n"

        self.page.run_task(ft.Clipboard().set, full_log)

        self.page.show_dialog(ft.SnackBar(ft.Text("Chat history copied to clipboard!")))
        self.page.update()

    def handle_scroll(self, e: ft.OnScrollEvent):
        # Calculate delta to detect direction
        delta = e.pixels - self.last_scroll_pixels
        self.last_scroll_pixels = e.pixels

        self.current_scroll_offset = e.pixels
        self.max_scroll_extent = e.max_scroll_extent

        # Logic for "Stick to Bottom"
        # If we are at the bottom, lock it.
        # If we scroll up significantly, unlock it.
        distance_from_bottom = e.max_scroll_extent - e.pixels
        is_at_bottom = distance_from_bottom <= 30  # slightly tighter threshold for latching

        if is_at_bottom:
            self.stick_to_bottom = True
        elif delta < -5: # User is scrolling up
            self.stick_to_bottom = False

    def get_user_portrait_url(self):
        # Return cached URL if available, otherwise return None (default avatar will be used)
        # We do NOT block here.
        return self.user_portrait_url

    def parse_and_render_message(self, text, is_user, reasoning_text=None, avatar_path=None, reasoning_expanded=False):
        controls = []

        # If it's a user message or no JSON, just render markdown
        if "```json" not in text or is_user:
            controls.append(ft.Markdown(text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
        else:
            segments = text.split("```json")

            if segments[0].strip():
                controls.append(ft.Markdown(segments[0].strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

            for segment in segments[1:]:
                if "```" in segment:
                    json_part, post_text = segment.split("```", 1)
                    try:
                        games_list = json.loads(json_part)
                        if isinstance(games_list, list):
                            card_row = ft.Row(wrap=True, spacing=10, run_spacing=10)
                            for game in games_list:
                                card_row.controls.append(GameCard(game))
                            controls.append(ft.Container(content=card_row, padding=5))
                        else:
                            controls.append(ft.Markdown(f"```json{json_part}```"))
                    except json.JSONDecodeError:
                        controls.append(ft.Markdown(f"```json{json_part}```"))

                    if post_text.strip():
                        controls.append(ft.Markdown(post_text.strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
                else:
                    controls.append(ft.Markdown(f"```json{segment}", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

        bubble_content = ft.Column(controls, tight=True, spacing=5)

        user_avatar_name = settings.STEAM_USER if settings.STEAM_USER else "USER"
        current_char_name = "Reaper"
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Ember")
            current_char_name = CharacterManager.load_character(current_char).name
        except:
            print("Error getting character name")

        avatar_name = user_avatar_name if is_user else current_char_name

        reasoning_control = None
        if reasoning_text and not is_user:
            reasoning_control = ft.Markdown(value=reasoning_text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=True, selectable=True)

        return ReaperChatBubble(
            avatar_name=avatar_name,
            content_control=bubble_content,
            is_user=is_user,
            reasoning_control=reasoning_control,
            reasoning_title="Dark Machinations...",
            avatar_src=avatar_path,
            reasoning_expanded=reasoning_expanded
        )

    def run_backlog_reaping_thread(self, user_message, run_id, stop_event):
        try:
            if stop_event.is_set(): return

            # Signal initialization immediately for responsiveness
            self.stream_queue.put({"type": "init", "run_id": run_id})

            # Note: Update logic moved to main thread before spawning this thread

            # CONSUME THE STREAM
            stream = self.agent.chat_stream(user_message, self.chat_history)

            for event_type, content in stream:
                if stop_event.is_set(): break
                self.stream_queue.put({"type": event_type, "content": content, "run_id": run_id})

            # Final Cleanup
            if not stop_event.is_set():
                self.stream_queue.put({"type": "finish", "run_id": run_id})
            else: # Stop button, cancel event
                self.stream_queue.put({"type": "cancel", "run_id": run_id})

        except Exception as e:
            traceback.print_exc()
            self.stream_queue.put({"type": "error", "content": str(e), "run_id": run_id})
        finally:
            self.stream_queue.put({"type": "cleanup", "run_id": run_id})

    async def _render_loop(self):
        """
        Dedicated background task to update UI from stream queue and state.
        Decouples message processing speed from UI rendering speed (RPC calls).
        """
        while self.stream_active or not self.stream_queue.empty():
            # Process all available items in the queue
            while not self.stream_queue.empty():
                try:
                    message = self.stream_queue.get_nowait()
                    await self._process_stream_message(message)
                except queue.Empty:
                    break

            # If updates are pending, apply them to the UI
            if self.stream_state.get("needs_update", False):
                state = self.stream_state

                # Update Reasoning
                if state["reasoning_view"] and state["reasoning_view"].page and state["reasoning_view"].visible:
                     await ui.utils.smart_update(state["reasoning_view"])
                if state["reasoning_container_ref"] and state["reasoning_container_ref"].current and state["reasoning_container_ref"].current.page and state["reasoning_container_ref"].current.visible:
                     await ui.utils.smart_update(state["reasoning_container_ref"].current)

                # Update Status Text (for visibility changes or text updates)
                if state["status_text"] and state["status_text"].page:
                     await ui.utils.smart_update(state["status_text"])

                # Update Markdown
                if state["agent_markdown"] and state["agent_markdown"].page:
                    await ui.utils.smart_update(state["agent_markdown"])

                self.scroll_chat_to_bottom(duration=50)
                self.stream_state["needs_update"] = False

            # If stream is inactive and queue is empty, exit loop
            if not self.stream_active and self.stream_queue.empty():
                break

            await asyncio.sleep(0.05)

    async def _process_stream_message(self, message):
        """
        Internal handler to process stream messages and update state/UI.
        Replaces _on_message_async.
        """
        msg_run_id = message.get("run_id")

        # Ignore messages from old/zombie threads
        if msg_run_id != self.current_run_id:
            return

        msg_type = message.get("type")
        content = message.get("content")
        state = self.stream_state

        if msg_type == "init":
            # Clean up any existing streaming bubble to prevent duplicates
            if self.current_streaming_bubble:
                try:
                    if self.br_chat_list.current and self.current_streaming_bubble in self.br_chat_list.current.controls:
                        self.br_chat_list.current.controls.remove(self.current_streaming_bubble)
                except Exception:
                    pass
                self.current_streaming_bubble = None

            state["status_text"] = ft.Text("Initializing...", italic=True, size=12, color=ft.Colors.GREY_500)
            state["agent_markdown"] = ft.Markdown("", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
            state["reasoning_view"] = ft.Markdown("", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=False, selectable=True)
            state["reasoning_buffer"] = ""

            # Get Real Name and Avatar
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
            real_char_name = CharacterManager.get_character_real_name(current_char)
            avatar_path = CharacterManager.get_character_image(current_char)

            bubble_content = ft.Column([state["status_text"], state["agent_markdown"]], tight=True, spacing=5)

            reasoning_ref = ft.Ref()
            state["reasoning_container_ref"] = reasoning_ref

            full_message_block = ReaperChatBubble(
                avatar_name=real_char_name,
                content_control=bubble_content,
                is_user=False,
                reasoning_control=state["reasoning_view"],
                reasoning_title="Consulting the Void...",
                reasoning_ref=reasoning_ref,
                reasoning_visible=False,
                avatar_src=avatar_path,
                reasoning_expanded=False
            )

            # Store reference to the streaming bubble for later removal
            self.current_streaming_bubble = full_message_block

            if self.br_chat_list.current:
                self.br_chat_list.current.controls.append(full_message_block)
                await ui.utils.smart_update(self.br_chat_list.current)
                self.scroll_chat_to_bottom(forced=True, delay_ms=600)

        elif msg_type == "reasoning":
            state["reasoning_buffer"] += content
            if state["reasoning_view"]:
                state["reasoning_view"].value = state["reasoning_buffer"]
                state["reasoning_view"].visible = True

            if "reasoning_container_ref" in state and state["reasoning_container_ref"].current:
                state["reasoning_container_ref"].current.visible = True

            state["needs_update"] = True

        elif msg_type == "status":
            if state["status_text"]:
                state["status_text"].value = content
                try:
                    await ui.utils.smart_update(state["status_text"])
                except RuntimeError:
                    pass

            if self.br_status.current:
                self.br_status.current.value = content
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                if self.br_status.current.page:
                    await ui.utils.smart_update(self.br_status.current)

        elif msg_type == "action":
            if self.br_chat_list.current:
                action_display = ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.TERMINAL, size=14, color=styles.COLOR_SYSTEM_LOG),
                        ft.Text(f"> {content}", size=12, font_family=styles.STYLE_MONOSPACE, color=styles.COLOR_SYSTEM_LOG)
                    ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=5),
                )

                position = len(self.br_chat_list.current.controls) - 1
                if position < 0: position = 0
                self.br_chat_list.current.controls.insert(position, action_display)

            try:
                await ui.utils.smart_update(self.br_chat_list.current)
                self.scroll_chat_to_bottom(duration=50)
            except RuntimeError:
                pass

            state["previous_was_tool"] = True

        elif msg_type == "text":
            # Update state synchronously first
            if state["status_text"] and state["status_text"].visible:
                state["status_text"].visible = False

            if state["previous_was_tool"] and not state["first_text"]:
                state["agent_markdown"].value += "\n\n"

            state["agent_markdown"].value += content

            state["previous_was_tool"] = False
            state["first_text"] = False

            state["needs_update"] = True

        elif msg_type == "finish":
            self.stream_active = False # Signal loop to exit (after queue empty)

            if not self.current_streaming_bubble:
                return

            # Force final flush of streaming controls to ensure completeness before replacement
            if state["agent_markdown"] and state["agent_markdown"].page:
                await ui.utils.smart_update(state["agent_markdown"])

            if state["reasoning_view"] and state["reasoning_view"].page:
                await ui.utils.smart_update(state["reasoning_view"])

            final_text = state["agent_markdown"].value
            final_reasoning = state["reasoning_buffer"]

            bubble_to_remove = self.current_streaming_bubble
            self.current_streaming_bubble = None

            if self.br_chat_list.current:
                current_settings = settings.load_settings()
                current_char = current_settings.get("CHARACTER", "Reaper")
                avatar_path = CharacterManager.get_character_image(current_char)

                was_reasoning_expanded = getattr(bubble_to_remove, "reasoning_expanded", False)

                try:
                    if bubble_to_remove in self.br_chat_list.current.controls:
                        self.br_chat_list.current.controls.remove(bubble_to_remove)
                except ValueError:
                    pass

                final_msg_control = self.parse_and_render_message(
                    final_text,
                    is_user=False,
                    reasoning_text=final_reasoning,
                    avatar_path=avatar_path,
                    reasoning_expanded=was_reasoning_expanded
                )
                self.br_chat_list.current.controls.append(final_msg_control)

                self._append_message_actions()

                await ui.utils.smart_update(self.br_chat_list.current)
                self.scroll_chat_to_bottom(delay_ms=100, forced=True)


            await self.update_buttons(False)

            if self.br_status.current:
                self.br_status.current.value = "Ready"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                await ui.utils.smart_update(self.br_status.current)

            # Finished we now save chat status
            self.chat_history.save()

        elif msg_type == "error":
            self.stream_active = False

            # Clean chat UI and chat history
            self.br_input.current.value = await self.remove_last_ai_response(including_user=True)

            self.page.show_dialog(ft.SnackBar(ft.Text("Error: " + content)))

            if self.br_status.current:
                self.br_status.current.value = f"Error: {content}"
                self.br_status.current.color = styles.COLOR_ERROR

            await ui.utils.smart_update(self.page)

        elif msg_type == "cancel":
            self.stream_active = False

            # Clean chat UI and chat history
            self.br_input.current.value = await self.remove_last_ai_response(including_user=True)

            if self.br_status.current:
                self.br_status.current.value = "Cancelled"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY

            await ui.utils.smart_update(self.page)

        elif msg_type == "cleanup":
            # Just ensure buttons are reset, stream_active should be False by now via other events
            await self.update_buttons(False)

    async def _scroll_task(self, duration, delay_ms):
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        if self.br_chat_list.current:
            try:
                # Flet > 0.80: scroll_to is awaitable
                res = self.br_chat_list.current.scroll_to(offset=-1, duration=duration)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def scroll_chat_to_bottom(self, duration=700, delay_ms=0, forced=False):
        if forced:
            self.stick_to_bottom = True
            if self.br_chat_list.current and self.page:
                try:
                    self.page.run_task(self._scroll_task, duration, delay_ms)
                except Exception:
                    pass
            return

        # Only scroll if locked to bottom
        if self.stick_to_bottom:
            if self.br_chat_list.current and self.page:
                try:
                    self.page.run_task(self._scroll_task, duration, delay_ms)
                except Exception:
                    pass

    def start_chat_thread(self, user_message):
        # Stop previous thread cleanly
        if self.current_stop_event:
            self.current_stop_event.set()

        # Update prompt with current character from settings before starting
        ####self._initialize_character()
        # this leads to duplicate messages on regenerate, or we could save state on regenerate message removal

        # Create new ID and Event
        new_run_id = str(uuid.uuid4())
        self.current_run_id = new_run_id

        new_stop_event = threading.Event()
        self.current_stop_event = new_stop_event

        # Ensure queue is clean-ish (we can't easily clear a Queue, but we rely on run_id filtering)
        # Ideally we'd replace the queue, but that's messy if the loop is reading.
        # But filter by run_id handles it.

        # Reset state
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None,
            "needs_update": False
        }
        self.current_streaming_bubble = None

        # Start background render loop
        self.stream_active = True
        if hasattr(self.page, 'run_thread'):
            self.page.run_task(self._render_loop)
        else:
            threading.Thread(target=self._render_loop, daemon=True).start()

        # Start thread
        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_backlog_reaping_thread, user_message, new_run_id, new_stop_event)
        else:
             threading.Thread(target=self.run_backlog_reaping_thread, args=(user_message, new_run_id, new_stop_event), daemon=True).start()

    def _append_message_actions(self):
        """Builds and appends the action buttons below the latest AI response."""
        if not self.br_chat_list.current:
            return

        actions_row = ft.Row(
            controls=[
                # Delete/Undo Button
                ft.IconButton(
                    icon=ft.Icons.UNDO,
                    tooltip="Delete & Edit Last Prompt",
                    icon_color=styles.COLOR_TEXT_SECONDARY,
                    on_click=self.delete_last_click,
                    icon_size=20,
                ),
                # Regenerate Button
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Regenerate Response",
                    icon_color=styles.COLOR_TEXT_SECONDARY,
                    on_click=self.regenerate_click,
                    icon_size=20,
                )
            ],
            alignment=ft.MainAxisAlignment.END,
            data="message_action_buttons"
        )
        self.br_chat_list.current.controls.append(actions_row)

    async def remove_message_actions(self, perform_update=True):
        if self.br_chat_list.current and self.br_chat_list.current.controls:
            last_ctrl = self.br_chat_list.current.controls[-1]

            # Check for new ID or old ID
            ctrl_data = getattr(last_ctrl, "data", "")
            if ctrl_data == "message_action_buttons" or ctrl_data == "regenerate_button":
                self.br_chat_list.current.controls.pop()
                if perform_update:
                    await ui.utils.smart_update(self.br_chat_list.current)
                return

            # Legacy check (fallback)
            if isinstance(last_ctrl, ft.Row) and last_ctrl.controls and isinstance(last_ctrl.controls[0], ft.IconButton):
                 if last_ctrl.controls[0].icon == ft.Icons.REFRESH:
                    self.br_chat_list.current.controls.pop()
                    if perform_update:
                        await ui.utils.smart_update(self.br_chat_list.current)

    async def delete_last_click(self, e):
        # Remove the action buttons row
        await self.remove_message_actions(perform_update=False)

        # Pop AI and User messages, and grab the user's text
        user_text = await self.remove_last_ai_response(including_user=True)

        # Put text back in the input box
        if user_text and self.br_input.current:
            self.br_input.current.value = user_text
            await ui.utils.smart_update(self.br_input.current)

        # Append actions again
        if self.chat_history.messages and self.chat_history.messages[-1].get('role') == 'assistant':
            self._append_message_actions()

        # Scroll and save
        self.scroll_chat_to_bottom(forced=True, duration=0, delay_ms=50)
        self.chat_history.save()
        await self.update_buttons(False) # Ensure we are in "Ready" state

    async def regenerate_click(self, e):
        await self.remove_message_actions(perform_update=False)

        await self.remove_last_ai_response(including_user=False)

        if self.br_chat_list.current:
            self.current_scroll_offset = 0
            self.max_scroll_extent = 0
            self.scroll_chat_to_bottom(forced=True, duration=0, delay_ms=50)

        await self.update_buttons(True)

        if self.chat_history.messages:
             last_msg = self.chat_history.messages[-1]
             if last_msg["role"] == "user":
                 user_message = last_msg["content"]
                 self.chat_history.pop()
                 self.start_chat_thread(user_message)

    async def remove_last_ai_response(self, including_user=False):
        # History update
        while self.chat_history.messages and not self.chat_history.messages[-1]["role"] == "user":
            self.chat_history.pop()

        user_text = ""
        if including_user:
            if self.chat_history.messages and self.chat_history.messages[-1]["role"] == "user":
                user_text = self.chat_history.messages[-1]["content"]
                self.chat_history.pop()

        # UI update
        while self.br_chat_list.current.controls:
            last_ctrl = self.br_chat_list.current.controls[-1]

            is_user_message = False
            if isinstance(last_ctrl, ReaperChatBubble) and getattr(last_ctrl, "is_user", False):
                is_user_message = True
            elif getattr(last_ctrl, "data", None) == "user_message":
                is_user_message = True

            if is_user_message:
                if including_user: # Force to pop user message too
                    self.br_chat_list.current.controls.pop()
                    return user_text
                break

            self.br_chat_list.current.controls.pop()
        return None

    async def prune_chat_ui(self):
        """
        Removes oldest chat bubbles if the list exceeds the maximum limit.
        """
        if not self.br_chat_list.current:
            return

        controls = self.br_chat_list.current.controls
        if len(controls) > self.max_chat_bubbles:
            excess = len(controls) - self.max_chat_bubbles
            for _ in range(excess):
                controls.pop(0)

    def hide_background(self):
        # Hide Background
        if self.br_empty_state.current.visible:
            self.br_empty_state.current.visible = False
            self.br_empty_state.current.update()

    def refresh_state(self):
        """Called by flet main page/controller when the user navigates back to this tab."""
        # Check if the character actually changed in settings
        current_settings = settings.load_settings()
        new_char_name = current_settings.get("CHARACTER", "Reaper")

        # If the character changed, we must reload the chat
        if not self.character or self.character.name != new_char_name:
            self.chat_history.reset_history()  # Removes all messages
            self._initialize_character()  # Loads the new Character and JSON

            # Update the Summoning Circle text
            if self.br_empty_state.current:
                char_display = new_char_name if new_char_name != "Reaper" else "the Reaper"
                self.br_empty_state_name.current.value = f"Summon {char_display}..."
                self.br_empty_state.current.update()
                self.br_empty_state_name.current.update()

            self._reload_chat_from_history()  # Rebuilds UI from new JSON

            # If the new history is empty, ensure the circle is visible
            if not self.chat_history.get_chat_length() and self.br_empty_state.current:
                self.br_empty_state.current.visible = True
            else:
                self.hide_background()

            self.update()
        else:
            self.scroll_chat_to_bottom(forced=True, duration=500, delay_ms=0)

    def _sync_data_sources_blocking(self):
        # This function runs in a separate thread
        try:
            vault.update(settings.STEAM_USER)
            vibes = VibeEngine.get_instance()
            vibes.ingest_library()
        except Exception as e:
            print(f"Sync error: {e}")

    async def stop(self, e):
        if self.current_stop_event:
            self.current_stop_event.set()

    async def update_buttons(self, is_running):
        if is_running:
            self.br_input.current.disabled = True
            self.br_btn_send.current.disabled = True
            self.br_btn_send.current.visible = False
            self.br_btn_stop.current.visible = True
        else:
            self.br_input.current.disabled = False
            self.br_btn_send.current.disabled = False
            self.br_btn_send.current.visible = True
            self.br_btn_stop.current.visible = False

        if self.br_input.current:
            await ui.utils.smart_update(self.br_input.current)
        if self.br_btn_send.current:
            await ui.utils.smart_update(self.br_btn_send.current)
        if self.br_btn_stop.current:
            await ui.utils.smart_update(self.br_btn_stop.current)


    async def send_message(self, e):
        user_message = self.br_input.current.value
        if not user_message:
            return

        # Hide Background
        self.hide_background()

        self.br_input.current.value = ""
        await self.update_buttons(True) # Show/hide buttons

        user_portrait_url = self.get_user_portrait_url()

        await self.remove_message_actions(perform_update=False)

        if self.br_chat_list.current:
            # Prune before adding new message to keep list size stable
            await self.prune_chat_ui()

            self.br_chat_list.current.controls.append(self.parse_and_render_message(user_message, is_user=True, avatar_path=user_portrait_url))
            await ui.utils.smart_update(self.br_chat_list.current)
            self.scroll_chat_to_bottom(delay_ms=200, forced=True)

        # Check for Sync Needed
        if vault.get_games_count() and vault.get_elapsed_since_update() > 1200: # 20 Mins
            # Inject System Status Bubble
            sync_bubble = ft.Container(
                content=ft.Row(
                    controls=[
                        GrimoireProgressBar(
                            width=300,
                            height=12
                        ),
                        ft.Text("Channeling into game library...", color=styles.COLOR_SYSTEM_LOG, size=12, font_family=styles.STYLE_MONOSPACE)
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10
                ),
                padding=10,
                alignment=ft.Alignment.CENTER
            )

            # Add to chat (temporarily)
            if self.br_chat_list.current:
                 self.br_chat_list.current.controls.append(sync_bubble)
                 await ui.utils.smart_update(self.br_chat_list.current)
                 self.scroll_chat_to_bottom(duration=100, forced=True)

            # Run blocking update in thread, await it here
            await asyncio.to_thread(self._sync_data_sources_blocking)

            # Remove the bubble
            if self.br_chat_list.current:
                if sync_bubble in self.br_chat_list.current.controls:
                    self.br_chat_list.current.controls.remove(sync_bubble)
                    await ui.utils.smart_update(self.br_chat_list.current)


        self.start_chat_thread(user_message)

    def prompt_clear_chat(self, e):
        """Opens the confirmation dialog."""

        # Define the dialog
        self.confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Burn the Ledger?", font_family=styles.FONT_HEADING, color=styles.COLOR_ERROR),
            content=ft.Text("Are you sure you want to wipe chat history? This action cannot be undone.",
                            color=styles.COLOR_TEXT_PRIMARY),
            bgcolor=styles.COLOR_SURFACE,
            shape=ft.RoundedRectangleBorder(radius=8),
            actions=[
                ft.TextButton(
                    "Cancel",
                    style=ft.ButtonStyle(color=styles.COLOR_TEXT_SECONDARY),
                    on_click=self.close_dialog
                ),
                ft.FilledButton(
                    "Wipe It",
                    style=ft.ButtonStyle(
                        bgcolor=styles.COLOR_ERROR,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=5)
                    ),
                    on_click=self.execute_clear_chat
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        # Show the dialog (Using Flet 0.22+ syntax)
        self.page.show_dialog(self.confirm_dialog)

    def close_dialog(self, e):
        """Closes the dialog without doing anything."""
        if self.confirm_dialog:
            self.confirm_dialog.open = False
            self.page.update()

    def execute_clear_chat(self, e):
        """Performs the actual deletion after confirmation."""

        # Clear the backend data (Assuming you made a method that keeps the system prompt)
        self.chat_history.reset_history()
        self.chat_history.save()

        # Clear the Flet UI column
        if self.br_chat_list.current:
            self.br_chat_list.current.controls.clear()

        # Bring back the Summoning Circle
        if self.br_empty_state.current:
            self.br_empty_state.current.visible = True

        # close dialog
        self.confirm_dialog.open = False

        self.update()