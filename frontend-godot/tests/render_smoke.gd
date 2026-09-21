extends SceneTree
## Render real backend fixtures and verify legal/disabled controls and layout.

class CommandRecorder extends Node:
	var busy := false
	var connected := true
	var url := ""
	var commands: Array[Dictionary] = []
	func submit(command: String, payload: Dictionary = {}) -> void:
		commands.append({"command": command, "payload": payload})

func _initialize() -> void:
	call_deferred("run")

func collect_buttons(node: Node, result: Dictionary) -> void:
	for child in node.get_children():
		if child is BaseButton:
			result[child.text] = child
		collect_buttons(child, result)

func settle() -> void:
	for _i in range(4):
		await process_frame

func check_history_reader(scene, fixture: Dictionary, recorder: CommandRecorder, errors: Array[String]) -> void:
	var reader = scene.conversation
	var original_id: int = reader.get_instance_id()
	# Both tabs retain a deliberate scroll position when new public records arrive.
	for index in range(2):
		scene._receive(fixture.state)
		reader.current_tab = index
		reader.jump_to_latest()
		await settle()
		var log: RichTextLabel = reader.dialogue_log if index == 0 else reader.event_log
		var bar := log.get_v_scroll_bar()
		if bar.max_value - bar.page < 150:
			errors.append("History fixture does not exercise scrolling")
		bar.value = 70 + index * 20
		var old_position := bar.value
		scene._receive(fixture.updated_state)
		await settle()
		if scene.conversation.get_instance_id() != original_id:
			errors.append("A game update replaced the history reader")
		if absf(bar.value - old_position) > 1:
			errors.append("New records moved the reading position in tab %d: %s -> %s" % [index, old_position, bar.value])
		if reader.current_tab != index:
			errors.append("A game update changed the active history tab")
	# Search identifies an original record without losing literal handwriting.
	reader.current_tab = 0
	var first: Dictionary = fixture.state.dialogue[0]
	var query: String = first.record_id
	reader.search_input.text = query
	reader.search_input.text_changed.emit(query)
	await settle()
	var text: String = reader.dialogue_log.get_parsed_text()
	if first.statement not in text or fixture.state.dialogue[1].statement in text:
		errors.append("Record search did not isolate the matching handwriting")
	# Search and evidence review remain usable while other inputs are locked.
	recorder.busy = true
	scene._busy_changed(true)
	if not reader.search_input.editable or reader.player_filter.disabled or reader.latest_button.disabled:
		errors.append("Waiting for an AI prevented history review")
	recorder.busy = false
	reader.search_input.grab_focus()
	reader.search_input.caret_column = 3
	scene._receive(fixture.updated_state)
	await settle()
	if reader.search_input.text != query or first.statement not in reader.dialogue_log.get_parsed_text():
		errors.append("A game update cleared a history search")
	if not reader.search_input.has_focus() or reader.search_input.caret_column != 3:
		errors.append("A game update interrupted typing in the history search")
	reader.jump_to_latest()
	await settle()
	reader.player_filter.select(2) # P2: these fixtures only target P1, so this selects P2's notes.
	reader.player_filter.item_selected.emit(2)
	await settle()
	for message in fixture.state.dialogue:
		var present: bool = message.statement in reader.dialogue_log.get_parsed_text()
		if present != (message.actor == "P2"):
			errors.append("Player filter included or dropped unrelated handwriting")
	scene.menu = true
	scene._render()
	scene.menu = false
	scene._render()
	await settle()
	if reader.player_filter.get_selected_metadata() != "P2":
		errors.append("Returning from the menu lost the reading filter")
	reader.latest_button.pressed.emit()
	await settle()
	var bar: VScrollBar = reader.dialogue_log.get_v_scroll_bar()
	if not reader.search_input.text.is_empty() or reader.player_filter.selected != 0 or absf(bar.value - (bar.max_value - bar.page)) > 1:
		errors.append("Back to latest did not clear filters and reach the newest note")
	# An active reader at the end continues following newly appended messages.
	scene._receive(fixture.state)
	reader.jump_to_latest()
	await settle()
	scene._receive(fixture.updated_state)
	await settle()
	if absf(bar.value - (bar.max_value - bar.page)) > 1:
		errors.append("A reader already at the end stopped following new messages")
	# A new match clears the previous match's search, tab and remembered position.
	reader.search_input.text = "旧卷"
	reader.search_input.text_changed.emit("旧卷")
	reader.current_tab = 1
	var reveal: Dictionary = fixture.state.duplicate(true)
	reveal.phase = "ROLE_REVEAL"
	scene._receive(reveal)
	await settle()
	if not reader.search_input.text.is_empty() or reader.current_tab != 0:
		errors.append("Starting a new match retained the old reading controls")

