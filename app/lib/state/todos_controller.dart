import 'package:flutter/foundation.dart';

import '../models/todo.dart';
import '../services/api_client.dart';

class TodosController extends ChangeNotifier {
  TodosController({required this.apiClient});

  final ApiClient apiClient;

  List<Todo> todos = [];
  bool loading = false;
  String? error;

  Future<void> load() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      todos = await apiClient.listTodos();
    } catch (e) {
      error = '加载失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> create(String title) async {
    await apiClient.createTodo(title: title);
    await load();
  }

  Future<void> complete(Todo todo) async {
    await apiClient.completeTodo(todo.id);
    await load();
  }

  Future<void> remove(Todo todo) async {
    todos.removeWhere((t) => t.id == todo.id);
    notifyListeners();
    var failed = false;
    try {
      await apiClient.deleteTodo(todo.id);
    } catch (_) {
      failed = true;
    }
    await load();
    if (failed) {
      error = '删除失败';
      notifyListeners();
    }
  }
}
