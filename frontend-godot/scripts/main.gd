extends Control

const PlayerSeatScript = preload("res://scripts/player_seat.gd")

var backend: BackendClient
var game_state: Dictionary = {"phase": "START"}
var selected_team: Array[String] = []
var last_phase := "START"
var startup_retries := 10
var loading := false

var status_label: Label
var phase_label: Label
var hint_label: Label
var error_label: Label
var table_grid: GridContainer
var event_log: RichTextLabel
var action_box: VBoxContainer

func _ready() -> void:
    _build_ui()
    backend = BackendClient.new()
    add_child(backend)
    backend.response_received.connect(_on_backend_response)
    backend.status_changed.connect(_on_backend_status)
    backend.launch_backend()
    await get_tree().create_timer(0.5).timeout
    backend.get_state()

func _build_ui() -> void:
    set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    var bg := ColorRect.new()
    bg.color = Color(0.055, 0.062, 0.075)
    bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(bg)

    var margin := MarginContainer.new()
    margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    margin.add_theme_constant_override("margin_left", 16)
    margin.add_theme_constant_override("margin_right", 16)
    margin.add_theme_constant_override("margin_top", 16)
    margin.add_theme_constant_override("margin_bottom", 16)
    add_child(margin)

    var root := VBoxContainer.new()
    root.add_theme_constant_override("separation", 10)
    margin.add_child(root)

    var top := PanelContainer.new()
    top.custom_minimum_size = Vector2(0, 74)
    root.add_child(top)
    status_label = Label.new()
    status_label.text = "AVALON — LOCAL MVP"
    status_label.add_theme_font_size_override("font_size", 18)
    status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    top.add_child(status_label)

    var split := HSplitContainer.new()
    split.size_flags_vertical = Control.SIZE_EXPAND_FILL
    split.split_offset = 850
    root.add_child(split)

    var table_panel := PanelContainer.new()
    split.add_child(table_panel)
    var table_margin := MarginContainer.new()
    table_margin.add_theme_constant_override("margin_left", 12)
    table_margin.add_theme_constant_override("margin_right", 12)
    table_margin.add_theme_constant_override("margin_top", 12)
    table_margin.add_theme_constant_override("margin_bottom", 12)
    table_panel.add_child(table_margin)
    table_grid = GridContainer.new()
    table_grid.columns = 3
    table_grid.add_theme_constant_override("h_separation", 12)
    table_grid.add_theme_constant_override("v_separation", 12)
    table_margin.add_child(table_grid)

    var log_panel := PanelContainer.new()
    log_panel.custom_minimum_size = Vector2(350, 0)
    split.add_child(log_panel)
    var log_box := VBoxContainer.new()
    log_panel.add_child(log_box)
    var log_title := Label.new()
    log_title.text = "PUBLIC EVENTS"
    log_title.add_theme_font_size_override("font_size", 16)
    log_box.add_child(log_title)
    event_log = RichTextLabel.new()
    event_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
    event_log.scroll_active = true
    event_log.bbcode_enabled = false
    log_box.add_child(event_log)

    var bottom := PanelContainer.new()
    bottom.custom_minimum_size = Vector2(0, 220)
    root.add_child(bottom)
    var bottom_margin := MarginContainer.new()
    bottom_margin.add_theme_constant_override("margin_left", 12)
    bottom_margin.add_theme_constant_override("margin_right", 12)
    bottom_margin.add_theme_constant_override("margin_top", 12)
    bottom_margin.add_theme_constant_override("margin_bottom", 12)
    bottom.add_child(bottom_margin)
    action_box = VBoxContainer.new()
    action_box.add_theme_constant_override("separation", 8)
    bottom_margin.add_child(action_box)

    phase_label = Label.new()
    phase_label.add_theme_font_size_override("font_size", 18)
    action_box.add_child(phase_label)
    hint_label = Label.new()
    hint_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    action_box.add_child(hint_label)
    error_label = Label.new()
    error_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    error_label.add_theme_color_override("font_color", Color(1.0, 0.42, 0.42))
    action_box.add_child(error_label)

