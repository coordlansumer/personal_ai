import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/chat_message.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/models/todo.dart';

void main() {
  test('Todo.fromJson 映射后端字段', () {
    final t = Todo.fromJson({
      'id': 1,
      'title': '买牛奶',
      'status': 'pending',
      'category': '购物',
      'due_at': '2026-08-05T15:00:00+08:00',
      'created_at': '2026-08-04T10:00:00+00:00',
      'completed_at': null,
    });
    expect(t.id, 1);
    expect(t.title, '买牛奶');
    expect(t.status, 'pending');
    expect(t.category, '购物');
    expect(t.dueAt, '2026-08-05T15:00:00+08:00');
    expect(t.isDone, isFalse);
  });

  test('Note.fromListJson', () {
    final n = Note.fromListJson({
      'id': 2,
      'content': '买咖啡豆',
      'created_at': '2026-08-04T10:00:00+00:00',
    });
    expect(n.id, 2);
    expect(n.content, '买咖啡豆');
    expect(n.score, isNull);
  });

  test('Note.fromSearchJson 用 note_id', () {
    final n = Note.fromSearchJson({'note_id': '2', 'content': '明天下班买咖啡豆', 'score': 0.87});
    expect(n.id, 2);
    expect(n.score, 0.87);
  });

  test('ChatBubble 各 kind', () {
    expect(ChatBubble(kind: BubbleKind.user, content: 'hi').kind, BubbleKind.user);
    final tool = ChatBubble(kind: BubbleKind.tool, name: 'now', arguments: const {}, result: const {'datetime': 'x'});
    expect(tool.name, 'now');
    expect(tool.result, const {'datetime': 'x'});
  });
}
