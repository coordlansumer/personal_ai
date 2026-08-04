import 'dart:convert';

sealed class ChatEvent {}

class SessionEvent extends ChatEvent {
  SessionEvent(this.sessionId);
  final String sessionId;
}

class TokenEvent extends ChatEvent {
  TokenEvent(this.content);
  final String content;
}

class ToolEvent extends ChatEvent {
  ToolEvent({required this.name, required this.arguments, required this.result});
  final String name;
  final Map<String, dynamic> arguments;
  final Map<String, dynamic> result;
}

class ErrorEvent extends ChatEvent {
  ErrorEvent(this.message);
  final String message;
}

class DoneEvent extends ChatEvent {}

ChatEvent? parseSseLine(String line) {
  if (!line.startsWith('data: ')) return null;
  final Map<String, dynamic> payload;
  try {
    payload = jsonDecode(line.substring(6)) as Map<String, dynamic>;
  } on FormatException {
    return null;
  }
  return switch (payload['type']) {
    'session' => SessionEvent(payload['session_id'] as String),
    'token' => TokenEvent(payload['content'] as String),
    'tool' => ToolEvent(
        name: payload['name'] as String,
        arguments: (payload['arguments'] as Map?)?.cast<String, dynamic>() ?? const {},
        result: (payload['result'] as Map?)?.cast<String, dynamic>() ?? const {},
      ),
    'error' => ErrorEvent(payload['message'] as String),
    'done' => DoneEvent(),
    _ => null,
  };
}
