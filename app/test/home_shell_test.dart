import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/home_shell.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:personal_ai_app/state/todos_controller.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget wrap() {
  final settings = SettingsService()..serverUrl = 'http://test';
  final api = ApiClient(baseUrl: 'http://test');
  final chat = ChatService(baseUrl: 'http://test');
  return MultiProvider(
    providers: [
      Provider.value(value: settings),
      Provider.value(value: api),
      Provider.value(value: chat),
      ChangeNotifierProvider(create: (_) => ChatController(chatService: chat, apiClient: api)),
      ChangeNotifierProvider(create: (_) => TodosController(apiClient: api)),
      ChangeNotifierProvider(create: (_) => NotesController(apiClient: api)),
    ],
    child: const MaterialApp(home: HomeShell()),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('底部导航切换聊天/待办/笔记', (tester) async {
    await tester.pumpWidget(wrap());
    expect(find.text('有什么可以帮你？'), findsOneWidget);

    await tester.tap(find.text('待办'));
    await tester.pumpAndSettle();
    expect(find.text('暂无待办'), findsOneWidget);

    await tester.tap(find.text('笔记'));
    await tester.pumpAndSettle();
    expect(find.text('暂无笔记'), findsOneWidget);
  });
}