func run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		push_error("Pass the generated JSON fixture path after --")
		quit(1)
		return
	var fixtures = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	# Let startup finish before isolating the renderer from its transport.
	for _i in range(100):
		if scene.backend.connected:
			break
		await create_timer(0.05).timeout
	scene.backend.stop()
	scene.backend.queue_free()
	var recorder := CommandRecorder.new()
	scene.add_child(recorder)
	scene.backend = recorder
	root.size = Vector2i(1280, 720)
	var errors: Array[String] = []
	for fixture in fixtures:
		scene.menu = false
		scene._receive(fixture.state)
		if not fixture.form.is_empty():
			scene._open_form(fixture.form)
		await process_frame
		await process_frame
		var buttons := {}
		collect_buttons(scene, buttons)
		for label in fixture.expected:
			if not buttons.has(label):
				errors.append("%s: missing %s" % [fixture.name, label])
		for label in fixture.disabled:
			if not buttons.has(label) or not buttons[label].disabled:
				errors.append("%s: should disable %s" % [fixture.name, label])
		if fixture.name == "good_mission" and buttons.has("失败"):
			errors.append("Good player was offered FAIL")
		# Errors may use the outer scroll container; regular play must fit one screen.
		if fixture.name != "ai_error" and scene.page.get_combined_minimum_size().y > 684:
			errors.append("%s: exceeds content height: %s" % [fixture.name, scene.page.get_combined_minimum_size()])
		if scene.page.get_combined_minimum_size().x > 1244:
			errors.append("%s: exceeds content width" % fixture.name)
		if fixture.state.phase != "ROLE_REVEAL":
			var center: float = scene.conversation.get_global_rect().get_center().x
			if absf(center - scene.page.get_global_rect().get_center().x) > 2:
				errors.append("%s: handwriting reader is not centered" % fixture.name)
			if scene.conversation.size.x < scene.page.size.x / 2:
				errors.append("%s: handwriting is not the main reading area" % fixture.name)
			var transcript: String = scene.conversation.dialogue_log.get_parsed_text()
			for message in fixture.state.dialogue:
				if str(message.statement) not in transcript or scene._name(message.actor) not in transcript:
					errors.append("%s: dialogue lost a speaker or literal statement" % fixture.name)
			if scene.conversation.get_tab_title(0) != "手稿" or scene.conversation.get_tab_title(1) != "编年史":
				errors.append("Conversation tabs are not in Chinese")
			# Reviewing the event log must survive incoming state refreshes.
			scene.conversation.current_tab = 1
			scene._receive(fixture.state)
			if scene.conversation.current_tab != 1:
				errors.append("Conversation tab choice was lost")
			scene.conversation.current_tab = 0
			if not fixture.form.is_empty():
				scene._open_form(fixture.form)
			buttons.clear()
			collect_buttons(scene, buttons)
		if fixture.name == "assassination":
			scene._select_seat(str(fixture.state.selection_targets[0]))
			buttons.clear()
			collect_buttons(scene, buttons)
			if not buttons.has("确认刺杀") or not buttons.has("取消"):
				errors.append("Assassination lacks confirmation")
		if fixture.name == "exile_nomination":
			var target: String = fixture.state.selection_targets[0]
			scene._select_seat(target)
			buttons.clear()
			collect_buttons(scene, buttons)
			var label: String = "确认提名 · " + scene._name(target)
			if not buttons.has(label) or buttons[label].disabled:
				errors.append("Exile nomination must enable after selecting a living target")
			else:
				buttons[label].pressed.emit()
				if recorder.commands.back() != {"command": "nominate_exile", "payload": {"target": target}}:
					errors.append("Nomination control sent the wrong target")
		if fixture.name == "exile_vote":
			for pair in [["赞成", "APPROVE"], ["反对", "REJECT"], ["弃票", "ABSTAIN"]]:
				buttons[pair[0]].pressed.emit()
				if recorder.commands.back() != {"command": "exile_vote", "payload": {"choice": pair[1]}}:
					errors.append("Exile ballot control lost its three-way choice")
		if fixture.name == "social":
			scene.commit_choice.button_pressed = true
			if "共消耗 2 点决心" not in scene.confirmation.text:
				errors.append("Committed Social preview is incorrect")
			scene._submit_social()
			var action: Dictionary = recorder.commands.back().payload.action
			if action.kind != "COMMITTED_SOCIAL" or action.social.card != "ACCUSE" or action.social.target != "P1":
				errors.append("Chinese social controls changed the engine command")
			if not action.social.has("public_writing") or not action.social.has("citations"):
				errors.append("Human handwriting must use the public writing schema")
		if fixture.name == "chronicle_citation":
			var message: Dictionary = fixture.state.dialogue.back()
			var rid: String = message.citations[0]
			if rid not in scene.conversation.dialogue_log.get_parsed_text():
				errors.append("Accusation lost its evidence link")
			scene.conversation.dialogue_log.meta_clicked.emit(rid)
			await process_frame
			var original: String = message.citation_records[0].public_writing
			if not is_instance_valid(scene.conversation.evidence_popup) or original not in scene.conversation.evidence_popup.dialog_text:
				errors.append("Citation did not open the original handwriting")
			scene.conversation.evidence_popup.hide()
		if fixture.name == "reply_link":
			var message: Dictionary = fixture.state.dialogue.back()
			var rid: String = message.reply_to
			if "回应 [" + rid + "]" not in scene.conversation.dialogue_log.get_parsed_text():
				errors.append("A response lacks its original question link")
			scene.conversation.dialogue_log.meta_clicked.emit(rid)
			await process_frame
			if not is_instance_valid(scene.conversation.evidence_popup) or rid not in scene.conversation.evidence_popup.title:
				errors.append("A response link did not open the original record")
			scene.conversation.evidence_popup.hide()
		if fixture.name == "history_review":
			await check_history_reader(scene, fixture, recorder, errors)
		if fixture.name == "good_mission":
			buttons["成功"].pressed.emit()
			if recorder.commands.back() != {"command": "mission", "payload": {"card": "SUCCESS"}}:
				errors.append("Chinese mission control changed the engine command")
	if errors.is_empty():
		print("PASS: %d phase/form render cases at 1280 × 720" % fixtures.size())
	else:
		for error in errors:
			push_error(error)
	scene.queue_free()
	await process_frame
	quit(0 if errors.is_empty() else 1)
