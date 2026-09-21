extends Control
## Presentation only. All commands return a complete authoritative state.

const Backend = preload("res://scripts/backend_client.gd")
const PlayerSeat = preload("res://scripts/player_seat.gd")
const TextZh = preload("res://scripts/text_zh.gd")
const DialoguePanel = preload("res://scripts/dialogue_panel.gd")
var backend: Node
var state: Dictionary = {"phase": "START", "players": [], "public_events": []}
var page: VBoxContainer
var actions: VBoxContainer
var action_scroll: ScrollContainer
var seats: GridContainer
var right_seats: GridContainer
var connection := "正在启动本地游戏服务…"
var transport_error := ""
var menu := true
var form := ""
var selection: Array[String] = []
var count_choice := 5
var seed_text := ""
var scheduled_revision := -1
var status_label: Label
var confirmation: Button
var evidence_choice: OptionButton
var evidence_preview: Label
var target_choice: OptionButton
var card_choice: OptionButton
var commit_choice: CheckBox
var writing_input: LineEdit
var citation_choice: OptionButton
var waiting_since := 0
var waiting_second := -1
var waiting_text := ""
var conversation_tab := 0
var conversation: DialoguePanel

func _ready() -> void:
	# Godot window sizes are physical pixels on macOS; keep text readable on Retina.
	var display_scale := DisplayServer.screen_get_scale() if OS.get_name() == "macOS" and DisplayServer.get_name() != "headless" else 1.0
	get_window().min_size = Vector2i(Vector2(1000, 620) * display_scale)
	if display_scale > 1.0:
		var usable := DisplayServer.screen_get_usable_rect()
		var desired := Vector2i(Vector2(1280, 720) * display_scale)
		get_window().size = Vector2i(mini(desired.x, usable.size.x - 80), mini(desired.y, usable.size.y - 100))
		get_window().position = usable.position + (usable.size - get_window().size) / 2
	_build_theme()
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 18)
	add_child(margin)
	var viewport_scroll := ScrollContainer.new()
	viewport_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	margin.add_child(viewport_scroll)
	page = VBoxContainer.new()
	page.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_theme_constant_override("separation", 8)
	viewport_scroll.add_child(page)
	backend = Backend.new()
	backend.state_received.connect(_receive)
	backend.connection_changed.connect(func(value: String): connection = value)
	backend.failed.connect(_failed)
	backend.busy_changed.connect(_busy_changed)
	add_child(backend)
	_render()

func _build_theme() -> void:
	var palette := Theme.new()
	palette.default_font_size = 16
	palette.set_color("font_color", "Label", Color("e6edf5"))
	palette.set_color("default_color", "RichTextLabel", Color("d1dce9"))
	for control in ["Button", "OptionButton", "CheckBox"]:
		palette.set_color("font_color", control, Color("edf4fa"))
		palette.set_color("font_disabled_color", control, Color("8c98aa"))
		for style_name in ["normal", "hover", "pressed", "disabled", "focus"]:
			var box := StyleBoxFlat.new()
			box.bg_color = Color("293d52") if style_name in ["hover", "pressed"] else Color("1c2a3c")
			box.border_color = Color("86d4bd") if style_name == "focus" else Color("425570")
			box.set_border_width_all(1)
			box.set_corner_radius_all(5)
			box.content_margin_left = 14
			box.content_margin_right = 14
			box.content_margin_top = 9
			box.content_margin_bottom = 9
			palette.set_stylebox(style_name, control, box)
	theme = palette

