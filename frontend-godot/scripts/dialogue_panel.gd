extends VBoxContainer
## A persistent reader: game updates never interrupt a review of older handwriting.
## All public text is literal, including search results and evidence popups.

signal tab_changed(index: int)

const TextZh = preload("res://scripts/text_zh.gd")
var tabs: TabContainer
var dialogue_log: RichTextLabel
var event_log: RichTextLabel
var evidence_popup: AcceptDialog
var search_input: LineEdit
var player_filter: OptionButton
var latest_button: Button
var current_tab: int:
	get:
		return tabs.current_tab if is_instance_valid(tabs) else 0
	set(value):
		if is_instance_valid(tabs):
			tabs.current_tab = value
var _state: Dictionary = {}
var _name_for: Callable
var _last_content: Array = []
var _player_ids: Array = []
var _pending_positions: Array = []
var _scroll_version := 0
var _restore_search_focus := false

func render(state: Dictionary, name_for: Callable) -> void:
	_state = state
	_name_for = name_for
	if not is_instance_valid(tabs):
		_build_reader()
	var ids: Array = state.players.map(func(player): return player.id)
	if ids != _player_ids:
		_player_ids = ids
		player_filter.clear()
		player_filter.add_item("全部角色")
		player_filter.set_item_metadata(0, "")
		for pid in ids:
			player_filter.add_item(name_for.call(pid))
			player_filter.set_item_metadata(player_filter.item_count - 1, pid)
		player_filter.select(0)
	_refresh_logs()
	if _restore_search_focus:
		search_input.grab_focus()
		_restore_search_focus = false

func _build_reader() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 6)
	var toolbar := HBoxContainer.new()
	toolbar.add_theme_constant_override("separation", 6)
	add_child(toolbar)
	player_filter = OptionButton.new()
	player_filter.custom_minimum_size.x = 110
	player_filter.tooltip_text = "筛选该角色的手稿，以及涉及他的公开记录"
	toolbar.add_child(player_filter)
	search_input = LineEdit.new()
	search_input.placeholder_text = "查找手稿或记录编号…"
	search_input.max_length = 120
	search_input.clear_button_enabled = true
	search_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	toolbar.add_child(search_input)
	latest_button = Button.new()
	latest_button.text = "回到最新"
	latest_button.tooltip_text = "清除筛选，回到当前页签的最新记录"
	toolbar.add_child(latest_button)
	tabs = TabContainer.new()
	tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(tabs)
	dialogue_log = _log("手稿")
	event_log = _log("编年史")
	dialogue_log.meta_clicked.connect(func(meta): _open_record(str(meta), _state))
	event_log.meta_clicked.connect(func(meta): _open_record(str(meta), _state))
	tabs.tab_changed.connect(func(index: int): tab_changed.emit(index))
	player_filter.item_selected.connect(func(_index: int): _refresh_logs(true))
	search_input.text_changed.connect(func(_text: String): _refresh_logs(true))
	latest_button.pressed.connect(jump_to_latest)

func get_tab_title(index: int) -> String:
	return tabs.get_tab_title(index)

func reset_reading() -> void:
	_last_content.clear()
	_pending_positions.clear()
	_scroll_version += 1
	_restore_search_focus = false
	if is_instance_valid(tabs):
		search_input.release_focus()
		search_input.text = ""
		player_filter.select(0)
		tabs.current_tab = 0
		dialogue_log.clear()
		event_log.clear()

func preserve_reading_position() -> void:
	if is_instance_valid(tabs):
		_pending_positions = _reading_positions()
		_restore_search_focus = search_input.has_focus()

func _reading_positions() -> Array:
	if not _pending_positions.is_empty():
		return _pending_positions.duplicate(true)
	var positions: Array = []
	for log in [dialogue_log, event_log]:
		var bar: VScrollBar = log.get_v_scroll_bar()
		positions.append({"latest": bar.value >= bar.max_value - bar.page - 4, "value": bar.value})
	return positions

func _queue_scroll(positions: Array) -> void:
	_pending_positions = positions
	_scroll_version += 1
	_restore_scroll.call_deferred(_scroll_version)

func _restore_scroll(version: int) -> void:
	# Wrapped text settles after its parent containers have resized.
	await get_tree().process_frame
	await get_tree().process_frame
	if version != _scroll_version:
		return
	var logs := [dialogue_log, event_log]
	for index in range(logs.size()):
		var bar: VScrollBar = logs[index].get_v_scroll_bar()
		var saved: Dictionary = _pending_positions[index]
		bar.value = maxf(0, bar.max_value - bar.page) if saved.latest else float(saved.value)
	_pending_positions.clear()

func jump_to_latest() -> void:
	search_input.text = ""
	player_filter.select(0)
	_refresh_logs()
	_queue_scroll([{"latest": true, "value": 0}, {"latest": true, "value": 0}])

