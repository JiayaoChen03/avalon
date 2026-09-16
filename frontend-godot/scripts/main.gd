extends Control

const PlayerSeatScript = preload("res://scripts/player_seat.gd")

var backend: BackendClient
var game_state: Dictionary = {"phase": "START"}
var selected_team: Array[String] = []
var seat_buttons: Dictionary = {}
var loading := false

var status_label: Label
var phase_label: Label
var hint_label: Label
var table_grid: GridContainer
var event_log: RichTextLabel
var action_box: VBoxContainer
var error_label: Label

func _ready() -> void:
    _build_ui()
    backend = BackendClient.new()
    add_child(backend)
    backend.response_received.connect(_on_backend_response)
    backend.status_changed.connect(_on_backend_status)
    backend.launch_backend()
    await get_tree().create_timer(0.6).timeout
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
    margin.add_theme_constant_override("margin_left", 18)
    margin.add_theme_constant_override("margin_right", 18)
    margin.add_theme_constant_override("margin_top", 14)
    margin.add_theme_constant_override("margin_bottom", 14)
    add_child(margin)

    var root := VBoxContainer.new()
    root.add_theme_constant_override("separation", 12)
    margin.add_child(root)

    var top := PanelContainer.new()
    top.custom_minimum_size = Vector2(0, 82)
    root.add_child(top)
    status_label = Label.new()
    status_label.text = "AVALON — LOCAL MVP"
    status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    status_label.add_theme_font_size_override("font_size", 18)
    top.add_child(status_label)

    var split := HSplitContainer.new()
    split.size_flags_vertical = Control.SIZE_EXPAND_FILL
    split.split_offset = 850
    root.add_child(split)

    var left_panel := PanelContainer.new()
    split.add_child(left_panel)
    var left_margin := MarginContainer.new()
    left_margin.add_theme_constant_override("margin_left", 14)
    left_margin.add_theme_constant_override("margin_right", 14)
    left_margin.add_theme_constant_override("margin_top", 14)
    left_margin.add_theme_constant_override("margin_bottom", 14)
    left_panel.add_child(left_margin)
    table_grid = GridContainer.new()
    table_grid.columns = 3
    table_grid.add_theme_constant_override("h_separation", 12)
    table_grid.add_theme_constant_override("v_separation", 12)
    left_margin.add_child(table_grid)

    var right_panel := PanelContainer.new()
    right_panel.custom_minimum_size = Vector2(350, 0)
    split.add_child(right_panel)
    var right_box := VBoxContainer.new()
    right_panel.add_child(right_box)
    var log_title := Label.new()
    log_title.text = "PUBLIC EVENTS"
    log_title.add_theme_font_size_override("font_size", 16)
    right_box.add_child(log_title)
    event_log = RichTextLabel.new()
    event_log.fit_content = false
    event_log.scroll_active = true
    event_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
    event_log.bbcode_enabled = false
    right_box.add_child(event_log)

    var bottom := PanelContainer.new()
    bottom.custom_minimum_size = Vector2(0, 210)
    root.add_child(bottom)
    var bottom_margin := MarginContainer.new()
    bottom_margin.add_theme_constant_override("margin_left", 14)
    bottom_margin.add_theme_constant_override("margin_right", 14)
    bottom_margin.add_theme_constant_override("margin_top", 10)
    bottom_margin.add_theme_constant_override("margin_bottom", 10)
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
    error_label.add_theme_color_override("font_color", Color(1.0, 0.45, 0.45))
    action_box.add_child(error_label)

func _on_backend_status(text: String) -> void:
    hint_label.text = text

func _on_backend_response(data: Dictionary) -> void:
    loading = false
    if not bool(data.get("ok", false)):
        error_label.text = str(data.get("error", "Unknown backend error."))
        if str(data.get("path", "")) == "/health":
            await get_tree().create_timer(0.8).timeout
            backend.get_state()
        return
    error_label.text = ""
    if data.get("service") == "avalon-ui":
        backend.get_state()
        return
    game_state = data
    _render()