func _on_backend_status(text: String) -> void:
    hint_label.text = text

func _on_backend_response(data: Dictionary) -> void:
    loading = false
    if not bool(data.get("ok", false)):
        var path := str(data.get("path", ""))
        if path == "/state" and startup_retries > 0:
            startup_retries -= 1
            hint_label.text = "Waiting for local Python backend..."
            await get_tree().create_timer(0.5).timeout
            backend.get_state()
            return
        error_label.text = str(data.get("error", "Backend error."))
        return
    error_label.text = ""
    var new_phase := str(data.get("phase", "START"))
    if new_phase == "TEAM_DRAFT" and last_phase != "TEAM_DRAFT":
        selected_team.clear()
    last_phase = new_phase
    game_state = data
    _render()

func _render() -> void:
    _render_status()
    _render_players()
    _render_events()
    _render_actions()

func _render_status() -> void:
    var phase := str(game_state.get("phase", "START"))
    if phase == "START":
        status_label.text = "AVALON — LOCAL MVP"
        return
    status_label.text = "MISSION %d / 5     GOOD %d / 3     EVIL %d / 3     PROPOSAL %d / 5     LEADER %s     PHASE %s" % [
        int(game_state.get("mission_round", 1)), int(game_state.get("good_wins", 0)),
        int(game_state.get("evil_wins", 0)), int(game_state.get("proposal_attempt", 1)),
        str(game_state.get("leader", "")), phase]

func _render_players() -> void:
    for child in table_grid.get_children():
        table_grid.remove_child(child)
        child.queue_free()
    var selectable := str(game_state.get("phase", "")) == "TEAM_DRAFT"
    for data in game_state.get("players", []):
        var seat := PlayerSeatScript.new()
        var pid := str(data.get("id", ""))
        seat.selected_for_team = selected_team.has(pid)
        seat.configure(data, int(game_state.get("max_resolve", 3)), selectable)
        if selectable:
            seat.pressed.connect(_toggle_team.bind(seat))
        table_grid.add_child(seat)

func _render_events() -> void:
    var lines := PackedStringArray()
    for event in game_state.get("public_events", []):
        lines.append("#%s  %s" % [str(event.get("seq", "?")), str(event.get("text", ""))])
    event_log.text = "\n".join(lines)
    await get_tree().process_frame
    event_log.scroll_to_line(max(0, lines.size() - 1))

func _clear_dynamic() -> void:
    for i in range(action_box.get_child_count() - 1, 2, -1):
        var child := action_box.get_child(i)
        action_box.remove_child(child)
        child.queue_free()

func _render_actions() -> void:
    _clear_dynamic()
    var phase := str(game_state.get("phase", "START"))
    phase_label.text = phase.replace("_", " ")
    hint_label.text = ""
    match phase:
        "START": _render_start()
        "ROLE_REVEAL": _render_role_reveal()
        "TEAM_DRAFT": _render_team_draft()
        "DISCUSSION": _render_discussion()
        "CHALLENGE_RESPONSE": _render_challenge_response()
        "REACTION": _render_reaction()
        "TEAM_CONFIRM": _render_team_confirm()
        "VOTE": _render_vote()
        "MISSION": _render_mission()
        "ROUND_RESULT": _render_round_result()
        "ASSASSINATION": _render_assassination()
        "GAME_OVER": _render_game_over()
        _: hint_label.text = "Waiting for backend transition..."

func _render_start() -> void:
    hint_label.text = "Local single-player: 1 Human + AI. No terminal input is required during play."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var count := OptionButton.new()
    count.add_item("5 players")
    count.set_item_metadata(0, 5)
    count.add_item("6 players")
    count.set_item_metadata(1, 6)
    row.add_child(count)
    var seed := LineEdit.new()
    seed.placeholder_text = "optional seed"
    seed.custom_minimum_size = Vector2(180, 0)
    row.add_child(seed)
    _button(row, "START GAME", _start_game.bind(count, seed), false)

