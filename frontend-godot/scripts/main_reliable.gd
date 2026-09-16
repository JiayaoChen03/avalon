extends "res://scripts/main.gd"

func _on_backend_response(data: Dictionary) -> void:
    if not bool(data.get("ok", false)) and typeof(data.get("state")) == TYPE_DICTIONARY:
        loading = false
        game_state = data["state"]
        last_phase = str(game_state.get("phase", last_phase))
        error_label.text = str(data.get("error", "AI transition failed."))
        _render()
        return
    super._on_backend_response(data)

func _render_actions() -> void:
    if str(game_state.get("phase", "")) != "AI_RETRY":
        super._render_actions()
        return
    _clear_dynamic()
    phase_label.text = "AI RETRY"
    hint_label.text = "The previous human action was accepted, but the following AI transition failed. Retry resumes from the authoritative backend state; it does not submit your action again."
    _button(action_box, "RETRY AI", _send.bind({"type": "RETRY_AI"}), false)
