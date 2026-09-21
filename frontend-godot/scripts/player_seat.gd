extends Button
## Reusable seat: consumes public state and emits ordinary button presses.

const TextZh = preload("res://scripts/text_zh.gd")

var player_id := ""

func render(player: Dictionary, selectable: bool, selected: bool, compact: bool = false) -> void:
	player_id = player.id
	custom_minimum_size = Vector2(0, 104)
	add_theme_font_size_override("font_size", 14)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	toggle_mode = false
	disabled = not selectable
	var tags: Array[String] = []
	if player.is_leader:
		tags.append("队长")
	if player.is_on_team:
		tags.append("队员")
	if player.is_active:
		tags.append("正在行动")
	if player.reaction_ready:
		tags.append("可反应")
	if selected:
		tags.append("已选 ✓")
	var amount := int(player.resolve)
	text = "%s  ·  %s\n%s · 第 %d 世%s\n决心  %s%s   %d / 3\n%s\n手写：%s" % [player.name, player.id, "真人" if player.is_human else "AI", player.get("life", 1), " · 待归来" if not player.get("alive", true) else "", "● ".repeat(amount), "○ ".repeat(3 - amount), amount, " · ".join(tags), TextZh.label(player.discussion_status)]
	tooltip_text = text
	if compact:
		custom_minimum_size = Vector2(190, 92)
		add_theme_font_size_override("font_size", 13)
		tags.erase("正在行动")
		text = "%s · %s\n第 %d 世%s\n决心 %s%s  %d/3\n%s\n%s" % [player.name, player.id, player.get("life", 1), " · 待归来" if not player.get("alive", true) else "", "●".repeat(amount), "○".repeat(3 - amount), amount, " · ".join(tags), "正在行动" if player.is_active else TextZh.label(player.discussion_status)]
	add_theme_color_override("font_disabled_color", Color("e6edf5"))
	var style := StyleBoxFlat.new()
	style.bg_color = Color("203647") if selected else Color("192435")
	style.border_color = Color("86d4bd") if selected else (Color("dcb875") if player.is_active else Color("34465e"))
	style.set_border_width_all(2 if selected or player.is_active else 1)
	style.set_corner_radius_all(7)
	style.content_margin_left = 8
	style.content_margin_right = 8
	add_theme_stylebox_override("normal", style)
	add_theme_stylebox_override("disabled", style)
	var hover := style.duplicate()
	hover.bg_color = Color("2b4157")
	add_theme_stylebox_override("hover", hover)
