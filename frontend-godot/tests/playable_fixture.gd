extends SceneTree
## Interactive end-to-end test. The title explicitly identifies the test model.

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	if not OS.get_environment("AVALON_PYTHON").ends_with("gui_test_python.sh"):
		push_error("This test requires AVALON_PYTHON=.../tests/gui_test_python.sh")
		quit(1)
		return
	root.title = "阿瓦隆界面验证 — 测试模型"
	root.add_child(load("res://scenes/main.tscn").instantiate())
