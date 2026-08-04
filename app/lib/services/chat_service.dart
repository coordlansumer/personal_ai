import 'dart:convert';
import 'dart:io';

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

class ChatService {
  ChatService({required this.baseUrl});

  String baseUrl;

  Stream<ChatEvent> stream(String message, String? sessionId) async* {
    final client = HttpClient();
    try {
      final req = await client.postUrl(Uri.parse('$baseUrl/api/chat'));
      req.headers.contentType = ContentType.json;
      req.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
      req.write(jsonEncode({'message': message, 'session_id': sessionId}));
      final res = await req.close();
      if (res.statusCode != 200) {
        final body = await utf8.decoder.bind(res).join();
        var detail = '服务器错误 (${res.statusCode})';
        try {
          final decoded = jsonDecode(body) as Map<String, dynamic>;
          if (decoded['detail'] is String) detail = decoded['detail'] as String;
        } on FormatException {
          // ignore: keep default detail
        }
        yield ErrorEvent(detail);
        return;
      }
      final lines = res.transform(utf8.decoder).transform(const LineSplitter());
      await for (final line in lines) {
        final ev = parseSseLine(line);
        if (ev != null) yield ev;
      }
    } on SocketException catch (e) {
      yield ErrorEvent('无法连接服务器: ${e.message}');
    } on HttpException catch (e) {
      yield ErrorEvent('请求失败: ${e.message}');
    } finally {
      client.close(force: true);
    }
  }
}
