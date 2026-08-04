import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/chat_message.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/models/todo.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:personal_ai_app/state/todos_controller.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Todo> todos = [];
  final List<Note> notes = [];
  final List<String> noteContents = [];
  bool failLoad = false;

  @override
  Future<List<Todo>> listTodos({String? status}) async {
    if (failLoad) throw ApiException('服务器不可用');
    return List.of(todos);
  }

  @override
  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final t = Todo(id: todos.length + 1, title: title);
    todos.add(t);
    return t;
  }

  @override
  Future<void> completeTodo(int id) async {
    final i = todos.indexWhere((t) => t.id == id);
    todos[i] = Todo(id: id, title: todos[i].title, status: 'done');
  }

  @override
  Future<void> deleteTodo(int id) async {
    todos.removeWhere((t) => t.id == id);
  }

  @override
  Future<List<Note>> listNotes() async => List.of(notes);

  @override
  Future<List<Note>> searchNotes(String query, {int topK = 5}) async =>
      notes.where((n) => n.content.contains(query)).toList();

  @override
  Future<void> deleteNote(int id) async {
    notes.removeWhere((n) => n.id == id);
  }

  @override
  Future<void> createNote(String content) async {
    noteContents.add(content);
  }
}

class FakeChatService extends ChatService {
  FakeChatService(this._events) : super(baseUrl: 'http://test');

  final List<ChatEvent> _events;
  String? lastMessage;
  String? lastSession;

  @override
  Stream<ChatEvent> stream(String message, String? sessionId) async* {
    lastMessage = message;
    lastSession = sessionId;
    yield* Stream.fromIterable(_events);
  }
}

void main() {
  test('TodosController 加载与错误态', () async {
    final api = FakeApiClient();
    final c = TodosController(apiClient: api);
    await c.load();
    expect(c.todos, isEmpty);
    expect(c.error, isNull);

    api.failLoad = true;
    await c.load();
    expect(c.error, isNotNull);
  });

  test('TodosController 完成与删除', () async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await c.complete(c.todos.single);
    expect(c.todos.single.isDone, isTrue);
    await c.remove(c.todos.single);
    expect(c.todos, isEmpty);
  });

  test('ChatController 把事件流组装成气泡', () async {
    final api = FakeApiClient();
    final service = FakeChatService([
      SessionEvent('sid-1'),
      TokenEvent('你'),
      TokenEvent('好'),
      ToolEvent(name: 'now', arguments: const {}, result: const {'datetime': '2026-08-04'}),
      DoneEvent(),
    ]);
    final c = ChatController(chatService: service, apiClient: api);
    await c.send('现在几点');
    expect(service.lastMessage, '现在几点');
    expect(service.lastSession, isNull);
    expect(c.sessionId, 'sid-1');
    expect(c.bubbles[1].content, '你好');
    expect(c.bubbles.any((b) => b.kind == BubbleKind.tool && b.name == 'now'), isTrue);
    expect(c.streaming, isFalse);
  });

  test('ChatController 错误事件变错误气泡', () async {
    final api = FakeApiClient();
    final c = ChatController(
      chatService: FakeChatService([ErrorEvent('无法连接服务器')]),
      apiClient: api,
    );
    await c.send('hi');
    expect(c.bubbles.last.kind, BubbleKind.error);
  });

  test('ChatController 记录笔记', () async {
    final api = FakeApiClient();
    final c = ChatController(chatService: FakeChatService([]), apiClient: api);
    await c.saveNote('买咖啡豆');
    expect(api.noteContents, ['买咖啡豆']);
  });

  test('NotesController 搜索与清空', () async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '明天下班买咖啡豆'));
    api.notes.add(Note(id: 2, content: '开会记录'));
    final c = NotesController(apiClient: api);
    await c.load();
    expect(c.notes.length, 2);
    await c.search('咖啡');
    expect(c.notes.single.id, 1);
    await c.search('');
    expect(c.notes.length, 2);
  });
}
