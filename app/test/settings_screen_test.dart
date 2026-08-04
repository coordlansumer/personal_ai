import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/screens/settings_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget wrap(SettingsService settings, ApiClient api, ChatService chat) => MultiProvider(
      providers: [
        Provider.value(value: settings),
        Provider.value(value: api),
        Provider.value(value: chat),
      ],
      child: const MaterialApp(home: SettingsScreen()),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('保存后更新 settings 与各 client 的 baseUrl', (tester) async {
    final settings = SettingsService();
    await settings.load();
    final api = ApiClient(baseUrl: settings.serverUrl);
    final chat = ChatService(baseUrl: settings.serverUrl);
    await tester.pumpWidget(wrap(settings, api, chat));

    await tester.enterText(find.byType(TextField), 'http://192.168.1.10:8000');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(settings.serverUrl, 'http://192.168.1.10:8000');
    expect(api.baseUrl, 'http://192.168.1.10:8000');
    expect(chat.baseUrl, 'http://192.168.1.10:8000');
  });
}