func _render() -> void:
    _render_status()
    _render_players()
    _render_events()
    _render_action_panel()

func _render_status() -> void:
    var phase := str(game_state.get("phase", "START"))
    if phase == "START":
        status_label.text = "AVALON — LOCAL MVP"
        return
    var leader := str(game_state.get("leader", ""))
    var mission := int(game_state.get("mission_round", 1))
    var attempt := int(game_state.get("proposal_attempt", 1))
    var good := int(game_state.get("good_wins", 0))
    var evil := int(game_state.get("evil_wins", 0))
    status_label.text = "MISSION %d / 5     GOOD %d / 3     EVIL %d / 3     PROPOSAL %d / 5     LEADER %s     PHASE %s" % [mission, good, evil, attempt, leader, phase]

func _clear_container(container: Container, preserve_first: int = 0) -> void:
    var children := container.get_children()
    for i in range(children.size() - 1, preserve_first - 1, -1):
        children[i].queue_free()

func _render_players() -> void:
    for child in table_grid.get_children():
        child.queue_free()
    seat_buttons.clear()
    var players: Array = game_state.get("players", [])
    var phase := str(game_state.get("phase", ""))
    var can_select := phase == "TEAM_DRAFT"
    for player in players:
        var seat := PlayerSeatScript.new()
        seat.selected_for_team = selected_team.has(str(player.get("id", "")))
        seat.configure(player, int(game_state.get("max_resolve", 3)), can_select)
        if can_select:
            seat.pressed.connect(_on_team_seat_pressed.bind(seat))
        seat_buttons[seat.player_id] = seat
        table_grid.add_child(seat)

func _render_events() -> void:
    var lines: Array[String] = []
    for event in game_state.get("public_events", []):
        lines.append("#%s  %s" % [str(event.get("seq", "?")), str(event.get("text", ""))])
    event_log.text = "\n".join(lines)
    await get_tree().process_frame
    event_log.scroll_to_line(max(0, lines.size() - 1))

func _render_action_panel() -> void:
    while action_box.get_child_count() > 3:
        action_box.get_child(3).queue_free()
    var phase := str(game_state.get("phase", "START"))
    phase_label.text = phase.replace("_", " ")
    hint_label.text = ""
    match phase:
        "START":
            _render_start()
        "ROLE_REVEAL":
            _render_role_reveal()
        "TEAM_DRAFT":
            _render_team_draft()
        "DISCUSSION":
            _render_discussion()
        "REACTION":
            _render_reaction()
        "TEAM_CONFIRM":
            _render_team_confirm()
        "VOTE":
            _render_vote()
        "MISSION":
            _render_mission()
        "ROUND_RESULT":
            _render_round_result()
        "ASSASSINATION":
            _render_assassination()
        "GAME_OVER":
            _render_game_over()
        _:
            hint_label.text = "Waiting for backend transition..."

func _render_start() -> void:
    hint_label.text = "Start a local 1 Human + AI match. Python backend and LLM configuration remain authoritative."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var count_label := Label.new()
    count_label.text = "Players"
    row.add_child(count_label)
    var count := OptionButton.new()
    count.name = "PlayerCount"
    count.add_item("5", 5)
    count.add_item("6", 6)
    row.add_child(count)
    var seed_label := Label.new()
    seed_label.text = "Optional seed"
    row.add_child(seed_label)
    var seed := LineEdit.new()
    seed.name = "Seed"
    seed.placeholder_text = "blank = random"
    seed.custom_minimum_size = Vector2(180, 0)
    row.add_child(seed)
    var start := Button.new()
    start.text = "START GAME"
    start.pressed.connect(_start_game.bind(count, seed))
    row.add_child(start)

