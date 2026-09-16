extends Button
class_name PlayerSeat

var player_id := ""
var selected_for_team := false

func configure(data: Dictionary, max_resolve: int, selectable: bool = false) -> void:
    player_id = str(data.get("id", ""))
    disabled = not selectable
    toggle_mode = selectable
    button_pressed = selected_for_team if selectable else false

    var name := str(data.get("name", player_id))
    var tags: Array[String] = []
    if bool(data.get("is_human", false)):
        tags.append("HUMAN")
    else:
        tags.append("AI")
    if bool(data.get("is_leader", false)):
        tags.append("LEADER")
    if bool(data.get("is_on_team", false)):
        tags.append("TEAM")
    if bool(data.get("is_active", false)):
        tags.append("ACTIVE")
    if bool(data.get("discussion_done", false)):
        tags.append("DONE")

    var resolve_value := int(data.get("resolve", 0))
    var dots := ""
    for i in range(max_resolve):
        dots += "●" if i < resolve_value else "○"
        if i < max_resolve - 1:
            dots += " "
    text = "%s\n%s\nResolve %s  %d/%d" % [name, " · ".join(tags), dots, resolve_value, max_resolve]
    custom_minimum_size = Vector2(190, 100)

func set_team_selected(value: bool) -> void:
    selected_for_team = value
    button_pressed = value
