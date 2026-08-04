import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/note.dart';
import '../models/todo.dart';

class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required this.baseUrl, http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String baseUrl;

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl/api$path').replace(queryParameters: query);

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
  }) async {
    final req = http.Request(method, _uri(path, query));
    if (body != null) {
      req.headers['content-type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final streamed = await _client.send(req);
    final res = await http.Response.fromStream(streamed);
    final decoded = res.body.isEmpty
        ? <String, dynamic>{}
        : (jsonDecode(res.body) as Map<String, dynamic>?) ?? <String, dynamic>{};
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final detail = decoded['detail'];
      throw ApiException(detail is String ? detail : '请求失败 (${res.statusCode})');
    }
    return decoded;
  }

  Future<List<Todo>> listTodos({String? status}) async {
    final data = await _send('GET', '/todos',
        query: status != null ? {'status': status} : null);
    return (data['todos'] as List)
        .map((e) => Todo.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final data = await _send('POST', '/todos', body: {
      'title': title,
      'due_at': ?dueAt,
      'category': ?category,
    });
    return Todo.fromJson(data);
  }

  Future<void> completeTodo(int id) => _send('POST', '/todos/$id/complete');
  Future<void> deleteTodo(int id) => _send('DELETE', '/todos/$id');

  Future<List<Note>> listNotes() async {
    final data = await _send('GET', '/notes');
    return (data['notes'] as List)
        .map((e) => Note.fromListJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<Note>> searchNotes(String query, {int topK = 5}) async {
    final data = await _send('GET', '/notes/search', query: {'q': query, 'top_k': '$topK'});
    return (data['hits'] as List)
        .map((e) => Note.fromSearchJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> deleteNote(int id) => _send('DELETE', '/notes/$id');
  Future<void> createNote(String content) => _send('POST', '/notes', body: {'content': content});
}