func _render_role_reveal() -> void:
    var human: Dictionary = game_state.get("human", {})
    var role := str(human.get("role", "UNKNOWN"))
    var known: Array = human.get("known_evil", [])
    hint_label.text = "YOU ARE %s" % role
    if not known.is_empty():
        hint_label.text += "\nLegitimately known Evil seats: " + " / ".join(known)
    var button := Button.new()
    button.text = "CONTINUE"
    button.pressed.connect(_send_action.bind({"type": "CONTINUE"}))
    action_box.add_child(button)

func _render_team_draft() -> void:
    var required := int(game_state.get("team_size", 0))
    hint_label.text = "SELECT %d PLAYERS — %d / %d selected" % [required, selected_team.size(), required]
    var confirm := Button.new()
    confirm.text = "CONFIRM TEAM"
    confirm.disabled = selected_team.size() != required
    confirm.pressed.connect(_send_action.bind({"type": "SUBMIT_TEAM", "team": selected_team.duplicate()}))
    action_box.add_child(confirm)

func _render_discussion() -> void:
    var resolve_value := _human_resolve()
    hint_label.text = "Your discussion turn. Resolve %d / %d. PASS is always free." % [resolve_value, int(game_state.get("max_resolve", 3))]
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "PASS [0]", _send_action.bind({"type": "DISCUSSION", "action": "PASS"}), false)
    _add_button(row, "SOCIAL [1]", _open_social_editor.bind(false), resolve_value < 1)
    _add_button(row, "CHALLENGE [1]", _open_challenge_editor, resolve_value < 1)
    _add_button(row, "CITE [1]", _open_cite_editor, resolve_value < 1)
    _add_button(row, "HOLD [1]", _send_action.bind({"type": "DISCUSSION", "action": "HOLD"}), resolve_value < 1)

func _render_reaction() -> void:
    var trigger: Dictionary = game_state.get("reaction_trigger", {})
    hint_label.text = "Pending reaction to #%s: %s\nReaction Social Action costs no additional Resolve." % [str(trigger.get("seq", "?")), str(trigger.get("text", ""))]
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "REACT", _open_social_editor.bind(true), false)
    _add_button(row, "KEEP WAITING", _send_action.bind({"type": "REACTION", "action": "KEEP_WAITING"}), false)

func _render_team_confirm() -> void:
    var team: Array = game_state.get("proposed_team", [])
    hint_label.text = "CURRENT TEAM: " + " / ".join(team)
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "LOCK TEAM [0]", _send_action.bind({"type": "TEAM_CONFIRM", "action": "LOCK_TEAM"}), false)
    _add_button(row, "REVISE TEAM [1]", _open_revision_editor, _human_resolve() < 1)

func _render_vote() -> void:
    var team: Array = game_state.get("proposed_team", [])
    hint_label.text = "SEALED TEAM VOTE — " + " / ".join(team)
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "APPROVE [0]", _send_action.bind({"type": "VOTE", "approve": true, "strong": false}), false)
    _add_button(row, "REJECT [0]", _send_action.bind({"type": "VOTE", "approve": false, "strong": false}), false)
    _add_button(row, "STRONG APPROVE [1]", _send_action.bind({"type": "VOTE", "approve": true, "strong": true}), _human_resolve() < 1)
    _add_button(row, "STRONG REJECT [1]", _send_action.bind({"type": "VOTE", "approve": false, "strong": true}), _human_resolve() < 1)

func _render_mission() -> void:
    var human: Dictionary = game_state.get("human", {})
    hint_label.text = "Submit your secret mission action. Individual mission cards will not be shown publicly."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "SUCCESS", _send_action.bind({"type": "MISSION", "card": "SUCCESS"}), false)
    if bool(human.get("is_evil", false)):
        _add_button(row, "FAIL", _send_action.bind({"type": "MISSION", "card": "FAIL"}), false)

func _render_round_result() -> void:
    var result: Dictionary = game_state.get("latest_mission_result", {})
    var outcome := "SUCCESS" if bool(result.get("success", false)) else "FAILED"
    hint_label.text = "MISSION %d %s — SUCCESS %d / FAIL %d\nResolve refreshes to full for the next mission round." % [int(result.get("round", 0)), outcome, int(result.get("success_count", 0)), int(result.get("fail_count", 0))]
    var button := Button.new()
    button.text = "NEXT ROUND"
    button.pressed.connect(_send_action.bind({"type": "CONTINUE"}))
    action_box.add_child(button)

