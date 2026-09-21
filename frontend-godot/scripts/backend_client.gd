extends Node
## Owns one private Python process. HTTP never blocks the Godot UI thread.

signal state_received(state: Dictionary)
signal connection_changed(message: String)
signal failed(message: String)
signal busy_changed(value: bool)

var state: Dictionary = {}
var busy := false
var connected := false
var process_id := -1
var connection_path := ""
var url := ""
var token := ""
var last_request: Dictionary = {}
var http: HTTPRequest
var sequence := 0

func _ready() -> void:
	http = HTTPRequest.new()
	http.timeout = 900.0 # Existing LLM retries may take minutes; the interface stays live.
	http.use_threads = true
	add_child(http)
	http.request_completed.connect(_completed)
	boot()

func boot() -> void:
	stop()
	_set_busy(true)
	connection_changed.emit("正在启动本地游戏服务…")
	var root := ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir()
	var python := OS.get_environment("AVALON_PYTHON")
	if python.is_empty():
		var local_python := root.path_join(".venv/Scripts/python.exe" if OS.get_name() == "Windows" else ".venv/bin/python")
		python = local_python if FileAccess.file_exists(local_python) else ("python" if OS.get_name() == "Windows" else "python3")
	connection_path = OS.get_user_data_dir().path_join("backend-%s-%s.json" % [OS.get_process_id(), Time.get_ticks_usec()])
	process_id = OS.create_process(python, [ProjectSettings.globalize_path("res://backend_bootstrap.py"), "--connection-file", connection_path, "--parent-pid", str(OS.get_process_id())])
	if process_id <= 0:
		_connection_failed("无法启动游戏服务。请安装 Python 3.10 或更新版本，或通过 AVALON_PYTHON 指定其位置。")
		return
	for _attempt in range(100):
		await get_tree().create_timer(0.1).timeout
		if FileAccess.file_exists(connection_path):
			var config = JSON.parse_string(FileAccess.get_file_as_string(connection_path))
			if config is Dictionary and config.has("url") and config.has("token"):
				url = config.url
				token = config.token
				connected = true
				refresh()
				return
		if not OS.is_process_running(process_id):
			break
	_connection_failed("游戏服务未能启动。请检查 Python 3.10 或更新版本及项目目录，然后重试连接。")

func refresh() -> void:
	_set_busy(true)
	var error := http.request(url + "/state", _headers())
	if error != OK:
		_connection_failed("无法连接本地游戏服务。")

func submit(command: String, payload: Dictionary = {}) -> void:
	if busy or not connected:
		return
	sequence += 1
	last_request = {"request_id": "%s-%s" % [OS.get_process_id(), sequence], "revision": state.get("revision", 0), "command": command, "payload": payload}
	_send_last()

func retry_request() -> void:
	if busy:
		return
	if last_request.is_empty():
		refresh()
	else:
		_send_last()

func _send_last() -> void:
	_set_busy(true)
	var error := http.request(url + "/command", _headers(), HTTPClient.METHOD_POST, JSON.stringify(last_request))
	if error != OK:
		_connection_failed("操作发送失败，请重试连接以恢复当前对局。")

func _headers() -> PackedStringArray:
	return PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + token])

func _completed(result: int, response_code: int, _headers_received: PackedStringArray, body: PackedByteArray) -> void:
	_set_busy(false)
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_connection_failed("本地游戏连接已中断，请重试。已提交的操作不会重复执行。")
		return
	var reply = JSON.parse_string(body.get_string_from_utf8())
	if not reply is Dictionary or not reply.get("state") is Dictionary:
		_connection_failed("游戏服务返回了无法读取的内容。")
		return
	connected = true
	state = reply.state
	connection_changed.emit("本地游戏服务已连接")
	state_received.emit(state)

func _connection_failed(message: String) -> void:
	connected = false
	_set_busy(false)
	connection_changed.emit("连接不可用")
	failed.emit(message)

func _set_busy(value: bool) -> void:
	busy = value
	busy_changed.emit(value)

func stop() -> void:
	if is_instance_valid(http):
		http.cancel_request()
	if process_id > 0 and OS.is_process_running(process_id):
		OS.kill(process_id)
	process_id = -1
	connected = false
	if not connection_path.is_empty() and FileAccess.file_exists(connection_path):
		DirAccess.remove_absolute(connection_path)

func _exit_tree() -> void:
	stop()
