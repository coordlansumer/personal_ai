import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/screens/notes_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:provider/provider.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Note> notes = [];
  final List<int> deleted = [];
  String? lastQuery;
  bool failLoad = false;

  @override
  Future<List<Note>> listNotes() async {
    if (failLoad) throw ApiException('服务器不可用');
    return List.of(notes);
  }

  @override
  Future<List<Note>> searchNotes(String query, {int topK = 5}) async {
    lastQuery = query;
    return notes.where((n) => n.content.contains(query)).toList();
  }

  @override
  Future<void> deleteNote(int id) async {
    deleted.add(id);
    notes.removeWhere((n) => n.id == id);
  }
}

Widget wrap(NotesController c) =>
    ChangeNotifierProvider.value(value: c, child: const MaterialApp(home: Scaffold(body: NotesScreen())));

void main() {
  testWidgets('展示笔记并搜索过滤', (tester) async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '明天下班买咖啡豆'));
    api.notes.add(Note(id: 2, content: '开会记录'));
    final c = NotesController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    expect(find.textContaining('买咖啡豆'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '咖啡');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(api.lastQuery, '咖啡');
    expect(find.textContaining('买咖啡豆'), findsOneWidget);
    expect(find.textContaining('开会记录'), findsNothing);
  });

  testWidgets('错误态显示重试按钮并可重载', (tester) async {
    final api = FakeApiClient()..failLoad = true;
    final c = NotesController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    expect(find.textContaining('加载失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);

    api.failLoad = false;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('暂无笔记'), findsOneWidget);
  });

  testWidgets('滑动删除笔记', (tester) async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '买咖啡豆'));
    final c = NotesController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    await tester.drag(find.textContaining('买咖啡豆'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(api.deleted, [1]);
    expect(find.textContaining('买咖啡豆'), findsNothing);
  });
}