func _render_role_reveal() -> void:
    var human: Dictionary = game_state.get("human", {})
    hint_label.text = "YOU ARE %s" % str(human.get("role", "UNKNOWN"))
    var known: Array = human.get("known_evil", [])
    if not known.is_empty():
        hint_label.text += "\nKnown Evil: " + _join(known)
    _button(action_box, "CONTINUE", _send.bind({"type": "CONTINUE"}), false)

func _render_team_draft() -> void:
    var required := int(game_state.get("team_size", 0))
    hint_label.text = "SELECT %d PLAYERS — %d / %d selected" % [required, selected_team.size(), required]
    _button(action_box, "CONFIRM TEAM", _send.bind({"type": "SUBMIT_TEAM", "team": selected_team.duplicate()}), selected_team.size() != required)

func _render_discussion() -> void:
    var legal: Array = game_state.get("legal_actions", [])
    hint_label.text = "Your discussion turn. Resolve %d / %d." % [_human_resolve(), int(game_state.get("max_resolve", 3))]
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _button(row, "PASS [0]", _send.bind({"type": "DISCUSSION", "action": "PASS"}), not legal.has("PASS"))
    _button(row, "SOCIAL [1]", _social_editor.bind(false, false, false), not legal.has("SOCIAL"))
    _button(row, "SOCIAL + COMMIT [2]", _social_editor.bind(false, true, false), not legal.has("COMMITTED_SOCIAL"))
    _button(row, "CHALLENGE [1]", _challenge_editor, not legal.has("CHALLENGE"))
    _button(row, "CITE [1]", _cite_editor, not legal.has("CITE"))
    _button(row, "HOLD [1]", _send.bind({"type": "DISCUSSION", "action": "HOLD"}), not legal.has("HOLD"))

func _render_challenge_response() -> void:
    var trigger: Dictionary = game_state.get("challenge_trigger", {})
    hint_label.text = "YOU WERE CHALLENGED\n%s" % str(trigger.get("text", "Public challenge"))
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var legal: Array = game_state.get("legal_actions", [])
    _button(row, "RESPOND [1]", _social_editor.bind(true, false, false), not legal.has("RESPOND"))
    _button(row, "DECLINE [0]", _send.bind({"type": "CHALLENGE_RESPONSE", "action": "DECLINE"}), not legal.has("DECLINE"))

func _render_reaction() -> void:
    var trigger: Dictionary = game_state.get("reaction_trigger", {})
    hint_label.text = "REACTION READY — %s" % str(trigger.get("text", "Public action"))
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var legal: Array = game_state.get("legal_actions", [])
    _button(row, "REACT [0]", _social_editor.bind(false, false, true), not legal.has("REACT"))
    _button(row, "KEEP WAITING", _send.bind({"type": "REACTION", "action": "KEEP_WAITING"}), not legal.has("SKIP"))

func _render_team_confirm() -> void:
    hint_label.text = "CURRENT TEAM: " + _join(game_state.get("proposed_team", []))
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var legal: Array = game_state.get("legal_actions", [])
    _button(row, "LOCK TEAM [0]", _send.bind({"type": "TEAM_CONFIRM", "action": "LOCK_TEAM"}), not legal.has("LOCK"))
    _button(row, "REVISE TEAM [1]", _revision_editor, not legal.has("REVISE"))

func _render_vote() -> void:
    hint_label.text = "SEALED VOTE — TEAM: " + _join(game_state.get("proposed_team", []))
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var legal: Array = game_state.get("legal_actions", [])
    _button(row, "APPROVE [0]", _send.bind({"type": "VOTE", "approve": true, "strong": false}), not legal.has("VOTE"))
    _button(row, "REJECT [0]", _send.bind({"type": "VOTE", "approve": false, "strong": false}), not legal.has("VOTE"))
    _button(row, "STRONG APPROVE [1]", _send.bind({"type": "VOTE", "approve": true, "strong": true}), not legal.has("STRONG_VOTE"))
    _button(row, "STRONG REJECT [1]", _send.bind({"type": "VOTE", "approve": false, "strong": true}), not legal.has("STRONG_VOTE"))