func _clear(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()

func _label(parent: Node, value: String, font_size: int = 16, wrap: bool = false) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size", font_size)
	if wrap:
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(label)
	return label

func _button(parent: Node, value: String, callback: Callable, enabled: bool = true, tip: String = "") -> Button:
	var button := Button.new()
	button.text = value
	button.disabled = not enabled or (backend.busy and value != "退出")
	button.tooltip_text = tip
	button.pressed.connect(callback)
	parent.add_child(button)
	return button

func _row(parent: Node) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	parent.add_child(row)
	return row

func _flow(parent: Node) -> HFlowContainer:
	var row := HFlowContainer.new()
	row.add_theme_constant_override("h_separation", 10)
	row.add_theme_constant_override("v_separation", 8)
	parent.add_child(row)
	return row

func _box(parent: Node) -> VBoxContainer:
	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color("111c2a")
	style.set_corner_radius_all(7)
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 12
	style.content_margin_bottom = 12
	panel.add_theme_stylebox_override("panel", style)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	parent.add_child(panel)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	panel.add_child(body)
	return body

func _receive(value: Dictionary) -> void:
	state = value
	transport_error = ""
	form = ""
	selection.clear()
	if state.phase == "ROLE_REVEAL":
		menu = false
		scheduled_revision = -1
		conversation_tab = 0
		if is_instance_valid(conversation):
			conversation.reset_reading()
	_render()
	if not menu and state.get("can_advance", false):
		_schedule_advance()

func _schedule_advance() -> void:
	var revision := int(state.revision)
	if scheduled_revision == revision:
		return
	scheduled_revision = revision
	await get_tree().create_timer(0.45).timeout
	if not menu and transport_error.is_empty() and int(state.revision) == revision and state.get("can_advance", false) and not backend.busy:
		backend.submit("advance")

func _failed(message: String) -> void:
	transport_error = message
	_render()

func _busy_changed(value: bool) -> void:
	if value and is_instance_valid(page):
		waiting_since = Time.get_ticks_msec()
		waiting_second = -1
		waiting_text = state.get("prompt", "") if state.get("can_advance", false) else "正在提交…"
		if state.get("retry_ai", false):
			waiting_text = "正在重试 AI 行动…"
		_disable_inputs(page)
		if is_instance_valid(status_label):
			status_label.text = waiting_text

func _process(_delta: float) -> void:
	if is_instance_valid(backend) and backend.busy and is_instance_valid(status_label):
		var elapsed := int((Time.get_ticks_msec() - waiting_since) / 1000)
		if elapsed != waiting_second and elapsed >= 2:
			waiting_second = elapsed
			status_label.text = "%s  ·  %d 秒" % [waiting_text, elapsed]

func _disable_inputs(node: Node) -> void:
	for child in node.get_children():
		# History controls stay available while a model call or submission is pending.
		if child == conversation:
			continue
		if child is BaseButton and child.text != "退出":
			child.disabled = true
		if child is LineEdit:
			child.editable = false
		_disable_inputs(child)

func _send(command: String, payload: Dictionary = {}) -> void:
	backend.submit(command, payload)

func _act(kind: String) -> void:
	_send("action", {"action": {"kind": kind}})

func _render() -> void:
	# Keep the reader alive across game updates, including its filters and scroll.
	if is_instance_valid(conversation):
		conversation.preserve_reading_position()
		if conversation.get_parent() != self:
			conversation.reparent(self)
		conversation.hide()
	_clear(page)
	status_label = null
	var header := _row(page)
	_label(header, "阿瓦隆", 25).size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if not menu and state.phase != "ROLE_REVEAL":
		_button(header, "我的身份", _show_role)
		_button(header, "新开一局", func(): menu = true; _render())
	_button(header, "退出", func(): get_tree().quit())
	if not transport_error.is_empty():
		_label(page, transport_error, 16, true).modulate = Color("ffbb9d")
		var recovery := _row(page)
		_button(recovery, "重试连接", func(): backend.retry_request(), not backend.url.is_empty())
		_button(recovery, "重启服务并新开一局", func(): menu = true; backend.boot(); _render())
	if not state.get("error", "").is_empty():
		_label(page, state.error, 16, true).modulate = Color("ffbb9d")
	if menu or state.phase == "START":
		_render_start()
	elif state.phase == "ROLE_REVEAL":
		_render_reveal()
	else:
		_render_table()
	var footer := _label(page, connection + "  ·  1 位真人 + AI 玩家  ·  任务牌匿名结算", 13)
	footer.modulate = Color("9aaabd")

func _center_body() -> VBoxContainer:
	var center := CenterContainer.new()
	center.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(center)
	var body := VBoxContainer.new()
	body.custom_minimum_size.x = 620
	body.add_theme_constant_override("separation", 20)
	center.add_child(body)
	return body

func _render_start() -> void:
	var body := _center_body()
	_label(body, "入座，开始推理。", 34)
	_label(body, "选择队伍，分配决心，从落笔与记录中寻找线索。\n完成三次任务，并保护梅林。", 18, true)
	var options := _row(body)
	_label(options, "人数")
	var count := OptionButton.new()
	count.add_item("5 人局 · 你 + 4 位 AI", 5)
	count.add_item("6 人局 · 你 + 5 位 AI", 6)
	count.select(0 if count_choice == 5 else 1)
	count.item_selected.connect(func(index: int): count_choice = count.get_item_id(index))
	options.add_child(count)
	var seed := LineEdit.new()
	seed.placeholder_text = "随机种子（选填）"
	seed.text = seed_text
	seed.custom_minimum_size.x = 200
	seed.max_length = 12
	seed.text_changed.connect(func(value: String): seed_text = value)
	options.add_child(seed)
	status_label = _label(body, "准备就绪。" if backend.connected else connection, 16, true)
	_button(body, "开始游戏", _start_game, backend.connected)
	_label(body, "AI 会自动行动，并在手稿栏中落笔。\n你可以通过点击完成整场对局。", 14, true).modulate = Color("a1b1c4")

func _start_game() -> void:
	var clean := seed_text.strip_edges()
	if not clean.is_empty() and (not clean.is_valid_int() or abs(clean.to_int()) > 2147483647):
		status_label.text = "请输入 -2147483647 至 2147483647 之间的整数，或留空随机开局。"
		return
	_send("start", {"players": count_choice, "seed": null if clean.is_empty() else clean.to_int()})

func _private_text() -> String:
	var info: Dictionary = state.get("private", {})
	var result := "你的身份\n\n" + TextZh.label(str(info.get("role", "")))
	var known: Array = info.get("known_evil", [])
	if not known.is_empty():
		var names: Array[String] = []
		for pid in known:
			names.append(_name(pid))
		result += "\n\n你知道以下玩家属于邪恶阵营：\n" + " / ".join(names)
	else:
		result += "\n\n你没有其他玩家的身份信息。"
	return result + "\n\n这些信息仅供你本人查看。"

func _render_reveal() -> void:
	var body := _center_body()
	_label(body, _private_text(), 22, true)
	_button(body, "继续", func(): _send("continue"))

func _show_role() -> void:
	var dialog := AcceptDialog.new()
	dialog.title = "我的身份"
	dialog.ok_button_text = "知道了"
	dialog.dialog_text = _private_text()
	add_child(dialog)
	dialog.confirmed.connect(dialog.queue_free)
	dialog.canceled.connect(dialog.queue_free)
	dialog.popup_centered(Vector2i(540, 280))

func _name(pid: String) -> String:
	for player in state.players:
		if player.id == pid:
			return "%s（%s）" % [player.name, pid]
	return pid

func _team_text(team: Array) -> String:
	var names: Array[String] = []
	for pid in team:
		names.append(_name(pid))
	return " / ".join(names)

func _score(value: int) -> String:
	return "●".repeat(value) + "○".repeat(maxi(0, 3 - value))

func _render_table() -> void:
	_label(page, "任务 %d / 5 · %s    善良 %s    邪恶 %s    提案 %d / 5    队长：%s" % [state.mission_round, "安全轮" if state.get("safe_round", false) else "危险轮", _score(int(state.successes)), _score(int(state.failures)), state.proposal_attempt, _name(state.leader)], 18)
	var phase_line := _row(page)
	_label(phase_line, "阶段  " + TextZh.label(str(state.phase)), 18).modulate = Color("86d4bd")
	status_label = _label(phase_line, state.get("prompt", ""), 16, true)
	_label(phase_line, "落笔：" + " → ".join(state.speaking_order), 12).modulate = Color("a1b1c4")
	var middle := _row(page)
	middle.size_flags_vertical = Control.SIZE_EXPAND_FILL
	seats = _seat_column(middle)
	var conversation_shell := _box(middle)
	conversation_shell.get_parent().custom_minimum_size.x = 400
	var reader_heading := _row(conversation_shell)
	_label(reader_heading, "圆桌手稿", 17).size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_label(reader_heading, "队伍  " + " / ".join(state.proposed_team) if not state.proposed_team.is_empty() else "尚未提议队伍", 13).modulate = Color("a1b1c4")
	if not is_instance_valid(conversation):
		conversation = DialoguePanel.new()
		conversation_shell.add_child(conversation)
		conversation.tab_changed.connect(func(index: int): conversation_tab = index)
	else:
		conversation.reparent(conversation_shell)
	conversation.show()
	conversation.render(state, _name)
	conversation.current_tab = conversation_tab
	right_seats = _seat_column(middle)
	_render_seats()
	var action_shell := _box(page)
	action_shell.get_parent().size_flags_vertical = Control.SIZE_FILL
	var amount := 0
	for player in state.players:
		if player.is_human:
			amount = int(player.resolve)
	_label(action_shell, "你的决心  %s%s   %d / 3" % ["● ".repeat(amount), "○ ".repeat(3 - amount), amount], 17)
	action_scroll = ScrollContainer.new()
	action_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	action_shell.add_child(action_scroll)
	actions = VBoxContainer.new()
	actions.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	actions.add_theme_constant_override("separation", 8)
	action_scroll.add_child(actions)
	_render_actions()
	if not state.get("notice", "").is_empty():
		_label(actions, state.notice, 14, true).modulate = Color("dcb875")

func _seat_column(parent: Node) -> GridContainer:
	var column := GridContainer.new()
	column.columns = 1
	column.custom_minimum_size.x = 190
	column.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("v_separation", 8)
	parent.add_child(column)
	return column

func _render_seats() -> void:
	_clear(seats)
	_clear(right_seats)
	var selectable: bool = state.human_turn and state.phase in ["TEAM_DRAFT", "ASSASSINATION", "EXILE_NOMINATION"]
	for index in range(6):
		var column := seats if index < 3 else right_seats
		if index >= state.players.size():
			var space := Control.new()
			space.custom_minimum_size.y = 92
			space.size_flags_vertical = Control.SIZE_EXPAND_FILL
			column.add_child(space)
			continue
		var player: Dictionary = state.players[index]
		var seat := PlayerSeat.new()
		seat.render(player, selectable and player.id in state.selection_targets and not backend.busy, player.id in selection, true)
		seat.pressed.connect(_select_seat.bind(str(player.id)))
		column.add_child(seat)

func _select_seat(pid: String) -> void:
	if pid in selection:
		selection.erase(pid)
	elif state.phase in ["ASSASSINATION", "EXILE_NOMINATION"]:
		selection.assign([pid])
	elif selection.size() < int(state.team_size):
		selection.append(pid)
	_render_seats()
	_render_actions()

func _available(kind: String) -> bool:
	return kind in state.legal_actions

func _reason(kind: String) -> String:
	for option in state.action_options:
		if option.kind == kind:
			return option.reason
	return "当前无法执行此操作"

func _action_button(parent: Node, label: String, kind: String, callback: Callable) -> void:
	_button(parent, label, callback, _available(kind), _reason(kind))

func _open_form(value: String) -> void:
	form = value
	_render_actions()

func _render_actions() -> void:
	_clear(actions)
	var result_phase: bool = state.phase in ["VOTE_RESULT", "ROUND_RESULT", "EXILE_RESULT", "GAME_OVER"]
	action_scroll.custom_minimum_size.y = 158 if not form.is_empty() or result_phase or state.phase in ["CHALLENGE_RESPONSE", "REACTION"] else 120
	if not state.human_turn and not result_phase and not state.get("retry_ai", false):
		action_scroll.custom_minimum_size.y = 48
	if state.get("retry_ai", false):
		_label(actions, "AI 暂时无法行动，当前对局已保留。", 16, true)
		_button(actions, "重试 AI 行动", func(): _send("retry"))
		return
	if not form.is_empty():
		_render_form()
		return
	if state.phase in ["VOTE_RESULT", "ROUND_RESULT", "EXILE_RESULT", "GAME_OVER"]:
		_render_result()
		return
	if not state.human_turn:
		_label(actions, state.prompt, 19, true)
		if state.phase in ["VOTE", "EXILE_VOTE"]:
			_label(actions, "你的选票已提交，收齐后一起公开。" if state.get("vote_submitted", false) else "选票收齐后一起公开。", 15)
		elif state.phase == "MISSION":
			_label(actions, "仅公布任务牌的汇总结果，不公开出牌者。", 15)
		return
	match state.phase:
		"TEAM_DRAFT":
			_label(actions, "选择 %d 名队员  ·  已选 %d / %d 人" % [state.team_size, selection.size(), state.team_size], 20)
			_label(actions, "点击玩家座位，选择本次任务的队员。")
			_button(actions, "确认队伍", func(): _send("team", {"team": selection}), selection.size() == int(state.team_size))
		"DISCUSSION", "COUNCIL_DISCUSSION":
			_label(actions, "任务后议会：回顾任务结果，讨论是否有人应该出局。" if state.phase == "COUNCIL_DISCUSSION" else "轮到你落笔了。选择一次行动，或保持沉默以节省决心。", 18)
			var row := _flow(actions)
			_action_button(row, "沉默  [0]", "PASS", func(): _act("PASS"))
			_action_button(row, "落笔  [1]", "SOCIAL", func(): _open_form("SOCIAL"))
			_action_button(row, "质询  [1]", "CHALLENGE", func(): _open_form("CHALLENGE"))
			_action_button(row, "引证  [1]", "CITE", func(): _open_form("CITE"))
			_action_button(row, "保留反应  [1]", "HOLD", func(): _act("HOLD"))
			_label(actions, "落笔可额外花 1 点加强承诺；保留反应会预付一次后续反应。方括号内为决心消耗。", 14, true)
		"CHALLENGE_RESPONSE":
			_label(actions, "%s 向你发起质询" % _name(state.challenge.actor), 20)
			_label(actions, "证据：" + _event_description(int(state.challenge.evidence)), 15, true)
			var row := _flow(actions)
			_action_button(row, "回应  [1]", "RESPOND", func(): _open_form("RESPOND"))
			_action_button(row, "拒绝回应  [0]", "DECLINE", func(): _act("DECLINE"))
		"REACTION":
			_label(actions, "可以反应  ·  " + _event_description(int(state.reaction_trigger)), 18, true)
			var row := _flow(actions)
			_action_button(row, "作出反应  [0 · 已预付]", "REACT", func(): _open_form("REACT"))
			_action_button(row, "继续等待  [0]", "SKIP", func(): _act("SKIP"))
		"TEAM_CONFIRM":
			_label(actions, "确认或调整队伍", 20)
			_label(actions, "可花 1 点决心替换一名队员，随后立即进入投票。", 15)
			var row := _flow(actions)
			_action_button(row, "确认队伍  [0]", "LOCK", func(): _act("LOCK"))
			_action_button(row, "调整队伍  [1]", "REVISE", func(): _open_form("REVISE"))
		"VOTE":
			_label(actions, "队伍投票  ·  " + _team_text(state.proposed_team), 18, true)
			var row := _flow(actions)
			_action_button(row, "赞成  [0]", "VOTE", func(): _send("vote", {"approve": true, "strong": false}))
			_action_button(row, "反对  [0]", "VOTE", func(): _send("vote", {"approve": false, "strong": false}))
			_action_button(row, "强烈赞成  [1]", "STRONG_VOTE", func(): _send("vote", {"approve": true, "strong": true}))
			_action_button(row, "强烈反对  [1]", "STRONG_VOTE", func(): _send("vote", {"approve": false, "strong": true}))
			_label(actions, "每人一票，强烈投票仍只计一票。收齐前所有选票均保密。", 14, true)
		"MISSION":
			_label(actions, "你将参与本次任务", 20)
			_label(actions, "安全轮：失败仍计分，但队员不会因任务死亡。秘密提交任务牌。" if state.get("safe_round", false) else "秘密提交一张任务牌，不消耗决心，出牌者不会被公开。", 15, true)
			var row := _flow(actions)
			for card in state.legal_actions:
				_button(row, TextZh.label(card), func(): _send("mission", {"card": card}))
		"EXILE_NOMINATION":
			_label(actions, "提名出局者：点击一名仍存活角色的座位。", 20)
			_label(actions, "由本次任务队长提名；全员投票，须 %d 票赞成才出局。" % state.required_approvals, 15, true)
			_button(actions, "确认提名" + (" · " + _name(selection[0]) if not selection.is_empty() else ""), func(): _send("nominate_exile", {"target": selection[0]}), selection.size() == 1)
		"EXILE_VOTE":
			_label(actions, "是否让 %s 出局？" % _name(state.exile_nominee), 20)
			var row := _flow(actions)
			for choice in ["APPROVE", "REJECT", "ABSTAIN"]:
				_button(row, TextZh.label(choice), func(): _send("exile_vote", {"choice": choice}))
			_label(actions, "须 %d 票赞成；弃票计入全员人数。每人一票，不消耗决心，收齐后一起公开。" % state.required_approvals, 14, true)
		"ASSASSINATION":
			_label(actions, "谁最有可能是梅林？点击一位可选玩家的座位。", 18, true)
			if not selection.is_empty():
				_label(actions, "确认刺杀 %s？" % _name(selection[0]), 20)
				var row := _flow(actions)
				_button(row, "确认刺杀", func(): _send("assassinate", {"target": selection[0]}))
				_button(row, "取消", func(): selection.clear(); _render_seats(); _render_actions())

func _event_description(seq: int) -> String:
	for event in state.public_events:
		if int(event.seq) == seq:
			var description := "#%d — %s" % [seq, event.text]
			for message in state.get("dialogue", []):
				if int(message.seq) == seq:
					description += "\n「%s」" % message.statement
					break
			return description
	return "#%d" % seq

func _picker(parent: Node, ids: Array) -> OptionButton:
	var picker := OptionButton.new()
	picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for pid in ids:
		picker.add_item(_name(pid))
		picker.set_item_metadata(picker.item_count - 1, pid)
	parent.add_child(picker)
	return picker

func _picked(picker: OptionButton) -> String:
	return str(picker.get_selected_metadata()) if picker.selected >= 0 else ""

func _render_form() -> void:
	var form_buttons: HFlowContainer
	if form in ["SOCIAL", "RESPOND", "REACT"]:
		_label(actions, "选择落笔方式与目标", 19)
		var row := _row(actions)
		card_choice = OptionButton.new()
		for card in state.social_cards:
			card_choice.add_item(TextZh.label(card))
			card_choice.set_item_metadata(card_choice.item_count - 1, card)
		row.add_child(card_choice)
		target_choice = _picker(row, state.selection_targets)
		commit_choice = CheckBox.new()
		commit_choice.text = "加强承诺 +1"
		commit_choice.visible = form == "SOCIAL"
		commit_choice.disabled = not _available("COMMITTED_SOCIAL")
		commit_choice.tooltip_text = "总共需要 2 点决心"
		row.add_child(commit_choice)
		var writing_row := _row(actions)
		writing_input = LineEdit.new()
		writing_input.placeholder_text = "手写短句（可选，最多 240 字）"
		writing_input.max_length = 240
		writing_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		writing_row.add_child(writing_input)
		citation_choice = OptionButton.new()
		citation_choice.add_item("不附引文")
		citation_choice.set_item_metadata(0, "")
		for event in state.evidence:
			citation_choice.add_item(str(event.get("record_id", event.seq)))
			citation_choice.set_item_metadata(citation_choice.item_count - 1, str(event.get("record_id", "")))
		writing_row.add_child(citation_choice)
		form_buttons = _flow(actions)
		confirmation = _button(form_buttons, "", _submit_social)
		card_choice.item_selected.connect(func(_index: int): _social_preview())
		target_choice.item_selected.connect(func(_index: int): _social_preview())
		commit_choice.toggled.connect(func(_value: bool): _social_preview())
		_social_preview()
	elif form in ["CHALLENGE", "CITE"]:
		_label(actions, "选择质询对象与公开证据" if form == "CHALLENGE" else "选择要引用的公开证据", 19)
		var row := _row(actions)
		if form == "CHALLENGE":
			target_choice = _picker(row, state.challenge_evidence.keys())
		evidence_choice = OptionButton.new()
		evidence_choice.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		evidence_choice.clip_text = true
		row.add_child(evidence_choice)
		evidence_preview = _label(actions, "", 14, true)
		form_buttons = _flow(actions)
		confirmation = _button(form_buttons, "确认  ·  消耗 1 点决心", _submit_evidence)
		evidence_choice.item_selected.connect(func(_index: int): _evidence_preview())
		if form == "CHALLENGE":
			target_choice.item_selected.connect(func(_index: int): _fill_evidence())
		_fill_evidence()
	elif form == "REVISE":
		_label(actions, "调整队伍  ·  消耗 1 点决心", 19)
		var row := _row(actions)
		_label(row, "换下")
		var removed := _picker(row, state.proposed_team)
		_label(row, "换上")
		var outside: Array = []
		for player in state.players:
			if player.id not in state.proposed_team:
				outside.append(player.id)
		var added := _picker(row, outside)
		var preview := _label(actions, "", 15, true)
		var update := func():
			var final_team: Array = state.proposed_team.duplicate()
			final_team[final_team.find(_picked(removed))] = _picked(added)
			preview.text = "%s → %s   |   最终队伍：%s" % [_picked(removed), _picked(added), _team_text(final_team)]
		removed.item_selected.connect(func(_index: int): update.call())
		added.item_selected.connect(func(_index: int): update.call())
		update.call()
		form_buttons = _flow(actions)
		_button(form_buttons, "确认调整", func(): _send("action", {"action": {"kind": "REVISE", "removed": _picked(removed), "added": _picked(added)}}))
	_button(form_buttons, "取消", func(): _open_form(""))

func _social_preview() -> void:
	var cost := 0 if form == "REACT" else (2 if commit_choice.button_pressed else 1)
	confirmation.text = "确认%s %s  ·  共消耗 %d 点决心" % [card_choice.get_item_text(card_choice.selected), _picked(target_choice), cost]

func _submit_social() -> void:
	var kind := "COMMITTED_SOCIAL" if form == "SOCIAL" and commit_choice.button_pressed else form
	var writing := writing_input.text.strip_edges()
	if writing.is_empty():
		writing = "%s——%s。" % [_name(_picked(target_choice)), card_choice.get_item_text(card_choice.selected)]
	var rid := str(citation_choice.get_selected_metadata())
	_send("action", {"action": {"kind": kind, "social": {"card": _picked(card_choice), "target": _picked(target_choice), "reason": "human_choice", "public_writing": writing, "citations": [rid] if not rid.is_empty() else []}}})

func _fill_evidence() -> void:
	evidence_choice.clear()
	var refs: Array = state.challenge_evidence.get(_picked(target_choice), []) if form == "CHALLENGE" else []
	for event in state.evidence:
		if form == "CHALLENGE" and event.seq not in refs:
			continue
		evidence_choice.add_item("#%d  %s" % [event.seq, str(event.text).left(80)])
		evidence_choice.set_item_metadata(evidence_choice.item_count - 1, int(event.seq))
	confirmation.disabled = evidence_choice.item_count == 0
	_evidence_preview()

func _evidence_preview() -> void:
	evidence_preview.text = _event_description(int(evidence_choice.get_selected_metadata())) if evidence_choice.selected >= 0 else "没有符合条件的公开证据。"

func _submit_evidence() -> void:
	var action := {"kind": form, "evidence": int(evidence_choice.get_selected_metadata())}
	if form == "CHALLENGE":
		action.target = _picked(target_choice)
	_send("action", {"action": action})

func _render_result() -> void:
	match state.phase:
		"VOTE_RESULT":
			var result: Dictionary = state.result
			var yes := 0
			var ballots: Array[String] = []
			for ballot in result.ballots:
				yes += int(ballot.approve)
				ballots.append("%s：%s%s" % [ballot.player, "强烈" if ballot.strong else "", "赞成" if ballot.approve else "反对"])
			_label(actions, "提案%s  ·  赞成 %d 票 / 反对 %d 票" % ["通过" if result.approved else "被否决", yes, result.ballots.size() - yes], 20)
			_label(actions, "    |    ".join(ballots), 15, true)
			_button(actions, "继续", func(): _send("continue"))
		"ROUND_RESULT":
			var result: Dictionary = state.result
			_label(actions, "第 %d 次任务  ·  %s" % [result.round, "成功" if result.success else "失败"], 23)
			_label(actions, "成功：%d 张    失败：%d 张    |    善良 %s    邪恶 %s" % [result.team.size() - int(result.fail_count), result.fail_count, _score(int(state.successes)), _score(int(state.failures))], 17)
			if result.get("safe_round", false):
				_label(actions, "本轮受安全保护：队员不会因任务失败死亡。", 14)
			_button(actions, "进入任务后讨论", func(): _send("continue"))
		"EXILE_RESULT":
			var result: Dictionary = state.result
			_label(actions, "%s %s" % [_name(result.target), "出局，等待下一任务轮重生" if result.exiled else "未出局"], 20)
			_label(actions, "赞成 %d 票 / 反对 %d 票 / 弃票 %d 票    ·    须 %d 票赞成" % [result.counts.APPROVE, result.counts.REJECT, result.counts.ABSTAIN, result.required_approvals], 17)
			var ballots: Array[String] = []
			for ballot in result.ballots:
				ballots.append("%s：%s" % [ballot.player, TextZh.label(ballot.choice)])
			_label(actions, "    |    ".join(ballots), 15, true)
			_button(actions, "下一轮 · 安全任务" if int(state.successes) < 3 and int(state.failures) < 3 else "继续结算", func(): _send("continue"))
		"GAME_OVER":
			_label(actions, "%s获胜" % TextZh.label(state.winner), 28)
			_label(actions, str(state.win_reason), 18)
			var row := _flow(actions)
			_button(row, "再玩一局", func(): menu = true; _render())
			_button(row, "退出", func(): get_tree().quit())
