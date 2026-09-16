extends "res://scripts/main.gd"

func _on_backend_response(data: Dictionary) -> void:
    if not bool(data.get("ok", false)) and data.has("state") and typeof(data["state"]) == TYPE_DICTIONARY:
        loading = false
        error_label.text = str(data.get("error", "Backend error."))
        var state: Dictionary = data["state"]
        var new_phase := str(state.get("phase", "START"))
        if new_phase == "TEAM_DRAFT" and last_phase != "TEAM_DRAFT":
            selected_team.clear()
        last_phase = new_phase
        game_state = state
        _render()
        return
    await super._on_backend_response(data)

func _render_actions() -> void:
    if str(game_state.get("phase", "START")) != "AI_RETRY":
        super._render_actions()
        return
    _clear_dynamic()
    phase_label.text = "AI RETRY"
    hint_label.text = "Your previous action was accepted, but a later AI decision failed. Retry only the interrupted AI transition; your action will not be submitted again."
    var legal: Array = game_state.get("legal_actions", [])
    _button(action_box, "RETRY AI", _send.bind({"type": "RETRY_AI"}), not legal.has("RETRY_AI"))
