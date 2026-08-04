import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_ai_app/services/api_client.dart';

ApiClient clientWith(String body, int status) => ApiClient(
      baseUrl: 'http://test',
      client: MockClient(
        (req) async => http.Response(body, status, headers: {'content-type': 'application/json'}),
      ),
    );

void main() {
  test('listTodos 解析列表', () async {
    final api = clientWith(
      '{"todos":[{"id":1,"title":"买牛奶","status":"pending","category":null,"due_at":null,"created_at":"2026-08-04T10:00:00+00:00","completed_at":null}],"count":1}',
      200,
    );
    final todos = await api.listTodos();
    expect(todos.single.title, '买牛奶');
  });

  test('createTodo 发送 title/category', () async {
    late http.Request captured;
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        captured = req;
        return http.Response('{"id":1,"title":"买牛奶","status":"pending","category":"购物"}', 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    await api.createTodo(title: '买牛奶', category: '购物');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/todos');
    expect(captured.body, contains('买牛奶'));
  });

  test('非 2xx 抛 ApiException 并带 detail', () async {
    final api = clientWith('{"detail":"标题不能为空"}', 400);
    expect(
      () => api.createTodo(title: ''),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '标题不能为空')),
    );
  });

  test('searchNotes 解析 hits（note_id 为字符串）', () async {
    final api = clientWith('{"hits":[{"note_id":"2","content":"明天下班买咖啡豆","score":0.87}],"count":1}', 200);
    final hits = await api.searchNotes('咖啡');
    expect(hits.single.id, 2);
    expect(hits.single.score, 0.87);
  });

  test('listNotes 解析列表', () async {
    final api = clientWith(
      '{"notes":[{"id":1,"content":"买咖啡豆","created_at":"2026-08-04T10:00:00+00:00"}],"count":1}',
      200,
    );
    final notes = await api.listNotes();
    expect(notes.single.content, '买咖啡豆');
  });

  test('deleteNote / completeTodo 打到对应路径', () async {
    final paths = <String>[];
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        paths.add('${req.method} ${req.url.path}');
        return http.Response('{"deleted":true,"id":2}', 200, headers: {'content-type': 'application/json'});
      }),
    );
    await api.deleteNote(2);
    await api.completeTodo(5);
    expect(paths, ['DELETE /api/notes/2', 'POST /api/todos/5/complete']);
  });
}