func _render_mission() -> void:
    hint_label.text = "Submit your secret mission action. Individual mission cards stay hidden."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var legal: Array = game_state.get("legal_actions", [])
    _button(row, "SUCCESS", _send.bind({"type": "MISSION", "card": "SUCCESS"}), not legal.has("SUCCESS"))
    _button(row, "FAIL", _send.bind({"type": "MISSION", "card": "FAIL"}), not legal.has("FAIL"))

func _render_round_result() -> void:
    var result: Dictionary = game_state.get("latest_mission_result", {})
    var outcome := "SUCCESS" if bool(result.get("success", false)) else "FAILED"
    hint_label.text = "MISSION %d %s — SUCCESS %d / FAIL %d" % [int(result.get("round", 0)), outcome, int(result.get("success_count", 0)), int(result.get("fail_count", 0))]
    _button(action_box, "CONTINUE", _send.bind({"type": "CONTINUE"}), false)

func _render_assassination() -> void:
    hint_label.text = "ASSASSINATION — choose who you believe is Merlin."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var picker := _picker(game_state.get("assassination_targets", []))
    row.add_child(picker)
    _button(row, "CONFIRM", _submit_assassination.bind(picker), picker.item_count == 0)

func _render_game_over() -> void:
    var result: Dictionary = game_state.get("game_result", {})
    hint_label.text = "%s WINS\n%s" % [str(result.get("winner", "")), str(result.get("reason", ""))]
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _button(row, "PLAY AGAIN", _play_again, false)
    _button(row, "QUIT", get_tree().quit, false)

func _social_editor(challenge_response: bool = false, committed: bool = false, reaction: bool = false) -> void:
    _clear_dynamic()
    hint_label.text = "Choose Social Action and target."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var card := OptionButton.new()
    for value in game_state.get("social_cards", []):
        card.add_item(str(value))
    row.add_child(card)
    var target := _picker(_all_ids())
    row.add_child(target)
    _button(row, "CONFIRM", _submit_social.bind(card, target, challenge_response, committed, reaction), false)
    _button(row, "CANCEL", _render_actions, false)

func _submit_social(card: OptionButton, target: OptionButton, challenge_response: bool, committed: bool, reaction: bool) -> void:
    var payload := {"card": card.get_item_text(card.selected), "target": target.get_item_text(target.selected)}
    if challenge_response:
        payload.merge({"type": "CHALLENGE_RESPONSE", "action": "RESPOND"})
    elif reaction:
        payload.merge({"type": "REACTION", "action": "REACT"})
    else:
        payload.merge({"type": "DISCUSSION", "action": "SOCIAL", "commit": committed})
    _send(payload)

func _challenge_editor() -> void:
    _clear_dynamic()
    hint_label.text = "Choose a target and public evidence. Backend validation remains authoritative."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var targets := _all_ids()
    targets.erase(str(game_state.get("human", {}).get("id", "P1")))
    var target := _picker(targets)
    var evidence := _evidence_picker()
    row.add_child(target)
    row.add_child(evidence)
    _button(row, "CONFIRM CHALLENGE", _submit_challenge.bind(target, evidence), evidence.item_count == 0)
    _button(row, "CANCEL", _render_actions, false)

func _submit_challenge(target: OptionButton, evidence: OptionButton) -> void:
    _send({"type": "DISCUSSION", "action": "CHALLENGE", "target": target.get_item_text(target.selected), "evidence": evidence.get_item_id(evidence.selected)})