func _matches(entry: Dictionary) -> bool:
	var pid := str(player_filter.get_selected_metadata())
	if not pid.is_empty() and pid != entry.get("actor", "") and pid != entry.get("target", "") and pid not in entry.get("team", []) and pid not in entry.get("votes", {}):
		return false
	var query := search_input.text.strip_edges().to_lower()
	if query.is_empty():
		return true
	var actor := str(entry.get("actor", ""))
	var target := str(entry.get("target", ""))
	var text := JSON.stringify(entry) + " " + str(_name_for.call(actor)) + " " + str(_name_for.call(target))
	return query in text.to_lower()

func _refresh_logs(reset_position: bool = false) -> void:
	var messages: Array = _state.get("dialogue", [])
	var records: Array = _state.get("public_events", [])
	var content := [messages, records, player_filter.get_selected_metadata(), search_input.text]
	var positions := _reading_positions()
	if reset_position:
		positions = [{"latest": false, "value": 0}, {"latest": false, "value": 0}]
	if content == _last_content:
		if not _pending_positions.is_empty():
			_queue_scroll(positions)
		return
	_last_content = content.duplicate(true)
	dialogue_log.clear()
	event_log.clear()
	var shown := 0
	for message in messages:
		if not _matches(message):
			continue
		shown += 1
		dialogue_log.push_color(Color("86d4bd"))
		dialogue_log.add_text("%s\n" % _name_for.call(message.actor))
		dialogue_log.pop()
		dialogue_log.push_font_size(13)
		dialogue_log.push_color(Color("a1b1c4"))
		var stage := "任务后议会" if message.get("discussion_stage", "proposal") == "council" else "提案 %d" % message.attempt
		dialogue_log.add_text("第 %d 次任务 · %s · " % [message.round, stage])
		_link(dialogue_log, str(message.record_id), str(message.record_id))
		dialogue_log.add_text("\n%s%s · %s → %s\n" % ["加强承诺 · " if message.committed else "", TextZh.label(message.kind), TextZh.label(message.card), _name_for.call(message.target)])
		dialogue_log.pop()
		dialogue_log.pop()
		dialogue_log.add_text(str(message.statement) + "\n")
		if message.get("reply_to") != null:
			dialogue_log.add_text("回应 ")
			_link(dialogue_log, str(message.reply_to), "[" + str(message.reply_to) + "]")
			dialogue_log.add_text("  ")
		for rid in message.get("citations", []):
			_link(dialogue_log, str(rid), "[%s]  " % rid)
		dialogue_log.add_text("\n")
	if shown == 0:
		dialogue_log.add_text("没有匹配的手稿。可换个关键词或回到最新。" if not messages.is_empty() else "旧神监听言语。圆桌只能手写。\n\n手稿永久归档，可以成为证据。\n保持沉默，也是一种选择。")
	shown = 0
	for event in records:
		if not _matches(event):
			continue
		shown += 1
		var cost := "  [决心 −%d → %d]" % [event.resolve_cost, event.resolve_after] if event.has("resolve_cost") else ""
		_link(event_log, str(event.get("record_id", event.seq)), "[%s]" % event.get("record_id", event.seq))
		event_log.add_text("  %s%s\n\n" % [event.text, cost])
	if shown == 0:
		event_log.add_text("没有匹配的公开记录。")
	_queue_scroll(positions)

func _link(log: RichTextLabel, rid: String, label: String) -> void:
	log.push_meta(rid)
	log.add_text(label)
	log.pop()

func _open_record(rid: String, state: Dictionary) -> void:
	for event in state.public_events:
		if str(event.get("record_id", event.seq)) != rid:
			continue
		if is_instance_valid(evidence_popup):
			evidence_popup.queue_free()
		evidence_popup = AcceptDialog.new()
		evidence_popup.title = "%s · 原始记录" % rid
		var writing := str(event.get("public_writing", ""))
		evidence_popup.dialog_text = "%s\n\n%s" % [event.text, "「%s」" % writing if not writing.is_empty() else "此条为公开行动记录，无附加手稿。"]
		evidence_popup.get_label().autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		evidence_popup.get_label().custom_minimum_size = Vector2(480, 160)
		evidence_popup.ok_button_text = "收起手稿"
		add_child(evidence_popup)
		evidence_popup.popup_centered(Vector2i(540, 280))
		return

func _log(title: String) -> RichTextLabel:
	var log := RichTextLabel.new()
	log.name = title
	log.bbcode_enabled = false
	log.scroll_following = false
	log.selection_enabled = true
	log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	log.custom_minimum_size.y = 160
	log.add_theme_font_size_override("normal_font_size", 16 if title == "手稿" else 14)
	tabs.add_child(log)
	return log
