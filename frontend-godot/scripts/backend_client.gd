extends Node
class_name BackendClient

signal response_received(data: Dictionary)
signal status_changed(text: String)

const BASE_URL := "http://127.0.0.1:8765"

var _http: HTTPRequest
var _busy := false
var _backend_pid := -1
var _last_path := ""

func _ready() -> void:
    _http = HTTPRequest.new()
    _http.timeout = 90.0
    add_child(_http)
    _http.request_completed.connect(_on_request_completed)

func _exit_tree() -> void:
    if _backend_pid > 0 and OS.is_process_running(_backend_pid):
        OS.kill(_backend_pid)

func launch_backend() -> void:
    if _backend_pid > 0:
        return
    var launcher := ProjectSettings.globalize_path("res://backend_launcher.py")
    for executable in ["python3", "python"]:
        var pid := OS.create_process(executable, PackedStringArray([launcher]))
        if pid > 0:
            _backend_pid = pid
            status_changed.emit("Starting local Python backend...")
            return
    status_changed.emit("Could not start Python. Install Python 3.10+ or make python3/python available in PATH.")

func get_state() -> void:
    _send(HTTPClient.METHOD_GET, "/state", {})

func start_game(player_count: int, seed_value, human_name: String = "YOU") -> void:
    _send(HTTPClient.METHOD_POST, "/start", {
        "player_count": player_count,
        "seed": seed_value,
        "human_name": human_name,
    })

func action(payload: Dictionary) -> void:
    _send(HTTPClient.METHOD_POST, "/action", payload)

func is_busy() -> bool:
    return _busy

func _send(method: int, path: String, payload: Dictionary) -> void:
    if _busy:
        return
    _busy = true
    _last_path = path
    var headers := PackedStringArray(["Content-Type: application/json"])
    var body := "" if method == HTTPClient.METHOD_GET else JSON.stringify(payload)
    var error := _http.request(BASE_URL + path, headers, method, body)
    if error != OK:
        _busy = false
        response_received.emit({"ok": false, "error": "Could not contact local backend.", "path": path})

func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
    _busy = false
    if result != HTTPRequest.RESULT_SUCCESS:
        response_received.emit({"ok": false, "error": "Local backend is not responding.", "path": _last_path})
        return
    var parsed = JSON.parse_string(body.get_string_from_utf8())
    if typeof(parsed) != TYPE_DICTIONARY:
        response_received.emit({"ok": false, "error": "Backend returned invalid JSON.", "path": _last_path})
        return
    var data: Dictionary = parsed
    if response_code < 200 or response_code >= 300:
        data["ok"] = false
    response_received.emit(data)