func _render_assassination() -> void:
    hint_label.text = "ASSASSINATION — choose who you believe is Merlin."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var picker := _player_picker(game_state.get("assassination_targets", []))
    row.add_child(picker)
    var confirm := Button.new()
    confirm.text = "CONFIRM ASSASSINATION"
    confirm.pressed.connect(_submit_assassination.bind(picker))
    row.add_child(confirm)

func _render_game_over() -> void:
    var result: Dictionary = game_state.get("game_result", {})
    hint_label.text = "%s WINS\n%s" % [str(result.get("winner", "")), str(result.get("reason", ""))]
    var row := HBoxContainer.new()
    action_box.add_child(row)
    _add_button(row, "PLAY AGAIN", _play_again, false)
    _add_button(row, "QUIT", get_tree().quit, false)

func _on_team_seat_pressed(seat: PlayerSeat) -> void:
    var pid := seat.player_id
    if selected_team.has(pid):
        selected_team.erase(pid)
        seat.set_team_selected(false)
    else:
        var required := int(game_state.get("team_size", 0))
        if selected_team.size() >= required:
            seat.set_team_selected(false)
            return
        selected_team.append(pid)
        seat.set_team_selected(true)
    _render_action_panel()

func _start_game(count_picker: OptionButton, seed_input: LineEdit) -> void:
    var count := int(count_picker.get_item_text(count_picker.selected))
    var seed_value = null
    if not seed_input.text.strip_edges().is_empty():
        if not seed_input.text.strip_edges().is_valid_int():
            error_label.text = "Seed must be an integer or blank."
            return
        seed_value = int(seed_input.text.strip_edges())
    selected_team.clear()
    _set_loading("Starting game...")
    backend.start_game(count, seed_value)

func _send_action(payload: Dictionary) -> void:
    if loading or backend.is_busy():
        return
    _set_loading("Backend is resolving the action / AI decisions...")
    backend.action(payload)

func _set_loading(text: String) -> void:
    loading = true
    error_label.text = ""
    hint_label.text = text
    for child in action_box.get_children():
        if child is Button:
            child.disabled = true

func _open_social_editor(is_reaction: bool) -> void:
    while action_box.get_child_count() > 3:
        action_box.get_child(3).queue_free()
    hint_label.text = "Choose Social Action and target."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var card := OptionButton.new()
    for value in game_state.get("social_cards", []):
        card.add_item(str(value))
    row.add_child(card)
    var target := _player_picker(_all_player_ids())
    row.add_child(target)
    var commit := CheckBox.new()
    commit.text = "COMMIT +1"
    commit.disabled = is_reaction or _human_resolve() < 2
    row.add_child(commit)
    var confirm := Button.new()
    confirm.text = "CONFIRM"
    confirm.pressed.connect(_submit_social.bind(card, target, commit, is_reaction))
    row.add_child(confirm)
    _add_button(row, "CANCEL", _render_action_panel, false)

func _submit_social(card: OptionButton, target: OptionButton, commit: CheckBox, is_reaction: bool) -> void:
    if target.item_count == 0:
        return
    var payload := {
        "type": "REACTION" if is_reaction else "DISCUSSION",
        "action": "REACT" if is_reaction else "SOCIAL",
        "card": card.get_item_text(card.selected),
        "target": target.get_item_text(target.selected),
        "commit": commit.button_pressed,
    }
    _send_action(payload)

