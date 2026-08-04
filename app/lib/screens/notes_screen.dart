import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/notes_controller.dart';

class NotesScreen extends StatefulWidget {
  const NotesScreen({super.key});

  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _submitSearch() async {
    await context.read<NotesController>().search(_search.text);
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<NotesController>();
    final Widget list;
    if (controller.loading) {
      list = const Center(child: CircularProgressIndicator());
    } else if (controller.error != null) {
      list = Center(child: Text(controller.error!));
    } else if (controller.notes.isEmpty) {
      list = Center(child: Text(controller.searching ? '没有搜到相关笔记' : '暂无笔记'));
    } else {
      list = RefreshIndicator(
        onRefresh: controller.load,
        child: ListView.builder(
          itemCount: controller.notes.length,
          itemBuilder: (_, i) {
            final note = controller.notes[i];
            return Dismissible(
              key: ValueKey('note-${note.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                color: Colors.red,
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                child: const Icon(Icons.delete, color: Colors.white),
              ),
              onDismissed: (_) => controller.remove(note),
              child: ListTile(
                leading: const Icon(Icons.note_outlined),
                title: Text(note.content, maxLines: 3, overflow: TextOverflow.ellipsis),
                subtitle: note.score != null
                    ? Text('相关度 ${note.score!.toStringAsFixed(2)}')
                    : null,
              ),
            );
          },
        ),
      );
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _search,
            decoration: InputDecoration(
              hintText: '搜索笔记（语义检索）',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: controller.searching
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _search.clear();
                        controller.search('');
                      },
                    ),
              border: const OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(20))),
              isDense: true,
            ),
            onSubmitted: (_) => _submitSearch(),
          ),
        ),
        Expanded(child: list),
      ],
    );
  }
}
