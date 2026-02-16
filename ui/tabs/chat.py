import time
import json
import threading
import traceback
import uuid
import asyncio

import flet as ft

import agent
import vault
import settings
import character_manager
import game_intelligence
from vibe_engine import VibeEngine
import styles

import ui.utils
from ui.widgets.chat_bubble import ReaperChatBubble
from ui.widgets.game_card import GameCard
from ui.widgets.styled_inputs import GrimoireTextField

class ReaperChatView(ft.Column):
    def __init__(self):
        super().__init__()
        self.expand = True

        self.br_chat_history = []
        self.br_chat_list = ft.Ref[ft.Column]()
        self.br_input = ft.Ref[ft.TextField]()
        self.br_status = ft.Ref[ft.Text]()
        self.br_btn_send = ft.Ref[ft.IconButton]()

        # Robust Threading
        self.current_run_id = None
        self.current_stop_event = None
        self.current_streaming_bubble = None  # Track the active streaming bubble control

        self.user_portrait_url = None

        self.current_scroll_offset = 0
        self.max_scroll_extent = 0
        self.scroll_buffer = 50
        self.max_chat_bubbles = 50  # Limit visible bubbles to prevent UI lag/leaks

        # Throttling state
        self.last_scroll_ts = 0


        # State for streaming
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None
        }

        self.controls = [
            ft.Row([
                ft.Text("Reaper Chat", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family="Cinzel"),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy Chat History", on_click=self.copy_chat_history)
            ]),
            ft.Container(
                content=ft.Column(
                    ref=self.br_chat_list,
                    on_scroll=self.handle_scroll,
                    expand=True,
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=10,
                expand=True,
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
                ft.IconButton(ref=self.br_btn_send, icon=ft.Icons.SEND, icon_color=styles.COLOR_TEXT_GOLD, on_click=self.send_message)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]

    def did_mount(self):
        # We subscribe when the view is mounted
        self.page.pubsub.subscribe(self.on_message)
        # Prefetch avatar without blocking using standard threading
        threading.Thread(target=self._prefetch_avatar, daemon=True).start()

    def will_unmount(self):
        self.page.pubsub.unsubscribe(self.on_message)

    def _prefetch_avatar(self):
        try:
             self.user_portrait_url = game_intelligence.get_steam_avatar(settings.STEAM_USER)
        except Exception as e:
            print(f"Error fetching avatar: {e}")

    def update_data_sources(self):
        vault.update(settings.STEAM_USER)
        vibes = VibeEngine.get_instance()
        vibes.ingest_library()

    def copy_chat_history(self, e):
        if not self.br_chat_history: return

        full_log = ""
        for msg in self.br_chat_history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            full_log += f"**{role}**: {content}\n\n"

        self.page.run_task(ft.Clipboard().set, full_log)

        self.page.snack_bar = ft.SnackBar(ft.Text("Chat history copied to clipboard!"))
        self.page.snack_bar.open = True
        self.page.update()

    def handle_scroll(self, e: ft.OnScrollEvent):
        self.current_scroll_offset = e.pixels
        self.max_scroll_extent = e.max_scroll_extent

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
        current_char = "Reaper"
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
        except:
            print("Error loading settings for character.")

        avatar_name = user_avatar_name if is_user else current_char

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
            self.page.pubsub.send_all({"type": "init", "run_id": run_id})

            # Note: Update logic moved to main thread before spawning this thread

            # CONSUME THE STREAM
            stream = agent.agent_chat_loop_stream(user_message, self.br_chat_history)

            for event_type, content in stream:
                if stop_event.is_set(): break
                time.sleep(0.02) # Small yield
                self.page.pubsub.send_all({"type": event_type, "content": content, "run_id": run_id})

            # Final Cleanup
            if not stop_event.is_set():
                self.page.pubsub.send_all({"type": "finish", "run_id": run_id})

        except Exception as e:
            traceback.print_exc()
            self.page.pubsub.send_all({"type": "error", "content": str(e), "run_id": run_id})
        finally:
            self.page.pubsub.send_all({"type": "cleanup", "run_id": run_id})

    async def _scroll_task(self, duration, delay_ms):
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        if self.br_chat_list.current:
            try:
                # Flet > 0.80: scroll_to is awaitable
                # Check if it's awaitable or just assume based on user feedback
                # To be safe: check if asyncio.iscoroutine or hasattr(awaitable)
                # But typically calling it returns the coroutine object if async.

                res = self.br_chat_list.current.scroll_to(offset=-1, duration=duration)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def scroll_chat_to_bottom(self, duration=700, delay_ms=0, forced=False):
        # Distance for scroll
        distance_from_bottom = self.max_scroll_extent - self.current_scroll_offset
        safe_scroll = distance_from_bottom <= self.scroll_buffer

        if forced:
            if self.br_chat_list.current and self.page:
                try:
                    self.last_scroll_ts = time.time()
                    self.page.run_task(self._scroll_task, duration, delay_ms)
                except Exception:
                    print("Error scrolling chat to bottom (forced).")
                    pass
            return

        if safe_scroll:
            now = time.time()
            if (now - self.last_scroll_ts) > 0.1: # Throttle: max 1 scroll every 100ms
                if self.br_chat_list.current and self.page:
                    try:
                        self.last_scroll_ts = now
                        self.page.run_task(self._scroll_task, duration, delay_ms)
                    except Exception:
                        print("Error scrolling chat to bottom.")
                        pass

    def start_chat_thread(self, user_message):
        # Stop previous thread cleanly
        if self.current_stop_event:
            self.current_stop_event.set()

        # Create new ID and Event
        new_run_id = str(uuid.uuid4())
        self.current_run_id = new_run_id

        new_stop_event = threading.Event()
        self.current_stop_event = new_stop_event

        # Reset state
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None
        }
        self.current_streaming_bubble = None

        # Start thread
        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_backlog_reaping_thread, user_message, new_run_id, new_stop_event)
        else:
             threading.Thread(target=self.run_backlog_reaping_thread, args=(user_message, new_run_id, new_stop_event), daemon=True).start()

    def on_message(self, message):
        # Delegate to async handler on main thread to avoid race conditions
        if self.page:
            self.page.run_task(self._on_message_async, message)

    async def _on_message_async(self, message):
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
            real_char_name = character_manager.get_character_real_name(current_char)
            avatar_path = character_manager.get_character_image(current_char)

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
                if state["reasoning_view"].page:
                    await ui.utils.smart_update(state["reasoning_view"])
                if "reasoning_container_ref" in state and state["reasoning_container_ref"].current:
                    state["reasoning_container_ref"].current.visible = True
                    if state["reasoning_container_ref"].current.page:
                        await ui.utils.smart_update(state["reasoning_container_ref"].current)
            self.scroll_chat_to_bottom(duration=50)

        elif msg_type == "status":
            if state["status_text"]:
                state["status_text"].value = content
                try:
                    await ui.utils.smart_update(state["status_text"])
                except RuntimeError:
                    pass

            if self.br_status.current:
                self.br_status.current.value = content
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
                print("ERROR in action")
                pass

            state["previous_was_tool"] = True

        elif msg_type == "text":
            if state["status_text"] and state["status_text"].visible:
                state["status_text"].visible = False
                if state["status_text"].page:
                    await ui.utils.smart_update(state["status_text"])

            if state["previous_was_tool"] and not state["first_text"]:
                state["agent_markdown"].value += "\n\n"

            state["agent_markdown"].value += content
            if state["agent_markdown"].page:
                await ui.utils.smart_update(state["agent_markdown"])
                self.scroll_chat_to_bottom(duration=50)  # scrolls to end without interrupting

            state["previous_was_tool"] = False
            state["first_text"] = False

        elif msg_type == "finish":
            if not self.current_streaming_bubble:
                return

            final_text = state["agent_markdown"].value
            final_reasoning = state["reasoning_buffer"]

            bubble_to_remove = self.current_streaming_bubble
            self.current_streaming_bubble = None

            if self.br_chat_list.current:
                current_settings = settings.load_settings()
                current_char = current_settings.get("CHARACTER", "Reaper")
                avatar_path = character_manager.get_character_image(current_char)

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

                regen_btn = ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="Regenerate Response",
                            icon_color=ft.Colors.GREY_500,
                            on_click=self.regenerate_click,
                            icon_size=20,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                    data="regenerate_button"
                )
                self.br_chat_list.current.controls.append(regen_btn)

                await ui.utils.smart_update(self.br_chat_list.current)
                self.scroll_chat_to_bottom(delay_ms=100)

            if self.br_status.current:
                self.br_status.current.value = "Ready"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                await ui.utils.smart_update(self.br_status.current)

        elif msg_type == "error":
            # Clean chat UI and chat history
            self.br_input.current.value = await self.remove_last_ai_response(including_user=True)

            self.page.show_dialog(ft.SnackBar(ft.Text("Error: " + content)))

            if self.br_status.current:
                self.br_status.current.value = f"Error: {content}"
                self.br_status.current.color = styles.COLOR_ERROR

            await ui.utils.smart_update(self.page)

        elif msg_type == "cleanup":
            if self.br_btn_send.current:
                self.br_btn_send.current.disabled = False
                await ui.utils.smart_update(self.br_btn_send.current)
            if self.br_input.current:
                self.br_input.current.disabled = False
                await ui.utils.smart_update(self.br_input.current)

    async def remove_regen_button(self, perform_update=True):
        if self.br_chat_list.current and self.br_chat_list.current.controls:
            last_ctrl = self.br_chat_list.current.controls[-1]

            if getattr(last_ctrl, "data", "") == "regenerate_button":
                self.br_chat_list.current.controls.pop()
                if perform_update:
                    await ui.utils.smart_update(self.br_chat_list.current)
                return

            if isinstance(last_ctrl, ft.Row) and last_ctrl.controls and isinstance(last_ctrl.controls[0], ft.IconButton):
                 if last_ctrl.controls[0].icon == ft.Icons.REFRESH:
                    self.br_chat_list.current.controls.pop()
                    if perform_update:
                        await ui.utils.smart_update(self.br_chat_list.current)

    async def regenerate_click(self, e):
        await self.remove_regen_button(perform_update=False)

        await self.remove_last_ai_response(including_user=False)

        if self.br_chat_list.current:
            self.current_scroll_offset = 0
            self.max_scroll_extent = 0
            self.scroll_chat_to_bottom(forced=True, duration=0, delay_ms=50)

        self.br_input.current.disabled = True
        self.br_btn_send.current.disabled = True
        await ui.utils.smart_update(self.br_input.current)
        await ui.utils.smart_update(self.br_btn_send.current)

        if self.br_chat_history:
             last_msg = self.br_chat_history[-1]
             if last_msg["role"] == "user":
                 user_message = last_msg["content"]
                 self.br_chat_history.pop()
                 self.start_chat_thread(user_message)

    async def remove_last_ai_response(self, including_user=False):
        # History update
        while self.br_chat_history and self.br_chat_history[-1]["role"] not in ("user", "system"):
            self.br_chat_history.pop()

        user_text = ""
        if including_user:
            if self.br_chat_history and self.br_chat_history[-1]["role"] == "user":
                user_text = self.br_chat_history[-1]["content"]
                self.br_chat_history.pop()

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
            # Calculate how many to remove
            excess = len(controls) - self.max_chat_bubbles

            # Remove from the top (oldest)
            # We use a slice assignment or loop pop
            # Note: 0 is top
            for _ in range(excess):
                controls.pop(0)

            # Since we modify the list in place, we don't need to reassign,
            # but we need to reset scroll/layout state slightly to avoid jumps?
            # Actually, removing items from top might shift scroll position.
            # But usually we are auto-scrolling to bottom anyway.

    def _sync_data_sources_blocking(self):
        # This function runs in a separate thread
        try:
            vault.update(settings.STEAM_USER)
            vibes = VibeEngine.get_instance()
            vibes.ingest_library()
        except Exception as e:
            print(f"Sync error: {e}")

    async def send_message(self, e):
        user_message = self.br_input.current.value
        if not user_message:
            return

        self.br_input.current.value = ""
        self.br_input.current.disabled = True
        self.br_btn_send.current.disabled = True
        await ui.utils.smart_update(self.br_input.current)
        await ui.utils.smart_update(self.br_btn_send.current)

        user_portrait_url = self.get_user_portrait_url()

        await self.remove_regen_button(perform_update=False)

        if self.br_chat_list.current:
            # Prune before adding new message to keep list size stable
            await self.prune_chat_ui()

            self.br_chat_list.current.controls.append(self.parse_and_render_message(user_message, is_user=True, avatar_path=user_portrait_url))
            await ui.utils.smart_update(self.br_chat_list.current)
            self.scroll_chat_to_bottom(delay_ms=200)

        # Check for Sync Needed
        if vault.get_games_count() and vault.get_elapsed_since_update() > 1200:
            # Inject System Status Bubble
            sync_bubble = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.ProgressBar(
                            width=300,
                            color=styles.COLOR_PROGRESS_BAR,
                            bgcolor=styles.COLOR_SURFACE,
                            height=2,
                            border_radius=0
                        ),
                        ft.Text("[System] Syncing Neural Link with Steam Vault...", color=styles.COLOR_SYSTEM_LOG, size=12, font_family=styles.STYLE_MONOSPACE)
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10
                ),
                padding=10,
                alignment=ft.alignment.center
            )

            # Add to chat (temporarily)
            if self.br_chat_list.current:
                 self.br_chat_list.current.controls.append(sync_bubble)
                 await ui.utils.smart_update(self.br_chat_list.current)
                 self.scroll_chat_to_bottom(duration=100)

            # Run blocking update in thread, await it here
            await asyncio.to_thread(self._sync_data_sources_blocking)

            # Update UI to "Synced" then remove or just remove
            sync_bubble.content.controls[0] = ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.GREEN_400)
            sync_bubble.content.controls[1].value = "[System] Data Synced."
            sync_bubble.content.controls[1].color = ft.Colors.GREEN_400
            if self.br_chat_list.current:
                 await ui.utils.smart_update(self.br_chat_list.current)

            # Short pause to let user see "Synced"
            await asyncio.sleep(1.0)

            # Remove the bubble
            if self.br_chat_list.current:
                if sync_bubble in self.br_chat_list.current.controls:
                    self.br_chat_list.current.controls.remove(sync_bubble)
                    await ui.utils.smart_update(self.br_chat_list.current)


        self.start_chat_thread(user_message)