func _open_challenge_editor() -> void:
    while action_box.get_child_count() > 3:
        action_box.get_child(3).queue_free()
    hint_label.text = "Choose a target and one eligible public event."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var targets := _all_player_ids()
    targets.erase(str(game_state.get("human", {}).get("id", "P1")))
    var target := _player_picker(targets)
    row.add_child(target)
    var evidence := _evidence_picker()
    row.add_child(evidence)
    var confirm := Button.new()
    confirm.text = "CONFIRM CHALLENGE"
    confirm.disabled = evidence.item_count == 0
    confirm.pressed.connect(_submit_challenge.bind(target, evidence))
    row.add_child(confirm)
    _add_button(row, "CANCEL", _render_action_panel, false)

func _submit_challenge(target: OptionButton, evidence: OptionButton) -> void:
    _send_action({
        "type": "DISCUSSION",
        "action": "CHALLENGE",
        "target": target.get_item_text(target.selected),
        "evidence": evidence.get_item_id(evidence.selected),
    })

func _open_cite_editor() -> void:
    while action_box.get_child_count() > 3:
        action_box.get_child(3).queue_free()
    hint_label.text = "Select one public event to cite."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var evidence := _evidence_picker()
    row.add_child(evidence)
    var confirm := Button.new()
    confirm.text = "CONFIRM CITE"
    confirm.disabled = evidence.item_count == 0
    confirm.pressed.connect(_submit_cite.bind(evidence))
    row.add_child(confirm)
    _add_button(row, "CANCEL", _render_action_panel, false)

func _submit_cite(evidence: OptionButton) -> void:
    _send_action({"type": "DISCUSSION", "action": "CITE", "evidence": evidence.get_item_id(evidence.selected)})

func _open_revision_editor() -> void:
    while action_box.get_child_count() > 3:
        action_box.get_child(3).queue_free()
    var team: Array = game_state.get("proposed_team", [])
    var non_team := _all_player_ids()
    for pid in team:
        non_team.erase(str(pid))
    hint_label.text = "Replace exactly one current team member. Discussion will not restart."
    var row := HBoxContainer.new()
    action_box.add_child(row)
    var remove := _player_picker(team)
    row.add_child(remove)
    var add := _player_picker(non_team)
    row.add_child(add)
    var confirm := Button.new()
    confirm.text = "CONFIRM REVISION [1]"
    confirm.pressed.connect(_submit_revision.bind(remove, add))
    row.add_child(confirm)
    _add_button(row, "CANCEL", _render_action_panel, false)

func _submit_revision(remove: OptionButton, add: OptionButton) -> void:
    _send_action({
        "type": "TEAM_CONFIRM",
        "action": "REVISE_TEAM",
        "remove": remove.get_item_text(remove.selected),
        "add": add.get_item_text(add.selected),
    })

func _submit_assassination(picker: OptionButton) -> void:
    if picker.item_count == 0:
        return
    _send_action({"type": "ASSASSINATE", "target": picker.get_item_text(picker.selected)})

func _play_again() -> void:
    game_state = {"phase": "START"}
    selected_team.clear()
    _render()

func _human_resolve() -> int:
    var human_id := str(game_state.get("human", {}).get("id", "P1"))
    for player in game_state.get("players", []):
        if str(player.get("id", "")) == human_id:
            return int(player.get("resolve", 0))
    return 0

func _all_player_ids() -> Array[String]:
    var ids: Array[String] = []
    for player in game_state.get("players", []):
        ids.append(str(player.get("id", "")))
    return ids

func _player_picker(ids: Array) -> OptionButton:
    var picker := OptionButton.new()
    for pid in ids:
        picker.add_item(str(pid))
    return picker

func _evidence_picker() -> OptionButton:
    var picker := OptionButton.new()
    picker.custom_minimum_size = Vector2(360, 0)
    for event in game_state.get("evidence_options", []):
        picker.add_item("#%s %s" % [str(event.get("seq", "?")), str(event.get("text", ""))], int(event.get("seq", 0)))
    return picker

func _add_button(parent: Container, label: String, callback: Callable, disabled_value: bool) -> Button:
    var button := Button.new()
    button.text = label
    button.disabled = disabled_value
    button.pressed.connect(callback)
    parent.add_child(button)
    return button
