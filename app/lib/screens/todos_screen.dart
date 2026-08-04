import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/todos_controller.dart';

class TodosScreen extends StatefulWidget {
  const TodosScreen({super.key});

  @override
  State<TodosScreen> createState() => _TodosScreenState();
}

class _TodosScreenState extends State<TodosScreen> {
  final _titleController = TextEditingController();

  @override
  void dispose() {
    _titleController.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final controller = context.read<TodosController>();
    _titleController.clear();
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建待办'),
        content: TextField(
          controller: _titleController,
          autofocus: true,
          decoration: const InputDecoration(hintText: '待办内容'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('取消')),
          FilledButton(
            onPressed: () {
              if (_titleController.text.trim().isEmpty) return;
              Navigator.of(ctx).pop(true);
            },
            child: const Text('确定'),
          ),
        ],
      ),
    );
    final title = _titleController.text.trim();
    if (saved == true && title.isNotEmpty) {
      await controller.create(title);
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<TodosController>();
    final Widget body;
    if (controller.loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (controller.error != null) {
      body = Center(child: Text(controller.error!));
    } else if (controller.todos.isEmpty) {
      body = const Center(child: Text('暂无待办'));
    } else {
      body = RefreshIndicator(
        onRefresh: controller.load,
        child: ListView.builder(
          itemCount: controller.todos.length,
          itemBuilder: (_, i) {
            final todo = controller.todos[i];
            return Dismissible(
              key: ValueKey('todo-${todo.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                color: Colors.red,
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                child: const Icon(Icons.delete, color: Colors.white),
              ),
              onDismissed: (_) => controller.remove(todo),
              child: ListTile(
                leading: Checkbox(
                  value: todo.isDone,
                  onChanged: (_) => controller.complete(todo),
                ),
                title: Text(
                  todo.title,
                  style: todo.isDone
                      ? const TextStyle(decoration: TextDecoration.lineThrough)
                      : null,
                ),
                subtitle: [todo.category, todo.dueAt].whereType<String>().isEmpty
                    ? null
                    : Text([todo.category, todo.dueAt].whereType<String>().join(' · ')),
              ),
            );
          },
        ),
      );
    }
    return Scaffold(
      body: body,
      floatingActionButton: FloatingActionButton(
        onPressed: _add,
        tooltip: '新建待办',
        child: const Icon(Icons.add),
      ),
    );
  }
}