func _cite_editor() -> void:
    _clear_dynamic()
    hint_label.text = "Select one public event to cite."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var evidence := _evidence_picker()
    row.add_child(evidence)
    _button(row, "CONFIRM CITE", _submit_cite.bind(evidence), evidence.item_count == 0)
    _button(row, "CANCEL", _render_actions, false)

func _submit_cite(evidence: OptionButton) -> void:
    _send({"type": "DISCUSSION", "action": "CITE", "evidence": evidence.get_item_id(evidence.selected)})

func _revision_editor() -> void:
    _clear_dynamic()
    hint_label.text = "Replace exactly one current member; discussion does not restart."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var team: Array = game_state.get("proposed_team", [])
    var outside := _all_ids()
    for pid in team:
        outside.erase(str(pid))
    var remove := _picker(team)
    var add := _picker(outside)
    row.add_child(remove)
    row.add_child(add)
    _button(row, "CONFIRM REVISION [1]", _submit_revision.bind(remove, add), false)
    _button(row, "CANCEL", _render_actions, false)

func _submit_revision(remove: OptionButton, add: OptionButton) -> void:
    _send({"type": "TEAM_CONFIRM", "action": "REVISE_TEAM", "remove": remove.get_item_text(remove.selected), "add": add.get_item_text(add.selected)})

func _toggle_team(seat: PlayerSeat) -> void:
    var pid := seat.player_id
    if selected_team.has(pid):
        selected_team.erase(pid)
        seat.set_team_selected(false)
    else:
        if selected_team.size() >= int(game_state.get("team_size", 0)):
            seat.set_team_selected(false)
            return
        selected_team.append(pid)
        seat.set_team_selected(true)
    _render_actions()

func _start_game(count: OptionButton, seed: LineEdit) -> void:
    var seed_value = null
    var seed_text := seed.text.strip_edges()
    if not seed_text.is_empty():
        if not seed_text.is_valid_int():
            error_label.text = "Seed must be an integer or blank."
            return
        seed_value = int(seed_text)
    selected_team.clear()
    _loading("Starting game / preparing agents...")
    backend.start_game(int(count.get_item_metadata(count.selected)), seed_value)

func _send(payload: Dictionary) -> void:
    if loading or backend.is_busy():
        return
    _loading("Backend / AI is resolving the next transition...")
    backend.action(payload)

func _loading(text: String) -> void:
    loading = true
    error_label.text = ""
    hint_label.text = text

func _play_again() -> void:
    game_state = {"phase": "START"}
    last_phase = "START"
    selected_team.clear()
    _render()

func _submit_assassination(picker: OptionButton) -> void:
    if picker.item_count > 0:
        _send({"type": "ASSASSINATE", "target": picker.get_item_text(picker.selected)})

func _human_resolve() -> int:
    var human_id := str(game_state.get("human", {}).get("id", "P1"))
    for player in game_state.get("players", []):
        if str(player.get("id", "")) == human_id:
            return int(player.get("resolve", 0))
    return 0

func _all_ids() -> Array[String]:
    var result: Array[String] = []
    for player in game_state.get("players", []):
        result.append(str(player.get("id", "")))
    return result

func _picker(values: Array) -> OptionButton:
    var picker := OptionButton.new()
    for value in values:
        picker.add_item(str(value))
    return picker

func _evidence_picker() -> OptionButton:
    var picker := OptionButton.new()
    picker.custom_minimum_size = Vector2(390, 0)
    for event in game_state.get("evidence_options", []):
        picker.add_item("#%s %s" % [str(event.get("seq", "?")), str(event.get("text", ""))], int(event.get("seq", 0)))
    return picker

func _join(values: Array) -> String:
    var parts := PackedStringArray()
    for value in values:
        parts.append(str(value))
    return " / ".join(parts)

func _button(parent: Container, label: String, callback: Callable, disabled_value: bool) -> Button:
    var button := Button.new()
    button.text = label
    button.disabled = disabled_value
    button.pressed.connect(callback)
    parent.add_child(button)
    return button
