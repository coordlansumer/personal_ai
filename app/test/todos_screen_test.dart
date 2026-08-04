import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/todo.dart';
import 'package:personal_ai_app/screens/todos_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/state/todos_controller.dart';
import 'package:provider/provider.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Todo> todos = [];
  final List<int> completed = [];
  final List<int> deleted = [];

  @override
  Future<List<Todo>> listTodos({String? status}) async => List.of(todos);

  @override
  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final t = Todo(id: todos.length + 1, title: title);
    todos.insert(0, t);
    return t;
  }

  @override
  Future<void> completeTodo(int id) async {
    completed.add(id);
    final i = todos.indexWhere((t) => t.id == id);
    todos[i] = Todo(id: id, title: todos[i].title, status: 'done');
  }

  @override
  Future<void> deleteTodo(int id) async {
    deleted.add(id);
    todos.removeWhere((t) => t.id == id);
  }
}

Widget wrap(TodosController c) =>
    ChangeNotifierProvider.value(value: c, child: const MaterialApp(home: TodosScreen()));

void main() {
  testWidgets('展示待办并可完成', (tester) async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    expect(find.text('买牛奶'), findsOneWidget);
    await tester.tap(find.byType(Checkbox));
    await tester.pumpAndSettle();
    expect(api.completed, [1]);
  });

  testWidgets('滑动删除待办', (tester) async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    await tester.drag(find.text('买牛奶'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(api.deleted, [1]);
    expect(find.text('买牛奶'), findsNothing);
  });

  testWidgets('空态展示', (tester) async {
    final c = TodosController(apiClient: FakeApiClient());
    await tester.pumpWidget(wrap(c));
    expect(find.text('暂无待办'), findsOneWidget);
  });
}
