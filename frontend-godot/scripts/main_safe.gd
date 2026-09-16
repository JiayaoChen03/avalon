extends "res://scripts/main.gd"

var _startup_retries := 8

func _on_backend_response(data: Dictionary) -> void:
    if not bool(data.get("ok", false)) and str(data.get("path", "")) == "/state" and _startup_retries > 0:
        loading = false
        _startup_retries -= 1
        error_label.text = ""
        hint_label.text = "Waiting for local Python backend..."
        await get_tree().create_timer(0.5).timeout
        backend.get_state()
        return
    super._on_backend_response(data)

func _clear_dynamic_controls() -> void:
    for i in range(action_box.get_child_count() - 1, 2, -1):
        var child := action_box.get_child(i)
        action_box.remove_child(child)
        child.queue_free()

func _render_action_panel() -> void:
    _clear_dynamic_controls()
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

func _open_social_editor(is_reaction: bool) -> void:
    _clear_dynamic_controls()
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

func _open_challenge_editor() -> void:
    _clear_dynamic_controls()
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

func _open_cite_editor() -> void:
    _clear_dynamic_controls()
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

func _open_revision_editor() -> void:
    _clear_dynamic_controls()
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
