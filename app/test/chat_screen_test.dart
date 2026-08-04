import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/screens/chat_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:provider/provider.dart';

class FakeChatService extends ChatService {
  FakeChatService(this._events) : super(baseUrl: 'http://test');

  final List<ChatEvent> _events;

  @override
  Stream<ChatEvent> stream(String message, String? sessionId) => Stream.fromIterable(_events);
}

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<String> notes = [];

  @override
  Future<void> createNote(String content) async => notes.add(content);
}

Widget wrap(ChatController controller) => ChangeNotifierProvider.value(
      value: controller,
      child: const MaterialApp(home: Scaffold(body: ChatScreen())),
    );

void main() {
  testWidgets('发送后展示用户气泡、AI 气泡与工具卡片', (tester) async {
    final api = FakeApiClient();
    final controller = ChatController(
      chatService: FakeChatService([
        SessionEvent('sid-1'),
        TokenEvent('现在'),
        TokenEvent('是 12:00'),
        ToolEvent(name: 'now', arguments: const {}, result: const {'datetime': '2026-08-04T12:00:00'}),
        DoneEvent(),
      ]),
      apiClient: api,
    );
    await tester.pumpWidget(wrap(controller));

    await tester.enterText(find.byType(TextField), '现在几点');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    expect(find.text('现在几点'), findsOneWidget);
    expect(find.textContaining('现在是 12:00'), findsOneWidget);
    expect(find.textContaining('工具调用'), findsOneWidget);
    expect(find.textContaining('now'), findsOneWidget);
  });

  testWidgets('记笔记按钮把输入写入后端并提示', (tester) async {
    final api = FakeApiClient();
    final controller = ChatController(chatService: FakeChatService([]), apiClient: api);
    await tester.pumpWidget(wrap(controller));

    await tester.enterText(find.byType(TextField), '买咖啡豆');
    await tester.tap(find.byIcon(Icons.note_add_outlined));
    await tester.pumpAndSettle();

    expect(api.notes, ['买咖啡豆']);
    expect(find.text('已记录到笔记'), findsOneWidget);
  });
}
