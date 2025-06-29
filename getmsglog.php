<?php
$config = json_decode(file_get_contents(__DIR__ . '/config.json'), true);
$API_KEY = $config['php']['api_key'];
$logfile = "messages.json";
if ($_SERVER['HTTP_X_API_KEY'] !== $API_KEY) {
    http_response_code(403);
    echo json_encode(["error" => "Unauthorized"]);
    exit;
}
$data = file_get_contents('php://input');
if (!$data) {
    http_response_code(400);
    echo json_encode(["error" => "No data"]);
    exit;
}
$json = json_decode($data, true);
if (!$json) {
    http_response_code(400);
    echo json_encode(["error" => "Invalid JSON"]);
    exit;
}
$messages = [];
if (file_exists($logfile)) {
    $messages = json_decode(file_get_contents($logfile), true);
    if (!is_array($messages)) $messages = [];
}
$messages[] = $json;
file_put_contents($logfile, json_encode($messages, JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT));
echo json_encode(["status" => "ok"]);
?>
